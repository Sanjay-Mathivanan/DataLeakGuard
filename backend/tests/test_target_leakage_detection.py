import pytest
from fastapi import status
from app.db import leakage_models


def test_exact_target_duplicate_detected(client, test_db):
    # Dataset with exact target duplication
    # target,leaked_feature
    # 1,1
    # 0,0
    import pandas as pd
    df = pd.DataFrame({
        'target': [1, 0],
        'leaked_feature': [1, 0]  # Exactly duplicates target
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test exact target duplicate",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis with target_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?target_column=target"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert result["dataset_id"] == dataset_id

    # There are no duplicate rows, only the target-column duplicate finding.
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["finding_type"] == "target_leakage"
    assert finding["severity"] == "high"
    assert finding["status"] == "open"
    assert "Feature column 'leaked_feature' exactly duplicates the target column 'target'." in finding["description"]
    assert finding["evidence"]["target_column"] == "target"
    assert finding["evidence"]["feature_column"] == "leaked_feature"
    assert finding["evidence"]["detection"] == "exact_target_duplicate"
    assert finding["evidence"]["matching_rows"] == 2
    assert finding["evidence"]["total_valid_rows"] == 2

    # Verify that a LeakageFinding record was created in the database
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "target_leakage"
        ).all()
        assert len(findings) == 1
        db_finding = findings[0]
        assert db_finding.id == finding["id"]
        assert db_finding.finding_type == "target_leakage"
        assert db_finding.severity == "high"
        assert db_finding.status == "open"
        assert db_finding.description == finding["description"]
        assert db_finding.evidence == finding["evidence"]
    finally:
        db.close()


def test_deterministic_feature_target_mapping(client, test_db):
    # Dataset with deterministic feature -> target mapping
    # feature,target
    # A,0
    # A,0
    # B,1
    # B,1
    import pandas as pd
    df = pd.DataFrame({
        'feature': ['A', 'A', 'B', 'B'],
        'target': [0, 0, 1, 1],
        # This auxiliary feature intentionally maps to both target groups.
        'other_feature': [10, 20, 10, 20]
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test deterministic mapping",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis with target_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?target_column=target"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert result["dataset_id"] == dataset_id

    # Should have target leakage finding for feature column
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["finding_type"] == "target_leakage"
    assert finding["severity"] == "high"
    assert finding["status"] == "open"
    assert finding["description"] == (
        "Feature column 'feature' is a reversible encoding of target 'target'."
    )
    assert finding["evidence"]["classification"] == "confirmed_reversible_encoding"
    assert finding["evidence"]["target_column"] == "target"
    assert finding["evidence"]["feature_column"] == "feature"
    assert finding["evidence"]["detection"] == "deterministic_feature_target_mapping"
    assert finding["evidence"]["unique_feature_values"] == 2
    assert finding["evidence"]["unique_target_values"] == 2
    assert finding["evidence"]["mapping"] == {"A": "0", "B": "1"}

    # Verify that a LeakageFinding record was created in the database
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "target_leakage"
        ).all()
        assert len(findings) == 1
        db_finding = findings[0]
        assert db_finding.id == finding["id"]
        assert db_finding.finding_type == "target_leakage"
        assert db_finding.severity == "high"
        assert db_finding.status == "open"
        assert db_finding.description == finding["description"]
        assert db_finding.evidence == finding["evidence"]
    finally:
        db.close()


    # Reanalysis must return the persisted deterministic-mapping finding.
    repeated_response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?target_column=target"
    )
    assert repeated_response.status_code == status.HTTP_200_OK
    repeated_findings = [
        f for f in repeated_response.json()["findings"]
        if f["finding_type"] == "target_leakage"
    ]
    assert len(repeated_findings) == 1
    assert repeated_findings[0]["id"] == finding["id"]
    assert repeated_findings[0]["evidence"] == finding["evidence"]


def test_no_target_leakage(client, test_db):
    # Dataset where feature values map to multiple target values (no leakage)
    # feature,target
    # A,0
    # A,1  # Same feature value maps to different target values
    # B,0
    # B,1
    import pandas as pd
    df = pd.DataFrame({
        'feature': ['A', 'A', 'B', 'B'],
        'target': [0, 1, 0, 1]
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test no target leakage",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis with target_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?target_column=target"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert result["dataset_id"] == dataset_id

    # Should have no target leakage findings (though might have exact duplicates if any)
    # In this dataset, there are no exact duplicate rows
    target_leakage_findings = [
        f for f in result["findings"]
        if f["finding_type"] == "target_leakage"
    ]
    assert len(target_leakage_findings) == 0

    # Verify no target_leakage findings in DB
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "target_leakage"
        ).all()
        assert len(findings) == 0
    finally:
        db.close()


def test_target_column_not_flagged(client, test_db):
    # Ensure the target column itself is never reported as leakage
    # feature,target
    # A,0
    # A,0
    # B,1
    # B,1
    import pandas as pd
    df = pd.DataFrame({
        'feature': ['A', 'A', 'B', 'B'],
        'target': [0, 0, 1, 1]
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test target column not flagged",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis with target_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?target_column=target"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert result["dataset_id"] == dataset_id

    # Should have no findings where the feature_column equals target_column
    target_leakage_findings = [
        f for f in result["findings"]
        if f["finding_type"] == "target_leakage"
        and f["evidence"]["feature_column"] == f["evidence"]["target_column"]
    ]
    assert len(target_leakage_findings) == 0

    # Verify no such findings in DB
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "target_leakage"
        ).all()
        for finding in findings:
            assert finding.evidence["feature_column"] != finding.evidence["target_column"]
    finally:
        db.close()


def test_single_value_feature_not_flagged(client, test_db):
    # A feature with only one unique value must not be flagged
    # feature,target
    # A,0
    # A,0
    # A,1
    # A,1
    import pandas as pd
    df = pd.DataFrame({
        'feature': ['A', 'A', 'A', 'A'],  # Only one unique value
        'target': [0, 0, 1, 1]
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test single value feature",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis with target_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?target_column=target"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert result["dataset_id"] == dataset_id

    # Should have no target leakage findings for single-value feature
    target_leakage_findings = [
        f for f in result["findings"]
        if f["finding_type"] == "target_leakage"
        and f["evidence"]["feature_column"] == "feature"
    ]
    assert len(target_leakage_findings) == 0

    # Verify no such findings in DB
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "target_leakage"
        ).all()
        for finding in findings:
            assert finding.evidence["feature_column"] != "feature"
    finally:
        db.close()


def test_missing_target_column(client, test_db):
    # Upload a dataset
    import pandas as pd
    df = pd.DataFrame({
        'feature': ['A', 'B'],
        'target': [0, 1]
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test missing target",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Call with target_column that doesn't exist
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?target_column=nonexistent"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Target column 'nonexistent' not found in dataset columns" in response.json()["detail"]


def test_repeated_analysis_idempotent(client, test_db):
    # Upload a dataset with an exact target duplicate
    import pandas as pd
    df = pd.DataFrame({
        'target': [1, 0],
        'leaked_feature': [1, 0]  # Exactly duplicates target
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test repeated target leakage",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # First analysis
    response1 = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?target_column=target"
    )
    assert response1.status_code == status.HTTP_200_OK
    result1 = response1.json()

    # Second analysis
    response2 = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?target_column=target"
    )
    assert response2.status_code == status.HTTP_200_OK
    result2 = response2.json()

    # Verify that the findings are the same (same ID)
    target_leakage_findings1 = [
        f for f in result1["findings"]
        if f["finding_type"] == "target_leakage"
    ]
    target_leakage_findings2 = [
        f for f in result2["findings"]
        if f["finding_type"] == "target_leakage"
    ]
    assert len(target_leakage_findings1) == len(target_leakage_findings2) == 1
    assert target_leakage_findings1[0]["id"] == target_leakage_findings2[0]["id"]

    # Verify that only one LeakageFinding record exists in the database
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "target_leakage"
        ).all()
        assert len(findings) == 1
    finally:
        db.close()


def test_existing_step31_behavior(client, test_db):
    # Call without target_column should still run exact duplicate detection
    import pandas as pd
    df = pd.DataFrame({
        'patient_id': ['P001', 'P002', 'P001', 'P003'],
        'split': ['train', 'train', 'test', 'test'],
        'value': [10, 20, 30, 40]
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test step31",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run analysis without target_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    # Should have no exact duplicate findings (all rows unique)
    assert len(result["findings"]) == 0  # since no exact duplicates

    # Now test with a dataset that has exact duplicates
    df_dup = pd.DataFrame({
        'patient_id': ['P001', 'P002', 'P001', 'P002'],
        'split': ['train', 'train', 'train', 'train'],
        'value': [10, 20, 10, 20]
    })
    csv_content_dup = df_dup.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test step31 dup",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test2.csv", csv_content_dup, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id_dup = data["id"]

    response = client.post(
        f"/api/v1/datasets/{dataset_id_dup}/analyze/leakage"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    # Expect two findings: one for each duplicate group
    assert len(result["findings"]) == 2
    # Both findings should be exact duplicates
    for f in result["findings"]:
        assert f["finding_type"] == "exact_duplicate"
        assert f["severity"] == "medium"
        assert f["status"] == "open"
        # Each finding should have duplicate_count of 2
        assert f["evidence"]["duplicate_count"] == 2


def test_findings_api_returns_target_leakage(client, test_db):
    # Upload a dataset with an exact target duplicate
    import pandas as pd
    df = pd.DataFrame({
        'target': [1, 0],
        'leaked_feature': [1, 0]  # Exactly duplicates target
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test findings api target leakage",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis to create a target leakage finding
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?target_column=target"
    )
    assert response.status_code == status.HTTP_200_OK

    # Get findings for the dataset
    response = client.get(f"/api/v1/datasets/{dataset_id}/findings")
    assert response.status_code == status.HTTP_200_OK
    findings = response.json()
    assert len(findings) == 1
    finding = findings[0]
    assert finding["finding_type"] == "target_leakage"
    assert finding["evidence"]["feature_column"] == "leaked_feature"
    assert finding["evidence"]["target_column"] == "target"


def test_individual_finding_api_returns_target_leakage(client, test_db):
    # Upload a dataset with an exact target duplicate
    import pandas as pd
    df = pd.DataFrame({
        'target': [1, 0],
        'leaked_feature': [1, 0]  # Exactly duplicates target
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test individual finding target leakage",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis to create a target leakage finding
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?target_column=target"
    )
    assert response.status_code == status.HTTP_200_OK
    analysis_result = response.json()
    finding_id = analysis_result["findings"][0]["id"]

    # Get the individual finding
    response = client.get(f"/api/v1/findings/{finding_id}")
    assert response.status_code == status.HTTP_200_OK
    finding = response.json()
    assert finding["finding_type"] == "target_leakage"
    assert finding["evidence"]["feature_column"] == "leaked_feature"
    assert finding["evidence"]["target_column"] == "target"


def _run_target_mapping_analysis(client, dataframe, name):
    csv_content = dataframe.to_csv(index=False).encode()
    upload_response = client.post(
        "/api/v1/datasets",
        data={
            "name": name,
            "type": "tabular",
            "format": "CSV",
            "description": "target mapping regression test",
        },
        files={"file": ("target_mapping.csv", csv_content, "text/csv")},
    )
    assert upload_response.status_code == status.HTTP_201_CREATED
    dataset_id = upload_response.json()["id"]

    analysis_response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?target_column=target"
    )
    assert analysis_response.status_code == status.HTTP_200_OK
    return [
        finding
        for finding in analysis_response.json()["findings"]
        if finding["finding_type"] == "target_leakage"
    ]


@pytest.mark.parametrize(
    ("feature_values", "target_values", "expected_mapping"),
    [
        pytest.param(
            ["A", "B"],
            ["0", "1"],
            {"A": "0", "B": "1"},
            id="one-to-one",
        ),
        pytest.param(
            ["A", "B", "C"],
            ["0", "0", "1"],
            {"A": "0", "B": "0", "C": "1"},
            id="many-to-one",
        ),
    ],
)
def test_deterministic_mapping_supports_one_to_one_and_many_to_one(
    client, test_db, feature_values, target_values, expected_mapping
):
    import pandas as pd

    findings = _run_target_mapping_analysis(
        client,
        pd.DataFrame({"feature": feature_values, "target": target_values}),
        "deterministic mapping cardinality",
    )

    assert len(findings) == 1
    evidence = findings[0]["evidence"]
    assert evidence["detection"] == "deterministic_feature_target_mapping"
    assert evidence["mapping"] == expected_mapping
    assert evidence["unique_feature_values"] == len(expected_mapping)
    assert evidence["unique_target_values"] == len(set(target_values))


def test_deterministic_mapping_ignores_missing_and_blank_pairs(client, test_db):
    import pandas as pd

    dataframe = pd.DataFrame(
        {
            "feature": ["A", "A", "B", "B", None, "C", "D", " "],
            "target": ["0", "0", "1", "1", "1", None, " ", "0"],
        }
    )

    findings = _run_target_mapping_analysis(
        client, dataframe, "deterministic mapping missing values"
    )

    assert len(findings) == 1
    evidence = findings[0]["evidence"]
    assert evidence["mapping"] == {"A": "0", "B": "1"}
    assert evidence["unique_feature_values"] == 2
    assert evidence["unique_target_values"] == 2
