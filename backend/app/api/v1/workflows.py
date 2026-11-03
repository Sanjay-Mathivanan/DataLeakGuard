import json
import hashlib
import hmac

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.api.identity import get_current_user
from app.core.dataset_service import get_dataset_file_path
from app.db import models
from app.db.session import get_db
from app.schemas.workflows import (
    DistributionCreate, ImpactCreate, ModelArtifactRead, ProvenanceCreate, ReportCreate,
)
from app.services.workflow_service import distribution_metrics, impact_metrics, report_html, report_payload
from app.utils.artifact_storage import get_model_path, save_model_artifact

router = APIRouter()


def _owned_dataset(db: Session, dataset_id: str, user: models.User) -> models.Dataset:
    dataset = db.query(models.Dataset).filter_by(id=dataset_id, owner_user_id=user.id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


@router.post("/model-artifacts", response_model=ModelArtifactRead, status_code=201)
async def upload_model_artifact(
    name: str = Form(...), version: str | None = Form(None),
    expected_sha256: str | None = Form(None),
    metadata: str | None = Form(None), file: UploadFile = File(...),
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user),
):
    content = await file.read()
    storage, sha256, size = save_model_artifact(content, file.filename or "artifact")
    if expected_sha256 and not hmac.compare_digest(expected_sha256.lower(), sha256):
        get_model_path(storage).unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="SHA-256 verification failed")
    try:
        metadata_json = json.loads(metadata) if metadata else None
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="metadata must be valid JSON")
    artifact = models.ModelArtifact(
        owner_user_id=user.id, name=name, version=version,
        original_filename=file.filename or "artifact", storage_filename=storage,
        sha256=sha256, size_bytes=size, metadata_json=metadata_json,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact


@router.get("/model-artifacts/{artifact_id}/verify")
def verify_model_artifact(artifact_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    artifact = db.query(models.ModelArtifact).filter_by(id=artifact_id, owner_user_id=user.id).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Model artifact not found")
    path = get_model_path(artifact.storage_filename)
    if not path.exists():
        return {"artifact_id": artifact.id, "verified": False, "reason": "file_not_found"}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"artifact_id": artifact.id, "verified": digest == artifact.sha256, "sha256": digest}


@router.get("/model-artifacts/{artifact_id}", response_model=ModelArtifactRead)
def get_model_artifact(artifact_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    artifact = db.query(models.ModelArtifact).filter_by(id=artifact_id, owner_user_id=user.id).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Model artifact not found")
    return artifact


@router.get("/model-artifacts", response_model=list[ModelArtifactRead])
def list_model_artifacts(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return db.query(models.ModelArtifact).filter(
        models.ModelArtifact.owner_user_id == user.id
    ).order_by(models.ModelArtifact.created_at.desc()).all()


@router.get("/model-artifacts/{artifact_id}/download")
def download_model_artifact(artifact_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    artifact = db.query(models.ModelArtifact).filter_by(id=artifact_id, owner_user_id=user.id).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Model artifact not found")
    path = get_model_path(artifact.storage_filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return StreamingResponse(path.open("rb"), media_type="application/octet-stream",
                             headers={"Content-Disposition": f'attachment; filename="{artifact.original_filename}"',
                                      "X-Artifact-SHA256": artifact.sha256})


@router.post("/provenance", status_code=201)
def create_provenance(data: ProvenanceCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _owned_dataset(db, data.dataset_id, user)
    record = models.ProvenanceRecord(owner_user_id=user.id, dataset_id=data.dataset_id,
                                     metadata_json=data.metadata, prediction_status="no_prediction")
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "dataset_id": record.dataset_id, "metadata": record.metadata_json,
            "prediction_status": record.prediction_status}


@router.get("/provenance")
def list_provenance(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    records = db.query(models.ProvenanceRecord).filter(
        models.ProvenanceRecord.owner_user_id == user.id
    ).order_by(models.ProvenanceRecord.created_at.desc()).limit(limit).all()
    return [
        {
            "id": item.id,
            "dataset_id": item.dataset_id,
            "metadata": item.metadata_json,
            "prediction_status": item.prediction_status,
            "created_at": item.created_at,
        }
        for item in records
    ]


@router.post("/distribution-comparisons", status_code=201)
def compare_distributions(data: DistributionCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    reference = _owned_dataset(db, data.reference_dataset_id, user)
    comparison = _owned_dataset(db, data.comparison_dataset_id, user)
    try:
        metrics = distribution_metrics(reference, comparison)
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    record = models.DistributionComparison(owner_user_id=user.id, reference_dataset_id=reference.id,
                                           comparison_dataset_id=comparison.id, metrics_json=metrics)
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "reference_dataset_id": reference.id, "comparison_dataset_id": comparison.id, "metrics": metrics}


@router.get("/distribution-comparisons")
def list_distribution_comparisons(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    records = db.query(models.DistributionComparison).filter(
        models.DistributionComparison.owner_user_id == user.id
    ).order_by(models.DistributionComparison.created_at.desc()).limit(limit).all()
    return [
        {
            "id": item.id,
            "reference_dataset_id": item.reference_dataset_id,
            "comparison_dataset_id": item.comparison_dataset_id,
            "metrics": item.metrics_json,
            "created_at": item.created_at,
        }
        for item in records
    ]


@router.post("/impact-metrics", status_code=201)
def create_impact(data: ImpactCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _owned_dataset(db, data.dataset_id, user)
    metrics = impact_metrics(db, data.dataset_id)
    record = models.ImpactMetric(owner_user_id=user.id, dataset_id=data.dataset_id, metrics_json=metrics)
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "dataset_id": data.dataset_id, "metrics": metrics}


@router.get("/impact-metrics/{dataset_id}")
def get_impact(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _owned_dataset(db, dataset_id, user)
    record = db.query(models.ImpactMetric).filter(
        models.ImpactMetric.dataset_id == dataset_id,
        models.ImpactMetric.owner_user_id == user.id,
    ).order_by(models.ImpactMetric.created_at.desc()).first()
    if record is None:
        metrics = impact_metrics(db, dataset_id)
        record = models.ImpactMetric(
            owner_user_id=user.id, dataset_id=dataset_id, metrics_json=metrics
        )
        db.add(record)
        db.commit()
        db.refresh(record)
    return {"id": record.id, "dataset_id": dataset_id, "metrics": record.metrics_json}


@router.post("/reports", status_code=201)
def create_report(data: ReportCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if data.dataset_id:
        _owned_dataset(db, data.dataset_id, user)
    payload = report_payload(db, user.id, data.dataset_id)
    record = models.ReportMetadata(owner_user_id=user.id, dataset_id=data.dataset_id, title=data.title,
                                   format="json", content_json=payload)
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "title": record.title, "format": record.format, "created_at": record.created_at, "content": payload}


@router.get("/reports")
def list_reports(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    records = db.query(models.ReportMetadata).filter(
        models.ReportMetadata.owner_user_id == user.id
    ).order_by(models.ReportMetadata.created_at.desc()).limit(limit).all()
    return [
        {
            "id": item.id,
            "title": item.title,
            "format": item.format,
            "created_at": item.created_at,
            "dataset_id": item.dataset_id,
            "content": item.content_json,
        }
        for item in records
    ]


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(
    report_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    record = db.query(models.ReportMetadata).filter(
        models.ReportMetadata.id == report_id,
        models.ReportMetadata.owner_user_id == user.id,
    ).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Report not found")
    db.delete(record)
    db.commit()


@router.get("/reports/{report_id}/download")
def download_report(report_id: str, format: str = "json", db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    report = db.query(models.ReportMetadata).filter_by(id=report_id, owner_user_id=user.id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if format.lower() == "html":
        body = report_html(report.title, report.content_json).encode("utf-8")
        return Response(body, media_type="text/html", headers={"Content-Disposition": f'attachment; filename="{report.id}.html"'})
    if format.lower() != "json":
        raise HTTPException(status_code=400, detail="format must be json or html")
    body = json.dumps(report.content_json, indent=2, default=str).encode("utf-8")
    return Response(body, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{report.id}.json"'})
