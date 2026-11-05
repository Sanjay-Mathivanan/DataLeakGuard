"""Reusable schema-independent profiling for uploaded tabular datasets."""

from __future__ import annotations

import os
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


MAX_CATEGORICAL_VALUES = 100
MAX_RARE_CATEGORIES = 20
DATETIME_PARSE_THRESHOLD = 0.7


def read_tabular_frame(file_path: str | Path) -> pd.DataFrame:
    """Load a supported tabular file using the application's existing formats."""
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".xlsx":
        return pd.read_excel(path)
    raise ValueError("Unsupported tabular format")


def parse_datetime_series(series: pd.Series) -> pd.Series:
    """Parse mixed supported datetime formats into UTC without rejecting valid rows."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        try:
            parsed = pd.to_datetime(
                series,
                errors="coerce",
                utc=True,
                format="mixed",
            )
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None and (
            bool(parsed.notna().any()) or not bool(series.notna().any())
        ):
            return parsed
        # Older pandas releases do not implement format="mixed". Retain their
        # normal parser as a compatibility fallback.
        return pd.to_datetime(series, errors="coerce", utc=True)


def _finite_number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if np.isfinite(number) else None


def _is_datetime_column(series: pd.Series) -> tuple[bool, pd.Series]:
    """Recognize actual datetimes and mostly-parseable textual datetime fields."""
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            return True, pd.to_datetime(series, errors="coerce", utc=True)

    if not (
        pd.api.types.is_object_dtype(series.dtype)
        or pd.api.types.is_string_dtype(series.dtype)
    ):
        return False, pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns, UTC]")

    non_null = series.dropna()
    if non_null.empty:
        return False, pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns, UTC]")

    sample = non_null.iloc[: min(len(non_null), 1_000)]
    parsed_sample = parse_datetime_series(sample)
    parse_ratio = float(parsed_sample.notna().mean()) if len(sample) else 0.0
    if parse_ratio < DATETIME_PARSE_THRESHOLD:
        return False, pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns, UTC]")
    parsed = parse_datetime_series(series)
    return True, parsed


def _numeric_profile(series: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return {
            "kind": "numeric",
            "mean": None,
            "median": None,
            "standard_deviation": None,
            "minimum": None,
            "maximum": None,
            "quantiles": {"25": None, "50": None, "75": None},
            "zero_count": 0,
            "negative_count": 0,
        }
    quantiles = values.quantile([0.25, 0.5, 0.75])
    return {
        "kind": "numeric",
        "mean": _finite_number(values.mean()),
        "median": _finite_number(quantiles.loc[0.5]),
        "standard_deviation": _finite_number(values.std(ddof=1)) if len(values) > 1 else None,
        "minimum": _finite_number(values.min()),
        "maximum": _finite_number(values.max()),
        "quantiles": {
            "25": _finite_number(quantiles.loc[0.25]),
            "50": _finite_number(quantiles.loc[0.5]),
            "75": _finite_number(quantiles.loc[0.75]),
        },
        "zero_count": int(values.eq(0).sum()),
        "negative_count": int(values.lt(0).sum()),
    }


def _categorical_profile(series: pd.Series, row_count: int) -> dict[str, Any]:
    counts = series.dropna().astype(str).value_counts(dropna=True)
    total = int(counts.sum())
    denominator = total or 1
    frequencies = [
        {
            "value": str(value),
            "count": int(count),
            "percentage": float(count / denominator * 100),
        }
        for value, count in counts.head(MAX_CATEGORICAL_VALUES).items()
    ]
    rare = [
        item for item in frequencies
        if item["percentage"] < 1.0
    ][:MAX_RARE_CATEGORIES]
    most_frequent = frequencies[0] if frequencies else None
    omitted_count = max(0, len(counts) - len(frequencies))
    return {
        "kind": "categorical",
        "category_count": int(len(counts)),
        "categories": frequencies,
        "categories_truncated": omitted_count > 0,
        "omitted_category_count": omitted_count,
        "most_frequent": most_frequent,
        "rare_categories_below_one_percent": rare,
        "non_null_count": total,
        "row_count": int(row_count),
    }


def _datetime_profile(series: pd.Series, parsed: pd.Series) -> dict[str, Any]:
    non_null_count = int(series.notna().sum())
    invalid_count = max(0, non_null_count - int(parsed.notna().sum()))
    valid = parsed.dropna()
    minimum = valid.min() if not valid.empty else None
    maximum = valid.max() if not valid.empty else None
    return {
        "kind": "datetime",
        "minimum": minimum.isoformat() if minimum is not None else None,
        "maximum": maximum.isoformat() if maximum is not None else None,
        "invalid_or_unparseable_count": invalid_count,
        "missing_timestamp_count": int(series.isna().sum()),
        "time_range_seconds": (
            float((maximum - minimum).total_seconds())
            if minimum is not None and maximum is not None
            else None
        ),
        "timezone_normalization": "UTC",
    }


def profile_dataframe(
    frame: pd.DataFrame,
    file_path: str | Path,
    *,
    dataset_name: str | None = None,
) -> dict[str, Any]:
    """Return bounded profile metadata; raw rows and full category sets are omitted."""
    path = Path(file_path)
    row_count, column_count = int(len(frame)), int(len(frame.columns))
    column_profiles: list[dict[str, Any]] = []

    for column in frame.columns:
        series = frame[column]
        missing_count = int(series.isna().sum())
        non_null_count = int(series.notna().sum())
        unique_count = int(series.nunique(dropna=True))
        duplicate_value_count = max(0, non_null_count - unique_count)
        if pd.api.types.is_numeric_dtype(series.dtype):
            kind = "numeric"
            statistics = _numeric_profile(series)
        else:
            is_datetime, parsed = _is_datetime_column(series)
            if is_datetime:
                kind = "datetime"
                statistics = _datetime_profile(series, parsed)
            else:
                kind = "categorical"
                statistics = _categorical_profile(series, row_count)

        column_profiles.append({
            "name": str(column),
            "dtype": str(series.dtype),
            "kind": kind,
            "non_null_count": non_null_count,
            "missing_count": missing_count,
            "missing_percentage": (
                float(missing_count / row_count * 100) if row_count else None
            ),
            "unique_count": unique_count,
            "duplicate_value_count": duplicate_value_count,
            "statistics": statistics,
        })

    total_cells = row_count * column_count
    total_missing = int(frame.isna().sum().sum())
    duplicate_rows = int(frame.duplicated().sum()) if row_count else 0
    completeness = (
        float((total_cells - total_missing) / total_cells * 100)
        if total_cells
        else None
    )
    duplicate_row_percentage = (
        float(duplicate_rows / row_count * 100) if row_count else None
    )
    try:
        file_size_bytes: int | None = int(os.path.getsize(path))
    except OSError:
        file_size_bytes = None

    return {
        "dataset_name": dataset_name,
        "row_count": row_count,
        "column_count": column_count,
        "file_format": path.suffix.lstrip(".").upper() or None,
        "file_size_bytes": file_size_bytes,
        "memory_usage_bytes": int(frame.memory_usage(index=True, deep=True).sum()),
        "duplicate_row_count": duplicate_rows,
        "total_missing_values": total_missing,
        "data_quality": {
            "completeness_percentage": completeness,
            "duplicate_row_percentage": duplicate_row_percentage,
            "summary": (
                "No cells are available to assess."
                if total_cells == 0
                else (
                    f"{total_missing} missing cell(s) and "
                    f"{duplicate_rows} duplicate row(s) were observed."
                )
            ),
        },
        # Preserve these legacy fields for existing profile consumers.
        "columns": [str(column) for column in frame.columns],
        "dtypes": {str(column): str(dtype) for column, dtype in frame.dtypes.items()},
        "column_profiles": column_profiles,
        "category_value_limit": MAX_CATEGORICAL_VALUES,
        "profiled_at": datetime.now(timezone.utc).isoformat(),
    }


def profile_tabular_file(
    file_path: str | Path,
    *,
    dataset_name: str | None = None,
) -> dict[str, Any]:
    frame = read_tabular_frame(file_path)
    return profile_dataframe(frame, file_path, dataset_name=dataset_name)


def build_dataset_column_metadata(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Adapt detailed profile data to the existing Dataset.columns API shape."""
    metadata: list[dict[str, Any]] = []
    for column in profile.get("column_profiles", []):
        statistics = column.get("statistics") or {}
        legacy_statistics: dict[str, Any] = {"kind": column.get("kind", "other")}
        if column.get("kind") == "numeric":
            legacy_statistics.update({
                "min": statistics.get("minimum"),
                "max": statistics.get("maximum"),
                "mean": statistics.get("mean"),
                "median": statistics.get("median"),
                "standardDeviation": statistics.get("standard_deviation"),
                "quantiles": statistics.get("quantiles", {}),
                "zeroCount": statistics.get("zero_count", 0),
                "negativeCount": statistics.get("negative_count", 0),
            })
        elif column.get("kind") == "categorical":
            legacy_statistics.update({
                "topValues": [
                    {
                        "value": item["value"],
                        "count": item["count"],
                        "percentage": item["percentage"],
                    }
                    for item in statistics.get("categories", [])[:10]
                ],
                "categoryCount": statistics.get("category_count", 0),
                "categoriesTruncated": statistics.get("categories_truncated", False),
                "mostFrequent": statistics.get("most_frequent"),
                "rareCategories": statistics.get("rare_categories_below_one_percent", []),
            })
        elif column.get("kind") == "datetime":
            legacy_statistics.update(statistics)

        metadata.append({
            "name": column.get("name", ""),
            "type": column.get("dtype", "unknown"),
            "kind": column.get("kind", "other"),
            "missingCount": int(column.get("missing_count", 0)),
            "nonNullCount": int(column.get("non_null_count", 0)),
            "missingPercentage": column.get("missing_percentage"),
            "uniqueCount": int(column.get("unique_count", 0)),
            "duplicateValueCount": int(column.get("duplicate_value_count", 0)),
            "statistics": legacy_statistics,
        })
    return metadata
