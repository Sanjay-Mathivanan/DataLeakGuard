import app.db.session
from app.db import models
from app.services.column_recommendation_service import recommend_columns


def test_recommendations_score_all_roles_from_stored_profile_signals():
    columns = [
        {
            "name": "risk_category",
            "type": "object",
            "missingCount": 1,
            "uniqueCount": 3,
            "statistics": {
                "kind": "categorical",
                "topValues": [{"value": "low", "count": 6}, {"value": "high", "count": 3}],
            },
        },
        {
            "name": "patient_id",
            "type": "object",
            "missingCount": 0,
            "uniqueCount": 8,
            "statistics": {"kind": "categorical", "topValues": [{"value": "patient-sensitive", "count": 2}]},
        },
        {
            "name": "data_split",
            "type": "object",
            "missingCount": 0,
            "uniqueCount": 3,
            "statistics": {
                "kind": "categorical",
                "topValues": [
                    {"value": "train", "count": 5},
                    {"value": "test", "count": 3},
                    {"value": "validation", "count": 2},
                ],
            },
        },
        {
            "name": "admission_date",
            "type": "object",
            "missingCount": 0,
            "uniqueCount": 4,
            "statistics": {"kind": "categorical", "topValues": []},
        },
    ]
    preview = [
        {
            "risk_category": "low",
            "patient_id": "patient-sensitive",
            "data_split": "train",
            "admission_date": "2026-01-01",
        },
        {
            "risk_category": "high",
            "patient_id": "patient-sensitive",
            "data_split": "test",
            "admission_date": "2026-01-02",
        },
        {
            "risk_category": "medium",
            "patient_id": "patient-3",
            "data_split": "validation",
            "admission_date": "2026-01-03",
        },
    ]

    result = recommend_columns(columns, 10, preview)
    assert result["roles"]["target"]["recommendation"]["column_name"] == "risk_category"
    assert result["roles"]["target"]["recommendation"]["score"] == 80
    assert result["roles"]["entity"]["recommendation"]["column_name"] == "patient_id"
    assert result["roles"]["entity"]["recommendation"]["score"] == 75
    assert result["roles"]["split"]["recommendation"]["column_name"] == "data_split"
    assert result["roles"]["split"]["recommendation"]["score"] == 100
    assert result["roles"]["timestamp"]["recommendation"]["column_name"] == "admission_date"
    assert result["roles"]["timestamp"]["recommendation"]["score"] == 70
    assert result["roles"]["target"]["recommendation"]["confidence"] in {"high", "medium"}
    assert result["roles"]["split"]["recommendation"]["profile"]["recognized_split_labels"] == [
        "test",
        "train",
        "validation",
    ]
    serialized = str(result)
    assert "patient-sensitive" not in serialized
    assert "low" not in result["roles"]["target"]["recommendation"]["profile"].values()
    assert "heuristic" in " ".join(result["limitations"])


def test_recommendations_warn_on_ambiguous_roles_and_do_not_invent_a_split():
    result = recommend_columns(
        [
            {
                "name": "diagnosis",
                "type": "object",
                "uniqueCount": 3,
                "missingCount": 0,
                "statistics": {"kind": "categorical", "topValues": []},
            },
            {
                "name": "risk_category",
                "type": "object",
                "uniqueCount": 3,
                "missingCount": 0,
                "statistics": {"kind": "categorical", "topValues": []},
            },
            {
                "name": "department",
                "type": "object",
                "uniqueCount": 4,
                "missingCount": 0,
                "statistics": {"kind": "categorical", "topValues": []},
            },
            {
                "name": "age",
                "type": "int64",
                "uniqueCount": 50,
                "missingCount": 1,
                "statistics": {"kind": "numeric"},
            },
        ],
        100,
    )
    assert result["roles"]["target"]["recommendation"]["column_name"] in {
        "diagnosis",
        "risk_category",
    }
    assert {
        candidate["column_name"]
        for candidate in result["roles"]["target"]["candidates"][:2]
    } == {"diagnosis", "risk_category"}
    assert any("similar heuristic scores" in warning for warning in result["roles"]["target"]["warnings"])
    assert result["roles"]["split"]["recommendation"] is None
    assert any("Split-dependent detectors" in warning for warning in result["roles"]["split"]["warnings"])
    assert result["roles"]["split"]["candidates"][0]["column_name"] == "department"
    assert result["roles"]["split"]["candidates"][0]["confidence"] == "not_recommended"


def test_readmission_outcome_recommendation_beats_diagnosis_and_derived_features():
    columns = [
        {
            "name": "diagnosis",
            "type": "object",
            "uniqueCount": 4,
            "missingCount": 0,
            "statistics": {"kind": "categorical"},
        },
        {
            "name": "readmitted_30d",
            "type": "object",
            "uniqueCount": 2,
            "missingCount": 0,
            "statistics": {"kind": "categorical"},
        },
        {
            "name": "readmission_flag_copy",
            "type": "object",
            "uniqueCount": 2,
            "missingCount": 0,
            "statistics": {"kind": "categorical"},
        },
        {
            "name": "post_discharge_followup",
            "type": "object",
            "uniqueCount": 2,
            "missingCount": 0,
            "statistics": {"kind": "categorical"},
        },
        {
            "name": "patient_id",
            "type": "object",
            "uniqueCount": 8,
            "missingCount": 0,
            "statistics": {"kind": "categorical"},
        },
    ]
    recommendation = recommend_columns(columns, 8)["roles"]["target"]["recommendation"]
    assert recommendation["column_name"] == "readmitted_30d"
    candidates = {
        candidate["column_name"]: candidate
        for candidate in recommend_columns(columns, 8)["roles"]["target"]["candidates"]
    }
    assert any(
        "possible copied, derived, or post-outcome signal" in warning
        for warning in candidates["readmission_flag_copy"]["warnings"]
    )
    assert candidates["readmission_flag_copy"]["score"] < recommendation["score"]

    # The recommendation remains semantic rather than tied to one dataset.
    other_target = recommend_columns(
        [
            {
                "name": "outcome",
                "type": "object",
                "uniqueCount": 2,
                "missingCount": 0,
                "statistics": {"kind": "categorical"},
            },
            {
                "name": "account_id",
                "type": "object",
                "uniqueCount": 8,
                "missingCount": 0,
                "statistics": {"kind": "categorical"},
            },
        ],
        8,
    )["roles"]["target"]["recommendation"]
    assert other_target["column_name"] == "outcome"


def test_recommendations_handle_missing_profile_and_large_schema_deterministically():
    assert recommend_columns(None, None)["profiled_column_count"] == 0
    large_columns = [
        {
            "name": f"feature_{index}",
            "type": "float64",
            "missingCount": index % 4,
            "uniqueCount": 10,
            "statistics": {"kind": "numeric"},
        }
        for index in range(250)
    ]
    large_columns.extend([
        {
            "name": "target_label",
            "type": "object",
            "missingCount": 120,
            "uniqueCount": 2,
            "statistics": {"kind": "categorical"},
        },
        {
            "name": "person_id",
            "type": "int64",
            "missingCount": 0,
            "uniqueCount": 180,
            "statistics": {"kind": "numeric"},
        },
    ])
    first = recommend_columns(large_columns, 200)
    second = recommend_columns(large_columns, 200)
    assert first == second
    assert first["profiled_column_count"] == 252
    target = first["roles"]["target"]["recommendation"]
    assert target["column_name"] == "target_label"
    assert any("More than half" in warning for warning in target["warnings"])


def test_recommendation_endpoint_is_owner_scoped_and_rejects_unsupported_format(client, test_db):
    db = app.db.session.TestingSessionLocal()
    try:
        owner = db.query(models.User).filter_by(email="test-owner@example.test").one()
        owned = models.Dataset(
            id="recommend-owned",
            name="Synthetic",
            type="tabular",
            format="CSV",
            owner_user_id=owner.id,
            sample_count=10,
            columns=[{
                "name": "target",
                "type": "object",
                "missingCount": 0,
                "uniqueCount": 2,
                "statistics": {"kind": "categorical", "topValues": []},
            }],
            preview_rows=[{"target": "label-a"}],
        )
        other = models.User(
            email="recommend-other@example.test",
            display_name="Other",
            password_hash="test-only",
        )
        db.add(other)
        db.commit()
        db.add(models.Dataset(
            id="recommend-private",
            name="Private",
            type="tabular",
            format="CSV",
            owner_user_id=other.id,
        ))
        db.add(models.Dataset(
            id="recommend-images",
            name="Images",
            type="computer-vision",
            format="ZIP",
            owner_user_id=owner.id,
        ))
        db.add(models.Dataset(
            id="recommend-no-profile",
            name="No profile",
            type="tabular",
            format="CSV",
            owner_user_id=owner.id,
        ))
        db.add(models.Dataset(
            id="recommend-unowned",
            name="Legacy unowned",
            type="tabular",
            format="CSV",
            owner_user_id=owner.id,
        ))
        db.add(owned)
        db.commit()
        db.query(models.Dataset).filter_by(id="recommend-unowned").update(
            {models.Dataset.owner_user_id: None}
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/datasets/recommend-owned/column-recommendations")
    assert response.status_code == 200
    assert response.json()["roles"]["target"]["recommendation"]["column_name"] == "target"
    assert "label-a" not in response.text
    assert client.get(
        "/api/v1/datasets/recommend-private/column-recommendations"
    ).status_code == 404
    assert client.get(
        "/api/v1/datasets/recommend-images/column-recommendations"
    ).status_code == 422
    missing_profile = client.get(
        "/api/v1/datasets/recommend-no-profile/column-recommendations"
    )
    assert missing_profile.status_code == 200
    assert missing_profile.json()["profiled_column_count"] == 0
    assert missing_profile.json()["roles"]["target"]["recommendation"] is None
    assert client.get(
        "/api/v1/datasets/recommend-unowned/column-recommendations"
    ).status_code == 404
