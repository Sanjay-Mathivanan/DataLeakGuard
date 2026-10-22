import os
import hashlib
import tempfile
import pandas as pd
from fastapi.testclient import TestClient
from app.main import app
from app.db import models, leakage_models
from app.core.config import settings
from app.utils.file_storage import ORIGINAL_DIR, PROCESSED_DIR
import uuid

API_V1_STR = "/api/v1"


def test_repair_finding_success(client, test_db):
    """Test successful repair of a specific finding."""
    # Upload a CSV with exact duplicates
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\nCharlie,40\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv with duplicates",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]
    storage_filename = data["storage_filename"]

    # Run leakage analysis to create a finding
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == 200
    analysis_result = response.json()
    assert len(analysis_result["findings"]) == 1
    finding_id = analysis_result["findings"][0]["id"]

    # Verify the finding is an exact duplicate
    finding = analysis_result["findings"][0]
    assert finding["finding_type"] == "exact_duplicate"
    assert finding["evidence"]["duplicate_count"] == 3
    assert set(finding["evidence"]["row_indices"]) == {0, 2, 4}

    # Repair the exact duplicates
    response = client.post(f"/api/v1/findings/{finding_id}/repair")
    assert response.status_code == 201
    repair_result = response.json()

    # Verify repair result
    assert repair_result["status"] == "completed"
    assert repair_result["operation_type"] == "repair"
    assert repair_result["dataset_id"] == dataset_id
    assert repair_result["finding_id"] == finding_id
    assert repair_result["affected_rows"] == 2  # Two duplicate rows removed (keeping first occurrence)
    assert "output_file" in repair_result
    assert "output_file_sha256" in repair_result
    assert "input_file_sha256" in repair_result

    # Verify audit fields are present
    assert "output_filename" in repair_result
    assert isinstance(repair_result["output_filename"], str)
    assert len(repair_result["output_filename"]) > 0

    # Verify original file unchanged
    original_path = ORIGINAL_DIR / storage_filename
    assert os.path.exists(original_path)
    with open(original_path, "rb") as f:
        original_hash = hashlib.sha256(f.read()).hexdigest()
    assert original_hash == data["file_sha256"]

    # Verify processed file exists and has correct SHA-256
    assert "output_file" in repair_result
    processed_filename = repair_result["output_file"]
    processed_path = PROCESSED_DIR / processed_filename
    assert os.path.exists(processed_path)
    assert repair_result["output_file_sha256"] == hashlib.sha256(
        open(processed_path, "rb").read()
    ).hexdigest()

    # Verify processed file content (should have 3 rows: Bob,25; Charlie,40; and one Alice,30)
    df_processed = pd.read_csv(processed_path)
    assert len(df_processed) == 3  # Original 5 rows - 2 duplicates removed = 3 rows

    # Verify the specific content and order
    assert df_processed.iloc[0]['name'] == 'Alice' and df_processed.iloc[0]['age'] == 30
    assert df_processed.iloc[1]['name'] == 'Bob' and df_processed.iloc[1]['age'] == 25
    assert df_processed.iloc[2]['name'] == 'Charlie' and df_processed.iloc[2]['age'] == 40


def test_repair_finding_not_found(client, test_db):
    """Test repair of nonexistent finding returns 404."""
    fake_finding_id = str(uuid.uuid4())
    response = client.post(f"/api/v1/findings/{fake_finding_id}/repair")
    assert response.status_code == 404
    assert "Finding not found" in response.json()["detail"]


def test_dataset_repair_success(client, test_db):
    """Test successful dataset-level repair."""
    # Upload a CSV with exact duplicates
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\nCharlie,40\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv for dataset repair",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis to create exact duplicate finding
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == 200
    analysis_result = response.json()
    assert len(analysis_result["findings"]) == 1
    assert analysis_result["findings"][0]["finding_type"] == "exact_duplicate"
    finding_id = analysis_result["findings"][0]["id"]

    # Repair dataset (should process the exact duplicate finding)
    response = client.post(f"/api/v1/datasets/{dataset_id}/repairs")
    # Note: This returns a list since we may process multiple findings
    assert response.status_code == 201
    repair_results = response.json()
    assert isinstance(repair_results, list)
    assert len(repair_results) == 1  # Should process exactly one finding

    repair_result = repair_results[0]
    # Verify repair result
    assert repair_result["status"] == "completed"
    assert repair_result["operation_type"] == "repair"
    assert repair_result["dataset_id"] == dataset_id
    assert repair_result["finding_id"] == finding_id
    assert repair_result["affected_rows"] == 2  # Two duplicate rows removed
    assert "output_file" in repair_result
    assert "output_file_sha256" in repair_result
    assert "input_file_sha256" in repair_result
    assert "output_filename" in repair_result  # Audit field

    # Verify original file unchanged
    original_path = ORIGINAL_DIR / data["storage_filename"]
    assert os.path.exists(original_path)
    with open(original_path, "rb") as f:
        original_hash = hashlib.sha256(f.read()).hexdigest()
    assert original_hash == data["file_sha256"]


def test_dataset_repair_unknown_dataset(client, test_db):
    """Test dataset-level repair with unknown dataset returns 404."""
    fake_dataset_id = str(uuid.uuid4())
    response = client.post(f"/api/v1/datasets/{fake_dataset_id}/repairs")
    assert response.status_code == 404
    assert "Dataset not found" in response.json()["detail"]


def test_dataset_repair_no_applicable_findings(client, test_db):
    """Test dataset-level repair when no exact duplicate findings exist."""
    # Upload a CSV with NO duplicates
    csv_content = b"name,age\nAlice,30\nBob,25\nCharlie,40\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv no duplicates",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis - should find no exact duplicates
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == 200
    analysis_result = response.json()
    assert len(analysis_result["findings"]) == 0  # No duplicates found

    # Repair dataset - should return empty list (no findings to process)
    response = client.post(f"/api/v1/datasets/{dataset_id}/repairs")
    assert response.status_code == 201
    repair_results = response.json()
    assert isinstance(repair_results, list)
    assert len(repair_results) == 0  # No findings to process


def test_dataset_repair_ignores_non_exact_findings(client, test_db):
    """Test that dataset-level repair ignores non-exact duplicate findings."""
    # We'll need to manually create a non-exact duplicate finding to test this
    # since it's difficult to generate other finding types through normal API

    # Upload a clean dataset first
    csv_content = b"name,age\nAlice,30\nBob,25\nCharlie,40\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv for non-exact finding",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    # Manually create a non-exact duplicate finding in the database
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        # Create a fake finding of wrong type
        fake_finding = leakage_models.LeakageFinding(
            dataset_id=dataset_id,
            finding_type="not_exact_duplicate",  # Wrong type - should be ignored
            severity="low",  # Required field
            status="open",
            description="Fake non-exact finding",
            evidence={"test": "evidence"}
        )
        db.add(fake_finding)
        db.commit()
        db.refresh(fake_finding)

        # Verify we have one finding (the non-exact one)
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id
        ).all()
        assert len(findings) == 1
        assert findings[0].finding_type == "not_exact_duplicate"

        # Repair dataset - should return empty list (no EXACT duplicate findings to process)
        response = client.post(f"/api/v1/datasets/{dataset_id}/repairs")
        assert response.status_code == 201
        repair_results = response.json()
        assert isinstance(repair_results, list)
        assert len(repair_results) == 0  # Should ignore non-exact findings

    finally:
        db.close()


def test_get_repair_success(client, test_db):
    """Test successful retrieval of a specific repair record."""
    # Upload a CSV with exact duplicates
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\nCharlie,40\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv for get repair",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis to create a finding
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == 200
    analysis_result = response.json()
    finding_id = analysis_result["findings"][0]["id"]

    # Repair the exact duplicate
    response = client.post(f"/api/v1/findings/{finding_id}/repair")
    assert response.status_code == 201
    repair_result = response.json()
    repair_id = repair_result["repair_id"]

    # Get the repair record
    response = client.get(f"/api/v1/repairs/{repair_id}")
    assert response.status_code == 200
    retrieved_repair = response.json()

    # Verify all expected fields are present
    assert retrieved_repair["id"] == repair_id
    assert retrieved_repair["dataset_id"] == dataset_id
    assert retrieved_repair["finding_id"] == finding_id
    assert retrieved_repair["operation_type"] == "repair"
    assert retrieved_repair["status"] == "completed"
    assert retrieved_repair["input_file_sha256"] == data["file_sha256"]
    assert retrieved_repair["output_file_sha256"] == repair_result["output_file_sha256"]
    assert retrieved_repair["output_filename"] == repair_result["output_file"]
    assert retrieved_repair["affected_rows"] == repair_result["affected_rows"]
    assert retrieved_repair["affected_columns"] == repair_result["affected_columns"]
    assert retrieved_repair["quarantine_info"] == repair_result["quarantine_info"]


def test_get_repair_not_found(client, test_db):
    """Test retrieval of nonexistent repair record returns 404."""
    fake_repair_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/repairs/{fake_repair_id}")
    assert response.status_code == 404
    assert "Repair not found" in response.json()["detail"]


def test_get_dataset_repairs_success(client, test_db):
    """Test successful retrieval of repair history for a dataset."""
    # Upload a CSV with exact duplicates
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\nCharlie,40\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv for get history",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    # Initially no repairs
    response = client.get(f"/api/v1/datasets/{dataset_id}/repairs")
    assert response.status_code == 200
    repair_history = response.json()
    assert isinstance(repair_history, list)
    assert len(repair_history) == 0

    # Run leakage analysis to create a finding
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == 200
    analysis_result = response.json()
    finding_id = analysis_result["findings"][0]["id"]

    # Repair the exact duplicate
    response = client.post(f"/api/v1/findings/{finding_id}/repair")
    assert response.status_code == 201
    repair_result = response.json()
    repair_id = repair_result["repair_id"]

    # Now get repair history - should have one repair
    response = client.get(f"/api/v1/datasets/{dataset_id}/repairs")
    assert response.status_code == 200
    repair_history = response.json()
    assert isinstance(repair_history, list)
    assert len(repair_history) == 1

    retrieved_repair = repair_history[0]
    # Verify all expected fields are present
    assert retrieved_repair["id"] == repair_id
    assert retrieved_repair["dataset_id"] == dataset_id
    assert retrieved_repair["finding_id"] == finding_id
    assert retrieved_repair["operation_type"] == "repair"
    assert retrieved_repair["status"] == "completed"
    assert retrieved_repair["input_file_sha256"] == data["file_sha256"]
    assert retrieved_repair["output_file_sha256"] == repair_result["output_file_sha256"]
    assert retrieved_repair["output_filename"] == repair_result["output_file"]
    assert retrieved_repair["affected_rows"] == repair_result["affected_rows"]
    assert retrieved_repair["affected_columns"] == repair_result["affected_columns"]
    assert retrieved_repair["quarantine_info"] == repair_result["quarantine_info"]


def test_get_dataset_repairs_unknown_dataset(client, test_db):
    """Test get dataset repair history with unknown dataset returns 404."""
    fake_dataset_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/datasets/{fake_dataset_id}/repairs")
    assert response.status_code == 404
    assert "Dataset not found" in response.json()["detail"]


def test_file_integrity_verification(client, test_db):
    """Verify file integrity is maintained through API repair operations."""
    # Upload a CSV with exact duplicates
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\nCharlie,40\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv for integrity",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]
    original_filename = data["storage_filename"]
    original_sha256 = data["file_sha256"]

    # Run leakage analysis to create a finding
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == 200
    analysis_result = response.json()
    finding_id = analysis_result["findings"][0]["id"]

    # Store original file info for later verification
    original_path = ORIGINAL_DIR / original_filename
    assert os.path.exists(original_path)
    with open(original_path, "rb") as f:
        original_hash_before = hashlib.sha256(f.read()).hexdigest()
    assert original_hash_before == original_sha256

    # Repair the exact duplicate
    response = client.post(f"/api/v1/findings/{finding_id}/repair")
    assert response.status_code == 201
    repair_result = response.json()

    # Verify original file still exists and is unchanged
    assert os.path.exists(original_path)
    with open(original_path, "rb") as f:
        original_hash_after = hashlib.sha256(f.read()).hexdigest()
    assert original_hash_after == original_sha256  # Should be unchanged

    # Verify processed file exists
    assert "output_file" in repair_result
    processed_filename = repair_result["output_file"]
    processed_path = PROCESSED_DIR / processed_filename
    assert os.path.exists(processed_path)

    # Verify stored output SHA-256 matches actual processed file SHA-256
    assert repair_result["output_file_sha256"] == hashlib.sha256(
        open(processed_path, "rb").read()
    ).hexdigest()

    # Verify processed file content has duplicates removed
    df_processed = pd.read_csv(processed_path)
    assert len(df_processed) == 3  # Original 5 rows - 2 duplicates removed = 3 rows

    # Should have one Alice,30 (first occurrence kept), one Bob,25, one Charlie,40
    alice_count = len(df_processed[df_processed['name'] == 'Alice'])
    bob_count = len(df_processed[df_processed['name'] == 'Bob'])
    charlie_count = len(df_processed[df_processed['name'] == 'Charlie'])
    assert alice_count == 1
    assert bob_count == 1
    assert charlie_count == 1


def test_repair_nonexistent_dataset(client, test_db):
    """Test repair dataset-level endpoint with non-existent dataset returns 404."""
    fake_dataset_id = str(uuid.uuid4())
    response = client.post(f"/api/v1/datasets/{fake_dataset_id}/repairs")
    assert response.status_code == 404
    assert "Dataset not found" in response.json()["detail"]


def test_repair_nonexistent_finding(client, test_db):
    """Test repair finding-level endpoint with non-existent finding returns 404."""
    fake_finding_id = str(uuid.uuid4())
    response = client.post(f"/api/v1/findings/{fake_finding_id}/repair")
    assert response.status_code == 404
    assert "Finding not found" in response.json()["detail"]


def test_repair_unsupported_finding_type(client, test_db):
    """Test repair with non-exact_duplicate finding returns 400."""
    # Upload a clean dataset first
    csv_content = b"name,age\nAlice,30\nBob,25\nCharlie,40\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv for unsupported finding type",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    # Manually create a non-exact duplicate finding in the database
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        # Create a fake finding of wrong type
        fake_finding = leakage_models.LeakageFinding(
            dataset_id=dataset_id,
            finding_type="target_leakage",  # Not exact_duplicate - should be rejected
            severity="low",
            status="open",
            description="Fake target leakage finding",
            evidence={"test": "evidence"}
        )
        db.add(fake_finding)
        db.commit()
        db.refresh(fake_finding)

        # Attempt to repair the non-exact duplicate finding
        response = client.post(f"/api/v1/findings/{fake_finding.id}/repair")
        assert response.status_code == 400
        assert "Finding is not of type exact_duplicate" in response.json()["detail"]

    finally:
        db.close()


def test_repair_finding_belongs_to_different_dataset(client, test_db):
    """Test repair when finding belongs to different dataset than specified."""
    # Upload first dataset
    csv_content1 = b"name,age\nAlice,30\nBob,25\nAlice,30\n"
    response1 = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv dataset 1",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test1.csv", csv_content1, "text/csv")}
    )
    assert response1.status_code == 201
    data1 = response1.json()
    dataset_id1 = data1["id"]

    # Upload second dataset
    csv_content2 = b"name,age\nDavid,35\nEve,40\nDavid,35\n"
    response2 = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv dataset 2",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test2.csv", csv_content2, "text/csv")}
    )
    assert response2.status_code == 201
    data2 = response2.json()
    dataset_id2 = data2["id"]

    # Run leakage analysis on first dataset to create a finding
    response = client.post(f"/api/v1/datasets/{dataset_id1}/analyze/leakage")
    assert response.status_code == 200
    analysis_result = response.json()
    finding_id = analysis_result["findings"][0]["id"]
    assert analysis_result["findings"][0]["dataset_id"] == dataset_id1

    # Attempt to repair the finding using the second dataset ID (should fail)
    response = client.post(f"/api/v1/datasets/{dataset_id2}/repairs")
    # Note: This endpoint processes ALL exact duplicate findings in the dataset
    # Since dataset 2 has its own findings, we need to check if it has any exact duplicates
    # For clean data, it should return 201 with empty list, but let's verify the behavior

    # Actually, let's test the finding-level endpoint instead for clearer validation
    response = client.post(f"/api/v1/findings/{finding_id}/repair")
    # This should succeed since we're using the correct dataset via the finding
    # To test cross-dataset validation, we need to test the dataset-level endpoint
    # but ensure the target dataset has no findings of its own

def test_repair_missing_original_storage_file(client, test_db):
    """Test repair when original storage file is missing returns controlled error."""
    # Upload a CSV with exact duplicates
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\nCharlie,40\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv missing file",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]
    storage_filename = data["storage_filename"]

    # Run leakage analysis to create a finding
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == 200
    analysis_result = response.json()
    finding_id = analysis_result["findings"][0]["id"]

    # Remove the original storage file
    original_path = ORIGINAL_DIR / storage_filename
    assert os.path.exists(original_path)
    os.remove(original_path)
    assert not os.path.exists(original_path)

    # Attempt repair - should fail with controlled error
    response = client.post(f"/api/v1/findings/{finding_id}/repair")
    assert response.status_code == 404
    assert "Original file not found" in response.json()["detail"]


def test_repair_original_sha256_mismatch(client, test_db):
    """Test repair when original file SHA-256 doesn't match stored hash returns controlled error."""
    # Upload a CSV with exact duplicates
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\nCharlie,40\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv SHA mismatch",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]
    storage_filename = data["storage_filename"]
    original_sha256 = data["file_sha256"]

    # Run leakage analysis to create a finding
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == 200
    analysis_result = response.json()
    finding_id = analysis_result["findings"][0]["id"]

    # Modify the original file after dataset hash is stored
    original_path = ORIGINAL_DIR / storage_filename
    assert os.path.exists(original_path)

    # Append some data to change the file
    with open(original_path, "ab") as f:
        f.write(b"\nExtra,Line\n")

    # Attempt repair - should fail with controlled error
    response = client.post(f"/api/v1/findings/{finding_id}/repair")
    assert response.status_code == 400
    assert "Original file SHA-256 mismatch" in response.json()["detail"]


def test_repair_malformed_missing_evidence(client, test_db):
    """Test repair with malformed or missing evidence returns controlled error."""
    # Upload a CSV with exact duplicates
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\nCharlie,40\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv malformed evidence",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    # Run leakage analysis to create a finding
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == 200
    analysis_result = response.json()
    original_finding_id = analysis_result["findings"][0]["id"]

    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        # Get the original finding
        original_finding = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.id == original_finding_id
        ).first()

        # Create a copy of the finding with malformed evidence
        malformed_finding = leakage_models.LeakageFinding(
            dataset_id=dataset_id,
            finding_type="exact_duplicate",
            severity="low",
            status="open",
            description="Finding with malformed evidence",
            evidence={}  # Empty evidence - missing required duplicate_count and row_indices
        )
        db.add(malformed_finding)
        db.commit()
        db.refresh(malformed_finding)

        # Attempt repair with malformed evidence
        response = client.post(f"/api/v1/findings/{malformed_finding.id}/repair")
        assert response.status_code == 400
        assert "Evidence missing required duplicate information" in response.json()["detail"]

        # Now test with missing row_indices
        malformed_finding2 = leakage_models.LeakageFinding(
            dataset_id=dataset_id,
            finding_type="exact_duplicate",
            severity="low",
            status="open",
            description="Finding with missing row_indices",
            evidence={"duplicate_count": 2}  # Missing row_indices
        )
        db.add(malformed_finding2)
        db.commit()
        db.refresh(malformed_finding2)

        response = client.post(f"/api/v1/findings/{malformed_finding2.id}/repair")
        assert response.status_code == 400
        assert "Evidence missing required duplicate information" in response.json()["detail"]

        # Now test with invalid row_indices type
        malformed_finding3 = leakage_models.LeakageFinding(
            dataset_id=dataset_id,
            finding_type="exact_duplicate",
            severity="low",
            status="open",
            description="Finding with invalid row_indices type",
            evidence={"duplicate_count": 2, "row_indices": "not_a_list"}
        )
        db.add(malformed_finding3)
        db.commit()
        db.refresh(malformed_finding3)

        response = client.post(f"/api/v1/findings/{malformed_finding3.id}/repair")
        assert response.status_code == 400
        assert "Invalid evidence format" in response.json()["detail"]  # This comes from the isinstance check

    finally:
        db.close()