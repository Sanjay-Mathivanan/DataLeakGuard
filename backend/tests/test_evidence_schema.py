from app.schemas.evidence import EvidenceResponse


def test_evidence_response_exact_duplicate():
    """Test EvidenceResponse with exact duplicate evidence"""
    evidence_data = {
        "finding_id": "test-finding-id-1",
        "dataset_id": "test-dataset-id",
        "finding_type": "exact_duplicate",
        "severity": "medium",
        "status": "open",
        "source_file": "test.csv",
        "source_file_sha256": "abc123def456",
        "detector_evidence": {
            "hash": "a1b2c3d4e5f6",
            "duplicate_count": 2,
            "row_indices": [0, 2]
        }
    }

    response = EvidenceResponse(**evidence_data)

    assert response.finding_id == "test-finding-id-1"
    assert response.dataset_id == "test-dataset-id"
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


def test_evidence_response_entity_overlap():
    """Test EvidenceResponse with entity overlap evidence"""
    evidence_data = {
        "finding_id": "test-finding-id-2",
        "dataset_id": "test-dataset-id",
        "finding_type": "entity_overlap",
        "severity": "high",
        "status": "open",
        "source_file": None,
        "source_file_sha256": None,
        "detector_evidence": {
            "entity_column": "patient_id",
            "split_column": "split",
            "entity_value": "P001",
            "splits": ["train", "test"],
            "row_indices": {
                "train": [0],
                "test": [2]
            }
        }
    }

    response = EvidenceResponse(**evidence_data)

    assert response.finding_id == "test-finding-id-2"
    assert response.dataset_id == "test-dataset-id"
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


def test_evidence_response_target_leakage_exact_duplicate():
    """Test EvidenceResponse with target leakage exact duplicate evidence"""
    evidence_data = {
        "finding_id": "test-finding-id-3",
        "dataset_id": "test-dataset-id",
        "finding_type": "target_leakage",
        "severity": "high",
        "status": "open",
        "source_file": "data.xlsx",
        "source_file_sha256": "xyz789abc123",
        "detector_evidence": {
            "target_column": "target",
            "feature_column": "leaked_feature",
            "detection": "exact_target_duplicate",
            "matching_rows": 4,
            "total_valid_rows": 4
        }
    }

    response = EvidenceResponse(**evidence_data)

    assert response.finding_id == "test-finding-id-3"
    assert response.dataset_id == "test-dataset-id"
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


def test_evidence_response_target_leakage_deterministic_mapping():
    """Test EvidenceResponse with target leakage deterministic mapping evidence"""
    evidence_data = {
        "finding_id": "test-finding-id-4",
        "dataset_id": "test-dataset-id",
        "finding_type": "target_leakage",
        "severity": "high",
        "status": "open",
        "source_file": "data.csv",
        "source_file_sha256": "def456ghi789",
        "detector_evidence": {
            "target_column": "target",
            "feature_column": "feature",
            "detection": "deterministic_feature_target_mapping",
            "unique_feature_values": 2,
            "unique_target_values": 2,
            "mapping": {"A": "0", "B": "1"}
        }
    }

    response = EvidenceResponse(**evidence_data)

    assert response.finding_id == "test-finding-id-4"
    assert response.dataset_id == "test-dataset-id"
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


def test_evidence_response_temporal_leakage():
    """Test EvidenceResponse with temporal leakage evidence"""
    evidence_data = {
        "finding_id": "test-finding-id-5",
        "dataset_id": "test-dataset-id",
        "finding_type": "temporal_leakage",
        "severity": "high",
        "status": "open",
        "source_file": None,
        "source_file_sha256": None,
        "detector_evidence": {
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
    }

    response = EvidenceResponse(**evidence_data)

    assert response.finding_id == "test-finding-id-5"
    assert response.dataset_id == "test-dataset-id"
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


def test_evidence_response_temporal_leakage_boundary():
    """Test EvidenceResponse with temporal leakage boundary overlap evidence"""
    evidence_data = {
        "finding_id": "test-finding-id-6",
        "dataset_id": "test-dataset-id",
        "finding_type": "temporal_leakage",
        "severity": "high",
        "status": "open",
        "source_file": "events.xlsx",
        "source_file_sha256": "xyz987abc654",
        "detector_evidence": {
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
    }

    response = EvidenceResponse(**evidence_data)

    assert response.finding_id == "test-finding-id-6"
    assert response.dataset_id == "test-dataset-id"
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


def test_evidence_response_train_test_contamination():
    """Test EvidenceResponse with train/test contamination evidence"""
    evidence_data = {
        "finding_id": "test-finding-id-7",
        "dataset_id": "test-dataset-id",
        "finding_type": "train_test_contamination",
        "severity": "high",
        "status": "open",
        "source_file": "splits.csv",
        "source_file_sha256": "abc123xyz789",
        "detector_evidence": {
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
    }

    response = EvidenceResponse(**evidence_data)

    assert response.finding_id == "test-finding-id-7"
    assert response.dataset_id == "test-dataset-id"
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


def test_evidence_response_serialization():
    """Test EvidenceResponse serialization to dict"""
    evidence_data = {
        "finding_id": "test-finding-id-8",
        "dataset_id": "test-dataset-id",
        "finding_type": "exact_duplicate",
        "severity": "medium",
        "status": "open",
        "source_file": "test.csv",
        "source_file_sha256": "abc123def456",
        "detector_evidence": {
            "hash": "a1b2c3d4e5f6",
            "duplicate_count": 2,
            "row_indices": [0, 2]
        }
    }

    response = EvidenceResponse(**evidence_data)
    serialized = response.model_dump()

    assert serialized["finding_id"] == "test-finding-id-8"
    assert serialized["dataset_id"] == "test-dataset-id"
    assert serialized["finding_type"] == "exact_duplicate"
    assert serialized["severity"] == "medium"
    assert serialized["status"] == "open"
    assert serialized["source_file"] == "test.csv"
    assert serialized["source_file_sha256"] == "abc123def456"
    assert serialized["detector_evidence"] == {
        "hash": "a1b2c3d4e5f6",
        "duplicate_count": 2,
        "row_indices": [0, 2]
    }


def test_evidence_response_from_orm():
    """Test EvidenceResponse creation from ORM-like object"""
    # Simulate an ORM object with attributes
    class MockFinding:
        def __init__(self):
            self.id = "test-finding-id-9"
            self.dataset_id = "test-dataset-id"
            self.finding_type = "entity_overlap"
            self.severity = "high"
            self.status = "open"
            # Note: EvidenceResponse doesn't have source_file/source_file_sha256 fields
            # These would need to be populated separately in practice

    class MockEvidence:
        def __init__(self):
            self.entity_column = "patient_id"
            self.split_column = "split"
            self.entity_value = "P001"
            self.splits = ["train", "test"]
            self.row_indices = {
                "train": [0],
                "test": [2]
            }

    mock_finding = MockFinding()
    mock_evidence = MockEvidence()

    # Create EvidenceResponse manually (in practice, this would come from a service)
    evidence_data = {
        "finding_id": mock_finding.id,
        "dataset_id": mock_finding.dataset_id,
        "finding_type": mock_finding.finding_type,
        "severity": mock_finding.severity,
        "status": mock_finding.status,
        "source_file": "data.csv",  # Would come from Dataset.storage_filename
        "source_file_sha256": "def456abc123",  # Would come from Dataset.file_sha256
        "detector_evidence": {
            "entity_column": mock_evidence.entity_column,
            "split_column": mock_evidence.split_column,
            "entity_value": mock_evidence.entity_value,
            "splits": mock_evidence.splits,
            "row_indices": mock_evidence.row_indices
        }
    }

    response = EvidenceResponse(**evidence_data)

    assert response.finding_id == "test-finding-id-9"
    assert response.dataset_id == "test-dataset-id"
    assert response.finding_type == "entity_overlap"
    assert response.severity == "high"
    assert response.status == "open"
    assert response.source_file == "data.csv"
    assert response.source_file_sha256 == "def456abc123"
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