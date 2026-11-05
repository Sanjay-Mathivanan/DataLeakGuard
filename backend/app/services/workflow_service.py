from __future__ import annotations

import html
import json
import math
import csv
import io
import textwrap
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.db import leakage_models, models
from app.core.dataset_service import get_dataset_file_path, verify_dataset_integrity


def _frame(dataset: models.Dataset) -> pd.DataFrame:
    path = get_dataset_file_path(dataset)
    return pd.read_csv(path) if dataset.format.upper() == "CSV" else pd.read_excel(path)


def distribution_metrics(reference: models.Dataset, comparison: models.Dataset) -> dict[str, Any]:
    left, right = _frame(reference), _frame(comparison)
    result: dict[str, Any] = {}
    for column in sorted(set(left.columns) | set(right.columns)):
        l = left[column] if column in left else pd.Series(dtype="object")
        r = right[column] if column in right else pd.Series(dtype="object")
        missing_delta = float(l.isna().mean() - r.isna().mean())
        if pd.api.types.is_numeric_dtype(l) and pd.api.types.is_numeric_dtype(r):
            values = pd.concat([pd.to_numeric(l, errors="coerce"), pd.to_numeric(r, errors="coerce")]).dropna()
            if values.empty:
                psi = 0.0
            else:
                edges = values.quantile([0, .2, .4, .6, .8, 1]).drop_duplicates().to_numpy()
                if len(edges) < 2:
                    psi = 0.0
                else:
                    a = pd.cut(pd.to_numeric(l, errors="coerce"), bins=edges, include_lowest=True).value_counts(normalize=True, sort=False)
                    b = pd.cut(pd.to_numeric(r, errors="coerce"), bins=edges, include_lowest=True).value_counts(normalize=True, sort=False)
                    psi = sum((x - y) * math.log(x / y) for x, y in zip(a.clip(lower=1e-6), b.clip(lower=1e-6)))
            result[str(column)] = {"kind": "numeric", "psi": float(psi), "missing_delta": missing_delta}
        else:
            a = l.dropna().astype(str).value_counts(normalize=True)
            b = r.dropna().astype(str).value_counts(normalize=True)
            keys = set(a.index) | set(b.index)
            delta = sum(abs(float(a.get(k, 0)) - float(b.get(k, 0))) for k in keys) / 2
            result[str(column)] = {"kind": "categorical", "distribution_delta": float(delta), "missing_delta": missing_delta}
    return result


def impact_metrics(db: Session, dataset_id: str) -> dict[str, int]:
    finding_status = func.lower(leakage_models.LeakageFinding.status)
    severity = func.lower(leakage_models.LeakageFinding.severity)
    finding_row = db.query(
        func.count(leakage_models.LeakageFinding.id).label("total"),
        func.sum(case((finding_status == "open", 1), else_=0)).label("open_count"),
        func.sum(case((severity == "high", 1), else_=0)).label("high_count"),
    ).filter(leakage_models.LeakageFinding.dataset_id == dataset_id).one()
    operation_row = db.query(
        func.count(models.RepairRecord.id).label("total"),
        func.sum(
            case(
                (func.lower(models.RepairRecord.status) == "completed", 1),
                else_=0,
            )
        ).label("completed"),
        func.coalesce(func.sum(models.RepairRecord.affected_rows), 0).label("affected"),
    ).filter(models.RepairRecord.dataset_id == dataset_id).one()
    return {
        "findings_total": int(finding_row.total or 0),
        "findings_open": int(finding_row.open_count or 0),
        "findings_high_severity": int(finding_row.high_count or 0),
        "operations_total": int(operation_row.total or 0),
        "operations_completed": int(operation_row.completed or 0),
        "affected_rows": int(operation_row.affected or 0),
    }


def _latest_event(db: Session, dataset_id: str, owner_id: str, event_type: str):
    return db.query(models.AuditEvent).filter(
        models.AuditEvent.dataset_id == dataset_id,
        models.AuditEvent.user_id == owner_id,
        models.AuditEvent.event_type == event_type,
    ).order_by(models.AuditEvent.created_at.desc(), models.AuditEvent.id.asc()).first()


def _profile_summary(dataset: models.Dataset) -> dict[str, Any]:
    profile = dataset.profile if isinstance(dataset.profile, dict) else {}
    columns = profile.get("column_profiles")
    if not isinstance(columns, list):
        return {
            "status": "not_performed",
            "reason": "No detailed persisted column profile is available.",
        }
    safe_columns = []
    for item in columns[:500]:
        if not isinstance(item, dict):
            continue
        stats = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
        kind = item.get("kind")
        if kind == "numeric":
            safe_statistics = {
                key: stats.get(key)
                for key in (
                    "mean", "median", "standard_deviation", "minimum",
                    "maximum", "quantiles", "zero_count", "negative_count",
                )
            }
        elif kind == "categorical":
            safe_statistics = {
                "category_count": stats.get("category_count"),
                "categories_truncated": stats.get("categories_truncated"),
            }
        elif kind == "datetime":
            safe_statistics = {
                key: stats.get(key)
                for key in (
                    "minimum", "maximum", "invalid_or_unparseable_count",
                    "missing_timestamp_count", "time_range_seconds",
                )
            }
        else:
            safe_statistics = {}
        safe_columns.append({
            "name": item.get("name"),
            "dtype": item.get("dtype"),
            "kind": kind,
            "non_null_count": item.get("non_null_count"),
            "missing_count": item.get("missing_count"),
            "missing_percentage": item.get("missing_percentage"),
            "unique_count": item.get("unique_count"),
            "duplicate_value_count": item.get("duplicate_value_count"),
            "statistics": safe_statistics,
        })
    return {
        "status": "available",
        "row_count": profile.get("row_count"),
        "column_count": profile.get("column_count"),
        "file_format": profile.get("file_format", dataset.format),
        "file_size_bytes": profile.get("file_size_bytes"),
        "memory_usage_bytes": profile.get("memory_usage_bytes"),
        "duplicate_row_count": profile.get("duplicate_row_count"),
        "total_missing_values": profile.get("total_missing_values"),
        "data_quality": profile.get("data_quality"),
        "profiled_at": profile.get("profiled_at"),
        "columns": safe_columns,
        "omitted_column_count": max(0, len(columns) - len(safe_columns)),
        "categorical_labels_omitted": True,
    }


def _finding_summary(db: Session, dataset_id: str) -> dict[str, Any]:
    query = db.query(leakage_models.LeakageFinding).filter(
        leakage_models.LeakageFinding.dataset_id == dataset_id
    )
    total = query.count()
    statuses = query.with_entities(
        func.lower(leakage_models.LeakageFinding.status),
        func.count(leakage_models.LeakageFinding.id),
    ).group_by(func.lower(leakage_models.LeakageFinding.status)).all()
    types = query.with_entities(
        leakage_models.LeakageFinding.finding_type,
        func.count(leakage_models.LeakageFinding.id),
    ).group_by(leakage_models.LeakageFinding.finding_type).all()
    severities = query.with_entities(
        func.lower(leakage_models.LeakageFinding.severity),
        func.count(leakage_models.LeakageFinding.id),
    ).group_by(func.lower(leakage_models.LeakageFinding.severity)).all()
    rows = query.order_by(
        leakage_models.LeakageFinding.created_at.desc(),
        leakage_models.LeakageFinding.id.asc(),
    ).limit(500).all()
    unresolved = [row for row in rows if str(row.status).lower() not in {"resolved", "false_positive"}]
    return {
        "status": "available" if total else "no_findings",
        "total": int(total),
        "status_counts": {str(key): int(count) for key, count in statuses if key},
        "type_counts": {str(key): int(count) for key, count in types if key},
        "severity_counts": {str(key): int(count) for key, count in severities if key},
        "findings": [
            {
                "id": row.id,
                "type": row.finding_type,
                "severity": row.severity,
                "status": row.status,
                "description": row.description,
                "evidence_available": isinstance(row.evidence, dict) and bool(row.evidence),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "unresolved": [
            {"id": row.id, "type": row.finding_type, "severity": row.severity, "status": row.status}
            for row in unresolved
        ],
        "omitted_finding_count": max(0, total - len(rows)),
        "unresolved_count": sum(
            int(count)
            for status, count in statuses
            if status and str(status).lower() not in {"resolved", "false_positive"}
        ),
        "unresolved_list_truncated": total > 500,
    }


def _operation_summaries(db: Session, dataset_id: str) -> dict[str, Any]:
    total = db.query(func.count(models.RepairRecord.id)).filter(
        models.RepairRecord.dataset_id == dataset_id
    ).scalar() or 0
    rows = db.query(models.RepairRecord).filter(
        models.RepairRecord.dataset_id == dataset_id
    ).order_by(models.RepairRecord.created_at.desc(), models.RepairRecord.id.asc()).limit(100).all()
    operations = []
    verification_results = []
    for row in rows:
        metadata = row.operation_metadata if isinstance(row.operation_metadata, dict) else {}
        verification = metadata.get("verification") or metadata.get("post_remediation_verification")
        if isinstance(verification, dict):
            checks = verification.get("checks")
            if isinstance(checks, list):
                verification_summary = {
                    "status": verification.get("status"),
                    "passed": sum(1 for check in checks if isinstance(check, dict) and check.get("status") == "passed"),
                    "failed": sum(1 for check in checks if isinstance(check, dict) and check.get("status") == "failed"),
                    "skipped": sum(1 for check in checks if isinstance(check, dict) and check.get("status") == "skipped"),
                    "review_required": sum(1 for check in checks if isinstance(check, dict) and check.get("status") == "review_required"),
                }
            else:
                verification_summary = {
                    "status": verification.get("status"),
                    "check_count": len(verification) if isinstance(verification, dict) else 0,
                }
            verification_results.append({"operation_id": row.id, **verification_summary})
        else:
            verification_summary = {"status": "not_available"}
        operations.append({
            "id": row.id,
            "finding_id": row.finding_id,
            "operation_type": row.operation_type,
            "status": row.status,
            "input_file_sha256": row.input_file_sha256,
            "output_file_sha256": row.output_file_sha256,
            "affected_rows": row.affected_rows,
            "affected_columns": row.affected_columns or [],
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "verification": verification_summary,
        })
    return {
        "status": "available" if total else "not_performed",
        "total": int(total),
        "operations": operations,
        "verification_results": verification_results,
        "omitted_operation_count": max(0, int(total) - len(operations)),
    }


def _dataset_report(db: Session, dataset: models.Dataset, owner_id: str) -> dict[str, Any]:
    profile = dataset.profile if isinstance(dataset.profile, dict) else {}
    source_integrity_verified = verify_dataset_integrity(dataset)
    analysis_event = _latest_event(db, dataset.id, owner_id, "analysis")
    analysis_details = (
        analysis_event.details if analysis_event and isinstance(analysis_event.details, dict) else {}
    )
    distribution_event = _latest_event(
        db, dataset.id, owner_id, "partition_distribution_analysis"
    )
    distribution_details = (
        distribution_event.details
        if distribution_event and isinstance(distribution_event.details, dict)
        else {}
    )
    applicability = analysis_details.get("detector_applicability", {})
    if not isinstance(applicability, dict):
        applicability = {}
    skipped = [
        {"detector": name, **(value if isinstance(value, dict) else {"status": str(value)})}
        for name, value in applicability.items()
        if isinstance(value, dict) and value.get("status") in {"skipped", "requires_configuration"}
    ]
    leakage = _finding_summary(db, dataset.id)
    if not source_integrity_verified:
        leakage["status"] = "stale"
        leakage["reason"] = (
            "Persisted findings are historical and cannot be attributed to the "
            "current bytes because source-file integrity failed."
        )
    operations = _operation_summaries(db, dataset.id)
    distribution_result = distribution_details.get("result")
    distribution = (
        {"status": "available", **distribution_result}
        if source_integrity_verified
        and isinstance(distribution_result, dict)
        and distribution_result.get("source_file_sha256") == dataset.file_sha256
        else {
            "status": "not_performed" if source_integrity_verified else "stale",
            "reason": (
                "The source file is missing or does not match its registered SHA-256."
                if not source_integrity_verified
                else "A persisted partition comparison is unavailable or stale for the registered source hash."
            ),
        }
    )
    configuration = (
        profile.get("analysis_columns")
        if isinstance(profile.get("analysis_columns"), dict)
        else analysis_details.get("columns", {})
    )
    return {
        "dataset": {
            "id": dataset.id,
            "name": dataset.name,
            "format": dataset.format,
            "source_sha256": dataset.file_sha256,
            "row_count": dataset.sample_count,
            "column_count": dataset.feature_count,
        },
        "source_integrity": {
            "status": "verified" if source_integrity_verified else "failed",
            "registered_sha256": dataset.file_sha256,
        },
        "profiling": (
            _profile_summary(dataset)
            if source_integrity_verified
            else {
                "status": "stale",
                "reason": "The source file is missing or does not match its registered SHA-256.",
            }
        ),
        "analysis": {
            "status": (
                "not_performed"
                if analysis_event is None
                else "available"
                if source_integrity_verified
                else "stale"
            ),
            "generated_at": analysis_event.created_at.isoformat() if analysis_event and analysis_event.created_at else None,
            "configuration": configuration,
            "detector_applicability": applicability,
        },
        "leakage": leakage,
        "distribution_analysis": distribution,
        "remediation": operations,
        "post_remediation_verification": operations["verification_results"],
        "remaining_unresolved_findings": {
            "count": leakage["unresolved_count"],
            "items": leakage["unresolved"],
            "truncated": leakage["unresolved_list_truncated"],
        },
        "skipped_analyses": skipped,
        "limitations_and_recommendations": [
            "Distribution differences are not proof of leakage or causation.",
            "This report does not execute model training, prediction, or performance evaluation.",
            "Only persisted analyses and operations are included; absent sections are explicitly marked not performed.",
        ],
    }


def report_payload(db: Session, owner_id: str, dataset_id: str | None) -> dict[str, Any]:
    datasets = db.query(models.Dataset).filter(models.Dataset.owner_user_id == owner_id)
    if dataset_id:
        datasets = datasets.filter(models.Dataset.id == dataset_id)
    rows = datasets.order_by(models.Dataset.uploaded_at.asc(), models.Dataset.id.asc()).all()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "datasets": [{"id": d.id, "name": d.name, "format": d.format, "sha256": d.file_sha256} for d in rows],
        "impact": [impact_metrics(db, d.id) for d in rows],
        "dataset_reports": [_dataset_report(db, dataset, owner_id) for dataset in rows],
    }


def report_html(title: str, payload: dict[str, Any]) -> str:
    escaped_title = html.escape(title)
    escaped_payload = html.escape(json.dumps(payload, indent=2, default=str))
    return (
        "<html><head><meta charset='utf-8'><title>"
        f"{escaped_title}</title></head><body><h1>{escaped_title}</h1>"
        f"<pre>{escaped_payload}</pre></body></html>"
    )


def _flatten_report(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key in sorted(value):
            child_path = f"{path}.{key}" if path else str(key)
            yield from _flatten_report(value[key], child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _flatten_report(child, f"{path}[{index}]")
    else:
        yield path, value


def report_csv(payload: dict[str, Any]) -> bytes:
    """Export the persisted report snapshot as a generic section/path/value CSV."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["section", "field", "value"])
    for path, value in _flatten_report(payload):
        section, _, field = path.partition(".")
        writer.writerow([section, field or section, json.dumps(value, ensure_ascii=False, default=str)])
    return output.getvalue().encode("utf-8")


def report_pdf(title: str, payload: dict[str, Any]) -> bytes:
    """Create a small dependency-free, paginated text PDF from the persisted snapshot."""
    lines = [title, f"Generated: {payload.get('generated_at', 'Unavailable')}", ""]
    lines.extend(
        f"{path}: {json.dumps(value, ensure_ascii=False, default=str)}"
        for path, value in _flatten_report(payload)
    )
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(textwrap.wrap(str(line), width=92) or [""])
    lines_per_page = 55
    pages = [
        wrapped[index:index + lines_per_page]
        for index in range(0, len(wrapped), lines_per_page)
    ] or [["No persisted report content is available."]]

    objects: list[bytes] = []
    page_ids = [3 + index * 2 for index in range(len(pages))]
    content_ids = [page_id + 1 for page_id in page_ids]
    font_id = 3 + len(pages) * 2
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii"))

    for page_id, content_id, page_lines in zip(page_ids, content_ids, pages):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>".encode("ascii")
        )
        commands = ["BT", "/F1 8 Tf", "45 755 Td", "11 TL"]
        for line in page_lines:
            safe = str(line).encode("latin-1", "replace").decode("latin-1")
            escaped = safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({escaped}) Tj")
            commands.append("T*")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1", "replace")
        objects.append(
            b"<< /Length " + str(len(stream)).encode("ascii")
            + b" >>\nstream\n" + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)
