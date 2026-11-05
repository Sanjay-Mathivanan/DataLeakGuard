from sqlalchemy.orm import Session
from app.db import models
from app.utils.file_storage import save_upload_file, compute_file_sha256, get_file_path
from app.utils.profiling.image_zip import profile_image_zip
from app.services.profiling_service import (
    build_dataset_column_metadata,
    profile_dataframe,
    read_tabular_frame,
)
from app.core.config import settings
import json
import os
import pandas as pd
from pathlib import Path
from datetime import date, datetime
from app.utils.file_storage import validate_upload_file


def _remove_unreferenced_upload(
    db: Session,
    storage_filename: str,
    storage_path: str
) -> None:
    """Remove only this upload when the database confirms it is unreferenced."""
    try:
        db.rollback()
        referenced = (
            db.query(models.Dataset.id)
            .filter(models.Dataset.storage_filename == storage_filename)
            .first()
        )
    except Exception:
        # If persistence cannot be checked, preserve the file rather than risk
        # deleting an original that may already be referenced by a row.
        return

    if referenced is None:
        try:
            Path(storage_path).unlink(missing_ok=True)
        except OSError:
            pass


def _json_preview_value(value):
    """Convert pandas/numpy scalars to values accepted by the JSON column."""
    if pd.isna(value):
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def create_dataset_from_upload(
    db: Session,
    *,
    name: str,
    dataset_type: str,  # 'tabular' or 'computer-vision'
    format: str,        # e.g., 'CSV', 'XLSX', 'ZIP'
    description: str,
    file_content: bytes | bytearray,
    original_filename: str,
    owner_user_id: str | None = None,
) -> models.Dataset:
    """
    Handle upload: store file, compute hash, profile, create Dataset record.
    """
    validate_upload_file(original_filename, dataset_type, format)

    # Store file and get metadata
    storage_filename, storage_path, file_sha256 = save_upload_file(
        file_content=file_content,
        original_filename=original_filename,
        dataset_type=dataset_type,
        max_size_mb=getattr(settings, "MAX_UPLOAD_SIZE_MB", 100)
    )

    # Profile based on type/format. Tabular uploads are read once; the same
    # frame feeds the detailed profile, legacy column metadata, and preview.
    profile = {}
    tabular_frame = None
    try:
        if dataset_type == "tabular" and format.upper() in {"CSV", "XLSX"}:
            tabular_frame = read_tabular_frame(storage_path)
            profile = profile_dataframe(
                tabular_frame,
                storage_path,
                dataset_name=name,
            )
        elif dataset_type == "computer-vision" and format.upper() == "ZIP":
            profile = profile_image_zip(storage_path)
        else:
            # Unsupported combinations are rejected before storage; retain a
            # defensive fallback for direct callers if the supported set grows.
            profile = {"warning": f"No profiler for type={dataset_type}, format={format}"}
    except Exception:
        _remove_unreferenced_upload(db, storage_filename, storage_path)
        raise

    # Initialize extra fields
    sample_count = None
    feature_count = None
    class_count = None
    columns = None
    preview_rows = None
    cv_stats = None

    # Preserve the existing dataset response shape while deriving its values
    # from the same detailed profile.
    if (
        dataset_type == "tabular"
        and format.upper() in {"CSV", "XLSX"}
        and "error" not in profile
        and tabular_frame is not None
    ):
        try:
            sample_count = int(profile.get("row_count", len(tabular_frame)))
            feature_count = int(profile.get("column_count", len(tabular_frame.columns)))
            columns = build_dataset_column_metadata(profile)
            preview_rows = [
                {
                    str(column): _json_preview_value(value)
                    for column, value in row.items()
                }
                for row in tabular_frame.head(6).to_dict(orient="records")
            ]
        except Exception:
            # If any error occurs in computing extra fields, leave them as None
            pass

    # Create DB record
    try:
        db_dataset = models.Dataset(
            name=name,
            type=dataset_type,
            format=format,
            description=description,
            owner_user_id=owner_user_id,
            status="Uploaded",
            storage_filename=storage_filename,
            file_sha256=file_sha256,
            profile=profile if profile else None,
            sample_count=sample_count,
            feature_count=feature_count,
            class_count=class_count,
            columns=columns,
            preview_rows=preview_rows,
            cv_stats=cv_stats,
        )
        db.add(db_dataset)
        db.commit()
        db.refresh(db_dataset)
    except Exception:
        _remove_unreferenced_upload(db, storage_filename, storage_path)
        raise
    return db_dataset


def get_dataset_file_path(dataset: models.Dataset) -> str:
    """
    Return absolute path to stored original file.
    Raises if file missing.
    """
    if not dataset.storage_filename:
        raise ValueError("Dataset has no storage filename")
    path = get_file_path(dataset.storage_filename)
    if not path.exists():
        raise FileNotFoundError(f"Stored file not found: {path}")
    return str(path)


def verify_dataset_integrity(dataset: models.Dataset) -> bool:
    """
    Recompute SHA-256 and compare to stored value.
    """
    if not dataset.storage_filename or not dataset.file_sha256:
        return False
    try:
        path = get_file_path(dataset.storage_filename)
        current_hash = compute_file_sha256(path)
        return current_hash == dataset.file_sha256
    except Exception:
        return False
