from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.repair_service import repair_exact_duplicates

router = APIRouter()


@router.post("/findings/{finding_id}/repair", status_code=status.HTTP_201_CREATED)
def repair_finding(finding_id: str, db: Session = Depends(get_db)):
    """
    Repair a specific finding by creating a processed version of the dataset
    with the identified issue resolved.
    """
    # In a real implementation, we would extract dataset_id from the finding
    # or require it as a parameter. For now, we'll need to get the finding
    # first to determine which dataset it belongs to.
    from app.db import leakage_models

    finding = db.query(leakage_models.LeakageFinding).filter(
        leakage_models.LeakageFinding.id == finding_id
    ).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Call the repair service
    result = repair_exact_duplicates(
        dataset_id=finding.dataset_id,
        finding_id=finding_id,
        db=db
    )
    return result


@router.post("/datasets/{dataset_id}/repairs", status_code=status.HTTP_201_CREATED)
def repair_dataset(dataset_id: str, db: Session = Depends(get_db)):
    """
    Repair all applicable findings in a dataset.
    Currently processes exact_duplicate findings.
    """
    from app.db import leakage_models, models
    from app.services.repair_service import repair_exact_duplicates

    # Verify dataset exists
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id
    ).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Find all exact duplicate findings for this dataset
    findings = db.query(leakage_models.LeakageFinding).filter(
        leakage_models.LeakageFinding.dataset_id == dataset_id,
        leakage_models.LeakageFinding.finding_type == "exact_duplicate",
        leakage_models.LeakageFinding.status == "open"
    ).all()

    # Process each finding
    repair_results = []
    for finding in findings:
        result = repair_exact_duplicates(
            dataset_id=dataset_id,
            finding_id=finding.id,
            db=db
        )
        repair_results.append(result)

    return repair_results


@router.get("/repairs/{repair_id}")
def get_repair(repair_id: str, db: Session = Depends(get_db)):
    """
    Get a specific repair record by its ID.
    """
    from app.db import models

    repair_record = db.query(models.RepairRecord).filter(
        models.RepairRecord.id == repair_id
    ).first()
    if not repair_record:
        raise HTTPException(status_code=404, detail="Repair not found")

    # Get the associated dataset for input file information
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == repair_record.dataset_id
    ).first()

    # Convert repair record to the expected format (matching test expectations)
    return {
        "id": str(repair_record.id),
        "dataset_id": repair_record.dataset_id,
        "finding_id": repair_record.finding_id,
        "operation_type": repair_record.operation_type,
        "status": repair_record.status,
        "input_file": dataset.storage_filename if dataset else None,
        "input_file_sha256": repair_record.input_file_sha256,
        "output_file": repair_record.output_filename,
        "output_filename": repair_record.output_filename,
        "output_file_sha256": repair_record.output_file_sha256,
        "original_row_count": getattr(repair_record, 'original_row_count', 0),
        "processed_row_count": getattr(repair_record, 'processed_row_count', 0),
        "affected_rows": getattr(repair_record, 'affected_rows', 0),
        "affected_columns": getattr(repair_record, 'affected_columns', []),
        "quarantine_info": getattr(repair_record, 'quarantine_info', None),
        "created_at": repair_record.created_at.isoformat() if repair_record.created_at else None,
        "completed_at": repair_record.completed_at.isoformat() if repair_record.completed_at else None
    }


@router.get("/datasets/{dataset_id}/repairs")
def get_dataset_repairs(dataset_id: str, db: Session = Depends(get_db)):
    """
    Get all repair records for a specific dataset.
    """
    from app.db import models

    # Verify dataset exists
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id
    ).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Get all repair records for this dataset
    repair_records = db.query(models.RepairRecord).filter(
        models.RepairRecord.dataset_id == dataset_id
    ).all()

    # Convert to expected format (matching test expectations)
    repair_results = []
    for record in repair_records:
        repair_results.append({
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
            "original_row_count": getattr(record, 'original_row_count', 0),
            "processed_row_count": getattr(record, 'processed_row_count', 0),
            "affected_rows": getattr(record, 'affected_rows', 0),
            "affected_columns": getattr(record, 'affected_columns', []),
            "quarantine_info": getattr(record, 'quarantine_info', None),
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None
        })

    return repair_results