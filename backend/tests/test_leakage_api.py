import pytest
from fastapi import status
from app.db import leakage_models


def test_analyze_valid_dataset(client, test_db):
    # Upload a CSV with an exact duplicate
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\n"
    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test csv",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert result["dataset_id"] == dataset_id
    assert result["rows_examined"] == 3
    assert result["duplicate_group_count"] == 1
    assert result["duplicated_row_count"] == 2
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["finding_type"] == "exact_duplicate"
    assert finding["severity"] == "medium"
    assert finding["status"] == "open"
    assert "Exact duplicate rows detected: 2 rows share identical content." in finding["description"]
    assert finding["evidence"]["duplicate_count"] == 2
    assert set(finding["evidence"]["row_indices"]) == {0, 2}

    # Verify that a LeakageFinding record was created in the database
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id
        ).all()
        assert len(findings) == 1
        db_finding = findings[0]
        assert db_finding.id == finding["id"]
        assert db_finding.finding_type == "exact_duplicate"
        assert db_finding.severity == "medium"
        assert db_finding.status == "open"
        assert db_finding.description == finding["description"]
        assert db_finding.evidence == finding["evidence"]
    finally:
        db.close()


def test_successful_analysis_persists_timestamp_and_target_class_counts(client, test_db):
    upload = client.post(
        "/api/v1/datasets",
        data={
            "name": "target profile",
            "type": "tabular",
            "format": "CSV",
            "description": "target distribution test",
        },
        files={
            "file": (
                "target.csv",
                b"feature,target\nA,yes\nB,no\nA,yes\n",
                "text/csv",
            )
        },
    )
    assert upload.status_code == status.HTTP_201_CREATED
    dataset_id = upload.json()["id"]
    assert upload.json()["last_analysis"] is None

    analyzed = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage",
        params={"target_column": "target"},
    )
    assert analyzed.status_code == status.HTTP_200_OK

    dataset_response = client.get(f"/api/v1/datasets/{dataset_id}")
    assert dataset_response.status_code == status.HTTP_200_OK
    dataset = dataset_response.json()
    assert dataset["status"] == "Analyzed"
    assert dataset["last_analysis"].endswith("+00:00")
    assert dataset["class_count"] == 2
    assert dataset["profile"]["target_column"] == "target"
    assert dataset["profile"]["target_class_counts"] == {"yes": 2, "no": 1}


def test_failed_analysis_preserves_last_successful_timestamp(client, test_db):
    upload = client.post(
        "/api/v1/datasets",
        data={
            "name": "failed analysis state",
            "type": "tabular",
            "format": "CSV",
            "description": "last successful timestamp must survive",
        },
        files={"file": ("data.csv", b"a,b\n1,x\n2,y\n", "text/csv")},
    )
    assert upload.status_code == status.HTTP_201_CREATED
    dataset_id = upload.json()["id"]

    successful = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert successful.status_code == status.HTTP_200_OK
    prior_timestamp = client.get(f"/api/v1/datasets/{dataset_id}").json()["last_analysis"]
    assert prior_timestamp is not None

    failed = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage",
        params={"target_column": "not_a_real_column"},
    )
    assert failed.status_code == status.HTTP_400_BAD_REQUEST
    after_failure = client.get(f"/api/v1/datasets/{dataset_id}").json()
    assert after_failure["status"] == "Analysis failed"
    assert after_failure["last_analysis"] == prior_timestamp

def test_get_dataset_findings(client, test_db):
    # Upload a CSV with an exact duplicate
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\n"
    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test csv",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis to create a finding
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == status.HTTP_200_OK

    # Get findings for the dataset
    response = client.get(f"/api/v1/datasets/{dataset_id}/findings")
    assert response.status_code == status.HTTP_200_OK
    findings = response.json()
    assert len(findings) == 1
    finding = findings[0]
    assert finding["finding_type"] == "exact_duplicate"
    assert finding["evidence"]["duplicate_count"] == 2


def test_get_individual_finding(client, test_db):
    # Upload a CSV with an exact duplicate
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\n"
    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test csv",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis to create a finding
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == status.HTTP_200_OK
    analysis_result = response.json()
    finding_id = analysis_result["findings"][0]["id"]

    # Get the individual finding
    response = client.get(f"/api/v1/findings/{finding_id}")
    assert response.status_code == status.HTTP_200_OK
    finding = response.json()
    assert finding["id"] == finding_id
    assert finding["finding_type"] == "exact_duplicate"
    assert finding["evidence"]["duplicate_count"] == 2


def test_unknown_dataset(client, test_db):
    # Use a non-existent dataset ID
    response = client.post("/api/v1/datasets/unknown-id/analyze/leakage")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Dataset not found"

    response = client.get("/api/v1/datasets/unknown-id/findings")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Dataset not found"


def test_unknown_finding(client, test_db):
    response = client.get("/api/v1/findings/unknown-id")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Finding not found"


def test_repeated_analysis_idempotent(client, test_db):
    # Upload a CSV with an exact duplicate
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\n"
    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "test csv",
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
    response1 = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response1.status_code == status.HTTP_200_OK
    result1 = response1.json()

    # Second analysis
    response2 = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
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
            leakage_models.LeakageFinding.dataset_id == dataset_id
        ).all()
        assert len(findings) == 1
    finally:
        db.close()



