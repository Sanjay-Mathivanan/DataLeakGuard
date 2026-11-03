from app.utils.operation_metadata import (
    normalize_operation_metadata,
    normalize_operation_response,
)


def test_operation_metadata_normalizes_missing_and_null_skipped_findings_without_claiming_none():
    for value in (None, {}, {"skipped_findings": None}, {"skipped_findings": "legacy"}):
        normalized = normalize_operation_metadata(value)
        assert normalized["skipped_findings"] == []
        assert normalized["skipped_findings_recorded"] is False


def test_operation_metadata_preserves_empty_and_populated_skipped_findings():
    empty = normalize_operation_metadata({"skipped_findings": []})
    assert empty["skipped_findings"] == []
    assert empty["skipped_findings_recorded"] is True

    skipped = [{"finding_id": "finding-1", "reason": "Evidence is stale."}]
    populated = normalize_operation_metadata({
        "selected_finding_ids": ["finding-1"],
        "skipped_findings": skipped,
        "custom_history_field": "preserved",
    })
    assert populated["skipped_findings"] == skipped
    assert populated["skipped_findings_recorded"] is True
    assert populated["selected_finding_ids"] == ["finding-1"]
    assert populated["custom_history_field"] == "preserved"


def test_operation_response_returns_normalized_copy_without_mutating_persisted_metadata():
    stored_metadata = {"strategy": "generated"}
    response = normalize_operation_response({
        "id": "operation-1",
        "operation_metadata": stored_metadata,
    })

    assert response["operation_metadata"] == {
        "strategy": "generated",
        "skipped_findings": [],
        "skipped_findings_recorded": False,
    }
    assert stored_metadata == {"strategy": "generated"}
