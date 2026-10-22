import pytest
from fastapi import status
from app.db import leakage_models


def test_entity_overlap_detected(client, test_db):
    # Dataset with entity overlap
    # patient_id,split,value
    # P001,train,10
    # P002,train,20
    # P001,test,30
    # P003,test,40
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
            "name": "test entity overlap",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis with entity_column and split_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?entity_column=patient_id&split_column=split"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert result["dataset_id"] == dataset_id
    # We don't assert rows_examined etc. because they are from exact duplicates (none)
    # But we can assert that duplicate_group_count and duplicated_row_count are 0? Not necessarily, because there are no exact duplicates.
    # However, we can leave it.
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["finding_type"] == "entity_overlap"
    assert finding["severity"] == "high"
    assert finding["status"] == "open"
    assert "Entity 'P001' appears in multiple splits: test, train." in finding["description"]
    assert finding["evidence"]["entity_column"] == "patient_id"
    assert finding["evidence"]["split_column"] == "split"
    assert finding["evidence"]["entity_value"] == "P001"
    assert set(finding["evidence"]["splits"]) == {"train", "test"}
    # Check row_indices: for train, row indices [0,1]? Wait, the entity P001 appears at row 0 and row 2.
    # For split train, the rows with patient_id=P001 are row 0.
    # For split test, the rows with patient_id=P001 are row 2.
    assert finding["evidence"]["row_indices"]["train"] == [0]
    assert finding["evidence"]["row_indices"]["test"] == [2]

    # Verify that a LeakageFinding record was created in the database
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "entity_overlap"
        ).all()
        assert len(findings) == 1
        db_finding = findings[0]
        assert db_finding.id == finding["id"]
        assert db_finding.finding_type == "entity_overlap"
        assert db_finding.severity == "high"
        assert db_finding.status == "open"
        assert db_finding.description == finding["description"]
        assert db_finding.evidence == finding["evidence"]
    finally:
        db.close()


def test_no_entity_overlap(client, test_db):
    # Dataset where every entity occurs in exactly one split.
    # patient_id,split,value
    # P001,train,10
    # P002,train,20
    # P003,test,30
    # P004,test,40
    import pandas as pd
    df = pd.DataFrame({
        'patient_id': ['P001', 'P002', 'P003', 'P004'],
        'split': ['train', 'train', 'test', 'test'],
        'value': [10, 20, 30, 40]
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test no overlap",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?entity_column=patient_id&split_column=split"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert len(result["findings"]) == 0

    # Verify no entity_overlap findings in DB
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "entity_overlap"
        ).all()
        assert len(findings) == 0
    finally:
        db.close()


def test_multiple_overlapping_entities(client, test_db):
    # Dataset:
    # P001 -> train + test
    # P002 -> train + validation
    import pandas as pd
    df = pd.DataFrame({
        'patient_id': ['P001', 'P002', 'P001', 'P002'],
        'split': ['train', 'train', 'test', 'validation'],
        'value': [10, 20, 30, 40]
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test multiple overlap",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?entity_column=patient_id&split_column=split"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert len(result["findings"]) == 2
    # Check that we have two findings for P001 and P002
    entity_values = {f["evidence"]["entity_value"] for f in result["findings"]}
    assert entity_values == {"P001", "P002"}
    for f in result["findings"]:
        assert f["finding_type"] == "entity_overlap"
        assert f["severity"] == "high"
        assert f["status"] == "open"
        assert f["evidence"]["entity_column"] == "patient_id"
        assert f["evidence"]["split_column"] == "split"
        assert set(f["evidence"]["splits"]) == {"train", "test"} or set(f["evidence"]["splits"]) == {"train", "validation"}


def test_missing_entity_column(client, test_db):
    # Upload a dataset
    import pandas as pd
    df = pd.DataFrame({
        'patient_id': ['P001', 'P002'],
        'split': ['train', 'test'],
        'value': [10, 20]
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test missing entity",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Call with only split_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?split_column=split"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Both entity_column and split_column must be provided" in response.json()["detail"]

    # Call with only entity_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?entity_column=patient_id"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Both entity_column and split_column must be provided" in response.json()["detail"]


def test_only_one_parameter_supplied(client, test_db):
    # This is covered in the previous test, but we can keep it as a separate test for clarity.
    pass


def test_repeated_analysis_idempotent(client, test_db):
    # Upload a dataset with an overlap
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
            "name": "test repeated",
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
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?entity_column=patient_id&split_column=split"
    )
    assert response1.status_code == status.HTTP_200_OK
    result1 = response1.json()

    # Second analysis
    response2 = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?entity_column=patient_id&split_column=split"
    )
    assert response2.status_code == status.HTTP_200_OK
    result2 = response2.json()

    # Verify that the findings are the same (same ID)
    assert len(result1["findings"]) == len(result2["findings"]) == 1
    assert result1["findings"][0]["id"] == result2["findings"][0]["id"]

    # Verify that only one LeakageFinding record exists in the database
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "entity_overlap"
        ).all()
        assert len(findings) == 1
    finally:
        db.close()


def test_existing_step31_behavior(client, test_db):
    # Call without entity_column/split_column should still run exact duplicate detection
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

    # Run analysis without entity_column/split_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    # Should have an exact duplicate finding for patient_id? Wait, the exact duplicate detection works on row hashes, not on patient_id.
    # The dataset has duplicate rows? The rows are:
    # P001,train,10
    # P002,train,20
    # P001,test,30
    # P003,test,40
    # There are no duplicate rows (all rows are unique). So we expect no exact duplicate findings.
    # But we can just assert that the analysis succeeds.
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


def test_findings_api_returns_entity_overlap(client, test_db):
    # Upload a dataset with an overlap
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
            "name": "test findings api",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis to create an entity overlap finding
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?entity_column=patient_id&split_column=split"
    )
    assert response.status_code == status.HTTP_200_OK

    # Get findings for the dataset
    response = client.get(f"/api/v1/datasets/{dataset_id}/findings")
    assert response.status_code == status.HTTP_200_OK
    findings = response.json()
    assert len(findings) == 1
    finding = findings[0]
    assert finding["finding_type"] == "entity_overlap"
    assert finding["evidence"]["entity_value"] == "P001"


def test_individual_finding_api_returns_entity_overlap(client, test_db):
    # Upload a dataset with an overlap
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
            "name": "test individual finding",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis to create an entity overlap finding
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?entity_column=patient_id&split_column=split"
    )
    assert response.status_code == status.HTTP_200_OK
    analysis_result = response.json()
    finding_id = analysis_result["findings"][0]["id"]

    # Get the individual finding
    response = client.get(f"/api/v1/findings/{finding_id}")
    assert response.status_code == status.HTTP_200_OK
    finding = response.json()
    assert finding["finding_type"] == "entity_overlap"
    assert finding["evidence"]["entity_value"] == "P001"