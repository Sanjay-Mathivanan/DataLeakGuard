from datetime import datetime, timezone
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
import pandas as pd
from app.db import models, leakage_models, schemas
from app.db.session import get_db
from app.core import dataset_service
from app.core.config import settings
from app.schemas import leakage
from app.services.leakage_detection_service import detect_exact_duplicates, detect_entity_overlap, detect_target_leakage, detect_temporal_leakage, detect_train_test_contamination
from app.utils.file_storage import validate_upload_file
from app.api.identity import get_current_user
from app.services.activity_service import record_user_event

router = APIRouter()


def _mark_analysis_failed(db: Session, dataset_id: str, user_id: str) -> None:
    """Persist failure state without changing the last successful timestamp."""
    try:
        db.rollback()
        dataset = db.query(models.Dataset).filter(
            models.Dataset.id == dataset_id,
            models.Dataset.owner_user_id == user_id,
        ).first()
        if dataset is not None:
            dataset.status = "Analysis failed"
            db.commit()
            record_user_event(
                db,
                user_id=user_id,
                dataset_id=dataset_id,
                event_type="analysis",
                outcome="failed",
                title="Dataset analysis failed",
                message=f"Analysis failed for {dataset.name}.",
                details={"status": "failed"},
            )
    except Exception:
        # Preserve the analysis error if recording status is itself unavailable.
        try:
            db.rollback()
        except Exception:
            pass


from fastapi import Form


async def read_upload_with_limit(file: UploadFile, max_size_bytes: int) -> bytearray:
    """Read an upload in bounded chunks and stop as soon as it exceeds its limit."""
    contents = bytearray()
    while True:
        bytes_remaining = max_size_bytes - len(contents)
        chunk = await file.read(min(1024 * 1024, bytes_remaining + 1))
        if not chunk:
            return contents
        if len(contents) + len(chunk) > max_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size exceeds limit of {max_size_bytes // (1024 * 1024)} MB",
            )
        contents.extend(chunk)


@router.post("/datasets", response_model=schemas.DatasetInDB, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    name: str = Form(...),
    type: str = Form(...),
    format: str = Form(...),
    description: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    max_size_mb = max(0, int(getattr(settings, "MAX_UPLOAD_SIZE_MB", 100)))
    max_size_bytes = max_size_mb * 1024 * 1024

    try:
        # Reject unsupported extensions or type/format mismatches before
        # consuming the uploaded body.
        validate_upload_file(file.filename or "", type, format)
        if file.size is not None and file.size > max_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size exceeds limit of {max_size_mb} MB",
            )
        contents = await read_upload_with_limit(file, max_size_bytes)

        # Call service
        db_dataset = dataset_service.create_dataset_from_upload(
            db=db,
            name=name,
            dataset_type=type,
            format=format,
            description=description,
            file_content=contents,
            original_filename=file.filename,
            owner_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_user_event(
        db,
        user_id=user.id,
        dataset_id=db_dataset.id,
        event_type="dataset_upload",
        outcome="completed",
        title="Dataset uploaded",
        message=f"{db_dataset.name} was uploaded successfully.",
        details={"format": db_dataset.format},
        deduplication_key=f"dataset-upload:{db_dataset.id}",
    )
    return db_dataset


@router.get("/datasets/{dataset_id}/profile", response_model=schemas.DatasetInDB)
def get_dataset_profile(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == user.id,
    ).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


@router.get("/datasets", response_model=List[schemas.DatasetInDB])
def read_datasets(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    datasets = db.query(models.Dataset).filter(
        models.Dataset.owner_user_id == user.id
    ).offset(skip).limit(limit).all()
    return datasets


@router.get("/datasets/{dataset_id}", response_model=schemas.DatasetInDB)
def read_dataset(
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
    return dataset


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return _delete_dataset_owned(dataset_id, db, user.id)


def _delete_dataset_owned(dataset_id: str, db: Session, owner_user_id: str):
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == owner_user_id,
    ).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Findings and repair/quarantine history are retained as audit records.
    # The models do not define cascading deletion for these records, so do not
    # remove their dataset row and leave the records orphaned.
    has_findings = db.query(leakage_models.LeakageFinding.id).filter(
        leakage_models.LeakageFinding.dataset_id == dataset_id
    ).first()
    has_operations = db.query(models.RepairRecord.id).filter(
        models.RepairRecord.dataset_id == dataset_id
    ).first()
    if has_findings or has_operations:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Dataset has persisted findings or repair/quarantine history; "
                "deletion is blocked to preserve audit records and derived outputs"
            ),
        )

    # Deletion currently removes only the database row. Preserve the uploaded
    # original because no documented file-retention/deletion policy exists.
    try:
        db.delete(dataset)
        db.commit()
    except Exception:
        # No files are removed here; rollback keeps the database state intact
        # whenever the failed transaction is still reversible.
        try:
            db.rollback()
        except Exception:
            pass
        raise
    return None


@router.post("/datasets/{dataset_id}/analyze/leakage", response_model=leakage.LeakageAnalysisResponse)
def analyze_leakage(
    dataset_id: str,
    entity_column: Optional[str] = None,
    split_column: Optional[str] = None,
    target_column: Optional[str] = None,
    time_column: Optional[str] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
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
    - split_column only: run exact duplicate + train/test contamination
    - Invalid target_column: return HTTP 400
    - Invalid time_column or split_column: return HTTP 400
    """
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == user.id,
    ).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Validate parameter combinations first
    # Rule 1: If time_column is provided, split_column must be provided
    if time_column is not None and split_column is None:
        _mark_analysis_failed(db, dataset_id, user.id)
        raise HTTPException(
            status_code=400,
            detail="Both time_column and split_column must be provided for temporal leakage detection"
        )
    # Rule 2: If entity_column is provided, split_column must be provided
    if entity_column is not None and split_column is None:
        _mark_analysis_failed(db, dataset_id, user.id)
        raise HTTPException(
            status_code=400,
            detail="Both entity_column and split_column must be provided for entity overlap detection"
        )
    # Note: split_column alone is valid for train/test contamination detection

    try:
        # Run exact duplicate detection. A supplied split column is excluded so
        # otherwise-identical rows in separate partitions can still be found.
        if split_column is not None:
            result = detect_exact_duplicates(
                dataset_id, db, exclude_columns=["id", split_column]
            )
        else:
            result = detect_exact_duplicates(dataset_id, db)
        findings = result["findings"]

        if target_column is not None:
            findings.extend(detect_target_leakage(dataset_id, db, target_column))
            result["findings"] = findings

        if time_column is not None and split_column is not None:
            findings.extend(
                detect_temporal_leakage(dataset_id, db, time_column, split_column)
            )
            result["findings"] = findings

        if entity_column is not None and split_column is not None:
            findings.extend(
                detect_entity_overlap(dataset_id, db, entity_column, split_column)
            )
            result["findings"] = findings

        if split_column is not None:
            findings.extend(
                detect_train_test_contamination(dataset_id, db, split_column)
            )
            result["findings"] = findings

        if target_column is not None or split_column is not None:
            # Persist only observed counts for explicitly configured columns.
            source_path = dataset_service.get_dataset_file_path(dataset)
            if dataset.format.upper() == "CSV":
                analysis_frame = pd.read_csv(source_path, dtype=str)
            elif dataset.format.upper() == "XLSX":
                analysis_frame = pd.read_excel(source_path, dtype=str)
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Configured-column summaries support CSV and XLSX datasets only",
                )
            profile = dict(dataset.profile or {})
            if target_column is not None:
                target_values = analysis_frame[target_column].dropna()
                target_values = target_values[target_values.astype(str).str.strip() != ""]
                counts = target_values.astype(str).value_counts()
                profile["target_column"] = target_column
                profile["target_class_counts"] = {
                    str(label): int(count) for label, count in counts.items()
                }
                dataset.class_count = int(len(counts))
            if split_column is not None:
                split_values = analysis_frame[split_column].dropna()
                split_values = split_values[split_values.astype(str).str.strip() != ""]
                split_counts = split_values.astype(str).value_counts()
                profile["split_column"] = split_column
                profile["split_row_counts"] = {
                    str(label): int(count) for label, count in split_counts.items()
                }
            dataset.profile = profile

        profile = dict(dataset.profile or {})
        profile["analysis_columns"] = {
            "entity_column": entity_column,
            "split_column": split_column,
            "target_column": target_column,
            "time_column": time_column,
        }
        dataset.profile = profile
        dataset.status = "Analyzed"
        dataset.last_analysis = datetime.now(timezone.utc)
        db.add(dataset)
        db.commit()
        result_findings = result.get("findings", [])
        record_user_event(
            db,
            user_id=user.id,
            dataset_id=dataset.id,
            event_type="analysis",
            outcome="completed",
            title="Dataset analysis completed",
            message=f"Analysis completed for {dataset.name}; {len(result_findings)} findings returned.",
            details={
                "finding_count": len(result_findings),
                "columns": profile["analysis_columns"],
            },
            deduplication_key=f"analysis:{dataset.id}:{uuid.uuid4()}",
        )
        return result
    except Exception:
        _mark_analysis_failed(db, dataset_id, user.id)
        raise


@router.get("/datasets/{dataset_id}/findings", response_model=List[leakage.LeakageFindingRead])
def get_dataset_findings(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Return all LeakageFinding records belonging to the dataset.
    """
    # Verify dataset exists
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == user.id,
    ).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    findings = db.query(leakage_models.LeakageFinding).filter(
        leakage_models.LeakageFinding.dataset_id == dataset_id
    ).all()
    return findings
