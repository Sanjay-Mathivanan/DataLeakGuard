import os
import hashlib
import pandas as pd
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.db import models, leakage_models
from app.utils.file_storage import QUARANTINE_DIR, ORIGINAL_DIR, compute_file_sha256
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


def quarantine_finding(
    dataset_id: str,
    finding_id: str,
    db: Session
) -> Dict[str, Any]:
    """
    Quarantine specific rows identified by a leakage finding.
    Creates a quarantined version containing only the affected rows.

    Only safe for findings with explicit row_indices evidence:
    - exact_duplicate
    - entity_overlap
    - train_test_contamination

    For findings without deterministic row indices:
    - target_leakage
    - temporal_leakage

    Args:
        dataset_id: The dataset ID
        finding_id: The leakage finding ID
        db: Database session

    Returns:
        Dict containing quarantine results and metadata

    Raises:
        HTTPException: If validation fails or quarantine encounters errors
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

    # Get dataset
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id
    ).first()
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found"
        )

    # Validate finding type is supported for quarantine
    supported_types = {"exact_duplicate", "entity_overlap", "train_test_contamination"}
    if finding.finding_type not in supported_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Automatic quarantine is not safe for finding type '{finding.finding_type}' "
                   f"because the current finding evidence does not contain deterministic row indices. "
                   f"Supported types: {sorted(supported_types)}"
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
    original_path = get_and_validate_original_path(dataset)

    # Verify original SHA-256 if available
    if dataset.file_sha256:
        actual_sha256 = compute_file_sha256(original_path)
        if actual_sha256 != dataset.file_sha256:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Original file SHA-256 mismatch - file may be corrupted"
            )

    # Step 3: Parse evidence and extract row indices based on finding type
    evidence = finding.evidence
    if not isinstance(evidence, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid evidence format"
        )

    # Extract row indices based on finding type
    try:
        if finding.finding_type == "exact_duplicate":
            row_indices = _extract_exact_duplicate_indices(evidence)
        elif finding.finding_type == "entity_overlap":
            row_indices = _extract_entity_overlap_indices(evidence)
        elif finding.finding_type == "train_test_contamination":
            row_indices = _extract_train_test_contamination_indices(evidence)
        else:
            # This should never happen due to earlier validation, but included for completeness
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported finding type for quarantine: {finding.finding_type}"
            )
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid evidence structure for {finding.finding_type}: {str(e)}"
        )

    # Validate row indices
    try:
        validated_indices = _validate_row_indices(row_indices, dataset_id, db)
    except (TypeError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    if not validated_indices:
        # No valid rows to quarantine
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid row indices found in evidence"
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
                detail=f"Unsupported file format for quarantine: {dataset.format}"
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read file: {str(e)}"
        )

    # Validate that we have enough rows in the dataframe
    if len(df) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dataset contains no rows"
        )

    # Double-check that all validated indices are within bounds
    max_index = len(df) - 1
    if any(idx > max_index for idx in validated_indices):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Row index out of bounds. Dataset has {len(df)} rows (0-{max_index}), "
                   f"but evidence references index {max(validated_indices)}"
        )

    # Step 5: Extract the quarantined rows (preserving original order)
    # Sort indices to ensure deterministic output
    sorted_indices = sorted(validated_indices)
    df_quarantined = df.iloc[sorted_indices].copy()

    quarantined_row_count = len(df_quarantined)

    # Check for a completed operation before creating any output file.
    quarantine_record = find_existing_completed_operation(
        db, dataset_id, finding_id, "quarantine"
    )
    if quarantine_record is None:
        quarantine_filename = generate_output_filename(dataset.storage_filename)
        quarantine_path = QUARANTINE_DIR / quarantine_filename
        output_created = False

        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            # Exclusive creation prevents an unlikely filename collision from
            # overwriting a file that this request does not own.
            if dataset.format.upper() == "CSV":
                with quarantine_path.open("x", encoding="utf-8", newline="") as output:
                    output_created = True
                    df_quarantined.to_csv(output, index=False)
            elif dataset.format.upper() == "XLSX":
                with quarantine_path.open("xb") as output:
                    output_created = True
                    df_quarantined.to_excel(output, index=False)
            else:
                raise ValueError(f"Unsupported format {dataset.format}")
        except Exception as e:
            cleanup_created_output_if_unreferenced(
                db, quarantine_path, quarantine_filename, output_created
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to write quarantined file: {str(e)}"
            )

        try:
            quarantined_sha256 = compute_file_sha256(quarantine_path)
            quarantine_record = create_base_repair_record(
                dataset_id=dataset_id,
                finding_id=finding_id,
                operation_type="quarantine",
                input_file_sha256=dataset.file_sha256,
                output_file_sha256=quarantined_sha256,
                output_filename=quarantine_filename,
            )
            # Set quarantine-specific fields.
            quarantine_record.affected_rows = quarantined_row_count
            quarantine_record.affected_columns = list(df.columns)
            quarantine_record.quarantine_info = _create_quarantine_info(
                finding=finding,
                dataset=dataset,
                row_indices=sorted_indices,
                quarantined_row_count=quarantined_row_count,
                quarantine_filename=quarantine_filename
            )

            db.add(quarantine_record)
            db.commit()
            db.refresh(quarantine_record)
        except Exception:
            cleanup_created_output_if_unreferenced(
                db, quarantine_path, quarantine_filename, output_created
            )
            raise

    # Step 9: Return results
    return {
        "quarantine_id": str(quarantine_record.id),
        "dataset_id": dataset_id,
        "finding_id": finding_id,
        "operation_type": "quarantine",
        "status": "completed",
        "input_file": dataset.storage_filename,
        "input_file_sha256": dataset.file_sha256,
        "output_file": quarantine_record.output_filename,
        "output_filename": quarantine_record.output_filename,
        "output_file_sha256": quarantine_record.output_file_sha256,
        "original_row_count": len(df),
        "quarantined_row_count": quarantine_record.affected_rows,
        "affected_rows": quarantine_record.affected_rows,
        "affected_columns": quarantine_record.affected_columns,
        "quarantine_info": quarantine_record.quarantine_info,
        "created_at": quarantine_record.created_at.isoformat() if quarantine_record.created_at else None,
        "completed_at": quarantine_record.completed_at.isoformat() if quarantine_record.completed_at else None
    }


def _extract_exact_duplicate_indices(evidence: Dict[str, Any]) -> List[Any]:
    """Extract row indices from exact_duplicate evidence."""
    if "row_indices" not in evidence:
        raise KeyError("Missing 'row_indices' in evidence")

    row_indices = evidence["row_indices"]
    if not isinstance(row_indices, list):
        raise TypeError("'row_indices' must be a list")

    # Remove duplicates and return (preserve original types for validation)
    return list(dict.fromkeys(row_indices))


def _extract_entity_overlap_indices(evidence: Dict[str, Any]) -> List[Any]:
    """Extract row indices from entity_overlap evidence."""
    if "row_indices" not in evidence:
        raise KeyError("Missing 'row_indices' in evidence")

    row_indices_dict = evidence["row_indices"]
    if not isinstance(row_indices_dict, dict):
        raise TypeError("'row_indices' must be a dictionary")

    # Flatten all indices from the split-organized structure
    all_indices = []
    for split_key, indices_list in row_indices_dict.items():
        if not isinstance(indices_list, list):
            raise TypeError(f"Row indices for split '{split_key}' must be a list")
        all_indices.extend(indices_list)

    return all_indices


def _extract_train_test_contamination_indices(evidence: Dict[str, Any]) -> List[Any]:
    """Extract row indices from train_test_contamination evidence."""
    if "row_indices" not in evidence:
        raise KeyError("Missing 'row_indices' in evidence")

    row_indices_dict = evidence["row_indices"]
    if not isinstance(row_indices_dict, dict):
        raise TypeError("'row_indices' must be a dictionary")

    # Flatten all indices from the split-organized structure
    all_indices = []
    for split_key, indices_list in row_indices_dict.items():
        if not isinstance(indices_list, list):
            raise TypeError(f"Row indices for split '{split_key}' must be a list")
        all_indices.extend(indices_list)

    return all_indices


def _validate_row_indices(row_indices: List[Any], dataset_id: str, db: Session) -> List[int]:
    """Validate and clean row indices."""
    if not isinstance(row_indices, list):
        raise TypeError("Row indices must be a list")

    # Remove duplicates and sort
    unique_indices = list(set(row_indices))

    # Validate each index
    validated_indices = []
    for idx in unique_indices:
        if not isinstance(idx, int):
            raise TypeError(f"Row index must be integer, got {type(idx).__name__}: {idx}")
        if idx < 0:
            raise ValueError(f"Row index must be non-negative, got {idx}")
        validated_indices.append(idx)

    # Sort for deterministic output
    return sorted(validated_indices)


def _create_quarantine_info(
    finding: leakage_models.LeakageFinding,
    dataset: models.Dataset,
    row_indices: List[int],
    quarantined_row_count: int,
    quarantine_filename: str
) -> Dict[str, Any]:
    """Create quarantine info metadata."""
    return {
        "operation": "quarantine",
        "source_finding_id": str(finding.id),
        "finding_type": finding.finding_type,
        "row_indices": row_indices,
        "affected_row_count": quarantined_row_count,
        "source_file": dataset.storage_filename,
        "quarantine_file": quarantine_filename,
        "quarantine_timestamp": pd.Timestamp.utcnow().isoformat()
    }
