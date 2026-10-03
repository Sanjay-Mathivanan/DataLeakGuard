#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pandas as pd
from app.db import models, leakage_models
from app.db.session import Base
from app.services.leakage_detection_service import detect_exact_duplicates

# Setup test database
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///./test_direct.db"
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

try:
    # Create test dataset exactly as in the target leakage test
    df = pd.DataFrame({
        'id': [1, 2, 3, 4],
        'feature': ['A', 'B', 'C', 'D'],
        'target': [1, 0, 1, 0],
        'leaked_feature': [1, 0, 1, 0]  # Exactly duplicates target
    })
    csv_content = df.to_csv(index=False).encode()

    print("Creating dataset directly...")
    # We'll create the dataset manually to test the service functions
    from app.core import dataset_service
    import tempfile

    # Create a temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        df.to_csv(f.name, index=False)
        temp_file_path = f.name

    try:
        with open(temp_file_path, 'rb') as f:
            file_content = f.read()

        # Create dataset using service
        db = TestingSessionLocal()
        try:
            dataset = dataset_service.create_dataset_from_upload(
                db=db,
                name="test direct",
                dataset_type="tabular",
                format="CSV",
                description="test",
                file_content=file_content,
                original_filename="test.csv"
            )
            db.commit()
            dataset_id = dataset.id
            print(f"Created dataset with ID: {dataset_id}")

            # Test detect_exact_duplicates directly
            print("\nTesting detect_exact_duplicates directly...")
            result = detect_exact_duplicates(dataset_id, db)
            print(f"Direct result: {result}")

        finally:
            db.close()
    finally:
        os.unlink(temp_file_path)

finally:
    # Cleanup
    app.main.app.dependency_overrides.clear()
    app.db.session.TestingSessionLocal = original_testing_session_local
    Base.metadata.drop_all(bind=engine)