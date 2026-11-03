"""Safe, reproducible split-output generation and validation helpers."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db import models
from app.utils.file_storage import (
    ORIGINAL_DIR,
    PROCESSED_DIR,
    compute_file_sha256,
)
from app.services.repair_quarantine_utils import (
    cleanup_created_output_if_unreferenced,
    generate_output_filename,
    get_and_validate_original_path,
)


GENERATED_SPLIT_COLUMN = "__dataleakguard_split__"
SPLIT_ALGORITHM = "sha256_seeded_row_order_v1"
_SPLIT_LABELS = {
    "train": "train",
    "training": "train",
    "test": "test",
    "testing": "test",
    "validation": "validation",
    "val": "validation",
}


def read_tabular_frame(path: Path, file_format: str) -> pd.DataFrame:
    """Read supported tabular inputs as strings to preserve detector semantics."""
    try:
        if file_format.upper() == "CSV":
            return pd.read_csv(path, dtype=str)
        if file_format.upper() == "XLSX":
            return pd.read_excel(path, dtype=str)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read the dataset for split validation or analysis",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Split strategies support CSV and XLSX datasets only",
    )


def validate_existing_split(
    frame: pd.DataFrame,
    split_column: str,
    *,
    allow_missing: bool = False,
) -> dict[str, Any]:
    """Validate a user-confirmed split column and report its observed categories."""
    if split_column not in frame.columns:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Selected split column '{split_column}' does not exist in the dataset",
        )
    values = frame[split_column].astype("string").str.strip()
    missing_count = int((values.isna() | values.eq("").fillna(False)).sum())
    if missing_count and not allow_missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Selected split column '{split_column}' has {missing_count} "
                "missing or blank rows; assign every row to a split before analysis"
            ),
        )
    # Match the contamination detector's case-insensitive split semantics so
    # values such as "train" and "TRAIN" cannot masquerade as two partitions.
    normalized_values = values.str.casefold()
    observed_values = normalized_values.dropna()
    observed_values = observed_values[observed_values != ""]
    counts = observed_values.value_counts()
    if len(counts) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Selected split column '{split_column}' must contain at least "
                "two non-empty split groups"
            ),
        )
    split_counts = {str(value): int(count) for value, count in counts.items()}
    recognized = sorted(
        {
            _SPLIT_LABELS[str(value)]
            for value in counts.index
            if str(value) in _SPLIT_LABELS
        }
    )
    warnings = []
    if missing_count:
        warnings.append(
            f"{missing_count} rows have no split membership and will be ignored by "
            "split-dependent detectors for backward-compatible analysis."
        )
    if not {"train", "test"}.issubset(set(recognized)):
        warnings.append(
            "The selected values do not explicitly include both train and test labels. "
            "All distinct values will be compared because you confirmed this split column."
        )
    return {
        "split_column": split_column,
        "split_row_counts": split_counts,
        "recognized_partitions": recognized,
        "missing_rows": missing_count,
        "warnings": warnings,
    }


def _row_order_key(seed: int, row_index: int) -> bytes:
    return hashlib.sha256(f"{seed}:{row_index}".encode("ascii")).digest()


def _read_original(dataset: models.Dataset) -> tuple[Path, pd.DataFrame, str]:
    original_path = get_and_validate_original_path(dataset)
    actual_hash = compute_file_sha256(original_path)
    if dataset.file_sha256 and actual_hash.lower() != dataset.file_sha256.lower():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Original dataset SHA-256 no longer matches its registered digest",
        )
    frame = read_tabular_frame(original_path, dataset.format)
    return original_path, frame, actual_hash


def _valid_completed_output(operation: models.RepairRecord) -> bool:
    filename = operation.output_filename
    if not isinstance(filename, str) or Path(filename).name != filename:
        return False
    path = (PROCESSED_DIR / filename).resolve()
    try:
        root = PROCESSED_DIR.resolve()
        path.relative_to(root)
        if not path.is_file() or not operation.output_file_sha256:
            return False
        return compute_file_sha256(path).lower() == operation.output_file_sha256.lower()
    except (OSError, ValueError, RuntimeError):
        return False


def generate_split_output(
    *,
    dataset: models.Dataset,
    test_ratio: float,
    random_seed: int,
    db: Session,
) -> dict[str, Any]:
    """Write a separate deterministic row-level train/test split copy."""
    if dataset.format.upper() not in {"CSV", "XLSX"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Generated splits support CSV and XLSX datasets only",
        )
    original_path, original_frame, input_hash = _read_original(dataset)
    if len(original_frame) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least two dataset rows are required to generate a train/test split",
        )
    if GENERATED_SPLIT_COLUMN in original_frame.columns:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"The reserved generated-split column '{GENERATED_SPLIT_COLUMN}' "
                "already exists; choose an existing split or rename the source column"
            ),
        )

    # Idempotently reuse the same completed output when the source and settings
    # match and its stored bytes still verify.
    existing_operations = db.query(models.RepairRecord).filter(
        models.RepairRecord.dataset_id == dataset.id,
        models.RepairRecord.operation_type == "split_generation",
        models.RepairRecord.status == "completed",
    ).all()
    for operation in existing_operations:
        metadata = operation.operation_metadata
        if (
            operation.input_file_sha256 == input_hash
            and isinstance(metadata, dict)
            and metadata.get("test_ratio") == test_ratio
            and metadata.get("random_seed") == random_seed
            and metadata.get("algorithm") == SPLIT_ALGORITHM
            and metadata.get("split_column") == GENERATED_SPLIT_COLUMN
            and _valid_completed_output(operation)
        ):
            return _split_operation_response(
                operation,
                reused=True,
            )

    row_count = len(original_frame)
    test_count = min(max(int(row_count * test_ratio + 0.5), 1), row_count - 1)
    ordered_indices = sorted(
        range(row_count),
        key=lambda index: (_row_order_key(random_seed, index), index),
    )
    test_indices = set(ordered_indices[:test_count])
    split_values = [
        "test" if index in test_indices else "train"
        for index in range(row_count)
    ]
    generated_frame = original_frame.copy()
    generated_frame[GENERATED_SPLIT_COLUMN] = split_values
    split_counts = {
        "train": row_count - test_count,
        "test": test_count,
    }
    metadata = {
        "strategy": "generated",
        "split_column": GENERATED_SPLIT_COLUMN,
        "test_ratio": float(test_ratio),
        "random_seed": int(random_seed),
        "algorithm": SPLIT_ALGORITHM,
        "row_count": row_count,
        "split_row_counts": split_counts,
        "group_aware": False,
        "stratified": False,
        "source_filename": dataset.storage_filename,
        "source_sha256": input_hash,
        "created_from_original": True,
    }

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output_path: Path | None = None
    output_filename: str | None = None
    output_created = False
    try:
        for _ in range(5):
            output_filename = generate_output_filename(dataset.storage_filename or "dataset.csv")
            output_path = PROCESSED_DIR / output_filename
            try:
                if dataset.format.upper() == "CSV":
                    output = output_path.open("x", encoding="utf-8", newline="")
                else:
                    output = output_path.open("xb")
                output_created = True
                break
            except FileExistsError:
                continue
        else:
            raise FileExistsError("Unable to allocate a unique split output filename")

        with output:
            if dataset.format.upper() == "CSV":
                generated_frame.to_csv(output, index=False)
            else:
                generated_frame.to_excel(output, index=False)
        output_hash = compute_file_sha256(output_path)
        record = models.RepairRecord(
            dataset_id=dataset.id,
            finding_id=None,
            operation_type="split_generation",
            status="completed",
            input_file_sha256=input_hash,
            output_file_sha256=output_hash,
            output_filename=output_filename,
            affected_rows=0,
            affected_columns=[GENERATED_SPLIT_COLUMN],
            operation_metadata=metadata,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
    except HTTPException:
        if output_path is not None and output_filename is not None:
            cleanup_created_output_if_unreferenced(
                db, output_path, output_filename, output_created
            )
        raise
    except Exception as exc:
        if output_path is not None and output_filename is not None:
            cleanup_created_output_if_unreferenced(
                db, output_path, output_filename, output_created
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate and persist the split output",
        ) from exc

    return _split_operation_response(record, reused=False)


def _split_operation_response(
    operation: models.RepairRecord,
    *,
    reused: bool,
) -> dict[str, Any]:
    metadata = operation.operation_metadata or {}
    return {
        "id": operation.id,
        "dataset_id": operation.dataset_id,
        "operation_type": operation.operation_type,
        "status": operation.status,
        "split_column": metadata.get("split_column"),
        "test_ratio": metadata.get("test_ratio"),
        "random_seed": metadata.get("random_seed"),
        "algorithm": metadata.get("algorithm"),
        "row_count": metadata.get("row_count"),
        "split_row_counts": metadata.get("split_row_counts", {}),
        "input_file_sha256": operation.input_file_sha256,
        "output_file_sha256": operation.output_file_sha256,
        "output_filename": operation.output_filename,
        "created_at": operation.created_at.isoformat() if operation.created_at else None,
        "completed_at": operation.completed_at.isoformat() if operation.completed_at else None,
        "reused": reused,
    }


def load_generated_split_frame(
    *,
    dataset: models.Dataset,
    operation_id: str,
    db: Session,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load only a verified split operation belonging to the owned dataset."""
    operation = db.query(models.RepairRecord).filter(
        models.RepairRecord.id == operation_id,
        models.RepairRecord.dataset_id == dataset.id,
        models.RepairRecord.operation_type == "split_generation",
        models.RepairRecord.status == "completed",
    ).first()
    if operation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Completed split generation operation not found for this dataset",
        )
    original_path, original_frame, current_input_hash = _read_original(dataset)
    if operation.input_file_sha256.lower() != current_input_hash.lower():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generated split belongs to an older version of the original dataset",
        )
    if not _valid_completed_output(operation):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generated split output is missing or failed SHA-256 verification",
        )
    metadata = operation.operation_metadata
    if (
        not isinstance(metadata, dict)
        or metadata.get("algorithm") != SPLIT_ALGORITHM
        or metadata.get("split_column") != GENERATED_SPLIT_COLUMN
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generated split metadata is invalid",
        )
    output_path = PROCESSED_DIR / operation.output_filename
    frame = read_tabular_frame(output_path, dataset.format)
    if (
        GENERATED_SPLIT_COLUMN not in frame.columns
        or len(frame) != metadata.get("row_count")
        or frame.columns.tolist()
        != [*original_frame.columns.tolist(), GENERATED_SPLIT_COLUMN]
        or not frame.drop(columns=[GENERATED_SPLIT_COLUMN]).equals(original_frame)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generated split output does not preserve the registered source rows and schema",
        )
    split_validation = validate_existing_split(frame, GENERATED_SPLIT_COLUMN)
    if split_validation["split_row_counts"] != metadata.get("split_row_counts"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generated split row counts do not match persisted operation metadata",
        )
    if metadata.get("source_sha256") != current_input_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generated split source digest does not match the registered dataset",
        )
    # Ensure the source was not changed while reading the separately stored output.
    if compute_file_sha256(original_path).lower() != current_input_hash.lower():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Original dataset changed while the generated split was being loaded",
        )
    return frame, metadata


def split_configuration_digest(configuration: dict[str, Any]) -> str:
    """Stable digest used by split strategy audit/preview references."""
    payload = json.dumps(configuration, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
