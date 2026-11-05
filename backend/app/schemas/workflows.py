from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ModelArtifactRead(BaseModel):
    id: str
    name: str
    version: Optional[str] = None
    original_filename: str
    sha256: str
    size_bytes: int
    metadata_json: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class ProvenanceCreate(BaseModel):
    dataset_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DistributionCreate(BaseModel):
    reference_dataset_id: str
    comparison_dataset_id: str


class PartitionDistributionCreate(BaseModel):
    reference_partition: str = Field(min_length=1, max_length=200)
    comparison_partition: str = Field(min_length=1, max_length=200)


class PartitionDistributionRead(BaseModel):
    id: str
    dataset_id: str
    created_at: str
    result: Dict[str, Any]


class ImpactCreate(BaseModel):
    dataset_id: str


class ReportCreate(BaseModel):
    title: str = "DataLeakGuard report"
    dataset_id: Optional[str] = None

