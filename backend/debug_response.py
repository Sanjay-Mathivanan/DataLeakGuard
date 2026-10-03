from fastapi.testclient import TestClient
from app.main import app
from app.db.session import TestingSessionLocal, get_db
from app.db.base import Base
import os

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

# Clean up
Base.metadata.drop_all(bind=TestingSessionLocal.kw['bind'])
app.dependency_overrides.clear()
