#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pandas as pd
from app.db import models, leakage_models
from app.db.session import Base
from app.main import app
from fastapi.testclient import TestClient

# Setup test database
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///./debug_null_test.db"
engine = create_engine(SQLALCHEMY_TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Override the TestingSessionLocal
import app.db.session
original_testing_session_local = app.db.session.TestingSessionLocal
app.db.session.TestingSessionLocal = TestingSessionLocal

# Create tables
Base.metadata.create_all(bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

import app.main
app.main.app.dependency_overrides[app.db.session.get_db] = override_get_db
client = TestClient(app.main.app)

try:
    # Create test dataset exactly as in the null values test
    df = pd.DataFrame({
        'feature1': ['A', 'A', 'A', None],
        'feature2': [10, 10, 10, 10],
        'split': ['train', None, 'test', 'train']
    })
    csv_content = df.to_csv(index=False).encode()

    print("Creating dataset...")
    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test contamination with nulls",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    print(f"Create dataset response: {response.status_code}")
    if response.status_code != 201:
        print(f"Error: {response.json()}")
        exit(1)

    data = response.json()
    dataset_id = data["id"]
    print(f"Created dataset with ID: {dataset_id}")

    # Run leakage analysis with split_column
    print("\nRunning leakage analysis with split_column=split...")
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?split_column=split"
    )
    print(f"Leakage analysis response: {response.status_code}")
    if response.status_code != 200:
        print(f"Error: {response.json()}")
        exit(1)

    result = response.json()
    print(f"\nFull result:")
    print(f"dataset_id: {result.get('dataset_id')}")
    print(f"rows_examined: {result.get('rows_examined')}")
    print(f"findings count: {len(result.get('findings', []))}")

    for i, finding in enumerate(result.get('findings', [])):
        print(f"\nFinding {i}:")
        print(f"  finding_type: {finding.get('finding_type')}")
        print(f"  severity: {finding.get('severity')}")
        print(f"  status: {finding.get('status')}")
        print(f"  description: {finding.get('description')}")
        print(f"  evidence: {finding.get('evidence')}")

finally:
    # Cleanup
    app.main.app.dependency_overrides.clear()
    app.db.session.TestingSessionLocal = original_testing_session_local
    Base.metadata.drop_all(bind=engine)
    # Clean up test file
    try:
        if os.path.exists("./debug_null_test.db"):
            os.remove("./debug_null_test.db")
    except:
        pass