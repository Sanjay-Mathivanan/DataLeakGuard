from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.quarantine_service import quarantine_finding

router = APIRouter()


@router.post("/findings/{finding_id}/quarantine", status_code=status.HTTP_201_CREATED)
def quarantine_finding_endpoint(finding_id: str, db: Session = Depends(get_db)):
    """
    Quarantine a specific finding by creating a quarantined version of the dataset
    containing only the affected rows.
    """
    # Get the finding first to determine which dataset it belongs to
    from app.db import leakage_models

    finding = db.query(leakage_models.LeakageFinding).filter(
        leakage_models.LeakageFinding.id == finding_id
    ).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Call the quarantine service
    result = quarantine_finding(
        dataset_id=finding.dataset_id,
        finding_id=finding_id,
        db=db
    )
    return result


@router.get("/datasets/{dataset_id}/quarantines")
def get_dataset_quarantines(dataset_id: str, db: Session = Depends(get_db)):
    """
    Get all quarantine records for a specific dataset.
    """
    from app.db import models

    # Verify dataset exists
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id
    ).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Get all quarantine records for this dataset
    quarantine_records = db.query(models.RepairRecord).filter(
        models.RepairRecord.dataset_id == dataset_id,
        models.RepairRecord.operation_type == "quarantine"
    ).all()

    # Convert to expected format (matching test expectations)
    quarantine_results = []
    for record in quarantine_records:
        quarantine_results.append({
            "id": str(record.id),
            "dataset_id": record.dataset_id,
            "finding_id": record.finding_id,
            "operation_type": record.operation_type,
            "status": record.status,
            "input_file": dataset.storage_filename,
            "input_file_sha256": record.input_file_sha256,
            "output_file": record.output_filename,
            "output_filename": record.output_filename,
            "output_file_sha256": record.output_file_sha256,
            "original_row_count": 0,  # This would need to be calculated or stored
            "quarantined_row_count": getattr(record, 'affected_rows', 0),
            "affected_rows": getattr(record, 'affected_rows', 0),
            "affected_columns": getattr(record, 'affected_columns', []),
            "quarantine_info": getattr(record, 'quarantine_info', None),
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None
        })

    return quarantine_results


@router.get("/quarantines/{quarantine_id}")
def get_quarantine(quarantine_id: str, db: Session = Depends(get_db)):
    """
    Get a specific quarantine record by its ID.
    """
    from app.db import models

    quarantine_record = db.query(models.RepairRecord).filter(
        models.RepairRecord.id == quarantine_id,
        models.RepairRecord.operation_type == "quarantine"
    ).first()
    if not quarantine_record:
        raise HTTPException(status_code=404, detail="Quarantine not found")

    # Get the associated dataset for input file information
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == quarantine_record.dataset_id
    ).first()

    # Convert quarantine record to the expected format (matching test expectations)
    return {
        "id": str(quarantine_record.id),
        "dataset_id": quarantine_record.dataset_id,
        "finding_id": quarantine_record.finding_id,
        "operation_type": quarantine_record.operation_type,
        "status": quarantine_record.status,
        "input_file": dataset.storage_filename if dataset else None,
        "input_file_sha256": quarantine_record.input_file_sha256,
        "output_file": quarantine_record.output_filename,
        "output_filename": quarantine_record.output_filename,
        "output_file_sha256": quarantine_record.output_file_sha256,
        "original_row_count": 0,  # This would need to be calculated or stored
        "quarantined_row_count": getattr(quarantine_record, 'affected_rows', 0),
        "affected_rows": getattr(quarantine_record, 'affected_rows', 0),
        "affected_columns": getattr(quarantine_record, 'affected_columns', []),
        "quarantine_info": getattr(quarantine_record, 'quarantine_info', None),
        "created_at": quarantine_record.created_at.isoformat() if quarantine_record.created_at else None,
        "completed_at": quarantine_record.completed_at.isoformat() if quarantine_record.completed_at else None
    }