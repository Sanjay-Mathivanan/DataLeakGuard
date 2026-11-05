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


def set_analysis_configuration(
    dataset_id: str,
    *,
    target_column: str | None,
    entity_column: str | None,
    time_column: str | None,
    split_column: str | None,
    split_strategy: dict,
) -> None:
    db = app.db.session.TestingSessionLocal()
    try:
        dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
        assert dataset is not None
        profile = dict(dataset.profile or {})
        profile["analysis_columns"] = {
            "target_column": target_column,
            "entity_column": entity_column,
            "time_column": time_column,
            "split_column": split_column,
        }
        profile["split_strategy"] = split_strategy
        dataset.profile = profile
        db.add(dataset)
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
    assert result["plan"]["feature_exclusion_reasons"]["confirmed_leak"]["finding_ids"] == [
        "target-exclusion-finding"
    ]
    assert result["plan"]["analysis_configuration"]["target_column"] is None
    assert result["plan"]["missing_value_counts_before"] == {}
    assert result["plan"]["missing_value_counts_after"] == {}

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
    assert operation["plan"]["verification"]["checks"]["selected_target_features_excluded"]
    assert operation["plan"]["verified_finding_ids"] == ["target-exclusion-finding"]
    db = app.db.session.TestingSessionLocal()
    try:
        finding = db.query(leakage_models.LeakageFinding).filter_by(
            id="target-exclusion-finding"
        ).one()
        assert finding.status == "resolved"
        assert finding.evidence["remediation_verification"]["status"] == "verified"
    finally:
        db.close()


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
    set_analysis_configuration(
        dataset["id"],
        target_column="value",
        entity_column="patient_id",
        time_column=None,
        split_column="partition",
        split_strategy={
            "strategy": "existing",
            "source": "user_confirmed_dataset_column",
            "test_ratio": 0.34,
            "random_seed": 319,
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
            "target_column": "value",
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
            "target_column": "value",
            "test_ratio": 0.34,
            "random_seed": 319,
        }],
    )
    assert result["plan"]["preview_digest"] == repeat_preview["plan"]["preview_digest"]
    assert result["plan"]["analysis_configuration"]["entity_column"] == "patient_id"
    assert result["plan"]["analysis_configuration"]["target_column"] == "value"
    assert result["plan"]["expected_final_row_count"] == 4
    assert result["plan"]["split_configurations"][0]["algorithm"] == (
        "sha256_seeded_greedy_group_target_balance_v1"
    )
    assert result["plan"]["split_configurations"][0]["target_column"] == "value"

    completed = execute(client, dataset["id"], result)
    assert completed.status_code == 201, completed.text
    output = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/dataset"
    )
    frame = pd.read_csv(io.BytesIO(output.content), dtype=str)
    assert frame.groupby("patient_id")["partition"].nunique().max() == 1
    assert completed.json()["plan"]["verification"]["checks"]["entity_groups_separated"]
    manifest = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/manifest"
    ).json()
    assert manifest["entity_column"] == "patient_id"
    assert manifest["target_column"] == "value"
    assert manifest["split_strategy"] == "existing"
    assert manifest["configuration_snapshot"]["entity_column"] == "patient_id"
    assert manifest["final_row_count"] == len(frame) == 4
    assert manifest["final_column_count"] == len(frame.columns)
    assert manifest["imputation_strategies"] == []
    assert manifest["verified_finding_ids"] == ["entity-overlap-finding"]
    assert manifest["unresolved_findings_count"] == 0
    db = app.db.session.TestingSessionLocal()
    try:
        finding = db.query(leakage_models.LeakageFinding).filter_by(
            id="entity-overlap-finding"
        ).one()
        assert finding.status == "resolved"
    finally:
        db.close()


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
    verification = operation["plan"]["verification"]
    assert operation["status"] == "completed", {
        key: value
        for key, value in verification["checks"].items()
        if value is not True
    }
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


def test_selected_duplicate_and_contamination_verification_share_stable_row_identity(client):
    # Arbitrary, non-domain-specific columns make this a regression test for
    # source row identity across duplicate removal, split rewriting, and feature
    # exclusion in one deterministic plan.
    csv_text = (
        "record_key,target_code,unsafe_input,event_clock,fold,entity_key,reading\n"
        "r-a,positive,positive,2022-01-10,train,g-1,shared\n"
        "r-b,positive,positive,2022-03-10,test,g-1,shared\n"
        "r-c,negative,negative,2022-03-01,train,g-2,other-train\n"
        "r-d,negative,negative,2022-02-15,test,g-3,other-test\n"
        "r-e,positive,positive,2022-01-15,train,g-4,other-1\n"
        "r-f,negative,negative,2022-01-25,train,g-5,other-2\n"
        "r-g,positive,positive,2022-02-10,test,g-6,other-3\n"
        "r-h,negative,negative,2022-04-01,test,g-7,other-4\n"
    )
    dataset = upload_csv(client, "arbitrary identity regression", csv_text)
    frame = pd.read_csv(
        ORIGINAL_DIR / dataset["storage_filename"], dtype=str
    )

    duplicate_hash = hash_row(
        frame.drop(columns=["record_key", "event_clock", "fold"]).iloc[0]
    )
    add_finding(
        dataset["id"],
        "arbitrary-duplicate",
        "exact_duplicate",
        {
            "hash": duplicate_hash,
            "duplicate_count": 2,
            "row_indices": [0, 1],
            "hash_excluded_columns": ["record_key", "event_clock", "fold"],
        },
    )
    contamination_hash = hash_row(frame[["unsafe_input", "reading"]].iloc[0])
    add_finding(
        dataset["id"],
        "arbitrary-contamination",
        "train_test_contamination",
        {
            "split_column": "fold",
            "detection": "configured_key_hash_overlap",
            "row_hash": contamination_hash,
            "splits": ["test", "train"],
            "row_indices": {"train": [0], "test": [1]},
            "matching_fields": ["unsafe_input", "reading"],
        },
    )
    add_finding(
        dataset["id"],
        "arbitrary-target",
        "target_leakage",
        {
            "target_column": "target_code",
            "feature_column": "unsafe_input",
            "detection": "exact_target_duplicate",
            "matching_rows": 8,
            "total_valid_rows": 8,
        },
    )
    add_finding(
        dataset["id"],
        "arbitrary-temporal",
        "temporal_leakage",
        {
            "time_column": "event_clock",
            "split_column": "fold",
            "detection": "temporal_overlap",
            "splits": {
                "train": {
                    "min_time": "2022-01-10T00:00:00",
                    "max_time": "2022-03-01T00:00:00",
                    "valid_rows": 4,
                },
                "test": {
                    "min_time": "2022-02-10T00:00:00",
                    "max_time": "2022-04-01T00:00:00",
                    "valid_rows": 4,
                },
            },
            "invalid_timestamp_rows": 0,
        },
    )
    set_analysis_configuration(
        dataset["id"],
        target_column="target_code",
        entity_column="entity_key",
        time_column="event_clock",
        split_column="fold",
        split_strategy={
            "strategy": "existing",
            "source": "user_confirmed_dataset_column",
            "test_ratio": 0.5,
            "random_seed": 29,
        },
    )

    result = preview(
        client,
        dataset["id"],
        [
            {
                "action": "exact_duplicate_keep_first",
                "finding_ids": ["arbitrary-duplicate"],
            },
            {
                "action": "exclude_contaminated_copies",
                "finding_ids": ["arbitrary-contamination"],
                "split_column": "fold",
                "retained_partition": "train",
            },
            {
                "action": "exclude_target_features",
                "finding_ids": ["arbitrary-target"],
                "target_column": "target_code",
                "feature_columns": ["unsafe_input"],
            },
            {
                "action": "rebuild_chronological_split",
                "finding_ids": ["arbitrary-temporal"],
                "time_column": "event_clock",
                "split_column": "fold",
                "cutoff": "2022-02-20",
            },
        ],
    )
    plan = result["plan"]
    assert plan["expected_final_row_count"] == 7
    assert plan["expected_output_source_row_identities_sha256"]
    assert plan["row_identity_scheme"] == "source_sha256_plus_zero_based_position_v1"

    completed = execute(client, dataset["id"], result)
    assert completed.status_code == 201, completed.text
    operation = completed.json()
    verification = operation["plan"]["verification"]
    assert verification["checks"]["output_source_identity_mapping_matches_plan"]
    assert verification["checks"]["output_source_identity_content_matches"]
    assert verification["checks"]["selected_exact_duplicate_groups_resolved"]
    assert verification["checks"]["selected_contamination_groups_separated"]
    assert verification["checks"]["chronological_order_verified"]
    assert verification["finding_verification"][
        "arbitrary-contamination"
    ]["verification_basis"] == (
        "source_row_identity_and_verified_projection_after_feature_exclusion"
    )
    assert set(operation["plan"]["verified_finding_ids"]) == {
        "arbitrary-duplicate",
        "arbitrary-contamination",
        "arbitrary-target",
        "arbitrary-temporal",
    }

    output = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/dataset"
    )
    cleaned = pd.read_csv(io.BytesIO(output.content), dtype=str)
    assert cleaned["record_key"].tolist() == [
        "r-a",
        "r-c",
        "r-d",
        "r-e",
        "r-f",
        "r-g",
        "r-h",
    ]
    assert "unsafe_input" not in cleaned.columns
    assert len(cleaned["target_code"]) == 7
    train_max = pd.to_datetime(
        cleaned.loc[cleaned["fold"] == "train", "event_clock"]
    ).max()
    test_min = pd.to_datetime(
        cleaned.loc[cleaned["fold"] == "test", "event_clock"]
    ).min()
    assert train_max < test_min

    report = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/report"
    )
    report_rows = pd.read_csv(io.BytesIO(report.content), dtype=str)
    assert set(report_rows["status"]) == {"included"}
    manifest = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/manifest"
    ).json()
    assert manifest["final_status"] == "fully_remediated_for_selected_rules", {
        "verification_status": manifest["verification"]["status"],
        "detector_results_after": manifest["detector_results_after"],
        "unresolved_findings_count": manifest["unresolved_findings_count"],
        "finding_verification": manifest["verification"].get(
            "finding_verification"
        ),
    }
    assert manifest["verification"]["checks"]["selected_exact_duplicate_groups_resolved"]
    assert manifest["verification"]["checks"]["selected_contamination_groups_separated"]
    assert manifest["verified_finding_ids"] == sorted(
        {
            "arbitrary-duplicate",
            "arbitrary-contamination",
            "arbitrary-target",
            "arbitrary-temporal",
        }
    )


def test_preview_rejects_chronological_split_that_moves_retained_contamination_row(client):
    dataset = upload_csv(
        client,
        "incompatible partition constraints",
        "record,value,event_clock,fold\n"
        "a,match,2022-01-01,train\n"
        "b,match,2022-01-02,test\n"
        "c,train-only,2022-03-01,train\n"
        "d,test-only,2022-02-15,test\n",
    )
    frame = pd.read_csv(
        ORIGINAL_DIR / dataset["storage_filename"], dtype=str
    )
    matching_hash = hash_row(frame[["value"]].iloc[0])
    add_finding(
        dataset["id"],
        "constraint-contamination",
        "train_test_contamination",
        {
            "split_column": "fold",
            "row_hash": matching_hash,
            "row_indices": {"train": [0], "test": [1]},
            "matching_fields": ["value"],
        },
    )
    add_finding(
        dataset["id"],
        "constraint-temporal",
        "temporal_leakage",
        {
            "time_column": "event_clock",
            "split_column": "fold",
            "splits": {
                "train": {
                    "min_time": "2022-01-01T00:00:00",
                    "max_time": "2022-03-01T00:00:00",
                    "valid_rows": 2,
                },
                "test": {
                    "min_time": "2022-01-02T00:00:00",
                    "max_time": "2022-02-15T00:00:00",
                    "valid_rows": 2,
                },
            },
            "invalid_timestamp_rows": 0,
        },
    )

    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/remediation-plans/preview",
        json={
            "actions": [
                {
                    "action": "exclude_contaminated_copies",
                    "finding_ids": ["constraint-contamination"],
                    "split_column": "fold",
                    "retained_partition": "test",
                },
                {
                    "action": "rebuild_chronological_split",
                    "finding_ids": ["constraint-temporal"],
                    "time_column": "event_clock",
                    "split_column": "fold",
                    "cutoff": "2022-02-01",
                },
            ]
        },
    )
    assert response.status_code == 409
    assert "conflicts with the explicitly retained partition" in str(
        response.json()["detail"]
    )


def test_duplicate_detector_cannot_resolve_a_selected_group_without_its_canonical_row():
    from app.services.remediation_service import (
        _sha256_json,
        _post_remediation_detector_results,
        _reconcile_selected_finding_detector_status,
        _source_row_identity,
        _verified_finding_ids,
        _verify_plan,
    )

    source = pd.DataFrame(
        {
            "arbitrary_key": ["x1", "x2", "y1"],
            "measure": ["same", "same", "other"],
            "partition_name": ["left", "right", "right"],
        }
    )
    plan = {
        "original_file_sha256": "a" * 64,
        "expected_output_source_row_positions_sha256": _sha256_json([2]),
        "expected_output_source_row_identities_sha256": _sha256_json(
            [_source_row_identity("a" * 64, 2)]
        ),
        "applied_finding_ids": ["duplicate-without-canonical"],
        "action_results": [
            {
                "action": "exact_duplicate_keep_first",
                "applied_finding_ids": ["duplicate-without-canonical"],
            }
        ],
        "finding_snapshot": [
            {
                "id": "duplicate-without-canonical",
                "finding_type": "exact_duplicate",
                "evidence": {
                    "row_indices": [0, 1],
                    "hash_excluded_columns": ["arbitrary_key", "partition_name"],
                },
            }
        ],
        "duplicate_group_constraints": [
            {
                "finding_id": "duplicate-without-canonical",
                "source_row_positions": [0, 1],
                "source_row_identities": [
                    _source_row_identity("a" * 64, 0),
                    _source_row_identity("a" * 64, 1),
                ],
                "keep_first_source_row_position": 0,
                "keep_first_source_row_identity": _source_row_identity(
                    "a" * 64, 0
                ),
            }
        ],
        "excluded_feature_columns": [],
        "expected_final_row_count": 1,
        "expected_output_change": True,
        "split_updates": {},
    }
    output = source.iloc[[2]].reset_index(drop=True)
    verification = _verify_plan(
        output_frame=output,
        output_source_row_positions=[2],
        quarantine_frame=None,
        quarantine_source_row_positions=[],
        source_frame=source,
        plan=plan,
    )
    detector = _post_remediation_detector_results(
        output,
        {
            "split_column": None,
            "split_strategy": "none",
        },
    )
    assert detector["exact_duplicate"]["status"] == "passed"
    assert verification["checks"]["selected_exact_duplicate_groups_resolved"] is False
    _reconcile_selected_finding_detector_status(detector, plan, set())
    assert detector["exact_duplicate"]["status"] == "review_required"
    assert detector["exact_duplicate"]["selected_finding_verification_failed"] is True
    assert _verified_finding_ids(
        plan,
        {
            **verification["checks"],
            "output_source_identity_mapping_matches_plan": True,
            "output_source_identity_content_matches": True,
            "output_bytes_round_trip_matches": True,
            "source_sha256_unchanged": True,
            "final_sha256_matches_output": True,
            "output_schema_matches_expected": True,
            "output_row_count_matches_expected": True,
        },
        verification["finding_checks"],
    ) == []


def test_failed_identity_verification_agrees_in_report_manifest_and_detector_state(
    client, monkeypatch
):
    from app.services import remediation_service

    dataset = upload_csv(
        client,
        "failed identity report regression",
        "record,value\nk-1,same\nk-2,same\nk-3,unique\n",
    )
    frame = pd.read_csv(
        ORIGINAL_DIR / dataset["storage_filename"], dtype=str
    )
    duplicate_hash = hash_row(frame.drop(columns=["record"]).iloc[0])
    add_finding(
        dataset["id"],
        "failed-identity-duplicate",
        "exact_duplicate",
        {
            "hash": duplicate_hash,
            "duplicate_count": 2,
            "row_indices": [0, 1],
            "hash_excluded_columns": ["record"],
        },
    )
    result = preview(
        client,
        dataset["id"],
        [
            {
                "action": "exact_duplicate_keep_first",
                "finding_ids": ["failed-identity-duplicate"],
            }
        ],
    )

    original_transform = remediation_service._execute_transform

    def wrong_identity_mapping(source, plan):
        output, quarantine, _, quarantine_positions = original_transform(
            source, plan
        )
        # The file bytes still contain the actual kept-first output, but this
        # deliberately incorrect mapping says the later duplicate survived.
        return output, quarantine, [1, 2], quarantine_positions

    monkeypatch.setattr(
        remediation_service, "_execute_transform", wrong_identity_mapping
    )
    completed = execute(client, dataset["id"], result)
    assert completed.status_code == 201, completed.text
    operation = completed.json()
    verification = operation["plan"]["verification"]
    assert operation["status"] == "failed"
    assert verification["checks"]["selected_exact_duplicate_groups_resolved"] is False
    assert (
        verification["detector_results_after"]["exact_duplicate"]["status"]
        == "review_required"
    )
    assert operation["plan"]["verified_finding_ids"] == []
    assert operation["plan"]["final_status"] == "failed"

    report_response = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/report"
    )
    assert report_response.status_code == 200
    report = pd.read_csv(io.BytesIO(report_response.content), dtype=str)
    assert report.iloc[0]["status"] == "failed_verification"

    manifest_response = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/manifest"
    )
    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    assert manifest["final_status"] == "failed"
    assert manifest["verification"]["detector_results_after"][
        "exact_duplicate"
    ]["status"] == "review_required"
    assert manifest["verified_finding_ids"] == []
    assert manifest["unresolved_findings_count"] == 1

    db = app.db.session.TestingSessionLocal()
    try:
        finding = db.query(leakage_models.LeakageFinding).filter_by(
            id="failed-identity-duplicate"
        ).one()
        assert finding.status == "open"
    finally:
        db.close()


def test_contamination_cannot_pass_when_all_selected_copies_disappear():
    from app.services.remediation_service import (
        _post_remediation_detector_results,
        _reconcile_selected_finding_detector_status,
        _sha256_json,
        _source_row_identity,
        _verify_plan,
    )

    source = pd.DataFrame(
        {
            "record_code": ["c-1", "c-2", "c-3"],
            "match_key": ["same", "same", "unique"],
            "split_name": ["left", "right", "left"],
        }
    )
    source_hash = "c" * 64
    row_hash = hash_row(source[["match_key"]].iloc[0])
    expected_positions = [2]
    plan = {
        "original_file_sha256": source_hash,
        "expected_output_source_row_positions_sha256": _sha256_json(
            expected_positions
        ),
        "expected_output_source_row_identities_sha256": _sha256_json(
            [_source_row_identity(source_hash, 2)]
        ),
        "applied_finding_ids": ["contamination-without-retained-copy"],
        "finding_snapshot": [
            {
                "id": "contamination-without-retained-copy",
                "finding_type": "train_test_contamination",
                "evidence": {},
            }
        ],
        "action_results": [
            {
                "action": "exclude_contaminated_copies",
                "applied_finding_ids": [
                    "contamination-without-retained-copy"
                ],
            }
        ],
        "contamination_constraints": [
            {
                "finding_id": "contamination-without-retained-copy",
                "action": "exclude_contaminated_copies",
                "split_column": "split_name",
                "row_hash": row_hash,
                "matching_fields": ["match_key"],
                "retained_partition": "right",
                "retained_source_row_positions": [1],
                "retained_source_row_identities": [
                    _source_row_identity(source_hash, 1)
                ],
                "excluded_source_row_positions": [0],
                "excluded_source_row_identities": [
                    _source_row_identity(source_hash, 0)
                ],
            }
        ],
        "excluded_feature_columns": [],
        "expected_final_row_count": 1,
        "expected_output_change": True,
        "split_updates": {},
        "quarantine_source_row_positions": [],
    }
    output = source.iloc[[2]].reset_index(drop=True)
    verification = _verify_plan(
        output_frame=output,
        output_source_row_positions=expected_positions,
        quarantine_frame=None,
        quarantine_source_row_positions=[],
        source_frame=source,
        plan=plan,
    )
    detector = _post_remediation_detector_results(
        output,
        {"split_column": "split_name", "split_strategy": "existing"},
    )
    assert detector["train_test_contamination"]["status"] == "passed"
    assert (
        verification["checks"]["selected_contamination_groups_separated"]
        is False
    )
    assert (
        verification["finding_checks"][
            "contamination-without-retained-copy"
        ]["selected_contamination_group_policy_verified"]
        is False
    )
    _reconcile_selected_finding_detector_status(detector, plan, set())
    assert detector["train_test_contamination"]["status"] == "review_required"


def test_contamination_verification_survives_excluding_its_evidenced_feature(
    client,
):
    """Feature exclusion must not invalidate source-identity remediation proof."""
    dataset = upload_csv(
        client,
        "excluded contamination evidence",
        "record_token,target_label,leak_marker,partition\n"
        "source-train,positive,positive,train\n"
        "source-test,positive,positive,test\n",
    )
    source_path = ORIGINAL_DIR / dataset["storage_filename"]
    source_bytes = source_path.read_bytes()
    frame = pd.read_csv(
        source_path, dtype=str
    )
    duplicate_hash = hash_row(
        frame.drop(columns=["record_token", "partition"]).iloc[0]
    )
    contamination_hash = hash_row(frame[["leak_marker"]].iloc[0])
    add_finding(
        dataset["id"],
        "excluded-feature-duplicate",
        "exact_duplicate",
        {
            "hash": duplicate_hash,
            "duplicate_count": 2,
            "row_indices": [0, 1],
            "hash_excluded_columns": ["record_token", "partition"],
        },
    )
    add_finding(
        dataset["id"],
        "excluded-feature-contamination",
        "train_test_contamination",
        {
            "split_column": "partition",
            "detection": "configured_key_hash_overlap",
            "row_hash": contamination_hash,
            "splits": ["test", "train"],
            "row_indices": {"train": [0], "test": [1]},
            "matching_fields": ["leak_marker"],
        },
    )
    add_finding(
        dataset["id"],
        "excluded-feature-target",
        "target_leakage",
        {
            "target_column": "target_label",
            "feature_column": "leak_marker",
            "detection": "exact_target_duplicate",
            "matching_rows": 2,
            "total_valid_rows": 2,
        },
    )
    set_analysis_configuration(
        dataset["id"],
        target_column="target_label",
        entity_column=None,
        time_column=None,
        split_column="partition",
        split_strategy={"strategy": "existing"},
    )

    result = preview(
        client,
        dataset["id"],
        [
            {
                "action": "exact_duplicate_keep_first",
                "finding_ids": ["excluded-feature-duplicate"],
            },
            {
                "action": "exclude_contaminated_copies",
                "finding_ids": ["excluded-feature-contamination"],
                "split_column": "partition",
                "retained_partition": "train",
            },
            {
                "action": "exclude_target_features",
                "finding_ids": ["excluded-feature-target"],
                "target_column": "target_label",
                "feature_columns": ["leak_marker"],
            },
        ],
    )
    completed = execute(client, dataset["id"], result)
    assert completed.status_code == 201, completed.text
    operation = completed.json()
    verification = operation["plan"]["verification"]

    assert (
        verification["detector_results_after"]["train_test_contamination"][
            "remaining_condition_count"
        ]
        == 0
    )
    assert (
        verification["detector_results_after"]["train_test_contamination"][
            "status"
        ]
        == "passed"
    )
    assert (
        verification["checks"]["selected_contamination_groups_separated"]
        is True
    )
    assert verification["status"] == "verified"
    assert operation["status"] == "completed"
    assert (
        verification["finding_verification"][
            "excluded-feature-contamination"
        ]["status"]
        == "verified"
    )
    assert (
        verification["finding_verification"][
            "excluded-feature-contamination"
        ]["verification_basis"]
        == "source_row_identity_and_verified_projection_after_feature_exclusion"
    )
    assert operation["plan"]["verified_finding_ids"] == [
        "excluded-feature-contamination",
        "excluded-feature-duplicate",
        "excluded-feature-target",
    ]

    output = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/dataset"
    )
    assert output.status_code == 200
    cleaned = pd.read_csv(io.BytesIO(output.content), dtype=str)
    assert source_path.read_bytes() == source_bytes
    assert cleaned["record_token"].tolist() == ["source-train"]
    assert cleaned["partition"].tolist() == ["train"]
    assert cleaned["target_label"].tolist() == ["positive"]
    assert "leak_marker" not in cleaned.columns

    manifest = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/manifest"
    ).json()
    assert manifest["final_status"] == "fully_remediated_for_selected_rules"
    assert manifest["verification"]["checks"][
        "selected_contamination_groups_separated"
    ] is True
    assert manifest["verification"]["finding_verification"][
        "excluded-feature-contamination"
    ]["verification_basis"] == (
        "source_row_identity_and_verified_projection_after_feature_exclusion"
    )
    report = client.get(
        f"/api/v1/operations/{result['id']}/remediation-artifacts/report"
    )
    report_rows = pd.read_csv(io.BytesIO(report.content), dtype=str)
    statuses = dict(zip(report_rows["finding_id"], report_rows["status"]))
    assert statuses["excluded-feature-contamination"] == "included"
    db = app.db.session.TestingSessionLocal()
    try:
        finding = db.query(leakage_models.LeakageFinding).filter_by(
            id="excluded-feature-contamination"
        ).one()
        assert finding.status == "resolved"
    finally:
        db.close()


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
