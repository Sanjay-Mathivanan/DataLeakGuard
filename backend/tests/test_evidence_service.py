from app.schemas.evidence import EvidenceResponse
from app.services.evidence_service import create_evidence_response
from app.db import leakage_models, models
import uuid


def test_create_evidence_response_exact_duplicate():
    """Test EvidenceResponse creation from exact duplicate finding"""
    # Create mock objects
    finding_id = str(uuid.uuid4())
    dataset_id = str(uuid.uuid4())

    finding = leakage_models.LeakageFinding(
        id=finding_id,
        dataset_id=dataset_id,
        finding_type="exact_duplicate",
        severity="medium",
        status="open",
        description="Exact duplicate rows detected",
        evidence={
            "hash": "a1b2c3d4e5f6",
            "duplicate_count": 2,
            "row_indices": [0, 2]
        }
    )

    dataset = models.Dataset(
        id=dataset_id,
        name="test dataset",
        type="tabular",
        format="CSV",
        storage_filename="test.csv",
        file_sha256="abc123def456"
    )

    # Create EvidenceResponse
    response = create_evidence_response(finding, dataset)

    # Verify mapping
    assert isinstance(response, EvidenceResponse)
    assert response.finding_id == finding_id
    assert response.dataset_id == dataset_id
    assert response.finding_type == "exact_duplicate"
    assert response.severity == "medium"
    assert response.status == "open"
    assert response.source_file == "test.csv"
    assert response.source_file_sha256 == "abc123def456"
    assert response.detector_evidence == {
        "hash": "a1b2c3d4e5f6",
        "duplicate_count": 2,
        "row_indices": [0, 2]
    }


def test_create_evidence_response_entity_overlap():
    """Test EvidenceResponse creation from entity overlap finding"""
    # Create mock objects
    finding_id = str(uuid.uuid4())
    dataset_id = str(uuid.uuid4())

    finding = leakage_models.LeakageFinding(
        id=finding_id,
        dataset_id=dataset_id,
        finding_type="entity_overlap",
        severity="high",
        status="open",
        description="Entity 'P001' appears in multiple splits: test, train.",
        evidence={
            "entity_column": "patient_id",
            "split_column": "split",
            "entity_value": "P001",
            "splits": ["train", "test"],
            "row_indices": {
                "train": [0],
                "test": [2]
            }
        }
    )

    dataset = models.Dataset(
        id=dataset_id,
        name="test dataset",
        type="tabular",
        format="CSV",
        storage_filename=None,  # Could be None for some datasets
        file_sha256=None       # Could be None for some datasets
    )

    # Create EvidenceResponse
    response = create_evidence_response(finding, dataset)

    # Verify mapping
    assert isinstance(response, EvidenceResponse)
    assert response.finding_id == finding_id
    assert response.dataset_id == dataset_id
    assert response.finding_type == "entity_overlap"
    assert response.severity == "high"
    assert response.status == "open"
    assert response.source_file is None
    assert response.source_file_sha256 is None
    assert response.detector_evidence == {
        "entity_column": "patient_id",
        "split_column": "split",
        "entity_value": "P001",
        "splits": ["train", "test"],
        "row_indices": {
            "train": [0],
            "test": [2]
        }
    }


def test_create_evidence_response_target_leakage_exact_duplicate():
    """Test EvidenceResponse creation from target leakage exact duplicate finding"""
    # Create mock objects
    finding_id = str(uuid.uuid4())
    dataset_id = str(uuid.uuid4())

    finding = leakage_models.LeakageFinding(
        id=finding_id,
        dataset_id=dataset_id,
        finding_type="target_leakage",
        severity="high",
        status="open",
        description="Feature column 'leaked_feature' exactly duplicates the target column 'target'.",
        evidence={
            "target_column": "target",
            "feature_column": "leaked_feature",
            "detection": "exact_target_duplicate",
            "matching_rows": 4,
            "total_valid_rows": 4
        }
    )

    dataset = models.Dataset(
        id=dataset_id,
        name="test dataset",
        type="tabular",
        format="XLSX",
        storage_filename="data.xlsx",
        file_sha256="xyz789abc123"
    )

    # Create EvidenceResponse
    response = create_evidence_response(finding, dataset)

    # Verify mapping
    assert isinstance(response, EvidenceResponse)
    assert response.finding_id == finding_id
    assert response.dataset_id == dataset_id
    assert response.finding_type == "target_leakage"
    assert response.severity == "high"
    assert response.status == "open"
    assert response.source_file == "data.xlsx"
    assert response.source_file_sha256 == "xyz789abc123"
    assert response.detector_evidence == {
        "target_column": "target",
        "feature_column": "leaked_feature",
        "detection": "exact_target_duplicate",
        "matching_rows": 4,
        "total_valid_rows": 4
    }


def test_create_evidence_response_target_leakage_deterministic_mapping():
    """Test EvidenceResponse creation from target leakage deterministic mapping finding"""
    # Create mock objects
    finding_id = str(uuid.uuid4())
    dataset_id = str(uuid.uuid4())

    finding = leakage_models.LeakageFinding(
        id=finding_id,
        dataset_id=dataset_id,
        finding_type="target_leakage",
        severity="high",
        status="open",
        description="Feature column 'feature' deterministically maps each feature value to a single target value.",
        evidence={
            "target_column": "target",
            "feature_column": "feature",
            "detection": "deterministic_feature_target_mapping",
            "unique_feature_values": 2,
            "unique_target_values": 2,
            "mapping": {"A": "0", "B": "1"}
        }
    )

    dataset = models.Dataset(
        id=dataset_id,
        name="test dataset",
        type="tabular",
        format="CSV",
        storage_filename="data.csv",
        file_sha256="def456ghi789"
    )

    # Create EvidenceResponse
    response = create_evidence_response(finding, dataset)

    # Verify mapping
    assert isinstance(response, EvidenceResponse)
    assert response.finding_id == finding_id
    assert response.dataset_id == dataset_id
    assert response.finding_type == "target_leakage"
    assert response.severity == "high"
    assert response.status == "open"
    assert response.source_file == "data.csv"
    assert response.source_file_sha256 == "def456ghi789"
    assert response.detector_evidence == {
        "target_column": "target",
        "feature_column": "feature",
        "detection": "deterministic_feature_target_mapping",
        "unique_feature_values": 2,
        "unique_target_values": 2,
        "mapping": {"A": "0", "B": "1"}
    }


def test_create_evidence_response_temporal_leakage():
    """Test EvidenceResponse creation from temporal leakage finding"""
    # Create mock objects
    finding_id = str(uuid.uuid4())
    dataset_id = str(uuid.uuid4())

    finding = leakage_models.LeakageFinding(
        id=finding_id,
        dataset_id=dataset_id,
        finding_type="temporal_leakage",
        severity="high",
        status="open",
        description="Temporal overlap detected between train and test periods: the test period begins before the train period ends.",
        evidence={
            "time_column": "event_date",
            "split_column": "split",
            "detection": "temporal_overlap",
            "splits": {
                "train": {
                    "min_time": "2025-01-01T00:00:00",
                    "max_time": "2025-01-20T00:00:00",
                    "valid_rows": 3
                },
                "test": {
                    "min_time": "2025-01-15T00:00:00",
                    "max_time": "2025-01-30T00:00:00",
                    "valid_rows": 2
                }
            },
            "invalid_timestamp_rows": 0
        }
    )

    dataset = models.Dataset(
        id=dataset_id,
        name="test dataset",
        type="tabular",
        format="CSV",
        storage_filename=None,
        file_sha256=None
    )

    # Create EvidenceResponse
    response = create_evidence_response(finding, dataset)

    # Verify mapping
    assert isinstance(response, EvidenceResponse)
    assert response.finding_id == finding_id
    assert response.dataset_id == dataset_id
    assert response.finding_type == "temporal_leakage"
    assert response.severity == "high"
    assert response.status == "open"
    assert response.source_file is None
    assert response.source_file_sha256 is None
    assert response.detector_evidence == {
        "time_column": "event_date",
        "split_column": "split",
        "detection": "temporal_overlap",
        "splits": {
            "train": {
                "min_time": "2025-01-01T00:00:00",
                "max_time": "2025-01-20T00:00:00",
                "valid_rows": 3
            },
            "test": {
                "min_time": "2025-01-15T00:00:00",
                "max_time": "2025-01-30T00:00:00",
                "valid_rows": 2
            }
        },
        "invalid_timestamp_rows": 0
    }


def test_create_evidence_response_temporal_leakage_boundary():
    """Test EvidenceResponse creation from temporal leakage boundary overlap finding"""
    # Create mock objects
    finding_id = str(uuid.uuid4())
    dataset_id = str(uuid.uuid4())

    finding = leakage_models.LeakageFinding(
        id=finding_id,
        dataset_id=dataset_id,
        finding_type="temporal_leakage",
        severity="high",
        status="open",
        description="Temporal boundary overlap detected between train and test periods.",
        evidence={
            "time_column": "event_date",
            "split_column": "split",
            "detection": "temporal_overlap",
            "splits": {
                "train": {
                    "min_time": "2025-01-01T00:00:00",
                    "max_time": "2025-01-10T00:00:00",
                    "valid_rows": 2
                },
                "test": {
                    "min_time": "2025-01-10T00:00:00",
                    "max_time": "2025-01-20T00:00:00",
                    "valid_rows": 2
                }
            },
            "invalid_timestamp_rows": 0,
            "boundary_overlap": True
        }
    )

    dataset = models.Dataset(
        id=dataset_id,
        name="test dataset",
        type="tabular",
        format="XLSX",
        storage_filename="events.xlsx",
        file_sha256="xyz987abc654"
    )

    # Create EvidenceResponse
    response = create_evidence_response(finding, dataset)

    # Verify mapping
    assert isinstance(response, EvidenceResponse)
    assert response.finding_id == finding_id
    assert response.dataset_id == dataset_id
    assert response.finding_type == "temporal_leakage"
    assert response.severity == "high"
    assert response.status == "open"
    assert response.source_file == "events.xlsx"
    assert response.source_file_sha256 == "xyz987abc654"
    assert response.detector_evidence == {
        "time_column": "event_date",
        "split_column": "split",
        "detection": "temporal_overlap",
        "splits": {
            "train": {
                "min_time": "2025-01-01T00:00:00",
                "max_time": "2025-01-10T00:00:00",
                "valid_rows": 2
            },
            "test": {
                "min_time": "2025-01-10T00:00:00",
                "max_time": "2025-01-20T00:00:00",
                "valid_rows": 2
            }
        },
        "invalid_timestamp_rows": 0,
        "boundary_overlap": True
    }


def test_create_evidence_response_train_test_contamination():
    """Test EvidenceResponse creation from train/test contamination finding"""
    # Create mock objects
    finding_id = str(uuid.uuid4())
    dataset_id = str(uuid.uuid4())

    finding = leakage_models.LeakageFinding(
        id=finding_id,
        dataset_id=dataset_id,
        finding_type="train_test_contamination",
        severity="high",
        status="open",
        description="Exact train/test contamination detected: the same canonical sample appears in train and test splits.",
        evidence={
            "split_column": "split",
            "detection": "exact_row_hash_overlap",
            "row_hash": "a1b2c3d4e5f6g7h8i9j0",
            "splits": ["train", "test"],
            "row_indices": {
                "train": [0, 3],
                "test": [0, 3]
            },
            "column_count": 3
        }
    )

    dataset = models.Dataset(
        id=dataset_id,
        name="test dataset",
        type="tabular",
        format="CSV",
        storage_filename="splits.csv",
        file_sha256="abc123xyz789"
    )

    # Create EvidenceResponse
    response = create_evidence_response(finding, dataset)

    # Verify mapping
    assert isinstance(response, EvidenceResponse)
    assert response.finding_id == finding_id
    assert response.dataset_id == dataset_id
    assert response.finding_type == "train_test_contamination"
    assert response.severity == "high"
    assert response.status == "open"
    assert response.source_file == "splits.csv"
    assert response.source_file_sha256 == "abc123xyz789"
    assert response.detector_evidence == {
        "split_column": "split",
        "detection": "exact_row_hash_overlap",
        "row_hash": "a1b2c3d4e5f6g7h8i9j0",
        "splits": ["train", "test"],
        "row_indices": {
            "train": [0, 3],
            "test": [0, 3]
        },
        "column_count": 3
    }


def test_create_evidence_response_preserves_input_objects():
    """Test that the service does not modify the input finding or dataset objects"""
    # Create mock objects
    finding_id = str(uuid.uuid4())
    dataset_id = str(uuid.uuid4())

    original_finding_id = finding_id
    original_dataset_id = dataset_id
    original_finding_type = "exact_duplicate"
    original_severity = "medium"
    original_status = "open"
    original_description = "Exact duplicate rows detected"
    original_evidence = {
        "hash": "a1b2c3d4e5f6",
        "duplicate_count": 2,
        "row_indices": [0, 2]
    }

    original_storage_filename = "test.csv"
    original_file_sha256 = "abc123def456"

    finding = leakage_models.LeakageFinding(
        id=original_finding_id,
        dataset_id=original_dataset_id,
        finding_type=original_finding_type,
        severity=original_severity,
        status=original_status,
        description=original_description,
        evidence=original_evidence
    )

    dataset = models.Dataset(
        id=original_dataset_id,
        name="test dataset",
        type="tabular",
        format="CSV",
        storage_filename=original_storage_filename,
        file_sha256=original_file_sha256
    )

    # Store original values for comparison
    finding_id_before = finding.id
    finding_dataset_id_before = finding.dataset_id
    finding_finding_type_before = finding.finding_type
    finding_severity_before = finding.severity
    finding_status_before = finding.status
    finding_description_before = finding.description
    finding_evidence_before = finding.evidence.copy()

    dataset_id_before = dataset.id
    dataset_storage_filename_before = dataset.storage_filename
    dataset_file_sha256_before = dataset.file_sha256

    # Create EvidenceResponse
    response = create_evidence_response(finding, dataset)

    # Verify input objects were not modified
    assert finding.id == finding_id_before
    assert finding.dataset_id == finding_dataset_id_before
    assert finding.finding_type == finding_finding_type_before
    assert finding.severity == finding_severity_before
    assert finding.status == finding_status_before
    assert finding.description == finding_description_before
    assert finding.evidence == finding_evidence_before

    assert dataset.id == dataset_id_before
    assert dataset.storage_filename == dataset_storage_filename_before
    assert dataset.file_sha256 == dataset_file_sha256_before

    # Verify response is correct
    assert response.finding_id == original_finding_id
    assert response.dataset_id == original_dataset_id
    assert response.finding_type == original_finding_type
    assert response.severity == original_severity
    assert response.status == original_status
    assert response.source_file == original_storage_filename
    assert response.source_file_sha256 == original_file_sha256
    assert response.detector_evidence == original_evidence


def test_create_evidence_response_deterministic():
    """Test that the service produces deterministic output"""
    # Create mock objects
    finding_id = str(uuid.uuid4())
    dataset_id = str(uuid.uuid4())

    finding = leakage_models.LeakageFinding(
        id=finding_id,
        dataset_id=dataset_id,
        finding_type="exact_duplicate",
        severity="medium",
        status="open",
        description="Exact duplicate rows detected",
        evidence={
            "hash": "a1b2c3d4e5f6",
            "duplicate_count": 2,
            "row_indices": [0, 2]
        }
    )

    dataset = models.Dataset(
        id=dataset_id,
        name="test dataset",
        type="tabular",
        format="CSV",
        storage_filename="test.csv",
        file_sha256="abc123def456"
    )

    # Call service multiple times
    response1 = create_evidence_response(finding, dataset)
    response2 = create_evidence_response(finding, dataset)
    response3 = create_evidence_response(finding, dataset)

    # Verify all responses are identical
    assert response1 == response2 == response3

    # Verify specific fields
    assert response1.finding_id == finding_id
    assert response1.dataset_id == dataset_id
    assert response1.finding_type == "exact_duplicate"
    assert response1.severity == "medium"
    assert response1.status == "open"
    assert response1.source_file == "test.csv"
    assert response1.source_file_sha256 == "abc123def456"
    assert response1.detector_evidence == {
        "hash": "a1b2c3d4e5f6",
        "duplicate_count": 2,
        "row_indices": [0, 2]
    }