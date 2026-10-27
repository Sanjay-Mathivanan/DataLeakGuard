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


def generate_combined_exact_duplicate_repair(
    dataset_id: str,
    selected_finding_ids: List[str],
    db: Session,
) -> Dict[str, Any]:
    """Create one cleaned copy from explicitly selected, current duplicate findings."""
    if not isinstance(selected_finding_ids, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="selected_finding_ids must be a non-empty list",
        )
    if any(not isinstance(value, str) or not value.strip() for value in selected_finding_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="selected_finding_ids must contain non-empty finding IDs",
        )
    if not selected_finding_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select at least one finding for combined repair",
        )

    requested_ids = sorted(set(selected_finding_ids))
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id
    ).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if not dataset.storage_filename:
        raise HTTPException(status_code=400, detail="Dataset has no storage filename")
    if dataset.format.upper() not in {"CSV", "XLSX"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {dataset.format}",
        )

    original_path = get_and_validate_original_path(dataset)
    try:
        input_sha256 = compute_file_sha256(original_path)
    except OSError:
        raise HTTPException(status_code=404, detail="Original file not found")
    if dataset.file_sha256 and input_sha256 != dataset.file_sha256:
        raise HTTPException(
            status_code=400,
            detail="Original file SHA-256 mismatch - file may be corrupted",
        )

    # Return an equivalent completed operation before writing another output.
    completed_operations = db.query(models.RepairRecord).filter(
        models.RepairRecord.dataset_id == dataset_id,
        models.RepairRecord.operation_type == "combined_repair",
        models.RepairRecord.status == "completed",
    ).all()
    for existing in completed_operations:
        metadata = existing.operation_metadata
        if (
            existing.input_file_sha256 == input_sha256
            and isinstance(metadata, dict)
            and metadata.get("selected_finding_ids") == requested_ids
        ):
            return _combined_repair_response(existing, dataset.storage_filename)

    try:
        if dataset.format.upper() == "CSV":
            original_frame = pd.read_csv(original_path, dtype=str)
        else:
            original_frame = pd.read_excel(original_path, dtype=str)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to read original file: {exc}",
        )

    findings = db.query(leakage_models.LeakageFinding).filter(
        leakage_models.LeakageFinding.id.in_(requested_ids)
    ).all()
    findings_by_id = {finding.id: finding for finding in findings}
    if len(findings_by_id) != len(requested_ids):
        raise HTTPException(status_code=404, detail="One or more findings were not found")
    if any(finding.dataset_id != dataset_id for finding in findings):
        raise HTTPException(
            status_code=400,
            detail="Every selected finding must belong to the specified dataset",
        )
    if any(finding.finding_type != "exact_duplicate" for finding in findings):
        raise HTTPException(
            status_code=400,
            detail="Combined repair supports exact_duplicate findings only",
        )

    previously_applied_ids = set()
    individual_repairs = db.query(models.RepairRecord.finding_id).filter(
        models.RepairRecord.dataset_id == dataset_id,
        models.RepairRecord.finding_id.in_(requested_ids),
        models.RepairRecord.operation_type == "repair",
        models.RepairRecord.status == "completed",
    ).all()
    previously_applied_ids.update(
        finding_id for (finding_id,) in individual_repairs if finding_id
    )
    for operation in completed_operations:
        metadata = operation.operation_metadata
        if isinstance(metadata, dict):
            applied_ids = metadata.get("applied_finding_ids")
            if isinstance(applied_ids, list):
                previously_applied_ids.update(
                    value for value in applied_ids if isinstance(value, str)
                )

    # Exact-duplicate evidence records the hash exclusions used by its own
    # analysis. The dataset's latest analysis configuration is not sufficient:
    # a finding can remain open after later analysis uses different settings.
    # For legacy findings without this metadata, use the only historical hint
    # available in the profile and retain strict hash validation.
    profile = dataset.profile if isinstance(dataset.profile, dict) else {}
    analysis_columns = profile.get("analysis_columns")
    split_column = (
        analysis_columns.get("split_column")
        if isinstance(analysis_columns, dict)
        else profile.get("split_column")
    )
    legacy_exclusions = (
        [
            column
            for column in ("id", split_column)
            if isinstance(column, str) and column in original_frame.columns
        ]
        if isinstance(split_column, str) and split_column in original_frame.columns
        else []
    )
    hash_groups_by_exclusions: Dict[
        Tuple[str, ...], Tuple[List[str], Dict[str, List[int]]]
    ] = {}

    def hash_groups(excluded_columns: List[str]):
        exclusion_key = tuple(excluded_columns)
        if exclusion_key not in hash_groups_by_exclusions:
            comparison_frame = original_frame.drop(columns=list(exclusion_key))
            frame_hashes = [
                hash_row(comparison_frame.iloc[index])
                for index in range(len(comparison_frame))
            ]
            rows_by_hash: Dict[str, List[int]] = {}
            for index, row_hash in enumerate(frame_hashes):
                rows_by_hash.setdefault(row_hash, []).append(index)
            hash_groups_by_exclusions[exclusion_key] = (
                frame_hashes,
                rows_by_hash,
            )
        return hash_groups_by_exclusions[exclusion_key]

    applied_ids: List[str] = []
    skipped_findings: List[Dict[str, str]] = []
    rows_to_remove = set()
    for finding_id in requested_ids:
        finding = findings_by_id[finding_id]
        if not isinstance(finding.status, str) or finding.status.strip().lower() != "open":
            skipped_findings.append({
                "finding_id": finding_id,
                "reason": f"Finding status is '{finding.status}', not 'open'.",
            })
            continue
        if finding_id in previously_applied_ids:
            skipped_findings.append({
                "finding_id": finding_id,
                "reason": "Finding was already included in a completed repair.",
            })
            continue

        evidence = finding.evidence
        row_indices = evidence.get("row_indices") if isinstance(evidence, dict) else None
        evidence_hash = evidence.get("hash") if isinstance(evidence, dict) else None
        duplicate_count = evidence.get("duplicate_count") if isinstance(evidence, dict) else None
        valid_indices = (
            isinstance(row_indices, list)
            and len(row_indices) >= 2
            and all(type(index) is int and 0 <= index < len(original_frame) for index in row_indices)
            and len(set(row_indices)) == len(row_indices)
        )
        if (
            not valid_indices
            or type(duplicate_count) is not int
            or duplicate_count != len(row_indices)
            or not isinstance(evidence_hash, str)
        ):
            skipped_findings.append({
                "finding_id": finding_id,
                "reason": "Duplicate evidence is missing, malformed, or no longer valid.",
            })
            continue

        evidence_exclusions = evidence.get("hash_excluded_columns")
        if evidence_exclusions is None:
            excluded_columns = legacy_exclusions
        elif (
            isinstance(evidence_exclusions, list)
            and all(
                isinstance(column, str) and column in original_frame.columns
                for column in evidence_exclusions
            )
            and len(set(evidence_exclusions)) == len(evidence_exclusions)
        ):
            excluded_columns = evidence_exclusions
        else:
            skipped_findings.append({
                "finding_id": finding_id,
                "reason": "Duplicate evidence contains invalid hash-exclusion metadata.",
            })
            continue

        frame_hashes, rows_by_hash = hash_groups(excluded_columns)
        actual_group_indices = rows_by_hash.get(evidence_hash, [])
        if (
            len(actual_group_indices) < 2
            or sorted(row_indices) != actual_group_indices
            or any(frame_hashes[index] != evidence_hash for index in row_indices)
        ):
            skipped_findings.append({
                "finding_id": finding_id,
                "reason": "Duplicate evidence no longer matches the original dataset rows.",
            })
            continue

        applied_ids.append(finding_id)
        rows_to_remove.update(actual_group_indices[1:])

    if not applied_ids or not rows_to_remove:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "No selected findings remain eligible for combined repair",
                "skipped_findings": skipped_findings,
            },
        )

    original_row_count = len(original_frame)
    cleaned_frame = original_frame.drop(index=sorted(rows_to_remove))
    final_row_count = len(cleaned_frame)
    duplicate_rows_removed = len(rows_to_remove)
    metadata = {
        "selected_finding_ids": requested_ids,
        "applied_finding_ids": applied_ids,
        "skipped_findings": skipped_findings,
        "original_row_count": original_row_count,
        "final_row_count": final_row_count,
        "duplicate_rows_removed": duplicate_rows_removed,
    }

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    processed_path = None
    processed_filename = None
    output_created = False
    try:
        for _ in range(5):
            processed_filename = generate_output_filename(dataset.storage_filename)
            processed_path = PROCESSED_DIR / processed_filename
            try:
                if dataset.format.upper() == "CSV":
                    output = processed_path.open("x", encoding="utf-8", newline="")
                else:
                    output = processed_path.open("xb")
                output_created = True
                break
            except FileExistsError:
                continue
        else:
            raise FileExistsError("Unable to allocate a unique processed filename")

        with output:
            cleaned_frame.to_csv(output, index=False) if dataset.format.upper() == "CSV" else cleaned_frame.to_excel(output, index=False)
        output_sha256 = compute_file_sha256(processed_path)

        record = models.RepairRecord(
            dataset_id=dataset_id,
            finding_id=None,
            operation_type="combined_repair",
            status="completed",
            input_file_sha256=input_sha256,
            output_file_sha256=output_sha256,
            output_filename=processed_filename,
            affected_rows=duplicate_rows_removed,
            affected_columns=[],
            quarantine_info=None,
            operation_metadata=metadata,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
    except Exception as exc:
        if processed_path is not None and processed_filename is not None:
            cleanup_created_output_if_unreferenced(
                db, processed_path, processed_filename, output_created
            )
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate or persist the combined cleaned dataset",
        )

    return _combined_repair_response(record, dataset.storage_filename)


def _combined_repair_response(
    record: models.RepairRecord,
    input_filename: str,
) -> Dict[str, Any]:
    metadata = record.operation_metadata or {}
    return {
        "id": str(record.id),
        "dataset_id": record.dataset_id,
        "finding_id": None,
        "operation_type": record.operation_type,
        "status": record.status,
        "input_file": input_filename,
        "input_file_sha256": record.input_file_sha256,
        "output_file": record.output_filename,
        "output_filename": record.output_filename,
        "output_file_sha256": record.output_file_sha256,
        "original_row_count": metadata.get("original_row_count"),
        "processed_row_count": metadata.get("final_row_count"),
        "affected_rows": record.affected_rows,
        "affected_columns": [],
        "operation_metadata": metadata,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }
