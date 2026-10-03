#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pandas as pd
import os
import tempfile
from app.db import models, leakage_models
from app.db.session import Base
from app.services.leakage_detection_service import detect_train_test_contamination, hash_row
from app.core import dataset_service
from fastapi import HTTPException

# Setup test database
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///./test_debug.db"
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
from fastapi.testclient import TestClient

app.main.app.dependency_overrides[app.db.session.get_db] = override_get_db
client = TestClient(app.main.app)

try:
    # Create test dataset
    df = pd.DataFrame({
        'id': [1, 2, 3, 4, 5],
        'feature1': ['A', 'B', 'C', 'A', 'D'],
        'feature2': [10, 20, 30, 10, 40],
        'split': ['train', 'train', 'test', 'test', 'train']
    })
    csv_content = df.to_csv(index=False).encode()

    print("Creating dataset...")
    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test debug",
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

    # Get the dataset to see storage filename
    db = TestingSessionLocal()
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    print(f"Dataset storage filename: {dataset.storage_filename}")
    print(f"Dataset format: {dataset.format}")
    db.close()

    # Check if file exists - using the correct backend/storage path
    storage_path = os.path.join("C:\\Users\\sanja\\my_project\\dataleakguard-cv\\backend\\storage", "original", dataset.storage_filename)
    print(f"Storage path: {storage_path}")
    print(f"File exists: {os.path.exists(storage_path)}")

    # List what's actually in the storage directory
    storage_original_dir = os.path.join("C:\\Users\\sanja\\my_project\\dataleakguard-cv\\backend\\storage", "original")
    if os.path.exists(storage_original_dir):
        files = os.listdir(storage_original_dir)
        print(f"Files in storage/original directory: {files}")
    else:
        print(f"Storage/original directory does not exist: {storage_original_dir}")

    # Check the storage directory itself
    storage_dir = "C:\\Users\\sanja\\my_project\\dataleakguard-cv\\backend\\storage"
    if os.path.exists(storage_dir):
        files = os.listdir(storage_dir)
        print(f"Files in storage directory: {files}")
    else:
        print(f"Storage directory does not exist: {storage_dir}")

    if os.path.exists(storage_path):
        # Try to read the file directly
        try:
            df_read = pd.read_csv(storage_path, dtype=str)
            print(f"Read dataframe shape: {df_read.shape}")
            print(f"Columns: {df_read.columns.tolist()}")
            print(f"First few rows:")
            print(df_read.head())
        except Exception as e:
            print(f"Error reading file: {e}")
    else:
        print("Storage file does not exist - this is the problem!")

    # Now try to run the contamination detection directly
    print("\nCalling detect_train_test_contamination directly...")
    db = TestingSessionLocal()
    try:
        findings = detect_train_test_contamination(dataset_id, db, "split")
        print(f"Number of findings returned: {len(findings)}")
        for i, finding in enumerate(findings):
            print(f"Finding {i}: {finding}")
    except Exception as e:
        print(f"Error in detect_train_test_contamination: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

finally:
    # Cleanup
    app.main.app.dependency_overrides.clear()
    app.db.session.TestingSessionLocal = original_testing_session_local
    Base.metadata.drop_all(bind=engine)
    # Clean up test file
    try:
        if os.path.exists("./test_debug.db"):
            os.remove("./test_debug.db")
    except:
        pass