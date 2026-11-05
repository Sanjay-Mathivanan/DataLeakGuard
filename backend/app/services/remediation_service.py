"""Evidence-validated, reproducible remediation plans for tabular datasets.

Plans are persisted in the existing RepairRecord table. Every transformation
is applied to an in-memory copy of the registered source and writes new
artifacts; the uploaded original is never opened for writing.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import leakage_models, models
from app.schemas.remediation import RemediationActionRequest
from app.utils.file_storage import (
    ORIGINAL_DIR,
    PROCESSED_DIR,
    compute_file_sha256,
)
from app.utils.row_hashing import hash_row


_ROW_REFERENCE_LIMIT = 200
_KNOWN_FINDING_TYPES = {
    "exact_duplicate",
    "entity_overlap",
    "target_leakage",
    "temporal_leakage",
    "train_test_contamination",
}
_ACTION_FINDING_TYPES = {
    "exact_duplicate_keep_first": {"exact_duplicate"},
    "rebuild_group_split": {"entity_overlap"},
    "exclude_target_features": {"target_leakage"},
    "rebuild_chronological_split": {"temporal_leakage"},
    "exclude_contaminated_copies": {"train_test_contamination"},
    "quarantine_evidenced_rows": {
        "exact_duplicate",
        "entity_overlap",
        "train_test_contamination",
    },
}


def _http_error(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _source_row_identity(source_hash: str, source_position: int) -> str:
    """Create an identity that remains stable across row filtering/reordering."""
    return _sha256_json(
        {
            "source_sha256": source_hash,
            "source_row_position": int(source_position),
        }
    )


def _safe_source_path(dataset: models.Dataset) -> Path:
    if not dataset.storage_filename or Path(dataset.storage_filename).name != dataset.storage_filename:
        raise _http_error(status.HTTP_400_BAD_REQUEST, "Dataset has an invalid source filename")
    root = ORIGINAL_DIR.resolve()
    path = (root / dataset.storage_filename).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise _http_error(status.HTTP_400_BAD_REQUEST, "Dataset source path is invalid")
    if not path.is_file():
        raise _http_error(status.HTTP_404_NOT_FOUND, "Original dataset file was not found")
    return path


def _read_source(dataset: models.Dataset, source_path: Path) -> pd.DataFrame:
    try:
        if dataset.format.upper() == "CSV":
            return pd.read_csv(source_path, dtype=str)
        if dataset.format.upper() == "XLSX":
            return pd.read_excel(source_path, dtype=str)
    except Exception as exc:
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            f"Could not read the original dataset: {exc}",
        ) from exc
    raise _http_error(
        status.HTTP_400_BAD_REQUEST,
        "Consolidated remediation supports tabular CSV and XLSX source datasets",
    )


def _source_state(dataset: models.Dataset) -> tuple[Path, str, pd.DataFrame]:
    source_path = _safe_source_path(dataset)
    source_hash = compute_file_sha256(source_path)
    if dataset.file_sha256 and source_hash.lower() != dataset.file_sha256.lower():
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "The registered original dataset SHA-256 no longer matches its stored file",
        )
    return source_path, source_hash, _read_source(dataset, source_path)


def _normalize_rows(value: Any, *, label: str, row_count: int) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must contain row positions")
    if any(type(index) is not int for index in value):
        raise ValueError(f"{label} contains a non-integer row position")
    rows = sorted(set(value))
    if len(rows) != len(value):
        raise ValueError(f"{label} contains duplicate row positions")
    if rows[0] < 0 or rows[-1] >= row_count:
        raise ValueError(f"{label} references a row outside the current source")
    return rows


def _text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _normalize_partition(value: Any) -> str:
    return _text(value).casefold()


def _load_selected_findings(
    db: Session,
    dataset_id: str,
    action: RemediationActionRequest,
) -> list[leakage_models.LeakageFinding]:
    if action.selection_mode == "all_eligible":
        allowed = _ACTION_FINDING_TYPES.get(action.action)
        requested_type = (action.finding_type or "").strip().lower()
        if action.action == "review_only":
            if requested_type not in _KNOWN_FINDING_TYPES:
                raise _http_error(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "all_eligible review selection requires a supported finding_type",
                )
        elif not allowed or requested_type not in allowed:
            raise _http_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "The selected finding_type is not supported by this remediation action",
            )
        return (
            db.query(leakage_models.LeakageFinding)
            .filter(
                leakage_models.LeakageFinding.dataset_id == dataset_id,
                leakage_models.LeakageFinding.finding_type == requested_type,
                leakage_models.LeakageFinding.status.ilike("open"),
            )
            .order_by(
                leakage_models.LeakageFinding.created_at.asc(),
                leakage_models.LeakageFinding.id.asc(),
            )
            .all()
        )

    ids = list(action.finding_ids)
    found = (
        db.query(leakage_models.LeakageFinding)
        .filter(
            leakage_models.LeakageFinding.id.in_(ids),
            leakage_models.LeakageFinding.dataset_id == dataset_id,
        )
        .all()
    )
    by_id = {item.id: item for item in found}
    if len(by_id) != len(ids):
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            "One or more selected findings do not belong to this dataset or were not found",
        )
    return [by_id[finding_id] for finding_id in ids]


def _finding_snapshot(
    findings: list[leakage_models.LeakageFinding],
) -> list[dict[str, Any]]:
    return [
        {
            "id": str(finding.id),
            "finding_type": finding.finding_type,
            "severity": finding.severity,
            "status": finding.status,
            "description": finding.description,
            "evidence": finding.evidence,
        }
        for finding in sorted(findings, key=lambda item: str(item.id))
    ]


def _validate_open(finding: leakage_models.LeakageFinding) -> None:
    if str(finding.status or "").strip().lower() != "open":
        raise ValueError("Finding is no longer open")


def _validate_duplicate_evidence(
    finding: leakage_models.LeakageFinding,
    frame: pd.DataFrame,
    hash_cache: dict[tuple[str, ...], tuple[list[str], dict[str, list[int]]]],
) -> tuple[list[int], str, list[str]]:
    evidence = finding.evidence
    if not isinstance(evidence, dict):
        raise ValueError("Duplicate finding has no structured evidence")
    duplicate_count = evidence.get("duplicate_count")
    if type(duplicate_count) is not int or duplicate_count < 2:
        raise ValueError("Duplicate evidence has an invalid duplicate_count")
    indices = _normalize_rows(
        evidence.get("row_indices"),
        label="Duplicate evidence row_indices",
        row_count=len(frame),
    )
    if len(indices) != duplicate_count:
        raise ValueError("Duplicate evidence count does not match its row positions")
    excluded = evidence.get("hash_excluded_columns", [])
    if (
        not isinstance(excluded, list)
        or any(not isinstance(column, str) or column not in frame.columns for column in excluded)
        or len(set(excluded)) != len(excluded)
    ):
        raise ValueError("Duplicate evidence has invalid hash-excluded columns")
    exclusion_key = tuple(excluded)
    if exclusion_key not in hash_cache:
        hash_frame = frame.drop(columns=list(exclusion_key))
        hashes = [hash_row(hash_frame.iloc[position]) for position in range(len(hash_frame))]
        groups: dict[str, list[int]] = {}
        for position, row_hash in enumerate(hashes):
            groups.setdefault(row_hash, []).append(position)
        hash_cache[exclusion_key] = (hashes, groups)
    hashes, groups = hash_cache[exclusion_key]
    expected_hash = hashes[indices[0]]
    current_group = groups.get(expected_hash, [])
    if current_group != indices:
        raise ValueError("Duplicate evidence no longer matches the exact source row group")
    if evidence.get("hash") not in (None, expected_hash):
        raise ValueError("Duplicate evidence hash no longer matches the source")
    return indices, expected_hash, excluded


def _validate_partitioned_evidence(
    finding: leakage_models.LeakageFinding,
    frame: pd.DataFrame,
    *,
    expected_type: str,
    split_column: str | None = None,
) -> tuple[dict[str, list[int]], str]:
    evidence = finding.evidence
    if not isinstance(evidence, dict):
        raise ValueError("Finding has no structured row evidence")
    if finding.finding_type != expected_type:
        raise ValueError("Finding type does not match the requested remediation")
    actual_split_column = evidence.get("split_column")
    if not isinstance(actual_split_column, str) or actual_split_column not in frame.columns:
        raise ValueError("Finding evidence does not identify a current split column")
    if split_column and actual_split_column != split_column:
        raise ValueError("Selected split column differs from the persisted finding evidence")
    row_map = evidence.get("row_indices")
    if not isinstance(row_map, dict) or not row_map:
        raise ValueError("Finding evidence has no partitioned row positions")
    normalized_map: dict[str, list[int]] = {}
    all_positions: list[int] = []
    for partition, raw_indices in row_map.items():
        if not isinstance(partition, str) or not partition.strip():
            raise ValueError("Finding evidence contains an invalid partition name")
        positions = _normalize_rows(
            raw_indices,
            label=f"Evidence positions for {partition}",
            row_count=len(frame),
        )
        normalized_map[partition] = positions
        all_positions.extend(positions)
    if len(set(all_positions)) != len(all_positions):
        raise ValueError("Partitioned evidence assigns a row to multiple partitions")
    split_values = frame[actual_split_column]
    for partition, positions in normalized_map.items():
        expected_partition = _normalize_partition(partition)
        if any(
            _normalize_partition(split_values.iloc[position]) != expected_partition
            for position in positions
        ):
            raise ValueError(
                f"Persisted row evidence no longer matches the '{partition}' partition"
            )
    return normalized_map, actual_split_column


def _validate_entity_finding(
    finding: leakage_models.LeakageFinding,
    frame: pd.DataFrame,
    entity_columns: list[str],
    split_column: str,
) -> list[int]:
    evidence = finding.evidence
    if finding.finding_type != "entity_overlap" or not isinstance(evidence, dict):
        raise ValueError("Selected finding is not a structured entity-overlap finding")
    persisted_columns = evidence.get("entity_columns")
    if not isinstance(persisted_columns, list):
        legacy_column = evidence.get("entity_column")
        persisted_columns = [legacy_column] if isinstance(legacy_column, str) else []
    if persisted_columns != entity_columns or evidence.get("split_column") != split_column:
        raise ValueError("Selected columns differ from the persisted entity-overlap evidence")
    if any(column not in frame.columns for column in entity_columns):
        raise ValueError("One or more configured entity columns are missing from the source")
    row_map, _ = _validate_partitioned_evidence(
        finding, frame, expected_type="entity_overlap", split_column=split_column
    )
    positions = sorted(position for group in row_map.values() for position in group)
    entity_values = evidence.get("entity_values")
    if not isinstance(entity_values, dict):
        legacy_value = evidence.get("entity_value")
        entity_values = {entity_columns[0]: legacy_value} if len(entity_columns) == 1 else {}
    if (
        set(entity_values) != set(entity_columns)
        or any(not isinstance(entity_values.get(column), str) or not entity_values[column].strip()
               for column in entity_columns)
    ):
        raise ValueError("Entity-overlap evidence does not identify the complete entity key")

    def row_matches(position: int) -> bool:
        return all(
            _text(frame[column].iloc[position]) == entity_values[column]
            for column in entity_columns
        )

    if any(not row_matches(position) for position in positions):
        raise ValueError("Entity row positions no longer match the persisted entity key")
    current_positions = [
        position
        for position in range(len(frame))
        if row_matches(position)
        and _normalize_partition(frame[split_column].iloc[position])
    ]
    if sorted(current_positions) != positions:
        raise ValueError("Entity row positions no longer include the complete current entity group")
    partitions = {
        _normalize_partition(frame[split_column].iloc[position])
        for position in positions
    }
    if len(partitions) < 2:
        raise ValueError("Entity-overlap evidence no longer spans multiple partitions")
    return positions


def _validate_contamination_finding(
    finding: leakage_models.LeakageFinding,
    frame: pd.DataFrame,
    split_column: str,
    hash_cache: dict[str, tuple[list[str], dict[str, dict[str, list[int]]]]],
) -> tuple[dict[str, list[int]], str]:
    evidence = finding.evidence
    if not isinstance(evidence, dict):
        raise ValueError("Contamination finding has no structured evidence")
    row_map, evidenced_split = _validate_partitioned_evidence(
        finding,
        frame,
        expected_type="train_test_contamination",
        split_column=split_column,
    )
    row_hash = evidence.get("row_hash")
    if not isinstance(row_hash, str) or len(row_hash) != 64:
        raise ValueError("Contamination evidence does not contain a valid row hash")
    matching_fields = evidence.get("matching_fields")
    if matching_fields is not None:
        if (
            not isinstance(matching_fields, list)
            or not matching_fields
            or any(
                not isinstance(column, str)
                or column == split_column
                or column not in frame.columns
                for column in matching_fields
            )
            or len(set(matching_fields)) != len(matching_fields)
        ):
            raise ValueError("Contamination evidence has invalid matching fields")
        hash_frame = frame[matching_fields]
    else:
        # Backward-compatible validation for findings persisted before
        # matching_fields was recorded.
        hash_frame = frame.drop(
            columns=[column for column in [split_column] if column in frame.columns]
        )
        id_columns = [column for column in hash_frame.columns if column.lower() == "id"]
        if id_columns:
            hash_frame = hash_frame.drop(columns=id_columns)
    cache_key = f"{split_column}:{_sha256_json(list(hash_frame.columns))}"
    positions = [position for group in row_map.values() for position in group]
    if any(hash_row(hash_frame.iloc[position]) != row_hash for position in positions):
        raise ValueError("Contamination row positions no longer match the persisted row hash")
    if cache_key not in hash_cache:
        all_hashes = [hash_row(hash_frame.iloc[position]) for position in range(len(hash_frame))]
        groups: dict[str, dict[str, list[int]]] = {}
        for position, current_hash in enumerate(all_hashes):
            partition = _normalize_partition(frame[split_column].iloc[position])
            if not partition:
                continue
            groups.setdefault(current_hash, {}).setdefault(partition, []).append(position)
        hash_cache[cache_key] = (all_hashes, groups)
    _, groups = hash_cache[cache_key]
    actual_groups = groups.get(row_hash, {})
    expected_groups = {
        _normalize_partition(partition): sorted(indices)
        for partition, indices in row_map.items()
    }
    if actual_groups != expected_groups:
        raise ValueError(
            "Contamination evidence no longer identifies every current copy across partitions"
        )
    return row_map, evidenced_split


def _validate_target_finding(
    finding: leakage_models.LeakageFinding,
    frame: pd.DataFrame,
    target_column: str,
    feature_column: str,
) -> None:
    evidence = finding.evidence
    if (
        finding.finding_type != "target_leakage"
        or not isinstance(evidence, dict)
        or evidence.get("target_column") != target_column
        or evidence.get("feature_column") != feature_column
        or target_column not in frame.columns
        or feature_column not in frame.columns
    ):
        raise ValueError("Target/feature selection does not match persisted leakage evidence")
    valid_target = frame[target_column].astype("string").str.strip()
    valid_feature = frame[feature_column].astype("string").str.strip()
    mask = (
        frame[target_column].notna()
        & valid_target.ne("").fillna(False)
        & frame[feature_column].notna()
        & valid_feature.ne("").fillna(False)
    )
    target_values = valid_target[mask]
    feature_values = valid_feature[mask]
    detection = evidence.get("detection")
    if detection == "exact_target_duplicate":
        if feature_values.tolist() != target_values.tolist():
            raise ValueError("The target-duplicate condition no longer holds in the source")
        return
    if detection == "deterministic_feature_target_mapping":
        mapping: dict[str, str] = {}
        for feature_value, target_value in zip(feature_values.tolist(), target_values.tolist()):
            if feature_value in mapping and mapping[feature_value] != target_value:
                raise ValueError("The deterministic target mapping no longer holds in the source")
            mapping[feature_value] = target_value
        mapping_digest = _sha256_json(sorted(mapping.items()))
        if (
            len(mapping) < 2
            or len(set(mapping.values())) < 2
            or (
                evidence.get("mapping_digest") is not None
                and mapping_digest != evidence.get("mapping_digest")
            )
            or (
                evidence.get("mapping_digest") is None
                and mapping != evidence.get("mapping")
            )
        ):
            raise ValueError("Persisted deterministic target evidence no longer matches the source")
        return
    raise ValueError("Target-leakage detection kind is unsupported for confirmed exclusion")


def _validate_temporal_finding(
    finding: leakage_models.LeakageFinding,
    frame: pd.DataFrame,
    time_column: str,
    split_column: str,
) -> None:
    evidence = finding.evidence
    if (
        finding.finding_type != "temporal_leakage"
        or not isinstance(evidence, dict)
        or evidence.get("time_column") != time_column
        or evidence.get("split_column") != split_column
        or time_column not in frame.columns
        or split_column not in frame.columns
    ):
        raise ValueError("Time/split selection does not match persisted temporal evidence")
    parsed = pd.to_datetime(
        frame[time_column], errors="coerce", utc=True
    ).dt.tz_convert(None)
    split_values = frame[split_column].map(_normalize_partition)
    valid = parsed.notna() & split_values.ne("")
    actual: dict[str, dict[str, Any]] = {}
    for partition in sorted(set(split_values[valid].tolist())):
        values = parsed[valid & split_values.eq(partition)]
        actual[partition] = {
            "min_time": values.min().isoformat(),
            "max_time": values.max().isoformat(),
            "valid_rows": int(len(values)),
        }
    expected = evidence.get("splits")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("Temporal finding has no split range evidence")
    expected_normalized: dict[str, dict[str, Any]] = {}
    for partition, values in expected.items():
        if not isinstance(partition, str) or not isinstance(values, dict):
            raise ValueError("Temporal split range evidence is malformed")
        try:
            min_time = pd.to_datetime(
                values.get("min_time"), errors="raise", utc=True
            ).tz_convert(None)
            max_time = pd.to_datetime(
                values.get("max_time"), errors="raise", utc=True
            ).tz_convert(None)
            valid_rows = int(values.get("valid_rows"))
        except Exception as exc:
            raise ValueError("Temporal split range evidence is malformed") from exc
        expected_normalized[_normalize_partition(partition)] = {
            "min_time": min_time.isoformat(),
            "max_time": max_time.isoformat(),
            "valid_rows": valid_rows,
        }
    if actual != expected_normalized:
        raise ValueError("Temporal split range evidence no longer matches the current source")
    invalid_rows = int(parsed.isna().sum())
    if evidence.get("missing_split_rows") is None:
        # Historical findings counted missing split memberships together with
        # invalid timestamps; keep their persisted evidence revalidatable.
        invalid_rows = int((parsed.isna() | split_values.eq("")).sum())
    elif int(evidence.get("missing_split_rows")) != int(split_values.eq("").sum()):
        raise ValueError("Temporal missing split count no longer matches the source")
    if int(evidence.get("invalid_timestamp_rows", -1)) != invalid_rows:
        raise ValueError("Temporal invalid timestamp count no longer matches the source")
    conventional_order = ["train", "validation", "val", "test"]
    ordered_partitions = sorted(
        actual,
        key=lambda name: (
            conventional_order.index(name)
            if name in conventional_order
            else len(conventional_order) + sorted(actual).index(name)
        ),
    )
    overlapping = False
    for index, earlier in enumerate(ordered_partitions):
        for later in ordered_partitions[index + 1 :]:
            earlier_max = pd.to_datetime(actual[earlier]["max_time"], utc=True)
            later_min = pd.to_datetime(actual[later]["min_time"], utc=True)
            overlapping = overlapping or later_min <= earlier_max
    if not overlapping:
        raise ValueError("The persisted temporal overlap condition no longer holds")
    return None


def _analysis_configuration_snapshot(
    dataset: models.Dataset,
    frame: pd.DataFrame,
) -> dict[str, Any]:
    """Return the last persisted user-confirmed detector configuration.

    A missing role stays null; it is never guessed from recommendations or
    substituted with another column. A generated split column is intentionally
    marked as unavailable in the immutable original source.
    """
    profile = dataset.profile if isinstance(dataset.profile, dict) else {}
    raw_columns = profile.get("analysis_columns")
    raw_columns = raw_columns if isinstance(raw_columns, dict) else {}
    raw_strategy = profile.get("split_strategy")
    split_strategy = raw_strategy if isinstance(raw_strategy, dict) else {}
    strategy_name = split_strategy.get("strategy")
    temporal_objective = raw_columns.get("temporal_objective")
    if temporal_objective not in {None, "future_prediction", "randomized_holdout"}:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "Persisted temporal objective is unsupported; review Analysis Setup",
        )

    values = {
        "target_column": raw_columns.get("target_column"),
        "timestamp_column": raw_columns.get("time_column"),
        "split_column": raw_columns.get("split_column"),
    }
    for role, column in values.items():
        if column is None or column == "":
            values[role] = None
            continue
        if not isinstance(column, str):
            raise _http_error(
                status.HTTP_409_CONFLICT,
                f"Persisted analysis configuration for {role} is malformed; review Analysis Setup",
            )
        if column not in frame.columns and not (
            role == "split_column"
            and strategy_name == "generated"
            and column == "__dataleakguard_split__"
        ):
            raise _http_error(
                status.HTTP_409_CONFLICT,
                f"Persisted analysis column '{column}' for {role} is not present in the current source",
            )

    raw_entity_columns = raw_columns.get("entity_columns")
    if raw_entity_columns is None:
        legacy_entity = raw_columns.get("entity_column")
        raw_entity_columns = [legacy_entity] if isinstance(legacy_entity, str) and legacy_entity else []
    if (
        not isinstance(raw_entity_columns, list)
        or any(not isinstance(column, str) or not column.strip() for column in raw_entity_columns)
        or len(set(raw_entity_columns)) != len(raw_entity_columns)
    ):
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "Persisted analysis entity-key configuration is malformed; review Analysis Setup",
        )
    missing_entity_columns = [
        column for column in raw_entity_columns if column not in frame.columns
    ]
    if missing_entity_columns:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "Persisted analysis entity columns are missing from the current source: "
            + ", ".join(missing_entity_columns),
        )
    entity_columns = list(raw_entity_columns)

    raw_contamination_columns = raw_columns.get("contamination_key_columns", [])
    if (
        not isinstance(raw_contamination_columns, list)
        or any(
            not isinstance(column, str) or not column.strip()
            for column in raw_contamination_columns
        )
        or len(set(raw_contamination_columns)) != len(raw_contamination_columns)
    ):
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "Persisted contamination-key configuration is malformed; review Analysis Setup",
        )
    missing_contamination_columns = [
        column for column in raw_contamination_columns if column not in frame.columns
    ]
    if missing_contamination_columns:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "Persisted contamination-key columns are missing from the current source: "
            + ", ".join(missing_contamination_columns),
        )

    safe_strategy_fields = {
        "strategy",
        "split_column",
        "split_operation_id",
        "test_ratio",
        "random_seed",
        "algorithm",
        "source",
        "train_label",
        "test_label",
        "reason",
        "row_count",
        "split_row_counts",
        "missing_membership_count",
    }
    strategy_snapshot = {
        key: value
        for key, value in split_strategy.items()
        if key in safe_strategy_fields
        and isinstance(value, (str, int, float, bool, type(None), dict))
    }
    return {
        **values,
        "entity_column": entity_columns[0] if len(entity_columns) == 1 else None,
        "entity_columns": entity_columns,
        "contamination_key_columns": list(raw_contamination_columns),
        "configuration_confirmed": raw_columns.get("configuration_confirmed") is True,
        "temporal_objective": temporal_objective,
        "split_strategy": strategy_name if isinstance(strategy_name, str) else None,
        "split_configuration": strategy_snapshot or None,
        "split_column_available_in_original_source": (
            values["split_column"] in frame.columns
            if values["split_column"] is not None
            else False
        ),
    }


def _post_remediation_detector_results(
    frame: pd.DataFrame,
    analysis_configuration: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Re-evaluate the five detector conditions on a concrete CSV frame.

    This helper intentionally does not persist findings. It returns explicit
    applicability and remaining-condition states so skipped checks are never
    represented as passes and verification cannot mutate the source findings.
    """
    def result(
        check_status: str,
        count: int | None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": check_status,
            "remaining_condition_count": count,
            **({"reason": reason} if reason else {}),
        }

    split_column = analysis_configuration.get("split_column")
    split_column = split_column if isinstance(split_column, str) else None
    split_available = bool(split_column and split_column in frame.columns)
    split_strategy = analysis_configuration.get("split_strategy")

    exact_exclusions: list[str] = []
    if split_strategy != "none":
        exact_exclusions.append("id")
        if split_available and split_column:
            exact_exclusions.append(split_column)
    exact_columns = [
        column for column in frame.columns if column not in exact_exclusions
    ]
    exact_groups: dict[str, int] = {}
    if exact_columns:
        for position in range(len(frame)):
            digest = hash_row(frame.iloc[position][exact_columns])
            exact_groups[digest] = exact_groups.get(digest, 0) + 1
    exact_count = sum(count >= 2 for count in exact_groups.values())
    detector_results: dict[str, dict[str, Any]] = {
        "exact_duplicate": result(
            "review_required" if exact_count else "passed",
            exact_count,
            "Exact duplicate groups remain in the output." if exact_count else None,
        )
    }

    raw_entities = analysis_configuration.get("entity_columns")
    entity_columns = raw_entities if isinstance(raw_entities, list) else []
    entity_columns = [
        column for column in entity_columns
        if isinstance(column, str) and column in frame.columns
    ]
    if not split_available or not entity_columns:
        detector_results["entity_overlap"] = result(
            "skipped",
            None,
            "Entity columns or split membership are unavailable in the remediation output.",
        )
    else:
        missing_entity_rows = 0
        entity_groups: dict[tuple[str, ...], set[str]] = {}
        for position in range(len(frame)):
            components = tuple(_text(frame[column].iloc[position]) for column in entity_columns)
            partition = _normalize_partition(frame[split_column].iloc[position])
            if not partition:
                continue
            if any(not value for value in components):
                missing_entity_rows += 1
                continue
            entity_groups.setdefault(components, set()).add(partition)
        overlaps = sum(len(partitions) > 1 for partitions in entity_groups.values())
        detector_results["entity_overlap"] = result(
            "review_required"
            if overlaps or missing_entity_rows
            else "passed",
            overlaps,
            (
                f"{overlaps} entity groups cross partitions; "
                f"{missing_entity_rows} rows have incomplete grouping keys."
                if overlaps or missing_entity_rows
                else None
            ),
        )

    target_column = analysis_configuration.get("target_column")
    if not isinstance(target_column, str) or target_column not in frame.columns:
        detector_results["target_leakage"] = result(
            "skipped", None, "No valid target column is configured."
        )
    else:
        target_raw = frame[target_column]
        target_values = target_raw.astype("string").str.strip()
        target_valid = target_raw.notna() & target_values.ne("").fillna(False)
        missing_targets = int((~target_valid).sum())
        valid_targets = target_values[target_valid]
        target_candidates = 0
        if valid_targets.nunique() > 1:
            for feature_column in frame.columns:
                if feature_column == target_column:
                    continue
                feature_raw = frame[feature_column]
                feature_values = feature_raw.astype("string").str.strip()
                valid_features = (
                    feature_raw.notna()
                    & feature_values.ne("").fillna(False)
                    & target_valid
                )
                features = feature_values[valid_features]
                targets = target_values[valid_features]
                if features.nunique() <= 1 or targets.nunique() <= 1:
                    continue
                mapping: dict[str, str] = {}
                consistent = True
                for feature, target in zip(features.tolist(), targets.tolist()):
                    prior = mapping.setdefault(str(feature), str(target))
                    if prior != str(target):
                        consistent = False
                        break
                if not consistent:
                    continue
                unique_features = set(mapping)
                unique_targets = set(mapping.values())
                cardinality_ratio = len(unique_features) / max(1, len(features))
                if (
                    len(unique_features) >= 5
                    and len(unique_features) > len(unique_targets)
                    and cardinality_ratio >= 0.8
                ):
                    continue
                target_candidates += 1
        target_status = (
            "review_required"
            if target_candidates or missing_targets
            else "passed"
        )
        detector_results["target_leakage"] = result(
            target_status,
            target_candidates,
            (
                f"{target_candidates} deterministic target-associated feature(s) remain; "
                f"{missing_targets} rows have missing targets."
                if target_candidates or missing_targets
                else None
            ),
        )

    time_column = analysis_configuration.get("timestamp_column")
    temporal_objective = analysis_configuration.get("temporal_objective")
    if (
        not split_available
        or not isinstance(time_column, str)
        or time_column not in frame.columns
    ):
        detector_results["temporal_leakage"] = result(
            "skipped",
            None,
            "Timestamp or split membership is unavailable in the remediation output.",
        )
    elif temporal_objective == "randomized_holdout":
        detector_results["temporal_leakage"] = result(
            "skipped",
            None,
            "Chronological ordering is not interpreted for a randomized-holdout objective.",
        )
    else:
        parsed_times = pd.to_datetime(frame[time_column], errors="coerce", utc=True)
        split_values = frame[split_column].map(_normalize_partition)
        invalid_times = int(parsed_times.isna().sum())
        missing_memberships = int((split_values == "").sum())
        ranges: dict[str, tuple[Any, Any]] = {}
        for label in sorted(set(split_values) - {""}):
            selected = parsed_times[(split_values == label) & parsed_times.notna()]
            if len(selected):
                ranges[label] = (selected.min(), selected.max())
        conventional = ["train", "validation", "val", "test"]
        ordered_labels = sorted(
            ranges,
            key=lambda label: (
                conventional.index(label)
                if label in conventional
                else len(conventional) + sorted(ranges).index(label)
            ),
        )
        overlaps = 0
        for index, earlier in enumerate(ordered_labels):
            for later in ordered_labels[index + 1 :]:
                if ranges[later][0] <= ranges[earlier][1]:
                    overlaps += 1
        detector_results["temporal_leakage"] = result(
            "review_required"
            if overlaps or invalid_times or missing_memberships
            else "passed",
            overlaps,
            (
                f"{overlaps} temporal partition overlaps; {invalid_times} missing/invalid "
                f"timestamps and {missing_memberships} missing split memberships."
                if overlaps or invalid_times or missing_memberships
                else None
            ),
        )

    if not split_available:
        detector_results["train_test_contamination"] = result(
            "skipped", None, "No verified split membership is available in the output."
        )
    else:
        raw_matching_columns = analysis_configuration.get("contamination_key_columns")
        configured_keys = (
            raw_matching_columns
            if isinstance(raw_matching_columns, list)
            else []
        )
        configured_keys = [
            column for column in configured_keys
            if isinstance(column, str) and column in frame.columns and column != split_column
        ]
        matching_columns = configured_keys or [
            column
            for column in frame.columns
            if column != split_column and column.lower() != "id"
        ]
        if not matching_columns:
            detector_results["train_test_contamination"] = result(
                "skipped",
                None,
                "No non-split comparison fields are available.",
            )
            return detector_results
        split_values = frame[split_column].map(_normalize_partition)
        missing_memberships = int((split_values == "").sum())
        missing_keys = 0
        hashes_by_partition: dict[str, set[str]] = {}
        if matching_columns:
            for position in range(len(frame)):
                partition = split_values.iloc[position]
                if not partition:
                    continue
                values = frame.iloc[position][matching_columns]
                if configured_keys and any(not _text(value) for value in values):
                    missing_keys += 1
                    continue
                digest = hash_row(values)
                hashes_by_partition.setdefault(digest, set()).add(partition)
        contaminated = sum(
            len(partitions) > 1 for partitions in hashes_by_partition.values()
        )
        detector_results["train_test_contamination"] = result(
            "review_required"
            if contaminated or missing_memberships or missing_keys
            else "passed",
            contaminated,
            (
                f"{contaminated} cross-partition matching group(s) remain; "
                f"{missing_memberships} rows lack split membership and "
                f"{missing_keys} rows lack configured comparison keys."
                if contaminated or missing_memberships or missing_keys
                else None
            ),
        )
    return detector_results


def _missing_value_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {
        str(column): int(count)
        for column, count in frame.isna().sum().items()
        if int(count) > 0
    }


def _persisted_detector_counts(
    db: Session,
    dataset_id: str,
) -> dict[str, dict[str, int]]:
    """Return persisted finding counts without loading finding evidence."""
    rows = (
        db.query(
            leakage_models.LeakageFinding.finding_type,
            func.lower(leakage_models.LeakageFinding.status),
            func.count(leakage_models.LeakageFinding.id),
        )
        .filter(leakage_models.LeakageFinding.dataset_id == dataset_id)
        .group_by(
            leakage_models.LeakageFinding.finding_type,
            func.lower(leakage_models.LeakageFinding.status),
        )
        .all()
    )
    counts: dict[str, dict[str, int]] = {}
    for finding_type, finding_status, count in rows:
        detector = str(finding_type or "unclassified")
        status_name = str(finding_status or "unclassified")
        detector_counts = counts.setdefault(
            detector,
            {"total": 0, "open": 0, "resolved": 0, "other_status": 0},
        )
        value = int(count or 0)
        detector_counts["total"] += value
        if status_name == "open":
            detector_counts["open"] += value
        elif status_name == "resolved":
            detector_counts["resolved"] += value
        else:
            detector_counts["other_status"] += value
    return counts


def _choose_group_test_entities(
    frame: pd.DataFrame,
    *,
    entity_columns: list[str],
    target_column: str | None,
    test_ratio: float,
    random_seed: int,
) -> tuple[set[str], dict[str, Any]]:
    """Choose whole entities deterministically, approximately balancing rows
    and (when explicitly supplied) target-class proportions.

    This is a deterministic greedy heuristic, not a statistically optimal
    stratified-group splitter. Entity values and target labels are not returned
    in the persisted summary.
    """
    # Canonical JSON makes composite grouping deterministic and collision-safe
    # even when individual values contain separators or punctuation.
    row_entities = [
        _canonical_json([_text(frame[column].iloc[position]) for column in entity_columns])
        for position in range(len(frame))
    ]
    entities = sorted(set(row_entities))
    group_sizes = Counter(row_entities)
    ranked = sorted(
        entities,
        key=lambda entity: (
            hashlib.sha256(f"{random_seed}:{entity}".encode("utf-8")).hexdigest(),
            entity,
        ),
    )
    if target_column is None:
        test_group_count = max(
            1, min(len(entities) - 1, round(len(entities) * test_ratio))
        )
        selected = set(ranked[:test_group_count])
        test_rows = sum(group_sizes[entity] for entity in selected)
        return selected, {
            "algorithm": "sha256_seeded_entity_order_v1",
            "entity_group_count": len(entities),
            "test_group_count": len(selected),
            "test_row_count": test_rows,
            "actual_test_row_ratio": test_rows / max(1, len(frame)),
            "entity_columns": entity_columns,
            "target_column": None,
            "target_class_count": None,
            "max_test_class_ratio_deviation": None,
        }

    if target_column not in frame.columns:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            f"Confirmed target column '{target_column}' is not present in the source",
        )

    group_classes: dict[str, Counter[str]] = {entity: Counter() for entity in entities}
    all_classes: Counter[str] = Counter()
    for entity, target_value in zip(row_entities, frame[target_column].tolist()):
        label = _text(target_value) or "__missing_target__"
        group_classes[entity][label] += 1
        all_classes[label] += 1

    desired_rows = len(frame) * test_ratio
    desired_class_counts = {
        label: total * test_ratio for label, total in all_classes.items()
    }

    def objective(test_rows: int, test_classes: Counter[str]) -> float:
        row_error = abs(test_rows - desired_rows) / max(1, len(frame))
        class_errors = []
        for label, total in all_classes.items():
            class_errors.append(
                abs(test_classes[label] - desired_class_counts[label])
                / max(1, total)
            )
        class_error = sum(class_errors) / max(1, len(class_errors))
        return row_error + class_error

    # Single deterministic pass: each candidate evaluation updates only the
    # small class counter, keeping large entity schemas bounded at O(rows +
    # groups * classes), rather than repeatedly summing every selected group.
    # The final ranked entity is reserved for training.
    candidates = ranked[:-1]
    selected: set[str] = set()
    selected_class_counts: Counter[str] = Counter()
    selected_rows = 0
    current_score = objective(selected_rows, selected_class_counts)
    for entity in candidates:
        candidate_classes = selected_class_counts + group_classes[entity]
        candidate_rows = selected_rows + group_sizes[entity]
        candidate_score = objective(candidate_rows, candidate_classes)
        if not selected or candidate_score < current_score:
            selected.add(entity)
            selected_class_counts = candidate_classes
            selected_rows = candidate_rows
            current_score = candidate_score

    test_rows = selected_rows
    class_deviations = []
    for label, total in all_classes.items():
        class_deviations.append(
            abs((selected_class_counts[label] / max(1, total)) - test_ratio)
        )
    return selected, {
        "algorithm": "sha256_seeded_greedy_group_target_balance_v1",
        "entity_group_count": len(entities),
        "test_group_count": len(selected),
        "test_row_count": test_rows,
        "actual_test_row_ratio": test_rows / max(1, len(frame)),
        "entity_columns": entity_columns,
        "target_column": target_column,
        "target_class_count": len(all_classes),
        "max_test_class_ratio_deviation": (
            max(class_deviations) if class_deviations else None
        ),
    }


def _build_plan(
    *,
    db: Session,
    dataset: models.Dataset,
    source_hash: str,
    frame: pd.DataFrame,
    actions: list[RemediationActionRequest],
) -> dict[str, Any]:
    analysis_configuration = _analysis_configuration_snapshot(dataset, frame)
    row_removals: dict[int, list[str]] = {}
    quarantine_positions: set[int] = set()
    split_updates: dict[str, dict[int, str]] = {}
    split_configurations: list[dict[str, Any]] = []
    duplicate_group_constraints: list[dict[str, Any]] = []
    contamination_constraints: list[dict[str, Any]] = []
    excluded_columns: set[str] = set()
    feature_exclusion_reasons: dict[str, dict[str, Any]] = {}
    action_results: list[dict[str, Any]] = []
    selected_findings: list[leakage_models.LeakageFinding] = []
    applied_finding_ids: set[str] = set()
    skipped_findings: list[dict[str, str]] = []
    seen_finding_actions: dict[str, str] = {}
    duplicate_hash_cache: dict[
        tuple[str, ...], tuple[list[str], dict[str, list[int]]]
    ] = {}
    contamination_hash_cache: dict[
        str, tuple[list[str], dict[str, dict[str, list[int]]]]
    ] = {}

    for action in actions:
        findings = _load_selected_findings(db, dataset.id, action)
        if not findings:
            raise _http_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"No findings matched remediation action '{action.action}'",
            )
        if action.action == "exclude_target_features":
            confirmed_features = {
                finding.evidence.get("feature_column")
                for finding in findings
                if isinstance(finding.evidence, dict)
                and isinstance(finding.evidence.get("feature_column"), str)
            }
            if action.selection_mode == "all_eligible" and not action.feature_columns:
                action.feature_columns = sorted(confirmed_features)
            if set(action.feature_columns) != confirmed_features:
                raise _http_error(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Excluded features must exactly match the selected persisted target-leakage findings",
                )
        action_finding_ids = [str(item.id) for item in findings]
        for finding in findings:
            existing_action = seen_finding_actions.get(str(finding.id))
            if existing_action:
                raise _http_error(
                    status.HTTP_409_CONFLICT,
                    f"Finding {finding.id} is selected for conflicting actions "
                    f"'{existing_action}' and '{action.action}'",
                )
            seen_finding_actions[str(finding.id)] = action.action
            selected_findings.append(finding)

        allowed_types = _ACTION_FINDING_TYPES.get(action.action)
        if action.action != "review_only" and not allowed_types:
            raise _http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown remediation action")
        if action.action == "review_only":
            allowed_types = _KNOWN_FINDING_TYPES

        applied_for_action: list[str] = []
        skipped_for_action: list[dict[str, str]] = []

        for finding in findings:
            try:
                if finding.finding_type not in allowed_types:
                    raise ValueError(
                        f"Action '{action.action}' is not supported for {finding.finding_type}"
                    )
                _validate_open(finding)

                if action.action == "review_only":
                    skipped = {
                        "finding_id": str(finding.id),
                        "reason": "Selected for review only; no automatic transformation requested",
                    }
                    skipped_findings.append(skipped)
                    skipped_for_action.append(skipped)
                    continue

                if action.action in {"exact_duplicate_keep_first", "quarantine_evidenced_rows"} and (
                    finding.finding_type == "exact_duplicate"
                ):
                    indices, _, _ = _validate_duplicate_evidence(
                        finding, frame, duplicate_hash_cache
                    )
                    duplicate_group_constraints.append(
                        {
                            "finding_id": str(finding.id),
                            "source_row_positions": indices,
                            "source_row_identities": [
                                _source_row_identity(source_hash, position)
                                for position in indices
                            ],
                            "keep_first_source_row_position": indices[0],
                            "keep_first_source_row_identity": _source_row_identity(
                                source_hash, indices[0]
                            ),
                        }
                    )
                    to_remove = indices[1:]
                    for position in to_remove:
                        row_removals.setdefault(position, []).append(
                            f"{finding.finding_type}:{finding.id}:{action.action}"
                        )
                    if action.action == "quarantine_evidenced_rows":
                        quarantine_positions.update(to_remove)

                elif action.action == "quarantine_evidenced_rows" and finding.finding_type == "entity_overlap":
                    evidence = finding.evidence or {}
                    entity_columns = action.entity_columns or (
                        [action.entity_column]
                        if action.entity_column
                        else evidence.get("entity_columns")
                        if isinstance(evidence.get("entity_columns"), list)
                        else [evidence.get("entity_column")]
                    )
                    split_column = action.split_column or evidence.get("split_column")
                    if (
                        not isinstance(entity_columns, list)
                        or not entity_columns
                        or any(not isinstance(column, str) for column in entity_columns)
                        or not isinstance(split_column, str)
                    ):
                        raise ValueError("Entity and split columns are required by the finding evidence")
                    positions = _validate_entity_finding(
                        finding, frame, entity_columns, split_column
                    )
                    for position in positions:
                        row_removals.setdefault(position, []).append(
                            f"entity_overlap:{finding.id}:quarantine"
                        )
                    quarantine_positions.update(positions)

                elif action.action == "quarantine_evidenced_rows" and finding.finding_type == "train_test_contamination":
                    evidence = finding.evidence or {}
                    split_column = action.split_column or evidence.get("split_column")
                    if not isinstance(split_column, str):
                        raise ValueError("A split column is required by contamination evidence")
                    row_map, _ = _validate_contamination_finding(
                        finding, frame, split_column, contamination_hash_cache
                    )
                    positions = [position for group in row_map.values() for position in group]
                    contamination_constraints.append(
                        {
                            "finding_id": str(finding.id),
                            "action": action.action,
                            "split_column": split_column,
                            "row_hash": (finding.evidence or {}).get("row_hash"),
                            "matching_fields": (
                                (finding.evidence or {}).get("matching_fields")
                                if isinstance(
                                    (finding.evidence or {}).get("matching_fields"),
                                    list,
                                )
                                else [
                                    column
                                    for column in frame.columns
                                    if column != split_column
                                    and column.lower() != "id"
                                ]
                            ),
                            "evidenced_source_row_positions": sorted(positions),
                            "evidenced_source_row_identities": [
                                _source_row_identity(source_hash, position)
                                for position in sorted(positions)
                            ],
                            "evidenced_positions_by_partition": {
                                partition: sorted(partition_positions)
                                for partition, partition_positions in row_map.items()
                            },
                        }
                    )
                    for position in positions:
                        row_removals.setdefault(position, []).append(
                            f"train_test_contamination:{finding.id}:quarantine"
                        )
                    quarantine_positions.update(positions)

                elif action.action == "rebuild_group_split":
                    entity_columns = action.entity_columns or (
                        [action.entity_column] if action.entity_column else []
                    )
                    split_column = action.split_column
                    if not entity_columns or not split_column:
                        raise ValueError("Group-aware split rebuilding requires an entity key and split column")
                    if any(column not in frame.columns for column in entity_columns) or split_column not in frame.columns:
                        raise ValueError("One or more selected entity or split columns do not exist in the source")
                    if action.target_column and action.target_column not in frame.columns:
                        raise ValueError("Selected target column does not exist in the source")
                    _validate_entity_finding(finding, frame, entity_columns, split_column)

                elif action.action == "exclude_target_features":
                    evidence = finding.evidence
                    if not isinstance(evidence, dict):
                        raise ValueError("Target-leakage finding has no structured evidence")
                    target_column = action.target_column
                    feature_columns = action.feature_columns
                    if not target_column or target_column not in frame.columns:
                        raise ValueError("A valid target column must be explicitly confirmed")
                    if target_column != evidence.get("target_column"):
                        raise ValueError("Confirmed target differs from the target in finding evidence")
                    if not feature_columns:
                        raise ValueError("Select one or more confirmed leaking feature columns")
                    if len(set(feature_columns)) != len(feature_columns):
                        raise ValueError("Confirmed leaking feature columns must be unique")
                    if target_column in feature_columns:
                        raise ValueError("The target column cannot be excluded from the model-ready output")
                    protected_configuration_columns = {
                        target_column,
                        analysis_configuration.get("split_column"),
                        analysis_configuration.get("timestamp_column"),
                        *analysis_configuration.get("entity_columns", []),
                        *analysis_configuration.get("contamination_key_columns", []),
                    }
                    protected_configuration_columns.discard(None)
                    protected_exclusions = sorted(
                        set(feature_columns).intersection(protected_configuration_columns)
                    )
                    if protected_exclusions:
                        raise ValueError(
                            "Configured target, entity, timestamp, split, or contamination-key "
                            "columns cannot be excluded: " + ", ".join(protected_exclusions)
                        )
                    feature_column = evidence.get("feature_column")
                    if (
                        not isinstance(feature_column, str)
                        or feature_column not in feature_columns
                        or feature_column not in frame.columns
                    ):
                        raise ValueError(
                            "Every excluded feature must be present in selected finding evidence and the source"
                        )
                    if feature_column not in frame.columns:
                        raise ValueError("The confirmed leaking feature is absent from the source")
                    _validate_target_finding(
                        finding,
                        frame,
                        target_column,
                        feature_column,
                    )
                    excluded_columns.update(feature_columns)
                    detector_signal = evidence.get("detection")
                    if not isinstance(detector_signal, str) or not detector_signal.strip():
                        detector_signal = evidence.get("method")
                    reason = evidence.get("reason")
                    if not isinstance(reason, str) or not reason.strip():
                        reason = (
                            f"Target-leakage evidence: {detector_signal}"
                            if isinstance(detector_signal, str) and detector_signal.strip()
                            else "Persisted target-leakage evidence supports excluding this feature."
                        )
                    reason = str(reason).strip()[:500]
                    feature_reason = feature_exclusion_reasons.setdefault(
                        feature_column,
                        {
                            "reason": reason,
                            "evidence_signal": (
                                detector_signal.strip()[:120]
                                if isinstance(detector_signal, str)
                                else "target_leakage_finding"
                            ),
                            "finding_ids": [],
                        },
                    )
                    feature_reason["finding_ids"].append(str(finding.id))

                elif action.action == "rebuild_chronological_split":
                    evidence = finding.evidence
                    if not isinstance(evidence, dict):
                        raise ValueError("Temporal finding has no structured evidence")
                    time_column = action.time_column
                    split_column = action.split_column
                    if (
                        not time_column
                        or not split_column
                        or time_column != evidence.get("time_column")
                        or split_column != evidence.get("split_column")
                    ):
                        raise ValueError("Time and split columns must match the temporal finding evidence")
                    if time_column not in frame.columns or split_column not in frame.columns:
                        raise ValueError("Selected time or split column does not exist in the source")
                    if not action.cutoff:
                        raise ValueError("A user-confirmed chronological cutoff is required")
                    try:
                        _validate_temporal_finding(
                            finding, frame, time_column, split_column
                        )
                        parsed_time = pd.to_datetime(frame[time_column], errors="coerce", utc=True)
                        cutoff = pd.to_datetime(action.cutoff, errors="raise", utc=True)
                    except Exception as exc:
                        if isinstance(exc, ValueError):
                            raise
                        raise ValueError("The timestamp column or selected cutoff cannot be parsed") from exc
                    if parsed_time.isna().any():
                        raise ValueError(
                            "Chronological split rebuilding is unavailable while any timestamp is invalid or missing"
                        )
                    updates = {
                        int(position): (
                            action.train_label.strip()
                            if value <= cutoff
                            else action.test_label.strip()
                        )
                        for position, value in enumerate(parsed_time)
                    }
                    labels = set(updates.values())
                    if len(labels) != 2:
                        raise ValueError("The cutoff must create non-empty train and test partitions")
                    split_updates.setdefault(split_column, {}).update(updates)
                    matching_config = next(
                        (
                            item
                            for item in split_configurations
                            if item.get("kind") == "chronological"
                            and item.get("split_column") == split_column
                            and item.get("time_column") == time_column
                            and item.get("cutoff") == cutoff.isoformat()
                            and item.get("train_label") == action.train_label.strip()
                            and item.get("test_label") == action.test_label.strip()
                        ),
                        None,
                    )
                    if matching_config is None:
                        split_configurations.append(
                            {
                                "kind": "chronological",
                                "time_column": time_column,
                                "split_column": split_column,
                                "cutoff": cutoff.isoformat(),
                                "train_label": action.train_label.strip(),
                                "test_label": action.test_label.strip(),
                                "finding_ids": [str(finding.id)],
                            }
                        )
                    else:
                        matching_config["finding_ids"].append(str(finding.id))

                elif action.action == "exclude_contaminated_copies":
                    if not action.split_column or not action.retained_partition:
                        raise ValueError(
                            "Contamination remediation requires a split column and explicitly retained partition"
                        )
                    row_map, split_column = _validate_contamination_finding(
                        finding, frame, action.split_column, contamination_hash_cache
                    )
                    retained = action.retained_partition.strip()
                    matched_partition = next(
                        (
                            name
                            for name in row_map
                            if _normalize_partition(name) == _normalize_partition(retained)
                        ),
                        None,
                    )
                    if matched_partition is None:
                        raise ValueError(
                            "The explicitly retained partition is not present in this finding's evidence"
                        )
                    retained_positions = sorted(row_map[matched_partition])
                    excluded_positions = sorted(
                        position
                        for partition, positions in row_map.items()
                        if partition != matched_partition
                        for position in positions
                    )
                    contamination_constraints.append(
                        {
                            "finding_id": str(finding.id),
                            "action": action.action,
                            "split_column": split_column,
                            "row_hash": (finding.evidence or {}).get("row_hash"),
                            "matching_fields": (
                                (finding.evidence or {}).get("matching_fields")
                                if isinstance(
                                    (finding.evidence or {}).get("matching_fields"),
                                    list,
                                )
                                else [
                                    column
                                    for column in frame.columns
                                    if column != split_column
                                    and column.lower() != "id"
                                ]
                            ),
                            "retained_partition": _normalize_partition(
                                matched_partition
                            ),
                            "retained_source_row_positions": retained_positions,
                            "retained_source_row_identities": [
                                _source_row_identity(source_hash, position)
                                for position in retained_positions
                            ],
                            "excluded_source_row_positions": excluded_positions,
                            "excluded_source_row_identities": [
                                _source_row_identity(source_hash, position)
                                for position in excluded_positions
                            ],
                        }
                    )
                    for partition, positions in row_map.items():
                        if partition != matched_partition:
                            for position in positions:
                                row_removals.setdefault(position, []).append(
                                    f"train_test_contamination:{finding.id}:retain:{matched_partition}"
                                )

                applied_for_action.append(str(finding.id))
                applied_finding_ids.add(str(finding.id))
            except ValueError as exc:
                if action.selection_mode == "all_eligible":
                    skipped = {"finding_id": str(finding.id), "reason": str(exc)}
                    skipped_findings.append(skipped)
                    skipped_for_action.append(skipped)
                else:
                    raise _http_error(
                        status.HTTP_409_CONFLICT,
                        f"Finding {finding.id} is not eligible for the requested action: {exc}",
                    ) from exc

        action_results.append(
            {
                "action": action.action,
                "selection_mode": action.selection_mode,
                "finding_type": action.finding_type,
                "finding_ids": action_finding_ids,
                "applied_finding_ids": applied_for_action,
                "skipped_findings": skipped_for_action,
                "configuration": action.model_dump(
                    mode="json",
                    exclude={"finding_ids"},
                ),
            }
        )

    if not selected_findings:
        raise _http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "No findings were selected")
    if len(split_updates) > 1:
        # Multiple independent split columns are permitted. Each column is
        # rewritten independently; conflict checks below handle repeated ones.
        pass
    split_columns = [item.get("split_column") for item in split_configurations]
    if len(set(split_columns)) != len(split_columns):
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "More than one action changes the same split column; create a single compatible split plan",
        )
    for split_column, assignments in split_updates.items():
        if any(position in assignments for position in row_removals):
            # Removing a row that would otherwise be reassigned is not
            # ambiguous, so the intersection is intentionally allowed.
            continue
        if split_column not in frame.columns:
            raise _http_error(status.HTTP_409_CONFLICT, "A planned split column is no longer present")

    final_columns = [column for column in frame.columns if column not in excluded_columns]
    if not final_columns:
        raise _http_error(status.HTTP_409_CONFLICT, "The plan would exclude every dataset column")
    for config in split_configurations:
        if config.get("split_column") in excluded_columns:
            raise _http_error(
                status.HTTP_409_CONFLICT,
                "A split column cannot also be excluded from the final output",
            )
        if config.get("time_column") in excluded_columns:
            raise _http_error(
                status.HTTP_409_CONFLICT,
                "A timestamp column used by a split cannot also be excluded",
            )

    # Group-aware split planning is computed after evidence validation so the
    # entity assignments are deterministic and are part of the preview digest.
    for action, result in zip(actions, action_results):
        if action.action != "rebuild_group_split":
            continue
        if not result["applied_finding_ids"]:
            continue
        entity_columns = action.entity_columns or (
            [action.entity_column] if action.entity_column else []
        )
        split_column = action.split_column
        assert entity_columns and split_column
        if action.test_ratio is None:
            raise _http_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Group-aware split rebuilding requires a test_ratio",
            )
        if action.random_seed is None:
            raise _http_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Group-aware split rebuilding requires a reproducible random_seed",
            )
        if any(
            frame[column].isna().any()
            or any(not _text(value) for value in frame[column].tolist())
            for column in entity_columns
        ):
            raise _http_error(
                status.HTTP_409_CONFLICT,
                "Group-aware split rebuilding requires non-missing values for every component of the entity key on every row",
            )
        row_entity_keys = [
            _canonical_json([_text(frame[column].iloc[position]) for column in entity_columns])
            for position in range(len(frame))
        ]
        entity_count = len(set(row_entity_keys))
        if entity_count < 2:
            raise _http_error(
                status.HTTP_409_CONFLICT,
                "At least two distinct entities are required to create a group-aware split",
            )
        test_entities, balance_summary = _choose_group_test_entities(
            frame,
            entity_columns=entity_columns,
            target_column=action.target_column,
            test_ratio=action.test_ratio,
            random_seed=action.random_seed,
        )
        updates = {
            int(position): (
                action.test_label.strip()
                if row_entity_keys[position] in test_entities
                else action.train_label.strip()
            )
            for position in range(len(frame))
        }
        split_updates.setdefault(split_column, {}).update(updates)
        split_configurations.append(
            {
                "kind": "group_aware",
                "entity_column": entity_columns[0] if len(entity_columns) == 1 else None,
                "entity_columns": entity_columns,
                "split_column": split_column,
                "test_ratio": action.test_ratio,
                "random_seed": action.random_seed,
                "train_label": action.train_label.strip(),
                "test_label": action.test_label.strip(),
                **balance_summary,
                "finding_ids": result["applied_finding_ids"],
            }
        )

    if len(split_configurations) > 1 and len(
        {item["split_column"] for item in split_configurations}
    ) != len(split_configurations):
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "The plan contains incompatible split changes for the same column",
        )

    removed_positions = sorted(row_removals)
    removed_position_set = set(removed_positions)
    for constraint in duplicate_group_constraints:
        keep_first = int(constraint["keep_first_source_row_position"])
        if keep_first in removed_position_set:
            raise _http_error(
                status.HTTP_409_CONFLICT,
                "Selected actions conflict: another remediation would remove the "
                f"keep-first source row for duplicate finding {constraint['finding_id']}",
            )

    for constraint in contamination_constraints:
        finding_id = constraint["finding_id"]
        if constraint["action"] == "exclude_contaminated_copies":
            retained_positions = set(
                constraint["retained_source_row_positions"]
            )
            if retained_positions.intersection(removed_position_set):
                raise _http_error(
                    status.HTTP_409_CONFLICT,
                    "Selected actions conflict: another remediation would remove a "
                    f"source row explicitly retained for contamination finding {finding_id}",
                )
            split_column = constraint["split_column"]
            split_assignments = split_updates.get(split_column, {})
            retained_partition = constraint["retained_partition"]
            moved_retained_positions = [
                position
                for position in sorted(retained_positions)
                if _normalize_partition(
                    split_assignments.get(
                        position, frame[split_column].iloc[position]
                    )
                )
                != retained_partition
            ]
            if moved_retained_positions:
                raise _http_error(
                    status.HTTP_409_CONFLICT,
                    "Selected split transformation conflicts with the explicitly "
                    f"retained partition for contamination finding {finding_id}; "
                    "revise the cutoff or retained partition",
                )
        else:
            evidenced_positions = set(
                constraint["evidenced_source_row_positions"]
            )
            if not evidenced_positions.issubset(removed_position_set) or not (
                evidenced_positions.issubset(quarantine_positions)
            ):
                raise _http_error(
                    status.HTTP_409_CONFLICT,
                    "Selected actions conflict with the evidenced quarantine rows "
                    f"for contamination finding {finding_id}",
                )

    if len(removed_positions) >= len(frame):
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "The proposed actions would remove every source row; revise the remediation plan",
        )
    quarantine_positions &= set(removed_positions)
    split_changed_positions: set[int] = set()
    for split_column, assignments in split_updates.items():
        split_changed_positions.update(
            position
            for position, label in assignments.items()
            if _text(frame[split_column].iloc[position]) != label
        )
    affected_positions = sorted(set(removed_positions).union(split_changed_positions))

    all_open_query = db.query(leakage_models.LeakageFinding.id).filter(
        leakage_models.LeakageFinding.dataset_id == dataset.id,
        leakage_models.LeakageFinding.status.ilike("open"),
    )
    open_ids = sorted(str(row[0]) for row in all_open_query.all())
    unresolved_ids = sorted(set(open_ids) - applied_finding_ids)
    selected_snapshot = _finding_snapshot(selected_findings)
    action_payload = [action.model_dump(mode="json") for action in actions]
    rows_digest = _sha256_json(affected_positions)
    persisted_action_configurations = [
        item.get("configuration", {})
        for item in action_results
        if isinstance(item.get("configuration"), dict)
    ]

    def first_configured_value(key: str) -> str | None:
        return next(
            (
                value
                for configuration in persisted_action_configurations
                if isinstance((value := configuration.get(key)), str) and value
            ),
            None,
        )

    entity_columns_used = next(
        (
            item.get("entity_columns")
            for item in split_configurations
            if isinstance(item.get("entity_columns"), list)
        ),
        next(
            (
                configuration.get("entity_columns")
                for configuration in persisted_action_configurations
                if isinstance(configuration.get("entity_columns"), list)
                and configuration.get("entity_columns")
            ),
            analysis_configuration.get("entity_columns") or (
                [first_configured_value("entity_column")]
                if first_configured_value("entity_column")
                else []
            ),
        ),
    )
    entity_columns_used = [
        value for value in entity_columns_used if isinstance(value, str)
    ]
    entity_column_used = (
        entity_columns_used[0] if len(entity_columns_used) == 1 else None
    )
    timestamp_column_used = next(
        (
            item.get("time_column")
            for item in split_configurations
            if isinstance(item.get("time_column"), str)
        ),
        first_configured_value("time_column"),
    )
    target_column_used = first_configured_value("target_column")
    if target_column_used is None:
        target_column_used = next(
            (
                item["evidence"].get("target_column")
                for item in selected_snapshot
                if item.get("finding_type") == "target_leakage"
                and isinstance(item.get("evidence"), dict)
                and isinstance(item["evidence"].get("target_column"), str)
            ),
            None,
        )
    split_column_used = next(
        (
            item.get("split_column")
            for item in split_configurations
            if isinstance(item.get("split_column"), str)
        ),
        first_configured_value("split_column") or analysis_configuration.get("split_column"),
    )
    remediation_configuration = {
        "target_column": target_column_used or analysis_configuration.get("target_column"),
        "entity_column": entity_column_used or analysis_configuration.get("entity_column"),
        "entity_columns": entity_columns_used,
        "contamination_key_columns": analysis_configuration.get(
            "contamination_key_columns", []
        ),
        "timestamp_column": timestamp_column_used or analysis_configuration.get("timestamp_column"),
        "temporal_objective": analysis_configuration.get("temporal_objective"),
        "split_column": split_column_used,
        "split_strategy": analysis_configuration.get("split_strategy"),
    }
    plan_core = {
        "version": 1,
        "dataset_id": str(dataset.id),
        "original_file_sha256": source_hash,
        "row_identity_scheme": "source_sha256_plus_zero_based_position_v1",
        "analysis_configuration": analysis_configuration,
        "remediation_configuration": remediation_configuration,
        "detector_counts_before": _persisted_detector_counts(db, dataset.id),
        "missing_value_counts_before": _missing_value_counts(frame),
        "finding_snapshot": selected_snapshot,
        "actions": action_payload,
        "action_results": action_results,
        "selected_finding_ids": sorted({str(item.id) for item in selected_findings}),
        "detector_types": sorted({str(item.finding_type) for item in selected_findings}),
        "applied_finding_ids": sorted(applied_finding_ids),
        "skipped_findings": skipped_findings,
        "affected_source_row_positions": affected_positions,
        "affected_source_row_positions_sha256": rows_digest,
        "rows_to_remove": removed_positions,
        "expected_output_source_row_positions_sha256": _sha256_json(
            [
                position
                for position in range(len(frame))
                if position not in removed_position_set
            ]
        ),
        "expected_output_source_row_identities_sha256": _sha256_json(
            [
                _source_row_identity(source_hash, position)
                for position in range(len(frame))
                if position not in removed_position_set
            ]
        ),
        "duplicate_group_constraints": duplicate_group_constraints,
        "contamination_constraints": contamination_constraints,
        "quarantine_source_row_positions": sorted(quarantine_positions),
        "excluded_feature_columns": sorted(excluded_columns),
        "feature_exclusion_reasons": feature_exclusion_reasons,
        "split_configurations": split_configurations,
        "split_updates": {
            column: {str(position): label for position, label in sorted(mapping.items())}
            for column, mapping in sorted(split_updates.items())
        },
        "original_row_count": len(frame),
        "expected_final_row_count": len(frame) - len(removed_positions),
        "original_column_count": len(frame.columns),
        "expected_final_column_count": len(final_columns),
        "expected_output_change": bool(
            removed_positions or excluded_columns or split_changed_positions
        ),
        "unresolved_finding_ids": unresolved_ids,
        "unresolved_findings_count": len(unresolved_ids),
    }
    detector_configuration = {
        **analysis_configuration,
        **{
            key: value
            for key, value in remediation_configuration.items()
            if value is not None
        },
    }
    plan_core["detector_configuration"] = detector_configuration
    preview_output, _, _, _ = _execute_transform(frame, plan_core)
    plan_core["missing_value_counts_after"] = _missing_value_counts(preview_output)
    plan_core["detector_results_before"] = _post_remediation_detector_results(
        frame, detector_configuration
    )
    plan_core["detector_results_after_preview"] = _post_remediation_detector_results(
        preview_output, detector_configuration
    )
    plan_core["source_output_identical"] = preview_output.reset_index(drop=True).equals(
        frame.reset_index(drop=True)
    )
    preview_digest = _sha256_json(plan_core)
    return {
        **plan_core,
        "preview_digest": preview_digest,
        "preview_token": preview_digest,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution_status": "previewed",
        "user_confirmation": False,
        "affected_source_row_positions_preview": affected_positions[:_ROW_REFERENCE_LIMIT],
        "affected_source_row_positions_truncated": len(affected_positions) > _ROW_REFERENCE_LIMIT,
        "affected_source_row_positions_count": len(affected_positions),
        "split_update_count": sum(len(values) for values in split_updates.values()),
    }


def _response_for_plan(record: models.RepairRecord) -> dict[str, Any]:
    metadata = record.operation_metadata if isinstance(record.operation_metadata, dict) else {}
    selected_ids = metadata.get("selected_finding_ids", [])
    if not isinstance(selected_ids, list):
        selected_ids = []
    skipped = metadata.get("skipped_findings", [])
    if not isinstance(skipped, list):
        skipped = []
    split_configs = metadata.get("split_configurations", [])
    if not isinstance(split_configs, list):
        split_configs = []
    public_plan = {
        key: metadata[key]
        for key in (
            "plan_id",
            "version",
            "execution_status",
            "user_confirmation",
            "preview_digest",
            "preview_token",
            "original_file_sha256",
            "final_file_sha256",
            "repair_report_sha256",
            "manifest_sha256",
            "quarantine_output_sha256",
            "original_row_count",
            "expected_final_row_count",
            "final_row_count",
            "original_column_count",
            "expected_final_column_count",
            "final_column_count",
            "removed_row_count",
            "quarantined_row_count",
            "affected_source_row_positions_preview",
            "affected_source_row_positions_count",
            "affected_source_row_positions_truncated",
            "affected_source_row_positions_sha256",
            "expected_output_source_row_identities_sha256",
            "row_identity_scheme",
            "excluded_feature_columns",
            "feature_exclusion_reasons",
            "analysis_configuration",
            "remediation_configuration",
            "detector_counts_before",
            "detector_configuration",
            "detector_results_before",
            "detector_results_after_preview",
            "detector_results_after",
            "missing_value_counts_before",
            "missing_value_counts_after",
            "expected_output_change",
            "source_output_identical",
            "split_update_count",
            "unresolved_findings_count",
            "unresolved_finding_ids",
            "verified_finding_ids",
            "final_status",
            "verification",
            "completed_at",
            "failure_reason",
        )
        if key in metadata
    }
    public_plan.update(
        {
            "selected_count": len(selected_ids),
            "selected_finding_ids_preview": selected_ids[:50],
            "selected_finding_ids_truncated": len(selected_ids) > 50,
            "detector_types": metadata.get("detector_types", []),
            "applied_count": len(metadata.get("applied_finding_ids", []))
            if isinstance(metadata.get("applied_finding_ids"), list)
            else 0,
            "skipped_findings": skipped[:50],
            "skipped_findings_truncated": len(skipped) > 50,
            "split_configurations": split_configs,
            "actions": [
                {
                    "action": item.get("action"),
                    "selection_mode": item.get("selection_mode"),
                    "finding_type": item.get("finding_type"),
                    "selected_count": len(item.get("finding_ids", []))
                    if isinstance(item.get("finding_ids"), list)
                    else 0,
                    "applied_count": len(item.get("applied_finding_ids", []))
                    if isinstance(item.get("applied_finding_ids"), list)
                    else 0,
                    "configuration": item.get("configuration", {}),
                }
                for item in metadata.get("action_results", [])
                if isinstance(item, dict)
            ],
        }
    )
    return {
        "id": str(record.id),
        "dataset_id": str(record.dataset_id),
        "operation_type": record.operation_type,
        "status": record.status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "original_file_sha256": record.input_file_sha256,
        "output_file_sha256": record.output_file_sha256,
        "output_filename": record.output_filename,
        "plan": public_plan,
    }


def preview_remediation_plan(
    *,
    dataset: models.Dataset,
    actions: list[RemediationActionRequest],
    db: Session,
) -> dict[str, Any]:
    if dataset.format.upper() not in {"CSV", "XLSX"}:
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            "Consolidated remediation supports tabular CSV and XLSX datasets only",
        )
    _, source_hash, frame = _source_state(dataset)
    plan = _build_plan(
        db=db,
        dataset=dataset,
        source_hash=source_hash,
        frame=frame,
        actions=actions,
    )
    record_id = str(uuid.uuid4())
    metadata = {
        **plan,
        "plan_id": record_id,
        "source_storage_filename": dataset.storage_filename,
        "final_output_filename": f"{record_id}-final.csv",
        "repair_report_filename": f"{record_id}-repair-report.csv",
        "manifest_filename": f"{record_id}-manifest.json",
        "quarantine_output_filename": (
            f"{record_id}-quarantined-rows.csv"
            if plan["quarantine_source_row_positions"]
            else None
        ),
    }
    record = models.RepairRecord(
        id=record_id,
        dataset_id=dataset.id,
        finding_id=None,
        operation_type="remediation_plan",
        status="previewed",
        input_file_sha256=source_hash,
        output_file_sha256=None,
        output_filename=None,
        affected_rows=len(plan["rows_to_remove"]),
        affected_columns=plan["excluded_feature_columns"],
        operation_metadata=metadata,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _response_for_plan(record)


def _execute_transform(
    frame: pd.DataFrame,
    plan: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame | None, list[int], list[int]]:
    source = frame.copy()
    rows_to_remove = [int(position) for position in plan.get("rows_to_remove", [])]
    removed_positions = set(rows_to_remove)
    quarantine_positions = sorted({
        int(position)
        for position in plan.get("quarantine_source_row_positions", [])
    })
    quarantined = (
        source.iloc[quarantine_positions].copy().reset_index(drop=True)
        if quarantine_positions
        else None
    )
    for column, mapping in plan.get("split_updates", {}).items():
        if column not in source.columns:
            raise ValueError(f"Planned split column '{column}' no longer exists")
        for position_text, label in mapping.items():
            source.iat[int(position_text), source.columns.get_loc(column)] = label
    if rows_to_remove:
        retained_ordinals = [
            ordinal
            for ordinal in range(len(source))
            if ordinal not in removed_positions
        ]
        source = source.iloc[retained_ordinals].copy().reset_index(drop=True)
        source_row_positions = retained_ordinals
    else:
        source_row_positions = list(range(len(source)))
    excluded = plan.get("excluded_feature_columns", [])
    if excluded:
        missing = [column for column in excluded if column not in source.columns]
        if missing:
            raise ValueError("One or more planned feature exclusions are no longer present")
        source = source.drop(columns=excluded)
    return source, quarantined, source_row_positions, quarantine_positions


def _verified_finding_ids(
    plan: dict[str, Any],
    checks: dict[str, bool],
    finding_checks: dict[str, dict[str, bool]] | None = None,
) -> list[str]:
    """Return applied findings whose postconditions and artifacts are verified.

    Row-level checks are required; detector-wide "no conditions remain" results
    alone are insufficient because a selected group could have been removed in
    its entirety. Artifact integrity is also required before a finding can be
    persisted as resolved.
    """
    finding_checks = finding_checks or {}
    required_integrity_checks = (
        "output_source_identity_mapping_matches_plan",
        "output_source_identity_content_matches",
        "output_bytes_round_trip_matches",
        "source_sha256_unchanged",
        "final_sha256_matches_output",
        "output_schema_matches_expected",
        "output_row_count_matches_expected",
        "source_output_change_matches_plan",
    )
    if any(checks.get(name) is not True for name in required_integrity_checks):
        return []
    if plan.get("quarantine_source_row_positions") and any(
        checks.get(name) is not True
        for name in (
            "quarantine_source_identity_mapping_matches_plan",
            "quarantine_source_identity_content_matches",
            "quarantine_output_round_trip_matches",
        )
    ):
        return []
    snapshots = {
        item.get("id"): item
        for item in plan.get("finding_snapshot", [])
        if isinstance(item, dict)
    }
    verified: set[str] = set()
    for action_result in plan.get("action_results", []):
        if not isinstance(action_result, dict):
            continue
        action_name = action_result.get("action")
        if action_name == "review_only":
            continue
        for finding_id in action_result.get("applied_finding_ids", []):
            snapshot = snapshots.get(finding_id, {})
            finding_type = snapshot.get("finding_type")
            row_checks = finding_checks.get(str(finding_id), {})
            if finding_type == "exact_duplicate" and action_name in {
                "exact_duplicate_keep_first",
                "quarantine_evidenced_rows",
            }:
                required = ["selected_exact_duplicate_group_resolved"]
            elif finding_type == "entity_overlap" and action_name == "rebuild_group_split":
                required = ["selected_entity_group_separated"]
            elif finding_type == "entity_overlap" and action_name == "quarantine_evidenced_rows":
                required = ["selected_entity_rows_quarantined"]
            elif finding_type == "target_leakage" and action_name == "exclude_target_features":
                required = [
                    "selected_target_feature_excluded",
                    "selected_target_column_preserved",
                ]
            elif finding_type == "temporal_leakage" and action_name == "rebuild_chronological_split":
                required = ["selected_chronological_order_verified"]
            elif finding_type == "train_test_contamination" and action_name in {
                "exclude_contaminated_copies",
                "quarantine_evidenced_rows",
            }:
                required = ["selected_contamination_group_policy_verified"]
            else:
                required = []
            if required and all(row_checks.get(name) is True for name in required):
                if action_name == "quarantine_evidenced_rows" and checks.get(
                    "quarantine_output_round_trip_matches"
                ) is not True:
                    continue
                verified.add(str(finding_id))
    return sorted(verified)


def _reconcile_selected_finding_detector_status(
    detector_results: dict[str, dict[str, Any]],
    plan: dict[str, Any],
    verified_finding_ids: set[str],
) -> None:
    """Prevent a zero-count detector scan from masking a failed selected rule."""
    applied_ids = {
        str(finding_id) for finding_id in plan.get("applied_finding_ids", [])
    }
    for finding_id in sorted(applied_ids - verified_finding_ids):
        snapshot = next(
            (
                item
                for item in plan.get("finding_snapshot", [])
                if isinstance(item, dict)
                and str(item.get("id")) == finding_id
            ),
            {},
        )
        detector_result = detector_results.get(snapshot.get("finding_type"))
        if not isinstance(detector_result, dict):
            continue
        detector_result["status"] = "review_required"
        detector_result["reason"] = (
            (detector_result.get("reason") + " ")
            if detector_result.get("reason")
            else ""
        ) + (
            "A selected finding's row-identity policy or output-integrity "
            "postcondition was not verified."
        )
        detector_result["selected_finding_verification_failed"] = True


def _verify_plan(
    *,
    output_frame: pd.DataFrame,
    output_source_row_positions: list[int],
    quarantine_frame: pd.DataFrame | None,
    quarantine_source_row_positions: list[int],
    source_frame: pd.DataFrame,
    plan: dict[str, Any],
) -> dict[str, Any]:
    valid_source_positions = (
        len(output_source_row_positions) == len(output_frame)
        and len(set(output_source_row_positions)) == len(output_source_row_positions)
        and all(
            type(position) is int and 0 <= position < len(source_frame)
            for position in output_source_row_positions
        )
    )
    source_positions_digest = (
        _sha256_json(output_source_row_positions)
        if valid_source_positions
        else None
    )
    output_source_identities = (
        [
            _source_row_identity(
                str(plan.get("original_file_sha256")), position
            )
            for position in output_source_row_positions
        ]
        if valid_source_positions
        else []
    )
    source_identities_digest = (
        _sha256_json(output_source_identities)
        if valid_source_positions
        else None
    )
    output_position_to_ordinal = (
        {
            source_position: output_ordinal
            for output_ordinal, source_position in enumerate(
                output_source_row_positions
            )
        }
        if valid_source_positions
        else {}
    )
    valid_quarantine_positions = (
        len(quarantine_source_row_positions)
        == (len(quarantine_frame) if quarantine_frame is not None else 0)
        and len(set(quarantine_source_row_positions))
        == len(quarantine_source_row_positions)
        and all(
            type(position) is int and 0 <= position < len(source_frame)
            for position in quarantine_source_row_positions
        )
    )
    quarantine_position_set = (
        set(quarantine_source_row_positions)
        if valid_quarantine_positions
        else set()
    )
    quarantine_source_row_position_set = set(quarantine_source_row_positions)
    expected_projected_output = source_frame.iloc[
        output_source_row_positions
    ].copy().reset_index(drop=True) if valid_source_positions else pd.DataFrame()
    expected_projected_quarantine = source_frame.iloc[
        quarantine_source_row_positions
    ].copy().reset_index(drop=True) if valid_quarantine_positions else pd.DataFrame()
    if valid_source_positions:
        for column, mapping in plan.get("split_updates", {}).items():
            if column not in expected_projected_output.columns:
                continue
            column_index = expected_projected_output.columns.get_loc(column)
            for output_ordinal, source_position in enumerate(
                output_source_row_positions
            ):
                label = mapping.get(str(source_position))
                if label is not None:
                    expected_projected_output.iat[
                        output_ordinal, column_index
                    ] = label
        excluded_columns = plan.get("excluded_feature_columns", [])
        if all(column in expected_projected_output.columns for column in excluded_columns):
            expected_projected_output = expected_projected_output.drop(
                columns=excluded_columns
            )
    checks: dict[str, bool] = {
        "output_source_identity_mapping_matches_plan": (
            valid_source_positions
            and source_positions_digest
            == plan.get("expected_output_source_row_positions_sha256")
            and source_identities_digest
            == plan.get("expected_output_source_row_identities_sha256")
        ),
        "output_source_identity_content_matches": (
            valid_source_positions
            and list(expected_projected_output.columns) == list(output_frame.columns)
            and expected_projected_output.equals(
                output_frame.reset_index(drop=True)
            )
        ),
        "quarantine_source_identity_mapping_matches_plan": (
            valid_quarantine_positions
            and quarantine_source_row_positions
            == sorted(plan.get("quarantine_source_row_positions", []))
        ),
        "quarantine_source_identity_content_matches": (
            valid_quarantine_positions
            and (
                expected_projected_quarantine.empty
                if quarantine_frame is None
                else expected_projected_quarantine.equals(
                    quarantine_frame.reset_index(drop=True)
                )
            )
        ),
        "output_schema_matches_expected": list(output_frame.columns)
        == [
            column
            for column in source_frame.columns
            if column not in plan.get("excluded_feature_columns", [])
        ],
        "output_row_count_matches_expected": len(output_frame)
        == plan.get("expected_final_row_count"),
        "excluded_features_absent": all(
            column not in output_frame.columns
            for column in plan.get("excluded_feature_columns", [])
        ),
        "missing_value_counts_match_preview": _missing_value_counts(output_frame)
        == plan.get("missing_value_counts_after", {}),
    }
    source_output_identical = output_frame.reset_index(drop=True).equals(
        source_frame.reset_index(drop=True)
    )
    checks["expected_output_change_is_present"] = (
        not plan.get("expected_output_change", False) or not source_output_identical
    )
    checks["selected_target_preserved"] = all(
        (
            action.get("configuration", {}).get("target_column") is None
            or action.get("configuration", {}).get("target_column") in output_frame.columns
        )
        for action in plan.get("action_results", [])
    )

    # Verify selected duplicate groups by immutable source identity. Merely
    # observing zero duplicate rows is insufficient: an operation that removed
    # every member of a selected group did not preserve its canonical record.
    duplicate_findings = {
        finding["id"]: finding
        for finding in plan.get("finding_snapshot", [])
        if isinstance(finding, dict)
        and finding.get("finding_type") == "exact_duplicate"
    }
    exact_duplicate_checks: list[bool] = []
    finding_checks: dict[str, dict[str, bool]] = {}
    duplicate_constraints = {
        str(item.get("finding_id")): item
        for item in plan.get("duplicate_group_constraints", [])
        if isinstance(item, dict) and item.get("finding_id") is not None
    }
    for action_result in plan.get("action_results", []):
        if not isinstance(action_result, dict):
            continue
        if action_result.get("action") not in {
            "exact_duplicate_keep_first",
            "quarantine_evidenced_rows",
        }:
            continue
        for finding_id in action_result.get("applied_finding_ids", []):
            snapshot = duplicate_findings.get(finding_id)
            if not snapshot:
                continue
            constraint = duplicate_constraints.get(str(finding_id))
            row_checks = finding_checks.setdefault(str(finding_id), {})
            if not constraint:
                row_checks["selected_exact_duplicate_group_resolved"] = False
                exact_duplicate_checks.append(False)
                continue
            evidence = snapshot.get("evidence")
            if not isinstance(evidence, dict):
                exact_duplicate_checks.append(False)
                row_checks["selected_exact_duplicate_group_resolved"] = False
                continue
            indices = constraint.get("source_row_positions")
            keep_first = constraint.get("keep_first_source_row_position")
            identities = constraint.get("source_row_identities")
            expected_identities = (
                [
                    _source_row_identity(
                        str(plan.get("original_file_sha256")), int(position)
                    )
                    for position in indices
                ]
                if isinstance(indices, list)
                and all(type(position) is int for position in indices)
                else []
            )
            if (
                not isinstance(indices, list)
                or not indices
                or type(keep_first) is not int
                or keep_first != indices[0]
                or identities != expected_identities
                or not valid_source_positions
            ):
                exact_duplicate_checks.append(False)
                row_checks["selected_exact_duplicate_group_resolved"] = False
                continue
            if any(position < 0 or position >= len(source_frame) for position in indices):
                exact_duplicate_checks.append(False)
                row_checks["selected_exact_duplicate_group_resolved"] = False
                continue
            surviving_source_positions = [
                int(position)
                for position in indices
                if int(position) in output_position_to_ordinal
            ]
            expected_removed_positions = [int(position) for position in indices[1:]]
            expected_quarantine_positions = (
                expected_removed_positions
                if action_result.get("action") == "quarantine_evidenced_rows"
                else []
            )
            quarantine_identity_matches = (
                expected_quarantine_positions
                == [
                    position
                    for position in expected_removed_positions
                    if position in quarantine_position_set
                ]
            )
            resolved = (
                surviving_source_positions == [int(keep_first)]
                and not set(expected_removed_positions).intersection(
                    output_position_to_ordinal
                )
                and (
                    action_result.get("action") != "quarantine_evidenced_rows"
                    or quarantine_identity_matches
                )
            )
            exact_duplicate_checks.append(resolved)
            row_checks["selected_exact_duplicate_group_resolved"] = resolved
    if exact_duplicate_checks:
        checks["selected_exact_duplicate_groups_resolved"] = all(exact_duplicate_checks)

    snapshots_by_id = {
        str(item.get("id")): item
        for item in plan.get("finding_snapshot", [])
        if isinstance(item, dict) and item.get("id") is not None
    }
    split_configurations = [
        item
        for item in plan.get("split_configurations", [])
        if isinstance(item, dict)
    ]

    # Verify group-aware splits and attach the result to each selected finding.
    entity_checks: list[bool] = []
    for config in split_configurations:
        if config.get("kind") != "group_aware":
            continue
        split_column = config.get("split_column")
        entity_columns = config.get("entity_columns")
        if not isinstance(entity_columns, list):
            legacy_column = config.get("entity_column")
            entity_columns = [legacy_column] if isinstance(legacy_column, str) else []
        valid = bool(
            entity_columns
            and all(column in output_frame.columns for column in entity_columns)
            and isinstance(split_column, str)
            and split_column in output_frame.columns
            and not any(output_frame[column].isna().any() for column in entity_columns)
        )
        if valid:
            group_counts = output_frame.groupby(entity_columns, dropna=False)[
                split_column
            ].nunique(dropna=False)
            valid = bool((group_counts <= 1).all())
        entity_checks.append(valid)
        for finding_id in config.get("finding_ids", []):
            snapshot = snapshots_by_id.get(str(finding_id), {})
            evidence = snapshot.get("evidence")
            row_map = evidence.get("row_indices") if isinstance(evidence, dict) else {}
            evidence_positions = (
                {
                    int(position)
                    for positions in row_map.values()
                    if isinstance(positions, list)
                    for position in positions
                    if type(position) is int
                }
                if isinstance(row_map, dict)
                else set()
            )
            retained_evidence = bool(
                evidence_positions.intersection(output_position_to_ordinal)
            )
            row_checks = finding_checks.setdefault(str(finding_id), {})
            row_checks["selected_entity_group_separated"] = (
                valid and retained_evidence
            )
    if entity_checks:
        checks["entity_groups_separated"] = all(entity_checks)

    # A quarantined entity finding is resolved only when its exact evidenced
    # source rows are absent from the clean output and preserved in quarantine.
    entity_quarantine_checks: list[bool] = []
    for action_result in plan.get("action_results", []):
        if not isinstance(action_result, dict) or action_result.get(
            "action"
        ) != "quarantine_evidenced_rows":
            continue
        for finding_id in action_result.get("applied_finding_ids", []):
            snapshot = snapshots_by_id.get(str(finding_id), {})
            if snapshot.get("finding_type") != "entity_overlap":
                continue
            evidence = snapshot.get("evidence")
            row_map = evidence.get("row_indices") if isinstance(evidence, dict) else {}
            positions = {
                int(position)
                for raw_positions in row_map.values()
                if isinstance(raw_positions, list)
                for position in raw_positions
                if type(position) is int
            } if isinstance(row_map, dict) else set()
            passed = bool(
                positions
                and positions.isdisjoint(output_position_to_ordinal)
                and positions.issubset(quarantine_position_set)
                and valid_quarantine_positions
            )
            entity_quarantine_checks.append(passed)
            entity_checks.append(passed)
            finding_checks.setdefault(str(finding_id), {})[
                "selected_entity_rows_quarantined"
            ] = passed
    if entity_quarantine_checks:
        checks["entity_rows_quarantined"] = all(entity_quarantine_checks)
        checks["entity_groups_separated"] = all(entity_checks)

    # Each chronology operation is checked independently; one passing split
    # cannot mask a different selected split with invalid boundaries.
    chronological_checks: list[bool] = []
    for config in split_configurations:
        if config.get("kind") != "chronological":
            continue
        time_column = config.get("time_column")
        split_column = config.get("split_column")
        valid = bool(
            isinstance(time_column, str)
            and time_column in output_frame.columns
            and isinstance(split_column, str)
            and split_column in output_frame.columns
        )
        if valid:
            parsed = pd.to_datetime(
                output_frame[time_column], errors="coerce", utc=True
            )
            split_values = output_frame[split_column].map(_normalize_partition)
            train_label = _normalize_partition(config.get("train_label"))
            test_label = _normalize_partition(config.get("test_label"))
            train_dates = parsed[split_values == train_label]
            test_dates = parsed[split_values == test_label]
            valid = bool(
                not parsed.isna().any()
                and len(train_dates) > 0
                and len(test_dates) > 0
                and train_dates.max() < test_dates.min()
            )
        chronological_checks.append(valid)
        for finding_id in config.get("finding_ids", []):
            finding_checks.setdefault(str(finding_id), {})[
                "selected_chronological_order_verified"
            ] = valid
    if chronological_checks:
        checks["chronological_order_verified"] = all(chronological_checks)

    # Verify contamination policies by stable source identity and requested
    # retained partition, not merely by counting partitions among whatever
    # matching rows happen to remain (where an empty result used to pass).
    contamination_checks: list[bool] = []
    finding_verification_basis: dict[str, str] = {}
    for constraint in plan.get("contamination_constraints", []):
        if not isinstance(constraint, dict):
            continue
        finding_id = str(constraint.get("finding_id"))
        split_column = constraint.get("split_column")
        action_name = constraint.get("action")
        row_hash = constraint.get("row_hash")
        matching_fields = constraint.get("matching_fields")
        if not isinstance(matching_fields, list):
            matching_fields = [
                column
                for column in source_frame.columns
                if column != split_column and column.lower() != "id"
            ]
        source_hash = str(plan.get("original_file_sha256"))

        def identities_match(positions: list[int], identities: Any) -> bool:
            return identities == [
                _source_row_identity(source_hash, position)
                for position in positions
            ]

        source_matching_fields_valid = bool(
            matching_fields
            and all(isinstance(column, str) for column in matching_fields)
            and len(set(matching_fields)) == len(matching_fields)
            and all(
                column in source_frame.columns and column != split_column
                for column in matching_fields
            )
        )
        matching_fields_available_in_output = bool(
            source_matching_fields_valid
            and all(column in output_frame.columns for column in matching_fields)
        )
        missing_matching_fields = [
            column
            for column in matching_fields
            if column not in output_frame.columns
        ]
        matching_fields_removed_by_plan = bool(
            missing_matching_fields
            and all(
                column in plan.get("excluded_feature_columns", [])
                for column in missing_matching_fields
            )
        )

        if action_name == "exclude_contaminated_copies":
            raw_retained_value = constraint.get("retained_source_row_positions", [])
            raw_excluded_value = constraint.get("excluded_source_row_positions", [])
            retained_list_valid = isinstance(raw_retained_value, list)
            excluded_list_valid = isinstance(raw_excluded_value, list)
            raw_retained_positions = (
                raw_retained_value if retained_list_valid else []
            )
            raw_excluded_positions = (
                raw_excluded_value if excluded_list_valid else []
            )
            source_evidence_positions = (
                raw_retained_positions + raw_excluded_positions
            )
            identities_valid = (
                retained_list_valid
                and excluded_list_valid
                and all(
                    type(position) is int
                    for position in source_evidence_positions
                )
                and len(set(source_evidence_positions))
                == len(source_evidence_positions)
                and identities_match(
                    raw_retained_positions,
                    constraint.get("retained_source_row_identities"),
                )
                and identities_match(
                    raw_excluded_positions,
                    constraint.get("excluded_source_row_identities"),
                )
            )
            retained_positions = set(raw_retained_positions) if identities_valid else set()
            excluded_positions = set(raw_excluded_positions) if identities_valid else set()
            retained_partition = _normalize_partition(
                constraint.get("retained_partition")
            )
            source_partition_policy_matches = bool(
                retained_positions
                and retained_partition
                and all(
                    _normalize_partition(source_frame.iloc[position][split_column])
                    == retained_partition
                    for position in retained_positions
                )
                and all(
                    _normalize_partition(source_frame.iloc[position][split_column])
                    != retained_partition
                    for position in excluded_positions
                )
            ) if (
                identities_valid
                and isinstance(split_column, str)
                and split_column in source_frame.columns
                and all(
                    0 <= position < len(source_frame)
                    for position in source_evidence_positions
                )
            ) else False
        elif action_name == "quarantine_evidenced_rows":
            raw_evidenced_value = constraint.get(
                "evidenced_source_row_positions", []
            )
            evidenced_list_valid = isinstance(raw_evidenced_value, list)
            raw_evidenced_positions = (
                raw_evidenced_value if evidenced_list_valid else []
            )
            source_evidence_positions = raw_evidenced_positions
            identities_valid = (
                evidenced_list_valid
                and all(
                    type(position) is int
                    for position in source_evidence_positions
                )
                and len(set(source_evidence_positions))
                == len(source_evidence_positions)
                and identities_match(
                    raw_evidenced_positions,
                    constraint.get("evidenced_source_row_identities"),
                )
            )
            retained_positions = set()
            excluded_positions = set()
            source_partition_policy_matches = True
        else:
            source_evidence_positions = []
            identities_valid = False
            retained_positions = set()
            excluded_positions = set()
            source_partition_policy_matches = False

        source_positions_in_range = bool(
            source_evidence_positions
            and all(
                type(position) is int and 0 <= position < len(source_frame)
                for position in source_evidence_positions
            )
        )
        source_evidence_matches = bool(
            source_matching_fields_valid
            and isinstance(row_hash, str)
            and source_positions_in_range
            and all(
                hash_row(source_frame.iloc[position][matching_fields]) == row_hash
                for position in source_evidence_positions
            )
        )
        output_evidence_projection_supported = bool(
            matching_fields_available_in_output
            or matching_fields_removed_by_plan
        )
        valid = bool(
            isinstance(split_column, str)
            and split_column in output_frame.columns
            and split_column in source_frame.columns
            and isinstance(row_hash, str)
            and source_matching_fields_valid
            and source_evidence_matches
            and output_evidence_projection_supported
            and valid_source_positions
            and valid_quarantine_positions
        )
        matching_output_positions: list[int] = []
        matching_partitions: set[str] = set()
        if valid and matching_fields_available_in_output:
            for output_position in range(len(output_frame)):
                if hash_row(output_frame.iloc[output_position][matching_fields]) != row_hash:
                    continue
                matching_output_positions.append(output_position)
                matching_partitions.add(
                    _normalize_partition(
                        output_frame[split_column].iloc[output_position]
                    )
                )
        if action_name == "exclude_contaminated_copies":
            surviving_retained = retained_positions.intersection(
                output_position_to_ordinal
            )
            surviving_excluded = excluded_positions.intersection(
                output_position_to_ordinal
            )
            actual_retained_partitions = {
                _normalize_partition(
                    output_frame.iloc[
                        output_position_to_ordinal[source_position]
                    ][split_column]
                )
                for source_position in surviving_retained
            } if valid else set()
            passed = bool(
                valid
                and identities_valid
                and retained_positions
                and surviving_retained == retained_positions
                and not surviving_excluded
                and actual_retained_partitions == {retained_partition}
                and source_partition_policy_matches
                and (
                    not matching_fields_available_in_output
                    or matching_partitions == {retained_partition}
                )
            )
        elif action_name == "quarantine_evidenced_rows":
            evidenced_positions = (
                set(source_evidence_positions) if identities_valid else set()
            )
            passed = bool(
                valid
                and identities_valid
                and source_evidence_matches
                and evidenced_positions
                and evidenced_positions.isdisjoint(output_position_to_ordinal)
                and evidenced_positions.issubset(quarantine_position_set)
                and (
                    not matching_fields_available_in_output
                    or not matching_output_positions
                )
            )
        else:
            passed = False
        contamination_checks.append(passed)
        row_checks = finding_checks.setdefault(finding_id, {})
        row_checks["contamination_source_evidence_matches"] = bool(
            identities_valid and source_evidence_matches
        )
        row_checks["contamination_evidence_projection_supported"] = (
            output_evidence_projection_supported
        )
        row_checks["selected_contamination_group_policy_verified"] = passed
        finding_verification_basis[finding_id] = (
            "source_row_identity_and_output_matching_fields"
            if matching_fields_available_in_output
            else "source_row_identity_and_verified_projection_after_feature_exclusion"
            if matching_fields_removed_by_plan
            else "source_row_identity_and_matching_field_verification_unavailable"
        )
    if contamination_checks:
        checks["selected_contamination_groups_separated"] = all(
            contamination_checks
        )

    target_exclusion_checks: list[bool] = []
    target_preservation_checks: list[bool] = []
    for action_result in plan.get("action_results", []):
        if not isinstance(action_result, dict) or action_result.get(
            "action"
        ) != "exclude_target_features":
            continue
        target_column = action_result.get("configuration", {}).get(
            "target_column"
        )
        target_preserved = (
            isinstance(target_column, str)
            and target_column in output_frame.columns
        )
        target_preservation_checks.append(target_preserved)
        for finding_id in action_result.get("applied_finding_ids", []):
            snapshot = snapshots_by_id.get(str(finding_id), {})
            evidence = snapshot.get("evidence")
            feature_column = (
                evidence.get("feature_column")
                if isinstance(evidence, dict)
                else None
            )
            excluded = bool(
                isinstance(feature_column, str)
                and feature_column in plan.get("excluded_feature_columns", [])
                and feature_column not in output_frame.columns
            )
            target_exclusion_checks.append(excluded)
            row_checks = finding_checks.setdefault(str(finding_id), {})
            row_checks["selected_target_feature_excluded"] = excluded
            row_checks["selected_target_column_preserved"] = target_preserved
    if target_exclusion_checks:
        checks["selected_target_features_excluded"] = all(target_exclusion_checks)
    if target_preservation_checks:
        checks["selected_target_preserved"] = all(target_preservation_checks)

    skipped_checks: list[dict[str, str]] = []
    check_action_families = [
        (
            "exact_duplicate_groups",
            {"exact_duplicate_keep_first", "quarantine_evidenced_rows"},
            "No supported exact-duplicate action was selected.",
        ),
        (
            "entity_group_separation",
            {"rebuild_group_split", "quarantine_evidenced_rows"},
            "No entity group split or evidence-backed quarantine was selected.",
        ),
        (
            "target_feature_exclusion",
            {"exclude_target_features"},
            "No confirmed target-feature exclusion was selected.",
        ),
        (
            "chronological_order",
            {"rebuild_chronological_split"},
            "No chronological split transformation was selected.",
        ),
        (
            "train_test_contamination",
            {"exclude_contaminated_copies", "quarantine_evidenced_rows"},
            "No contamination exclusion or evidence-backed quarantine was selected.",
        ),
    ]
    for check_name, relevant_actions, reason in check_action_families:
        selected_for_family = any(
            action.get("action") in relevant_actions
            and action.get("applied_finding_ids")
            for action in plan.get("action_results", [])
            if isinstance(action, dict)
        )
        if not selected_for_family:
            skipped_checks.append({"check": check_name, "reason": reason})
    analysis_configuration = plan.get("analysis_configuration", {})
    if (
        isinstance(analysis_configuration, dict)
        and analysis_configuration.get("split_strategy") == "none"
    ):
        skipped_checks.append(
            {
                "check": "split_dependent_detectors",
                "reason": (
                    "Analysis used No Split; entity overlap, temporal leakage, and "
                    "train/test contamination were not evaluated in that analysis."
                ),
            }
        )

    applied_finding_ids = set(plan.get("applied_finding_ids", []))
    all_checks_passed = all(checks.values())
    finding_verification: dict[str, dict[str, Any]] = {}
    for finding_id in sorted(applied_finding_ids):
        row_checks = finding_checks.get(finding_id, {})
        finding_verification[finding_id] = {
            "checks": row_checks,
            "status": (
                "pending_artifact_verification"
                if row_checks and all(value is True for value in row_checks.values())
                else "failed_verification"
            ),
        }
    return {
        "status": "pending_artifact_verification" if all_checks_passed else "failed",
        "checks": checks,
        "skipped_checks": skipped_checks,
        "finding_checks": finding_checks,
        "finding_verification": finding_verification,
        "finding_verification_basis": finding_verification_basis,
        "verified_finding_ids": [],
        "checks_passed": sum(value is True for value in checks.values()),
        "checks_failed": sum(value is not True for value in checks.values()),
        "checks_skipped": len(skipped_checks),
        "all_checks_passed": all_checks_passed,
    }


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    with path.open("x", encoding="utf-8", newline="") as output:
        frame.to_csv(output, index=False)


def _write_report(path: Path, plan: dict[str, Any], verification: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "finding_id",
                "detector_type",
                "action",
                "status",
                "reason",
                "affected_source_row_positions",
                "affected_source_row_positions_sha256",
                "excluded_feature_columns",
            ],
        )
        writer.writeheader()
        verified_ids = set(verification.get("verified_finding_ids", []))
        finding_verification = verification.get("finding_verification", {})
        finding_verification = (
            finding_verification if isinstance(finding_verification, dict) else {}
        )
        skipped_by_id = {
            item["finding_id"]: item["reason"]
            for item in plan.get("skipped_findings", [])
        }
        for action in plan.get("action_results", []):
            action_name = action.get("action")
            applied = set(action.get("applied_finding_ids", []))
            for finding_id in action.get("finding_ids", []):
                snapshot = next(
                    (
                        item
                        for item in plan.get("finding_snapshot", [])
                        if item["id"] == finding_id
                    ),
                    {},
                )
                evidence = snapshot.get("evidence")
                row_positions: list[int] = []
                if isinstance(evidence, dict):
                    raw_positions = evidence.get("row_indices")
                    if isinstance(raw_positions, list):
                        row_positions = sorted(
                            index
                            for index in raw_positions
                            if type(index) is int
                        )
                    elif isinstance(raw_positions, dict):
                        row_positions = sorted(
                            {
                                index
                                for indices in raw_positions.values()
                                if isinstance(indices, list)
                                for index in indices
                                if type(index) is int
                            }
                        )
                    if (
                        action_name
                        in {"exact_duplicate_keep_first", "quarantine_evidenced_rows"}
                        and snapshot.get("finding_type") == "exact_duplicate"
                    ):
                        row_positions = row_positions[1:]
                    if (
                        action_name == "exclude_contaminated_copies"
                        and isinstance(raw_positions, dict)
                    ):
                        retained = action.get("configuration", {}).get(
                            "retained_partition"
                        )
                        row_positions = sorted(
                            {
                                index
                                for partition, indices in raw_positions.items()
                                if _normalize_partition(partition)
                                != _normalize_partition(retained)
                                for index in indices
                                if type(index) is int
                            }
                        )
                row_digest = _sha256_json(row_positions)
                writer.writerow(
                    {
                        "finding_id": finding_id,
                        "detector_type": snapshot.get("finding_type", "unknown"),
                        "action": action_name,
                        "status": (
                            "review_only"
                            if action_name == "review_only"
                            else "included"
                            if finding_id in verified_ids
                            else "failed_verification"
                            if finding_id in applied
                            else "not_applied"
                        ),
                        "reason": skipped_by_id.get(
                            finding_id,
                            finding_verification.get(finding_id, {}).get("reason")
                            if isinstance(
                                finding_verification.get(finding_id), dict
                            )
                            else None
                        ) or (
                            "Selected rule passed its detector-specific post-remediation verification"
                            if finding_id in verified_ids
                            else "Execution or post-remediation verification did not establish this finding as resolved"
                            if finding_id in applied
                            else "Selected for review; no automatic transformation was requested",
                        ),
                        "affected_source_row_positions": json.dumps(row_positions),
                        "affected_source_row_positions_sha256": row_digest,
                        "excluded_feature_columns": json.dumps(
                            plan.get("excluded_feature_columns", [])
                        ),
                    }
                )


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="") as output:
        json.dump(manifest, output, ensure_ascii=False, sort_keys=True, indent=2)


def _owned_plan(
    db: Session,
    dataset_id: str,
    plan_id: str,
    *,
    allowed_owner_id: str,
) -> tuple[models.RepairRecord, models.Dataset]:
    result = (
        db.query(models.RepairRecord, models.Dataset)
        .join(models.Dataset, models.Dataset.id == models.RepairRecord.dataset_id)
        .filter(
            models.RepairRecord.id == plan_id,
            models.RepairRecord.dataset_id == dataset_id,
            models.Dataset.owner_user_id == allowed_owner_id,
            models.RepairRecord.operation_type.in_(
                ["remediation_plan", "consolidated_remediation"]
            ),
        )
        .first()
    )
    if result is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "Remediation plan not found")
    return result


def execute_remediation_plan(
    *,
    db: Session,
    dataset_id: str,
    plan_id: str,
    owner_user_id: str,
    preview_token: str,
    confirmed: bool,
) -> dict[str, Any]:
    record, dataset = _owned_plan(
        db, dataset_id, plan_id, allowed_owner_id=owner_user_id
    )
    plan = record.operation_metadata
    if not isinstance(plan, dict) or plan.get("plan_id") != plan_id:
        raise _http_error(status.HTTP_409_CONFLICT, "Persisted remediation plan is malformed")
    if confirmed is not True:
        raise _http_error(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "Explicit confirmation is required before generating remediation outputs",
        )
    if not isinstance(preview_token, str) or preview_token != plan.get("preview_token"):
        raise _http_error(status.HTTP_409_CONFLICT, "The remediation preview token is invalid")
    if record.status == "completed" and record.operation_type == "consolidated_remediation":
        return _response_for_plan(record)
    if record.status != "previewed" or record.operation_type != "remediation_plan":
        raise _http_error(status.HTTP_409_CONFLICT, "This remediation plan is no longer executable")

    try:
        source_path, source_hash, frame = _source_state(dataset)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_409_CONFLICT:
            record.status = "stale"
            db.commit()
        raise
    if source_hash != record.input_file_sha256 or source_hash != plan.get("original_file_sha256"):
        record.status = "stale"
        db.commit()
        raise _http_error(status.HTTP_409_CONFLICT, "The original dataset changed after preview")

    try:
        action_requests = [
            RemediationActionRequest.model_validate(item)
            for item in plan.get("actions", [])
        ]
        recomputed = _build_plan(
            db=db,
            dataset=dataset,
            source_hash=source_hash,
            frame=frame,
            actions=action_requests,
        )
    except HTTPException:
        record.status = "stale"
        db.commit()
        raise
    if recomputed["preview_digest"] != plan.get("preview_digest"):
        record.status = "stale"
        db.commit()
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "Selected findings or evidence changed after preview; request a new preview",
        )

    record.status = "processing"
    record.operation_type = "consolidated_remediation"
    record.operation_metadata = {
        **plan,
        "execution_status": "processing",
        "user_confirmation": True,
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }
    db.add(record)
    db.commit()
    created_paths: list[Path] = []
    try:
        (
            output_frame,
            quarantine_frame,
            output_source_row_positions,
            quarantine_source_row_positions,
        ) = _execute_transform(frame, plan)
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        output_path = PROCESSED_DIR / plan["final_output_filename"]
        report_path = PROCESSED_DIR / plan["repair_report_filename"]
        manifest_path = PROCESSED_DIR / plan["manifest_filename"]
        _write_csv(output_path, output_frame)
        created_paths.append(output_path)
        quarantine_hash = None
        verified_quarantine = None
        if quarantine_frame is not None and plan.get("quarantine_output_filename"):
            quarantine_path = PROCESSED_DIR / plan["quarantine_output_filename"]
            _write_csv(quarantine_path, quarantine_frame)
            created_paths.append(quarantine_path)
            quarantine_hash = compute_file_sha256(quarantine_path)
            verified_quarantine = pd.read_csv(quarantine_path, dtype=str)
            quarantine_matches = verified_quarantine.equals(
                quarantine_frame.reset_index(drop=True)
            )
        else:
            quarantine_matches = not bool(plan.get("quarantine_source_row_positions"))
        final_hash = compute_file_sha256(output_path)
        verified_output = pd.read_csv(output_path, dtype=str)
        readback_matches = verified_output.equals(output_frame.reset_index(drop=True))
        verification = _verify_plan(
            output_frame=verified_output,
            output_source_row_positions=output_source_row_positions,
            quarantine_frame=verified_quarantine,
            quarantine_source_row_positions=quarantine_source_row_positions,
            source_frame=frame,
            plan=plan,
        )
        verification["checks"]["output_bytes_round_trip_matches"] = readback_matches
        verification["checks"]["quarantine_output_round_trip_matches"] = (
            quarantine_matches
        )
        verification["checks"]["source_sha256_unchanged"] = (
            compute_file_sha256(source_path) == source_hash
        )
        verification["checks"]["final_sha256_matches_output"] = (
            compute_file_sha256(output_path) == final_hash
        )
        verification["source_output_identical"] = verified_output.reset_index(
            drop=True
        ).equals(frame.reset_index(drop=True))
        verification["checks"]["source_output_change_matches_plan"] = (
            not plan.get("expected_output_change", False)
            or not verification["source_output_identical"]
        )
        verification["all_checks_passed"] = all(
            value is True for value in verification["checks"].values()
        )
        applied_finding_ids = set(plan.get("applied_finding_ids", []))
        verified_finding_ids = set(
            _verified_finding_ids(
                plan,
                verification["checks"],
                verification.get("finding_checks", {}),
            )
        )
        detector_results_after = _post_remediation_detector_results(
            verified_output,
            plan.get(
                "detector_configuration",
                plan.get("analysis_configuration", {}),
            ),
        )
        verification["detector_results_before"] = plan.get(
            "detector_results_before", {}
        )
        verification["detector_results_after"] = detector_results_after
        verification["detector_check_counts"] = {
            state: sum(
                check.get("status") == state
                for check in detector_results_after.values()
            )
            for state in ("passed", "failed", "skipped", "review_required")
        }

        # Keep detector-level and selected-finding reporting consistent. A
        # selected finding whose specific source-row postcondition or artifact
        # integrity failed must not be hidden by a zero-count global scan.
        _reconcile_selected_finding_detector_status(
            detector_results_after, plan, verified_finding_ids
        )

        verification["verified_finding_ids"] = sorted(verified_finding_ids)
        finding_verification = verification.get("finding_verification", {})
        for finding_id in sorted(applied_finding_ids):
            row_checks = verification.get("finding_checks", {}).get(
                finding_id, {}
            )
            failed_specific_checks = [
                name for name, passed in row_checks.items() if passed is not True
            ]
            is_verified = finding_id in verified_finding_ids
            finding_verification[finding_id] = {
                "checks": row_checks,
                "status": (
                    "verified"
                    if is_verified
                    else "failed_verification"
                    if failed_specific_checks
                    or not verification["all_checks_passed"]
                    else "review_required"
                ),
                **(
                    {
                        "reason": (
                            "Failed finding-specific checks: "
                            + ", ".join(failed_specific_checks)
                        )
                    }
                    if failed_specific_checks
                    else (
                        {}
                        if is_verified
                        else {
                            "reason": "Required output artifact integrity checks did not pass."
                        }
                    )
                ),
                **(
                    {
                        "verification_basis": verification[
                            "finding_verification_basis"
                        ][finding_id]
                    }
                    if finding_id
                    in verification.get("finding_verification_basis", {})
                    else {}
                ),
            }
        verification["finding_verification"] = finding_verification
        verification["checks_passed"] = sum(
            value is True for value in verification["checks"].values()
        )
        verification["checks_failed"] = sum(
            value is not True for value in verification["checks"].values()
        )
        verification["checks_skipped"] = len(
            verification.get("skipped_checks", [])
        ) + verification["detector_check_counts"]["skipped"]
        verification["all_checks_passed"] = (
            verification["checks_failed"] == 0
        )
        all_applied_verified = (
            bool(applied_finding_ids)
            and applied_finding_ids == verified_finding_ids
            and not plan.get("skipped_findings")
        )
        detector_review_required = any(
            item.get("status") == "review_required"
            for item in detector_results_after.values()
            if isinstance(item, dict)
        )
        verification["status"] = (
            "failed"
            if not verification["all_checks_passed"]
            else "verified"
            if all_applied_verified
            and not detector_review_required
            else "review_required"
        )
        result_status = (
            "failed"
            if not verification["all_checks_passed"]
            else "review_required"
            if verification["status"] == "review_required"
            else "partially_remediated"
            if plan.get("unresolved_findings_count", 0) > 0
            else "fully_remediated_for_selected_rules"
        )

        # Mark findings resolved only after their detector-specific output
        # postcondition and all artifact integrity checks have passed. Findings
        # without a matching verified action remain open and unresolved.
        for finding_id in sorted(verified_finding_ids):
            finding = (
                db.query(leakage_models.LeakageFinding)
                .filter(
                    leakage_models.LeakageFinding.id == finding_id,
                    leakage_models.LeakageFinding.dataset_id == dataset_id,
                    leakage_models.LeakageFinding.status.ilike("open"),
                )
                .first()
            )
            if finding is None:
                continue
            finding.status = "resolved"
            evidence = dict(finding.evidence or {})
            evidence["remediation_verification"] = {
                "operation_id": plan_id,
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "original_file_sha256": source_hash,
                "final_file_sha256": final_hash,
                "status": "verified",
            }
            finding.evidence = evidence
            db.add(finding)

        # Some session factories disable autoflush. Flush verified status
        # changes before querying unresolved findings so the manifest reflects
        # this transaction's actual state, not the pre-execution snapshot.
        db.flush()
        unresolved_rows = (
            db.query(leakage_models.LeakageFinding.id)
            .filter(
                leakage_models.LeakageFinding.dataset_id == dataset_id,
                leakage_models.LeakageFinding.status.ilike("open"),
            )
            .all()
        )
        unresolved_ids = sorted(str(row[0]) for row in unresolved_rows)
        execution_plan = {
            **plan,
            "verified_finding_ids": sorted(verified_finding_ids),
            "finding_verification": finding_verification,
            "unresolved_finding_ids": unresolved_ids,
            "unresolved_findings_count": len(unresolved_ids),
            "missing_value_counts_after": _missing_value_counts(verified_output),
            "source_output_identical": verification["source_output_identical"],
        }
        if result_status == "fully_remediated_for_selected_rules" and unresolved_ids:
            result_status = "partially_remediated"

        report_manifest = {
            "remediation_plan_version": plan.get("version"),
            "plan_id": plan_id,
            "operation_id": plan_id,
            "dataset_id": dataset_id,
            "original_file_sha256": source_hash,
            "final_file_sha256": final_hash,
            "row_identity_scheme": plan.get("row_identity_scheme"),
            "affected_source_row_positions_sha256": plan.get(
                "affected_source_row_positions_sha256"
            ),
            "expected_output_source_row_identities_sha256": plan.get(
                "expected_output_source_row_identities_sha256"
            ),
            "original_row_count": len(frame),
            "final_row_count": len(verified_output),
            "original_column_count": len(frame.columns),
            "final_column_count": len(verified_output.columns),
            "removed_row_count": len(plan.get("rows_to_remove", [])),
            "quarantined_row_count": len(plan.get("quarantine_source_row_positions", [])),
            "target_column": plan.get("remediation_configuration", {}).get(
                "target_column"
            ),
            "entity_column": plan.get("remediation_configuration", {}).get(
                "entity_column"
            ),
            "entity_columns": plan.get("remediation_configuration", {}).get(
                "entity_columns", []
            ),
            "contamination_key_columns": plan.get(
                "remediation_configuration", {}
            ).get("contamination_key_columns", []),
            "timestamp_column": plan.get("remediation_configuration", {}).get(
                "timestamp_column"
            ),
            "temporal_objective": plan.get("remediation_configuration", {}).get(
                "temporal_objective"
            ),
            "split_column": plan.get("remediation_configuration", {}).get(
                "split_column"
            ),
            "split_strategy": plan.get("remediation_configuration", {}).get(
                "split_strategy"
            ),
            "split_cutoff": [
                item.get("cutoff")
                for item in plan.get("split_configurations", [])
                if item.get("kind") == "chronological"
            ],
            "configuration_snapshot": plan.get("analysis_configuration", {}),
            "detector_configuration": plan.get("detector_configuration", {}),
            "configuration_confirmed": plan.get(
                "analysis_configuration", {}
            ).get("configuration_confirmed", False),
            "remediation_configuration": plan.get(
                "remediation_configuration", {}
            ),
            "excluded_feature_columns": plan.get("excluded_feature_columns", []),
            "feature_exclusion_reasons": plan.get(
                "feature_exclusion_reasons", {}
            ),
            "missing_value_counts_before": plan.get(
                "missing_value_counts_before", {}
            ),
            "missing_value_counts_after": _missing_value_counts(verified_output),
            "imputation_strategies": [],
            "detector_counts_before": plan.get("detector_counts_before", {}),
            "detector_results_before": plan.get("detector_results_before", {}),
            "detector_results_after": detector_results_after,
            "split_configurations": plan.get("split_configurations", []),
            "selected_finding_ids": plan.get("selected_finding_ids", []),
            "detector_types": plan.get("detector_types", []),
            "actions": plan.get("action_results", []),
            "affected_source_row_positions": plan.get(
                "affected_source_row_positions", []
            ),
            "affected_source_row_positions_sha256": plan.get(
                "affected_source_row_positions_sha256"
            ),
            "rows_to_remove": plan.get("rows_to_remove", []),
            "quarantine_source_row_positions": plan.get(
                "quarantine_source_row_positions", []
            ),
            "applied_finding_ids": plan.get("applied_finding_ids", []),
            "verified_finding_ids": sorted(verified_finding_ids),
            "skipped_findings": plan.get("skipped_findings", []),
            "unresolved_finding_ids": unresolved_ids,
            "unresolved_findings_count": len(unresolved_ids),
            "skipped_checks": verification.get("skipped_checks", []),
            "verification": verification,
            "quarantine_file_sha256": quarantine_hash,
            "final_status": result_status,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_report(report_path, execution_plan, verification)
        created_paths.append(report_path)
        report_hash = compute_file_sha256(report_path)
        report_manifest["repair_report_sha256"] = report_hash
        report_manifest["quarantine_file_sha256"] = quarantine_hash
        _write_manifest(manifest_path, report_manifest)
        created_paths.append(manifest_path)
        manifest_hash = compute_file_sha256(manifest_path)

        final_metadata = {
            **execution_plan,
            "execution_status": result_status,
            "user_confirmation": True,
            "verification": verification,
            "original_file_sha256": source_hash,
            "final_file_sha256": final_hash,
            "repair_report_sha256": report_hash,
            "manifest_sha256": manifest_hash,
            "quarantine_output_sha256": quarantine_hash,
            "final_row_count": len(verified_output),
            "final_column_count": len(verified_output.columns),
            "removed_row_count": len(plan.get("rows_to_remove", [])),
            "quarantined_row_count": len(plan.get("quarantine_source_row_positions", [])),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "final_status": result_status,
        }
        record.operation_type = "consolidated_remediation"
        record.status = "completed" if verification["all_checks_passed"] else "failed"
        record.output_filename = output_path.name
        record.output_file_sha256 = final_hash
        record.affected_rows = len(execution_plan.get("rows_to_remove", []))
        record.affected_columns = execution_plan.get("excluded_feature_columns", [])
        record.error_info = (
            None
            if verification["all_checks_passed"]
            else {"verification": verification}
        )
        record.operation_metadata = final_metadata
        db.add(record)
        db.commit()
        db.refresh(record)
        result = _response_for_plan(record)
        result["artifact_hashes"] = {
            "dataset": final_hash,
            "repair_report": report_hash,
            "manifest": manifest_hash,
        }
        return result
    except Exception as exc:
        db.rollback()
        for path in created_paths:
            try:
                path.unlink()
            except OSError:
                pass
        failed = db.query(models.RepairRecord).filter(
            models.RepairRecord.id == plan_id
        ).first()
        if failed is not None:
            failed.status = "failed"
            failed.error_info = {"reason": str(exc)[:1000]}
            failed.operation_metadata = {
                **(failed.operation_metadata or {}),
                "execution_status": "failed",
                "failure_reason": str(exc)[:1000],
            }
            db.add(failed)
            db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise _http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Remediation execution failed; the original dataset was not modified",
        ) from exc


def cancel_remediation_plan(
    *,
    db: Session,
    dataset_id: str,
    plan_id: str,
    owner_user_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    record, _ = _owned_plan(
        db, dataset_id, plan_id, allowed_owner_id=owner_user_id
    )
    if record.operation_type != "remediation_plan" or record.status != "previewed":
        raise _http_error(status.HTTP_409_CONFLICT, "Only a pending preview can be cancelled")
    record.status = "cancelled"
    metadata = dict(record.operation_metadata or {})
    metadata["execution_status"] = "cancelled"
    metadata["cancelled_at"] = datetime.now(timezone.utc).isoformat()
    if reason:
        metadata["cancellation_reason"] = reason
    record.operation_metadata = metadata
    db.add(record)
    db.commit()
    db.refresh(record)
    return _response_for_plan(record)


def list_remediation_plans(
    *,
    db: Session,
    dataset_id: str,
    owner_user_id: str,
    skip: int = 0,
    limit: int = 20,
) -> dict[str, Any]:
    dataset = db.query(models.Dataset.id).filter(
        models.Dataset.id == dataset_id,
        models.Dataset.owner_user_id == owner_user_id,
    ).first()
    if dataset is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "Dataset not found")
    query = db.query(models.RepairRecord).filter(
        models.RepairRecord.dataset_id == dataset_id,
        models.RepairRecord.operation_type.in_(
            ["remediation_plan", "consolidated_remediation"]
        ),
    )
    total = query.count()
    records = (
        query.order_by(
            models.RepairRecord.created_at.desc(),
            models.RepairRecord.id.asc(),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {
        "items": [_response_for_plan(record) for record in records],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


def resolve_remediation_artifact(
    *,
    db: Session,
    operation_id: str,
    owner_user_id: str,
    artifact: str,
) -> tuple[Path, str, str]:
    record = (
        db.query(models.RepairRecord)
        .join(models.Dataset, models.Dataset.id == models.RepairRecord.dataset_id)
        .filter(
            models.RepairRecord.id == operation_id,
            models.Dataset.owner_user_id == owner_user_id,
            models.RepairRecord.operation_type == "consolidated_remediation",
            models.RepairRecord.status.in_(["completed", "failed"]),
        )
        .first()
    )
    if record is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "Completed remediation output not found")
    metadata = record.operation_metadata if isinstance(record.operation_metadata, dict) else {}
    artifacts = {
        "dataset": (
            record.output_filename,
            "DataLeakGuard_Final_Cleaned_Dataset.csv",
            record.output_file_sha256,
        ),
        "report": (
            metadata.get("repair_report_filename"),
            "DataLeakGuard_Final_Repair_Report.csv",
            metadata.get("repair_report_sha256"),
        ),
        "manifest": (
            metadata.get("manifest_filename"),
            "DataLeakGuard_Repair_Manifest.json",
            metadata.get("manifest_sha256"),
        ),
        "quarantine": (
            metadata.get("quarantine_output_filename"),
            "DataLeakGuard_Quarantined_Rows.csv",
            metadata.get("quarantine_output_sha256"),
        ),
    }
    if artifact not in artifacts:
        raise _http_error(status.HTTP_404_NOT_FOUND, "Unknown remediation artifact")
    stored_name, download_name, expected_hash = artifacts[artifact]
    if record.status != "completed" and artifact in {"dataset", "quarantine"}:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "Unverified dataset output is unavailable; use the report and manifest to inspect the failure",
        )
    if not isinstance(stored_name, str) or Path(stored_name).name != stored_name:
        raise _http_error(status.HTTP_404_NOT_FOUND, "Requested artifact was not generated")
    root = PROCESSED_DIR.resolve()
    path = (root / stored_name).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise _http_error(status.HTTP_400_BAD_REQUEST, "Stored artifact path is invalid")
    if not path.is_file():
        raise _http_error(status.HTTP_404_NOT_FOUND, "Remediation artifact file is missing")
    if not isinstance(expected_hash, str) or compute_file_sha256(path) != expected_hash:
        raise _http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Remediation artifact failed SHA-256 integrity verification",
        )
    return path, download_name, (
        "application/json"
        if artifact == "manifest"
        else "text/csv; charset=utf-8"
    )
