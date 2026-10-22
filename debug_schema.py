#!/usr/bin/env python3
"""Debug script to check database schema."""

import os
import sys

# Add the backend directory to the path
backend_path = os.path.join(os.path.dirname(__file__), "backend")
sys.path.insert(0, backend_path)

print(f"Python path: {sys.path[:3]}")

try:
    from app.db import models
    from app.db.session import TestingSessionLocal
    from sqlalchemy import inspect
    print("Imports successful")
except Exception as e:
    print(f"Import error: {e}")
    sys.exit(1)

def check_repair_record_schema():
    """Check the columns in the RepairRecord table."""
    db = TestingSessionLocal()
    try:
        # Get the inspector
        inspector = inspect(db.get_bind())

        # Get columns for repair_records table
        columns = inspector.get_columns('repair_records')

        print("Columns in repair_records table:")
        for column in columns:
            print(f"  {column['name']}: {column['type']}")

        # Check if output_filename exists
        column_names = [col['name'] for col in columns]
        if 'output_filename' in column_names:
            print("\n✓ output_filename column EXISTS")
        else:
            print("\n✗ output_filename column MISSING")
            print(f"Available columns: {column_names}")

    finally:
        db.close()

if __name__ == "__main__":
    check_repair_record_schema()