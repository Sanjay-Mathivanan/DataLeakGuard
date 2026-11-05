from typing import Any

from pydantic import BaseModel


class DatasetProfilingRead(BaseModel):
    dataset_id: str
    dataset_name: str
    source_file_sha256: str
    generated_at: str
    profile: dict[str, Any]
