from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db import leakage_models
from app.db.session import get_db
from app.schemas import leakage

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