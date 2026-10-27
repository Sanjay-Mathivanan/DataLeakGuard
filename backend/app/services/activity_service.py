import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AuditEvent, Notification


def record_user_event(
    db: Session,
    *,
    user_id: str,
    event_type: str,
    outcome: str,
    title: str,
    message: str,
    dataset_id: str | None = None,
    finding_id: str | None = None,
    operation_id: str | None = None,
    details: dict | None = None,
    deduplication_key: str | None = None,
) -> AuditEvent:
    """Persist one user-scoped event and its notification atomically."""
    if deduplication_key:
        existing = db.query(AuditEvent).filter(
            AuditEvent.deduplication_key == deduplication_key
        ).first()
        if existing:
            return existing
    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    event = AuditEvent(
        id=event_id,
        user_id=user_id,
        dataset_id=dataset_id,
        finding_id=finding_id,
        operation_id=operation_id,
        event_type=event_type,
        outcome=outcome,
        details=details,
        deduplication_key=deduplication_key,
        created_at=now,
    )
    notification = Notification(
        user_id=user_id,
        event_type=event_type,
        title=title,
        message=message,
        dataset_id=dataset_id,
        finding_id=finding_id,
        operation_id=operation_id,
        deduplication_key=f"notification:{deduplication_key}" if deduplication_key else None,
        created_at=now,
    )
    db.add_all([event, notification])
    try:
        db.commit()
        db.refresh(event)
        return event
    except IntegrityError:
        db.rollback()
        if deduplication_key:
            existing = db.query(AuditEvent).filter(
                AuditEvent.deduplication_key == deduplication_key
            ).first()
            if existing:
                return existing
        raise
