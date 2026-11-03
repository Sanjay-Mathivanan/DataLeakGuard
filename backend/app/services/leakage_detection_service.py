import os
import pandas as pd
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from typing import Optional, List
from app.db import models, leakage_models
from app.utils.file_storage import ORIGINAL_DIR
from app.utils.row_hashing import hash_row


def _load_analysis_frame(
    dataset: models.Dataset,
    supplied_frame: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Use an explicitly supplied analysis frame or load the registered original."""
    if supplied_frame is not None:
        if not isinstance(supplied_frame, pd.DataFrame):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Analysis frame must be a pandas DataFrame",
            )
        return supplied_frame.copy()

    storage_path = ORIGINAL_DIR / dataset.storage_filename
    if not os.path.exists(storage_path):
        raise HTTPException(status_code=404, detail="Stored file not found")
    try:
        if dataset.format.upper() == "CSV":
            return pd.read_csv(storage_path, dtype=str)
        if dataset.format.upper() == "XLSX":
            return pd.read_excel(storage_path, dtype=str)
        raise HTTPException(status_code=400, detail="Unsupported file format")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(exc)}")


def detect_exact_duplicates(
    dataset_id: str,
    db: Session,
    exclude_columns: Optional[List[str]] = None,
    analysis_frame: Optional[pd.DataFrame] = None,
):
    """
    Detect exact duplicate rows in a dataset's stored file.
    Returns analysis metadata and creates/updates LeakageFinding records.

    Args:
        dataset_id: The dataset ID
        db: Database session
        exclude_columns: Optional list of column names to exclude from duplicate check
    """
    # Get dataset
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    df = _load_analysis_frame(dataset, analysis_frame)


    # Persist the exact columns used to compute each hash. A later repair
    # cannot safely infer this from the dataset's current analysis settings,
    # since the same dataset may have been analyzed with different settings.
    existing_exclusions = list(
        dict.fromkeys(
            column
            for column in (exclude_columns or [])
            if isinstance(column, str) and column in df.columns
        )
    )
    if existing_exclusions:
        df = df.drop(columns=existing_exclusions)

    # Compute hash for each row
    df['_hash'] = df.apply(hash_row, axis=1)


    # Group by hash
    grouped = df.groupby('_hash')

    findings_created = []
    duplicate_groups = 0
    duplicated_rows = 0

    for hash_val, group in grouped:
        group_size = len(group)
        if group_size >= 2:
            duplicate_groups += 1
            duplicated_rows += group_size

            # Evidence
            evidence = {
                "hash": hash_val,
                "duplicate_count": group_size,
                "row_indices": group.index.tolist(),  # zero-based row numbers in the dataframe
                "hash_excluded_columns": existing_exclusions,
            }

            # Check if finding already exists (idempotency). Also recognize
            # legacy evidence without hash_excluded_columns and enrich that
            # same record rather than creating a duplicate or changing its
            # original creation timestamp.
            existing = db.query(leakage_models.LeakageFinding).filter(
                leakage_models.LeakageFinding.dataset_id == dataset_id,
                leakage_models.LeakageFinding.finding_type == "exact_duplicate",
                leakage_models.LeakageFinding.evidence == evidence
            ).first()
            if existing is None:
                candidates = db.query(leakage_models.LeakageFinding).filter(
                    leakage_models.LeakageFinding.dataset_id == dataset_id,
                    leakage_models.LeakageFinding.finding_type == "exact_duplicate",
                ).all()
                for candidate in candidates:
                    candidate_evidence = candidate.evidence
                    if not isinstance(candidate_evidence, dict):
                        continue
                    if any(
                        candidate_evidence.get(key) != evidence[key]
                        for key in ("hash", "duplicate_count", "row_indices")
                    ):
                        continue
                    prior_exclusions = candidate_evidence.get(
                        "hash_excluded_columns"
                    )
                    if prior_exclusions is None:
                        candidate.evidence = {
                            **candidate_evidence,
                            "hash_excluded_columns": existing_exclusions,
                        }
                        existing = candidate
                        break
                    if prior_exclusions == existing_exclusions:
                        existing = candidate
                        break

            if existing:
                # Per requirements: preserve original created_at, do not refresh
                findings_created.append(existing)
            else:
                finding = leakage_models.LeakageFinding(
                    dataset_id=dataset_id,
                    finding_type="exact_duplicate",
                    severity="medium",
                    status="open",
                    description=f"Exact duplicate rows detected: {group_size} rows share identical content.",
                    evidence=evidence
                )
                db.add(finding)
                findings_created.append(finding)

    db.commit()

    # Refresh findings to get IDs etc.
    for f in findings_created:
        db.refresh(f)

    # Build response
    findings_out = []
    for f in findings_created:
        findings_out.append({
            "id": str(f.id),
            "dataset_id": str(f.dataset_id),
            "finding_type": f.finding_type,
            "severity": f.severity,
            "status": f.status,
            "description": f.description,
            "evidence": f.evidence,
            "created_at": f.created_at.isoformat() if f.created_at else None
        })

    return {
        "dataset_id": dataset_id,
        "rows_examined": len(df),
        "duplicate_group_count": duplicate_groups,
        "duplicated_row_count": duplicated_rows,
        "findings": findings_out
    }


def detect_entity_overlap(
    dataset_id: str,
    db: Session,
    entity_column: str,
    split_column: str,
    analysis_frame: Optional[pd.DataFrame] = None,
) -> list:
    """
    Detect entity overlap in a dataset's stored file.
    Returns a list of finding dicts to be added to the analysis findings.
    """
    # Get dataset
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    df = _load_analysis_frame(dataset, analysis_frame)

    # Check that entity_column and split_column exist
    if entity_column not in df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Entity column '{entity_column}' not found in dataset columns"
        )
    if split_column not in df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Split column '{split_column}' not found in dataset columns"
        )

    # Normalize entity values: strip whitespace, treat null/empty as missing
    entity_series = df[entity_column].astype(str).str.strip()
    # Normalize split values: strip whitespace, lowercase, treat null/empty as missing
    split_series = df[split_column].astype(str).str.strip().str.lower()

    # Mask for non-empty entity values and non-empty split values
    non_empty_entity_mask = df[entity_column].notna() & (entity_series != '')
    non_empty_split_mask = df[split_column].notna() & (split_series != '')
    combined_mask = non_empty_entity_mask & non_empty_split_mask

    # We'll only consider rows with non-empty entity and split values
    df_filtered = df[combined_mask].copy()
    entity_series_filtered = entity_series[combined_mask]
    split_series_filtered = split_series[combined_mask]

    # Check if we have any valid entities remaining
    if len(df_filtered) == 0:
        raise HTTPException(
            status_code=400,
            detail=f"No valid entities found in column '{entity_column}'"
        )

    # List to hold findings (ORM objects) that we will commit and then convert to dicts
    findings_to_commit = []
    # List to hold finding dicts for existing findings (which already have IDs)
    findings_to_return = []

    # Group by entity value
    grouped = df_filtered.groupby(entity_series_filtered)

    # Calculate split sets for each entity
    entity_splits = {}
    for entity_value, group in grouped:
        group_split_series = split_series_filtered[group.index]
        unique_splits = set(group_split_series.tolist())
        entity_splits[entity_value] = {
            "splits": list(unique_splits),
            "split_count": len(unique_splits),
            "row_indices": group.index.tolist()
        }

    # Check for entity overlap: each entity appearing in more than one split
    findings_to_commit = []
    findings_to_return = []

    for entity_value, split_info in entity_splits.items():
        # Check if this entity appears in more than one split
        if split_info["split_count"] > 1:
            # Build evidence for entity overlap
            evidence = {
                "entity_column": entity_column,
                "split_column": split_column,
                "entity_value": entity_value,
                "splits": split_info["splits"],
                "row_indices": {split: [int(idx) for idx in split_info["row_indices"]
                                  if split_series_filtered.loc[idx] == split]
                               for split in split_info["splits"]}
            }

            # Check if a finding with this evidence already exists
            existing = db.query(leakage_models.LeakageFinding).filter(
                leakage_models.LeakageFinding.dataset_id == dataset_id,
                leakage_models.LeakageFinding.finding_type == "entity_overlap",
                leakage_models.LeakageFinding.evidence == evidence
            ).first()

            if existing:
                # Update created_at to now (refresh)
                existing.created_at = pd.Timestamp.utcnow()
                db.add(existing)
                # Building finding dict from existing finding
                finding_dict = {
                    "id": str(existing.id),
                    "dataset_id": str(existing.dataset_id),
                    "finding_type": existing.finding_type,
                    "severity": existing.severity,
                    "status": existing.status,
                    "description": existing.description,
                    "evidence": existing.evidence,
                    "created_at": existing.created_at.isoformat() if existing.created_at else None
                }
                findings_to_return.append(finding_dict)
            else:
                # Create new finding
                splits_str = ", ".join(sorted(split_info["splits"]))
                description = f"Entity '{entity_value}' appears in multiple splits: {splits_str}."
                finding = leakage_models.LeakageFinding(
                    dataset_id=dataset_id,
                    finding_type="entity_overlap",
                    severity="high",
                    status="open",
                    description=description,
                    evidence=evidence
                )
                db.add(finding)
                findings_to_commit.append(finding)

    # Commit the new findings
    db.commit()

    # Refresh the new findings to get IDs and other generated values
    for finding in findings_to_commit:
        db.refresh(finding)
        # Build finding dict from new finding
        finding_dict = {
            "id": str(finding.id),
            "dataset_id": str(finding.dataset_id),
            "finding_type": finding.finding_type,
            "severity": finding.severity,
            "status": finding.status,
            "description": finding.description,
            "evidence": finding.evidence,
            "created_at": finding.created_at.isoformat() if finding.created_at else None
        }
        findings_to_return.append(finding_dict)

    return findings_to_return


def detect_target_leakage(
    dataset_id: str,
    db: Session,
    target_column: str,
    analysis_frame: Optional[pd.DataFrame] = None,
) -> list:
    """
    Detect target leakage in a dataset's stored file.
    Returns a list of finding dicts to be added to the analysis findings.
    """
    # Get dataset
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    df = _load_analysis_frame(dataset, analysis_frame)

    # Check that target_column exists
    if target_column not in df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Target column '{target_column}' not found in dataset columns"
        )

    # Normalize valid target values while checking nulls before string conversion.
    # Converting nulls first would turn them into strings such as "nan".
    target_series = df[target_column].astype("string").str.strip()
    non_empty_target_mask = (
        df[target_column].notna() & target_series.ne("").fillna(False)
    )
    df_filtered = df[non_empty_target_mask].copy()
    target_series_filtered = target_series[non_empty_target_mask]

    # Check if we have any valid targets remaining
    if len(df_filtered) == 0:
        raise HTTPException(
            status_code=400,
            detail=f"No valid targets found in column '{target_column}'"
        )

    # List to hold findings (ORM objects) that we will commit and then convert to dicts
    findings_to_commit = []
    # List to hold finding dicts for existing findings (which already have IDs)
    findings_to_return = []

    # For each non-target column
    for column in df_filtered.columns:
        if column == target_column:
            continue  # Skip the target column itself

        # Exclude null and whitespace-only feature values before constructing
        # mappings. Keep nonblank feature values unchanged for the evidence.
        raw_feature_series = df_filtered[column]
        feature_value_strings = raw_feature_series.astype("string")
        valid_feature_mask = (
            raw_feature_series.notna()
            & feature_value_strings.str.strip().ne("").fillna(False)
        )
        feature_series = raw_feature_series[valid_feature_mask]
        target_series = target_series_filtered[valid_feature_mask]

        # Check if feature column has sufficient variation
        # Skip columns where all values are the same (likely ID columns)
        if feature_series.nunique() <= 1:
            continue

        # Check if target column has sufficient variation
        if target_series.nunique() <= 1:
            continue

        # Build mapping from feature values to target values
        mapping = {}
        is_exact_duplicate = True
        is_deterministic_mapping = True
        conflicting_mappings = {}

        # Iterate through rows with valid feature/target pairs to build mapping
        for feature_val, target_val in zip(feature_series, target_series):
            if feature_val in mapping:
                # Check for consistency
                if mapping[feature_val] != target_val:
                    is_exact_duplicate = False
                    is_deterministic_mapping = False
                    if feature_val not in conflicting_mappings:
                        conflicting_mappings[feature_val] = [mapping[feature_val]]
                    conflicting_mappings[feature_val].append(target_val)
            else:
                mapping[feature_val] = target_val

        # Check for exact target duplication: feature column values identical to target column values
        # Compare the actual values directly, not the mapping
        feature_values = feature_series.tolist()
        target_values = target_series.tolist()

        # Check if feature column exactly matches target column
        if feature_values == target_values and len(feature_values) > 0:
            # Build evidence for exact target duplication
            evidence = {
                "target_column": target_column,
                "feature_column": column,
                "detection": "exact_target_duplicate",
                "matching_rows": len(feature_series),
                "total_valid_rows": len(feature_series)
            }

            # Check if a finding with this evidence already exists
            existing = db.query(leakage_models.LeakageFinding).filter(
                leakage_models.LeakageFinding.dataset_id == dataset_id,
                leakage_models.LeakageFinding.finding_type == "target_leakage",
                leakage_models.LeakageFinding.evidence == evidence
            ).first()

            if existing:
                # Update created_at to now (refresh)
                existing.created_at = pd.Timestamp.utcnow()
                db.add(existing)
                # Build finding dict from existing finding
                finding_dict = {
                    "id": str(existing.id),
                    "dataset_id": str(existing.dataset_id),
                    "finding_type": existing.finding_type,
                    "severity": existing.severity,
                    "status": existing.status,
                    "description": existing.description,
                    "evidence": existing.evidence,
                    "created_at": existing.created_at.isoformat() if existing.created_at else None
                }
                findings_to_return.append(finding_dict)
            else:
                # Create new finding
                description = f"Feature column '{column}' exactly duplicates the target column '{target_column}'."
                finding = leakage_models.LeakageFinding(
                    dataset_id=dataset_id,
                    finding_type="target_leakage",
                    severity="high",
                    status="open",
                    description=description,
                    evidence=evidence
                )
                db.add(finding)
                findings_to_commit.append(finding)

            # Reset flags to prevent fall-through to deterministic mapping check
            is_exact_duplicate = False
            is_deterministic_mapping = False
            conflicting_mappings = {}

        # Check for deterministic feature -> target mapping
        elif is_deterministic_mapping and len(mapping) > 0 and len(conflicting_mappings) == 0:
            # Each feature value maps to exactly one target value
            # But different feature values can map to different target values
            unique_feature_values = set(mapping.keys())
            unique_target_values = set(mapping.values())

            # Apply conservative evidence requirements:
            # - Feature must have at least 2 distinct non-null values
            # - Target must have at least 2 distinct non-null values
            # - Every valid feature value must map consistently to one target
            # - At least 2 distinct target groups must be represented
            # - Target column itself is never flagged
            if (len(unique_feature_values) >= 2 and
                len(unique_target_values) >= 2):

                # Build evidence for deterministic mapping
                evidence = {
                    "target_column": target_column,
                    "feature_column": column,
                    "detection": "deterministic_feature_target_mapping",
                    "unique_feature_values": len(unique_feature_values),
                    "unique_target_values": len(unique_target_values),
                    "mapping": mapping
                }

                # Check if a finding with this evidence already exists
                existing = db.query(leakage_models.LeakageFinding).filter(
                    leakage_models.LeakageFinding.dataset_id == dataset_id,
                    leakage_models.LeakageFinding.finding_type == "target_leakage",
                    leakage_models.LeakageFinding.evidence == evidence
                ).first()

                if existing:
                    # Update created_at to now (refresh)
                    existing.created_at = pd.Timestamp.utcnow()
                    db.add(existing)
                    # Build finding dict from existing finding
                    finding_dict = {
                        "id": str(existing.id),
                        "dataset_id": str(existing.dataset_id),
                        "finding_type": existing.finding_type,
                        "severity": existing.severity,
                        "status": existing.status,
                        "description": existing.description,
                        "evidence": existing.evidence,
                        "created_at": existing.created_at.isoformat() if existing.created_at else None
                    }
                    findings_to_return.append(finding_dict)
                else:
                    # Create new finding
                    description = f"Feature column '{column}' deterministically maps each feature value to a single target value."
                    finding = leakage_models.LeakageFinding(
                        dataset_id=dataset_id,
                        finding_type="target_leakage",
                        severity="high",
                        status="open",
                        description=description,
                        evidence=evidence
                    )
                    db.add(finding)
                    findings_to_commit.append(finding)

    # Commit the new findings
    db.commit()

    # Refresh the new findings to get IDs and other generated values
    for finding in findings_to_commit:
        db.refresh(finding)
        # Build finding dict from new finding
        finding_dict = {
            "id": str(finding.id),
            "dataset_id": str(finding.dataset_id),
            "finding_type": finding.finding_type,
            "severity": finding.severity,
            "status": finding.status,
            "description": finding.description,
            "evidence": finding.evidence,
            "created_at": finding.created_at.isoformat() if finding.created_at else None
        }
        findings_to_return.append(finding_dict)

    return findings_to_return


def detect_temporal_leakage(
    dataset_id: str,
    db: Session,
    time_column: str,
    split_column: str,
    analysis_frame: Optional[pd.DataFrame] = None,
) -> list:
    """
    Detect temporal leakage in a dataset's stored file.
    Returns a list of finding dicts to be added to the analysis findings.
    """
    # Get dataset
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    df = _load_analysis_frame(dataset, analysis_frame)

    # Check that time_column and split_column exist
    if time_column not in df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Time column '{time_column}' not found in dataset columns"
        )
    if split_column not in df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Split column '{split_column}' not found in dataset columns"
        )

    # Normalize time values: parse as datetime, handle invalid values
    try:
        time_series = pd.to_datetime(df[time_column], errors='coerce')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse time column: {str(e)}")

    # Normalize split values: strip whitespace, lowercase, treat null/empty as missing
    split_series = df[split_column].astype(str).str.strip().str.lower()

    # Mask for valid (non-NaT) time values and non-empty split values
    valid_time_mask = ~time_series.isna()
    non_empty_split_mask = split_series != ''
    combined_mask = valid_time_mask & non_empty_split_mask

    # We'll only consider rows with valid time values and non-empty split values
    df_filtered = df[combined_mask].copy()
    time_series_filtered = time_series[combined_mask]
    split_series_filtered = split_series[combined_mask]

    # Check if we have any valid timestamps remaining
    if len(df_filtered) == 0:
        raise HTTPException(
            status_code=400,
            detail=f"No valid timestamps found in column '{time_column}'"
        )

    # List to hold findings (ORM objects) that we will commit and then convert to dicts
    findings_to_commit = []
    # List to hold finding dicts for existing findings (which already have IDs)
    findings_to_return = []

    # Group by split value
    grouped = df_filtered.groupby(split_series_filtered)

    # Calculate time ranges for each split
    split_ranges = {}
    for split_value, group in grouped:
        group_time_series = time_series_filtered[group.index]
        min_time = group_time_series.min()
        max_time = group_time_series.max()
        valid_rows = len(group)

        split_ranges[split_value] = {
            "min_time": min_time.isoformat() if not pd.isna(min_time) else None,
            "max_time": max_time.isoformat() if not pd.isna(max_time) else None,
            "valid_rows": valid_rows
        }

    # Check for temporal leakage between splits
    # For conventional case: train -> test, validation -> test, etc.
    # We'll check all pairs of splits where one should temporally precede the other
    split_values = list(split_ranges.keys())

    # Define conventional order (earlier to later)
    conventional_order = ["train", "validation", "val", "test"]

    # Check each pair of splits
    for i, split1 in enumerate(split_values):
        for j, split2 in enumerate(split_values):
            if i >= j:  # Avoid duplicate pairs and self-pairs
                continue

            # Determine which split should come first based on conventional ordering
            # If both splits are in conventional order, use that
            # Otherwise, use alphabetical order as fallback
            split1_order = conventional_order.index(split1) if split1 in conventional_order else len(conventional_order) + split_values.index(split1)
            split2_order = conventional_order.index(split2) if split2 in conventional_order else len(conventional_order) + split_values.index(split2)

            # If split1 should come before split2
            if split1_order < split2_order:
                earlier_split = split1
                later_split = split2
            else:
                earlier_split = split2
                later_split = split1

            # Get time ranges
            earlier_range = split_ranges[earlier_split]
            later_range = split_ranges[later_split]

            # Check for temporal overlap: later split begins before or at the end of earlier split
            # Convert strings back to datetime for comparison
            earlier_max = pd.to_datetime(earlier_range["max_time"]) if earlier_range["max_time"] else None
            later_min = pd.to_datetime(later_range["min_time"]) if later_range["min_time"] is not None else None

            # Skip if we don't have valid times
            if earlier_max is None or later_min is None:
                continue

            # Check for overlap or boundary overlap
            is_overlap = later_min <= earlier_max
            is_boundary_overlap = later_min == earlier_max

            if is_overlap:
                # Build evidence for temporal leakage
                evidence = {
                    "time_column": time_column,
                    "split_column": split_column,
                    "detection": "temporal_overlap",
                    "splits": split_ranges,
                    "invalid_timestamp_rows": len(df) - len(df_filtered)  # Original rows minus filtered rows
                }

                # Add boundary overlap flag if applicable
                if is_boundary_overlap:
                    evidence["boundary_overlap"] = True

                # Check if a finding with this evidence already exists
                existing = db.query(leakage_models.LeakageFinding).filter(
                    leakage_models.LeakageFinding.dataset_id == dataset_id,
                    leakage_models.LeakageFinding.finding_type == "temporal_leakage",
                    leakage_models.LeakageFinding.evidence == evidence
                ).first()

                if existing:
                    # Update created_at to now (refresh)
                    existing.created_at = pd.Timestamp.utcnow()
                    db.add(existing)
                    # Build finding dict from existing finding
                    finding_dict = {
                        "id": str(existing.id),
                        "dataset_id": str(existing.dataset_id),
                        "finding_type": existing.finding_type,
                        "severity": existing.severity,
                        "status": existing.status,
                        "description": existing.description,
                        "evidence": existing.evidence,
                        "created_at": existing.created_at.isoformat() if existing.created_at else None
                    }
                    findings_to_return.append(finding_dict)
                else:
                    # Create new finding
                    if is_boundary_overlap:
                        description = f"Temporal boundary overlap detected between {earlier_split} and {later_split} periods."
                    else:
                        description = f"Temporal overlap detected between {earlier_split} and {later_split} periods: the {later_split} period begins before the {earlier_split} period ends."

                    finding = leakage_models.LeakageFinding(
                        dataset_id=dataset_id,
                        finding_type="temporal_leakage",
                        severity="high",
                        status="open",
                        description=description,
                        evidence=evidence
                    )
                    db.add(finding)
                    findings_to_commit.append(finding)

    # Commit the new findings
    db.commit()

    # Refresh the new findings to get IDs and other generated values
    for finding in findings_to_commit:
        db.refresh(finding)
        # Build finding dict from new finding
        finding_dict = {
            "id": str(finding.id),
            "dataset_id": str(finding.dataset_id),
            "finding_type": finding.finding_type,
            "severity": finding.severity,
            "status": finding.status,
            "description": finding.description,
            "evidence": finding.evidence,
            "created_at": finding.created_at.isoformat() if finding.created_at else None
        }
        findings_to_return.append(finding_dict)

    return findings_to_return


def detect_train_test_contamination(
    dataset_id: str,
    db: Session,
    split_column: str,
    analysis_frame: Optional[pd.DataFrame] = None,
) -> list:
    """
    Detect train/test contamination in a dataset's stored file.
    Returns a list of finding dicts to be added to the analysis findings.
    """
    # DEBUG: Function entry point
    # Get dataset
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    df = _load_analysis_frame(dataset, analysis_frame)

    # Check that split_column exists
    if split_column not in df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Split column '{split_column}' not found in dataset columns"
        )

    # Normalize split values: strip whitespace, lowercase, treat null/empty as missing
    # First convert to string, but preserve actual null values as None for proper handling
    split_series = df[split_column].copy()
    # Handle actual null/NaN values by keeping them as None, then convert rest to string
    split_series = split_series.where(split_series.isnull(), split_series.astype(str).str.strip().str.lower())

    # Mask for non-empty split values (exclude None/null values and empty strings)
    non_empty_split_mask = split_series.notna() & (split_series != '')
    df_filtered = df[non_empty_split_mask].copy()
    split_series_filtered = split_series[non_empty_split_mask]

    # Check if we have any valid split values remaining
    if len(df_filtered) == 0:
        raise HTTPException(
            status_code=400,
            detail=f"No valid split values found in column '{split_column}'"
        )

    # Calculate column_count (original columns excluding split column)
    column_count = len(df_filtered.columns) - 1  # All columns except split column

    # We'll compute row hashes excluding the split column and any ID column
    # Create a copy of the dataframe without the split column for hashing
    df_for_hashing = df_filtered.drop(columns=[split_column])
    # Also exclude ID column if present (case-insensitive)
    id_columns = [col for col in df_for_hashing.columns if col.lower() == 'id']
    if id_columns:
        df_for_hashing = df_for_hashing.drop(columns=id_columns)

    # Compute hash for each row (excluding split column and ID column)
    df_filtered['_row_hash'] = df_for_hashing.apply(hash_row, axis=1)

    # Group by row hash
    grouped = df_filtered.groupby('_row_hash')

    # List to hold findings (ORM objects) that we will commit and then convert to dicts
    findings_to_commit = []
    # List to hold finding dicts for existing findings (which already have IDs)
    findings_to_return = []

    # Process each group of rows with the same hash
    for row_hash, group in grouped:
        # Get the split values for this group
        group_split_series = split_series_filtered[group.index]
        unique_splits = set(group_split_series.tolist())
        split_count = len(unique_splits)

        # Create a contamination finding ONLY when:
        # number of distinct splits > 1
        if split_count > 1:
            # Evidence indices are zero-based source dataframe row positions, not
            # positions within a filtered split or hash group. Quarantine applies
            # them to the original dataframe with iloc.
            row_indices_data = {
                split_value: [
                    int(row_index)
                    for row_index, row_split in group_split_series.items()
                    if row_split == split_value
                ]
                for split_value in sorted(unique_splits)
            }

            # Build evidence for train/test contamination
            evidence = {
                "split_column": split_column,
                "detection": "exact_row_hash_overlap",
                "row_hash": row_hash,
                "splits": [str(s) for s in sorted(unique_splits)],  # Ensure strings
                "row_indices": {str(k): [int(x) for x in v] for k, v in row_indices_data.items()},
                "column_count": int(column_count)  # All columns except split column
            }

            # Check if a finding with this evidence already exists
            existing = db.query(leakage_models.LeakageFinding).filter(
                leakage_models.LeakageFinding.dataset_id == dataset_id,
                leakage_models.LeakageFinding.finding_type == "train_test_contamination",
                leakage_models.LeakageFinding.evidence == evidence
            ).first()

            if existing:
                # Per requirements: preserve original created_at, do not refresh
                # Building finding dict from existing finding
                finding_dict = {
                    "id": str(existing.id),
                    "dataset_id": str(existing.dataset_id),
                    "finding_type": existing.finding_type,
                    "severity": existing.severity,
                    "status": existing.status,
                    "description": existing.description,
                    "evidence": existing.evidence,
                    "created_at": existing.created_at.isoformat() if existing.created_at else None
                }
                findings_to_return.append(finding_dict)
            else:
                # Create new finding
                if len(unique_splits) == 2:
                    description = f"Exact train/test contamination detected: the same canonical sample appears in {list(unique_splits)[0]} and {list(unique_splits)[1]} splits."
                else:
                    description = f"Exact train/test contamination detected across multiple dataset splits: {', '.join(sorted(unique_splits))}."

                finding = leakage_models.LeakageFinding(
                    dataset_id=dataset_id,
                    finding_type="train_test_contamination",
                    severity="high",
                    status="open",
                    description=description,
                    evidence=evidence
                )
                db.add(finding)
                findings_to_commit.append(finding)

    # Commit the new findings
    db.commit()

    # Refresh the new findings to get IDs and other generated values
    # NOTE: Per requirements, we should NOT refresh created_at during repeated analysis
    # to preserve original created_at. However, we still need to refresh to get the ID
    # for newly created findings. Let's be selective about what we refresh.
    for finding in findings_to_commit:
        db.refresh(finding)
        # Build finding dict from new finding
        finding_dict = {
            "id": str(finding.id),
            "dataset_id": str(finding.dataset_id),
            "finding_type": finding.finding_type,
            "severity": finding.severity,
            "status": finding.status,
            "description": finding.description,
            "evidence": finding.evidence,
            "created_at": finding.created_at.isoformat() if finding.created_at else None
        }
        findings_to_return.append(finding_dict)

    return findings_to_return
