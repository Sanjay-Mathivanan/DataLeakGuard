from fastapi.testclient import TestClient
from app.main import app
import io

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
