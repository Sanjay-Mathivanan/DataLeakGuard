from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from datetime import timezone

from app.api.identity import get_current_user
from app.db import leakage_models, models
from app.db.session import get_db
from app.schemas.identity import AuditEventRead, NotificationRead

router = APIRouter(tags=["workspace"])


@router.get("/dashboard/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    owned_dataset_ids = select(models.Dataset.id).where(
        models.Dataset.owner_user_id == user.id
    )
    total_datasets = db.query(func.count(models.Dataset.id)).filter(
        models.Dataset.owner_user_id == user.id
    ).scalar()
    findings = db.query(leakage_models.LeakageFinding).filter(
        leakage_models.LeakageFinding.dataset_id.in_(owned_dataset_ids)
    )
    total_findings = findings.count()
    open_findings = findings.filter(
        func.lower(leakage_models.LeakageFinding.status) == "open"
    ).count()
    high_findings = findings.filter(
        func.lower(leakage_models.LeakageFinding.severity).in_(["high", "critical"])
    ).count()
    recent_datasets = db.query(models.Dataset).filter(
        models.Dataset.owner_user_id == user.id
    ).order_by(
        models.Dataset.last_analysis.desc().nullslast(),
        models.Dataset.uploaded_at.desc(),
    ).limit(5).all()
    recent_operations = db.query(models.RepairRecord).filter(
        models.RepairRecord.dataset_id.in_(owned_dataset_ids)
    ).order_by(models.RepairRecord.created_at.desc()).limit(5).all()
    latest_analysis = db.query(func.max(models.Dataset.last_analysis)).filter(
        models.Dataset.owner_user_id == user.id
    ).scalar()
    return {
        "dataset_count": int(total_datasets or 0),
        "finding_count": int(total_findings or 0),
        "open_finding_count": int(open_findings or 0),
        "high_or_critical_finding_count": int(high_findings or 0),
        "latest_analysis_at": latest_analysis,
        "recent_datasets": [
            {
                "id": item.id,
                "name": item.name,
                "status": item.status,
                "last_analysis": item.last_analysis,
            }
            for item in recent_datasets
        ],
        "recent_operations": [
            {
                "id": item.id,
                "dataset_id": item.dataset_id,
                "operation_type": item.operation_type,
                "status": item.status,
                "created_at": item.created_at,
            }
            for item in recent_operations
        ],
        "models": {"available": False, "reason": "No persisted model registry is implemented."},
        "reports": {"available": False, "reason": "No persisted report registry is implemented."},
    }


@router.get("/notifications", response_model=list[NotificationRead])
def list_notifications(
    limit: int = Query(default=30, ge=1, le=100),
    unread_only: bool = False,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = db.query(models.Notification).filter(models.Notification.user_id == user.id)
    if unread_only:
        query = query.filter(models.Notification.read_at.is_(None))
    return query.order_by(models.Notification.created_at.desc()).limit(limit).all()


@router.get("/notifications/unread-count")
def unread_notification_count(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    count = db.query(func.count(models.Notification.id)).filter(
        models.Notification.user_id == user.id,
        models.Notification.read_at.is_(None),
    ).scalar()
    return {"unread_count": int(count or 0)}


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    item = db.query(models.Notification).filter(
        models.Notification.id == notification_id,
        models.Notification.user_id == user.id,
    ).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if item.read_at is None:
        from datetime import datetime, timezone
        item.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(item)
    return item


@router.post("/notifications/read-all")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from datetime import datetime, timezone
    updated = db.query(models.Notification).filter(
        models.Notification.user_id == user.id,
        models.Notification.read_at.is_(None),
    ).update(
        {models.Notification.read_at: datetime.now(timezone.utc)},
        synchronize_session=False,
    )
    db.commit()
    return {"updated_count": int(updated)}


@router.get("/datasets/{dataset_id}/findings")
def dataset_findings(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == user.id,
    ).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    items = db.query(leakage_models.LeakageFinding).filter(
        leakage_models.LeakageFinding.dataset_id == dataset_id
    ).order_by(leakage_models.LeakageFinding.created_at.desc()).all()
    return items


@router.get("/datasets/{dataset_id}/history", response_model=list[AuditEventRead])
def dataset_history(
    dataset_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == user.id,
    ).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    events = db.query(models.AuditEvent).filter(
        models.AuditEvent.user_id == user.id,
        models.AuditEvent.dataset_id == dataset_id,
    ).order_by(models.AuditEvent.created_at.desc()).limit(limit).all()
    response = [
        {
            "id": event.id,
            "event_type": event.event_type,
            "outcome": event.outcome,
            "details": event.details,
            "created_at": event.created_at,
            "dataset_id": event.dataset_id,
            "finding_id": event.finding_id,
            "operation_id": event.operation_id,
        }
        for event in events
    ]
    seen_operations = {event.operation_id for event in events if event.operation_id}
    operation_records = db.query(models.RepairRecord).filter(
        models.RepairRecord.dataset_id == dataset_id
    ).order_by(models.RepairRecord.created_at.desc()).all()
    for operation in operation_records:
        if operation.id in seen_operations:
            continue
        response.append({
            "id": f"operation:{operation.id}",
            "event_type": operation.operation_type,
            "outcome": operation.status,
            "details": operation.operation_metadata,
            "created_at": operation.completed_at or operation.created_at,
            "dataset_id": dataset_id,
            "finding_id": operation.finding_id,
            "operation_id": operation.id,
        })
    if not any(event["event_type"] == "dataset_upload" for event in response):
        response.append({
            "id": f"dataset-upload:{dataset.id}",
            "event_type": "dataset_upload",
            "outcome": "recorded",
            "details": {"source": "persisted dataset upload timestamp"},
            "created_at": dataset.uploaded_at,
            "dataset_id": dataset.id,
            "finding_id": None,
            "operation_id": None,
        })
    if dataset.last_analysis and not any(
        event["event_type"] == "analysis" for event in response
    ):
        response.append({
            "id": f"dataset-analysis:{dataset.id}",
            "event_type": "analysis",
            "outcome": "completed" if dataset.status == "Analyzed" else "unavailable",
            "details": {"source": "most recent persisted analysis timestamp"},
            "created_at": dataset.last_analysis,
            "dataset_id": dataset.id,
            "finding_id": None,
            "operation_id": None,
        })
    def timestamp(event):
        value = event["created_at"]
        if value is None:
            return 0.0
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    response.sort(key=timestamp, reverse=True)
    return response[:limit]


@router.get("/account/history", response_model=list[AuditEventRead])
def account_history(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    events = db.query(models.AuditEvent).filter(
        models.AuditEvent.user_id == user.id
    ).order_by(models.AuditEvent.created_at.desc()).limit(limit).all()
    response = [
        {
            "id": event.id,
            "event_type": event.event_type,
            "outcome": event.outcome,
            "details": event.details,
            "created_at": event.created_at,
            "dataset_id": event.dataset_id,
            "finding_id": event.finding_id,
            "operation_id": event.operation_id,
        }
        for event in events
    ]
    dataset_ids = [
        item[0]
        for item in db.query(models.Dataset.id).filter(
            models.Dataset.owner_user_id == user.id
        ).all()
    ]
    if dataset_ids:
        seen_operations = {event.operation_id for event in events if event.operation_id}
        operations = db.query(models.RepairRecord).filter(
            models.RepairRecord.dataset_id.in_(dataset_ids)
        ).order_by(models.RepairRecord.created_at.desc()).all()
        for operation in operations:
            if operation.id in seen_operations:
                continue
            response.append({
                "id": f"operation:{operation.id}",
                "event_type": operation.operation_type,
                "outcome": operation.status,
                "details": operation.operation_metadata,
                "created_at": operation.completed_at or operation.created_at,
                "dataset_id": operation.dataset_id,
                "finding_id": operation.finding_id,
                "operation_id": operation.id,
            })
        for dataset in db.query(models.Dataset).filter(
            models.Dataset.id.in_(dataset_ids)
        ).all():
            if not any(
                item["dataset_id"] == dataset.id
                and item["event_type"] == "dataset_upload"
                for item in response
            ):
                response.append({
                    "id": f"dataset-upload:{dataset.id}",
                    "event_type": "dataset_upload",
                    "outcome": "recorded",
                    "details": {"source": "persisted dataset upload timestamp"},
                    "created_at": dataset.uploaded_at,
                    "dataset_id": dataset.id,
                    "finding_id": None,
                    "operation_id": None,
                })
    def timestamp(event):
        value = event["created_at"]
        if value is None:
            return 0.0
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    response.sort(key=timestamp, reverse=True)
    return response[:limit]
