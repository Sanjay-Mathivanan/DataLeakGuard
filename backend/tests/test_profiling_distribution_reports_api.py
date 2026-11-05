import csv
import hashlib
import io
import json

from app.db import models, session
from app.utils.file_storage import ORIGINAL_DIR


def _upload_partitioned_dataset(client):
    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "Partitioned API fixture",
            "type": "tabular",
            "format": "CSV",
            "description": "Disposable profiling, distribution, and report fixture",
        },
        files={
            "file": (
                "partitioned.csv",
                (
                    b"measurement,category,target_label,fold_marker\n"
                    b"1.0,north,ready,development\n"
                    b"2.0,north,ready,development\n"
                    b"3.0,south,review,holdout\n"
                    b"4.0,south,review,holdout\n"
                ),
                "text/csv",
            )
        },
    )
    assert response.status_code == 201, response.text
    dataset = response.json()
    db = session.TestingSessionLocal()
    try:
        persisted = db.query(models.Dataset).filter_by(id=dataset["id"]).one()
        profile = dict(persisted.profile or {})
        profile["analysis_columns"] = {
            "target_column": "target_label",
            "split_column": "fold_marker",
        }
        profile["split_strategy"] = {"strategy": "existing"}
        persisted.profile = profile
        db.add(persisted)
        db.commit()
    finally:
        db.close()
    return dataset


def test_partition_distribution_api_persists_and_retrieves_actual_comparison(client):
    dataset = _upload_partitioned_dataset(client)
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/distribution-analysis",
        json={
            "reference_partition": "development",
            "comparison_partition": "holdout",
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["dataset_id"] == dataset["id"]
    assert created["result"]["split_column"] == "fold_marker"
    assert created["result"]["partition_row_counts"] == {
        "development": 2,
        "holdout": 2,
    }
    assert created["result"]["target"]["column"] == "target_label"
    assert "target_label" not in created["result"]["features"]

    retrieved = client.get(
        f"/api/v1/datasets/{dataset['id']}/distribution-analysis"
    )
    assert retrieved.status_code == 200
    assert retrieved.json()["id"] == created["id"]
    assert retrieved.json()["result"] == created["result"]


def test_partition_distribution_api_validates_configuration_labels_and_ownership(
    client, test_db
):
    dataset = _upload_partitioned_dataset(client)
    invalid_labels = client.post(
        f"/api/v1/datasets/{dataset['id']}/distribution-analysis",
        json={
            "reference_partition": "development",
            "comparison_partition": "missing",
        },
    )
    assert invalid_labels.status_code == 422

    db = session.TestingSessionLocal()
    try:
        owner = db.query(models.User).filter_by(
            email="test-owner@example.test"
        ).one()
        foreign_owner = models.User(
            email="distribution-private@example.test",
            display_name="Private distribution owner",
            password_hash="test-only",
        )
        db.add(foreign_owner)
        db.commit()
        db.refresh(foreign_owner)
        private_dataset = models.Dataset(
            id="private-partition-dataset",
            name="Private",
            type="tabular",
            format="CSV",
            owner_user_id=foreign_owner.id,
        )
        db.add(private_dataset)
        db.commit()
        assert owner.id != foreign_owner.id
    finally:
        db.close()

    assert client.get(
        "/api/v1/datasets/private-partition-dataset/distribution-analysis"
    ).status_code == 404
    assert client.post(
        "/api/v1/datasets/private-partition-dataset/distribution-analysis",
        json={
            "reference_partition": "development",
            "comparison_partition": "holdout",
        },
    ).status_code == 404


def test_partition_distribution_retrieval_rejects_a_changed_source_file(client):
    dataset = _upload_partitioned_dataset(client)
    created = client.post(
        f"/api/v1/datasets/{dataset['id']}/distribution-analysis",
        json={
            "reference_partition": "development",
            "comparison_partition": "holdout",
        },
    )
    assert created.status_code == 201, created.text

    source_path = ORIGINAL_DIR / dataset["storage_filename"]
    source_path.write_bytes(source_path.read_bytes() + b"\n")
    stale = client.get(
        f"/api/v1/datasets/{dataset['id']}/distribution-analysis"
    )
    assert stale.status_code == 409
    assert "SHA-256" in stale.json()["detail"]


def test_report_snapshot_download_formats_and_dataset_ownership(client):
    dataset = _upload_partitioned_dataset(client)
    distribution = client.post(
        f"/api/v1/datasets/{dataset['id']}/distribution-analysis",
        json={
            "reference_partition": "development",
            "comparison_partition": "holdout",
        },
    )
    assert distribution.status_code == 201, distribution.text

    generated = client.post(
        "/api/v1/reports",
        json={"dataset_id": dataset["id"], "title": "Fixture report"},
    )
    assert generated.status_code == 201, generated.text
    record = generated.json()
    assert record["dataset_id"] == dataset["id"]
    dataset_report = record["content"]["dataset_reports"][0]
    assert dataset_report["dataset"]["id"] == dataset["id"]
    assert dataset_report["profiling"]["status"] == "available"
    assert dataset_report["profiling"]["row_count"] == 4
    assert dataset_report["analysis"]["status"] == "not_performed"
    assert dataset_report["distribution_analysis"]["status"] == "available"
    assert dataset_report["distribution_analysis"]["features"]["measurement"]["kind"] == "numeric"
    assert dataset_report["remaining_unresolved_findings"]["count"] == 0

    listed = client.get("/api/v1/reports")
    assert listed.status_code == 200
    assert any(report["id"] == record["id"] for report in listed.json())
    detail = client.get(f"/api/v1/reports/{record['id']}")
    assert detail.status_code == 200
    assert detail.json()["content"] == record["content"]

    json_download = client.get(
        f"/api/v1/reports/{record['id']}/download?format=json"
    )
    assert json_download.status_code == 200
    assert json.loads(json_download.content)["dataset_reports"][0]["dataset"]["id"] == dataset["id"]

    csv_download = client.get(
        f"/api/v1/reports/{record['id']}/download?format=csv"
    )
    assert csv_download.status_code == 200
    csv_rows = list(csv.reader(io.StringIO(csv_download.text)))
    assert csv_rows[0] == ["section", "field", "value"]
    assert any("row_count" in row[1] and "4" in row[2] for row in csv_rows[1:])

    pdf_download = client.get(
        f"/api/v1/reports/{record['id']}/download?format=pdf"
    )
    assert pdf_download.status_code == 200
    assert pdf_download.headers["content-type"] == "application/pdf"
    assert pdf_download.content.startswith(b"%PDF-1.4")
    assert b"%%EOF" in pdf_download.content

    html_download = client.get(
        f"/api/v1/reports/{record['id']}/download?format=html"
    )
    assert html_download.status_code == 200
    assert b"<html>" in html_download.content

    bad_format = client.get(
        f"/api/v1/reports/{record['id']}/download?format=exe"
    )
    assert bad_format.status_code == 400
    assert client.get("/api/v1/reports/nonexistent-report").status_code == 404

    db = session.TestingSessionLocal()
    try:
        foreign_owner = models.User(
            email="report-private@example.test",
            display_name="Private report owner",
            password_hash="test-only",
        )
        db.add(foreign_owner)
        db.commit()
        db.refresh(foreign_owner)
        private_report = models.ReportMetadata(
            owner_user_id=foreign_owner.id,
            dataset_id=dataset["id"],
            title="Private report",
            format="json",
            content_json={},
        )
        db.add(private_report)
        db.commit()
        db.refresh(private_report)
        private_id = private_report.id
    finally:
        db.close()
    assert client.get(f"/api/v1/reports/{private_id}").status_code == 404
    assert client.get(
        f"/api/v1/reports/{private_id}/download?format=json"
    ).status_code == 404


def test_profile_refresh_uses_registered_source_hash_and_does_not_change_source(client):
    dataset = _upload_partitioned_dataset(client)
    source_path = ORIGINAL_DIR / dataset["storage_filename"]
    before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    response = client.post(f"/api/v1/datasets/{dataset['id']}/profiling")
    after = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert response.status_code == 201, response.text
    assert before == after == dataset["file_sha256"]
    assert response.json()["source_file_sha256"] == before


def test_report_marks_profile_findings_and_distribution_stale_if_source_changes(client):
    dataset = _upload_partitioned_dataset(client)
    source_path = ORIGINAL_DIR / dataset["storage_filename"]
    source_path.write_bytes(source_path.read_bytes() + b"\n")

    generated = client.post(
        "/api/v1/reports",
        json={"dataset_id": dataset["id"], "title": "Stale source report"},
    )
    assert generated.status_code == 201, generated.text
    snapshot = generated.json()["content"]["dataset_reports"][0]
    assert snapshot["source_integrity"]["status"] == "failed"
    assert snapshot["profiling"]["status"] == "stale"
    assert snapshot["analysis"]["status"] == "not_performed"
    assert snapshot["leakage"]["status"] == "stale"
    assert snapshot["distribution_analysis"]["status"] == "stale"
