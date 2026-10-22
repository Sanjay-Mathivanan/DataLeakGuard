import uuid
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON
from sqlalchemy.sql import func
from .base import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(
        String,
        primary_key=True,
        index=True,
        default=lambda: str(uuid.uuid4())
    )
    name = Column(String, index=True)
    type = Column(String)  # tabular or computer-vision
    format = Column(String)  # CSV, XLSX, ZIP, YOLO, COCO
    sample_count = Column(Integer)
    feature_count = Column(Integer)
    class_count = Column(Integer)
    status = Column(String)  # IntegrityStatus
    issues_count = Column(Integer, default=0)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    last_analysis = Column(DateTime(timezone=True), nullable=True)
    description = Column(Text)
    # Storage fields
    storage_filename = Column(String, nullable=True)
    file_sha256 = Column(String, nullable=True)
    profile = Column(JSON, nullable=True)
    # Optional fields
    preview_rows = Column(JSON, nullable=True)
    columns = Column(JSON, nullable=True)
    cv_stats = Column(JSON, nullable=True)

class RepairRecord(Base):
    __tablename__ = "repair_records"

    id = Column(
        String,
        primary_key=True,
        index=True,
        default=lambda: str(uuid.uuid4())
    )

    dataset_id = Column(String, nullable=False, index=True)
    finding_id = Column(String, nullable=True, index=True)  # Nullable for dataset-level repairs
    operation_type = Column(String, nullable=False)  # 'repair' or 'quarantine'
    status = Column(String, nullable=False, default='pending')  # 'pending', 'processing', 'completed', 'failed'
    input_file_sha256 = Column(String, nullable=False)
    output_file_sha256 = Column(String, nullable=True)
    output_filename = Column(String, nullable=True)  # Name of the processed output file
    affected_rows = Column(Integer, nullable=False, default=0)
    affected_columns = Column(JSON, nullable=True)  # List of column names affected
    quarantine_info = Column(JSON, nullable=True)  # For quarantine operations
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_info = Column(JSON, nullable=True)
