from __future__ import annotations

import html
import json
import math
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.db import leakage_models, models
from app.core.dataset_service import get_dataset_file_path


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
    findings = db.query(leakage_models.LeakageFinding).filter_by(dataset_id=dataset_id).all()
    operations = db.query(models.RepairRecord).filter_by(dataset_id=dataset_id).all()
    return {
        "findings_total": len(findings),
        "findings_open": sum(1 for f in findings if f.status == "open"),
        "findings_high_severity": sum(1 for f in findings if f.severity == "high"),
        "operations_total": len(operations),
        "operations_completed": sum(1 for o in operations if o.status == "completed"),
        "affected_rows": sum(o.affected_rows or 0 for o in operations),
    }


def report_payload(db: Session, owner_id: str, dataset_id: str | None) -> dict[str, Any]:
    datasets = db.query(models.Dataset).filter(models.Dataset.owner_user_id == owner_id)
    if dataset_id:
        datasets = datasets.filter(models.Dataset.id == dataset_id)
    rows = datasets.all()
    return {
        "datasets": [{"id": d.id, "name": d.name, "format": d.format, "sha256": d.file_sha256} for d in rows],
        "impact": [impact_metrics(db, d.id) for d in rows],
    }


def report_html(title: str, payload: dict[str, Any]) -> str:
    escaped_title = html.escape(title)
    escaped_payload = html.escape(json.dumps(payload, indent=2, default=str))
    return (
        "<html><head><meta charset='utf-8'><title>"
        f"{escaped_title}</title></head><body><h1>{escaped_title}</h1>"
        f"<pre>{escaped_payload}</pre></body></html>"
    )
