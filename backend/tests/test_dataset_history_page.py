from datetime import datetime, timedelta, timezone

import app.db.session
from app.db import models


def _make_dataset(db, owner_id, dataset_id="history-page", name="History Dataset"):
    dataset = models.Dataset(
        id=dataset_id,
        name=name,
        type="tabular",
        format="CSV",
        owner_user_id=owner_id,
        uploaded_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(dataset)
    db.commit()
    return dataset


def test_dataset_history_page_merges_paginates_and_deduplicates(client, test_db):
    db = app.db.session.TestingSessionLocal()
    try:
        owner = db.query(models.User).filter_by(email="test-owner@example.test").one()
        dataset = _make_dataset(db, owner.id)
        dataset_id = dataset.id
        base = datetime(2026, 1, 2, tzinfo=timezone.utc)
        db.add_all([
            models.AuditEvent(
                id="upload-event",
                user_id=owner.id,
                dataset_id=dataset_id,
                event_type="dataset_upload",
                outcome="completed",
                details={"source": "test"},
                created_at=base,
            ),
            models.AuditEvent(
                id="analysis-event",
                user_id=owner.id,
                dataset_id=dataset_id,
                event_type="analysis",
                outcome="completed",
                details={"finding_count": 1},
                created_at=base + timedelta(hours=1),
            ),
            models.AuditEvent(
                id="repair-event",
                user_id=owner.id,
                dataset_id=dataset_id,
                operation_id="repair-operation",
                event_type="repair",
                outcome="completed",
                details={"operation": "remove duplicates"},
                created_at=base + timedelta(hours=2),
            ),
        ])
        db.add_all([
            models.RepairRecord(
                id="repair-operation",
                dataset_id=dataset_id,
                operation_type="repair",
                status="completed",
                input_file_sha256="input",
                output_file_sha256="output",
                output_filename="cleaned.csv",
                affected_rows=1,
                operation_metadata={"removed_rows": 1},
                created_at=base + timedelta(hours=2),
                completed_at=base + timedelta(hours=3),
            ),
            models.RepairRecord(
                id="quarantine-operation",
                dataset_id=dataset_id,
                operation_type="quarantine",
                status="failed",
                input_file_sha256="input",
                affected_rows=0,
                error_info={"reason": "test-only failure reason"},
                created_at=base + timedelta(hours=4),
                completed_at=base + timedelta(hours=5),
            ),
        ])
        db.commit()
    finally:
        db.close()

    response = client.get(
        f"/api/v1/datasets/{dataset_id}/history/page",
        params={"skip": 1, "limit": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert len(body["items"]) == 2
    assert {item["id"] for item in body["items"]}.isdisjoint(
        {"operation:repair-operation"}
    )

    failed = client.get(
        f"/api/v1/datasets/{dataset_id}/history/page",
        params={"event_type": "quarantine", "status": "failed"},
    )
    assert failed.status_code == 200
    failed_item = failed.json()["items"][0]
    assert failed_item["operation_id"] == "quarantine-operation"
    assert failed_item["failure_reason"] == "test-only failure reason"
    assert failed_item["dataset_name"] == "History Dataset"
    assert failed_item["completed_at"].startswith("2026-01-02T05:00:00")
    assert failed_item["details"]["affected_rows"] == 0

    searched = client.get(
        f"/api/v1/datasets/{dataset_id}/history/page",
        params={"search": "quarantine-operation"},
    )
    assert searched.status_code == 200
    assert [item["operation_id"] for item in searched.json()["items"]] == [
        "quarantine-operation"
    ]

    date_filtered = client.get(
        f"/api/v1/datasets/{dataset_id}/history/page",
        params={
            "start_date": "2026-01-02T04:30:00Z",
            "end_date": "2026-01-02T06:00:00Z",
        },
    )
    assert date_filtered.status_code == 200
    assert [item["operation_id"] for item in date_filtered.json()["items"]] == [
        "quarantine-operation"
    ]


def test_dataset_history_page_denies_other_and_legacy_unowned_datasets(client, test_db):
    db = app.db.session.TestingSessionLocal()
    try:
        owner = db.query(models.User).filter_by(email="test-owner@example.test").one()
        other = models.User(
            email="history-other@example.test",
            display_name="Other",
            password_hash="test-only",
        )
        db.add(other)
        db.commit()
        _make_dataset(db, other.id, "other-history")
        _make_dataset(db, owner.id, "unowned-history")
        db.query(models.Dataset).filter_by(id="unowned-history").update(
            {models.Dataset.owner_user_id: None}
        )
        db.commit()
    finally:
        db.close()

    assert client.get("/api/v1/datasets/other-history/history/page").status_code == 404
    assert client.get("/api/v1/datasets/unowned-history/history/page").status_code == 404
