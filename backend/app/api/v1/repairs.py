import hmac
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db import models, leakage_models
from app.db.session import get_db
from app.api.identity import get_current_user
from app.services.activity_service import record_user_event
from app.services.repair_service import (
    generate_combined_exact_duplicate_repair,
    repair_exact_duplicates,
)
from app.services.remediation_service import _response_for_plan
from app.utils.operation_metadata import (
    normalize_operation_metadata,
    normalize_operation_response,
)
from app.utils.file_storage import (
    PROCESSED_DIR,
    QUARANTINE_DIR,
    compute_file_sha256,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_SAFE_OUTPUT_FILENAME = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*\.(?:csv|xlsx)",
    re.IGNORECASE,
)
_OUTPUT_MEDIA_TYPES = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class CombinedRepairPreviewRequest(BaseModel):
    selected_finding_ids: list[str] = Field(min_length=1)


class CombinedRepairRequest(CombinedRepairPreviewRequest):
    preview_token: Optional[str] = None
    confirmed: bool = False


@router.post("/findings/{finding_id}/repair", status_code=status.HTTP_201_CREATED)
def repair_finding(
    finding_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Repair a specific finding by creating a processed version of the dataset
    with the identified issue resolved.
    """
    # In a real implementation, we would extract dataset_id from the finding
    # or require it as a parameter. For now, we'll need to get the finding
    # first to determine which dataset it belongs to.
    finding = db.query(leakage_models.LeakageFinding).join(
        models.Dataset, models.Dataset.id == leakage_models.LeakageFinding.dataset_id
    ).filter(
        leakage_models.LeakageFinding.id == finding_id,
        models.Dataset.owner_user_id == user.id,
    ).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Call the repair service
    try:
        result = normalize_operation_response(
            repair_exact_duplicates(
                dataset_id=finding.dataset_id,
                finding_id=finding_id,
                db=db
            )
        )
    except Exception:
        record_user_event(
            db,
            user_id=user.id,
            dataset_id=finding.dataset_id,
            finding_id=finding_id,
            event_type="repair",
            outcome="failed",
            title="Repair failed",
            message="The repair operation did not complete.",
        )
        raise
    operation_id = result.get("repair_id") or result.get("id")
    record_user_event(
        db,
        user_id=user.id,
        dataset_id=finding.dataset_id,
        finding_id=finding_id,
        operation_id=operation_id,
        event_type="repair",
        outcome="completed",
        title="Repair completed",
        message="An approved repair operation completed.",
        deduplication_key=f"repair:{operation_id}" if operation_id else None,
    )
    return result


@router.post("/datasets/{dataset_id}/repairs", status_code=status.HTTP_201_CREATED)
def repair_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Repair all applicable findings in a dataset.
    Currently processes exact_duplicate findings.
    """
    from app.services.repair_service import repair_exact_duplicates

    # Verify dataset exists
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == user.id,
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
        result = normalize_operation_response(
            repair_exact_duplicates(
                dataset_id=dataset_id,
                finding_id=finding.id,
                db=db
            )
        )
        repair_results.append(result)
        operation_id = result.get("repair_id") or result.get("id")
        record_user_event(
            db,
            user_id=user.id,
            dataset_id=dataset_id,
            finding_id=finding.id,
            operation_id=operation_id,
            event_type="repair",
            outcome="completed",
            title="Repair completed",
            message="An approved repair operation completed.",
            deduplication_key=f"repair:{operation_id}" if operation_id else None,
        )

    return repair_results


@router.post(
    "/datasets/{dataset_id}/repairs/combined/preview",
)
def preview_dataset_combined_repair(
    dataset_id: str,
    request: CombinedRepairPreviewRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Preview selected exact-duplicate cleaning without writing an output."""
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == user.id,
    ).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return generate_combined_exact_duplicate_repair(
        dataset_id=dataset_id,
        selected_finding_ids=request.selected_finding_ids,
        db=db,
        preview_only=True,
    )


@router.post(
    "/datasets/{dataset_id}/repairs/combined",
    status_code=status.HTTP_201_CREATED,
)
def repair_dataset_combined(
    dataset_id: str,
    request: CombinedRepairRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Generate one cleaned copy from user-selected exact-duplicate findings."""
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == user.id,
    ).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if request.confirmed is not True:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Explicit confirmation is required before generating combined cleaned output",
        )
    if not request.preview_token:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="A current combined-cleaning preview token is required",
        )
    try:
        result = generate_combined_exact_duplicate_repair(
            dataset_id=dataset_id,
            selected_finding_ids=request.selected_finding_ids,
            db=db,
            expected_preview_token=request.preview_token,
        )
    except Exception:
        record_user_event(
            db,
            user_id=user.id,
            dataset_id=dataset_id,
            event_type="combined_repair",
            outcome="failed",
            title="Combined repair failed",
            message="The selected findings could not be applied to a cleaned output.",
            details={"selected_finding_ids": request.selected_finding_ids},
        )
        raise
    operation_id = result.get("id")
    record_user_event(
        db,
        user_id=user.id,
        dataset_id=dataset_id,
        operation_id=operation_id,
        event_type="combined_repair",
        outcome="completed",
        title="Combined repair completed",
        message="A cleaned dataset was generated from selected duplicate findings.",
        details={
            "selected_finding_ids": (result.get("operation_metadata") or {}).get(
                "selected_finding_ids", []
            ),
            "applied_finding_ids": (result.get("operation_metadata") or {}).get("applied_finding_ids", []),
            "skipped_findings": (result.get("operation_metadata") or {}).get("skipped_findings", []),
            "duplicate_rows_removed": result.get("affected_rows"),
            "affected_row_indices_preview": (
                result.get("operation_metadata") or {}
            ).get("affected_row_indices_preview", []),
            "affected_row_indices_count": (
                result.get("operation_metadata") or {}
            ).get("affected_row_indices_count", 0),
            "affected_row_indices_sha256": (
                result.get("operation_metadata") or {}
            ).get("affected_row_indices_sha256"),
            "evidence_reference_finding_ids": (
                result.get("operation_metadata") or {}
            ).get("evidence_reference_finding_ids", []),
        },
        deduplication_key=f"combined-repair:{operation_id}" if operation_id else None,
    )
    return normalize_operation_response(result)


@router.get("/repairs/{repair_id}")
def get_repair(
    repair_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Get a specific repair record by its ID.
    """
    repair_record = db.query(models.RepairRecord).filter(
        models.RepairRecord.id == repair_id,
        models.RepairRecord.dataset_id.in_(
            db.query(models.Dataset.id).filter(models.Dataset.owner_user_id == user.id)
        ),
    ).first()
    if not repair_record:
        raise HTTPException(status_code=404, detail="Repair not found")

    # Get the associated dataset for input file information
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == repair_record.dataset_id
    ).first()

    # Convert repair record to the expected format (matching test expectations)
    stored_operation_metadata = repair_record.operation_metadata
    operation_metadata = (
        _response_for_plan(repair_record)["plan"]
        if repair_record.operation_type
        in {"remediation_plan", "consolidated_remediation"}
        else normalize_operation_metadata(stored_operation_metadata)
    )
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
        "original_row_count": (
            stored_operation_metadata.get("original_row_count")
            if isinstance(stored_operation_metadata, dict)
            else getattr(repair_record, 'original_row_count', 0)
        ),
        "processed_row_count": (
            stored_operation_metadata.get("final_row_count")
            if isinstance(stored_operation_metadata, dict)
            else getattr(repair_record, 'processed_row_count', 0)
        ),
        "affected_rows": getattr(repair_record, 'affected_rows', 0),
        "affected_columns": getattr(repair_record, 'affected_columns', []),
        "quarantine_info": getattr(repair_record, 'quarantine_info', None),
        "operation_metadata": operation_metadata,
        "created_at": repair_record.created_at.isoformat() if repair_record.created_at else None,
        "completed_at": repair_record.completed_at.isoformat() if repair_record.completed_at else None
    }


@router.get("/datasets/{dataset_id}/repairs")
def get_dataset_repairs(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Get all repair records for a specific dataset.
    """
    # Verify dataset exists
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == user.id,
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
        stored_operation_metadata = record.operation_metadata
        operation_metadata = (
            _response_for_plan(record)["plan"]
            if record.operation_type
            in {"remediation_plan", "consolidated_remediation"}
            else normalize_operation_metadata(stored_operation_metadata)
        )
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
            "original_row_count": (
                stored_operation_metadata.get("original_row_count")
                if isinstance(stored_operation_metadata, dict)
                else getattr(record, 'original_row_count', 0)
            ),
            "processed_row_count": (
                stored_operation_metadata.get("final_row_count")
                if isinstance(stored_operation_metadata, dict)
                else getattr(record, 'processed_row_count', 0)
            ),
            "affected_rows": getattr(record, 'affected_rows', 0),
            "affected_columns": getattr(record, 'affected_columns', []),
            "quarantine_info": getattr(record, 'quarantine_info', None),
            "operation_metadata": operation_metadata,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None
        })

    return repair_results


@router.get("/operations/{operation_id}/download")
def download_operation_output(
    operation_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Download a completed repair or quarantine output by operation ID."""
    operation = db.query(models.RepairRecord).join(
        models.Dataset,
        models.Dataset.id == models.RepairRecord.dataset_id,
    ).filter(
        models.RepairRecord.id == operation_id,
        models.Dataset.owner_user_id == user.id,
    ).first()
    if operation is None:
        raise HTTPException(status_code=404, detail="Operation not found")

    if not isinstance(operation.status, str) or operation.status.lower() != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Operation output is not available until the operation is completed",
        )

    output_directories = {
        "repair": PROCESSED_DIR,
        "combined_repair": PROCESSED_DIR,
        "consolidated_remediation": PROCESSED_DIR,
        "train_only_imputation": PROCESSED_DIR,
        "quarantine": QUARANTINE_DIR,
    }
    output_directory = output_directories.get(operation.operation_type)
    if output_directory is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Operation type does not support output downloads",
        )

    filename = operation.output_filename
    if (
        not isinstance(filename, str)
        or not _SAFE_OUTPUT_FILENAME.fullmatch(filename)
        or ".." in filename
        or "/" in filename
        or "\\" in filename
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Operation has an invalid output filename",
        )

    try:
        storage_root = output_directory.resolve(strict=True)
        output_path = (storage_root / filename).resolve(strict=True)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Operation output file not found")
    except (OSError, RuntimeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Operation has an invalid output filename",
        )

    try:
        output_path.relative_to(storage_root)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Operation has an invalid output filename",
        )

    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="Operation output file not found")

    expected_sha256 = operation.output_file_sha256
    if expected_sha256 is not None:
        if (
            not isinstance(expected_sha256, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256)
        ):
            logger.error(
                "Invalid stored output hash (operation_id=%s)",
                operation_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Operation output failed SHA-256 integrity verification",
            )
        try:
            actual_sha256 = compute_file_sha256(output_path)
        except OSError:
            logger.error(
                "Unable to verify operation output (operation_id=%s)",
                operation_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to verify operation output integrity",
            )
        if not hmac.compare_digest(actual_sha256, expected_sha256.lower()):
            logger.error(
                "Operation output SHA-256 mismatch (operation_id=%s)",
                operation_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Operation output failed SHA-256 integrity verification",
            )

    media_type = _OUTPUT_MEDIA_TYPES.get(
        output_path.suffix.lower(),
        "application/octet-stream",
    )
    return FileResponse(
        path=output_path,
        media_type=media_type,
        filename=(
            "DataLeakGuard_Final_Cleaned_Dataset.csv"
            if operation.operation_type == "consolidated_remediation"
            else filename
        ),
    )
