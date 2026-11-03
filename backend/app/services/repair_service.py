import os
import hashlib
import hmac
import json
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

_COMBINED_REPAIR_ROW_REFERENCE_LIMIT = 200


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

    # Extract and validate duplicate evidence before modifying a copy.
    duplicate_count = evidence.get("duplicate_count")
    row_indices = evidence.get("row_indices")

    if (
        type(duplicate_count) is not int
        or duplicate_count < 2
        or not isinstance(row_indices, list)
        or len(row_indices) != duplicate_count
        or not all(type(index) is int for index in row_indices)
        or len(set(row_indices)) != len(row_indices)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate evidence is missing or malformed"
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

    # The operation is eligible only while the persisted evidence still
    # identifies exactly the same duplicate group in the current source.
    original_row_count = len(df)
    sorted_indices = sorted(row_indices)
    if any(index < 0 or index >= original_row_count for index in sorted_indices):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate evidence row indices are outside the current dataset"
        )

    excluded_columns = evidence.get("hash_excluded_columns", [])
    if (
        not isinstance(excluded_columns, list)
        or any(
            not isinstance(column, str) or column not in df.columns
            for column in excluded_columns
        )
        or len(set(excluded_columns)) != len(excluded_columns)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate evidence contains invalid hash-exclusion metadata"
        )
    comparison_frame = df.drop(columns=excluded_columns)
    try:
        current_hashes = [
            hash_row(comparison_frame.iloc[index])
            for index in range(original_row_count)
        ]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to verify duplicate evidence against the current dataset"
        ) from exc
    evidenced_hash = current_hashes[sorted_indices[0]]
    evidenced_group = [
        index for index, row_hash in enumerate(current_hashes)
        if row_hash == evidenced_hash
    ]
    stored_hash = evidence.get("hash")
    if (
        evidenced_group != sorted_indices
        or (stored_hash is not None and stored_hash != evidenced_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate evidence no longer matches the original dataset rows"
        )

    # Keep the first occurrence and remove later rows in this validated group.
    indices_to_remove = sorted_indices[1:]
    df_processed = df.drop(index=indices_to_remove).copy()

    processed_row_count = len(df_processed)
    rows_removed = original_row_count - processed_row_count

    if rows_removed != duplicate_count - 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The current duplicate evidence does not support the expected repair"
        )

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
            if dataset.format.upper() == "CSV":
                verified_frame = pd.read_csv(processed_path, dtype=str)
            else:
                verified_frame = pd.read_excel(processed_path, dtype=str)
            if (
                len(verified_frame) != processed_row_count
                or list(verified_frame.columns) != list(df.columns)
            ):
                raise ValueError("The generated output row count or schema did not verify")
            verified_comparison = verified_frame.drop(columns=excluded_columns)
            remaining_group_count = sum(
                hash_row(verified_comparison.iloc[index]) == evidenced_hash
                for index in range(len(verified_comparison))
            )
            if remaining_group_count != 1:
                raise ValueError("The duplicate condition remains after repair")

            operation_metadata = {
                "selected_finding_ids": [finding_id],
                "applied_finding_ids": [finding_id],
                "skipped_findings": [],
                "original_row_count": original_row_count,
                "final_row_count": processed_row_count,
                "duplicate_rows_removed": rows_removed,
                "evidence_reference_finding_ids": [finding_id],
                "repair_strategy": "exact_duplicate_keep_first",
                "verification_status": "verified",
                "verification": {
                    "input_file_hash_checked": bool(dataset.file_sha256),
                    "evidence_matches_input": True,
                    "output_sha256": processed_sha256,
                    "output_readable": True,
                    "output_schema_matches": True,
                    "output_row_count": len(verified_frame),
                    "remaining_evidenced_duplicate_rows": remaining_group_count,
                },
            }
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
            repair_record.operation_metadata = operation_metadata

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
        "operation_metadata": repair_record.operation_metadata,
        "created_at": repair_record.created_at.isoformat() if repair_record.created_at else None,
        "completed_at": repair_record.completed_at.isoformat() if repair_record.completed_at else None
    }


def generate_combined_exact_duplicate_repair(
    dataset_id: str,
    selected_finding_ids: List[str],
    db: Session,
    *,
    preview_only: bool = False,
    expected_preview_token: Optional[str] = None,
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

    # Return an equivalent completed operation only when the same preview was
    # explicitly confirmed. The token is a staleness check, not authorization.
    completed_operations = db.query(models.RepairRecord).filter(
        models.RepairRecord.dataset_id == dataset_id,
        models.RepairRecord.operation_type == "combined_repair",
        models.RepairRecord.status == "completed",
    ).all()
    if not preview_only and expected_preview_token:
        for existing in completed_operations:
            metadata = existing.operation_metadata
            if (
                existing.input_file_sha256 == input_sha256
                and isinstance(metadata, dict)
                and metadata.get("selected_finding_ids") == requested_ids
                and isinstance(metadata.get("preview_token"), str)
                and hmac.compare_digest(metadata["preview_token"], expected_preview_token)
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
        if finding.finding_type != "exact_duplicate":
            skipped_findings.append({
                "finding_id": finding_id,
                "reason": (
                    "Combined cleaning supports exact_duplicate findings only; "
                    f"'{finding.finding_type}' is not eligible."
                ),
            })
            continue
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

    original_row_count = len(original_frame)
    final_row_count = original_row_count - len(rows_to_remove)
    duplicate_rows_removed = len(rows_to_remove)
    removed_row_indices = sorted(rows_to_remove)
    affected_row_indices_sha256 = hashlib.sha256(
        json.dumps(
            removed_row_indices,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    preview_payload = {
        "dataset_id": dataset_id,
        "input_file_sha256": input_sha256,
        "selected_finding_ids": requested_ids,
        "applied_finding_ids": applied_ids,
        "skipped_findings": skipped_findings,
        "original_row_count": original_row_count,
        "final_row_count": final_row_count,
        "duplicate_rows_removed": duplicate_rows_removed,
        "affected_row_indices_preview": removed_row_indices[
            :_COMBINED_REPAIR_ROW_REFERENCE_LIMIT
        ],
        "affected_row_indices_count": len(removed_row_indices),
        "affected_row_indices_truncated": (
            len(removed_row_indices) > _COMBINED_REPAIR_ROW_REFERENCE_LIMIT
        ),
        "affected_row_indices_sha256": affected_row_indices_sha256,
        "removed_row_indices": removed_row_indices,
    }
    preview_token = hashlib.sha256(
        json.dumps(
            preview_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    if preview_only:
        return {
            **{
                key: value
                for key, value in preview_payload.items()
                if key != "removed_row_indices"
            },
            "operation_type": "combined_repair_preview",
            "status": "preview" if applied_ids and rows_to_remove else "not_eligible",
            "preview_token": preview_token if applied_ids and rows_to_remove else None,
            "explanation": (
                "Eligible exact-duplicate findings will be applied to one separate output. "
                "The uploaded original remains unchanged."
                if applied_ids and rows_to_remove
                else "No selected finding currently supports a safe combined-cleaning output."
            ),
        }

    if not expected_preview_token:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Run a current preview and provide its token before confirming combined cleaning",
        )
    if not hmac.compare_digest(expected_preview_token, preview_token):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Combined-cleaning inputs changed after preview; preview the current selection again",
        )

    if not applied_ids or not rows_to_remove:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "No selected findings remain eligible for combined repair",
                "skipped_findings": skipped_findings,
            },
        )

    cleaned_frame = original_frame.drop(index=sorted(rows_to_remove))
    final_row_count = len(cleaned_frame)
    metadata = {
        "selected_finding_ids": requested_ids,
        "applied_finding_ids": applied_ids,
        "skipped_findings": skipped_findings,
        "original_row_count": original_row_count,
        "final_row_count": final_row_count,
        "duplicate_rows_removed": duplicate_rows_removed,
        "affected_row_indices_preview": preview_payload[
            "affected_row_indices_preview"
        ],
        "affected_row_indices_count": preview_payload[
            "affected_row_indices_count"
        ],
        "affected_row_indices_truncated": preview_payload[
            "affected_row_indices_truncated"
        ],
        "affected_row_indices_sha256": affected_row_indices_sha256,
        "evidence_reference_finding_ids": applied_ids,
        "preview_token": preview_token,
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
