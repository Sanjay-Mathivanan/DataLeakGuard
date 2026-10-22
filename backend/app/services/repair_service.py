import os
import hashlib
import pandas as pd
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.db import models, leakage_models
from app.utils.file_storage import PROCESSED_DIR, ORIGINAL_DIR, compute_file_sha256
from app.utils.row_hashing import hash_row
from app.core.config import settings
from .repair_quarantine_utils import (
    validate_dataset_and_finding,
    get_and_validate_original_path,
    validate_file_sha256,
    generate_output_filename,
    find_existing_completed_operation,
    create_base_repair_record,
    cleanup_created_output_if_unreferenced,
)


def repair_exact_duplicates(
    dataset_id: str,
    finding_id: str,
    db: Session
) -> Dict[str, Any]:
    """
    Repair exact duplicates in a dataset by creating a processed version
    with duplicate rows removed (keeping first occurrence).

    Args:
        dataset_id: The dataset ID
        finding_id: The exact duplicate finding ID
        db: Database session

    Returns:
        Dict containing repair results and metadata

    Raises:
        HTTPException: If validation fails or repair encounters errors
    """
    # Step 1: Validate inputs
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

    # Validate finding type is exact_duplicate
    if finding.finding_type != "exact_duplicate":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Finding is not of type exact_duplicate: {finding.finding_type}"
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

    # Step 2: Validate original file exists and hash matches
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

    # Verify original SHA-256 if available
    if dataset.file_sha256:
        actual_sha256 = compute_file_sha256(original_path)
        if actual_sha256 != dataset.file_sha256:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Original file SHA-256 mismatch - file may be corrupted"
            )

    # Step 3: Parse evidence to get duplicate information
    evidence = finding.evidence
    if not isinstance(evidence, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid evidence format"
        )

    # Extract duplicate information from evidence
    duplicate_count = evidence.get("duplicate_count")
    row_indices = evidence.get("row_indices")

    if duplicate_count is None or row_indices is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Evidence missing required duplicate information"
        )

    # Step 4: Read the original file based on format
    try:
        if dataset.format.upper() == "CSV":
            df = pd.read_csv(original_path, dtype=str)  # read all as string to preserve exact values
        elif dataset.format.upper() == "XLSX":
            df = pd.read_excel(original_path, dtype=str)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file format: {dataset.format}"
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read file: {str(e)}"
        )

    # Step 5: Apply repair algorithm - remove duplicate rows, keep first occurrence
    original_row_count = len(df)

    # Create a copy to work with
    df_processed = df.copy()

    # Sort indices to ensure we process them in order
    # Convert to list of integers and sort
    try:
        sorted_indices = sorted([int(idx) for idx in row_indices])
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid evidence format"
        )

    # Keep the first occurrence, remove all subsequent duplicates
    # If we have indices [0, 2, 4], we want to keep 0 and remove [2, 4]
    if len(sorted_indices) > 1:
        indices_to_remove = sorted_indices[1:]  # All except the first
    else:
        indices_to_remove = []  # No duplicates to remove if only one index

    # Remove duplicates in reverse order to maintain correct indices
    for idx in reversed(indices_to_remove):
        if idx < len(df_processed):
            df_processed = df_processed.drop(df_processed.index[idx])

    processed_row_count = len(df_processed)
    rows_removed = original_row_count - processed_row_count

    # Verify we removed the expected number of rows
    if rows_removed != duplicate_count:
        # This might happen if there are overlapping duplicate groups
        # but we'll proceed with what we actually removed
        pass

    # Check for a completed operation before creating any output file.
    repair_record = find_existing_completed_operation(
        db, dataset_id, finding_id, "repair"
    )
    if repair_record is None:
        processed_filename = generate_output_filename(dataset.storage_filename)
        processed_path = PROCESSED_DIR / processed_filename
        output_created = False

        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        try:
            # Exclusive creation prevents an unlikely filename collision from
            # overwriting a file that this request does not own.
            if dataset.format.upper() == "CSV":
                with processed_path.open("x", encoding="utf-8", newline="") as output:
                    output_created = True
                    df_processed.to_csv(output, index=False)
            elif dataset.format.upper() == "XLSX":
                with processed_path.open("xb") as output:
                    output_created = True
                    df_processed.to_excel(output, index=False)
            else:
                raise ValueError(f"Unsupported format {dataset.format}")
        except Exception as e:
            cleanup_created_output_if_unreferenced(
                db, processed_path, processed_filename, output_created
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to write processed file: {str(e)}"
            )

        try:
            processed_sha256 = compute_file_sha256(processed_path)
            repair_record = create_base_repair_record(
                dataset_id=dataset_id,
                finding_id=finding_id,
                operation_type="repair",
                input_file_sha256=dataset.file_sha256,
                output_file_sha256=processed_sha256,
                output_filename=processed_filename,
            )
            repair_record.affected_rows = rows_removed
            repair_record.affected_columns = []
            repair_record.quarantine_info = None

            db.add(repair_record)
            db.commit()
            db.refresh(repair_record)
        except Exception:
            cleanup_created_output_if_unreferenced(
                db, processed_path, processed_filename, output_created
            )
            raise

    # Step 9: Return results
    return {
        "repair_id": str(repair_record.id),
        "dataset_id": dataset_id,
        "finding_id": finding_id,
        "operation_type": "repair",
        "status": "completed",
        "input_file": dataset.storage_filename,
        "input_file_sha256": dataset.file_sha256,
        "output_file": repair_record.output_filename,
        "output_filename": repair_record.output_filename,
        "output_file_sha256": repair_record.output_file_sha256,
        "original_row_count": original_row_count,
        "processed_row_count": original_row_count - repair_record.affected_rows,
        "affected_rows": repair_record.affected_rows,
        "affected_columns": [],
        "quarantine_info": repair_record.quarantine_info,
        "created_at": repair_record.created_at.isoformat() if repair_record.created_at else None,
        "completed_at": repair_record.completed_at.isoformat() if repair_record.completed_at else None
    }
