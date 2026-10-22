"""
Shared utilities for repair and quarantine services.
Contains genuinely identical low-level logic to eliminate duplication.
"""
import os
from uuid import uuid4
from pathlib import Path
from typing import Tuple, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.db import models, leakage_models
from app.utils.file_storage import ORIGINAL_DIR, compute_file_sha256


def validate_dataset_and_finding(
    db: Session,
    finding_id: str,
    dataset_id: str
) -> Tuple[leakage_models.LeakageFinding, models.Dataset]:
    """
    Validate that a finding exists and belongs to a dataset.

    Args:
        db: Database session
        finding_id: The finding ID to validate
        dataset_id: The dataset ID to validate against

    Returns:
        Tuple of (finding, dataset) objects

    Raises:
        HTTPException: 404 if finding or dataset not found
        HTTPException: 400 if finding doesn't belong to dataset
    """
    # Find the LeakageFinding
    finding = db.query(leakage_models.LeakageFinding).filter(
        leakage_models.LeakageFinding.id == finding_id
    ).first()
    if not finding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Finding not found"
        )

    # Validate finding belongs to dataset
    if finding.dataset_id != dataset_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Finding does not belong to the specified dataset"
        )

    # Get dataset
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id
    ).first()
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found"
        )

    return finding, dataset


def get_and_validate_original_path(dataset: models.Dataset) -> Path:
    """
    Get and validate the original file path for a dataset.

    Args:
        dataset: Dataset object containing storage_filename

    Returns:
        Path to the original file

    Raises:
        HTTPException: 400 if no storage filename
        HTTPException: 404 if original file not found
    """
    if not dataset.storage_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dataset has no storage filename"
        )

    # Build storage path
    original_path = ORIGINAL_DIR / dataset.storage_filename
    if not os.path.exists(original_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original file not found"
        )

    return original_path


def validate_file_sha256(dataset: models.Dataset, file_path: Path) -> None:
    """
    Validate that a file's SHA-256 matches the dataset's stored hash.

    Args:
        dataset: Dataset object potentially containing file_sha256
        file_path: Path to the file to validate

    Raises:
        HTTPException: 400 if SHA-256 mismatch and dataset has stored hash
    """

    if dataset.file_sha256:
        actual_sha256 = compute_file_sha256(file_path)
        if actual_sha256 != dataset.file_sha256:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Original file SHA-256 mismatch - file may be corrupted"
            )


def generate_output_filename(original_filename: str) -> str:
    """
    Generate a UUID-based output filename preserving the original extension.

    Args:
        original_filename: Original filename to extract extension from

    Returns:
        UUID-based filename with same extension as original
    """
    original_ext = original_filename.split(".")[-1].lower()
    return f"{uuid4()}.{original_ext}"


def find_existing_completed_operation(
    db: Session,
    dataset_id: str,
    finding_id: str,
    operation_type: str
) -> Optional[models.RepairRecord]:
    """
    Find an existing completed operation for idempotency checking.

    Args:
        db: Database session
        dataset_id: Dataset ID
        finding_id: Finding ID
        operation_type: Operation type ("repair" or "quarantine")

    Returns:
        Existing RepairRecord if found and completed, None otherwise
    """
    return db.query(models.RepairRecord).filter(
        models.RepairRecord.dataset_id == dataset_id,
        models.RepairRecord.finding_id == finding_id,
        models.RepairRecord.operation_type == operation_type,
        models.RepairRecord.status == "completed"
    ).first()


def cleanup_created_output_if_unreferenced(
    db: Session,
    output_path: Path,
    output_filename: str,
    created_by_request: bool,
) -> None:
    """
    Remove an output only when this request created it and no persisted
    operation record references its filename.

    If the database cannot be queried after a persistence failure, retain the
    file rather than risk deleting an output that may have been committed.
    """
    if not created_by_request:
        return

    try:
        db.rollback()
        reference = db.query(models.RepairRecord.id).filter(
            models.RepairRecord.output_filename == output_filename
        ).first()
    except Exception:
        return

    if reference is not None:
        return

    try:
        output_path.unlink()
    except (FileNotFoundError, OSError):
        # Cleanup is best-effort; retaining a file is safer than risking data loss.
        return


def create_base_repair_record(
    dataset_id: str,
    finding_id: str,
    operation_type: str,
    input_file_sha256: str,
    output_file_sha256: str,
    output_filename: str
) -> models.RepairRecord:
    """
    Create a base RepairRecord with common fields set.

    Args:
        dataset_id: Dataset ID
        finding_id: Finding ID
        operation_type: Operation type ("repair" or "quarantine")
        input_file_sha256: SHA-256 of input file
        output_file_sha256: SHA-256 of output file
        output_filename: Name of output file

    Returns:
        RepairRecord instance with common fields set (not yet saved to DB)
    """
    return models.RepairRecord(
        dataset_id=dataset_id,
        finding_id=finding_id,
        operation_type=operation_type,
        status="completed",
        input_file_sha256=input_file_sha256,
        output_file_sha256=output_file_sha256,
        output_filename=output_filename
    )
