from app.db import leakage_models, models
import app.db.session


def _add_dataset(db, owner_id, dataset_id):
    dataset = models.Dataset(
        id=dataset_id,
        name=dataset_id,
        type="tabular",
        format="CSV",
        owner_user_id=owner_id,
    )
    db.add(dataset)
    db.commit()
    return dataset


def _add_finding(
    db,
    dataset_id,
    finding_id,
    *,
    finding_type="exact_duplicate",
    severity="medium",
    finding_status="open",
    description="duplicate rows",
    evidence=None,
):
    db.add(
        leakage_models.LeakageFinding(
            id=finding_id,
            dataset_id=dataset_id,
            finding_type=finding_type,
            severity=severity,
            status=finding_status,
            description=description,
            evidence=evidence or {},
        )
    )
    db.commit()


def _make_dataset(test_db, dataset_id="findings-page"):
    db = app.db.session.TestingSessionLocal()
    try:
        owner = db.query(models.User).filter_by(email="test-owner@example.test").one()
        _add_dataset(db, owner.id, dataset_id)
        return owner.id
    finally:
        db.close()


def test_findings_page_uses_bounded_pagination_and_reports_global_counts(client, test_db):
    _make_dataset(test_db)
    db = app.db.session.TestingSessionLocal()
    try:
        for index in range(5):
            _add_finding(
                db,
                "findings-page",
                f"finding-{index}",
                severity=("low", "medium", "high", "critical", "medium")[index],
                finding_status=("open", "resolved", "under_review", "open", "resolved")[index],
            )
    finally:
        db.close()

    first = client.get("/api/v1/datasets/findings-page/findings/page?skip=0&limit=2")
    second = client.get("/api/v1/datasets/findings-page/findings/page?skip=2&limit=2")
    assert first.status_code == second.status_code == 200
    first_body, second_body = first.json(), second.json()
    assert len(first_body["items"]) == len(second_body["items"]) == 2
    assert set(item["id"] for item in first_body["items"]).isdisjoint(
        item["id"] for item in second_body["items"]
    )
    assert first_body["total"] == 5
    assert first_body["dataset_summary"] == {
        "total": 5,
        "open": 2,
        "resolved": 2,
        "low": 1,
        "medium": 2,
        "high": 1,
        "other_severity": 1,
        "status_counts": {"open": 2, "resolved": 2, "under_review": 1},
        "detector_counts": {"exact_duplicate": 5},
    }
    assert client.get(
        "/api/v1/datasets/findings-page/findings/page?limit=101"
    ).status_code == 422


def test_findings_page_searches_id_type_description_and_evidence(client, test_db):
    _make_dataset(test_db)
    db = app.db.session.TestingSessionLocal()
    try:
        _add_finding(
            db,
            "findings-page",
            "id-searchable",
            description="unusual patient overlap",
            evidence={"column_name": "patient_key"},
        )
        _add_finding(
            db,
            "findings-page",
            "type-searchable",
            finding_type="temporal_leakage",
            description="date ordering",
        )
        _add_finding(
            db,
            "findings-page",
            "evidence-searchable",
            evidence={"matched_value": "safe-evidence-marker"},
        )
    finally:
        db.close()

    for term, expected_id in (
        ("id-searchable", "id-searchable"),
        ("temporal", "type-searchable"),
        ("patient overlap", "id-searchable"),
        ("safe-evidence-marker", "evidence-searchable"),
    ):
        response = client.get(
            "/api/v1/datasets/findings-page/findings/page",
            params={"search": term},
        )
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["items"]] == [expected_id]


def test_findings_page_filters_and_matching_summary_are_distinct(client, test_db):
    _make_dataset(test_db)
    db = app.db.session.TestingSessionLocal()
    try:
        _add_finding(
            db,
            "findings-page",
            "exact-high-open",
            severity="high",
            finding_status="open",
        )
        _add_finding(
            db,
            "findings-page",
            "exact-low-resolved",
            severity="low",
            finding_status="resolved",
        )
        _add_finding(
            db,
            "findings-page",
            "future-type",
            finding_type="future_detector",
            severity="informational",
            finding_status="pending",
        )
    finally:
        db.close()

    response = client.get(
        "/api/v1/datasets/findings-page/findings/page",
        params={"finding_type": "exact_duplicate", "severity": "high", "status": "open"},
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == ["exact-high-open"]
    assert body["total"] == 1
    assert body["dataset_summary"]["total"] == 3
    assert body["matching_summary"]["total"] == 1
    assert body["matching_summary"]["open"] == 1
    assert body["matching_summary"]["high"] == 1

    unknown = client.get(
        "/api/v1/datasets/findings-page/findings/page",
        params={"finding_type": "other", "severity": "other"},
    )
    assert unknown.status_code == 200
    assert [item["id"] for item in unknown.json()["items"]] == ["future-type"]


def test_findings_page_rejects_unowned_and_legacy_unowned_datasets(client, test_db):
    db = app.db.session.TestingSessionLocal()
    try:
        current_user = db.query(models.User).filter_by(email="test-owner@example.test").one()
        other_user = models.User(
            email="other-owner@example.test",
            display_name="Other Owner",
            password_hash="test-only",
        )
        db.add(other_user)
        db.commit()
        _add_dataset(db, other_user.id, "other-owned")
        _add_dataset(db, current_user.id, "legacy-unowned")
        db.query(models.Dataset).filter_by(id="legacy-unowned").update(
            {models.Dataset.owner_user_id: None}
        )
        db.commit()
    finally:
        db.close()

    assert client.get(
        "/api/v1/datasets/other-owned/findings/page"
    ).status_code == 404
    assert client.get(
        "/api/v1/datasets/legacy-unowned/findings/page"
    ).status_code == 404
