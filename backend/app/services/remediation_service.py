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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException, status
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
    entity_column: str,
    split_column: str,
) -> list[int]:
    evidence = finding.evidence
    if finding.finding_type != "entity_overlap" or not isinstance(evidence, dict):
        raise ValueError("Selected finding is not a structured entity-overlap finding")
    if (
        evidence.get("entity_column") != entity_column
        or evidence.get("split_column") != split_column
    ):
        raise ValueError("Selected columns differ from the persisted entity-overlap evidence")
    row_map, _ = _validate_partitioned_evidence(
        finding, frame, expected_type="entity_overlap", split_column=split_column
    )
    positions = sorted(position for group in row_map.values() for position in group)
    entity_value = evidence.get("entity_value")
    if not isinstance(entity_value, str) or not entity_value.strip():
        raise ValueError("Entity-overlap evidence does not identify an entity")
    if any(_text(frame[entity_column].iloc[position]) != entity_value for position in positions):
        raise ValueError("Entity row positions no longer match the persisted entity value")
    current_positions = [
        position
        for position in range(len(frame))
        if _text(frame[entity_column].iloc[position]) == entity_value
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
    hash_frame = frame.drop(
        columns=[column for column in [split_column] if column in frame.columns]
    )
    id_columns = [column for column in hash_frame.columns if column.lower() == "id"]
    if id_columns:
        hash_frame = hash_frame.drop(columns=id_columns)
    positions = [position for group in row_map.values() for position in group]
    if any(hash_row(hash_frame.iloc[position]) != row_hash for position in positions):
        raise ValueError("Contamination row positions no longer match the persisted row hash")
    if split_column not in hash_cache:
        all_hashes = [hash_row(hash_frame.iloc[position]) for position in range(len(hash_frame))]
        groups: dict[str, dict[str, list[int]]] = {}
        for position, current_hash in enumerate(all_hashes):
            partition = _normalize_partition(frame[split_column].iloc[position])
            if not partition:
                continue
            groups.setdefault(current_hash, {}).setdefault(partition, []).append(position)
        hash_cache[split_column] = (all_hashes, groups)
    _, groups = hash_cache[split_column]
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
        if (
            len(mapping) < 2
            or len(set(mapping.values())) < 2
            or mapping != evidence.get("mapping")
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
    parsed = pd.to_datetime(frame[time_column], errors="coerce", utc=True)
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
            min_time = pd.to_datetime(values.get("min_time"), errors="raise", utc=True)
            max_time = pd.to_datetime(values.get("max_time"), errors="raise", utc=True)
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
    invalid_rows = int((parsed.isna() | split_values.eq("")).sum())
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


def _build_plan(
    *,
    db: Session,
    dataset: models.Dataset,
    source_hash: str,
    frame: pd.DataFrame,
    actions: list[RemediationActionRequest],
) -> dict[str, Any]:
    row_removals: dict[int, list[str]] = {}
    quarantine_positions: set[int] = set()
    split_updates: dict[str, dict[int, str]] = {}
    split_configurations: list[dict[str, Any]] = []
    excluded_columns: set[str] = set()
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
                    to_remove = indices[1:]
                    for position in to_remove:
                        row_removals.setdefault(position, []).append(
                            f"{finding.finding_type}:{finding.id}:{action.action}"
                        )
                    if action.action == "quarantine_evidenced_rows":
                        quarantine_positions.update(to_remove)

                elif action.action == "quarantine_evidenced_rows" and finding.finding_type == "entity_overlap":
                    evidence = finding.evidence or {}
                    entity_column = action.entity_column or evidence.get("entity_column")
                    split_column = action.split_column or evidence.get("split_column")
                    if not isinstance(entity_column, str) or not isinstance(split_column, str):
                        raise ValueError("Entity and split columns are required by the finding evidence")
                    positions = _validate_entity_finding(
                        finding, frame, entity_column, split_column
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
                    for position in positions:
                        row_removals.setdefault(position, []).append(
                            f"train_test_contamination:{finding.id}:quarantine"
                        )
                    quarantine_positions.update(positions)

                elif action.action == "rebuild_group_split":
                    entity_column = action.entity_column
                    split_column = action.split_column
                    if not entity_column or not split_column:
                        raise ValueError("Group-aware split rebuilding requires entity and split columns")
                    if entity_column not in frame.columns or split_column not in frame.columns:
                        raise ValueError("Selected entity or split column does not exist in the source")
                    _validate_entity_finding(finding, frame, entity_column, split_column)

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
        entity_column = action.entity_column
        split_column = action.split_column
        assert entity_column and split_column
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
        if frame[entity_column].isna().any() or any(
            not _text(value) for value in frame[entity_column].tolist()
        ):
            raise _http_error(
                status.HTTP_409_CONFLICT,
                "Group-aware split rebuilding requires a non-missing entity value on every row",
            )
        entities = sorted({_text(value) for value in frame[entity_column].tolist()})
        if len(entities) < 2:
            raise _http_error(
                status.HTTP_409_CONFLICT,
                "At least two distinct entities are required to create a group-aware split",
            )
        ranked_entities = sorted(
            entities,
            key=lambda entity: (
                hashlib.sha256(f"{action.random_seed}:{entity}".encode("utf-8")).hexdigest(),
                entity,
            ),
        )
        test_groups = max(1, min(len(entities) - 1, round(len(entities) * action.test_ratio)))
        test_entities = set(ranked_entities[:test_groups])
        updates = {
            int(position): (
                action.test_label.strip()
                if _text(value) in test_entities
                else action.train_label.strip()
            )
            for position, value in enumerate(frame[entity_column].tolist())
        }
        split_updates.setdefault(split_column, {}).update(updates)
        split_configurations.append(
            {
                "kind": "group_aware",
                "entity_column": entity_column,
                "split_column": split_column,
                "test_ratio": action.test_ratio,
                "random_seed": action.random_seed,
                "algorithm": "sha256_seeded_entity_order_v1",
                "train_label": action.train_label.strip(),
                "test_label": action.test_label.strip(),
                "entity_group_count": len(entities),
                "test_group_count": test_groups,
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
    plan_core = {
        "version": 1,
        "dataset_id": str(dataset.id),
        "original_file_sha256": source_hash,
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
        "quarantine_source_row_positions": sorted(quarantine_positions),
        "excluded_feature_columns": sorted(excluded_columns),
        "split_configurations": split_configurations,
        "split_updates": {
            column: {str(position): label for position, label in sorted(mapping.items())}
            for column, mapping in sorted(split_updates.items())
        },
        "original_row_count": len(frame),
        "expected_final_row_count": len(frame) - len(removed_positions),
        "original_column_count": len(frame.columns),
        "expected_final_column_count": len(final_columns),
        "unresolved_finding_ids": unresolved_ids,
        "unresolved_findings_count": len(unresolved_ids),
    }
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
            "excluded_feature_columns",
            "split_update_count",
            "unresolved_findings_count",
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
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    source = frame.copy()
    rows_to_remove = [int(position) for position in plan.get("rows_to_remove", [])]
    quarantine_positions = [
        int(position)
        for position in plan.get("quarantine_source_row_positions", [])
    ]
    quarantined = source.iloc[quarantine_positions].copy() if quarantine_positions else None
    for column, mapping in plan.get("split_updates", {}).items():
        if column not in source.columns:
            raise ValueError(f"Planned split column '{column}' no longer exists")
        for position_text, label in mapping.items():
            source.iat[int(position_text), source.columns.get_loc(column)] = label
    if rows_to_remove:
        source = source.drop(index=rows_to_remove)
    excluded = plan.get("excluded_feature_columns", [])
    if excluded:
        missing = [column for column in excluded if column not in source.columns]
        if missing:
            raise ValueError("One or more planned feature exclusions are no longer present")
        source = source.drop(columns=excluded)
    return source, quarantined


def _verify_plan(
    *,
    output_frame: pd.DataFrame,
    source_frame: pd.DataFrame,
    plan: dict[str, Any],
) -> dict[str, Any]:
    checks: dict[str, bool] = {
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
    }
    checks["selected_target_preserved"] = all(
        (
            action.get("configuration", {}).get("target_column") is None
            or action.get("configuration", {}).get("target_column") in output_frame.columns
        )
        for action in plan.get("action_results", [])
    )

    # Verify each selected duplicate group after deterministic keep-first
    # removal, using its own persisted hash exclusions.
    duplicate_findings = {
        finding["id"]: finding
        for finding in plan.get("finding_snapshot", [])
        if finding.get("finding_type") == "exact_duplicate"
    }
    exact_duplicate_checks: list[bool] = []
    for action_result in plan.get("action_results", []):
        if action_result.get("action") not in {
            "exact_duplicate_keep_first",
            "quarantine_evidenced_rows",
        }:
            continue
        for finding_id in action_result.get("applied_finding_ids", []):
            snapshot = duplicate_findings.get(finding_id)
            if not snapshot:
                continue
            evidence = snapshot.get("evidence")
            if not isinstance(evidence, dict):
                exact_duplicate_checks.append(False)
                continue
            excluded = evidence.get("hash_excluded_columns", [])
            if not isinstance(excluded, list):
                exact_duplicate_checks.append(False)
                continue
            compare = output_frame.drop(
                columns=[column for column in excluded if column in output_frame.columns]
            )
            original_compare = source_frame.drop(
                columns=[column for column in excluded if column in source_frame.columns]
            )
            indices = evidence.get("row_indices", [])
            if not isinstance(indices, list) or not indices:
                exact_duplicate_checks.append(False)
                continue
            surviving_evidenced_positions = set(int(index) for index in indices).intersection(
                set(int(index) for index in output_frame.index)
            )
            exact_duplicate_checks.append(len(surviving_evidenced_positions) <= 1)
            expected_hash = hash_row(original_compare.iloc[int(indices[0])])
            count = sum(
                hash_row(compare.iloc[position]) == expected_hash
                for position in range(len(compare))
            )
            # A split reassignment or excluded features can make output hashing
            # differ from the source's hash definition. Only assert this check
            # where all original compared columns remain available.
            if (
                len(compare.columns) == len(original_compare.columns)
                and surviving_evidenced_positions
            ):
                exact_duplicate_checks[-1] = exact_duplicate_checks[-1] and count >= 1
    if exact_duplicate_checks:
        checks["selected_exact_duplicate_groups_resolved"] = all(exact_duplicate_checks)

    entity_checks: list[bool] = []
    for config in plan.get("split_configurations", []):
        split_column = config.get("split_column")
        if config.get("kind") == "group_aware":
            entity_column = config.get("entity_column")
            if entity_column not in output_frame.columns or split_column not in output_frame.columns:
                entity_checks.append(False)
            else:
                group_counts = output_frame.groupby(entity_column, dropna=False)[
                    split_column
                ].nunique(dropna=False)
                entity_checks.append(bool((group_counts <= 1).all()))
        elif config.get("kind") == "chronological":
            time_column = config.get("time_column")
            if time_column not in output_frame.columns or split_column not in output_frame.columns:
                checks["chronological_order_verified"] = False
                continue
            parsed = pd.to_datetime(output_frame[time_column], errors="coerce", utc=True)
            train = output_frame.loc[
                output_frame[split_column].astype(str) == config["train_label"], time_column
            ]
            test = output_frame.loc[
                output_frame[split_column].astype(str) == config["test_label"], time_column
            ]
            train_dates = pd.to_datetime(train, errors="coerce", utc=True)
            test_dates = pd.to_datetime(test, errors="coerce", utc=True)
            checks["chronological_order_verified"] = bool(
                not parsed.isna().any()
                and len(train_dates) > 0
                and len(test_dates) > 0
                and train_dates.max() < test_dates.min()
            )
    for action_result in plan.get("action_results", []):
        if action_result.get("action") != "quarantine_evidenced_rows":
            continue
        for snapshot in plan.get("finding_snapshot", []):
            evidence = snapshot.get("evidence")
            if (
                snapshot.get("finding_type") != "entity_overlap"
                or not isinstance(evidence, dict)
                or snapshot["id"] not in action_result.get("finding_ids", [])
            ):
                continue
            entity_column = evidence.get("entity_column")
            split_column = evidence.get("split_column")
            entity_value = evidence.get("entity_value")
            if entity_column not in output_frame.columns or split_column not in output_frame.columns:
                entity_checks.append(False)
                continue
            entity_rows = output_frame[
                output_frame[entity_column].map(_text).eq(entity_value)
            ]
            entity_checks.append(
                entity_rows.empty
                or entity_rows[split_column].nunique(dropna=False) <= 1
            )
    if entity_checks:
        checks["entity_groups_separated"] = all(entity_checks)

    contamination_checks: list[bool] = []
    for action_result in plan.get("action_results", []):
        if action_result.get("action") not in {
            "exclude_contaminated_copies",
            "quarantine_evidenced_rows",
        }:
            continue
        for snapshot in plan.get("finding_snapshot", []):
            evidence = snapshot.get("evidence")
            if (
                snapshot.get("finding_type") != "train_test_contamination"
                or not isinstance(evidence, dict)
                or snapshot["id"] not in action_result.get("finding_ids", [])
            ):
                continue
            split_column = evidence.get("split_column")
            row_hash = evidence.get("row_hash")
            if split_column not in output_frame.columns:
                contamination_checks.append(False)
                continue
            compare = output_frame.drop(
                columns=[
                    column
                    for column in [split_column]
                    + [name for name in output_frame.columns if name.lower() == "id"]
                    if column in output_frame.columns
                ]
            )
            normalized_splits = output_frame[split_column].map(_normalize_partition)
            partitions = {
                normalized_splits.iloc[position]
                for position in range(len(compare))
                if hash_row(compare.iloc[position]) == row_hash
            }
            contamination_checks.append(len(partitions) <= 1)
    if contamination_checks:
        checks["selected_contamination_groups_separated"] = all(contamination_checks)

    return {
        "status": "verified" if all(checks.values()) else "failed",
        "checks": checks,
        "all_checks_passed": all(checks.values()),
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
                            if finding_id in applied and verification["all_checks_passed"]
                            else "failed_verification"
                            if finding_id in applied
                            else "not_applied"
                        ),
                        "reason": skipped_by_id.get(
                            finding_id,
                            "Selected rule was verified in the generated output"
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
        output_frame, quarantine_frame = _execute_transform(frame, plan)
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        output_path = PROCESSED_DIR / plan["final_output_filename"]
        report_path = PROCESSED_DIR / plan["repair_report_filename"]
        manifest_path = PROCESSED_DIR / plan["manifest_filename"]
        _write_csv(output_path, output_frame)
        created_paths.append(output_path)
        quarantine_hash = None
        if quarantine_frame is not None and plan.get("quarantine_output_filename"):
            quarantine_path = PROCESSED_DIR / plan["quarantine_output_filename"]
            _write_csv(quarantine_path, quarantine_frame)
            created_paths.append(quarantine_path)
            quarantine_hash = compute_file_sha256(quarantine_path)
        final_hash = compute_file_sha256(output_path)
        verified_output = pd.read_csv(output_path, dtype=str)
        readback_matches = verified_output.equals(output_frame.reset_index(drop=True))
        verification = _verify_plan(
            output_frame=output_frame,
            source_frame=frame,
            plan=plan,
        )
        verification["checks"]["output_bytes_round_trip_matches"] = readback_matches
        verification["all_checks_passed"] = all(verification["checks"].values())
        verification["status"] = (
            "verified" if verification["all_checks_passed"] else "failed"
        )
        all_applied_verified = (
            verification["all_checks_passed"]
            and not plan.get("skipped_findings")
            and not any(
                action.get("action") == "review_only"
                for action in plan.get("action_results", [])
            )
        )
        result_status = (
            "review_required"
            if not verification["all_checks_passed"] or plan.get("skipped_findings")
            else "partially_remediated"
            if plan.get("unresolved_findings_count", 0) > 0
            else "fully_remediated_for_selected_rules"
        )
        if not all_applied_verified:
            result_status = "review_required"
        report_manifest = {
            "remediation_plan_version": plan.get("version"),
            "plan_id": plan_id,
            "dataset_id": dataset_id,
            "original_file_sha256": source_hash,
            "final_file_sha256": final_hash,
            "original_row_count": len(frame),
            "final_row_count": len(verified_output),
            "removed_row_count": len(plan.get("rows_to_remove", [])),
            "quarantined_row_count": len(plan.get("quarantine_source_row_positions", [])),
            "excluded_feature_columns": plan.get("excluded_feature_columns", []),
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
            "skipped_findings": plan.get("skipped_findings", []),
            "unresolved_findings_count": plan.get("unresolved_findings_count", 0),
            "verification": verification,
            "quarantine_file_sha256": quarantine_hash,
            "final_status": result_status,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_report(report_path, plan, verification)
        created_paths.append(report_path)
        report_hash = compute_file_sha256(report_path)
        report_manifest["repair_report_sha256"] = report_hash
        report_manifest["quarantine_file_sha256"] = quarantine_hash
        _write_manifest(manifest_path, report_manifest)
        created_paths.append(manifest_path)
        manifest_hash = compute_file_sha256(manifest_path)

        final_metadata = {
            **plan,
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
        record.affected_rows = len(plan.get("rows_to_remove", []))
        record.affected_columns = plan.get("excluded_feature_columns", [])
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
