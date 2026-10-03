import os
import uuid
import hashlib
from pathlib import Path
from typing import Tuple
from app.core.config import settings

# Storage base directory
STORAGE_BASE = Path(__file__).resolve().parents[2] / "storage"
ORIGINAL_DIR = STORAGE_BASE / "original"
PROCESSED_DIR = STORAGE_BASE / "processed"
QUARANTINE_DIR = STORAGE_BASE / "quarantine"

# Ensure directories exist
ORIGINAL_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

def _allowed_file(filename: str, allowed_extensions: set) -> bool:
    return "." in filename and \
           filename.rsplit(".", 1)[1].lower() in allowed_extensions

def save_upload_file(
    file_content: bytes,
    original_filename: str,
    dataset_type: str,  # 'tabular' or 'computer-vision'
    max_size_mb: int = None
) -> Tuple[str, str, str]:
    """
    Save an uploaded file to storage/original with a UUID name.
    Returns (storage_filename, storage_path, sha256_hex).
    Raises ValueError on validation errors.
    """
    # Determine allowed extensions based on dataset type
    if dataset_type == "tabular":
        allowed_extensions = {"csv", "xlsx"}
    elif dataset_type == "computer-vision":
        allowed_extensions = {"zip"}
    else:
        raise ValueError(f"Unsupported dataset type: {dataset_type}")

    if not _allowed_file(original_filename, allowed_extensions):
        raise ValueError(
            f"File extension not allowed for type {dataset_type}. "
            f"Allowed: {allowed_extensions}"
        )

    # Size check
    max_size = max_size_mb or getattr(settings, "MAX_UPLOAD_SIZE_MB", 100)
    max_size_bytes = max_size * 1024 * 1024
    if len(file_content) > max_size_bytes:
        raise ValueError(
            f"File size exceeds limit of {max_size} MB "
            f"({len(file_content)} bytes provided)"
        )

    # Compute SHA-256
    sha256_hash = hashlib.sha256(file_content).hexdigest()

    # Generate UUID-based filename preserving original extension
    file_ext = original_filename.rsplit(".", 1)[1].lower()
    storage_filename = f"{uuid.uuid4()}.{file_ext}"
    storage_path = ORIGINAL_DIR / storage_filename

    # Write file
    with open(storage_path, "wb") as f:
        f.write(file_content)

    return storage_filename, str(storage_path), sha256_hash


def get_file_path(storage_filename: str) -> Path:
    """Return absolute Path to stored original file."""
    return ORIGINAL_DIR / storage_filename


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA-256 of a file."""
    hash_sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()