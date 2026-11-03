import uuid
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON, ForeignKey
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
    # Legacy datasets remain unowned until an explicit ownership decision.
    owner_user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)

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
    operation_type = Column(String, nullable=False)  # repair, quarantine, or combined_repair
    status = Column(String, nullable=False, default='pending')  # 'pending', 'processing', 'completed', 'failed'
    input_file_sha256 = Column(String, nullable=False)
    output_file_sha256 = Column(String, nullable=True)
    output_filename = Column(String, nullable=True)  # Name of the processed output file
    affected_rows = Column(Integer, nullable=False, default=0)
    affected_columns = Column(JSON, nullable=True)  # List of column names affected
    quarantine_info = Column(JSON, nullable=True)  # For quarantine operations
    operation_metadata = Column(JSON, nullable=True)  # Provenance for compound operations
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_info = Column(JSON, nullable=True)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    csrf_token_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    dataset_id = Column(String, nullable=True, index=True)
    finding_id = Column(String, nullable=True, index=True)
    operation_id = Column(String, nullable=True, index=True)
    event_type = Column(String, nullable=False, index=True)
    outcome = Column(String, nullable=False)
    details = Column(JSON, nullable=True)
    deduplication_key = Column(String, nullable=True, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    dataset_id = Column(String, nullable=True, index=True)
    finding_id = Column(String, nullable=True, index=True)
    operation_id = Column(String, nullable=True, index=True)
    deduplication_key = Column(String, nullable=True, unique=True)


class ModelArtifact(Base):
    __tablename__ = "model_artifacts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    version = Column(String, nullable=True)
    storage_filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    sha256 = Column(String, nullable=False, index=True)
    size_bytes = Column(Integer, nullable=False)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProvenanceRecord(Base):
    __tablename__ = "provenance_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=False, index=True)
    metadata_json = Column(JSON, nullable=False)
    prediction_status = Column(String, nullable=False, default="no_prediction")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DistributionComparison(Base):
    __tablename__ = "distribution_comparisons"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    reference_dataset_id = Column(String, ForeignKey("datasets.id"), nullable=False)
    comparison_dataset_id = Column(String, ForeignKey("datasets.id"), nullable=False)
    metrics_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ImpactMetric(Base):
    __tablename__ = "impact_metrics"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=False, index=True)
    metrics_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReportMetadata(Base):
    __tablename__ = "report_metadata"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    format = Column(String, nullable=False)
    content_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
