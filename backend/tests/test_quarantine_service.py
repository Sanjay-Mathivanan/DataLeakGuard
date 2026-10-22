import os
import hashlib
import tempfile
import pandas as pd
from fastapi.testclient import TestClient
from app.main import app
from app.db import models, leakage_models
from app.core.config import settings
from app.utils.file_storage import ORIGINAL_DIR, QUARANTINE_DIR, PROCESSED_DIR
import uuid

# Import the quarantine service directly for unit testing
from app.services.quarantine_service import (
    quarantine_finding,
    _extract_exact_duplicate_indices,
    _extract_entity_overlap_indices,
    _extract_train_test_contamination_indices,
    _validate_row_indices,
    _create_quarantine_info
)
from app.db.session import get_db


def test_extract_exact_duplicate_indices():
    """Test extraction of row indices from exact_duplicate evidence."""
    evidence = {
        "row_indices": [0, 2, 4, 2, 0]  # With duplicates
    }
    indices = _extract_exact_duplicate_indices(evidence)
    assert indices == [0, 2, 4]  # Should be deduplicated

def test_extract_exact_duplicate_indices_missing():
    """Test extraction fails gracefully when row_indices missing."""
    evidence = {"hash": "abc"}
    try:
        _extract_exact_duplicate_indices(evidence)
        assert False, "Should have raised KeyError"
    except KeyError as e:
        assert "row_indices" in str(e)

def test_extract_entity_overlap_indices():
    """Test extraction of row indices from entity_overlap evidence."""
    evidence = {
        "row_indices": {
            "hospital_A": [0, 2],
            "hospital_B": [1, 3]
        }
    }
    indices = _extract_entity_overlap_indices(evidence)
    assert set(indices) == {0, 1, 2, 3}  # All indices flattened

def test_extract_entity_overlap_indices_missing():
    """Test extraction fails gracefully when row_indices missing."""
    evidence = {"entity_column": "hospital"}
    try:
        _extract_entity_overlap_indices(evidence)
        assert False, "Should have raised KeyError"
    except KeyError as e:
        assert "row_indices" in str(e)

def test_extract_train_test_contamination_indices():
    """Test extraction of row indices from train_test_contamination evidence."""
    evidence = {
        "row_indices": {
            "train": [0, 3],
            "test": [1, 2, 4]
        }
    }
    indices = _extract_train_test_contamination_indices(evidence)
    assert set(indices) == {0, 1, 2, 3, 4}  # All indices flattened

def test_extract_train_test_contamination_indices_missing():
    """Test extraction fails gracefully when row_indices missing."""
    evidence = {"split_column": "split"}
    try:
        _extract_train_test_contamination_indices(evidence)
        assert False, "Should have raised KeyError"
    except KeyError as e:
        assert "row_indices" in str(e)

def test_validate_row_indices():
    """Test validation of row indices."""
    # Valid indices
    indices = [0, 2, 4, 2, 0]  # With duplicates, out of order
    validated = _validate_row_indices(indices, "test_dataset", None)  # db=None for now
    assert validated == [0, 2, 4]  # Should be deduplicated and sorted

def test_validate_row_indices_invalid():
    """Test validation fails for invalid indices."""
    # Negative index
    try:
        _validate_row_indices([-1, 0, 1], "test_dataset", None)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "non-negative" in str(e)

    # Non-integer
    try:
        _validate_row_indices([0, 1.5, 2], "test_dataset", None)
        assert False, "Should have raised TypeError"
    except TypeError as e:
        assert "integer" in str(e)

def test_validate_row_indices_empty():
    """Test validation of empty indices."""
    validated = _validate_row_indices([], "test_dataset", None)
    assert validated == []

def test_create_quarantine_info():
    """Test creation of quarantine info."""
    # Create mock objects
    class MockFinding:
        def __init__(self):
            self.id = uuid.uuid4()
            self.finding_type = "exact_duplicate"

    class MockDataset:
        def __init__(self):
            self.storage_filename = "test.csv"

    finding = MockFinding()
    dataset = MockDataset()
    row_indices = [0, 2, 4]
    quarantined_row_count = 3
    quarantine_filename = "test-quarantine.csv"

    info = _create_quarantine_info(
        finding=finding,
        dataset=dataset,
        row_indices=row_indices,
        quarantined_row_count=quarantined_row_count,
        quarantine_filename=quarantine_filename
    )

    assert info["operation"] == "quarantine"
    assert info["source_finding_id"] == str(finding.id)
    assert info["finding_type"] == finding.finding_type
    assert info["row_indices"] == [0, 2, 4]
    assert info["affected_row_count"] == 3
    assert info["source_file"] == "test.csv"
    assert info["quarantine_file"] == quarantine_filename
    assert "quarantine_timestamp" in info


def test_quarantine_service_can_get_session():
    """Test that we can get a database session."""
    # Get database session using the same pattern as the API
    db_gen = get_db()
    try:
        db = next(db_gen)
        # For now, we'll just test that we can get a session
        # A full test would require setting up data through the API
        # which is complex to do in a unit test without the test client
        assert db is not None
    finally:
        try:
            next(db_gen)  # Close the generator
        except StopIteration:
            pass