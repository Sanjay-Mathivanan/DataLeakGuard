"""Backward-compatible serializers for persisted operation metadata."""

from __future__ import annotations

from typing import Any


def normalize_operation_metadata(value: Any) -> dict[str, Any]:
    """Return a response-safe metadata mapping without changing persisted data.

    Repair, quarantine, combined-repair, and split-generation records share a
    storage table but have different metadata shapes. Older records may have
    no metadata or predate ``skipped_findings``. In those cases the response
    uses an empty array and marks the details as unavailable rather than
    implying that skipped findings were checked and none existed.
    """
    metadata = dict(value) if isinstance(value, dict) else {}
    skipped_findings = metadata.get("skipped_findings")
    if isinstance(skipped_findings, list):
        metadata["skipped_findings_recorded"] = True
    else:
        metadata["skipped_findings"] = []
        metadata["skipped_findings_recorded"] = False
    return metadata


def normalize_operation_response(value: dict[str, Any]) -> dict[str, Any]:
    """Copy an operation response and standardize its metadata field."""
    response = dict(value)
    response["operation_metadata"] = normalize_operation_metadata(
        response.get("operation_metadata")
    )
    return response
