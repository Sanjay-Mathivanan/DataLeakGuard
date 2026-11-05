from datetime import datetime, timezone
import uuid
from typing import List, Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from sqlalchemy import case, cast, func, or_, String
from sqlalchemy.orm import Session
import pandas as pd
from app.db import models, leakage_models, schemas
from app.db.session import get_db
from app.core import dataset_service
from app.core.config import settings
from app.schemas import leakage
from app.schemas.findings import DatasetFindingPage, FindingCounts
from app.schemas.column_recommendations import ColumnRecommendationsResponse
from app.schemas.profiling import DatasetProfilingRead
from app.schemas.split_strategy import SplitGenerationRequest, SplitGenerationResponse
from app.services.profiling_service import (
    build_dataset_column_metadata,
    profile_tabular_file,
)
from app.services.leakage_detection_service import detect_exact_duplicates, detect_entity_overlap, detect_target_leakage, detect_temporal_leakage, detect_train_test_contamination
from app.services.column_recommendation_service import recommend_columns
from app.services.split_strategy_service import (
    GENERATED_SPLIT_COLUMN,
    generate_split_output,
    load_generated_split_frame,
    read_tabular_frame,
    validate_existing_split,
)
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


def _get_owned_tabular_dataset(
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
    if dataset.type != "tabular" or (dataset.format or "").upper() not in {"CSV", "XLSX"}:
        raise HTTPException(
            status_code=422,
            detail="Detailed profiling is supported for tabular CSV/XLSX datasets only",
        )
    return dataset


def _detailed_profile_view(profile: dict) -> dict:
    """Return the detailed profiler fields without analysis/configuration metadata."""
    keys = {
        "dataset_name",
        "row_count",
        "column_count",
        "file_format",
        "file_size_bytes",
        "memory_usage_bytes",
        "duplicate_row_count",
        "total_missing_values",
        "data_quality",
        "columns",
        "dtypes",
        "column_profiles",
        "category_value_limit",
        "profiled_at",
    }
    return {key: profile[key] for key in keys if key in profile}


def _profiling_response(dataset: models.Dataset) -> DatasetProfilingRead:
    profile = dataset.profile if isinstance(dataset.profile, dict) else {}
    detailed = _detailed_profile_view(profile)
    return DatasetProfilingRead(
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        source_file_sha256=dataset.file_sha256 or "",
        generated_at=str(detailed.get("profiled_at") or ""),
        profile=detailed,
    )


@router.get(
    "/datasets/{dataset_id}/profiling",
    response_model=DatasetProfilingRead,
    tags=["profiling"],
)
def get_detailed_dataset_profiling(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Retrieve the last persisted detailed profile for an owned tabular dataset."""
    dataset = _get_owned_tabular_dataset(dataset_id, db, user)
    if not dataset_service.verify_dataset_integrity(dataset):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The stored source file is missing or no longer matches its registered SHA-256.",
        )
    profile = dataset.profile if isinstance(dataset.profile, dict) else {}
    if not isinstance(profile.get("column_profiles"), list):
        raise HTTPException(
            status_code=404,
            detail="No detailed profile is available; run POST /profiling to generate one.",
        )
    return _profiling_response(dataset)


@router.post(
    "/datasets/{dataset_id}/profiling",
    response_model=DatasetProfilingRead,
    status_code=status.HTTP_201_CREATED,
    tags=["profiling"],
)
def refresh_detailed_dataset_profiling(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Recompute and persist a detailed profile from the immutable uploaded file."""
    dataset = _get_owned_tabular_dataset(dataset_id, db, user)
    if not dataset_service.verify_dataset_integrity(dataset):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The stored source file is missing or no longer matches its registered SHA-256.",
        )
    try:
        source_path = dataset_service.get_dataset_file_path(dataset)
        detailed = profile_tabular_file(source_path, dataset_name=dataset.name)
        previous = dict(dataset.profile or {})
        previous.update(detailed)
        dataset.profile = previous
        dataset.sample_count = detailed["row_count"]
        dataset.feature_count = detailed["column_count"]
        dataset.columns = build_dataset_column_metadata(detailed)
        db.add(dataset)
        db.commit()
        db.refresh(dataset)
    except (FileNotFoundError, OSError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"Could not profile the source dataset: {exc}") from exc

    record_user_event(
        db,
        user_id=user.id,
        dataset_id=dataset.id,
        event_type="dataset_profiling",
        outcome="completed",
        title="Dataset profiling completed",
        message=f"A detailed profile was generated for {dataset.name}.",
        details={
            "row_count": detailed["row_count"],
            "column_count": detailed["column_count"],
            "duplicate_row_count": detailed["duplicate_row_count"],
            "total_missing_values": detailed["total_missing_values"],
            "source_file_sha256": dataset.file_sha256,
        },
        deduplication_key=f"dataset-profiling:{dataset.id}:{detailed['profiled_at']}",
    )
    return _profiling_response(dataset)


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


@router.post(
    "/datasets/{dataset_id}/split-strategies/generate",
    response_model=SplitGenerationResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_dataset_split(
    dataset_id: str,
    request: SplitGenerationRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Create a separate, reproducible split copy for an owned tabular dataset."""
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == user.id,
    ).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    result = generate_split_output(
        dataset=dataset,
        test_ratio=request.test_ratio,
        random_seed=request.random_seed,
        db=db,
    )
    record_user_event(
        db,
        user_id=user.id,
        dataset_id=dataset.id,
        operation_id=result["id"],
        event_type="split_generation",
        outcome="completed",
        title="Train/test split copy generated",
        message=(
            f"A separate row-level split copy was generated for {dataset.name}; "
            "the registered original was not changed."
        ),
        details={
            "strategy": "generated",
            "test_ratio": result["test_ratio"],
            "random_seed": result["random_seed"],
            "algorithm": result["algorithm"],
            "split_column": result["split_column"],
            "split_row_counts": result["split_row_counts"],
            "input_file_sha256": result["input_file_sha256"],
            "output_file_sha256": result["output_file_sha256"],
            "reused": result["reused"],
        },
        deduplication_key=(
            f"split-generation:{result['id']}" if result.get("id") else None
        ),
    )
    return result


@router.post("/datasets/{dataset_id}/analyze/leakage", response_model=leakage.LeakageAnalysisResponse)
def analyze_leakage(
    dataset_id: str,
    entity_column: Optional[str] = None,
    entity_columns: Optional[List[str]] = Query(default=None),
    contamination_key_columns: Optional[List[str]] = Query(default=None),
    split_column: Optional[str] = None,
    target_column: Optional[str] = None,
    time_column: Optional[str] = None,
    temporal_objective: Optional[Literal["future_prediction", "randomized_holdout"]] = None,
    configuration_confirmed: bool = False,
    split_strategy: Optional[Literal["existing", "generated", "none"]] = None,
    split_operation_id: Optional[str] = None,
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

    try:
        if temporal_objective is not None and time_column is None:
            raise HTTPException(
                status_code=422,
                detail="temporal_objective requires time_column",
            )
        resolved_temporal_objective = temporal_objective or "future_prediction"
        configured_contamination_keys: list[str] = []
        if contamination_key_columns is not None:
            configured_contamination_keys = [
                column.strip()
                for column in contamination_key_columns
                if isinstance(column, str) and column.strip()
            ]
            if (
                not configured_contamination_keys
                or len(configured_contamination_keys) != len(contamination_key_columns)
                or len(set(configured_contamination_keys))
                != len(configured_contamination_keys)
            ):
                raise HTTPException(
                    status_code=422,
                    detail="contamination_key_columns must contain unique, non-empty names",
                )
        if entity_column is not None and entity_columns is not None:
            raise HTTPException(
                status_code=422,
                detail="Provide entity_column or entity_columns, not both",
            )
        configured_entity_columns: list[str] = []
        if entity_columns is not None:
            configured_entity_columns = [
                column.strip()
                for column in entity_columns
                if isinstance(column, str) and column.strip()
            ]
            if (
                not configured_entity_columns
                or len(configured_entity_columns) != len(entity_columns)
                or len(set(configured_entity_columns)) != len(configured_entity_columns)
            ):
                raise HTTPException(
                    status_code=422,
                    detail="entity_columns must contain unique, non-empty column names",
                )
        elif entity_column is not None:
            configured_entity_columns = [entity_column]

        legacy_split_request = split_strategy is None
        if (
            legacy_split_request
            and split_column is None
            and (configured_entity_columns or time_column is not None)
        ):
            if configured_entity_columns and time_column is None:
                detail = "Both entity_column and split_column must be provided"
            elif time_column is not None and not configured_entity_columns:
                detail = (
                    "Both time_column and split_column must be provided for "
                    "temporal leakage detection"
                )
            else:
                detail = (
                    "Entity overlap and temporal leakage analysis require a "
                    "verified split column"
                )
            raise HTTPException(
                status_code=400,
                detail=detail,
            )
        # Keep old clients compatible: a legacy split_column means an
        # explicitly selected existing split; requests without it use no-split.
        resolved_strategy = split_strategy or (
            "existing" if split_column is not None else "none"
        )
        if resolved_strategy == "existing":
            if not split_column:
                raise HTTPException(
                    status_code=422,
                    detail="Existing split strategy requires split_column",
                )
            if split_operation_id:
                raise HTTPException(
                    status_code=422,
                    detail="split_operation_id is only valid for generated split strategy",
                )
            source_path = dataset_service.get_dataset_file_path(dataset)
            analysis_frame = read_tabular_frame(source_path, dataset.format)
            if legacy_split_request and split_column not in analysis_frame.columns:
                raise HTTPException(
                    status_code=400,
                    detail=f"Split column '{split_column}' not found in dataset columns",
                )
            split_configuration = validate_existing_split(
                analysis_frame,
                split_column,
                # Earlier API clients allowed rows with unknown split membership;
                # detectors already exclude those rows. The explicit Phase 5
                # strategy remains strict and rejects incomplete assignments.
                allow_missing=legacy_split_request,
            )
            split_configuration.update(
                {"strategy": "existing", "source": "user_confirmed_dataset_column"}
            )
            effective_split_column = split_column
            split_explanation = (
                "The selected existing split column was validated from the registered dataset."
            )
        elif resolved_strategy == "generated":
            if split_column:
                raise HTTPException(
                    status_code=422,
                    detail="Do not provide split_column when using a generated split",
                )
            if not split_operation_id:
                raise HTTPException(
                    status_code=422,
                    detail="Generated split strategy requires split_operation_id",
                )
            analysis_frame, split_configuration = load_generated_split_frame(
                dataset=dataset,
                operation_id=split_operation_id,
                db=db,
            )
            effective_split_column = GENERATED_SPLIT_COLUMN
            split_configuration = {
                **split_configuration,
                "strategy": "generated",
                "split_operation_id": split_operation_id,
            }
            split_explanation = (
                "Analysis uses a verified, separately stored, deterministic row-level split copy."
            )
        else:
            if split_column or split_operation_id:
                raise HTTPException(
                    status_code=422,
                    detail="No-split strategy cannot include split_column or split_operation_id",
                )
            source_path = dataset_service.get_dataset_file_path(dataset)
            analysis_frame = read_tabular_frame(source_path, dataset.format)
            effective_split_column = None
            split_configuration = {
                "strategy": "none",
                "reason": "No split membership was selected or generated.",
            }
            split_explanation = (
                "Train/test contamination, entity overlap, and temporal checks "
                "requiring split membership were not evaluated."
            )

        invalid_contamination_keys = [
            column
            for column in configured_contamination_keys
            if column not in analysis_frame.columns or column == effective_split_column
        ]
        if invalid_contamination_keys:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Contamination comparison key columns must exist and cannot "
                    "be the split column: "
                    + ", ".join(invalid_contamination_keys)
                ),
            )
        if target_column is not None and target_column not in analysis_frame.columns:
            raise HTTPException(
                status_code=400,
                detail=f"Target column '{target_column}' not found in dataset columns",
            )
        if time_column is not None and time_column not in analysis_frame.columns:
            raise HTTPException(
                status_code=400,
                detail=f"Time column '{time_column}' not found in dataset columns",
            )
        invalid_entity_columns = [
            column for column in configured_entity_columns
            if column not in analysis_frame.columns
        ]
        if invalid_entity_columns:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Entity column(s) not found in dataset columns: "
                    + ", ".join(invalid_entity_columns)
                ),
            )

        # Entity and temporal checks are split-dependent. In explicit no-split
        # mode, keep independent checks running and disclose the skipped ones.
        if effective_split_column is None:
            skipped_detectors = [
                "entity_overlap",
                "temporal_leakage",
                "train_test_contamination",
            ]
        else:
            skipped_detectors = []
        if (
            effective_split_column is not None
            and time_column is not None
            and resolved_temporal_objective == "randomized_holdout"
        ):
            skipped_detectors.append("temporal_leakage")

        # Reuse the selected frame so the detectors do not reread the entire
        # dataset separately. The source file remains untouched.
        excluded = ["id", effective_split_column] if effective_split_column else None
        result = detect_exact_duplicates(
            dataset_id,
            db,
            exclude_columns=excluded,
            analysis_frame=analysis_frame,
        )
        findings = result["findings"]

        if target_column is not None:
            findings.extend(
                detect_target_leakage(
                    dataset_id, db, target_column, analysis_frame=analysis_frame
                )
            )
            result["findings"] = findings

        if (
            time_column is not None
            and effective_split_column is not None
            and resolved_temporal_objective == "future_prediction"
        ):
            findings.extend(
                detect_temporal_leakage(
                    dataset_id,
                    db,
                    time_column,
                    effective_split_column,
                    analysis_frame=analysis_frame,
                )
            )
            result["findings"] = findings

        if configured_entity_columns and effective_split_column is not None:
            findings.extend(
                detect_entity_overlap(
                    dataset_id,
                    db,
                    (
                        configured_entity_columns[0]
                        if len(configured_entity_columns) == 1
                        else configured_entity_columns
                    ),
                    effective_split_column,
                    analysis_frame=analysis_frame,
                )
            )
            result["findings"] = findings

        if effective_split_column is not None:
            findings.extend(
                detect_train_test_contamination(
                    dataset_id,
                    db,
                    effective_split_column,
                    analysis_frame=analysis_frame,
                    matching_columns=configured_contamination_keys,
                )
            )
            result["findings"] = findings

        if target_column is not None or effective_split_column is not None:
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
            if effective_split_column is not None:
                split_values = analysis_frame[effective_split_column].dropna()
                split_values = split_values[split_values.astype(str).str.strip() != ""]
                split_counts = split_values.astype(str).value_counts()
                profile["split_column"] = effective_split_column
                profile["split_row_counts"] = {
                    str(label): int(count) for label, count in split_counts.items()
                }
            profile["split_strategy"] = split_configuration
            dataset.profile = profile

        profile = dict(dataset.profile or {})
        if effective_split_column is None:
            profile.pop("split_column", None)
            profile.pop("split_row_counts", None)
        profile["analysis_columns"] = {
            "configuration_confirmed": configuration_confirmed,
            "entity_column": (
                configured_entity_columns[0]
                if len(configured_entity_columns) == 1
                else None
            ),
            "entity_columns": configured_entity_columns,
            "contamination_key_columns": configured_contamination_keys,
            "split_column": effective_split_column,
            "target_column": target_column,
            "time_column": time_column,
            "temporal_objective": (
                resolved_temporal_objective if time_column is not None else None
            ),
        }
        profile["split_strategy"] = split_configuration
        dataset.profile = profile
        dataset.status = "Analyzed"
        dataset.last_analysis = datetime.now(timezone.utc)
        db.add(dataset)
        db.commit()
        result_findings = result.get("findings", [])

        def missing_column_count(column: str | None) -> int:
            if not column or column not in analysis_frame.columns:
                return 0
            values = analysis_frame[column]
            text = values.astype("string").str.strip()
            return int((values.isna() | text.eq("").fillna(False)).sum())

        target_missing_rows = missing_column_count(target_column)
        entity_missing_rows = (
            int(
                analysis_frame[configured_entity_columns]
                .apply(
                    lambda series: (
                        series.isna()
                        | series.astype("string").str.strip().eq("").fillna(False)
                    )
                )
                .any(axis=1)
                .sum()
            )
            if configured_entity_columns
            else 0
        )
        invalid_timestamp_rows = (
            int(
                pd.to_datetime(
                    analysis_frame[time_column], errors="coerce", utc=True
                ).isna().sum()
            )
            if time_column and time_column in analysis_frame.columns
            else 0
        )
        missing_split_rows = missing_column_count(effective_split_column)
        contamination_missing_key_rows = (
            int(
                analysis_frame[configured_contamination_keys]
                .apply(
                    lambda series: (
                        series.isna()
                        | series.astype("string").str.strip().eq("").fillna(False)
                    )
                )
                .any(axis=1)
                .sum()
            )
            if configured_contamination_keys
            else 0
        )
        contamination_matching_fields = (
            configured_contamination_keys
            if configured_contamination_keys
            else [
                column
                for column in analysis_frame.columns
                if column != effective_split_column and column.lower() != "id"
            ]
        )
        detector_applicability = {
            "entity_overlap": (
                {
                    "status": (
                        "review_required"
                        if entity_missing_rows or missing_split_rows
                        else "evaluated"
                    ),
                    "entity_columns": configured_entity_columns,
                    "missing_entity_key_rows": entity_missing_rows,
                    "missing_split_membership_rows": missing_split_rows,
                    "reason": (
                        "Rows with incomplete entity keys or split membership were excluded from grouping."
                        if entity_missing_rows or missing_split_rows
                        else None
                    ),
                }
                if configured_entity_columns and effective_split_column is not None
                else {
                    "status": "skipped" if effective_split_column is None else "requires_configuration",
                    "reason": (
                        "No split strategy is available."
                        if effective_split_column is None
                        else "Select one or more entity columns; no identifier is assumed."
                    ),
                }
            ),
            "target_leakage": (
                {
                    "status": "review_required" if target_missing_rows else "evaluated",
                    "target_column": target_column,
                    "missing_target_rows": target_missing_rows,
                    "reason": (
                        "Rows with missing target values were excluded from target-dependent checks."
                        if target_missing_rows
                        else None
                    ),
                }
                if target_column
                else {"status": "requires_configuration", "reason": "Select a target column."}
            ),
            "temporal_leakage": (
                {
                    "status": (
                        "review_required"
                        if invalid_timestamp_rows or missing_split_rows
                        else "evaluated"
                    ),
                    "time_column": time_column,
                    "split_column": effective_split_column,
                    "invalid_or_missing_timestamp_rows": invalid_timestamp_rows,
                    "missing_split_membership_rows": missing_split_rows,
                    "timestamp_timezone_normalization": "UTC",
                    "reason": (
                        "Invalid timestamps or missing split assignments were excluded from chronology checks."
                        if invalid_timestamp_rows or missing_split_rows
                        else None
                    ),
                }
                if (
                    time_column
                    and effective_split_column is not None
                    and resolved_temporal_objective == "future_prediction"
                )
                else {
                    "status": (
                        "skipped"
                        if effective_split_column is None
                        or (
                            time_column
                            and resolved_temporal_objective == "randomized_holdout"
                        )
                        else "requires_configuration"
                    ),
                    "reason": (
                        "No split strategy is available."
                        if effective_split_column is None
                        else (
                            "Temporal range overlap is not interpreted as leakage for a randomized-holdout objective."
                            if time_column
                            and resolved_temporal_objective == "randomized_holdout"
                            else "Select a timestamp column to evaluate chronology."
                        )
                    ),
                }
            ),
            "train_test_contamination": (
                {
                    "status": (
                        "requires_configuration"
                        if not contamination_matching_fields
                        else "review_required"
                        if missing_split_rows or contamination_missing_key_rows
                        else "evaluated"
                    ),
                    "split_column": effective_split_column,
                    "matching_fields": contamination_matching_fields,
                    "matching_strategy": (
                        "user_configured_key"
                        if configured_contamination_keys
                        else "exact_row_content"
                    ),
                    "missing_split_membership_rows": missing_split_rows,
                    "missing_comparison_key_rows": contamination_missing_key_rows,
                    "reason": (
                        "Select a comparison key; no non-split fields remain for cross-partition comparison."
                        if not contamination_matching_fields
                        else "Rows with missing split membership or configured comparison-key components were excluded from cross-partition comparisons."
                        if missing_split_rows or contamination_missing_key_rows
                        else None
                    ),
                }
                if effective_split_column is not None
                else {
                    "status": "skipped",
                    "reason": "No split membership was selected or generated.",
                }
            ),
        }
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
                "split_strategy": split_configuration,
                "skipped_detectors": skipped_detectors,
                "detector_applicability": detector_applicability,
            },
            deduplication_key=f"analysis:{dataset.id}:{uuid.uuid4()}",
        )
        result["split_strategy"] = resolved_strategy
        result["split_configuration"] = split_configuration
        result["skipped_detectors"] = skipped_detectors
        result["split_explanation"] = split_explanation
        result["analysis_configuration"] = profile["analysis_columns"]
        result["detector_applicability"] = detector_applicability
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


_KNOWN_FINDING_TYPES = {
    "exact_duplicate",
    "entity_overlap",
    "target_leakage",
    "temporal_leakage",
    "train_test_contamination",
}
_STANDARD_SEVERITIES = {"low", "medium", "high"}


def _finding_counts(query) -> FindingCounts:
    """Return aggregate counts for a dataset or the currently matching query."""
    status_value = func.lower(leakage_models.LeakageFinding.status)
    severity_value = func.lower(leakage_models.LeakageFinding.severity)
    row = query.with_entities(
        func.count(leakage_models.LeakageFinding.id).label("total"),
        func.sum(case((status_value == "open", 1), else_=0)).label("open_count"),
        func.sum(case((status_value == "resolved", 1), else_=0)).label("resolved_count"),
        func.sum(case((severity_value == "low", 1), else_=0)).label("low_count"),
        func.sum(case((severity_value == "medium", 1), else_=0)).label("medium_count"),
        func.sum(case((severity_value == "high", 1), else_=0)).label("high_count"),
        func.sum(case((severity_value.notin_(_STANDARD_SEVERITIES), 1), else_=0)).label("other_count"),
    ).one()
    status_rows = query.with_entities(
        status_value.label("status"),
        func.count(leakage_models.LeakageFinding.id),
    ).group_by(status_value).all()
    detector_rows = query.with_entities(
        leakage_models.LeakageFinding.finding_type,
        func.count(leakage_models.LeakageFinding.id),
    ).group_by(leakage_models.LeakageFinding.finding_type).all()
    return FindingCounts(
        total=int(row.total or 0),
        open=int(row.open_count or 0),
        resolved=int(row.resolved_count or 0),
        low=int(row.low_count or 0),
        medium=int(row.medium_count or 0),
        high=int(row.high_count or 0),
        other_severity=int(row.other_count or 0),
        status_counts={str(key): int(count) for key, count in status_rows if key},
        detector_counts={str(key): int(count) for key, count in detector_rows if key},
    )


@router.get(
    "/datasets/{dataset_id}/findings/page",
    response_model=DatasetFindingPage,
    tags=["findings"],
)
def get_dataset_findings_page(
    dataset_id: str,
    skip: int = Query(default=0, ge=0, le=1_000_000),
    limit: int = Query(default=25, ge=1, le=100),
    search: Optional[str] = Query(default=None, max_length=200),
    finding_type: Optional[str] = Query(default=None, max_length=100),
    severity: Optional[str] = Query(default=None, max_length=40),
    finding_status: Optional[str] = Query(default=None, alias="status", max_length=40),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Return a filtered page while preserving the existing array endpoint."""
    dataset = db.query(models.Dataset.id).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == user.id,
    ).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    base_query = db.query(leakage_models.LeakageFinding).filter(
        leakage_models.LeakageFinding.dataset_id == dataset_id
    )
    dataset_summary = _finding_counts(base_query)
    query = base_query

    if finding_type:
        normalized_type = finding_type.strip().lower()
        if normalized_type == "other":
            query = query.filter(
                func.lower(leakage_models.LeakageFinding.finding_type).notin_(
                    _KNOWN_FINDING_TYPES
                )
            )
        else:
            query = query.filter(
                func.lower(leakage_models.LeakageFinding.finding_type)
                == normalized_type
            )
    detector_summary = _finding_counts(query)
    if severity:
        normalized_severity = severity.strip().lower()
        if normalized_severity == "other":
            query = query.filter(
                func.lower(leakage_models.LeakageFinding.severity).notin_(
                    _STANDARD_SEVERITIES
                )
            )
        else:
            query = query.filter(
                func.lower(leakage_models.LeakageFinding.severity)
                == normalized_severity
            )
    if finding_status:
        query = query.filter(
            func.lower(leakage_models.LeakageFinding.status)
            == finding_status.strip().lower()
        )
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                leakage_models.LeakageFinding.id.ilike(pattern),
                leakage_models.LeakageFinding.finding_type.ilike(pattern),
                leakage_models.LeakageFinding.description.ilike(pattern),
                cast(leakage_models.LeakageFinding.evidence, String).ilike(pattern),
            )
        )

    matching_summary = _finding_counts(query)
    items = query.order_by(
        leakage_models.LeakageFinding.created_at.desc(),
        leakage_models.LeakageFinding.id.asc(),
    ).offset(skip).limit(limit).all()
    return DatasetFindingPage(
        items=items,
        total=matching_summary.total,
        skip=skip,
        limit=limit,
        dataset_summary=dataset_summary,
        matching_summary=matching_summary,
        detector_summary=detector_summary,
    )


@router.get(
    "/datasets/{dataset_id}/column-recommendations",
    response_model=ColumnRecommendationsResponse,
    tags=["analysis"],
)
def get_column_recommendations(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Suggest detector-column roles from stored profile metadata only."""
    dataset = db.query(models.Dataset).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == user.id,
    ).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if dataset.type != "tabular" or (dataset.format or "").upper() not in {"CSV", "XLSX"}:
        raise HTTPException(
            status_code=422,
            detail="Column recommendations are supported for tabular CSV/XLSX datasets only",
        )
    return recommend_columns(
        columns=dataset.columns if isinstance(dataset.columns, list) else None,
        row_count=dataset.sample_count,
        preview_rows=dataset.preview_rows if isinstance(dataset.preview_rows, list) else None,
    )
