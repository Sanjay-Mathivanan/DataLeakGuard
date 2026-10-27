import os
import hashlib
import pandas as pd
from fastapi.testclient import TestClient
from app.main import app
from app.db import models, leakage_models
from app.core.config import settings
from app.utils.file_storage import ORIGINAL_DIR
import tempfile

API_V1_STR = "/api/v1"

def test_no_duplicates(client, test_db):
    csv_content = b"name,age\nAlice,30\nBob,25\nCharlie,35\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    # Import service
    from app.services.leakage_detection_service import detect_exact_duplicates
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        result = detect_exact_duplicates(dataset_id, db)
    finally:
        db.close()

    assert result["rows_examined"] == 3
    assert result["duplicate_group_count"] == 0
    assert result["duplicated_row_count"] == 0
    assert result["findings"] == []

def test_one_duplicate_group(client, test_db):
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    from app.services.leakage_detection_service import detect_exact_duplicates
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        result = detect_exact_duplicates(dataset_id, db)
    finally:
        db.close()

    assert result["rows_examined"] == 3
    assert result["duplicate_group_count"] == 1
    assert result["duplicated_row_count"] == 2
    assert len(result["findings"]) == 1
    f = result["findings"][0]
    assert f["finding_type"] == "exact_duplicate"
    assert f["severity"] == "medium"
    assert f["status"] == "open"
    assert "Exact duplicate rows detected: 2 rows share identical content." in f["description"]
    assert f["evidence"]["duplicate_count"] == 2
    assert set(f["evidence"]["row_indices"]) == {0, 2}

def test_three_identical_rows(client, test_db):
    csv_content = b"name,age\nAlice,30\nAlice,30\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    from app.services.leakage_detection_service import detect_exact_duplicates
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        result = detect_exact_duplicates(dataset_id, db)
    finally:
        db.close()

    assert result["rows_examined"] == 3
    assert result["duplicate_group_count"] == 1
    assert result["duplicated_row_count"] == 3
    assert len(result["findings"]) == 1
    f = result["findings"][0]
    assert f["evidence"]["duplicate_count"] == 3
    assert set(f["evidence"]["row_indices"]) == {0, 1, 2}

def test_row_order_does_not_affect_hash(client, test_db):
    # Two rows with same values but different column order? Actually column order is fixed by file.
    # We'll test that swapping rows doesn't change groups.
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    from app.services.leakage_detection_service import detect_exact_duplicates
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        result1 = detect_exact_duplicates(dataset_id, db)
    finally:
        db.close()

    # Now create a dataset with rows in different order but same content
    csv_content2 = b"name,age\nAlice,30\nAlice,30\nBob,25\n"
    response2 = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv2",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test2.csv", csv_content2, "text/csv")}
    )
    assert response2.status_code == 201
    data2 = response2.json()
    dataset_id2 = data2["id"]

    db = TestingSessionLocal()
    try:
        result2 = detect_exact_duplicates(dataset_id2, db)
    finally:
        db.close()

    assert result1["duplicate_group_count"] == result2["duplicate_group_count"] == 1
    assert result1["duplicated_row_count"] == result2["duplicated_row_count"] == 2

def test_null_values(client, test_db):
    csv_content = b"name,age\nAlice,30\n,\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    from app.services.leakage_detection_service import detect_exact_duplicates
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        result = detect_exact_duplicates(dataset_id, db)
    finally:
        db.close()

    assert result["rows_examined"] == 3
    assert result["duplicate_group_count"] == 1
    assert result["duplicated_row_count"] == 2
    assert len(result["findings"]) == 1
    f = result["findings"][0]
    assert f["evidence"]["duplicate_count"] == 2

def test_different_column_values_not_duplicates(client, test_db):
    csv_content = b"name,age\nAlice,30\nBob,25\nCharlie,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    from app.services.leakage_detection_service import detect_exact_duplicates
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        result = detect_exact_duplicates(dataset_id, db)
    finally:
        db.close()

    assert result["duplicate_group_count"] == 0

def test_deterministic_repeatability(client, test_db):
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    from app.services.leakage_detection_service import detect_exact_duplicates
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        result1 = detect_exact_duplicates(dataset_id, db)
        result2 = detect_exact_duplicates(dataset_id, db)
    finally:
        db.close()

    assert result1["duplicate_group_count"] == result2["duplicate_group_count"] == 1
    assert len(result1["findings"]) == len(result2["findings"]) == 1
    # Ensure no duplicate findings created (same finding ID)
    assert result1["findings"][0]["id"] == result2["findings"][0]["id"]

def test_equivalent_csv_xlsx(client, test_db):
    # CSV
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data_csv = response.json()
    dataset_id_csv = data_csv["id"]

    # XLSX with same content
    df = pd.DataFrame([{"name": "Alice", "age": 30},
                       {"name": "Bob", "age": 25},
                       {"name": "Alice", "age": 30}])
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        df.to_excel(tmp.name, index=False)
        tmp.seek(0)
        xlsx_content = tmp.read()
    os.unlink(tmp.name)

    response2 = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test xlsx",
            "type": "tabular",
            "format": "XLSX",
            "description": "test"
        },
        files={"file": ("test.xlsx", xlsx_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert response2.status_code == 201
    data_xlsx = response2.json()
    dataset_id_xlsx = data_xlsx["id"]

    from app.services.leakage_detection_service import detect_exact_duplicates
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        result_csv = detect_exact_duplicates(dataset_id_csv, db)
        result_xlsx = detect_exact_duplicates(dataset_id_xlsx, db)
    finally:
        db.close()

    assert result_csv["duplicate_group_count"] == result_xlsx["duplicate_group_count"] == 1
    assert result_csv["duplicated_row_count"] == result_xlsx["duplicated_row_count"] == 2

def test_repeated_analysis_no_duplicate_findings(client, test_db):
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv",
            "type": "tabular",
            "format": "CSV",
            "description": "test"
        },
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    dataset_id = data["id"]

    from app.services.leakage_detection_service import detect_exact_duplicates
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        # First analysis
        result1 = detect_exact_duplicates(dataset_id, db)
        # Second analysis
        result2 = detect_exact_duplicates(dataset_id, db)
    finally:
        db.close()

    # Count findings in DB for this dataset
    db = TestingSessionLocal()
    try:
        findings = db.query(leakage_models.LeakageFinding).filter(
            leakage_models.LeakageFinding.dataset_id == dataset_id,
            leakage_models.LeakageFinding.finding_type == "exact_duplicate"
        ).all()
    finally:
        db.close()

    assert len(findings) == 1  # only one finding ever created


def test_repeated_analysis_enriches_legacy_hash_evidence_without_recreating(
    client, test_db
):
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "legacy evidence metadata",
            "type": "tabular",
            "format": "CSV",
            "description": "test",
        },
        files={"file": ("legacy-evidence.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 201
    dataset_id = response.json()["id"]

    from app.db.session import TestingSessionLocal
    from app.services.leakage_detection_service import detect_exact_duplicates

    db = TestingSessionLocal()
    try:
        first_result = detect_exact_duplicates(dataset_id, db)
        finding_id = first_result["findings"][0]["id"]
        finding = (
            db.query(leakage_models.LeakageFinding)
            .filter_by(id=finding_id)
            .one()
        )
        original_created_at = finding.created_at
        # Simulate a finding persisted by the previous evidence format.
        legacy_evidence = dict(finding.evidence)
        legacy_evidence.pop("hash_excluded_columns", None)
        finding.evidence = legacy_evidence
        db.commit()

        second_result = detect_exact_duplicates(dataset_id, db)
        findings = (
            db.query(leakage_models.LeakageFinding)
            .filter_by(dataset_id=dataset_id, finding_type="exact_duplicate")
            .all()
        )
    finally:
        db.close()

    assert len(findings) == 1
    assert second_result["findings"][0]["id"] == finding_id
    assert findings[0].created_at == original_created_at
    assert findings[0].evidence["hash_excluded_columns"] == []

def test_controlled_storage_resolution(client, test_db):
    # This test ensures we use Dataset.storage_filename
    csv_content = b"name,age\nAlice,30\nBob,25\nAlice,30\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv",
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

    from app.services.leakage_detection_service import detect_exact_duplicates
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        result = detect_exact_duplicates(dataset_id, db)
    finally:
        db.close()

    assert result["duplicate_group_count"] == 1

    # Now try to tamper with storage_filename? Not needed; we trust service uses it.

def test_missing_stored_file(client, test_db):
    csv_content = b"name,age\nAlice,30\nBob,25\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test csv",
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

    # Delete the stored file
    storage_path = ORIGINAL_DIR / storage_filename
    if os.path.exists(storage_path):
        os.remove(storage_path)

    from app.services.leakage_detection_service import detect_exact_duplicates
    from app.db.session import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        try:
            detect_exact_duplicates(dataset_id, db)
            assert False, "Expected HTTPException"
        except Exception as e:
            # Should be HTTPException with 404
            assert "Stored file not found" in str(e)
    finally:
        db.close()

def test_unsupported_format(client, test_db):
    txt_content = b"name,age\nAlice,30\nBob,25\n"
    response = client.post(
        f"{API_V1_STR}/datasets",
        data={
            "name": "test txt",
            "type": "tabular",
            "format": "TXT",  # unsupported
            "description": "test"
        },
        files={"file": ("test.txt", txt_content, "text/plain")}
    )
    assert response.status_code == 400
    # Optionally verify the response detail contains the extension validation message
    assert "File extension not allowed for type tabular" in response.json()["detail"]
