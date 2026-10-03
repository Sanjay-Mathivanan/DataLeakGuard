from sqlalchemy.orm import Session
from app.db import models
from app.utils.file_storage import save_upload_file, compute_file_sha256, get_file_path
from app.utils.profiling.tabular import profile_tabular
from app.utils.profiling.image_zip import profile_image_zip
from app.core.config import settings
import json
import os

def create_dataset_from_upload(
    db: Session,
    *,
    name: str,
    dataset_type: str,  # 'tabular' or 'computer-vision'
    format: str,        # e.g., 'CSV', 'XLSX', 'ZIP'
    description: str,
    file_content: bytes,
    original_filename: str
) -> models.Dataset:
    """
    Handle upload: store file, compute hash, profile, create Dataset record.
    """
    # Store file and get metadata
    storage_filename, storage_path, file_sha256 = save_upload_file(
        file_content=file_content,
        original_filename=original_filename,
        dataset_type=dataset_type,
        max_size_mb=getattr(settings, "MAX_UPLOAD_SIZE_MB", 100)
    )

    # Profile based on type/format
    profile = {}
    if dataset_type == "tabular" and format.upper() in {"CSV", "XLSX"}:
        profile = profile_tabular(storage_path)
    elif dataset_type == "computer-vision" and format.upper() == "ZIP":
        profile = profile_image_zip(storage_path)
    else:
        # Unsupported combination; still store but profile empty
        profile = {"warning": f"No profiler for type={dataset_type}, format={format}"}

    # Create DB record
    db_dataset = models.Dataset(
        name=name,
        type=dataset_type,
        format=format,
        description=description,
        storage_filename=storage_filename,
        file_sha256=file_sha256,
        profile=profile if profile else None,
        # other fields like sample_count etc. can be filled from profile if desired
    )
    db.add(db_dataset)
    db.commit()
    db.refresh(db_dataset)
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