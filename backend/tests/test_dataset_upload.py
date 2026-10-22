import asyncio
import os
import hashlib
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from app.api.v1 import datasets as datasets_api
from app.main import app
from app.api.v1.datasets import read_upload_with_limit
from app.core import dataset_service
from app.core.dataset_service import create_dataset_from_upload
from app.db import models, session as db_session
from app.utils.file_storage import ORIGINAL_DIR, validate_upload_file

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
    storage_path = ORIGINAL_DIR / data["storage_filename"]
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
    existing_files = set(ORIGINAL_DIR.iterdir())
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
    assert set(ORIGINAL_DIR.iterdir()) == existing_files


def test_upload_rejects_declared_format_mismatch_before_storage(client):
    existing_files = set(ORIGINAL_DIR.iterdir())
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "mismatched format",
            "type": "tabular",
            "format": "XLSX",
            "description": "test",
        },
        files={"file": ("data.csv", b"name\nAlice\n", "text/csv")},
    )

    assert response.status_code == 400
    assert "does not match" in response.json()["detail"]
    assert set(ORIGINAL_DIR.iterdir()) == existing_files


@pytest.mark.parametrize(
    ("filename", "dataset_type", "file_format", "extension"),
    [
        ("table.csv", "tabular", "CSV", "csv"),
        ("table.xlsx", "tabular", "XLSX", "xlsx"),
        ("images.zip", "computer-vision", "ZIP", "zip"),
    ],
)
def test_upload_validation_allows_only_supported_type_format_pairs(
    filename, dataset_type, file_format, extension
):
    assert validate_upload_file(filename, dataset_type, file_format) == extension


def test_upload_oversized(client, monkeypatch):
    # Temporarily reduce max size to 0 bytes to force error
    from app.core.config import settings
    original = settings.MAX_UPLOAD_SIZE_MB
    settings.MAX_UPLOAD_SIZE_MB = 0
    monkeypatch.setattr(
        datasets_api,
        "read_upload_with_limit",
        lambda *args, **kwargs: pytest.fail("oversized uploads should be rejected before reading"),
    )
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
        assert response.status_code == 413
        assert "File size exceeds limit" in response.json()["detail"]
    finally:
        settings.MAX_UPLOAD_SIZE_MB = original


def test_upload_reader_stops_after_crossing_limit():
    class TrackingUpload:
        def __init__(self, content):
            self.content = content
            self.bytes_read = 0

        async def read(self, size):
            chunk = self.content[self.bytes_read:self.bytes_read + size]
            self.bytes_read += len(chunk)
            return chunk

    upload = TrackingUpload(b"x" * (2 * 1024 * 1024))
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(read_upload_with_limit(upload, max_size_bytes=4))

    assert exc_info.value.status_code == 413
    assert upload.bytes_read == 5
    assert upload.bytes_read < len(upload.content)


def test_upload_commit_failure_removes_only_unreferenced_new_file(test_db, monkeypatch):
    db = db_session.TestingSessionLocal()
    try:
        existing_dataset = create_dataset_from_upload(
            db,
            name="existing dataset",
            dataset_type="tabular",
            format="CSV",
            description="preserved dataset",
            file_content=b"name\nExisting\n",
            original_filename="existing.csv",
        )
        existing_path = ORIGINAL_DIR / existing_dataset.storage_filename
        existing_files = set(ORIGINAL_DIR.iterdir())

        def fail_commit():
            raise RuntimeError("simulated database commit failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="simulated database commit failure"):
            create_dataset_from_upload(
                db,
                name="failed dataset",
                dataset_type="tabular",
                format="CSV",
                description="must not leave an orphan",
                file_content=b"name\nNew\n",
                original_filename="new.csv",
            )

        assert set(ORIGINAL_DIR.iterdir()) == existing_files
        assert existing_path.is_file()
        assert db.query(models.Dataset).filter(models.Dataset.id == existing_dataset.id).first()
    finally:
        db.close()


def test_upload_does_not_remove_file_if_commit_persisted_before_raising(test_db, monkeypatch):
    db = db_session.TestingSessionLocal()
    try:
        original_commit = db.commit

        def commit_then_raise():
            original_commit()
            raise RuntimeError("commit result was reported as failed")

        monkeypatch.setattr(db, "commit", commit_then_raise)
        with pytest.raises(RuntimeError, match="commit result was reported as failed"):
            create_dataset_from_upload(
                db,
                name="persisted despite error",
                dataset_type="tabular",
                format="CSV",
                description="the referenced file must remain",
                file_content=b"name\nPersisted\n",
                original_filename="persisted.csv",
            )

        persisted = (
            db.query(models.Dataset)
            .filter(models.Dataset.name == "persisted despite error")
            .first()
        )
        assert persisted is not None
        assert (ORIGINAL_DIR / persisted.storage_filename).is_file()
    finally:
        db.close()


def test_upload_profiling_failure_does_not_leave_an_orphan(test_db, monkeypatch):
    db = db_session.TestingSessionLocal()
    existing_files = set(ORIGINAL_DIR.iterdir())
    try:
        def fail_profile(storage_path):
            raise RuntimeError("simulated profiling failure")

        monkeypatch.setattr(dataset_service, "profile_tabular", fail_profile)
        with pytest.raises(RuntimeError, match="simulated profiling failure"):
            create_dataset_from_upload(
                db,
                name="profile failure",
                dataset_type="tabular",
                format="CSV",
                description="must not leave an orphan",
                file_content=b"name\nNew\n",
                original_filename="profile-failure.csv",
            )

        assert set(ORIGINAL_DIR.iterdir()) == existing_files
        assert db.query(models.Dataset).count() == 0
    finally:
        db.close()


def test_upload_preserves_new_file_if_database_reference_cannot_be_checked(test_db, monkeypatch):
    db = db_session.TestingSessionLocal()
    existing_files = set(ORIGINAL_DIR.iterdir())
    try:
        def fail_commit():
            raise RuntimeError("simulated database commit failure")

        def fail_query(*args, **kwargs):
            raise RuntimeError("simulated database query failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        monkeypatch.setattr(db, "query", fail_query)

        with pytest.raises(RuntimeError, match="simulated database commit failure"):
            create_dataset_from_upload(
                db,
                name="uncertain dataset",
                dataset_type="tabular",
                format="CSV",
                description="preserve if persistence is uncertain",
                file_content=b"name\nNew\n",
                original_filename="uncertain.csv",
            )

        new_files = set(ORIGINAL_DIR.iterdir()) - existing_files
        assert len(new_files) == 1
        assert next(iter(new_files)).is_file()
    finally:
        db.close()


def test_configured_frontend_dev_origin_is_allowed_by_cors(client):
    response = client.options(
        f"{API_V1_STR}/datasets",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


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
