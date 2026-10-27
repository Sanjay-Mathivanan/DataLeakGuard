from pydantic import BaseModel, field_serializer
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

class DatasetBase(BaseModel):
    name: str
    type: str  # tabular or computer-vision
    format: str  # CSV, XLSX, ZIP, YOLO, COCO
    sample_count: Optional[int] = None
    feature_count: Optional[int] = None
    class_count: Optional[int] = None
    status: Optional[str] = None  # IntegrityStatus
    issues_count: Optional[int] = 0
    description: Optional[str] = None
    preview_rows: Optional[List[Dict[str, Any]]] = None
    columns: Optional[List[Dict[str, Any]]] = None
    cv_stats: Optional[Dict[str, Any]] = None

class DatasetCreate(DatasetBase):
    pass

class DatasetInDB(DatasetBase):
    id: str
    uploaded_at: datetime
    last_analysis: Optional[datetime] = None
    storage_filename: Optional[str] = None
    file_sha256: Optional[str] = None
    profile: Optional[Dict[str, Any]] = None

    class Config:
        orm_mode = True

    @field_serializer("last_analysis")
    def serialize_last_analysis(self, value: Optional[datetime]):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
