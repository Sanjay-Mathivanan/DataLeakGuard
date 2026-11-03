import hashlib
import io
from pathlib import Path

import pandas as pd
import pytest
from app.db import leakage_models, models
import app.db.session
from app.services import repair_service
from app.utils.row_hashing import hash_row


CSV_CONTENT = (
    "EmployeeID,Department,Salary\n"
    "E001,IT,50000\n"
    "E002,HR,40000\n"
    "E001,IT,50000\n"
    "E003,Sales,45000\n"
    "E002,HR,40000\n"
).encode()

EXPECTED_CSV = (
    "EmployeeID,Department,Salary\n"
    "E001,IT,50000\n"
    "E002,HR,40000\n"
    "E003,Sales,45000\n"
)


@pytest.fixture
def combined_dataset(client, test_db, tmp_path, monkeypatch):
    original_dir = tmp_path / "original"
    processed_dir = tmp_path / "processed"
    original_dir.mkdir()
    processed_dir.mkdir()
    monkeypatch.setattr(repair_service, "ORIGINAL_DIR", original_dir)
    monkeypatch.setattr(repair_service, "PROCESSED_DIR", processed_dir)
    monkeypatch.setattr("app.api.v1.repairs.PROCESSED_DIR", processed_dir)
    monkeypatch.setattr(
        "app.services.repair_quarantine_utils.ORIGINAL_DIR",
        original_dir,
    )

    dataset_id = "combined-dataset"
    df = pd.read_csv(io.BytesIO(CSV_CONTENT), dtype=str)
    source = original_dir / "source.csv"
    source.write_bytes(CSV_CONTENT)

    db = app.db.session.TestingSessionLocal()
    dataset = models.Dataset(
        id=dataset_id,
        name="Combined repair test",
        type="tabular",
        format="CSV",
        storage_filename=source.name,
        file_sha256=hashlib.sha256(CSV_CONTENT).hexdigest(),
    )
    db.add(dataset)
    db.commit()

    finding_ids = []
    for finding_id, indices in (
        ("duplicate-e001", [0, 2]),
        ("duplicate-e002", [1, 4]),
    ):
        evidence = {
            "hash": hash_row(df.iloc[indices[0]]),
            "duplicate_count": len(indices),
            "row_indices": indices,
        }
        db.add(
            leakage_models.LeakageFinding(
                id=finding_id,
                dataset_id=dataset_id,
                finding_type="exact_duplicate",
                severity="medium",
                status="open",
                description=f"Duplicate rows at {indices}",
                evidence=evidence,
            )
        )
        finding_ids.append(finding_id)
    db.commit()
    db.close()

    return {
        "client": client,
        "dataset_id": dataset_id,
        "finding_ids": finding_ids,
        "original": source,
        "processed_dir": processed_dir,
    }


def preview(client, dataset_id, finding_ids):
    return client.post(
        f"/api/v1/datasets/{dataset_id}/repairs/combined/preview",
        json={"selected_finding_ids": finding_ids},
    )


def generate(client, dataset_id, finding_ids):
    preview_response = preview(client, dataset_id, finding_ids)
    if preview_response.status_code != 200:
        return preview_response
    preview_data = preview_response.json()
    token = preview_data.get("preview_token")
    if not token:
        return preview_response
    return client.post(
        f"/api/v1/datasets/{dataset_id}/repairs/combined",
        json={
            "selected_finding_ids": finding_ids,
            "preview_token": token,
            "confirmed": True,
        },
    )


def test_combined_repair_preview_is_read_only_and_reports_expected_changes(combined_dataset):
    original_bytes = combined_dataset["original"].read_bytes()
    response = preview(
        combined_dataset["client"],
        combined_dataset["dataset_id"],
        combined_dataset["finding_ids"],
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "preview"
    assert result["operation_type"] == "combined_repair_preview"
    assert result["selected_finding_ids"] == sorted(combined_dataset["finding_ids"])
    assert result["applied_finding_ids"] == sorted(combined_dataset["finding_ids"])
    assert result["original_row_count"] == 5
    assert result["final_row_count"] == 3
    assert result["duplicate_rows_removed"] == 2
    assert result["affected_row_indices_preview"] == [2, 4]
    assert result["affected_row_indices_count"] == 2
    assert result["affected_row_indices_truncated"] is False
    assert len(result["affected_row_indices_sha256"]) == 64
    assert result["preview_token"]
    assert combined_dataset["original"].read_bytes() == original_bytes
    assert list(combined_dataset["processed_dir"].iterdir()) == []
    db = app.db.session.TestingSessionLocal()
    assert db.query(models.RepairRecord).filter_by(
        operation_type="combined_repair"
    ).count() == 0
    db.close()


def test_combined_repair_requires_confirmation_and_fresh_preview_token(combined_dataset):
    client = combined_dataset["client"]
    dataset_id = combined_dataset["dataset_id"]
    finding_ids = combined_dataset["finding_ids"]
    endpoint = f"/api/v1/datasets/{dataset_id}/repairs/combined"
    missing_confirmation = client.post(
        endpoint,
        json={"selected_finding_ids": finding_ids, "preview_token": "unused"},
    )
    assert missing_confirmation.status_code == 428
    missing_token = client.post(
        endpoint,
        json={"selected_finding_ids": finding_ids, "confirmed": True},
    )
    assert missing_token.status_code == 428

    stale = client.post(
        endpoint,
        json={
            "selected_finding_ids": finding_ids,
            "preview_token": "0" * 64,
            "confirmed": True,
        },
    )
    assert stale.status_code == 409
    assert list(combined_dataset["processed_dir"].iterdir()) == []


def test_combined_repair_write_failure_leaves_no_partial_output_or_operation(
    combined_dataset, monkeypatch
):
    original_before = combined_dataset["original"].read_bytes()

    def fail_csv_write(*args, **kwargs):
        raise OSError("isolated simulated write failure")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_csv_write)
    response = generate(
        combined_dataset["client"],
        combined_dataset["dataset_id"],
        combined_dataset["finding_ids"],
    )
    assert response.status_code == 500
    assert combined_dataset["original"].read_bytes() == original_before
    assert list(combined_dataset["processed_dir"].iterdir()) == []

    db = app.db.session.TestingSessionLocal()
    try:
        assert db.query(models.RepairRecord).filter_by(
            dataset_id=combined_dataset["dataset_id"],
            operation_type="combined_repair",
        ).count() == 0
    finally:
        db.close()


def test_combined_repair_preview_normalizes_duplicate_selection(combined_dataset):
    client = combined_dataset["client"]
    dataset_id = combined_dataset["dataset_id"]
    first_id = combined_dataset["finding_ids"][0]
    response = preview(client, dataset_id, [first_id, first_id])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["selected_finding_ids"] == [first_id]
    assert result["applied_finding_ids"] == [first_id]
    assert result["duplicate_rows_removed"] == 1


def test_combined_repair_applies_two_findings_once_and_is_idempotent(combined_dataset):
    client = combined_dataset["client"]
    dataset_id = combined_dataset["dataset_id"]
    finding_ids = combined_dataset["finding_ids"]
    original_path = combined_dataset["original"]
    original_bytes = original_path.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()

    first = generate(client, dataset_id, finding_ids)
    assert first.status_code == 201, first.text
    result = first.json()
    assert result["operation_type"] == "combined_repair"
    assert result["status"] == "completed"
    assert result["input_file_sha256"] == original_hash
    assert result["original_row_count"] == 5
    assert result["processed_row_count"] == 3
    assert result["affected_rows"] == 2
    metadata = result["operation_metadata"]
    assert {
        key: metadata[key]
        for key in (
            "selected_finding_ids",
            "applied_finding_ids",
            "skipped_findings",
            "original_row_count",
            "final_row_count",
            "duplicate_rows_removed",
        )
    } == {
        "selected_finding_ids": sorted(finding_ids),
        "applied_finding_ids": sorted(finding_ids),
        "skipped_findings": [],
        "original_row_count": 5,
        "final_row_count": 3,
        "duplicate_rows_removed": 2,
    }
    assert metadata["evidence_reference_finding_ids"] == sorted(finding_ids)
    assert len(metadata["preview_token"]) == 64
    assert metadata["affected_row_indices_preview"] == [2, 4]
    assert metadata["affected_row_indices_count"] == 2
    assert metadata["affected_row_indices_truncated"] is False
    assert len(metadata["affected_row_indices_sha256"]) == 64
    assert result["operation_metadata"]["skipped_findings_recorded"] is True

    output_path = combined_dataset["processed_dir"] / result["output_filename"]
    assert output_path.is_file()
    assert output_path.read_text(encoding="utf-8") == EXPECTED_CSV
    assert result["output_file_sha256"] == hashlib.sha256(output_path.read_bytes()).hexdigest()
    assert original_path.read_bytes() == original_bytes
    assert len(list(combined_dataset["processed_dir"].iterdir())) == 1

    repeated = client.post(
        f"/api/v1/datasets/{dataset_id}/repairs/combined",
        json={
            "selected_finding_ids": list(reversed(finding_ids)),
            "preview_token": metadata["preview_token"],
            "confirmed": True,
        },
    )
    assert repeated.status_code == 201
    assert repeated.json() == result
    assert len(list(combined_dataset["processed_dir"].iterdir())) == 1

    history = client.get(f"/api/v1/datasets/{dataset_id}/repairs")
    assert history.status_code == 200
    records = [row for row in history.json() if row["operation_type"] == "combined_repair"]
    assert len(records) == 1
    assert records[0]["id"] == result["id"]
    assert records[0]["operation_metadata"] == result["operation_metadata"]

    audit_history = client.get(f"/api/v1/datasets/{dataset_id}/history")
    assert audit_history.status_code == 200, audit_history.text
    completed_event = next(
        item for item in audit_history.json()
        if item["event_type"] == "combined_repair"
        and item["operation_id"] == result["id"]
    )
    assert completed_event["outcome"] == "completed"
    assert completed_event["details"]["selected_finding_ids"] == sorted(finding_ids)
    assert completed_event["details"]["affected_row_indices_count"] == 2
    assert completed_event["details"]["affected_row_indices_preview"] == [2, 4]
    assert completed_event["details"]["evidence_reference_finding_ids"] == sorted(finding_ids)


def test_combined_repair_download_verifies_hash_and_serves_output(combined_dataset):
    client = combined_dataset["client"]
    result = generate(
        client,
        combined_dataset["dataset_id"],
        combined_dataset["finding_ids"],
    ).json()

    response = client.get(f"/api/v1/operations/{result['id']}/download")
    assert response.status_code == 200
    assert response.content.decode("utf-8").replace("\r\n", "\n") == EXPECTED_CSV
    assert response.headers["content-disposition"].endswith(
        f'filename="{result["output_filename"]}"'
    )

    output_path = combined_dataset["processed_dir"] / result["output_filename"]
    output_path.write_text("tampered", encoding="utf-8")
    mismatch = client.get(f"/api/v1/operations/{result['id']}/download")
    assert mismatch.status_code == 500
    assert "SHA-256 integrity verification" in mismatch.json()["detail"]


def test_combined_repair_supports_xlsx(combined_dataset):
    client = combined_dataset["client"]
    db = app.db.session.TestingSessionLocal()
    dataset = db.query(models.Dataset).filter_by(
        id=combined_dataset["dataset_id"]
    ).first()
    frame = pd.read_csv(io.BytesIO(CSV_CONTENT), dtype=str)
    buffer = io.BytesIO()
    frame.to_excel(buffer, index=False)
    xlsx_bytes = buffer.getvalue()

    xlsx_path = combined_dataset["original"].with_suffix(".xlsx")
    xlsx_path.write_bytes(xlsx_bytes)
    dataset.storage_filename = xlsx_path.name
    dataset.format = "XLSX"
    dataset.file_sha256 = hashlib.sha256(xlsx_bytes).hexdigest()
    db.commit()
    db.close()

    response = generate(
        client,
        combined_dataset["dataset_id"],
        combined_dataset["finding_ids"],
    )
    assert response.status_code == 201, response.text
    result = response.json()
    output_path = combined_dataset["processed_dir"] / result["output_filename"]
    cleaned = pd.read_excel(output_path, dtype=str)
    assert len(cleaned) == 3
    assert result["output_file_sha256"] == hashlib.sha256(output_path.read_bytes()).hexdigest()
    assert xlsx_path.read_bytes() == xlsx_bytes
    assert output_path.suffix == ".xlsx"


def test_overlapping_duplicate_evidence_does_not_double_count_rows(combined_dataset):
    db = app.db.session.TestingSessionLocal()
    original_frame = pd.read_csv(combined_dataset["original"], dtype=str)
    db.add(
        leakage_models.LeakageFinding(
            id="duplicate-e001-overlap",
            dataset_id=combined_dataset["dataset_id"],
            finding_type="exact_duplicate",
            severity="medium",
            status="open",
            description="Repeated evidence for the same duplicate group",
            evidence={
                "hash": hash_row(original_frame.iloc[0]),
                "duplicate_count": 2,
                "row_indices": [0, 2],
            },
        )
    )
    db.commit()
    db.close()

    response = generate(
        combined_dataset["client"],
        combined_dataset["dataset_id"],
        ["duplicate-e001", "duplicate-e001-overlap"],
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["affected_rows"] == 1
    assert result["operation_metadata"]["duplicate_rows_removed"] == 1
    assert result["processed_row_count"] == 4


def test_combined_repair_matches_split_analysis_duplicate_evidence(
    combined_dataset, monkeypatch
):
    client = combined_dataset["client"]
    dataset_id = combined_dataset["dataset_id"]
    source = combined_dataset["original"]
    monkeypatch.setattr("app.utils.file_storage.ORIGINAL_DIR", source.parent)
    monkeypatch.setattr(
        "app.services.leakage_detection_service.ORIGINAL_DIR", source.parent
    )
    source_bytes = (
        "id,value,split\n"
        "1,alpha,train\n"
        "2,alpha,test\n"
        "3,beta,train\n"
        "4,beta,test\n"
    ).encode()
    source.write_bytes(source_bytes)

    db = app.db.session.TestingSessionLocal()
    dataset = db.query(models.Dataset).filter_by(id=dataset_id).first()
    dataset.file_sha256 = hashlib.sha256(source_bytes).hexdigest()
    db.query(leakage_models.LeakageFinding).filter_by(
        dataset_id=dataset_id
    ).delete(synchronize_session=False)
    db.commit()
    db.close()

    analysis = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage",
        params={"split_column": "split"},
    )
    assert analysis.status_code == 200, analysis.text
    exact_findings = [
        finding
        for finding in analysis.json()["findings"]
        if finding["finding_type"] == "exact_duplicate"
    ]
    assert len(exact_findings) == 2
    assert all(
        finding["evidence"]["hash_excluded_columns"] == ["id", "split"]
        for finding in exact_findings
    )

    # Repeating the same analysis configuration must reuse the persisted
    # findings while retaining their hash configuration.
    repeated_analysis = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage",
        params={"split_column": "split"},
    )
    assert repeated_analysis.status_code == 200, repeated_analysis.text
    repeated_exact_findings = [
        finding
        for finding in repeated_analysis.json()["findings"]
        if finding["finding_type"] == "exact_duplicate"
    ]
    assert {finding["id"] for finding in repeated_exact_findings} == {
        finding["id"] for finding in exact_findings
    }

    # Later analysis settings must not invalidate already-persisted evidence.
    latest_analysis = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage"
    )
    assert latest_analysis.status_code == 200, latest_analysis.text

    response = generate(
        client,
        dataset_id,
        [finding["id"] for finding in exact_findings],
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["original_row_count"] == 4
    assert result["processed_row_count"] == 2
    assert result["affected_rows"] == 2
    assert result["operation_metadata"]["applied_finding_ids"] == sorted(
        finding["id"] for finding in exact_findings
    )
    assert result["operation_metadata"]["skipped_findings"] == []
    assert source.read_bytes() == source_bytes


def test_combined_repair_rejects_unknown_empty_cross_dataset_and_non_duplicate(
    combined_dataset,
):
    client = combined_dataset["client"]
    dataset_id = combined_dataset["dataset_id"]
    assert generate(client, "unknown-dataset", combined_dataset["finding_ids"]).status_code == 404
    assert generate(client, dataset_id, []).status_code == 422
    assert generate(client, dataset_id, ["missing-finding"]).status_code == 404

    db = app.db.session.TestingSessionLocal()
    db.add(
        models.Dataset(
            id="other-dataset",
            name="Other",
            type="tabular",
            format="CSV",
            storage_filename="source.csv",
            file_sha256=hashlib.sha256(CSV_CONTENT).hexdigest(),
        )
    )
    db.flush()
    db.add(
        leakage_models.LeakageFinding(
            id="cross-dataset-finding",
            dataset_id="other-dataset",
            finding_type="exact_duplicate",
            severity="medium",
            status="open",
            description="Cross dataset",
            evidence={"hash": "unused", "duplicate_count": 2, "row_indices": [0, 1]},
        )
    )
    db.add(
        leakage_models.LeakageFinding(
            id="not-a-duplicate",
            dataset_id=dataset_id,
            finding_type="target_leakage",
            severity="medium",
            status="open",
            description="Unsupported operation",
            evidence={},
        )
    )
    db.commit()
    db.close()

    cross_dataset = generate(client, dataset_id, ["cross-dataset-finding"])
    assert cross_dataset.status_code == 400
    non_duplicate = generate(client, dataset_id, ["not-a-duplicate"])
    assert non_duplicate.status_code == 200
    assert non_duplicate.json()["status"] == "not_eligible"
    assert non_duplicate.json()["skipped_findings"] == [{
        "finding_id": "not-a-duplicate",
        "reason": (
            "Combined cleaning supports exact_duplicate findings only; "
            "'target_leakage' is not eligible."
        ),
    }]
    assert list(combined_dataset["processed_dir"].iterdir()) == []


def test_combined_repair_preview_excludes_mixed_ineligible_findings(combined_dataset):
    db = app.db.session.TestingSessionLocal()
    db.add(
        leakage_models.LeakageFinding(
            id="unsupported-finding",
            dataset_id=combined_dataset["dataset_id"],
            finding_type="temporal_leakage",
            severity="high",
            status="open",
            description="Temporal issue is not eligible for combined cleaning.",
            evidence={},
        )
    )
    db.commit()
    db.close()

    response = preview(
        combined_dataset["client"],
        combined_dataset["dataset_id"],
        [combined_dataset["finding_ids"][0], "unsupported-finding"],
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "preview"
    assert result["applied_finding_ids"] == [combined_dataset["finding_ids"][0]]
    assert result["skipped_findings"] == [{
        "finding_id": "unsupported-finding",
        "reason": (
            "Combined cleaning supports exact_duplicate findings only; "
            "'temporal_leakage' is not eligible."
        ),
    }]


def test_combined_repair_skips_resolved_and_stale_findings(combined_dataset):
    db = app.db.session.TestingSessionLocal()
    resolved = db.query(leakage_models.LeakageFinding).filter_by(
        id="duplicate-e002"
    ).first()
    resolved.status = "resolved"
    db.add(
        leakage_models.LeakageFinding(
            id="stale-duplicate",
            dataset_id=combined_dataset["dataset_id"],
            finding_type="exact_duplicate",
            severity="medium",
            status="open",
            description="Stale evidence",
            evidence={
                "hash": "0" * 64,
                "duplicate_count": 2,
                "row_indices": [1, 4],
            },
        )
    )
    db.commit()
    db.close()

    response = generate(
        combined_dataset["client"],
        combined_dataset["dataset_id"],
        ["duplicate-e001", "duplicate-e002", "stale-duplicate"],
    )
    assert response.status_code == 201, response.text
    metadata = response.json()["operation_metadata"]
    assert metadata["applied_finding_ids"] == ["duplicate-e001"]
    assert {item["finding_id"] for item in metadata["skipped_findings"]} == {
        "duplicate-e002",
        "stale-duplicate",
    }
    assert len(list(combined_dataset["processed_dir"].iterdir())) == 1

    all_skipped = generate(
        combined_dataset["client"],
        combined_dataset["dataset_id"],
        ["duplicate-e002"],
    )
    assert all_skipped.status_code == 200
    assert all_skipped.json()["status"] == "not_eligible"
    assert all_skipped.json()["skipped_findings"] == [{
        "finding_id": "duplicate-e002",
        "reason": "Finding status is 'resolved', not 'open'.",
    }]
    assert len(list(combined_dataset["processed_dir"].iterdir())) == 1


def test_combined_repair_skips_finding_already_repaired_individually(combined_dataset):
    db = app.db.session.TestingSessionLocal()
    db.add(
        models.RepairRecord(
            id="prior-individual-repair",
            dataset_id=combined_dataset["dataset_id"],
            finding_id="duplicate-e002",
            operation_type="repair",
            status="completed",
            input_file_sha256=hashlib.sha256(CSV_CONTENT).hexdigest(),
            output_file_sha256="0" * 64,
            output_filename="prior.csv",
            affected_rows=1,
        )
    )
    db.commit()
    db.close()

    response = generate(
        combined_dataset["client"],
        combined_dataset["dataset_id"],
        combined_dataset["finding_ids"],
    )
    assert response.status_code == 201, response.text
    metadata = response.json()["operation_metadata"]
    assert metadata["applied_finding_ids"] == ["duplicate-e001"]
    assert metadata["skipped_findings"] == [{
        "finding_id": "duplicate-e002",
        "reason": "Finding was already included in a completed repair.",
    }]


def test_combined_repair_generation_failure_does_not_persist_completed_record(
    combined_dataset, monkeypatch
):
    real_hash = repair_service.compute_file_sha256
    calls = 0

    def fail_output_hash(path: Path) -> str:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated output hashing failure")
        return real_hash(path)

    monkeypatch.setattr(repair_service, "compute_file_sha256", fail_output_hash)
    response = generate(
        combined_dataset["client"],
        combined_dataset["dataset_id"],
        combined_dataset["finding_ids"],
    )
    assert response.status_code == 500

    db = app.db.session.TestingSessionLocal()
    records = db.query(models.RepairRecord).filter_by(
        operation_type="combined_repair"
    ).all()
    db.close()
    assert records == []
    assert list(combined_dataset["processed_dir"].iterdir()) == []
