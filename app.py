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
    Return the item as a plain dict suitable for JSON.

    The boto3 Table resource already unmarshals DynamoDB AttributeValue
    descriptors into native Python types (str, int, bool, list, dict),
    so items from scan/get_item are already plain Python dicts.

    This function is kept as a safety net: if a value somehow still
    carries a DynamoDB type descriptor (e.g. {"S": "..."}), we unwrap it.
    """
    # DynamoDB type-descriptor tags used by the low-level API
    _ddb_types = ("S", "N", "BOOL", "L", "M")

    def _unwrap(value):
        """Recursively unwrap a single value if it looks like a descriptor."""
        if isinstance(value, dict) and len(value) == 1:
            tag = next(iter(value))
            if tag in _ddb_types:
                inner = value[tag]
                if tag == "S":
                    return inner
                elif tag == "N":
                    return int(inner) if isinstance(inner, str) and inner.isdigit() else float(inner)
                elif tag == "BOOL":
                    return inner
                elif tag == "L":
                    return [_unwrap(v) for v in inner]
                elif tag == "M":
                    return serialize_item(inner)
        if isinstance(value, dict):
            return {k: _unwrap(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_unwrap(v) for v in value]
        return value

    return {k: _unwrap(v) for k, v in item.items()}


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
    Build a DynamoDB-ready item using Python-native values.

    The boto3 Table resource API automatically marshals native Python
    types into DynamoDB AttributeValue descriptors, so we should NOT
    wrap values in {"S": ...}, {"N": ...}, etc. manually.
    """
    item = {
        "student_id": student_id,
        "name": data["name"],
        "age": data["age"],
        "is_active": data.get("is_active", True),
        "subjects": data.get("subjects", []),
        "address": {
            "city": data.get("address", {}).get("city", ""),
            "pin": data.get("address", {}).get("pin", ""),
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

    for field_name in ["name", "age", "is_active", "subjects", "address"]:
        if field_name in data:
            attr_name = f"#{field_name}"
            attr_val = f":{field_name}"
            expr_attr_names[attr_name] = field_name

            # Use Python-native values — the Table resource auto-marshals them.
            if field_name == "address":
                expr_attr_values[attr_val] = {
                    "city": data[field_name].get("city", ""),
                    "pin": data[field_name].get("pin", ""),
                }
            else:
                expr_attr_values[attr_val] = data[field_name]

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
