from typing import Dict, Optional

from pydantic import BaseModel, Field


class SplitGenerationRequest(BaseModel):
    test_ratio: float = Field(default=0.2, ge=0.05, le=0.95)
    random_seed: int = Field(default=42, ge=-(2**31), le=2**31 - 1)


class SplitGenerationResponse(BaseModel):
    id: str
    dataset_id: str
    operation_type: str
    status: str
    split_column: str
    test_ratio: float
    random_seed: int
    algorithm: str
    row_count: int
    split_row_counts: Dict[str, int]
    input_file_sha256: str
    output_file_sha256: str
    output_filename: str
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    reused: bool = False
