import hashlib

import pandas as pd
import pytest

from app.db.models import Dataset
from app.services.partition_distribution_service import compare_dataset_partitions
from app.services.profiling_service import profile_dataframe


def _dataset(storage, frame, *, name, stem, split, target):
    filename = f"{stem}.csv"
    original_directory = next(
        value for source, value in storage.items() if source.name == "original"
    )
    path = original_directory / filename
    frame.to_csv(path, index=False)
    profile = profile_dataframe(frame, path, dataset_name=name)
    profile["analysis_columns"] = {
        "split_column": split,
        "target_column": target,
    }
    profile["split_strategy"] = {"strategy": "existing"}
    return Dataset(
        id=f"dataset-{stem}",
        name=name,
        type="tabular",
        format="CSV",
        storage_filename=filename,
        file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        profile=profile,
        sample_count=len(frame),
        feature_count=len(frame.columns),
    )


@pytest.mark.parametrize(
    ("name", "schema"),
    [
        (
            "Manufacturing records",
            {
                "vibration_level": [1, 2, 3, 4, 5, 6, 20, 21, 22, 23, 24, 25],
                "production_line": ["a"] * 6 + ["b"] * 6,
                "quality_state": ["ok", "ok", "review"] * 4,
                "fold_name": ["development"] * 6 + ["holdout"] * 6,
            },
        ),
        (
            "Education records",
            {
                "assessment_points": [40, 42, 43, 44, 46, 48, 80, 82, 83, 84, 86, 88],
                "campus_category": ["north"] * 6 + ["south"] * 6,
                "completion_flag": ["yes", "no"] * 6,
                "evaluation_group": ["learn"] * 6 + ["validate"] * 6,
            },
        ),
    ],
)
def test_partition_comparison_uses_generic_schema_and_user_selected_labels(
    isolated_storage, name, schema
):
    frame = pd.DataFrame(schema)
    split = "fold_name" if "fold_name" in frame else "evaluation_group"
    target = "quality_state" if "quality_state" in frame else "completion_flag"
    labels = sorted(frame[split].unique())
    dataset = _dataset(
        isolated_storage,
        frame,
        name=name,
        stem=f"fixture-{len(frame.columns)}-{labels[0]}",
        split=split,
        target=target,
    )

    result = compare_dataset_partitions(
        dataset,
        reference_partition=labels[0],
        comparison_partition=labels[1],
    )

    assert result["split_column"] == split
    assert result["reference_partition"] == labels[0]
    assert result["comparison_partition"] == labels[1]
    assert result["partition_row_counts"] == {labels[0]: 6, labels[1]: 6}
    assert set(result["features"]) == {
        column for column in frame.columns if column not in {split, target}
    }
    assert result["summary"]["feature_count"] == 2
    assert result["features"][next(
        column for column in result["features"] if frame[column].dtype.kind in "iu"
    )]["kolmogorov_smirnov_statistic"] > 0
    assert result["target"]["status"] == "analyzed"
    assert result["target"]["column"] == target


def test_partition_comparison_requires_saved_split_configuration(isolated_storage, tmp_path):
    source = tmp_path / "unconfigured.csv"
    frame = pd.DataFrame({"measurement": [1, 2], "partition": ["a", "b"]})
    frame.to_csv(source, index=False)
    dataset = Dataset(
        id="without-config",
        name="Unconfigured",
        type="tabular",
        format="CSV",
        storage_filename=source.name,
        profile=profile_dataframe(frame, source),
    )
    # The generic file resolver is storage-scoped; the missing configuration
    # must be rejected before an attempt is made to read this external path.
    with pytest.raises(ValueError, match="persisted split-column configuration"):
        compare_dataset_partitions(
            dataset,
            reference_partition="a",
            comparison_partition="b",
        )


def test_partition_comparison_rejects_missing_and_identical_partition_labels(isolated_storage):
    frame = pd.DataFrame({
        "metric": [1, 2, 3, 4],
        "partition_label": ["alpha", "alpha", "beta", "beta"],
    })
    dataset = _dataset(
        isolated_storage,
        frame,
        name="Arbitrary partitions",
        stem="partition-labels",
        split="partition_label",
        target=None,
    )
    with pytest.raises(ValueError, match="must be different"):
        compare_dataset_partitions(
            dataset,
            reference_partition="alpha",
            comparison_partition="alpha",
        )
    with pytest.raises(ValueError, match="not present"):
        compare_dataset_partitions(
            dataset,
            reference_partition="alpha",
            comparison_partition="not-a-partition",
        )


def test_small_samples_are_marked_insufficient_not_passed(isolated_storage):
    frame = pd.DataFrame({
        "numeric_value": [1, 100],
        "split_marker": ["left", "right"],
    })
    dataset = _dataset(
        isolated_storage,
        frame,
        name="Small fixture",
        stem="small-partitions",
        split="split_marker",
        target=None,
    )
    result = compare_dataset_partitions(
        dataset,
        reference_partition="left",
        comparison_partition="right",
    )
    assert result["features"]["numeric_value"]["status"] == "insufficient_data"
    assert result["summary"]["status"] == "insufficient_data"
    assert result["target"]["status"] == "skipped"
