from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.identity import get_current_user
from app.db import models
from app.db.session import get_db
from app.schemas.remediation import (
    RemediationCancelRequest,
    RemediationExecuteRequest,
    RemediationPreviewRequest,
)
from app.services.activity_service import record_user_event
from app.services.remediation_service import (
    cancel_remediation_plan,
    execute_remediation_plan,
    list_remediation_plans,
    preview_remediation_plan,
    resolve_remediation_artifact,
)

router = APIRouter()


def _owned_dataset(
    dataset_id: str,
    db: Session,
    user: models.User,
) -> models.Dataset:
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == user.id,
    ).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


@router.post(
    "/datasets/{dataset_id}/remediation-plans/preview",
    status_code=status.HTTP_201_CREATED,
)
def create_remediation_preview(
    dataset_id: str,
    request: RemediationPreviewRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Persist a server-validated preview without changing the source dataset."""
    dataset = _owned_dataset(dataset_id, db, user)
    result = preview_remediation_plan(
        dataset=dataset,
        actions=request.actions,
        db=db,
    )
    plan = result.get("plan", {})
    record_user_event(
        db,
        user_id=user.id,
        dataset_id=dataset_id,
        operation_id=result.get("id"),
        event_type="remediation_preview",
        outcome="completed",
        title="Remediation preview created",
        message="A server-validated remediation preview is ready for review.",
        details={
            "selected_finding_count": plan.get("selected_count", 0),
            "detector_types": plan.get("detector_types", []),
            "affected_source_row_positions_count": plan.get(
                "affected_source_row_positions_count", 0
            ),
            "preview_digest": plan.get("preview_digest"),
        },
        deduplication_key=f"remediation-preview:{result['id']}",
    )
    return result


@router.post(
    "/datasets/{dataset_id}/remediation-plans/{plan_id}/execute",
    status_code=status.HTTP_201_CREATED,
)
def execute_remediation_preview(
    dataset_id: str,
    plan_id: str,
    request: RemediationExecuteRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _owned_dataset(dataset_id, db, user)
    try:
        result = execute_remediation_plan(
            db=db,
            dataset_id=dataset_id,
            plan_id=plan_id,
            owner_user_id=user.id,
            preview_token=request.preview_token,
            confirmed=request.confirmed,
        )
    except Exception as exc:
        record_user_event(
            db,
            user_id=user.id,
            dataset_id=dataset_id,
            operation_id=plan_id,
            event_type="consolidated_remediation",
            outcome="failed",
            title="Consolidated remediation failed",
            message="The confirmed remediation plan did not produce a verified output.",
            details={"failure_reason": str(getattr(exc, "detail", exc))[:500]},
            deduplication_key=f"consolidated-remediation-failed:{plan_id}",
        )
        raise

    result_status = result.get("status")
    record_user_event(
        db,
        user_id=user.id,
        dataset_id=dataset_id,
        operation_id=plan_id,
        event_type="consolidated_remediation",
        outcome="failed" if result_status == "failed" else "completed",
        title=(
            "Consolidated remediation verification failed"
            if result_status == "failed"
            else "Consolidated remediation completed"
        ),
        message=(
            "The output was generated but one or more post-remediation checks failed."
            if result_status == "failed"
            else "A separate remediation output and audit manifest were generated."
        ),
        details={
            "operation_status": result_status,
            "final_status": (result.get("plan") or {}).get("final_status"),
            "verification": (result.get("plan") or {}).get("verification"),
            "artifact_hashes": result.get("artifact_hashes", {}),
        },
        deduplication_key=f"consolidated-remediation:{plan_id}",
    )
    return result


@router.post(
    "/datasets/{dataset_id}/remediation-plans/{plan_id}/cancel",
)
def cancel_remediation_preview(
    dataset_id: str,
    plan_id: str,
    request: RemediationCancelRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _owned_dataset(dataset_id, db, user)
    result = cancel_remediation_plan(
        db=db,
        dataset_id=dataset_id,
        plan_id=plan_id,
        owner_user_id=user.id,
        reason=request.reason,
    )
    record_user_event(
        db,
        user_id=user.id,
        dataset_id=dataset_id,
        operation_id=plan_id,
        event_type="remediation_cancelled",
        outcome="completed",
        title="Remediation preview cancelled",
        message="The preview was cancelled without changing the source dataset.",
        details={"reason": request.reason},
        deduplication_key=f"remediation-cancelled:{plan_id}",
    )
    return result


@router.get("/datasets/{dataset_id}/remediation-plans")
def get_remediation_plans(
    dataset_id: str,
    skip: int = Query(default=0, ge=0, le=1_000_000),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return list_remediation_plans(
        db=db,
        dataset_id=dataset_id,
        owner_user_id=user.id,
        skip=skip,
        limit=limit,
    )


@router.get("/operations/{operation_id}/remediation-artifacts/{artifact}")
def download_remediation_artifact(
    operation_id: str,
    artifact: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    path, filename, media_type = resolve_remediation_artifact(
        db=db,
        operation_id=operation_id,
        owner_user_id=user.id,
        artifact=artifact,
    )
    return FileResponse(path=path, media_type=media_type, filename=filename)
