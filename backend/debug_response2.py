from fastapi.testclient import TestClient
from app.main import app
from app.db.session import TestingSessionLocal, get_db
from app.db import models
from app.db.base import Base
import json

# Override the dependency to use a test session
def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

# Create tables
Base.metadata.create_all(bind=TestingSessionLocal.kw['bind'])

client = TestClient(app)

csv_content = b"name,age\nAlice,30\nBob,25\n"
response = client.post(
    "/api/v1/datasets",
    data={
        "name": "test csv",
        "type": "tabular",
        "format": "CSV",
        "description": "test"
    },
    files={"file": ("test.csv", csv_content, "text/csv")}
)

print("Status code:", response.status_code)
print("Response JSON:", response.json())

# Query the dataset from the database to see what was stored
db = TestingSessionLocal()
try:
    # We need to get the id from the response
    data = response.json()
    dataset_id = data["id"]
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if dataset:
        print("\nDataset ORM attributes:")
        print(f"  storage_filename: {getattr(dataset, 'storage_filename', 'NOT FOUND')}")
        print(f"  file_sha256: {getattr(dataset, 'file_sha256', 'NOT FOUND')}")
        print(f"  profile: {getattr(dataset, 'profile', 'NOT FOUND')}")
        print(f"  name: {getattr(dataset, 'name', 'NOT FOUND')}")
    else:
        print("Dataset not found")
finally:
    db.close()

# Clean up
Base.metadata.drop_all(bind=TestingSessionLocal.kw['bind'])
app.dependency_overrides.clear()
