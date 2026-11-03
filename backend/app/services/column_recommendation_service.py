"""Deterministic column-role recommendations based on stored profile metadata.

Scores rank candidates; they are heuristic points, not probabilities.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


SPLIT_LABELS = {
    "train": "train",
    "training": "train",
    "test": "test",
    "testing": "test",
    "validation": "validation",
    "val": "validation",
}

ROLE_ORDER = ("target", "entity", "split", "timestamp")


def _tokens(name: str) -> set[str]:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return set(re.findall(r"[a-z0-9]+", separated.casefold()))


def _number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return None


def _dtype_kind(dtype: str, statistics: dict[str, Any]) -> str:
    value = dtype.casefold()
    if any(marker in value for marker in ("datetime", "timestamp", "date")):
        return "datetime"
    if re.match(r"^(u?int|float|double|decimal|numeric|number)", value):
        return "numeric"
    if statistics.get("kind") == "categorical" or value.startswith(
        ("object", "string", "str", "bool", "category")
    ):
        return "categorical"
    return "other"


def _split_labels(column: dict[str, Any], preview_rows: list[dict[str, Any]]) -> set[str]:
    name = str(column.get("name", ""))
    values: list[Any] = []
    for row in preview_rows[:6]:
        if isinstance(row, dict) and name in row:
            values.append(row[name])
    statistics = column.get("statistics")
    if isinstance(statistics, dict) and isinstance(statistics.get("topValues"), list):
        for entry in statistics["topValues"][:10]:
            if isinstance(entry, dict):
                values.append(entry.get("value"))
    labels = set()
    for value in values:
        if value is None:
            continue
        normalized = str(value).strip().casefold()
        label = SPLIT_LABELS.get(normalized)
        if label:
            labels.add(label)
    return labels


def _parse_datetime(value: Any) -> bool:
    if isinstance(value, (date, datetime)):
        return True
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    if not normalized or len(normalized) > 80:
        return False
    try:
        datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        return True
    except ValueError:
        pass
    for pattern in ("%m/%d/%Y", "%m/%d/%Y %H:%M:%S", "%Y/%m/%d"):
        try:
            datetime.strptime(normalized, pattern)
            return True
        except ValueError:
            continue
    return False


def _confidence(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 55:
        return "medium"
    if score >= 35:
        return "low"
    return "not_recommended"


def _candidate_profile(
    column: dict[str, Any],
    row_count: int | None,
    preview_rows: list[dict[str, Any]],
    split_labels: set[str],
    parsed_datetime_count: int,
) -> dict[str, Any]:
    statistics = column.get("statistics")
    if not isinstance(statistics, dict):
        statistics = {}
    unique_count = _number(column.get("uniqueCount"))
    missing_count = _number(column.get("missingCount"))
    ratio = unique_count / row_count if unique_count is not None and row_count else None
    missing_ratio = missing_count / row_count if missing_count is not None and row_count else None
    return {
        "data_type": str(column.get("type") or "unknown"),
        "kind": _dtype_kind(str(column.get("type") or ""), statistics),
        "unique_count": unique_count,
        "unique_ratio": round(ratio, 4) if ratio is not None else None,
        "missing_count": missing_count,
        "missing_ratio": round(missing_ratio, 4) if missing_ratio is not None else None,
        "sample_count": row_count,
        # Report only recognized partition vocabulary, never arbitrary cell values.
        "recognized_split_labels": sorted(split_labels),
        "datetime_parseable_sample_count": parsed_datetime_count,
        "preview_rows_considered": min(6, len(preview_rows)),
    }


def _score_column(
    role: str,
    column: dict[str, Any],
    row_count: int | None,
    preview_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    name = str(column.get("name") or "")
    tokens = _tokens(name)
    statistics = column.get("statistics")
    if not isinstance(statistics, dict):
        statistics = {}
    kind = _dtype_kind(str(column.get("type") or ""), statistics)
    unique_count = _number(column.get("uniqueCount"))
    missing_count = _number(column.get("missingCount"))
    unique_ratio = (
        unique_count / row_count
        if unique_count is not None and row_count and row_count > 0
        else None
    )
    missing_ratio = (
        missing_count / row_count
        if missing_count is not None and row_count and row_count > 0
        else None
    )
    split_labels = _split_labels(column, preview_rows)
    sample_values = [
        row.get(name)
        for row in preview_rows[:6]
        if isinstance(row, dict) and name in row and row.get(name) is not None
    ]
    parsed_datetime_count = sum(_parse_datetime(value) for value in sample_values)

    score = 0
    signals: list[str] = []
    warnings: list[str] = []

    if role == "target":
        name_scores = {
            "target": 60,
            "label": 55,
            "outcome": 55,
            "readmission": 65,
            "readmitted": 65,
            "diagnosis": 50,
            "risk_category": 50,
            "class": 40,
        }
        matched = [
            (token, points)
            for token, points in name_scores.items()
            if (
                token in tokens
                or (token == "risk_category" and {"risk", "category"}.issubset(tokens))
            )
        ]
        if matched:
            token, points = max(matched, key=lambda item: item[1])
            score += points
            signals.append(f"Column name contains the role token '{token}'.")
        derived_markers = tokens & {
            "after", "copy", "copied", "derived", "duplicate", "followup",
            "proxy", "post",
        }
        if derived_markers:
            score -= 35
            markers = ", ".join(sorted(derived_markers))
            warnings.append(
                "The name contains a possible copied, derived, or post-outcome "
                f"signal ({markers}); do not treat it as the target without manual review."
            )
            signals.append(
                "A possible derived/post-outcome name signal reduced the target-role score."
            )
        if kind == "categorical":
            score += 10
            signals.append("Stored profile identifies categorical values.")
        elif kind == "numeric":
            score += 4
            signals.append("Stored profile identifies numeric values; targets can be numeric.")
        if unique_count is not None and 2 <= unique_count <= 20:
            score += 20
            signals.append("Observed cardinality is compatible with a compact label set.")
        elif unique_count is not None and 21 <= unique_count <= 50:
            score += 8
            warnings.append("The target has more than 20 unique values; verify that it is a label.")
        elif unique_count == 1:
            score -= 25
            warnings.append("Only one unique non-missing value was observed.")
        elif unique_count is not None and unique_count > 50:
            score -= 15
            warnings.append("High cardinality makes this less clearly a target label.")

    elif role == "entity":
        entity_terms = {"patient", "customer", "user", "record", "entity", "subject", "person"}
        has_identifier_token = bool(tokens & {"id", "identifier", "key"})
        named_entity = bool(tokens & entity_terms)
        if named_entity and has_identifier_token:
            score += 55
            signals.append("Column name combines an entity term with an identifier/key token.")
        elif "identifier" in tokens or "key" in tokens:
            score += 45
            signals.append("Column name contains an identifier/key token.")
        elif "id" in tokens:
            score += 32
            signals.append("Column name contains an exact 'id' token.")
        if kind in {"numeric", "categorical"}:
            score += 5
            signals.append("Stored profile type can represent an entity key.")
        if unique_ratio is not None:
            if unique_ratio >= 0.8:
                score += 15
                signals.append("Most rows have distinct identifiers.")
            elif unique_ratio >= 0.2:
                score += 10
                signals.append("Identifier values have useful observed variation.")
            else:
                score += 5
                signals.append("Repeated values are retained as potentially useful entity groups.")

    elif role == "split":
        if tokens & {"split", "partition", "subset", "fold"}:
            score += 55
            signals.append("Column name contains an explicit split/partition token.")
        if len(split_labels) >= 2:
            score += 35
            signals.append("Stored sample/profile values include multiple recognized train/test/validation labels.")
        elif split_labels:
            score += 15
            signals.append("At least one recognized train/test/validation label was observed.")
        if kind == "categorical":
            score += 5
            signals.append("Stored profile identifies categorical values.")
        if unique_count is not None and 2 <= unique_count <= 10:
            score += 8
            signals.append("Observed category count is small enough to plausibly encode partitions.")
        if not (tokens & {"split", "partition", "subset", "fold"}) and not split_labels:
            warnings.append("A small category count alone is not treated as proof of a dataset split.")

    elif role == "timestamp":
        time_tokens = {
            "date", "time", "timestamp", "created", "event", "admission",
            "updated", "occurred", "captured",
        }
        if tokens & time_tokens:
            score += 45
            signals.append("Column name contains a date/time-related token.")
        if kind == "datetime":
            score += 35
            signals.append("Stored profile dtype identifies a date/time column.")
        elif len(sample_values) >= 2 and parsed_datetime_count >= 2:
            score += 20
            signals.append("At least two of up to six stored preview values parse as dates/times.")
        if unique_count is not None and unique_count >= 2:
            score += 5
            signals.append("Observed values have temporal variation.")
        if sample_values and parsed_datetime_count == 0 and kind != "datetime":
            warnings.append("No stored preview value parsed as a date/time.")

    if missing_ratio is not None and missing_ratio > 0.5:
        warnings.append("More than half of rows are missing this column.")
        score -= 10
    elif missing_ratio is not None and missing_ratio > 0.2:
        warnings.append("More than one fifth of rows are missing this column.")
        score -= 5
    if role == "entity" and unique_ratio is not None and unique_ratio < 1:
        signals.append("Entity values need not be unique; repeated keys can support overlap checks.")

    score = max(0, min(100, score))
    confidence = _confidence(score)
    explanation = (
        " ".join(signals)
        if signals
        else "No role-specific name, type, cardinality, or sampled-value signal was found."
    )
    return {
        "column_name": name,
        "role": role,
        "score": score,
        "confidence": confidence,
        "explanation": explanation,
        "supporting_signals": signals,
        "warnings": warnings,
        "profile": _candidate_profile(
            column,
            row_count,
            preview_rows,
            split_labels,
            parsed_datetime_count,
        ),
    }


def recommend_columns(
    columns: list[dict[str, Any]] | None,
    row_count: int | None,
    preview_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rank column candidates for each detector role without selecting config."""
    stored_columns = columns if isinstance(columns, list) else []
    previews = preview_rows if isinstance(preview_rows, list) else []
    normalized_columns = [
        column for column in stored_columns
        if isinstance(column, dict) and isinstance(column.get("name"), str)
    ]
    roles: dict[str, Any] = {}
    for role in ROLE_ORDER:
        ranked = sorted(
            (
                _score_column(role, column, row_count, previews)
                for column in normalized_columns
            ),
            key=lambda candidate: (-candidate["score"], candidate["column_name"].casefold()),
        )
        candidates = ranked[:5]
        top = candidates[0] if candidates else None
        recommendation = top if top and top["score"] >= 50 else None
        warnings: list[str] = []
        if recommendation is None:
            warnings.append("No reliable recommendation; choose a column manually if appropriate.")
        if len(candidates) > 1 and candidates[1]["score"] >= 35 and (
            candidates[0]["score"] - candidates[1]["score"] <= 10
        ):
            warnings.append("Multiple candidates have similar heuristic scores; manually verify the role.")
        if role == "split" and recommendation is None:
            warnings.append("Split-dependent detectors require a manually verified split column.")
        roles[role] = {
            "recommendation": recommendation,
            "candidates": candidates,
            "warnings": warnings,
        }

    limitations = []
    if not normalized_columns:
        limitations.append("Stored column-profile metadata is unavailable.")
    limitations.append(
        "Scores are deterministic heuristic ranking points, not calibrated probabilities or proof of leakage."
    )
    limitations.append(
        "Only stored profile fields and up to six stored preview rows are used; no full dataset rescan or external service is used."
    )
    return {
        "profiled_column_count": len(normalized_columns),
        "sample_count": row_count,
        "roles": roles,
        "limitations": limitations,
    }
