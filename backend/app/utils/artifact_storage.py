import hashlib
import uuid
from pathlib import Path

from app.utils.file_storage import STORAGE_BASE

MODEL_DIR = STORAGE_BASE / "models"


def save_model_artifact(content: bytes, filename: str) -> tuple[str, str, int]:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    storage_filename = f"{uuid.uuid4()}{suffix}"
    path = MODEL_DIR / storage_filename
    path.write_bytes(content)
    return storage_filename, hashlib.sha256(content).hexdigest(), len(content)


def get_model_path(storage_filename: str) -> Path:
    path = (MODEL_DIR / storage_filename).resolve()
    if path.parent != MODEL_DIR.resolve():
        raise ValueError("Invalid artifact path")
    return path
