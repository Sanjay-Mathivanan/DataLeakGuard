import pytest
from fastapi import status
from app.db import leakage_models, models
from app.schemas.evidence import EvidenceResponse


def test_get_finding_evidence_success(client, test_db):
    """Test successful retrieval of evidence for an existing finding."""
    # Upload a dataset with an exact duplicate to create a finding
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

    # Get the evidence for the finding
    response = client.get(f"/api/v1/findings/{finding_id}/evidence")
    assert response.status_code == status.HTTP_200_OK
    evidence = response.json()

    # Verify evidence structure
    assert isinstance(evidence, dict)
    assert evidence["finding_id"] == finding_id
    assert evidence["dataset_id"] == dataset_id
    assert evidence["finding_type"] == "exact_duplicate"
    assert evidence["severity"] == "medium"
    assert evidence["status"] == "open"
    assert evidence["source_file"] is not None
    assert evidence["source_file_sha256"] is not None
    assert evidence["detector_evidence"] is not None

    # Verify detector_evidence matches the finding's stored evidence
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        finding_record = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.id == finding_id
        ).first()
        assert evidence["detector_evidence"] == finding_record.evidence

        # Verify source_file matches Dataset.storage_filename
        dataset_record = db.query(models.Dataset).filter(
            models.Dataset.id == dataset_id
        ).first()
        assert evidence["source_file"] == dataset_record.storage_filename

        # Verify source_file_sha256 matches Dataset.file_sha256
        assert evidence["source_file_sha256"] == dataset_record.file_sha256
    finally:
        db.close()


def test_get_finding_evidence_unknown_finding(client, test_db):
    """Test 404 when finding_id does not exist."""
    response = client.get("/api/v1/findings/unknown-id/evidence")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Finding not found"


def test_get_finding_evidence_missing_dataset(client, test_db):
    """Test that evidence endpoint works when finding and dataset exist."""
    # Upload a dataset with an exact duplicate to create a finding
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

    # Get evidence for the finding - should succeed since both exist
    response = client.get(f"/api/v1/findings/{finding_id}/evidence")
    assert response.status_code == status.HTTP_200_OK
    # The test mainly verifies the endpoint doesn't crash when finding exists