import hashlib
import io

import pandas as pd
import pytest

import app.db.session
from app.db import models
from app.utils.file_storage import ORIGINAL_DIR


def upload_csv(client, content: str) -> dict:
    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "train-only imputation regression",
            "type": "tabular",
            "format": "CSV",
            "description": "isolated synthetic fixture",
        },
        files={"file": ("imputation.csv", content.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def configure_columns(dataset_id: str) -> None:
    db = app.db.session.TestingSessionLocal()
    try:
        dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
        assert dataset is not None
        profile = dict(dataset.profile or {})
        profile["analysis_columns"] = {
            "target_column": "outcome",
            "entity_column": "entity key",
            "entity_columns": ["entity key"],
            "contamination_key_columns": ["record"],
            "time_column": "observed at",
            "split_column": "partition label",
        }
        dataset.profile = profile
        db.add(dataset)
        db.commit()
    finally:
        db.close()


def preview_imputation(client, dataset_id: str, *, columns=None):
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/preprocessing/imputation/preview",
        json={
            "split_column": "partition label",
            "training_partition": "train",
            "columns": columns
            or [
                {"column": "numeric feature", "method": "mean"},
                {"column": "category feature", "method": "mode"},
            ],
        },
    )
    return response


def test_imputation_fits_training_only_preserves_source_and_is_idempotent(client):
    source_csv = (
        "record,outcome,entity key,observed at,partition label,numeric feature,category feature\n"
        "r1,yes,e1,2025-01-01,train,2,red\n"
        "r2,no,e2,2025-01-02,train,4,red\n"
        "r3,yes,e3,2025-01-03,train,,\n"
        "r4,no,e4,2025-01-04,test,10000,blue\n"
        "r5,yes,e5,2025-01-05,test,,\n"
    )
    dataset = upload_csv(client, source_csv)
    configure_columns(dataset["id"])
    source_path = ORIGINAL_DIR / dataset["storage_filename"]
    source_bytes = source_path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()

    preview = preview_imputation(client, dataset["id"])
    assert preview.status_code == 200, preview.text
    preview_data = preview.json()
    assert preview_data["fit_row_count"] == 3
    strategies = {item["column"]: item for item in preview_data["strategies"]}
    assert strategies["numeric feature"]["fitted_value"] == "3"
    assert strategies["numeric feature"]["fit_partition"] == "training_partition_only"
    assert strategies["category feature"]["fitted_value"] == "red"
    assert preview_data["missing_counts_before"] == {
        "numeric feature": 2,
        "category feature": 2,
    }
    assert preview_data["missing_counts_after"] == {
        "numeric feature": 0,
        "category feature": 0,
    }
    assert set(preview_data["protected_columns"]) == {
        "outcome",
        "entity key",
        "record",
        "observed at",
        "partition label",
    }

    request = {
        "split_column": "partition label",
        "training_partition": "train",
        "columns": [
            {"column": "numeric feature", "method": "mean"},
            {"column": "category feature", "method": "mode"},
        ],
        "preview_token": preview_data["preview_token"],
        "confirmed": False,
    }
    not_confirmed = client.post(
        f"/api/v1/datasets/{dataset['id']}/preprocessing/imputation/execute",
        json=request,
    )
    assert not_confirmed.status_code == 428
    assert source_path.read_bytes() == source_bytes

    request["confirmed"] = True
    executed = client.post(
        f"/api/v1/datasets/{dataset['id']}/preprocessing/imputation/execute",
        json=request,
    )
    assert executed.status_code == 201, executed.text
    operation = executed.json()
    assert operation["status"] == "completed"
    assert operation["input_file_sha256"] == source_hash
    assert operation["operation_metadata"]["verification"]["status"] == "verified"
    assert all(
        check["status"] == "passed"
        for check in operation["operation_metadata"]["verification"]["checks"].values()
    )
    assert source_path.read_bytes() == source_bytes

    download = client.get(f"/api/v1/operations/{operation['id']}/download")
    assert download.status_code == 200, download.text
    assert hashlib.sha256(download.content).hexdigest() == operation["output_file_sha256"]
    output = pd.read_csv(io.BytesIO(download.content), dtype=str)
    assert output["numeric feature"].tolist() == ["2", "4", "3", "10000", "3"]
    assert output["category feature"].tolist() == ["red", "red", "red", "blue", "red"]
    assert output["outcome"].tolist() == ["yes", "no", "yes", "no", "yes"]
    assert output["partition label"].tolist() == ["train", "train", "train", "test", "test"]

    repeated = client.post(
        f"/api/v1/datasets/{dataset['id']}/preprocessing/imputation/execute",
        json=request,
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == operation["id"]


@pytest.mark.parametrize(
    "protected",
    ["outcome", "entity key", "record", "observed at", "partition label"],
)
def test_configured_target_entity_comparison_key_timestamp_and_split_cannot_be_imputed(client, protected):
    dataset = upload_csv(
        client,
        "record,outcome,entity key,observed at,partition label,feature\n"
        "r1,yes,e1,2025-01-01,train,1\n"
        "r2,no,e2,2025-01-02,test,\n",
    )
    configure_columns(dataset["id"])
    response = preview_imputation(
        client,
        dataset["id"],
        columns=[{"column": protected, "method": "mode"}],
    )
    assert response.status_code == 422
    assert "Do not impute configured" in response.json()["detail"]


def test_stale_preview_is_rejected_after_source_changes(client):
    dataset = upload_csv(
        client,
        "record,partition label,feature\nr1,train,1\nr2,test,\n",
    )
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/preprocessing/imputation/preview",
        json={
            "split_column": "partition label",
            "training_partition": "train",
            "columns": [{"column": "feature", "method": "median"}],
        },
    )
    assert response.status_code == 200, response.text
    preview_data = response.json()
    source_path = ORIGINAL_DIR / dataset["storage_filename"]
    source_path.write_text(
        "record,partition label,feature\nr1,train,1\nr2,test,2\n",
        encoding="utf-8",
    )
    execution = client.post(
        f"/api/v1/datasets/{dataset['id']}/preprocessing/imputation/execute",
        json={
            "split_column": "partition label",
            "training_partition": "train",
            "columns": [{"column": "feature", "method": "median"}],
            "preview_token": preview_data["preview_token"],
            "confirmed": True,
        },
    )
    assert execution.status_code == 409
    assert "stale" in execution.json()["detail"].lower()


def test_train_only_imputation_rejects_missing_membership_and_invalid_numeric_values(client):
    missing_split_dataset = upload_csv(
        client,
        "partition label,feature\ntrain,1\n,2\n",
    )
    missing_split = client.post(
        f"/api/v1/datasets/{missing_split_dataset['id']}/preprocessing/imputation/preview",
        json={
            "split_column": "partition label",
            "columns": [{"column": "feature", "method": "mean"}],
        },
    )
    assert missing_split.status_code == 422
    assert "missing membership" in missing_split.json()["detail"]

    nonnumeric_dataset = upload_csv(
        client,
        "partition label,feature\ntrain,red\ntest,\n",
    )
    nonnumeric = client.post(
        f"/api/v1/datasets/{nonnumeric_dataset['id']}/preprocessing/imputation/preview",
        json={
            "split_column": "partition label",
            "columns": [{"column": "feature", "method": "mean"}],
        },
    )
    assert nonnumeric.status_code == 422
    assert "numeric training values" in nonnumeric.json()["detail"]
