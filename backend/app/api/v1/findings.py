from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db import leakage_models, models
from app.db.session import get_db
from app.schemas import leakage
from app.services.evidence_service import create_evidence_response
from app.schemas.evidence import EvidenceResponse

router = APIRouter()


@router.get("/findings/{finding_id}", response_model=leakage.LeakageFindingRead)
def get_finding(finding_id: str, db: Session = Depends(get_db)):
    """
    Return one LeakageFinding by its ID.
    """
    finding = db.query(leakage_models.LeakageFinding).filter(
        leakage_models.LeakageFinding.id == finding_id
    ).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


@router.get("/findings/{finding_id}/evidence", response_model=EvidenceResponse)
def get_finding_evidence(finding_id: str, db: Session = Depends(get_db)):
    """
    Return evidence for a specific finding.
    """
    # Get the finding
    finding = db.query(leakage_models.LeakageFinding).filter(
        leakage_models.LeakageFinding.id == finding_id
    ).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Get the associated dataset
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == finding.dataset_id
    ).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Associated dataset not found")

    # Create and return evidence response
    return create_evidence_response(finding, dataset)