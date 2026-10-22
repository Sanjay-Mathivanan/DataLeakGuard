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


def validate_upload_file(
    original_filename: str,
    dataset_type: str,
    file_format: str = None
) -> str:
    """Validate the supported dataset type, extension, and declared format."""
    allowed_formats = {
        "tabular": {"csv": "CSV", "xlsx": "XLSX"},
        "computer-vision": {"zip": "ZIP"},
    }
    formats_by_extension = allowed_formats.get(dataset_type)
    if formats_by_extension is None:
        raise ValueError(f"Unsupported dataset type: {dataset_type}")

    if not _allowed_file(original_filename, set(formats_by_extension)):
        allowed_extensions = ", ".join(f".{ext}" for ext in formats_by_extension)
        raise ValueError(
            f"File extension not allowed for type {dataset_type}. "
            f"Allowed: {allowed_extensions}"
        )

    extension = original_filename.rsplit(".", 1)[1].lower()
    expected_format = formats_by_extension[extension]
    if file_format is not None and file_format.strip().upper() != expected_format:
        raise ValueError(
            f"Declared format {file_format!r} does not match "
            f"file extension .{extension}"
        )

    return extension


def save_upload_file(
    file_content: bytes | bytearray,
    original_filename: str,
    dataset_type: str,  # 'tabular' or 'computer-vision'
    max_size_mb: int = None
) -> Tuple[str, str, str]:
    """
    Save an uploaded file to storage/original with a UUID name.
    Returns (storage_filename, storage_path, sha256_hex).
    Raises ValueError on validation errors.
    """
    file_ext = validate_upload_file(original_filename, dataset_type)

    # Size check
    max_size = (
        getattr(settings, "MAX_UPLOAD_SIZE_MB", 100)
        if max_size_mb is None
        else max_size_mb
    )
    max_size_bytes = max_size * 1024 * 1024
    if len(file_content) > max_size_bytes:
        raise ValueError(
            f"File size exceeds limit of {max_size} MB "
            f"({len(file_content)} bytes provided)"
        )

    # Compute SHA-256
    sha256_hash = hashlib.sha256(file_content).hexdigest()

    # Exclusive creation prevents a UUID collision from overwriting an
    # existing original file.
    while True:
        storage_filename = f"{uuid.uuid4()}.{file_ext}"
        storage_path = ORIGINAL_DIR / storage_filename
        try:
            output = open(storage_path, "xb")
            break
        except FileExistsError:
            continue

    try:
        with output:
            output.write(file_content)
    except Exception:
        # Exclusive creation proves this request created the partial file.
        try:
            storage_path.unlink()
        except OSError:
            pass
        raise

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
