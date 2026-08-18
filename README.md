# 🎓 Student Manager — Flask + DynamoDB CRUD App

A simple CRUD web application for managing student records, built with **Flask** and **AWS DynamoDB**. Designed for a university cloud computing assignment.

## Architecture

```
Browser  ──►  Flask (app.py)  ──►  AWS DynamoDB ("Students" table)
                  │
                  └── templates/index.html (single-page frontend)
```

## Prerequisites

- Python 3.8+
- AWS account with DynamoDB access
- If running on EC2: an IAM role with `dynamodb:*` permissions on the `Students` table
- If running locally: AWS credentials configured (`aws configure`)

> ⚠️ **No hardcoded AWS keys** — the app uses boto3's default credential chain (IAM role, environment variables, or `~/.aws/credentials`).

## Project Structure

```
.
├── app.py              # Flask CRUD REST API
├── create_table.py     # Script to create the DynamoDB table
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html      # Frontend HTML/CSS/JS
└── README.md           # This file
```

## Setup & Running

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create the DynamoDB table

```bash
python3 create_table.py
```

This creates a `Students` table with On-Demand billing and `student_id` (String) as the partition key. It's safe to run multiple times — it will skip if the table already exists.

### 3. Run the app

```bash
python3 app.py
```

The app starts on **http://0.0.0.0:5000**.

- Open `http://<your-ec2-public-ip>:5000` in a browser for the web UI.
- Or use the REST API with `curl` (see below).

## Student Schema

| Field        | DynamoDB Type | Description                        |
|-------------|---------------|------------------------------------|
| `student_id` | String (S)   | Partition key — auto-generated UUID |
| `name`       | String (S)   | Student's full name                |
| `age`        | Number (N)   | Student's age                      |
| `is_active`  | Boolean (BOOL)| Whether the student is active     |
| `subjects`   | List (L)     | List of subject names (strings)    |
| `address`    | Map (M)      | Object with `city` and `pin`       |

## REST API — Example curl Commands

### Create a student (POST)

```bash
curl -X POST http://localhost:5000/students \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Alice Smith",
    "age": 21,
    "is_active": true,
    "subjects": ["Math", "Physics", "CS"],
    "address": {"city": "Bangalore", "pin": "560001"}
  }'
```

### List all students (GET)

```bash
curl http://localhost:5000/students
```

### Get a student by ID (GET)

```bash
curl http://localhost:5000/students/<student_id>
```

### Update a student (PUT)

```bash
curl -X PUT http://localhost:5000/students/<student_id> \
  -H "Content-Type: application/json" \
  -d '{
    "age": 22,
    "is_active": false,
    "subjects": ["Math", "AI"],
    "address": {"city": "Mumbai", "pin": "400001"}
  }'
```

### Delete a student (DELETE)

```bash
curl -X DELETE http://localhost:5000/students/<student_id>
```

## DynamoDB Credential Note

This application uses **boto3's default credential chain**. When running on an EC2 instance, attach an IAM role with the appropriate DynamoDB permissions. No access keys or secrets are hardcoded in the source code.

Example IAM policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "dynamodb:*",
      "Resource": "arn:aws:dynamodb:us-east-1:*:table/Students"
    }
  ]
}
```

## License

This project is for educational purposes.
