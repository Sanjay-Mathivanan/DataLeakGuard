import hashlib
import io

import pandas as pd
from fastapi import status

from app.db import models
import app.db.session
from app.utils.file_storage import ORIGINAL_DIR, PROCESSED_DIR


SPLIT_CSV = (
    "id,patient_id,value,target,event_time,partition\n"
    "1,p1,same,A,2020-01-01,train\n"
    "2,p1,same,A,2020-01-01,test\n"
    "3,p2,blue,B,2020-01-02,train\n"
    "4,p3,green,B,2021-01-02,test\n"
)


def upload_dataset(client, csv_content: str = SPLIT_CSV) -> dict:
    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "split strategy fixture",
            "type": "tabular",
            "format": "CSV",
            "description": "isolated split-strategy test input",
        },
        files={"file": ("split.csv", csv_content.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return response.json()


def test_existing_split_analysis_validates_and_reports_contamination(client, test_db):
    dataset = upload_dataset(client)
    source_path = ORIGINAL_DIR / dataset["storage_filename"]
    source_before = source_path.read_bytes()
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params={
            "split_strategy": "existing",
            "split_column": "partition",
            "entity_column": "patient_id",
            "target_column": "target",
            "time_column": "event_time",
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    result = response.json()
    assert result["split_strategy"] == "existing"
    assert result["split_configuration"]["source"] == "user_confirmed_dataset_column"
    assert result["split_configuration"]["split_row_counts"] == {
        "train": 2,
        "test": 2,
    }
    assert result["skipped_detectors"] == []
    assert source_path.read_bytes() == source_before
    assert "train_test_contamination" in {
        finding["finding_type"] for finding in result["findings"]
    }

    db = app.db.session.TestingSessionLocal()
    try:
        saved_dataset = db.query(models.Dataset).filter_by(id=dataset["id"]).one()
        assert saved_dataset.profile["split_strategy"]["strategy"] == "existing"
        event = (
            db.query(models.AuditEvent)
            .filter_by(dataset_id=dataset["id"], event_type="analysis")
            .order_by(models.AuditEvent.created_at.desc())
            .first()
        )
        assert event.details["split_strategy"]["split_column"] == "partition"
    finally:
        db.close()


def test_existing_split_rejects_missing_or_incomplete_split(client, test_db):
    dataset = upload_dataset(
        client,
        "id,value,partition\n1,a,train\n2,b,\n3,c,test\n",
    )
    missing = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params={"split_strategy": "existing", "split_column": "absent"},
    )
    assert missing.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "does not exist" in missing.json()["detail"]

    incomplete = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params={"split_strategy": "existing", "split_column": "partition"},
    )
    assert incomplete.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "missing or blank rows" in incomplete.json()["detail"]

    case_only = upload_dataset(
        client,
        "id,value,partition\n1,a,train\n2,b,TRAIN\n",
    )
    normalized = client.post(
        f"/api/v1/datasets/{case_only['id']}/analyze/leakage",
        params={"split_strategy": "existing", "split_column": "partition"},
    )
    assert normalized.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "at least two non-empty split groups" in normalized.json()["detail"]


def test_generate_split_is_deterministic_separate_and_audited(client, test_db):
    dataset = upload_dataset(client)
    source_path = ORIGINAL_DIR / dataset["storage_filename"]
    source_before = source_path.read_bytes()
    source_digest = hashlib.sha256(source_before).hexdigest()
    body = {"test_ratio": 0.25, "random_seed": 817}

    first = client.post(
        f"/api/v1/datasets/{dataset['id']}/split-strategies/generate",
        json=body,
    )
    assert first.status_code == status.HTTP_201_CREATED, first.text
    first_result = first.json()
    assert first_result["status"] == "completed"
    assert first_result["algorithm"] == "sha256_seeded_row_order_v1"
    assert first_result["input_file_sha256"] == source_digest
    assert first_result["split_row_counts"] == {"train": 3, "test": 1}
    output_path = PROCESSED_DIR / first_result["output_filename"]
    output_bytes = output_path.read_bytes()
    assert first_result["output_file_sha256"] == hashlib.sha256(output_bytes).hexdigest()
    assert first_result["output_file_sha256"] != source_digest
    split_frame = pd.read_csv(io.BytesIO(output_bytes), dtype=str)
    assert len(split_frame) == 4
    assert first_result["split_column"] in split_frame.columns
    assert source_path.read_bytes() == source_before

    second = client.post(
        f"/api/v1/datasets/{dataset['id']}/split-strategies/generate",
        json=body,
    )
    assert second.status_code == status.HTTP_201_CREATED, second.text
    second_result = second.json()
    assert second_result["id"] == first_result["id"]
    assert second_result["output_file_sha256"] == first_result["output_file_sha256"]
    assert second_result["reused"] is True
    assert len(list(PROCESSED_DIR.iterdir())) == 1

    history = client.get(f"/api/v1/datasets/{dataset['id']}/history")
    assert history.status_code == status.HTTP_200_OK
    assert any(
        row["event_type"] == "split_generation"
        and row["operation_id"] == first_result["id"]
        for row in history.json()
    )


def test_generated_split_can_be_selected_for_analysis(client, test_db):
    dataset = upload_dataset(client)
    generated = client.post(
        f"/api/v1/datasets/{dataset['id']}/split-strategies/generate",
        json={"test_ratio": 0.5, "random_seed": 19},
    )
    assert generated.status_code == status.HTTP_201_CREATED, generated.text
    operation_id = generated.json()["id"]

    analyzed = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params={
            "split_strategy": "generated",
            "split_operation_id": operation_id,
            "entity_column": "patient_id",
        },
    )
    assert analyzed.status_code == status.HTTP_200_OK, analyzed.text
    result = analyzed.json()
    assert result["split_strategy"] == "generated"
    assert result["split_configuration"]["split_operation_id"] == operation_id
    assert result["split_configuration"]["random_seed"] == 19
    assert result["split_configuration"]["group_aware"] is False
    assert result["skipped_detectors"] == []

    db = app.db.session.TestingSessionLocal()
    try:
        saved_dataset = db.query(models.Dataset).filter_by(id=dataset["id"]).one()
        assert saved_dataset.profile["analysis_columns"]["split_column"] == (
            result["split_configuration"]["split_column"]
        )
        assert saved_dataset.profile["split_strategy"]["strategy"] == "generated"
    finally:
        db.close()


def test_no_split_skips_split_dependent_detectors_explicitly(client, test_db):
    dataset = upload_dataset(
        client,
        (
            "id,patient_id,value,target,event_time\n"
            "1,p1,same,A,2020-01-01\n"
            "2,p2,blue,B,2020-01-02\n"
            "1,p1,same,A,2020-01-01\n"
        ),
    )
    db = app.db.session.TestingSessionLocal()
    try:
        saved_dataset = db.query(models.Dataset).filter_by(id=dataset["id"]).one()
        saved_dataset.profile = {
            "split_column": "stale_partition",
            "split_row_counts": {"train": 99, "test": 1},
        }
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params={
            "split_strategy": "none",
            "entity_column": "patient_id",
            "target_column": "target",
            "time_column": "event_time",
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    result = response.json()
    assert result["split_strategy"] == "none"
    assert set(result["skipped_detectors"]) == {
        "entity_overlap",
        "temporal_leakage",
        "train_test_contamination",
    }
    assert "train_test_contamination" not in {
        finding["finding_type"] for finding in result["findings"]
    }
    finding_types = {finding["finding_type"] for finding in result["findings"]}
    assert "exact_duplicate" in finding_types
    assert "target_leakage" in finding_types
    assert result["duplicate_group_count"] == 1
    assert "were not evaluated" in result["split_explanation"]
    persisted = client.get(f"/api/v1/datasets/{dataset['id']}").json()["profile"]
    assert "split_column" not in persisted
    assert "split_row_counts" not in persisted
    assert persisted["split_strategy"]["strategy"] == "none"
    assert persisted["analysis_columns"]["target_column"] == "target"
    history = client.get(f"/api/v1/datasets/{dataset['id']}/history")
    assert history.status_code == status.HTTP_200_OK
    event = next(
        item for item in history.json()
        if item["event_type"] == "analysis"
    )
    assert event["details"]["split_strategy"]["strategy"] == "none"
    assert set(event["details"]["skipped_detectors"]) == {
        "entity_overlap",
        "temporal_leakage",
        "train_test_contamination",
    }


def test_split_configuration_validation_and_dataset_ownership(client, test_db):
    dataset = upload_dataset(client)
    invalid_ratio = client.post(
        f"/api/v1/datasets/{dataset['id']}/split-strategies/generate",
        json={"test_ratio": 0.01, "random_seed": 3},
    )
    assert invalid_ratio.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    generated_without_id = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params={"split_strategy": "generated"},
    )
    assert generated_without_id.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    db = app.db.session.TestingSessionLocal()
    try:
        other = models.User(
            email="other-split-owner@example.test",
            display_name="Other",
            password_hash="test-only",
        )
        db.add(other)
        db.flush()
        foreign_dataset = models.Dataset(
            id="foreign-split-dataset",
            name="not owned",
            type="tabular",
            format="CSV",
            owner_user_id=other.id,
            storage_filename="not-accessed.csv",
        )
        db.add(foreign_dataset)
        db.commit()
    finally:
        db.close()

    denied = client.post(
        "/api/v1/datasets/foreign-split-dataset/split-strategies/generate",
        json={"test_ratio": 0.2, "random_seed": 42},
    )
    assert denied.status_code == status.HTTP_404_NOT_FOUND
