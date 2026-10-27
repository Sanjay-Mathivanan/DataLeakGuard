import hashlib

import pytest
from fastapi import HTTPException

from app.api.v1.datasets import _delete_dataset_owned
from app.db import leakage_models, models, session as db_session
from app.utils.file_storage import ORIGINAL_DIR, PROCESSED_DIR, QUARANTINE_DIR


def _create_dataset(db, filename="source.csv"):
    content = b"name,value\nAlice,1\n"
    path = ORIGINAL_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    dataset = models.Dataset(
        name="deletion safety test",
        type="tabular",
        format="CSV",
        storage_filename=filename,
        file_sha256=hashlib.sha256(content).hexdigest(),
    )
    db.add(dataset)
    db.commit()
    return dataset, path, content


def test_delete_removes_only_dataset_record_and_preserves_original(client):
    original_content = b"name,value\nAlice,1\n"
    upload = client.post(
        "/api/v1/datasets",
        data={
            "name": "deletion safety test",
            "type": "tabular",
            "format": "CSV",
            "description": "preserve original on metadata deletion",
        },
        files={"file": ("source.csv", original_content, "text/csv")},
    )
    assert upload.status_code == 201
    dataset_id = upload.json()["id"]
    original_path = ORIGINAL_DIR / upload.json()["storage_filename"]
    assert original_path.read_bytes() == original_content

    deleted = client.delete(f"/api/v1/datasets/{dataset_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/datasets/{dataset_id}").status_code == 404
    assert original_path.read_bytes() == original_content

    # Repeated deletion remains state-idempotent; the existing API reports
    # an absent dataset as 404.
    repeated_delete = client.delete(f"/api/v1/datasets/{dataset_id}")
    assert repeated_delete.status_code == 404
    assert original_path.read_bytes() == original_content


def test_delete_is_blocked_when_findings_exist(test_db):
    db = db_session.TestingSessionLocal()
    try:
        dataset, original_path, original_content = _create_dataset(db)
        finding = leakage_models.LeakageFinding(
            dataset_id=dataset.id,
            finding_type="exact_duplicate",
            severity="medium",
            status="open",
            description="duplicate rows",
            evidence={"row_indices": [0]},
        )
        db.add(finding)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            _delete_dataset_owned(dataset.id, db, dataset.owner_user_id)

        assert exc_info.value.status_code == 409
        assert db.query(models.Dataset).filter_by(id=dataset.id).first() is not None
        assert db.query(leakage_models.LeakageFinding).filter_by(id=finding.id).first() is not None
        assert original_path.read_bytes() == original_content
    finally:
        db.close()


@pytest.mark.parametrize("operation_type", ["repair", "quarantine"])
def test_delete_is_blocked_when_operation_outputs_exist(test_db, operation_type):
    db = db_session.TestingSessionLocal()
    try:
        # Resolve these at test execution time. Collection-time Path parameters
        # retain the repository storage directories before the autouse
        # isolated_storage fixture can redirect module constants.
        output_dir = (
            PROCESSED_DIR if operation_type == "repair" else QUARANTINE_DIR
        )
        dataset, original_path, original_content = _create_dataset(db)
        output_filename = f"{operation_type}-output.csv"
        output_path = output_dir / output_filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_content = b"name,value\nAlice,1\n"
        output_path.write_bytes(output_content)

        operation = models.RepairRecord(
            dataset_id=dataset.id,
            operation_type=operation_type,
            status="completed",
            input_file_sha256=dataset.file_sha256,
            output_file_sha256=hashlib.sha256(output_content).hexdigest(),
            output_filename=output_filename,
            affected_rows=0,
        )
        db.add(operation)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            _delete_dataset_owned(dataset.id, db, dataset.owner_user_id)

        assert exc_info.value.status_code == 409
        assert db.query(models.Dataset).filter_by(id=dataset.id).first() is not None
        assert db.query(models.RepairRecord).filter_by(id=operation.id).first() is not None
        assert original_path.read_bytes() == original_content
        assert output_path.read_bytes() == output_content
    finally:
        db.close()


def test_delete_rolls_back_and_preserves_original_when_commit_fails(
    test_db, monkeypatch
):
    db = db_session.TestingSessionLocal()
    try:
        dataset, original_path, original_content = _create_dataset(db)
        dataset_id = dataset.id

        def fail_commit():
            raise RuntimeError("simulated commit failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            _delete_dataset_owned(dataset_id, db, dataset.owner_user_id)

        assert db.query(models.Dataset).filter_by(id=dataset_id).first() is not None
        assert original_path.read_bytes() == original_content
    finally:
        db.close()


def test_delete_preserves_dataset_and_file_when_reference_check_fails(
    test_db, monkeypatch
):
    db = db_session.TestingSessionLocal()
    try:
        dataset, original_path, original_content = _create_dataset(db)
        dataset_id = dataset.id
        original_query = db.query
        query_count = 0

        def fail_operation_reference_check(*entities, **kwargs):
            nonlocal query_count
            query_count += 1
            if query_count == 3:
                raise RuntimeError("simulated database reference-check failure")
            return original_query(*entities, **kwargs)

        monkeypatch.setattr(db, "query", fail_operation_reference_check)
        with pytest.raises(RuntimeError, match="reference-check failure"):
            _delete_dataset_owned(dataset_id, db, dataset.owner_user_id)

        verification_db = db_session.TestingSessionLocal()
        try:
            assert (
                verification_db.query(models.Dataset)
                .filter_by(id=dataset_id)
                .first()
                is not None
            )
        finally:
            verification_db.close()
        assert original_path.read_bytes() == original_content
    finally:
        db.close()
