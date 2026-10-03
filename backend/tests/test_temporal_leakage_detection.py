import pytest
from fastapi import status
from app.db import leakage_models


def test_temporal_overlap_detected(client, test_db):
    # Dataset with temporal overlap
    # event_date,split
    # 2025-01-01,train
    # 2025-01-10,train
    # 2025-01-20,train
    # 2025-01-15,test
    # 2025-01-30,test
    import pandas as pd
    df = pd.DataFrame({
        'event_date': ['2025-01-01', '2025-01-10', '2025-01-20', '2025-01-15', '2025-01-30'],
        'split': ['train', 'train', 'train', 'test', 'test']
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test temporal overlap",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis with time_column and split_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?time_column=event_date&split_column=split"
    )
    print(f"Response status: {response.status_code}")
    if response.status_code != status.HTTP_200_OK:
        print(f"Response body: {response.json()}")
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert result["dataset_id"] == dataset_id

    # Should have temporal leakage finding
    temporal_leakage_findings = [
        f for f in result["findings"]
        if f["finding_type"] == "temporal_leakage"
    ]
    assert len(temporal_leakage_findings) == 1
    finding = temporal_leakage_findings[0]
    assert finding["severity"] == "high"
    assert finding["status"] == "open"
    assert "Temporal overlap detected" in finding["description"]
    assert finding["evidence"]["time_column"] == "event_date"
    assert finding["evidence"]["split_column"] == "split"
    assert finding["evidence"]["detection"] == "temporal_overlap"
    assert "train" in finding["evidence"]["splits"]
    assert "test" in finding["evidence"]["splits"]
    assert finding["evidence"]["splits"]["train"]["min_time"] == "2025-01-01T00:00:00"
    assert finding["evidence"]["splits"]["train"]["max_time"] == "2025-01-20T00:00:00"
    assert finding["evidence"]["splits"]["test"]["min_time"] == "2025-01-15T00:00:00"
    assert finding["evidence"]["splits"]["test"]["max_time"] == "2025-01-30T00:00:00"
    assert finding["evidence"]["splits"]["train"]["valid_rows"] == 3
    assert finding["evidence"]["splits"]["test"]["valid_rows"] == 2
    assert finding["evidence"]["invalid_timestamp_rows"] == 0

    # Verify that a LeakageFinding record was created in the database
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "temporal_leakage"
        ).all()
        assert len(findings) == 1
        db_finding = findings[0]
        assert db_finding.id == finding["id"]
        assert db_finding.finding_type == "temporal_leakage"
        assert db_finding.severity == "high"
        assert db_finding.status == "open"
        assert db_finding.description == finding["description"]
        assert db_finding.evidence == finding["evidence"]
    finally:
        db.close()


def test_no_temporal_overlap(client, test_db):
    # Dataset without temporal overlap
    # event_date,split
    # 2025-01-01,train
    # 2025-01-10,train
    # 2025-01-20,train
    # 2025-02-01,test
    # 2025-02-10,test
    import pandas as pd
    df = pd.DataFrame({
        'event_date': ['2025-01-01', '2025-01-10', '2025-01-20', '2025-02-01', '2025-02-10'],
        'split': ['train', 'train', 'train', 'test', 'test']
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test no temporal overlap",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis with time_column and split_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?time_column=event_date&split_column=split"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert result["dataset_id"] == dataset_id

    # Should have no temporal leakage findings
    temporal_leakage_findings = [
        f for f in result["findings"]
        if f["finding_type"] == "temporal_leakage"
    ]
    assert len(temporal_leakage_findings) == 0

    # Verify no temporal_leakage findings in DB
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "temporal_leakage"
        ).all()
        assert len(findings) == 0
    finally:
        db.close()


def test_boundary_overlap_detected(client, test_db):
    # Dataset with boundary overlap (test_min == train_max)
    # event_date,split
    # 2025-01-01,train
    # 2025-01-10,train
    # 2025-01-10,test
    # 2025-01-20,test
    import pandas as pd
    df = pd.DataFrame({
        'event_date': ['2025-01-01', '2025-01-10', '2025-01-10', '2025-01-20'],
        'split': ['train', 'train', 'test', 'test']
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test boundary overlap",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis with time_column and split_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?time_column=event_date&split_column=split"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert result["dataset_id"] == dataset_id

    # Should have temporal leakage finding with boundary_overlap = true
    temporal_leakage_findings = [
        f for f in result["findings"]
        if f["finding_type"] == "temporal_leakage"
    ]
    assert len(temporal_leakage_findings) == 1
    finding = temporal_leakage_findings[0]
    assert finding["severity"] == "high"
    assert finding["status"] == "open"
    assert "Temporal boundary overlap detected" in finding["description"]
    assert finding["evidence"]["time_column"] == "event_date"
    assert finding["evidence"]["split_column"] == "split"
    assert finding["evidence"]["detection"] == "temporal_overlap"
    assert finding["evidence"]["boundary_overlap"] == True
    assert "train" in finding["evidence"]["splits"]
    assert "test" in finding["evidence"]["splits"]
    assert finding["evidence"]["splits"]["train"]["min_time"] == "2025-01-01T00:00:00"
    assert finding["evidence"]["splits"]["train"]["max_time"] == "2025-01-10T00:00:00"
    assert finding["evidence"]["splits"]["test"]["min_time"] == "2025-01-10T00:00:00"
    assert finding["evidence"]["splits"]["test"]["max_time"] == "2025-01-20T00:00:00"
    assert finding["evidence"]["splits"]["train"]["valid_rows"] == 2
    assert finding["evidence"]["splits"]["test"]["valid_rows"] == 2
    assert finding["evidence"]["invalid_timestamp_rows"] == 0

    # Verify that a LeakageFinding record was created in the database
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "temporal_leakage"
        ).all()
        assert len(findings) == 1
        db_finding = findings[0]
        assert db_finding.id == finding["id"]
        assert db_finding.finding_type == "temporal_leakage"
        assert db_finding.severity == "high"
        assert db_finding.status == "open"
        assert db_finding.description == finding["description"]
        assert db_finding.evidence == finding["evidence"]
    finally:
        db.close()


def test_invalid_timestamps_are_reported(client, test_db):
    # Dataset with invalid timestamps
    # event_date,split
    # 2025-01-01,train
    # invalid,train
    # 2025-01-20,train
    # 2025-01-15,test
    # 2025-01-30,test
    import pandas as pd
    df = pd.DataFrame({
        'event_date': ['2025-01-01', 'invalid', '2025-01-20', '2025-01-15', '2025-01-30'],
        'split': ['train', 'train', 'train', 'test', 'test']
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test invalid timestamps",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis with time_column and split_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?time_column=event_date&split_column=split"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert result["dataset_id"] == dataset_id

    # Should have temporal leakage finding (using valid timestamps)
    temporal_leakage_findings = [
        f for f in result["findings"]
        if f["finding_type"] == "temporal_leakage"
    ]
    print(f"DEBUG: Found {len(temporal_leakage_findings)} temporal leakage findings")
    if temporal_leakage_findings:
        print(f"DEBUG: First temporal leakage finding: {temporal_leakage_findings[0]}")
    assert len(temporal_leakage_findings) == 1
    finding = temporal_leakage_findings[0]
    assert finding["severity"] == "high"
    assert finding["status"] == "open"
    assert "Temporal overlap detected" in finding["description"]
    assert finding["evidence"]["time_column"] == "event_date"
    assert finding["evidence"]["split_column"] == "split"
    assert finding["evidence"]["detection"] == "temporal_overlap"
    assert finding["evidence"]["invalid_timestamp_rows"] == 1
    assert finding["evidence"]["splits"]["train"]["valid_rows"] == 2  # Only 2 valid timestamps in train
    assert finding["evidence"]["splits"]["test"]["valid_rows"] == 2

    # Verify that a LeakageFinding record was created in the database
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "temporal_leakage"
        ).all()
        assert len(findings) == 1
        db_finding = findings[0]
        assert db_finding.id == finding["id"]
        assert db_finding.finding_type == "temporal_leakage"
        assert db_finding.severity == "high"
        assert db_finding.status == "open"
        assert db_finding.description == finding["description"]
        assert db_finding.evidence == finding["evidence"]
    finally:
        db.close()


def test_no_valid_timestamps(client, test_db):
    # Dataset with all invalid timestamps
    # event_date,split
    # invalid1,train
    # invalid2,train
    # invalid3,test
    # invalid4,test
    import pandas as pd
    df = pd.DataFrame({
        'event_date': ['invalid1', 'invalid2', 'invalid3', 'invalid4'],
        'split': ['train', 'train', 'test', 'test']
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test no valid timestamps",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis with time_column and split_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?time_column=event_date&split_column=split"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "No valid timestamps found in column 'event_date'" in response.json()["detail"]


def test_missing_time_column(client, test_db):
    # Upload a dataset
    import pandas as pd
    df = pd.DataFrame({
        'feature': ['A', 'B'],
        'split': ['train', 'test']
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test missing time",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Call with time_column that doesn't exist
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?time_column=nonexistent&split_column=split"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Time column 'nonexistent' not found in dataset columns" in response.json()["detail"]


def test_missing_split_column(client, test_db):
    # Upload a dataset
    import pandas as pd
    df = pd.DataFrame({
        'feature': ['A', 'B'],
        'event_date': ['2025-01-01', '2025-01-02']
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test missing split",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Call with split_column that doesn't exist
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?time_column=event_date&split_column=nonexistent"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Split column 'nonexistent' not found in dataset columns" in response.json()["detail"]


def test_only_time_column_supplied(client, test_db):
    # Upload a dataset
    import pandas as pd
    df = pd.DataFrame({
        'feature': ['A', 'B'],
        'event_date': ['2025-01-01', '2025-01-02']
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test only time column",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Call with only time_column
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?time_column=event_date"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Both time_column and split_column must be provided for temporal leakage detection" in response.json()["detail"]


def test_only_split_column_supplied(client, test_db):
    # Upload a dataset
    import pandas as pd
    df = pd.DataFrame({
        'feature': ['A', 'B'],
        'split': ['train', 'test']
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test only split column",
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
    assert "Both entity_column and split_column must be provided for entity overlap detection" in response.json()["detail"]


def test_repeated_analysis_idempotent(client, test_db):
    # Upload a dataset with temporal overlap
    import pandas as pd
    df = pd.DataFrame({
        'event_date': ['2025-01-01', '2025-01-10', '2025-01-20', '2025-01-15', '2025-01-30'],
        'split': ['train', 'train', 'train', 'test', 'test']
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test repeated temporal leakage",
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
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?time_column=event_date&split_column=split"
    )
    assert response1.status_code == status.HTTP_200_OK
    result1 = response1.json()

    # Second analysis
    response2 = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?time_column=event_date&split_column=split"
    )
    assert response2.status_code == status.HTTP_200_OK
    result2 = response2.json()

    # Verify that the findings are the same (same ID)
    temporal_leakage_findings1 = [
        f for f in result1["findings"]
        if f["finding_type"] == "temporal_leakage"
    ]
    temporal_leakage_findings2 = [
        f for f in result2["findings"]
        if f["finding_type"] == "temporal_leakage"
    ]
    assert len(temporal_leakage_findings1) == len(temporal_leakage_findings2) == 1
    assert temporal_leakage_findings1[0]["id"] == temporal_leakage_findings2[0]["id"]

    # Verify that only one LeakageFinding record exists in the database
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "temporal_leakage"
        ).all()
        assert len(findings) == 1
    finally:
        db.close()


def test_existing_step31_behavior(client, test_db):
    # Call without time_column/split_column should still run exact duplicate detection
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

    # Run analysis without time_column/split_column
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


def test_existing_step32_behavior(client, test_db):
    # Call with entity_column/split_column should still run entity overlap detection
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
            "name": "test step32",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run analysis with entity_column/split_column (no time_column)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?entity_column=patient_id&split_column=split"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
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

    # Now test with a dataset that has entity overlap
    df_overlap = pd.DataFrame({
        'patient_id': ['P001', 'P002', 'P001', 'P003'],
        'split': ['train', 'train', 'test', 'test'],
        'value': [10, 20, 30, 40]
    })
    csv_content_overlap = df_overlap.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test step32 overlap",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test2.csv", csv_content_overlap, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id_overlap = data["id"]

    response = client.post(
        f"/api/v1/datasets/{dataset_id_overlap}/analyze/leakage?entity_column=patient_id&split_column=split"
    )
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
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


def test_findings_api_returns_temporal_leakage(client, test_db):
    # Upload a dataset with temporal overlap
    import pandas as pd
    df = pd.DataFrame({
        'event_date': ['2025-01-01', '2025-01-10', '2025-01-20', '2025-01-15', '2025-01-30'],
        'split': ['train', 'train', 'train', 'test', 'test']
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test findings api temporal leakage",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis to create a temporal leakage finding
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?time_column=event_date&split_column=split"
    )
    assert response.status_code == status.HTTP_200_OK

    # Get findings for the dataset
    response = client.get(f"/api/v1/datasets/{dataset_id}/findings")
    assert response.status_code == status.HTTP_200_OK
    findings = response.json()
    assert len(findings) == 1
    finding = findings[0]
    assert finding["finding_type"] == "temporal_leakage"
    assert finding["evidence"]["time_column"] == "event_date"
    assert finding["evidence"]["split_column"] == "split"


def test_individual_finding_api_returns_temporal_leakage(client, test_db):
    # Upload a dataset with temporal overlap
    import pandas as pd
    df = pd.DataFrame({
        'event_date': ['2025-01-01', '2025-01-10', '2025-01-20', '2025-01-15', '2025-01-30'],
        'split': ['train', 'train', 'train', 'test', 'test']
    })
    csv_content = df.to_csv(index=False).encode()

    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test individual finding temporal leakage",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis to create a temporal leakage finding
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?time_column=event_date&split_column=split"
    )
    assert response.status_code == status.HTTP_200_OK
    analysis_result = response.json()
    finding_id = analysis_result["findings"][0]["id"]

    # Get the individual finding
    response = client.get(f"/api/v1/findings/{finding_id}")
    assert response.status_code == status.HTTP_200_OK
    finding = response.json()
    assert finding["finding_type"] == "temporal_leakage"
    assert finding["evidence"]["time_column"] == "event_date"
    assert finding["evidence"]["split_column"] == "split"