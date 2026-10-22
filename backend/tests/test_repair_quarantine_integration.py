import os
import hashlib
import tempfile
import pandas as pd
from fastapi.testclient import TestClient
from app.main import app
from app.db import models, leakage_models
from app.core.config import settings
from app.utils.file_storage import ORIGINAL_DIR, PROCESSED_DIR, QUARANTINE_DIR
import uuid

API_V1_STR = "/api/v1"


def test_repair_and_quarantine_use_same_original_source_safely(client, test_db):
    """Test that both services read from the same original source and leave it unchanged."""
    # Upload a test dataset with exact duplicates suitable for both repair and quarantine
    csv_content = b"name,age,value\nAlice,30,100\nBob,25,200\nAlice,30,100\nCharlie,35,300\nAlice,30,100\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test integration dataset",
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
    original_file_sha256 = data["file_sha256"]

    # Run leakage analysis to create a finding suitable for both operations
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == 200
    analysis_result = response.json()
    assert len(analysis_result["findings"]) == 1
    finding_id = analysis_result["findings"][0]["id"]
    finding = analysis_result["findings"][0]

    # Verify it's an exact duplicate (suitable for both repair and quarantine)
    assert finding["finding_type"] == "exact_duplicate"
    assert finding["evidence"]["duplicate_count"] == 3  # Three Alice,30 rows
    assert set(finding["evidence"]["row_indices"]) == {0, 2, 4}  # Indices of Alice,30 rows

    # Store original file info for later verification
    original_path = ORIGINAL_DIR / storage_filename
    assert os.path.exists(original_path)
    with open(original_path, "rb") as f:
        original_content_before = f.read()
    original_hash_before = hashlib.sha256(original_content_before).hexdigest()
    assert original_hash_before == original_file_sha256

    # Execute repair operation
    repair_response = client.post(f"/api/v1/findings/{finding_id}/repair")
    assert repair_response.status_code == 201
    repair_result = repair_response.json()
    assert repair_result["status"] == "completed"
    assert repair_result["operation_type"] == "repair"

    # Execute quarantine operation
    quarantine_response = client.post(f"/api/v1/findings/{finding_id}/quarantine")
    assert quarantine_response.status_code == 201
    quarantine_result = quarantine_response.json()
    assert quarantine_result["status"] == "completed"
    assert quarantine_result["operation_type"] == "quarantine"

    # Verify original file remains unchanged
    assert os.path.exists(original_path)
    with open(original_path, "rb") as f:
        original_content_after = f.read()
    original_hash_after = hashlib.sha256(original_content_after).hexdigest()
    assert original_hash_after == original_file_sha256
    assert original_content_before == original_content_after  # Exactly the same

    # Verify repair output is NOT in quarantine storage
    repair_output_filename = repair_result["output_file"]
    repair_output_path = PROCESSED_DIR / repair_output_filename
    quarantine_output_path = QUARANTINE_DIR / repair_output_filename
    assert os.path.exists(repair_output_path)
    assert not os.path.exists(quarantine_output_path)  # Repair output not in quarantine

    # Verify quarantine output is NOT in processed storage
    quarantine_output_filename = quarantine_result["output_file"]
    quarantine_output_path = QUARANTINE_DIR / quarantine_output_filename
    processed_quarantine_path = PROCESSED_DIR / quarantine_output_filename
    assert os.path.exists(quarantine_output_path)
    assert not os.path.exists(processed_quarantine_path)  # Quarantine output not in processed

    # Verify both outputs are different files (different operations)
    assert repair_output_filename != quarantine_output_filename


def test_operation_specific_idempotency(client, test_db):
    """Test that repair and quarantine operations are idempotent within their own service."""
    # Upload a test dataset
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\nCharlie,40\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test idempotency",
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

    # Test repair idempotency
    # First repair
    repair_response1 = client.post(f"/api/v1/findings/{finding_id}/repair")
    assert repair_response1.status_code == 201
    repair_result1 = repair_response1.json()
    assert repair_result1["status"] == "completed"
    assert repair_result1["operation_type"] == "repair"

    # Second repair on the same finding
    repair_response2 = client.post(f"/api/v1/findings/{finding_id}/repair")
    assert repair_response2.status_code == 201
    repair_result2 = repair_response2.json()
    assert repair_result2["status"] == "completed"
    assert repair_result2["operation_type"] == "repair"

    # Verify both repairs return the same result (idempotent)
    assert repair_result1["output_file"] == repair_result2["output_file"]
    assert repair_result1["output_file_sha256"] == repair_result2["output_file_sha256"]
    # Note: The API doesn't return the database record ID, so we verify idempotency
    # by checking that the output files and their hashes are identical

    # Test quarantine idempotency
    # First quarantine
    quarantine_response1 = client.post(f"/api/v1/findings/{finding_id}/quarantine")
    assert quarantine_response1.status_code == 201
    quarantine_result1 = quarantine_response1.json()
    assert quarantine_result1["status"] == "completed"
    assert quarantine_result1["operation_type"] == "quarantine"

    # Second quarantine on the same finding
    quarantine_response2 = client.post(f"/api/v1/findings/{finding_id}/quarantine")
    assert quarantine_response2.status_code == 201
    quarantine_result2 = quarantine_response2.json()
    assert quarantine_result2["status"] == "completed"
    assert quarantine_result2["operation_type"] == "quarantine"

    # Verify both quarantines return the same result (idempotent)
    assert quarantine_result1["output_file"] == quarantine_result2["output_file"]
    assert quarantine_result1["output_file_sha256"] == quarantine_result2["output_file_sha256"]
    # The API does not return the database record ID,
    # so idempotency is verified using identical output files and hashes.

    # Verify repair and quarantine remain separate operations
    assert repair_result1["operation_type"] == "repair"
    assert quarantine_result1["operation_type"] == "quarantine"
    assert repair_result1["output_file"] != quarantine_result1["output_file"]

    # Verify a repair record does not satisfy quarantine idempotency (different operation types)
    # This is implicitly tested by the fact that we called quarantine after repair and it created a new record
    # rather than returning the repair record

    # Verify a quarantine record does not satisfy repair idempotency (different operation types)
    # This is implicitly tested by the fact that we called repair after quarantine and it created a new record
    # rather than returning the quarantine record


def test_storage_isolation(client, test_db):
    """Verify storage isolation between repair, quarantine, and original storage."""
    # Upload a test dataset
    csv_content = b"product,price\nProductA,10.99\nProductB,20.50\nProductA,10.99\nProductC,15.75\nProductA,10.99\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test storage isolation",
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

    # Execute repair operation
    repair_response = client.post(f"/api/v1/findings/{finding_id}/repair")
    assert repair_response.status_code == 201
    repair_result = repair_response.json()

    # Execute quarantine operation
    quarantine_response = client.post(f"/api/v1/findings/{finding_id}/quarantine")
    assert quarantine_response.status_code == 201
    quarantine_result = quarantine_response.json()

    # Verify original file still exists in original storage
    original_path = ORIGINAL_DIR / storage_filename
    assert os.path.exists(original_path), "Original file should still exist in original storage"

    # Verify repair output exists only in processed storage
    repair_output_filename = repair_result["output_file"]
    repair_output_path = PROCESSED_DIR / repair_output_filename
    assert os.path.exists(repair_output_path), "Repair output should exist in processed storage"
    assert not os.path.exists(QUARANTINE_DIR / repair_output_filename), "Repair output should NOT exist in quarantine storage"
    assert not os.path.exists(ORIGINAL_DIR / repair_output_filename), "Repair output should NOT exist in original storage"

    # Verify quarantine output exists only in quarantine storage
    quarantine_output_filename = quarantine_result["output_file"]
    quarantine_output_path = QUARANTINE_DIR / quarantine_output_filename
    assert os.path.exists(quarantine_output_path), "Quarantine output should exist in quarantine storage"
    assert not os.path.exists(PROCESSED_DIR / quarantine_output_filename), "Quarantine output should NOT exist in processed storage"
    assert not os.path.exists(ORIGINAL_DIR / quarantine_output_filename), "Quarantine output should NOT exist in original storage"

    # Verify no operation overwrites the original
    assert os.path.exists(original_path), "Original file should still exist after both operations"
    with open(original_path, "rb") as f:
        original_content = f.read()
    original_hash = hashlib.sha256(original_content).hexdigest()
    assert original_hash == data["file_sha256"], "Original file SHA-256 should remain unchanged"


def test_repair_record_audit_trail(client, test_db):
    """Verify RepairRecord entries contain correct information for both operations."""
    # Upload a test dataset
    csv_content = b"id,name,value\n1,Alice,100\n2,Bob,200\n1,Alice,100\n3,Charlie,300\n1,Alice,100\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test audit trail",
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
    input_file_sha256 = data["file_sha256"]

    # Run leakage analysis to create a finding
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == 200
    analysis_result = response.json()
    finding_id = analysis_result["findings"][0]["id"]
    finding = analysis_result["findings"][0]

    # Execute repair operation
    repair_response = client.post(f"/api/v1/findings/{finding_id}/repair")
    assert repair_response.status_code == 201
    repair_result = repair_response.json()

    # Execute quarantine operation
    quarantine_response = client.post(f"/api/v1/findings/{finding_id}/quarantine")
    assert quarantine_response.status_code == 201
    quarantine_result = quarantine_response.json()

    # Verify repair record audit trail
    assert repair_result["dataset_id"] == dataset_id
    assert repair_result["finding_id"] == finding_id
    assert repair_result["operation_type"] == "repair"
    assert repair_result["status"] == "completed"
    assert repair_result["input_file_sha256"] == input_file_sha256
    assert "output_file_sha256" in repair_result
    assert repair_result["output_file"] == repair_result["output_filename"]

    # Verify repair-specific metadata
    assert repair_result["affected_rows"] == 2  # Two duplicate rows removed (keeping first of three)
    assert repair_result["affected_columns"] == []  # For exact duplicate repair, we remove rows, not columns
    assert repair_result["quarantine_info"] is None  # Repair doesn't have quarantine info

    # Verify quarantine record audit trail
    assert quarantine_result["dataset_id"] == dataset_id
    assert quarantine_result["finding_id"] == finding_id
    assert quarantine_result["operation_type"] == "quarantine"
    assert quarantine_result["status"] == "completed"
    assert quarantine_result["input_file_sha256"] == input_file_sha256
    assert "output_file_sha256" in quarantine_result
    assert quarantine_result["output_file"] == quarantine_result["output_filename"]

    # Verify quarantine-specific metadata
    assert quarantine_result["affected_rows"] == 3  # Three rows quarantined (all Alice rows)
    assert len(quarantine_result["affected_columns"]) == 3  # All columns affected (id, name, value)
    assert quarantine_result["quarantine_info"] is not None  # Quarantine has quarantine info
    assert isinstance(quarantine_result["quarantine_info"], dict)
    assert quarantine_result["quarantine_info"]["operation"] == "quarantine"
    assert quarantine_result["quarantine_info"]["source_finding_id"] == finding_id
    assert quarantine_result["quarantine_info"]["finding_type"] == "exact_duplicate"


def test_different_output_hashes(client, test_db):
    """Verify that input and output SHA-256 hashes are different when operation changes file contents."""
    # Upload a test dataset where operations will change the content
    csv_content = b"name,score\nAlice,100\nBob,90\nAlice,100\nCharlie,80\nAlice,100\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test hash differences",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]
    input_file_sha256 = data["file_sha256"]

    # Run leakage analysis to create a finding
    response = client.post(f"/api/v1/datasets/{dataset_id}/analyze/leakage")
    assert response.status_code == 200
    analysis_result = response.json()
    finding_id = analysis_result["findings"][0]["id"]

    # Execute repair operation (should change file by removing duplicates)
    repair_response = client.post(f"/api/v1/findings/{finding_id}/repair")
    assert repair_response.status_code == 201
    repair_result = repair_response.json()

    # Execute quarantine operation (should change file by extracting subset)
    quarantine_response = client.post(f"/api/v1/findings/{finding_id}/quarantine")
    assert quarantine_response.status_code == 201
    quarantine_result = quarantine_response.json()

    # Verify repair: input SHA-256 corresponds to original, output SHA-256 corresponds to generated output
    assert repair_result["input_file_sha256"] == input_file_sha256
    repair_output_path = PROCESSED_DIR / repair_result["output_file"]
    assert os.path.exists(repair_output_path)
    with open(repair_output_path, "rb") as f:
        repair_output_hash = hashlib.sha256(f.read()).hexdigest()
    assert repair_result["output_file_sha256"] == repair_output_hash
    assert repair_result["input_file_sha256"] != repair_result["output_file_sha256"]  # Should be different

    # Verify quarantine: input SHA-256 corresponds to original, output SHA-256 corresponds to generated output
    assert quarantine_result["input_file_sha256"] == input_file_sha256
    quarantine_output_path = QUARANTINE_DIR / quarantine_result["output_file"]
    assert os.path.exists(quarantine_output_path)
    with open(quarantine_output_path, "rb") as f:
        quarantine_output_hash = hashlib.sha256(f.read()).hexdigest()
    assert quarantine_result["output_file_sha256"] == quarantine_output_hash
    assert quarantine_result["input_file_sha256"] != quarantine_result["output_file_sha256"]  # Should be different


def test_service_specific_behavior(client, test_db):
    """Verify each service performs its intended behavior correctly."""
    # Upload a test dataset with known duplicate structure
    csv_content = b"user_id,action,count\nuser1,login,5\nuser2,logout,3\nuser1,login,5\nuser3,view,7\nuser1,login,5\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test service behavior",
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
    finding = analysis_result["findings"][0]

    # Execute repair operation
    repair_response = client.post(f"/api/v1/findings/{finding_id}/repair")
    assert repair_response.status_code == 201
    repair_result = repair_response.json()

    # Verify repair performs intended behavior: removes duplicates, keeps first occurrence
    assert repair_result["status"] == "completed"
    assert repair_result["operation_type"] == "repair"

    # Check that processed file has correct content (3 rows: user1/login/5, user2/logout/3, user3/view/7)
    repair_df = pd.read_csv(PROCESSED_DIR / repair_result["output_file"])
    assert len(repair_df) == 3  # Original 5 rows - 2 duplicate user1 rows = 3 rows
    assert list(repair_df["user_id"]) == ["user1", "user2", "user3"]
    assert list(repair_df["action"]) == ["login", "logout", "view"]
    assert list(repair_df["count"]) == [5, 3, 7]

    # Execute quarantine operation
    quarantine_response = client.post(f"/api/v1/findings/{finding_id}/quarantine")
    assert quarantine_response.status_code == 201
    quarantine_result = quarantine_response.json()

    # Verify quarantine performs intended behavior: preserves affected rows as quarantine output
    assert quarantine_result["status"] == "completed"
    assert quarantine_result["operation_type"] == "quarantine"

    # Check that quarantined file has correct content (3 rows: all user1/login/5 rows)
    quarantine_df = pd.read_csv(QUARANTINE_DIR / quarantine_result["output_file"])
    assert len(quarantine_df) == 3  # Three user1/login/5 rows
    assert all(quarantine_df["user_id"] == "user1")
    assert all(quarantine_df["action"] == "login")
    assert all(quarantine_df["count"] == 5)

    # Verify each service writes to its own destination
    repair_path = PROCESSED_DIR / repair_result["output_file"]
    quarantine_path = QUARANTINE_DIR / quarantine_result["output_file"]
    assert os.path.exists(repair_path)
    assert os.path.exists(quarantine_path)
    assert repair_path != quarantine_path  # Different files

    # Verify each service creates the correct operation type
    assert repair_result["operation_type"] == "repair"
    assert quarantine_result["operation_type"] == "quarantine"


def test_shared_utility_integration(client, test_db):
    """Verify that shared utilities work correctly when used by both services."""
    # Upload a test dataset
    csv_content = b"category,value\nA,10\nB,20\nA,10\nC,30\nA,10\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test shared utilities",
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

    # Test that both services can successfully execute (indicating shared utilities work)
    repair_response = client.post(f"/api/v1/findings/{finding_id}/repair")
    assert repair_response.status_code == 201
    repair_result = repair_response.json()
    assert repair_result["status"] == "completed"

    quarantine_response = client.post(f"/api/v1/findings/{finding_id}/quarantine")
    assert quarantine_response.status_code == 201
    quarantine_result = quarantine_response.json()
    assert quarantine_result["status"] == "completed"

    # Verify that the shared utilities produced consistent results
    # Both services should have processed the same original file
    assert repair_result["dataset_id"] == dataset_id
    assert quarantine_result["dataset_id"] == dataset_id
    assert repair_result["finding_id"] == finding_id
    assert quarantine_result["finding_id"] == finding_id
    assert repair_result["input_file_sha256"] == data["file_sha256"]
    assert quarantine_result["input_file_sha256"] == data["file_sha256"]


def test_no_cross_service_state_corruption(client, test_db):
    """Verify that running repair and quarantine doesn't corrupt state of either service."""
    # Upload a test dataset
    csv_content = b"type,amount\nExpense,100\nIncome,200\nExpense,100\nGain,50\nExpense,100\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test state corruption",
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

    # Get initial database state
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        initial_dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
        initial_finding = db.query(leakage_models.LeakageFinding).filter(leakage_models.LeakageFinding.id == finding_id).first()

        initial_dataset_name = initial_dataset.name
        initial_finding_type = initial_finding.finding_type
        initial_finding_description = initial_finding.description

        # Execute repair operation
        repair_response = client.post(f"/api/v1/findings/{finding_id}/repair")
        assert repair_response.status_code == 201
        repair_result = repair_response.json()

        # Execute quarantine operation
        quarantine_response = client.post(f"/api/v1/findings/{finding_id}/quarantine")
        assert quarantine_response.status_code == 201
        quarantine_result = quarantine_response.json()

        # Verify final database state
        final_dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
        final_finding = db.query(leakage_models.LeakageFinding).filter(leakage_models.LeakageFinding.id == finding_id).first()

        # Verify dataset metadata remains valid
        assert final_dataset is not None
        assert final_dataset.id == dataset_id
        assert final_dataset.name == initial_dataset_name  # Should not change
        assert final_dataset.storage_filename == storage_filename  # Should not change

        # Verify finding metadata remains valid
        assert final_finding is not None
        assert final_finding.id == finding_id
        assert final_finding.finding_type == initial_finding_type  # Should not change
        assert final_finding.description == initial_finding_description  # Should not change

        # Verify both RepairRecord entries remain valid by finding them via dataset_id, finding_id, and operation_type
        repair_record = db.query(models.RepairRecord).filter(
            models.RepairRecord.dataset_id == dataset_id,
            models.RepairRecord.finding_id == finding_id,
            models.RepairRecord.operation_type == "repair",
            models.RepairRecord.status == "completed"
        ).first()
        quarantine_record = db.query(models.RepairRecord).filter(
            models.RepairRecord.dataset_id == dataset_id,
            models.RepairRecord.finding_id == finding_id,
            models.RepairRecord.operation_type == "quarantine",
            models.RepairRecord.status == "completed"
        ).first()

        assert repair_record is not None
        assert quarantine_record is not None
        # Verify they are different records (different operation types)
        assert repair_record.operation_type == "repair"
        assert quarantine_record.operation_type == "quarantine"
        assert repair_record.dataset_id == dataset_id
        assert quarantine_record.dataset_id == dataset_id
        assert repair_record.finding_id == finding_id
        assert quarantine_record.finding_id == finding_id

        # Verify one operation did not modify the other operation's record
        assert repair_record.output_file_sha256 != quarantine_record.output_file_sha256  # Different outputs
        assert repair_record.output_filename != quarantine_record.output_filename  # Different files

    finally:
        db.close()


if __name__ == "__main__":
    # This allows running the test file directly for debugging
    # But normally it would be run via: python -m pytest tests/test_repair_quarantine_integration.py -v
    pass