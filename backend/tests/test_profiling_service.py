import pandas as pd
import pytest

from app.services.profiling_service import profile_dataframe, profile_tabular_file


def test_profile_reports_numeric_categorical_datetime_missing_and_duplicates(tmp_path):
    source = tmp_path / "arbitrary-schema.csv"
    frame = pd.DataFrame({
        "measure_value": [0, -2, 4, None, 0],
        "program_group": ["north", "south", "north", None, "north"],
        "logged_when": [
            "2026-01-01T10:00:00+02:00",
            "2026-01-02T10:00:00Z",
            "invalid",
            None,
            "2026-01-01T10:00:00+02:00",
        ],
    })
    frame.to_csv(source, index=False)

    profile = profile_tabular_file(source, dataset_name="Synthetic mixed fixture")
    by_name = {column["name"]: column for column in profile["column_profiles"]}

    assert profile["dataset_name"] == "Synthetic mixed fixture"
    assert profile["row_count"] == 5
    assert profile["column_count"] == 3
    assert profile["file_format"] == "CSV"
    assert profile["file_size_bytes"] == source.stat().st_size
    assert profile["memory_usage_bytes"] > 0
    assert profile["duplicate_row_count"] == 1
    assert profile["total_missing_values"] == 3
    assert profile["data_quality"]["completeness_percentage"] == pytest.approx(80)

    numeric = by_name["measure_value"]
    assert numeric["kind"] == "numeric"
    assert numeric["missing_count"] == 1
    assert numeric["unique_count"] == 3
    assert numeric["statistics"]["mean"] == pytest.approx(0.5)
    assert numeric["statistics"]["median"] == 0
    assert numeric["statistics"]["zero_count"] == 2
    assert numeric["statistics"]["negative_count"] == 1
    assert numeric["statistics"]["quantiles"]["25"] == pytest.approx(-0.5)
    assert numeric["statistics"]["quantiles"]["75"] == pytest.approx(1)

    categorical = by_name["program_group"]
    assert categorical["kind"] == "categorical"
    assert categorical["statistics"]["category_count"] == 2
    assert categorical["statistics"]["most_frequent"]["value"] == "north"
    assert categorical["statistics"]["categories"][0]["percentage"] == pytest.approx(75)

    temporal = by_name["logged_when"]
    assert temporal["kind"] == "datetime"
    assert temporal["statistics"]["invalid_or_unparseable_count"] == 1
    assert temporal["statistics"]["missing_timestamp_count"] == 1
    assert temporal["statistics"]["minimum"].endswith("+00:00")
    assert temporal["statistics"]["maximum"].endswith("+00:00")


def test_profile_bounds_high_cardinality_category_values(tmp_path):
    source = tmp_path / "high-cardinality.csv"
    frame = pd.DataFrame({"opaque_code": [f"code-{index}" for index in range(125)]})
    profile = profile_dataframe(frame, source)
    column = profile["column_profiles"][0]

    assert column["unique_count"] == 125
    assert len(column["statistics"]["categories"]) == 100
    assert column["statistics"]["categories_truncated"] is True
    assert column["statistics"]["omitted_category_count"] == 25


def test_profile_handles_header_only_empty_dataset_without_fake_statistics(tmp_path):
    source = tmp_path / "empty.csv"
    source.write_text("numeric_field,category_field\n", encoding="utf-8")
    profile = profile_tabular_file(source)

    assert profile["row_count"] == 0
    assert profile["column_count"] == 2
    assert profile["duplicate_row_count"] == 0
    assert profile["data_quality"]["completeness_percentage"] is None
    assert all(column["missing_count"] == 0 for column in profile["column_profiles"])
    assert all(
        column["statistics"]["category_count"] == 0
        for column in profile["column_profiles"]
    )


@pytest.mark.parametrize(
    ("domain", "columns"),
    [
        ("manufacturing", {"pressure_reading": [1.5, 2.5], "line_class": ["A", "B"]}),
        ("education", {"assessment_score": [70, 85], "campus_type": ["urban", "rural"]}),
        ("finance", {"balance_delta": [-4, 3], "instrument_group": ["bond", "equity"]}),
        ("retail", {"basket_total": [12, 27], "channel_name": ["store", "web"]}),
    ],
)
def test_profiles_generalize_across_unrelated_domains(tmp_path, domain, columns):
    source = tmp_path / f"{domain}-sample.csv"
    frame = pd.DataFrame(columns)
    profile = profile_dataframe(frame, source, dataset_name=domain)

    assert profile["dataset_name"] == domain
    assert {column["name"] for column in profile["column_profiles"]} == set(columns)
    assert profile["row_count"] == 2
    assert profile["column_count"] == 2
