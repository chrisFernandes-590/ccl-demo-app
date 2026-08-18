#!/usr/bin/env python3
"""
app.py
Flask CRUD REST API for the "Student Manager" application.
Uses AWS DynamoDB as the backend — credentials come from the
EC2 instance IAM role (boto3 default credential chain).

Endpoints:
    POST   /students           → Create a student
    GET    /students           → List all students
    GET    /students/<id>      → Get a student by ID
    PUT    /students/<id>      → Update a student
    DELETE /students/<id>      → Delete a student
    GET    /                   → Serve the frontend HTML page
"""

import uuid
import boto3
from flask import Flask, request, jsonify, render_template
from botocore.exceptions import ClientError

app = Flask(__name__)

# DynamoDB resource — uses default credential chain (IAM role, env vars, etc.)
# No hardcoded AWS keys!
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
table = dynamodb.Table("Students")


# ---------------------------------------------------------------------------
# Helper: serialise DynamoDB types to plain Python / JSON-friendly dicts
# ---------------------------------------------------------------------------

def serialize_item(item):
    """
    Convert a DynamoDB item dict into a plain dict suitable for JSON.
    Handles String (S), Number (N), Boolean (BOOL), List (L), and Map (M).
    """
    result = {}
    for key, value in item.items():
        if "S" in value:
            result[key] = value["S"]
        elif "N" in value:
            result[key] = int(value["N"]) if value["N"].isdigit() else float(value["N"])
        elif "BOOL" in value:
            result[key] = value["BOOL"]
        elif "L" in value:
            result[key] = [serialize_item(v) if isinstance(v, dict) else v for v in value["L"]]
        elif "M" in value:
            result[key] = serialize_item(value["M"])
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------

def validate_student(data, partial=False):
    """
    Validate incoming student data.
    If partial=True, only the fields that are present are validated
    (used for PUT / update operations).
    Returns (cleaned_data, error_message).
    """
    if not data:
        return None, "Request body must be JSON."

    errors = []

    # name — required on create
    if not partial or "name" in data:
        if not data.get("name") or not isinstance(data["name"], str):
            errors.append("'name' must be a non-empty string.")

    # age — required on create
    if not partial or "age" in data:
        age = data.get("age")
        if age is None:
            errors.append("'age' is required.")
        elif not isinstance(age, int) or age < 0 or age > 150:
            errors.append("'age' must be a valid integer between 0 and 150.")

    # is_active — optional, but must be bool if provided
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            errors.append("'is_active' must be a boolean.")

    # subjects — optional, must be list of strings if provided
    if "subjects" in data:
        if not isinstance(data["subjects"], list):
            errors.append("'subjects' must be a list.")
        elif not all(isinstance(s, str) for s in data["subjects"]):
            errors.append("Every element in 'subjects' must be a string.")

    # address — optional, must be dict with "city" and "pin" if provided
    if "address" in data:
        addr = data["address"]
        if not isinstance(addr, dict):
            errors.append("'address' must be an object (map).")
        else:
            if not isinstance(addr.get("city", ""), str):
                errors.append("'address.city' must be a string.")
            if not isinstance(addr.get("pin", ""), str):
                errors.append("'address.pin' must be a string.")

    if errors:
        return None, "; ".join(errors)
    return data, None


def build_put_item(student_id, data):
    """
    Build a DynamoDB-ready item dict from validated Python values.
    Uses explicit DynamoDB type descriptors (S, N, BOOL, L, M).
    """
    item = {
        "student_id": {"S": student_id},
        "name": {"S": data["name"]},
        "age": {"N": str(data["age"])},
        "is_active": {"BOOL": data.get("is_active", True)},
        "subjects": {"L": [{"S": s} for s in data.get("subjects", [])]},
        "address": {
            "M": {
                "city": {"S": data.get("address", {}).get("city", "")},
                "pin": {"S": data.get("address", {}).get("pin", "")},
            }
        },
    }
    return item


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the single-page frontend."""
    return render_template("index.html")


@app.route("/students", methods=["POST"])
def create_student():
    """Create a new student. Returns 201 on success."""
    data, error = validate_student(request.get_json())
    if error:
        return jsonify({"error": error}), 400

    # Generate a unique student_id
    student_id = str(uuid.uuid4())

    item = build_put_item(student_id, data)
    table.put_item(Item=item)

    created = serialize_item(item)
    return jsonify({"message": "Student created.", "student": created}), 201


@app.route("/students", methods=["GET"])
def list_students():
    """Return all students in the table."""
    response = table.scan()
    items = [serialize_item(item) for item in response.get("Items", [])]
    # Sort by name for consistent display
    items.sort(key=lambda x: x.get("name", ""))
    return jsonify(items), 200


@app.route("/students/<student_id>", methods=["GET"])
def get_student(student_id):
    """Fetch a single student by ID. Returns 404 if not found."""
    response = table.get_item(Key={"student_id": student_id})
    item = response.get("Item")
    if not item:
        return jsonify({"error": "Student not found."}), 404

    return jsonify(serialize_item(item)), 200


@app.route("/students/<student_id>", methods=["PUT"])
def update_student(student_id):
    """
    Update a student. Only the fields provided in the body are updated.
    Returns 404 if the student doesn't exist.
    """
    data, error = validate_student(request.get_json(), partial=True)
    if error:
        return jsonify({"error": error}), 400

    # Check if the student exists first
    existing = table.get_item(Key={"student_id": student_id})
    if "Item" not in existing:
        return jsonify({"error": "Student not found."}), 404

    # Build an UpdateExpression dynamically
    update_expr_parts = []
    expr_attr_names = {}
    expr_attr_values = {}

    field_map = {
        "name": ("name", "S"),
        "age": ("age", "N"),
        "is_active": ("is_active", "BOOL"),
        "subjects": ("subjects", "L"),
        "address": ("address", "M"),
    }

    for field_name in ["name", "age", "is_active", "subjects", "address"]:
        if field_name in data:
            attr_name = f"#{field_name}"
            attr_val = f":{field_name}"
            expr_attr_names[attr_name] = field_name

            if field_name == "age":
                expr_attr_values[attr_val] = {"N": str(data[field_name])}
            elif field_name == "subjects":
                expr_attr_values[attr_val] = {"L": [{"S": s} for s in data[field_name]]}
            elif field_name == "address":
                expr_attr_values[attr_val] = {
                    "M": {
                        "city": {"S": data[field_name].get("city", "")},
                        "pin": {"S": data[field_name].get("pin", "")},
                    }
                }
            else:
                # name (S) and is_active (BOOL) — pass through as-is with boto3 marshalling
                expr_attr_values[attr_val] = {field_map[field_name][1]: data[field_name]}

            update_expr_parts.append(f"{attr_name} = {attr_val}")

    if not update_expr_parts:
        return jsonify({"error": "No valid fields provided for update."}), 400

    update_expression = "SET " + ", ".join(update_expr_parts)

    table.update_item(
        Key={"student_id": student_id},
        UpdateExpression=update_expression,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )

    # Return the updated student
    updated = table.get_item(Key={"student_id": student_id})
    return jsonify({
        "message": "Student updated.",
        "student": serialize_item(updated["Item"]),
    }), 200


@app.route("/students/<student_id>", methods=["DELETE"])
def delete_student(student_id):
    """Delete a student. Returns 404 if not found."""
    existing = table.get_item(Key={"student_id": student_id})
    if "Item" not in existing:
        return jsonify({"error": "Student not found."}), 404

    table.delete_item(Key={"student_id": student_id})
    return jsonify({"message": "Student deleted."}), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Run on 0.0.0.0 so it's accessible from outside the EC2 instance
    app.run(host="0.0.0.0", port=5000, debug=True)
