import hashlib

import pytest

from app.db import models
import app.db.session


def _create_operation(
    operation_id,
    operation_type="repair",
    status="completed",
    output_filename="output.csv",
    output_file_sha256=None,
):
    db = app.db.session.TestingSessionLocal()
    try:
        operation = models.RepairRecord(
            id=operation_id,
            dataset_id="dataset-download-test",
            finding_id="finding-download-test",
            operation_type=operation_type,
            status=status,
            input_file_sha256="a" * 64,
            output_file_sha256=output_file_sha256,
            output_filename=output_filename,
        )
        db.add(operation)
        db.commit()
    finally:
        db.close()


@pytest.mark.parametrize(
    ("operation_type", "extension", "expected_media_type"),
    [
        ("repair", ".csv", "text/csv"),
        (
            "quarantine",
            ".xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ],
)
def test_completed_operation_download_returns_file_and_safe_headers(
    client,
    test_db,
    tmp_path,
    monkeypatch,
    operation_type,
    extension,
    expected_media_type,
):
    processed_dir = tmp_path / "processed"
    quarantine_dir = tmp_path / "quarantine"
    processed_dir.mkdir()
    quarantine_dir.mkdir()
    monkeypatch.setattr("app.api.v1.repairs.PROCESSED_DIR", processed_dir)
    monkeypatch.setattr("app.api.v1.repairs.QUARANTINE_DIR", quarantine_dir)

    filename = f"download-test{extension}"
    payload = b"safe output bytes\n"
    output_dir = processed_dir if operation_type == "repair" else quarantine_dir
    (output_dir / filename).write_bytes(payload)
    _create_operation(
        "operation-download-success",
        operation_type=operation_type,
        output_filename=filename,
        output_file_sha256=hashlib.sha256(payload).hexdigest(),
    )

    response = client.get(
        "/api/v1/operations/operation-download-success/download",
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"].startswith(expected_media_type)
    assert "attachment" in response.headers["content-disposition"].lower()
    assert filename in response.headers["content-disposition"]
    assert "content-disposition" in response.headers[
        "access-control-expose-headers"
    ].lower()
    assert str(tmp_path) not in str(response.headers)


def test_download_returns_404_for_unknown_operation(client, test_db):
    response = client.get("/api/v1/operations/unknown-operation/download")

    assert response.status_code == 404
    assert response.json()["detail"] == "Operation not found"


def test_download_returns_404_when_recorded_output_is_missing(
    client,
    test_db,
    tmp_path,
    monkeypatch,
):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    monkeypatch.setattr("app.api.v1.repairs.PROCESSED_DIR", processed_dir)
    monkeypatch.setattr(
        "app.api.v1.repairs.QUARANTINE_DIR",
        tmp_path / "quarantine",
    )
    _create_operation("operation-missing-output")

    response = client.get("/api/v1/operations/operation-missing-output/download")

    assert response.status_code == 404
    assert response.json()["detail"] == "Operation output file not found"


def test_download_rejects_unsupported_operation_type(client, test_db):
    _create_operation(
        "operation-unsupported-type",
        operation_type="future_operation",
    )

    response = client.get("/api/v1/operations/operation-unsupported-type/download")

    assert response.status_code == 400
    assert response.json()["detail"] == "Operation type does not support output downloads"


@pytest.mark.parametrize(
    "filename",
    [
        "../outside.csv",
        r"..\outside.csv",
        r"C:\outside.csv",
        "bad..name.csv",
        "output.txt",
        None,
    ],
)
def test_download_rejects_malformed_or_traversal_filenames(
    client,
    test_db,
    tmp_path,
    monkeypatch,
    filename,
):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    monkeypatch.setattr("app.api.v1.repairs.PROCESSED_DIR", processed_dir)
    _create_operation(
        "operation-malformed-filename",
        output_filename=filename,
    )

    response = client.get("/api/v1/operations/operation-malformed-filename/download")

    assert response.status_code == 400
    assert response.json()["detail"] == "Operation has an invalid output filename"
    assert not (tmp_path / "outside.csv").exists()


def test_download_does_not_serve_output_when_hash_mismatches(
    client,
    test_db,
    tmp_path,
    monkeypatch,
):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    monkeypatch.setattr("app.api.v1.repairs.PROCESSED_DIR", processed_dir)
    payload = b"changed output\n"
    (processed_dir / "output.csv").write_bytes(payload)
    _create_operation(
        "operation-hash-mismatch",
        output_file_sha256=hashlib.sha256(b"recorded output\n").hexdigest(),
    )

    response = client.get("/api/v1/operations/operation-hash-mismatch/download")

    assert response.status_code == 500
    assert "integrity verification" in response.json()["detail"].lower()
    assert response.content != payload


def test_download_rejects_incomplete_operation_before_serving_file(
    client,
    test_db,
    tmp_path,
    monkeypatch,
):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    monkeypatch.setattr("app.api.v1.repairs.PROCESSED_DIR", processed_dir)
    (processed_dir / "output.csv").write_bytes(b"not ready\n")
    _create_operation(
        "operation-incomplete",
        status="processing",
    )

    response = client.get("/api/v1/operations/operation-incomplete/download")

    assert response.status_code == 409
    assert "not available" in response.json()["detail"]


def test_download_rejects_symlink_that_resolves_outside_storage_root(
    client,
    test_db,
    tmp_path,
    monkeypatch,
):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    outside_file = tmp_path / "outside.csv"
    outside_file.write_bytes(b"outside\n")
    link_path = processed_dir / "linked.csv"
    try:
        link_path.symlink_to(outside_file)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable in this test environment")

    monkeypatch.setattr("app.api.v1.repairs.PROCESSED_DIR", processed_dir)
    _create_operation(
        "operation-symlink-escape",
        output_filename=link_path.name,
        output_file_sha256=hashlib.sha256(b"outside\n").hexdigest(),
    )

    response = client.get("/api/v1/operations/operation-symlink-escape/download")

    assert response.status_code == 400
    assert response.json()["detail"] == "Operation has an invalid output filename"


def test_download_allows_completed_operation_without_recorded_hash(
    client,
    test_db,
    tmp_path,
    monkeypatch,
):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    monkeypatch.setattr("app.api.v1.repairs.PROCESSED_DIR", processed_dir)
    payload = b"legacy output\n"
    (processed_dir / "output.csv").write_bytes(payload)
    _create_operation(
        "operation-no-hash",
        output_file_sha256=None,
    )

    response = client.get("/api/v1/operations/operation-no-hash/download")

    assert response.status_code == 200
    assert response.content == payload
