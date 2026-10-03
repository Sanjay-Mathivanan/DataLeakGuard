from sqlalchemy import Column, String, DateTime, Text, JSON, ForeignKey
from sqlalchemy.sql import func
from .base import Base
import uuid


class LeakageFinding(Base):
    __tablename__ = "leakage_findings"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=False)
    finding_type = Column(String, nullable=False)  # e.g., 'exact_duplicate', 'near_duplicate_image'
    severity = Column(String, nullable=False)  # e.g., 'low', 'medium', 'high'
    status = Column(String, nullable=False, default='open')  # e.g., 'open', 'under_review', 'resolved', 'false_positive'
    description = Column(Text, nullable=False)
    evidence = Column(JSON, nullable=False)  # structured evidence
    created_at = Column(DateTime(timezone=True), server_default=func.now())