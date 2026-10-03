import os
import hashlib
import pytest
from fastapi.testclient import TestClient
from app.main import app

API_V1_STR = "/api/v1"  # matches settings.API_V1_STR in main.py


def test_upload_csv(client):
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "test csv"
    assert data["storage_filename"] is not None
    assert data["file_sha256"] is not None
    assert data["profile"] is not None
    assert data["profile"]["row_count"] == 3
    assert data["profile"]["column_count"] == 2
    # Verify file exists
    storage_path = os.path.join("backend", "storage", "original", data["storage_filename"])
    assert os.path.exists(storage_path)
    # Verify SHA-256
    with open(storage_path, "rb") as f:
        computed = hashlib.sha256(f.read()).hexdigest()
    assert computed == data["file_sha256"]
    # Verify profile endpoint
    resp2 = client.get(f"{API_V1_STR}/datasets/{data['id']}/profile")
    assert resp2.status_code == 200
    profile_data = resp2.json()
    assert profile_data["id"] == data["id"]
    assert profile_data["profile"] == data["profile"]


def test_upload_invalid_extension(client):
    csv_content = b"name,age\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "bad",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.txt", csv_content, "text/plain")}
    )
    assert response.status_code == 400


def test_upload_oversized(client, monkeypatch):
    # Temporarily reduce max size to 0 bytes to force error
    from app.core.config import settings
    original = settings.MAX_UPLOAD_SIZE_MB
    settings.MAX_UPLOAD_SIZE_MB = 0
    try:
        csv_content = b"name,age\nAlice,30\n"
        response = client.post(
            f"{API_V1_STR}/datasets",
            data={
                "name": "big",
                "type": "tabular",
                "format": "CSV",
                "description": "test"
            },
            files={"file": ("big.csv", csv_content, "text/csv")}
        )
        assert response.status_code == 400
        assert "File size exceeds limit" in response.json()["detail"]
    finally:
        settings.MAX_UPLOAD_SIZE_MB = original


def test_crud_compatibility(client):
    # Upload a dataset
    csv_content = b"name,age\nAlice,30\nBob,25\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "crud test",
            "type": "tabular",
            "format": "CSV",
            "description": "crud"
        },
        files={"file": ("crud.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]
    assert data["name"] == "crud test"
    assert data["storage_filename"] is not None
    assert data["file_sha256"] is not None

    # GET single dataset
    resp_get = client.get(f"{API_V1_STR}/datasets/{dataset_id}")
    assert resp_get.status_code == 200
    get_data = resp_get.json()
    assert get_data["id"] == dataset_id
    assert get_data["name"] == "crud test"
    assert get_data["storage_filename"] == data["storage_filename"]
    assert get_data["file_sha256"] == data["file_sha256"]

    # GET list datasets
    resp_list = client.get(f"{API_V1_STR}/datasets")
    assert resp_list.status_code == 200
    list_data = resp_list.json()
    assert any(d["id"] == dataset_id for d in list_data)

    # DELETE dataset (optional, but verify endpoint exists)
    resp_del = client.delete(f"{API_V1_STR}/datasets/{dataset_id}")
    # DELETE may return 204 or 200; we just ensure not 404
    assert resp_del.status_code != 404