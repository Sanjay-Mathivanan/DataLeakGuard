import hashlib
import io

import pandas as pd
import pytest

import app.db.session
from app.db import leakage_models, models
from app.utils.file_storage import ORIGINAL_DIR
from app.utils.row_hashing import hash_row


def upload_csv(client, name: str, content: str) -> dict:
    response = client.post(
        "/api/v1/datasets",
        data={
            "name": name,
            "type": "tabular",
            "format": "CSV",
            "description": "isolated remediation test dataset",
        },
        files={"file": (f"{name}.csv", content.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_finding(
    dataset_id: str,
    finding_id: str,
    finding_type: str,
    evidence: dict,
    *,
    status: str = "open",
) -> None:
    db = app.db.session.TestingSessionLocal()
    try:
        db.add(
            leakage_models.LeakageFinding(
                id=finding_id,
                dataset_id=dataset_id,
                finding_type=finding_type,
                severity="high",
                status=status,
                description=f"Persisted {finding_type} test evidence",
                evidence=evidence,
            )
        )
        db.commit()
    finally:
        db.close()


def preview(client, dataset_id: str, actions: list[dict]) -> dict:
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/remediation-plans/preview",
        json={"actions": actions},
    )
    assert response.status_code == 201, response.text
    return response.json()


def execute(client, dataset_id: str, result: dict, *, confirmed: bool = True):
    return client.post(
        f"/api/v1/datasets/{dataset_id}/remediation-plans/{result['id']}/execute",
        json={
            "preview_token": result["plan"]["preview_token"],
            "confirmed": confirmed,
        },
    )


def test_exact_duplicate_plan_preserves_source_and_generates_verified_artifacts(client):
    source_csv = "id,value\n1,a\n2,b\n3,a\n"
    dataset = upload_csv(client, "duplicate remediation", source_csv)
    source_path = ORIGINAL_DIR / dataset["storage_filename"]
    original_bytes = source_path.read_bytes()
    frame = pd.read_csv(io.BytesIO(original_bytes), dtype=str)
    duplicate_hash = hash_row(frame.drop(columns=["id"]).iloc[0])
    add_finding(
        dataset["id"],
        "duplicate-plan-finding",
        "exact_duplicate",
        {
            "hash": duplicate_hash,
            "duplicate_count": 2,
            "row_indices": [0, 2],
            "hash_excluded_columns": ["id"],
        },
    )

    result = preview(
        client,
        dataset["id"],
        [
            {
                "action": "exact_duplicate_keep_first",
                "finding_ids": ["duplicate-plan-finding"],
            }
        ],
    )
    plan = result["plan"]
    assert result["status"] == "previewed"
    assert plan["original_file_sha256"] == hashlib.sha256(original_bytes).hexdigest()
    assert plan["expected_final_row_count"] == 2
    assert plan["affected_source_row_positions_preview"] == [2]
    assert plan["affected_source_row_positions_count"] == 1
    assert plan["user_confirmation"] is False

    missing_confirmation = execute(client, dataset["id"], result, confirmed=False)
    assert missing_confirmation.status_code == 428
    assert source_path.read_bytes() == original_bytes

    completed = execute(client, dataset["id"], result)
    assert completed.status_code == 201, completed.text
    operation = completed.json()
    assert operation["operation_type"] == "consolidated_remediation"
    assert operation["status"] == "completed"
    assert operation["plan"]["final_status"] == "fully_remediated_for_selected_rules"
    assert operation["plan"]["verification"]["all_checks_passed"] is True
    assert source_path.read_bytes() == original_bytes

    output_response = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/dataset"
    )
    assert output_response.status_code == 200
    assert "DataLeakGuard_Final_Cleaned_Dataset.csv" in output_response.headers[
        "content-disposition"
    ]
    cleaned = pd.read_csv(io.BytesIO(output_response.content), dtype=str)
    assert len(cleaned) == 2
    assert list(cleaned.columns) == ["id", "value"]
    assert operation["artifact_hashes"]["dataset"] == hashlib.sha256(
        output_response.content
    ).hexdigest()

    report_response = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/report"
    )
    assert report_response.status_code == 200
    report = pd.read_csv(io.BytesIO(report_response.content), dtype=str)
    assert report.iloc[0]["finding_id"] == "duplicate-plan-finding"
    manifest_response = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/manifest"
    )
    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    assert manifest["original_file_sha256"] == plan["original_file_sha256"]
    assert manifest["final_file_sha256"] == operation["output_file_sha256"]
    assert manifest["rows_to_remove"] == [2]

    repeated = execute(client, dataset["id"], result)
    assert repeated.status_code == 201
    assert repeated.json()["id"] == operation["id"]


def test_target_leakage_excludes_only_confirmed_feature_and_preserves_target(client):
    dataset = upload_csv(
        client,
        "target remediation",
        "id,target,confirmed_leak,ordinary\n1,yes,yes,a\n2,no,no,b\n",
    )
    evidence = {
        "target_column": "target",
        "feature_column": "confirmed_leak",
        "detection": "exact_target_duplicate",
        "matching_rows": 2,
        "total_valid_rows": 2,
    }
    add_finding(dataset["id"], "target-exclusion-finding", "target_leakage", evidence)
    result = preview(
        client,
        dataset["id"],
        [
            {
                "action": "exclude_target_features",
                "finding_ids": ["target-exclusion-finding"],
                "target_column": "target",
                "feature_columns": ["confirmed_leak"],
            }
        ],
    )
    assert result["plan"]["excluded_feature_columns"] == ["confirmed_leak"]

    completed = execute(client, dataset["id"], result)
    assert completed.status_code == 201, completed.text
    operation = completed.json()
    response = client.get(
        f"/api/v1/operations/{operation['id']}/remediation-artifacts/dataset"
    )
    cleaned = pd.read_csv(io.BytesIO(response.content), dtype=str)
    assert list(cleaned.columns) == ["id", "target", "ordinary"]
    assert cleaned["target"].tolist() == ["yes", "no"]
    assert operation["plan"]["verification"]["checks"]["selected_target_preserved"]


def test_entity_overlap_rebuild_keeps_each_entity_in_one_seeded_partition(client):
    dataset = upload_csv(
        client,
        "entity group split",
        "id,patient_id,value,partition\n"
        "1,p1,a,train\n2,p1,b,test\n3,p2,c,train\n4,p3,d,test\n",
    )
    add_finding(
        dataset["id"],
        "entity-overlap-finding",
        "entity_overlap",
        {
            "entity_column": "patient_id",
            "split_column": "partition",
            "entity_value": "p1",
            "splits": ["train", "test"],
            "row_indices": {"train": [0], "test": [1]},
        },
    )
    result = preview(
        client,
        dataset["id"],
        [{
            "action": "rebuild_group_split",
            "finding_ids": ["entity-overlap-finding"],
            "entity_column": "patient_id",
            "split_column": "partition",
            "test_ratio": 0.34,
            "random_seed": 319,
        }],
    )
    repeat_preview = preview(
        client,
        dataset["id"],
        [{
            "action": "rebuild_group_split",
            "finding_ids": ["entity-overlap-finding"],
            "entity_column": "patient_id",
            "split_column": "partition",
            "test_ratio": 0.34,
            "random_seed": 319,
        }],
    )
    assert result["plan"]["preview_digest"] == repeat_preview["plan"]["preview_digest"]
    assert result["plan"]["expected_final_row_count"] == 4
    assert result["plan"]["split_configurations"][0]["algorithm"] == (
        "sha256_seeded_entity_order_v1"
    )

    completed = execute(client, dataset["id"], result)
    assert completed.status_code == 201, completed.text
    output = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/dataset"
    )
    frame = pd.read_csv(io.BytesIO(output.content), dtype=str)
    assert frame.groupby("patient_id")["partition"].nunique().max() == 1
    assert completed.json()["plan"]["verification"]["checks"]["entity_groups_separated"]


def test_temporal_finding_requires_and_verifies_confirmed_chronological_cutoff(client):
    dataset = upload_csv(
        client,
        "temporal remediation",
        "id,event_time,partition,value\n"
        "1,2020-01-01,train,a\n"
        "2,2020-02-01,train,b\n"
        "3,2020-01-15,test,c\n"
        "4,2020-03-01,test,d\n",
    )
    add_finding(
        dataset["id"],
        "temporal-overlap-finding",
        "temporal_leakage",
        {
            "time_column": "event_time",
            "split_column": "partition",
            "detection": "temporal_overlap",
            "splits": {
                "train": {
                    "min_time": "2020-01-01T00:00:00",
                    "max_time": "2020-02-01T00:00:00",
                    "valid_rows": 2,
                },
                "test": {
                    "min_time": "2020-01-15T00:00:00",
                    "max_time": "2020-03-01T00:00:00",
                    "valid_rows": 2,
                },
            },
            "invalid_timestamp_rows": 0,
        },
    )
    result = preview(
        client,
        dataset["id"],
        [
            {
                "action": "rebuild_chronological_split",
                "finding_ids": ["temporal-overlap-finding"],
                "time_column": "event_time",
                "split_column": "partition",
                "cutoff": "2020-01-31",
            }
        ],
    )
    assert result["plan"]["expected_final_row_count"] == 4
    completed = execute(client, dataset["id"], result)
    assert completed.status_code == 201, completed.text
    output = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/dataset"
    )
    frame = pd.read_csv(io.BytesIO(output.content), dtype=str)
    train_max = pd.to_datetime(
        frame.loc[frame["partition"] == "train", "event_time"]
    ).max()
    test_min = pd.to_datetime(
        frame.loc[frame["partition"] == "test", "event_time"]
    ).min()
    assert train_max < test_min
    assert completed.json()["plan"]["verification"]["checks"][
        "chronological_order_verified"
    ]


def test_contamination_remediation_requires_explicit_retained_partition(client):
    dataset = upload_csv(
        client,
        "contamination remediation",
        "id,feature,partition\n1,same,train\n2,other,train\n"
        "3,same,test\n4,last,test\n",
    )
    frame = pd.read_csv(
        ORIGINAL_DIR / dataset["storage_filename"],
        dtype=str,
    )
    hash_frame = frame.drop(columns=["partition", "id"])
    same_hash = hash_row(hash_frame.iloc[0])
    add_finding(
        dataset["id"],
        "contamination-finding",
        "train_test_contamination",
        {
            "split_column": "partition",
            "detection": "exact_row_hash_overlap",
            "row_hash": same_hash,
            "splits": ["test", "train"],
            "row_indices": {"train": [0], "test": [2]},
            "column_count": 2,
        },
    )
    without_policy = client.post(
        f"/api/v1/datasets/{dataset['id']}/remediation-plans/preview",
        json={
            "actions": [
                {
                    "action": "exclude_contaminated_copies",
                    "finding_ids": ["contamination-finding"],
                    "split_column": "partition",
                }
            ]
        },
    )
    assert without_policy.status_code == 422
    assert "retained_partition" in str(without_policy.json()["detail"])

    result = preview(
        client,
        dataset["id"],
        [
            {
                "action": "exclude_contaminated_copies",
                "finding_ids": ["contamination-finding"],
                "split_column": "partition",
                "retained_partition": "train",
            }
        ],
    )
    assert result["plan"]["affected_source_row_positions_preview"] == [2]
    assert result["plan"]["affected_source_row_positions_count"] == 1
    completed = execute(client, dataset["id"], result)
    assert completed.status_code == 201, completed.text
    output = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/dataset"
    )
    cleaned = pd.read_csv(io.BytesIO(output.content), dtype=str)
    assert "same" in cleaned["feature"].tolist()
    assert cleaned.loc[cleaned["feature"] == "same", "partition"].tolist() == ["train"]
    assert completed.json()["plan"]["verification"]["checks"][
        "selected_contamination_groups_separated"
    ]


def test_all_eligible_selection_is_resolved_and_validated_by_backend(client):
    dataset = upload_csv(
        client,
        "select all duplicates",
        "id,value\n1,a\n2,a\n3,b\n4,b\n",
    )
    frame = pd.read_csv(ORIGINAL_DIR / dataset["storage_filename"], dtype=str)
    hash_frame = frame.drop(columns=["id"])
    for finding_id, indices in (("all-a", [0, 1]), ("all-b", [2, 3])):
        add_finding(
            dataset["id"],
            finding_id,
            "exact_duplicate",
            {
                "hash": hash_row(hash_frame.iloc[indices[0]]),
                "duplicate_count": 2,
                "row_indices": indices,
                "hash_excluded_columns": ["id"],
            },
        )
    result = preview(
        client,
        dataset["id"],
        [
            {
                "action": "exact_duplicate_keep_first",
                "selection_mode": "all_eligible",
                "finding_type": "exact_duplicate",
            }
        ],
    )
    assert result["plan"]["selected_count"] == 2
    assert result["plan"]["applied_count"] == 2
    assert result["plan"]["affected_source_row_positions_count"] == 2
    assert result["plan"]["selected_finding_ids_truncated"] is False


def test_changed_finding_evidence_stales_preview_and_original_is_unchanged(client):
    dataset = upload_csv(client, "stale remediation", "id,value\n1,a\n2,a\n")
    frame = pd.read_csv(ORIGINAL_DIR / dataset["storage_filename"], dtype=str)
    add_finding(
        dataset["id"],
        "stale-finding",
        "exact_duplicate",
        {
            "hash": hash_row(frame.drop(columns=["id"]).iloc[0]),
            "duplicate_count": 2,
            "row_indices": [0, 1],
            "hash_excluded_columns": ["id"],
        },
    )
    source_path = ORIGINAL_DIR / dataset["storage_filename"]
    original_bytes = source_path.read_bytes()
    result = preview(
        client,
        dataset["id"],
        [
            {
                "action": "exact_duplicate_keep_first",
                "finding_ids": ["stale-finding"],
            }
        ],
    )
    db = app.db.session.TestingSessionLocal()
    try:
        finding = db.query(leakage_models.LeakageFinding).filter_by(
            id="stale-finding"
        ).one()
        finding.description = "Finding changed after preview"
        db.commit()
    finally:
        db.close()
    stale = execute(client, dataset["id"], result)
    assert stale.status_code == 409
    assert "changed after preview" in stale.json()["detail"]
    assert source_path.read_bytes() == original_bytes
    operations = client.get(
        f"/api/v1/datasets/{dataset['id']}/remediation-plans"
    ).json()["items"]
    assert operations[0]["status"] == "stale"


def test_changed_original_file_stales_preview_without_overwriting_source(client):
    dataset = upload_csv(client, "source staleness", "id,value\n1,a\n2,a\n")
    frame = pd.read_csv(ORIGINAL_DIR / dataset["storage_filename"], dtype=str)
    add_finding(
        dataset["id"],
        "source-stale-finding",
        "exact_duplicate",
        {
            "hash": hash_row(frame.drop(columns=["id"]).iloc[0]),
            "duplicate_count": 2,
            "row_indices": [0, 1],
            "hash_excluded_columns": ["id"],
        },
    )
    source_path = ORIGINAL_DIR / dataset["storage_filename"]
    result = preview(
        client,
        dataset["id"],
        [{
            "action": "exact_duplicate_keep_first",
            "finding_ids": ["source-stale-finding"],
        }],
    )
    changed_source = b"id,value\n1,a\n2,changed\n"
    source_path.write_bytes(changed_source)
    stale = execute(client, dataset["id"], result)
    assert stale.status_code == 409
    assert source_path.read_bytes() == changed_source
    operations = client.get(
        f"/api/v1/datasets/{dataset['id']}/remediation-plans"
    ).json()["items"]
    assert operations[0]["status"] == "stale"


def test_entity_overlap_quarantine_creates_separate_verified_quarantine_artifact(client):
    dataset = upload_csv(
        client,
        "entity quarantine plan",
        "id,patient_id,value,partition\n"
        "1,p1,a,train\n2,p1,b,test\n3,p2,c,train\n",
    )
    source_path = ORIGINAL_DIR / dataset["storage_filename"]
    original_bytes = source_path.read_bytes()
    add_finding(
        dataset["id"],
        "entity-quarantine-finding",
        "entity_overlap",
        {
            "entity_column": "patient_id",
            "split_column": "partition",
            "entity_value": "p1",
            "splits": ["train", "test"],
            "row_indices": {"train": [0], "test": [1]},
        },
    )
    result = preview(
        client,
        dataset["id"],
        [{
            "action": "quarantine_evidenced_rows",
            "finding_ids": ["entity-quarantine-finding"],
        }],
    )
    assert result["plan"]["affected_source_row_positions_preview"] == [0, 1]
    completed = execute(client, dataset["id"], result)
    assert completed.status_code == 201, completed.text
    operation = completed.json()
    assert operation["plan"]["verification"]["checks"]["entity_groups_separated"]
    assert source_path.read_bytes() == original_bytes

    cleaned = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/dataset"
    )
    quarantined = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/quarantine"
    )
    assert cleaned.status_code == quarantined.status_code == 200
    assert pd.read_csv(io.BytesIO(cleaned.content))["patient_id"].tolist() == ["p2"]
    assert pd.read_csv(io.BytesIO(quarantined.content))["patient_id"].tolist() == ["p1", "p1"]


def test_remediation_endpoints_enforce_dataset_ownership(client):
    dataset = upload_csv(client, "foreign remediation", "id,value\n1,a\n2,a\n")
    db = app.db.session.TestingSessionLocal()
    try:
        other_user = models.User(
            id="another-owner",
            email="another-remediation-owner@example.test",
            display_name="Other",
            password_hash="test-only",
        )
        db.add(other_user)
        db.commit()
        saved = db.query(models.Dataset).filter_by(id=dataset["id"]).one()
        saved.owner_user_id = other_user.id
        db.commit()
    finally:
        db.close()
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/remediation-plans/preview",
        json={
            "actions": [
                {
                    "action": "review_only",
                    "selection_mode": "all_eligible",
                    "finding_type": "exact_duplicate",
                }
            ]
        },
    )
    assert response.status_code == 404


def test_review_only_can_create_a_manifest_without_claiming_finding_repaired(client):
    dataset = upload_csv(client, "review output", "id,value\n1,a\n2,b\n")
    add_finding(
        dataset["id"],
        "review-only-finding",
        "temporal_leakage",
        {"time_column": "event_time"},
    )
    result = preview(
        client,
        dataset["id"],
        [
            {
                "action": "review_only",
                "finding_ids": ["review-only-finding"],
            }
        ],
    )
    assert result["plan"]["applied_count"] == 0
    completed = execute(client, dataset["id"], result)
    assert completed.status_code == 201
    data = completed.json()
    assert data["plan"]["final_status"] == "review_required"
    assert data["plan"]["unresolved_findings_count"] == 1
    assert data["status"] == "completed"


@pytest.mark.parametrize(
    "bad_body",
    [
        {"actions": []},
        {
            "actions": [
                {
                    "action": "exclude_contaminated_copies",
                    "selection_mode": "all_eligible",
                    "finding_type": "entity_overlap",
                }
            ]
        },
        {
            "actions": [
                {
                    "action": "rebuild_group_split",
                    "finding_ids": ["id"],
                    "entity_column": "entity",
                    "split_column": "split",
                    "test_ratio": 1.0,
                    "random_seed": 0,
                }
            ]
        },
    ],
)
def test_schema_rejects_invalid_remediation_configuration(client, bad_body):
    dataset = upload_csv(client, "invalid configuration", "id,value\n1,a\n")
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/remediation-plans/preview",
        json=bad_body,
    )
    assert response.status_code == 422
