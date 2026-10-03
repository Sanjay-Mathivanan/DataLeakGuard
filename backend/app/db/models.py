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