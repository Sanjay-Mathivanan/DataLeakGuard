from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from app.db import models, leakage_models, schemas
from app.db.session import get_db
from app.core import dataset_service
from app.schemas import leakage
from app.services.leakage_detection_service import detect_exact_duplicates, detect_entity_overlap, detect_target_leakage, detect_temporal_leakage, detect_train_test_contamination

router = APIRouter()


from fastapi import Form

@router.post("/datasets", response_model=schemas.DatasetInDB, status_code=status.HTTP_201_CREATED)
def create_dataset(
    name: str = Form(...),
    type: str = Form(...),
    format: str = Form(...),
    description: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # Read file content
    contents = file.file.read()
    try:
        # Call service
        db_dataset = dataset_service.create_dataset_from_upload(
            db=db,
            name=name,
            dataset_type=type,
            format=format,
            description=description,
            file_content=contents,
            original_filename=file.filename
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return db_dataset


@router.get("/datasets/{dataset_id}/profile", response_model=schemas.DatasetInDB)
def get_dataset_profile(dataset_id: str, db: Session = Depends(get_db)):
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


@router.get("/datasets", response_model=List[schemas.DatasetInDB])
def read_datasets(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    datasets = db.query(models.Dataset).offset(skip).limit(limit).all()
    return datasets


@router.get("/datasets/{dataset_id}", response_model=schemas.DatasetInDB)
def read_dataset(dataset_id: str, db: Session = Depends(get_db)):
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: str, db: Session = Depends(get_db)):
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    db.delete(dataset)
    db.commit()
    return None


@router.post("/datasets/{dataset_id}/analyze/leakage", response_model=leakage.LeakageAnalysisResponse)
def analyze_leakage(
    dataset_id: str,
    entity_column: Optional[str] = None,
    split_column: Optional[str] = None,
    target_column: Optional[str] = None,
    time_column: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Run leakage analysis for the specified dataset.
    Behavior:
    - No optional parameters: run exact duplicate detection only (Step 3.1 behavior)
    - entity_column + split_column: run exact duplicate + entity overlap (Step 3.2 behavior)
    - target_column only: run exact duplicate + target leakage
    - target_column + entity_column + split_column: run exact duplicate + entity overlap + target leakage
    - time_column + split_column: run exact duplicate + temporal leakage
    - target_column + time_column + split_column: run exact duplicate + target leakage + temporal leakage
    - target_column + entity_column + split_column + time_column: run exact duplicate + target leakage + entity overlap + temporal leakage
    - Only entity_column or only split_column: return HTTP 400
    - Only time_column: return HTTP 400
    - Only split_column: return HTTP 400
    - Invalid target_column: return HTTP 400
    - Invalid time_column or split_column: return HTTP 400
    """
    with open("debug_api.txt", "a") as f:
        f.write(f"DEBUG: analyze_leakage called with dataset_id={dataset_id}, entity_column={entity_column}, split_column={split_column}, target_column={target_column}, time_column={time_column}\\n")
    # Validate parameter combinations first
    # Rule 1: If time_column is provided, split_column must be provided
    if time_column is not None and split_column is None:
        raise HTTPException(
            status_code=400,
            detail="Both time_column and split_column must be provided for temporal leakage detection"
        )
    # Rule 2: If entity_column is provided, split_column must be provided
    if entity_column is not None and split_column is None:
        raise HTTPException(
            status_code=400,
            detail="Both entity_column and split_column must be provided for entity overlap detection"
        )
    # Note: split_column alone is valid for train/test contamination detection

    # Run exact duplicate detection
    # Exclude ID column (surrogate key) and split_column when checking for duplicates
    # (we want to detect when the same data appears in different splits)
    if split_column is not None:
        result = detect_exact_duplicates(dataset_id, db, exclude_columns=['id', split_column])
    else:
        result = detect_exact_duplicates(dataset_id, db)
    findings = result['findings']
    print(f"DEBUG: After exact_duplicates, findings count: {len(findings)}")
    if findings:
        print(f"DEBUG: After exact_duplicates, finding types: {[f.get('finding_type') for f in findings]}")

    # Handle target_column parameter
    if target_column is not None:
        # Validate that target_column exists (will raise HTTPException if not)
        target_findings = detect_target_leakage(dataset_id, db, target_column)
        print(f"DEBUG: target_leakage returned {len(target_findings)} findings")
        findings.extend(target_findings)
        result['findings'] = findings
        print(f"DEBUG: After target_leakage, findings count: {len(findings)}")
        if findings:
            print(f"DEBUG: After target_leakage, finding types: {[f.get('finding_type') for f in findings]}")

    # Handle temporal leakage parameters
    if time_column is not None and split_column is not None:
        # Both provided, run temporal leakage detection
        print(f"DEBUG: About to call detect_temporal_leakage with dataset_id={dataset_id}, time_column={time_column}, split_column={split_column}")
        temporal_findings = detect_temporal_leakage(dataset_id, db, time_column, split_column)
        print(f"DEBUG: detect_temporal_leakage returned {len(temporal_findings)} findings")
        findings.extend(temporal_findings)
        result['findings'] = findings
        print(f"DEBUG: After temporal_leakage, findings count: {len(findings)}")
        if findings:
            print(f"DEBUG: After temporal_leakage, finding types: {[f.get('finding_type') for f in findings]}")

    # Handle entity_column and split_column parameters
    if entity_column is not None and split_column is not None:
        # Both provided, run entity overlap detection
        entity_findings = detect_entity_overlap(dataset_id, db, entity_column, split_column)
        findings.extend(entity_findings)
        result['findings'] = findings
        print(f"DEBUG: After entity_overlap, findings count: {len(findings)}")
        if findings:
            print(f"DEBUG: After entity_overlap, finding types: {[f.get('finding_type') for f in findings]}")
    # If none provided for entity/split, do nothing (findings already contain exact duplicates and/or target leakage and/or temporal leakage)

    # Handle train/test contamination parameters
    if split_column is not None:
        # Provided, run train/test contamination detection
        contamination_findings = detect_train_test_contamination(dataset_id, db, split_column)
        findings.extend(contamination_findings)
        result['findings'] = findings
        print(f"DEBUG: After train/test_contamination, findings count: {len(findings)}")
        if findings:
            print(f"DEBUG: After train/test_contamination, finding types: {[f.get('finding_type') for f in findings]}")

    print(f"DEBUG: Final findings count: {len(findings)}")
    if findings:
        print(f"DEBUG: Final finding types: {[f.get('finding_type') for f in findings]}")
    return result


@router.get("/datasets/{dataset_id}/findings", response_model=List[leakage.LeakageFindingRead])
def get_dataset_findings(dataset_id: str, db: Session = Depends(get_db)):
    """
    Return all LeakageFinding records belonging to the dataset.
    """
    # Verify dataset exists
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    findings = db.query(leakage_models.LeakageFinding).filter(
        leakage_models.LeakageFinding.dataset_id == dataset_id
    ).all()
    return findings