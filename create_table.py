#!/usr/bin/env python3
"""
create_table.py
Creates the "Students" DynamoDB table if it doesn't already exist.
Uses On-Demand (PAY_PER_REQUEST) billing mode and boto3's default
credential chain (e.g., EC2 instance IAM role — no hardcoded keys).
"""

import boto3
from botocore.exceptions import ClientError


def create_students_table():
    """Create the Students table in DynamoDB (idempotent)."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    try:
        table = dynamodb.create_table(
            TableName="Students",
            KeySchema=[
                {
                    "AttributeName": "student_id",
                    "KeyType": "HASH",  # Partition key
                }
            ],
            AttributeDefinitions=[
                {
                    "AttributeName": "student_id",
                    "AttributeType": "S",  # String
                }
            ],
            BillingMode="PAY_PER_REQUEST",  # On-Demand billing
        )

        # Wait until the table is created
        table.wait_until_exists()
        print(f"✅ Table 'Students' created successfully!")
        print(f"   Table ARN: {table.table_arn}")
        return table

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "ResourceInUseException":
            print("ℹ️  Table 'Students' already exists — nothing to do.")
        else:
            print(f"❌ Error creating table: {e}")
            raise


if __name__ == "__main__":
    create_students_table()
