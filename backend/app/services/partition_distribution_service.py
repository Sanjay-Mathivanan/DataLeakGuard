"""Within-dataset, persisted-partition distribution comparisons."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from app.db.models import Dataset
from app.core.dataset_service import get_dataset_file_path
from app.services.profiling_service import parse_datetime_series, read_tabular_frame


CATEGORY_DISPLAY_LIMIT = 50
PSI_POTENTIAL_SHIFT_THRESHOLD = 0.2
CATEGORICAL_TV_POTENTIAL_SHIFT_THRESHOLD = 0.1


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _ks_statistic(left: np.ndarray, right: np.ndarray) -> float:
    values = np.sort(np.concatenate((left, right)))
    left_sorted, right_sorted = np.sort(left), np.sort(right)
    left_cdf = np.searchsorted(left_sorted, values, side="right") / len(left_sorted)
    right_cdf = np.searchsorted(right_sorted, values, side="right") / len(right_sorted)
    return float(np.max(np.abs(left_cdf - right_cdf))) if len(values) else 0.0


def _asymptotic_ks_pvalue(statistic: float, n_left: int, n_right: int) -> float | None:
    """Two-sided asymptotic KS p-value approximation; ties are not corrected."""
    if min(n_left, n_right) < 5:
        return None
    effective_n = math.sqrt(n_left * n_right / (n_left + n_right))
    z = (effective_n + 0.12 + 0.11 / effective_n) * statistic
    if z <= 0:
        return 1.0
    probability = 0.0
    for index in range(1, 101):
        term = math.exp(-2 * index * index * z * z)
        probability += 2 * term if index % 2 else -2 * term
        if term < 1e-12:
            break
    return min(1.0, max(0.0, probability))


def _numeric_comparison(left: pd.Series, right: pd.Series) -> dict[str, Any]:
    left_values = pd.to_numeric(left, errors="coerce").to_numpy(dtype=float)
    right_values = pd.to_numeric(right, errors="coerce").to_numpy(dtype=float)
    left_values = left_values[np.isfinite(left_values)]
    right_values = right_values[np.isfinite(right_values)]
    base: dict[str, Any] = {
        "kind": "numeric",
        "reference_non_missing": int(len(left_values)),
        "comparison_non_missing": int(len(right_values)),
        "reference_missing": int(left.isna().sum()),
        "comparison_missing": int(right.isna().sum()),
    }
    if min(len(left_values), len(right_values)) < 2:
        return {
            **base,
            "status": "insufficient_data",
            "interpretation": "At least two finite observations per partition are needed.",
        }

    left_series, right_series = pd.Series(left_values), pd.Series(right_values)
    left_quantiles = left_series.quantile([0.25, 0.5, 0.75])
    right_quantiles = right_series.quantile([0.25, 0.5, 0.75])
    pooled = np.concatenate((left_values, right_values))
    edges = np.unique(np.quantile(pooled, np.linspace(0, 1, 11)))
    if len(edges) < 2:
        epsilon = max(abs(float(pooled[0])) * 1e-9, 1e-9)
        edges = np.array([float(pooled[0]) - epsilon, float(pooled[0]) + epsilon])
    else:
        edges[0] = np.nextafter(edges[0], -np.inf)
        edges[-1] = np.nextafter(edges[-1], np.inf)
    left_hist = np.histogram(left_values, bins=edges)[0].astype(float)
    right_hist = np.histogram(right_values, bins=edges)[0].astype(float)
    left_share = left_hist / len(left_values)
    right_share = right_hist / len(right_values)
    left_safe = np.clip(left_share, 1e-6, None)
    right_safe = np.clip(right_share, 1e-6, None)
    psi = float(np.sum((left_share - right_share) * np.log(left_safe / right_safe)))
    overlap = float(np.minimum(left_share, right_share).sum())
    quantile_points = np.linspace(0, 1, 256)
    wasserstein = float(np.mean(np.abs(
        np.quantile(left_values, quantile_points)
        - np.quantile(right_values, quantile_points)
    )))
    ks = _ks_statistic(left_values, right_values)
    p_value = _asymptotic_ks_pvalue(ks, len(left_values), len(right_values))
    if p_value is not None and p_value < 0.05:
        status = "significant_distribution_difference"
        interpretation = (
            "The approximate two-sided KS test detected a difference; this is "
            "a distribution result, not evidence of leakage or causation."
        )
    elif psi >= PSI_POTENTIAL_SHIFT_THRESHOLD:
        status = "potential_distribution_shift"
        interpretation = (
            "The binned PSI exceeded the configured review threshold; this "
            "descriptive threshold does not establish statistical significance or leakage."
        )
    else:
        status = "no_significant_distribution_difference"
        interpretation = (
            "No difference crossed the reported statistical or review thresholds; "
            "this does not prove the distributions are identical."
        )

    return {
        **base,
        "status": status,
        "reference": {
            "mean": _float(left_series.mean()),
            "median": _float(left_series.median()),
            "standard_deviation": _float(left_series.std(ddof=1)),
            "minimum": _float(left_series.min()),
            "maximum": _float(left_series.max()),
            "quantiles": {
                str(int(key * 100)): _float(value)
                for key, value in left_quantiles.items()
            },
        },
        "comparison": {
            "mean": _float(right_series.mean()),
            "median": _float(right_series.median()),
            "standard_deviation": _float(right_series.std(ddof=1)),
            "minimum": _float(right_series.min()),
            "maximum": _float(right_series.max()),
            "quantiles": {
                str(int(key * 100)): _float(value)
                for key, value in right_quantiles.items()
            },
        },
        "mean_difference": _float(right_series.mean() - left_series.mean()),
        "median_difference": _float(right_series.median() - left_series.median()),
        "standard_deviation_difference": _float(
            right_series.std(ddof=1) - left_series.std(ddof=1)
        ),
        "kolmogorov_smirnov_statistic": ks,
        "kolmogorov_smirnov_p_value_approximate": p_value,
        "wasserstein_distance_approximate": wasserstein,
        "population_stability_index": psi,
        "histogram_overlap": overlap,
        "interpretation": interpretation,
        "method_limitations": [
            "PSI bins are derived from pooled observed quantiles.",
            "Wasserstein distance is estimated using 256 empirical quantiles.",
            "The KS p-value is asymptotic and does not correct for ties.",
            "Distribution differences do not by themselves establish leakage.",
        ],
    }


def _categorical_comparison(left: pd.Series, right: pd.Series) -> dict[str, Any]:
    left_counts = left.dropna().astype(str).value_counts()
    right_counts = right.dropna().astype(str).value_counts()
    left_total, right_total = int(left_counts.sum()), int(right_counts.sum())
    base = {
        "kind": "categorical",
        "reference_non_missing": left_total,
        "comparison_non_missing": right_total,
        "reference_missing": int(left.isna().sum()),
        "comparison_missing": int(right.isna().sum()),
        "reference_unique_count": int(len(left_counts)),
        "comparison_unique_count": int(len(right_counts)),
    }
    if left_total == 0 or right_total == 0:
        return {
            **base,
            "status": "insufficient_data",
            "interpretation": "At least one non-missing category is needed in each partition.",
        }

    left_shares = left_counts / left_total
    right_shares = right_counts / right_total
    left_top = set(left_counts.head(CATEGORY_DISPLAY_LIMIT).index)
    right_top = set(right_counts.head(CATEGORY_DISPLAY_LIMIT).index)
    displayed = sorted(left_top | right_top)
    categories = []
    for value in displayed:
        left_count = int(left_counts.get(value, 0))
        right_count = int(right_counts.get(value, 0))
        categories.append({
            "category": value,
            "reference_count": left_count,
            "comparison_count": right_count,
            "reference_percentage": float(left_count / left_total * 100),
            "comparison_percentage": float(right_count / right_total * 100),
        })
    all_categories = set(left_counts.index) | set(right_counts.index)
    total_variation = float(sum(
        abs(float(left_shares.get(value, 0)) - float(right_shares.get(value, 0)))
        for value in all_categories
    ) / 2)
    unseen_reference = sorted(set(right_counts.index) - set(left_counts.index))
    unseen_comparison = sorted(set(left_counts.index) - set(right_counts.index))
    potential_shift = (
        total_variation >= CATEGORICAL_TV_POTENTIAL_SHIFT_THRESHOLD
        or bool(unseen_reference)
        or bool(unseen_comparison)
    )
    return {
        **base,
        "status": (
            "potential_distribution_shift"
            if potential_shift
            else "no_significant_distribution_difference"
        ),
        "categories": categories,
        "categories_truncated": (
            len(left_counts) > CATEGORY_DISPLAY_LIMIT
            or len(right_counts) > CATEGORY_DISPLAY_LIMIT
        ),
        "categories_displayed": len(displayed),
        "unseen_in_reference": unseen_reference[:CATEGORY_DISPLAY_LIMIT],
        "unseen_in_comparison": unseen_comparison[:CATEGORY_DISPLAY_LIMIT],
        "unseen_category_count": len(unseen_reference) + len(unseen_comparison),
        "total_variation_distance": total_variation,
        "interpretation": (
            "Observed category proportions differ or categories are partition-specific. "
            "This descriptive comparison does not establish leakage or causation."
            if potential_shift
            else "No large category-proportion difference was detected at the configured review threshold."
        ),
        "method_limitations": [
            "Only the most frequent categories from each partition are listed.",
            "The total-variation distance uses all observed categories.",
            "Category distribution differences do not by themselves establish leakage.",
        ],
    }


def _datetime_comparison(left: pd.Series, right: pd.Series) -> dict[str, Any]:
    left_dates = parse_datetime_series(left).dropna()
    right_dates = parse_datetime_series(right).dropna()
    result: dict[str, Any] = {
        "kind": "datetime",
        "reference_missing_or_invalid": int(len(left) - len(left_dates)),
        "comparison_missing_or_invalid": int(len(right) - len(right_dates)),
        "status": "insufficient_data",
    }
    if not left_dates.empty and not right_dates.empty:
        left_min, left_max = left_dates.min(), left_dates.max()
        right_min, right_max = right_dates.min(), right_dates.max()
        result.update({
            "reference_minimum": left_min.isoformat(),
            "reference_maximum": left_max.isoformat(),
            "comparison_minimum": right_min.isoformat(),
            "comparison_maximum": right_max.isoformat(),
            "ranges_overlap": bool(left_min <= right_max and right_min <= left_max),
            "status": "descriptive",
            "interpretation": (
                "Timestamp ranges overlap."
                if left_min <= right_max and right_min <= left_max
                else "Timestamp ranges do not overlap."
            ),
        })
    else:
        result["interpretation"] = "A valid timestamp is needed in each partition."
    return result


def _column_kinds(dataset: Dataset) -> dict[str, str]:
    profile = dataset.profile if isinstance(dataset.profile, dict) else {}
    return {
        item["name"]: item.get("kind", "other")
        for item in profile.get("column_profiles", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def compare_dataset_partitions(
    dataset: Dataset,
    *,
    reference_partition: str,
    comparison_partition: str,
) -> dict[str, Any]:
    """Compare two explicitly selected labels from the configured split column."""
    if not reference_partition.strip() or not comparison_partition.strip():
        raise ValueError("Select two non-empty partition labels.")
    reference_partition = reference_partition.strip()
    comparison_partition = comparison_partition.strip()
    if reference_partition == comparison_partition:
        raise ValueError("Reference and comparison partitions must be different.")

    profile = dataset.profile if isinstance(dataset.profile, dict) else {}
    configuration = profile.get("analysis_columns")
    split_column = configuration.get("split_column") if isinstance(configuration, dict) else None
    split_strategy = profile.get("split_strategy")
    if not split_column or (
        isinstance(split_strategy, dict) and split_strategy.get("strategy") == "none"
    ):
        raise ValueError(
            "Partition distribution analysis requires a persisted split-column configuration."
        )
    target_column = configuration.get("target_column")
    if target_column is not None and not isinstance(target_column, str):
        target_column = None

    frame = read_tabular_frame(get_dataset_file_path(dataset))
    if split_column not in frame.columns:
        raise ValueError("The configured split column is not present in the source dataset.")
    normalized_labels = frame[split_column].astype("string").str.strip()
    available_labels = set(normalized_labels.dropna().tolist())
    if reference_partition not in available_labels:
        raise ValueError(f"Reference partition {reference_partition!r} is not present.")
    if comparison_partition not in available_labels:
        raise ValueError(f"Comparison partition {comparison_partition!r} is not present.")

    ref_mask = normalized_labels.eq(reference_partition).fillna(False)
    cmp_mask = normalized_labels.eq(comparison_partition).fillna(False)
    reference_frame = frame.loc[ref_mask]
    comparison_frame = frame.loc[cmp_mask]
    kinds = _column_kinds(dataset)

    features: dict[str, Any] = {}
    for column in frame.columns:
        if column == split_column or column == target_column:
            continue
        left, right = reference_frame[column], comparison_frame[column]
        kind = kinds.get(str(column))
        if kind is None and pd.api.types.is_numeric_dtype(frame[column].dtype):
            kind = "numeric"
        elif kind is None:
            kind = "categorical"
        if kind == "numeric":
            features[str(column)] = _numeric_comparison(left, right)
        elif kind == "datetime":
            features[str(column)] = _datetime_comparison(left, right)
        else:
            features[str(column)] = _categorical_comparison(left, right)

    if target_column and target_column not in frame.columns:
        raise ValueError("The configured target column is not present in the source dataset.")
    if target_column:
        target_values = frame.loc[:, target_column]
        if kinds.get(target_column) == "numeric" or pd.api.types.is_numeric_dtype(target_values.dtype):
            target_comparison = _numeric_comparison(
                reference_frame[target_column],
                comparison_frame[target_column],
            )
        else:
            target_comparison = _categorical_comparison(
                reference_frame[target_column],
                comparison_frame[target_column],
            )
        target_comparison["missing_target_values"] = {
            "reference": int(reference_frame[target_column].isna().sum()),
            "comparison": int(comparison_frame[target_column].isna().sum()),
        }
        if target_comparison.get("kind") == "categorical":
            target_comparison["class_distribution"] = target_comparison.get("categories", [])
        target = {
            "status": "analyzed",
            "column": target_column,
            "distribution_status": target_comparison.get("status"),
            **{
                key: value
                for key, value in target_comparison.items()
                if key != "status"
            },
        }
    else:
        target = {
            "status": "skipped",
            "reason": "No target column is configured; target/class comparison was not performed.",
        }

    result_statuses = [item.get("status") for item in features.values()]
    significant_count = result_statuses.count("significant_distribution_difference")
    potential_count = result_statuses.count("potential_distribution_shift")
    sufficient_count = sum(
        1 for status in result_statuses if status != "insufficient_data"
    )
    if sufficient_count == 0:
        overall_status = "insufficient_data"
    elif significant_count:
        overall_status = "significant_distribution_difference"
    elif potential_count:
        overall_status = "potential_distribution_shift"
    else:
        overall_status = "no_significant_distribution_difference"

    return {
        "dataset_id": dataset.id,
        "dataset_name": dataset.name,
        "source_file_sha256": dataset.file_sha256,
        "split_column": str(split_column),
        "reference_partition": reference_partition,
        "comparison_partition": comparison_partition,
        "partition_row_counts": {
            reference_partition: int(len(reference_frame)),
            comparison_partition: int(len(comparison_frame)),
        },
        "rows_with_other_or_missing_partition": int(
            len(frame) - len(reference_frame) - len(comparison_frame)
        ),
        "target": target,
        "features": features,
        "summary": {
            "status": overall_status,
            "feature_count": len(features),
            "significant_difference_count": significant_count,
            "potential_shift_count": potential_count,
            "insufficient_data_count": result_statuses.count("insufficient_data"),
            "interpretation": (
                "Distribution comparison is descriptive and does not by itself establish leakage, "
                "causation, or model performance degradation."
            ),
        },
        "methodology": {
            "numeric": "Mean/median/standard deviation, extrema, quartiles, approximate KS, approximate Wasserstein, PSI and histogram overlap.",
            "categorical": "Partition frequencies, proportions, unseen categories and total-variation distance.",
            "labels_are_user_selected": True,
            "partition_source": "Persisted analysis split-column configuration.",
        },
    }
