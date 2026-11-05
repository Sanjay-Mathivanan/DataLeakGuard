"""Explicit train-only imputation for separate model-ready CSV copies."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core import dataset_service
from app.db import models
from app.schemas.preprocessing import ImputationPreviewRequest
from app.services.activity_service import record_user_event
from app.services.split_strategy_service import (
    GENERATED_SPLIT_COLUMN,
    load_generated_split_frame,
    read_tabular_frame,
)
from app.utils.file_storage import PROCESSED_DIR, compute_file_sha256


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_missing(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.isna() | text.eq("").fillna(False)


def _count_missing(frame: pd.DataFrame, columns: list[str] | None = None) -> dict[str, int]:
    selected = columns if columns is not None else list(frame.columns)
    return {
        column: int(_is_missing(frame[column]).sum())
        for column in selected
        if column in frame.columns
    }


def _series_equal(left: pd.Series, right: pd.Series) -> bool:
    """Compare CSV-backed values while normalizing pandas' missing sentinels."""
    return left.reset_index(drop=True).astype("string").equals(
        right.reset_index(drop=True).astype("string")
    )


def _read_profile_columns(dataset: models.Dataset) -> tuple[set[str], dict[str, Any]]:
    profile = dataset.profile if isinstance(dataset.profile, dict) else {}
    analysis = profile.get("analysis_columns")
    analysis = analysis if isinstance(analysis, dict) else {}
    protected: set[str] = set()
    for role in ("target_column", "split_column", "time_column", "timestamp_column", "entity_column"):
        value = analysis.get(role) or profile.get(role)
        if isinstance(value, str) and value:
            protected.add(value)
    entity_columns = analysis.get("entity_columns")
    if isinstance(entity_columns, list):
        protected.update(
            value for value in entity_columns if isinstance(value, str) and value
        )
    contamination_columns = analysis.get("contamination_key_columns")
    if isinstance(contamination_columns, list):
        protected.update(
            value for value in contamination_columns if isinstance(value, str) and value
        )
    snapshot = {
        key: value
        for key, value in analysis.items()
        if key in {
            "configuration_confirmed",
            "target_column",
            "entity_column",
            "entity_columns",
            "contamination_key_columns",
            "split_column",
            "time_column",
            "temporal_objective",
        }
        and (
            isinstance(value, (str, int, float, bool, type(None)))
            or isinstance(value, list)
        )
    }
    if not snapshot:
        snapshot = {
            key: profile[key]
            for key in (
                "target_column",
                "entity_column",
                "entity_columns",
                "contamination_key_columns",
                "split_column",
                "time_column",
                "timestamp_column",
                "temporal_objective",
            )
            if profile.get(key) is not None
        }
    return protected, snapshot


def _read_working_frame(
    *,
    dataset: models.Dataset,
    request: ImputationPreviewRequest,
    db: Session,
) -> tuple[pd.DataFrame, str, dict[str, Any]]:
    try:
        source_path = dataset_service.get_dataset_file_path(dataset)
        source_hash = compute_file_sha256(source_path)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The registered source dataset is not available",
        ) from exc

    if request.split_operation_id:
        if request.split_column != GENERATED_SPLIT_COLUMN:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Generated-split imputation must use the verified generated split column",
            )
        frame, split_configuration = load_generated_split_frame(
            dataset=dataset,
            operation_id=request.split_operation_id,
            db=db,
        )
        return frame, source_hash, {
            "strategy": "generated",
            "split_operation_id": request.split_operation_id,
            "split_configuration": split_configuration,
        }
    return read_tabular_frame(source_path, dataset.format), source_hash, {
        "strategy": "existing",
        "split_operation_id": None,
        "split_configuration": None,
    }


def _fit_strategy(
    frame: pd.DataFrame,
    *,
    column: str,
    method: str,
    constant_value: Any,
    train_mask: pd.Series,
) -> dict[str, Any]:
    values = frame.loc[train_mask, column]
    observed = values.loc[~_is_missing(values)]
    fitted_value: str | float | None
    if method == "leave_missing":
        fitted_value = None
    elif method == "constant":
        fitted_value = str(constant_value)
    elif method in {"mean", "median"}:
        numeric = pd.to_numeric(observed, errors="coerce")
        if observed.empty or numeric.isna().any():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{method} imputation requires observed numeric training values in '{column}'",
            )
        number = float(numeric.mean() if method == "mean" else numeric.median())
        if not math.isfinite(number):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not fit a finite {method} value for '{column}'",
            )
        # String form matches the application's dtype-preserving CSV readers.
        fitted_value = format(number, ".17g")
    elif method == "mode":
        if observed.empty:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Mode imputation requires an observed training value in '{column}'",
            )
        counts = observed.astype("string").value_counts(dropna=True)
        max_count = int(counts.max())
        fitted_value = sorted(
            str(value) for value, count in counts.items() if int(count) == max_count
        )[0]
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported imputation method '{method}'",
        )

    return {
        "column": column,
        "method": method,
        "fitted_value": fitted_value,
        "fit_partition": "training_partition_only",
        "training_observed_count": int(len(observed)),
        "training_missing_count": int(_is_missing(values).sum()),
        "source_missing_count": int(_is_missing(frame[column]).sum()),
    }


def _build_imputation_plan(
    *,
    dataset: models.Dataset,
    request: ImputationPreviewRequest,
    db: Session,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame, source_hash, split_provenance = _read_working_frame(
        dataset=dataset,
        request=request,
        db=db,
    )
    if request.split_column not in frame.columns:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Selected split column '{request.split_column}' does not exist in the working dataset",
        )
    split_values = frame[request.split_column].astype("string").str.strip()
    missing_split = split_values.isna() | split_values.eq("").fillna(False)
    if missing_split.any():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Train-only imputation requires complete split membership; "
                f"{int(missing_split.sum())} rows have missing membership"
            ),
        )
    normalized_train = request.training_partition.strip().casefold()
    train_mask = split_values.str.casefold().eq(normalized_train).fillna(False)
    if not train_mask.any():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The configured training partition has no rows",
        )

    protected_columns, confirmed_configuration = _read_profile_columns(dataset)
    protected_columns.add(request.split_column)
    requested_columns = [item.column for item in request.columns]
    missing_columns = [column for column in requested_columns if column not in frame.columns]
    if missing_columns:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected imputation columns do not exist: " + ", ".join(missing_columns),
        )
    protected_selection = sorted(set(requested_columns).intersection(protected_columns))
    if protected_selection:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Do not impute configured target, entity, timestamp, or split columns: "
                + ", ".join(protected_selection)
            ),
        )

    strategy_rows = [
        _fit_strategy(
            frame,
            column=item.column,
            method=item.method,
            constant_value=item.constant_value,
            train_mask=train_mask,
        )
        for item in request.columns
    ]
    output = frame.copy()
    affected_row_mask = pd.Series(False, index=output.index, dtype=bool)
    imputed_cell_count = 0
    for strategy in strategy_rows:
        column = strategy["column"]
        if strategy["method"] == "leave_missing":
            continue
        missing_mask = _is_missing(output[column])
        output.loc[missing_mask, column] = strategy["fitted_value"]
        filled_mask = missing_mask & ~_is_missing(output[column])
        affected_row_mask |= filled_mask
        imputed_cell_count += int(filled_mask.sum())

    missing_before = _count_missing(frame, requested_columns)
    missing_after = _count_missing(output, requested_columns)
    plan = {
        "version": 1,
        "dataset_id": str(dataset.id),
        "source_file_sha256": source_hash,
        "working_split_provenance": split_provenance,
        "split_column": request.split_column,
        "training_partition": request.training_partition.strip(),
        "fit_row_count": int(train_mask.sum()),
        "strategies": strategy_rows,
        "missing_counts_before": missing_before,
        "missing_counts_after": missing_after,
        "affected_row_count": int(affected_row_mask.sum()),
        "imputed_cell_count": imputed_cell_count,
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "protected_columns": sorted(protected_columns),
        "confirmed_analysis_configuration": confirmed_configuration,
    }
    plan["preview_token"] = _sha256_json(plan)
    return output, plan


def preview_train_only_imputation(
    *,
    dataset: models.Dataset,
    request: ImputationPreviewRequest,
    db: Session,
) -> dict[str, Any]:
    _, plan = _build_imputation_plan(dataset=dataset, request=request, db=db)
    return {
        "preview_token": plan["preview_token"],
        "source_file_sha256": plan["source_file_sha256"],
        "split_column": plan["split_column"],
        "training_partition": plan["training_partition"],
        "fit_row_count": plan["fit_row_count"],
        "strategies": plan["strategies"],
        "missing_counts_before": plan["missing_counts_before"],
        "missing_counts_after": plan["missing_counts_after"],
        "expected_row_count": plan["row_count"],
        "expected_column_count": plan["column_count"],
        "protected_columns": plan["protected_columns"],
        "confirmation_required": True,
    }


def _operation_response(record: models.RepairRecord) -> dict[str, Any]:
    metadata = record.operation_metadata if isinstance(record.operation_metadata, dict) else {}
    return {
        "id": str(record.id),
        "dataset_id": record.dataset_id,
        "operation_type": record.operation_type,
        "status": record.status,
        "output_filename": record.output_filename,
        "input_file_sha256": record.input_file_sha256,
        "output_file_sha256": record.output_file_sha256,
        "affected_rows": record.affected_rows,
        "affected_columns": record.affected_columns or [],
        "operation_metadata": metadata,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


def execute_train_only_imputation(
    *,
    dataset: models.Dataset,
    request: ImputationPreviewRequest,
    preview_token: str,
    confirmed: bool,
    db: Session,
    user: models.User,
) -> dict[str, Any]:
    if not confirmed:
        raise HTTPException(
            status_code=428,
            detail="Explicit confirmation is required before generating the imputed copy",
        )
    output, plan = _build_imputation_plan(dataset=dataset, request=request, db=db)
    if not hmac.compare_digest(plan["preview_token"], preview_token):
        raise HTTPException(
            status_code=409,
            detail="Imputation preview is stale; review the current preview before execution",
        )

    for record in (
        db.query(models.RepairRecord)
        .filter(
            models.RepairRecord.dataset_id == dataset.id,
            models.RepairRecord.operation_type == "train_only_imputation",
            models.RepairRecord.status == "completed",
        )
        .all()
    ):
        metadata = record.operation_metadata
        if (
            isinstance(metadata, dict)
            and metadata.get("preview_token") == preview_token
            and record.output_filename
            and record.output_file_sha256
        ):
            output_path = PROCESSED_DIR / record.output_filename
            if (
                output_path.is_file()
                and compute_file_sha256(output_path) == record.output_file_sha256
            ):
                return _operation_response(record)

    operation_id = str(uuid.uuid4())
    output_filename = f"dlg_imputed_{operation_id}.csv"
    output_path = PROCESSED_DIR / output_filename
    record = models.RepairRecord(
        id=operation_id,
        dataset_id=dataset.id,
        finding_id=None,
        operation_type="train_only_imputation",
        status="processing",
        input_file_sha256=plan["source_file_sha256"],
        output_filename=output_filename,
        affected_rows=plan["affected_row_count"],
        affected_columns=[strategy["column"] for strategy in plan["strategies"]],
        operation_metadata={
            **plan,
            "execution_status": "processing",
            "user_confirmation": True,
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.add(record)
    db.commit()

    output_created = False
    try:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8", newline="") as output_file:
            output_created = True
            output.to_csv(output_file, index=False)
        output_hash = compute_file_sha256(output_path)
        verified_output = pd.read_csv(output_path, dtype=str)
        source_path = dataset_service.get_dataset_file_path(dataset)
        checks = {
            "source_hash_unchanged": compute_file_sha256(source_path) == plan["source_file_sha256"],
            "output_hash_matches_readback": compute_file_sha256(output_path) == output_hash,
            "output_round_trip_matches": verified_output.equals(output.reset_index(drop=True)),
            "row_count_preserved": len(verified_output) == plan["row_count"],
            "column_names_and_order_preserved": list(verified_output.columns) == list(output.columns),
            "split_values_preserved": _series_equal(
                verified_output[request.split_column],
                output[request.split_column],
            ),
            "selected_missing_counts_match_preview": _count_missing(
                verified_output, [item["column"] for item in plan["strategies"]]
            ) == plan["missing_counts_after"],
        }
        # Protected columns are compared directly with the source frame used
        # to produce this preview; no imputation is permitted on those columns.
        original_working_frame, _, _ = _read_working_frame(
            dataset=dataset,
            request=request,
            db=db,
        )
        protected = [column for column in plan["protected_columns"] if column in output.columns]
        checks["protected_columns_preserved"] = all(
            _series_equal(
                verified_output[column],
                original_working_frame[column],
            )
            for column in protected
        )
        verification = {
            "status": "verified" if all(checks.values()) else "failed",
            "checks": {
                key: {"status": "passed" if passed else "failed"}
                for key, passed in checks.items()
            },
            "checks_passed": sum(checks.values()),
            "checks_failed": sum(not passed for passed in checks.values()),
            "checks_skipped": 0,
        }
        final_metadata = {
            **plan,
            "execution_status": "completed" if verification["status"] == "verified" else "failed",
            "final_file_sha256": output_hash,
            "final_row_count": len(verified_output),
            "final_column_count": len(verified_output.columns),
            "imputed_cell_count": plan["imputed_cell_count"],
            "missing_counts_after": _count_missing(
                verified_output, [item["column"] for item in plan["strategies"]]
            ),
            "verification": verification,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        record.operation_metadata = final_metadata
        record.output_file_sha256 = output_hash
        record.status = "completed" if verification["status"] == "verified" else "failed"
        record.completed_at = datetime.now(timezone.utc)
        record.error_info = None if record.status == "completed" else {
            "message": "One or more imputation postconditions failed",
            "verification": verification,
        }
        db.add(record)
        record_user_event(
            db,
            user_id=user.id,
            dataset_id=dataset.id,
            operation_id=operation_id,
            event_type="preprocessing",
            outcome=record.status,
            title="Train-only imputation completed" if record.status == "completed" else "Train-only imputation failed",
            message="A separate train-fitted imputation output was generated and verified."
            if record.status == "completed"
            else "The imputation output failed one or more verification checks.",
            details={
                "preview_token": preview_token,
                "training_partition": plan["training_partition"],
                "split_column": plan["split_column"],
                "verification": verification,
            },
            deduplication_key=f"train-only-imputation:{operation_id}",
        )
        db.commit()
        if record.status != "completed":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Imputation output did not pass post-operation verification",
            )
        return _operation_response(record)
    except Exception as exc:
        if output_created and output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                # Preserve the execution error; failed records cannot be downloaded.
                pass
        db.rollback()
        record.status = "failed"
        record.completed_at = datetime.now(timezone.utc)
        record.error_info = {"message": "Imputation execution or verification failed"}
        metadata = dict(record.operation_metadata or {})
        metadata["execution_status"] = "failed"
        record.operation_metadata = metadata
        db.add(record)
        db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Train-only imputation failed; no verified output is available",
        ) from exc
