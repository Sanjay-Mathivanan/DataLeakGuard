import pandas as pd
import pytest

import app.db.session
from app.db import models


SCHEMA_CASES = [
    ("manufacturing", "equipment_group", "phase_name", "failure_state", "measured_at", "encoded_failure", "record_token"),
    ("healthcare", "care_pathway", "evaluation_arm", "revisit_state", "documented_at", "encoded_revisit", "encounter_token"),
    ("finance", "portfolio_slice", "holdout_group", "default_state", "valued_on", "encoded_default", "transaction_token"),
    ("education", "course_cohort", "assessment_arm", "completion_state", "recorded_on", "encoded_completion", "learner_token"),
    ("retail", "market_segment", "validation_batch", "return_state", "sold_at", "encoded_return", "order_token"),
]


def _upload(client, name: str, frame: pd.DataFrame) -> dict:
    response = client.post(
        "/api/v1/datasets",
        data={
            "name": f"{name} arbitrary-schema fixture",
            "type": "tabular",
            "format": "CSV",
            "description": "synthetic detector regression input",
        },
        files={
            "file": (
                f"{name}.csv",
                frame.to_csv(index=False).encode("utf-8"),
                "text/csv",
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    "domain,entity_a,split,target,time_column,encoded_feature,record_token",
    SCHEMA_CASES,
)
def test_configured_columns_drive_detectors_for_unrelated_domain_schemas(
    client,
    domain,
    entity_a,
    split,
    target,
    time_column,
    encoded_feature,
    record_token,
):
    entity_b = f"{entity_a}_component"
    exact_target_copy = f"{target}_snapshot"
    frame = pd.DataFrame(
        {
            entity_a: ["group-a", "group-a", "group-b", "group-c", "", "group-d"],
            entity_b: ["unit-1", "unit-1", "unit-2", "unit-3", "unit-4", "unit-5"],
            split: ["train", "test", "train", "test", "test", "train"],
            target: ["high", "high", "low", "high", "low", "low"],
            time_column: [
                "2025-01-01T00:00:00+02:00",
                "2025-01-01T00:00:00+02:00",
                "2025-01-03T00:00:00Z",
                "2025-01-04T00:00:00-05:00",
                "not-a-date",
                "2025-01-05T00:00:00Z",
            ],
            exact_target_copy: ["high", "high", "low", "high", "low", "low"],
            encoded_feature: [1, 1, 0, 1, 0, 0],
            record_token: ["shared-token", "shared-token"]
            + [f"token-{index}" for index in range(2, 6)],
            "measure": [11, 11, 12, 13, 14, 15],
        }
    )
    dataset = _upload(client, domain, frame)
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params=[
            ("split_strategy", "existing"),
            ("split_column", split),
            ("target_column", target),
            ("time_column", time_column),
            ("entity_columns", entity_a),
            ("entity_columns", entity_b),
        ],
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["analysis_configuration"]["entity_columns"] == [entity_a, entity_b]
    assert result["analysis_configuration"]["target_column"] == target
    assert result["analysis_configuration"]["time_column"] == time_column

    entity_evidence = next(
        evidence
        for finding_type, evidence in (
            (item["finding_type"], item["evidence"]) for item in result["findings"]
        )
        if finding_type == "entity_overlap"
    )
    assert entity_evidence["entity_columns"] == [entity_a, entity_b]
    assert entity_evidence["row_indices"]["train"] == [0]
    assert entity_evidence["row_indices"]["test"] == [1]
    assert entity_evidence["missing_entity_key_row_count"] == 1
    assert result["detector_applicability"]["entity_overlap"]["status"] == "review_required"

    target_findings = [
        item for item in result["findings"] if item["finding_type"] == "target_leakage"
    ]
    target_evidence = {item["evidence"]["feature_column"]: item["evidence"] for item in target_findings}
    assert target_evidence[exact_target_copy]["classification"] == "confirmed_exact_copy"
    assert target_evidence[encoded_feature]["classification"] == "confirmed_reversible_encoding"
    assert record_token not in target_evidence

    assert "temporal_leakage" in {
        item["finding_type"] for item in result["findings"]
    }
    temporal_status = result["detector_applicability"]["temporal_leakage"]
    assert temporal_status["timestamp_timezone_normalization"] == "UTC"
    assert temporal_status["invalid_or_missing_timestamp_rows"] == 1
    assert temporal_status["status"] == "review_required"

    contamination = [
        item for item in result["findings"]
        if item["finding_type"] == "train_test_contamination"
    ]
    assert contamination
    contamination_evidence = contamination[0]["evidence"]
    assert contamination_evidence["classification"] == "exact_cross_partition_content_match"
    assert contamination_evidence["evidence_strength"] == "confirmed_exact"
    assert contamination_evidence["matching_fields"]
    assert contamination_evidence["record_references"]

    db = app.db.session.TestingSessionLocal()
    try:
        persisted = db.query(models.Dataset).filter(models.Dataset.id == dataset["id"]).first()
        assert persisted is not None
        assert persisted.profile["analysis_columns"]["entity_columns"] == [entity_a, entity_b]
        assert persisted.profile["analysis_columns"]["target_column"] == target
    finally:
        db.close()


def test_large_arbitrary_schema_uses_user_confirmed_composite_group_key(client):
    row_count = 6224
    frame = pd.DataFrame(
        {
            "study cohort": [
                "cohort-shared" if position < 2 else f"cohort-{position // 2}"
                for position in range(row_count)
            ],
            "site reference": [
                "site-shared" if position < 2 else f"site-{position // 4}"
                for position in range(row_count)
            ],
            "holdout marker": [
                (
                    "train"
                    if position == 0 or (position >= 2 and (position // 2) % 2 == 0)
                    else "test"
                )
                for position in range(row_count)
            ],
            "completion outcome": [position % 2 for position in range(row_count)],
            "captured at": [
                f"2025-01-{(position % 28) + 1:02d}T12:00:00Z"
                for position in range(row_count)
            ],
            "record reference": [f"record-{position}" for position in range(row_count)],
            "measurement value": [float(position % 97) for position in range(row_count)],
        }
    )
    dataset = _upload(client, "large arbitrary schema", frame)
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params=[
            ("split_strategy", "existing"),
            ("split_column", "holdout marker"),
            ("entity_columns", "study cohort"),
            ("entity_columns", "site reference"),
            ("target_column", "completion outcome"),
            ("time_column", "captured at"),
        ],
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["rows_examined"] == row_count
    assert result["analysis_configuration"]["entity_columns"] == [
        "study cohort",
        "site reference",
    ]
    overlaps = [
        finding
        for finding in result["findings"]
        if finding["finding_type"] == "entity_overlap"
    ]
    assert len(overlaps) == 1
    assert overlaps[0]["evidence"]["row_indices"] == {
        "test": [1],
        "train": [0],
    }


def test_missing_target_does_not_abort_analysis_and_is_not_reported_as_passed(client):
    frame = pd.DataFrame(
        {
            "partition label": ["train", "test"],
            "outcome value": ["", None],
            "measure value": [1, 2],
        }
    )
    dataset = _upload(client, "empty-target", frame)
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params=[
            ("split_strategy", "none"),
            ("target_column", "outcome value"),
        ],
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert not any(
        item["finding_type"] == "target_leakage" for item in result["findings"]
    )
    assert result["detector_applicability"]["target_leakage"]["status"] == "review_required"
    assert result["detector_applicability"]["target_leakage"]["missing_target_rows"] == 2
    for detector in ("entity_overlap", "temporal_leakage", "train_test_contamination"):
        assert result["detector_applicability"][detector]["status"] == "skipped"


def test_no_split_persists_configured_roles_while_marking_split_checks_skipped(client):
    dataset = _upload(
        client,
        "explicit-no-split-configuration",
        pd.DataFrame(
            {
                "group reference": ["a", "b"],
                "observed timestamp": ["2025-01-01", "2025-01-02"],
                "outcome value": [0, 1],
                "stable sample key": ["x", "y"],
                "measurement": [2.0, 3.0],
            }
        ),
    )
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params=[
            ("split_strategy", "none"),
            ("configuration_confirmed", "true"),
            ("target_column", "outcome value"),
            ("entity_column", "group reference"),
            ("time_column", "observed timestamp"),
            ("contamination_key_columns", "stable sample key"),
        ],
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["analysis_configuration"] == {
        "configuration_confirmed": True,
        "entity_column": "group reference",
        "entity_columns": ["group reference"],
        "contamination_key_columns": ["stable sample key"],
        "split_column": None,
        "target_column": "outcome value",
        "time_column": "observed timestamp",
        "temporal_objective": "future_prediction",
    }
    assert result["skipped_detectors"] == [
        "entity_overlap",
        "temporal_leakage",
        "train_test_contamination",
    ]
    assert all(
        result["detector_applicability"][name]["status"] == "skipped"
        for name in ("entity_overlap", "temporal_leakage", "train_test_contamination")
    )


def test_configured_entity_columns_must_exist_and_cannot_be_silently_ignored(client):
    dataset = _upload(
        client,
        "missing-entity-column",
        pd.DataFrame({"partition": ["train", "test"], "value": [1, 2]}),
    )
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params=[
            ("split_strategy", "existing"),
            ("split_column", "partition"),
            ("entity_columns", "unknown grouping field"),
        ],
    )
    assert response.status_code == 400
    assert "not found" in response.json()["detail"]


def test_randomized_holdout_temporal_overlap_is_explicitly_skipped(client):
    dataset = _upload(
        client,
        "randomized-holdout",
        pd.DataFrame(
            {
                "partition": ["train", "train", "test", "test"],
                "observed_at": [
                    "2025-02-01T00:00:00Z",
                    "2025-02-04T00:00:00Z",
                    "2025-02-02T00:00:00Z",
                    "2025-02-05T00:00:00Z",
                ],
                "measure": [1, 2, 3, 4],
            }
        ),
    )
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params=[
            ("split_strategy", "existing"),
            ("split_column", "partition"),
            ("time_column", "observed_at"),
            ("temporal_objective", "randomized_holdout"),
        ],
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert "temporal_leakage" in result["skipped_detectors"]
    assert not any(
        finding["finding_type"] == "temporal_leakage"
        for finding in result["findings"]
    )
    temporal = result["detector_applicability"]["temporal_leakage"]
    assert temporal["status"] == "skipped"
    assert "not interpreted as leakage" in temporal["reason"]


def test_user_configured_contamination_key_propagates_through_analysis_and_manifest(client):
    frame = pd.DataFrame(
        {
            "partition name": ["fit", "holdout", "fit"],
            "sample key": ["same-observation", "same-observation", "other-observation"],
            "changed measurement": [10.0, 999.0, 12.0],
            "record label": ["first copy", "changed copy", "independent"],
        }
    )
    dataset = _upload(client, "configured-contamination-key", frame)
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params=[
            ("split_strategy", "existing"),
            ("split_column", "partition name"),
            ("contamination_key_columns", "sample key"),
            ("configuration_confirmed", "true"),
        ],
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["analysis_configuration"]["configuration_confirmed"] is True
    assert result["analysis_configuration"]["contamination_key_columns"] == ["sample key"]
    finding = next(
        item for item in result["findings"]
        if item["finding_type"] == "train_test_contamination"
    )
    evidence = finding["evidence"]
    assert evidence["detection"] == "configured_key_hash_overlap"
    assert evidence["matching_fields"] == ["sample key"]
    assert evidence["classification"] == "configured_key_cross_partition_match"
    assert evidence["record_references"] == [
        {"source_row_position": 0, "partition": "fit"},
        {"source_row_position": 1, "partition": "holdout"},
    ]

    preview_response = client.post(
        f"/api/v1/datasets/{dataset['id']}/remediation-plans/preview",
        json={
            "actions": [
                {
                    "action": "exclude_contaminated_copies",
                    "finding_ids": [finding["id"]],
                    "split_column": "partition name",
                    "retained_partition": "fit",
                }
            ]
        },
    )
    assert preview_response.status_code == 201, preview_response.text
    preview = preview_response.json()
    assert preview["plan"]["analysis_configuration"]["contamination_key_columns"] == [
        "sample key"
    ]
    assert preview["plan"]["remediation_configuration"]["contamination_key_columns"] == [
        "sample key"
    ]
    assert preview["plan"]["detector_results_before"]["train_test_contamination"] == {
        "status": "review_required",
        "remaining_condition_count": 1,
        "reason": "1 cross-partition matching group(s) remain; 0 rows lack split membership and 0 rows lack configured comparison keys.",
    }

    execute_response = client.post(
        f"/api/v1/datasets/{dataset['id']}/remediation-plans/{preview['id']}/execute",
        json={
            "preview_token": preview["plan"]["preview_token"],
            "confirmed": True,
        },
    )
    assert execute_response.status_code == 201, execute_response.text
    operation = execute_response.json()
    assert operation["plan"]["verification"]["status"] == "verified"
    assert operation["plan"]["verification"]["detector_results_after"][
        "train_test_contamination"
    ]["status"] == "passed"
    assert operation["plan"]["verification"]["detector_check_counts"]["passed"] >= 1
    assert operation["plan"]["verification"]["detector_check_counts"]["skipped"] >= 1
    manifest_response = client.get(
        f"/api/v1/operations/{preview['id']}/remediation-artifacts/manifest"
    )
    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    assert manifest["configuration_snapshot"]["contamination_key_columns"] == [
        "sample key"
    ]
    assert manifest["remediation_configuration"]["contamination_key_columns"] == [
        "sample key"
    ]
    assert manifest["detector_results_after"]["train_test_contamination"]["status"] == "passed"
    assert manifest["verified_finding_ids"] == [finding["id"]]


@pytest.mark.parametrize(
    "keys",
    [
        [("contamination_key_columns", "missing field")],
        [
            ("contamination_key_columns", "sample key"),
            ("contamination_key_columns", "sample key"),
        ],
        [("contamination_key_columns", "")],
    ],
)
def test_invalid_or_duplicate_contamination_keys_are_rejected_not_ignored(client, keys):
    dataset = _upload(
        client,
        "invalid-contamination-key",
        pd.DataFrame(
            {
                "partition": ["train", "test"],
                "sample key": ["a", "a"],
                "value": [1, 2],
            }
        ),
    )
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params=[
            ("split_strategy", "existing"),
            ("split_column", "partition"),
            *keys,
        ],
    )
    assert response.status_code == 422
    assert "contamination" in response.json()["detail"].lower()


def test_missing_configured_contamination_keys_are_reviewed_not_matched_as_null_copies(client):
    dataset = _upload(
        client,
        "missing-contamination-key-values",
        pd.DataFrame(
            {
                "partition": ["train", "test"],
                "sample reference": ["", None],
                "measurement": [10, 99],
            }
        ),
    )
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params=[
            ("split_strategy", "existing"),
            ("split_column", "partition"),
            ("contamination_key_columns", "sample reference"),
        ],
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert not any(
        item["finding_type"] == "train_test_contamination"
        for item in result["findings"]
    )
    applicability = result["detector_applicability"]["train_test_contamination"]
    assert applicability["status"] == "review_required"
    assert applicability["missing_comparison_key_rows"] == 2
    assert "excluded" in applicability["reason"]


def test_temporal_objective_requires_a_confirmed_timestamp_column(client):
    dataset = _upload(
        client,
        "missing-temporal-column",
        pd.DataFrame({"partition": ["train", "test"], "measure": [1, 2]}),
    )
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/analyze/leakage",
        params=[
            ("split_strategy", "existing"),
            ("split_column", "partition"),
            ("temporal_objective", "future_prediction"),
        ],
    )
    assert response.status_code == 422
    assert "requires time_column" in response.json()["detail"]
