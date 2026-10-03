import os
import pandas as pd
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from typing import Optional, List
from app.db import models, leakage_models
from app.utils.row_hashing import hash_row

STORAGE_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "storage", "original"))

def detect_exact_duplicates(dataset_id: str, db: Session, exclude_columns: Optional[List[str]] = None):
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

    # Build storage path
    storage_path = os.path.join(STORAGE_BASE, dataset.storage_filename)
    if not os.path.exists(storage_path):
        raise HTTPException(status_code=404, detail="Stored file not found")

    # Read file based on format
    try:
        if dataset.format.upper() == "CSV":
            df = pd.read_csv(storage_path, dtype=str)  # read all as string to preserve exact values
        elif dataset.format.upper() == "XLSX":
            df = pd.read_excel(storage_path, dtype=str)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")


    # Apply exclusions if specified
    if exclude_columns:
        # Only exclude columns that actually exist in the dataframe
        existing_exclusions = [col for col in exclude_columns if col in df.columns]
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
                "row_indices": group.index.tolist()  # zero-based row numbers in the dataframe
            }

            # Check if finding already exists (idempotency)
            existing = db.query(leakage_models.LeakageFinding).filter(
                leakage_models.LeakageFinding.dataset_id == dataset_id,
                leakage_models.LeakageFinding.finding_type == "exact_duplicate",
                leakage_models.LeakageFinding.evidence == evidence
            ).first()

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
    split_column: str
) -> list:
    """
    Detect entity overlap in a dataset's stored file.
    Returns a list of finding dicts to be added to the analysis findings.
    """
    # Get dataset
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Build storage path
    storage_path = os.path.join(STORAGE_BASE, dataset.storage_filename)
    if not os.path.exists(storage_path):
        raise HTTPException(status_code=404, detail="Stored file not found")

    # Read file based on format
    try:
        if dataset.format.upper() == "CSV":
            df = pd.read_csv(storage_path, dtype=str)
        elif dataset.format.upper() == "XLSX":
            df = pd.read_excel(storage_path, dtype=str)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

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
    non_empty_entity_mask = entity_series != ''
    non_empty_split_mask = split_series != ''
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

    # Check for entity overlap between splits
    # For conventional case: train -> test, validation -> test, etc.
    # We'll check all pairs of entities where one should temporally precede the other
    entity_values = list(entity_splits.keys())

    # Define conventional order (earlier to later)
    conventional_order = ["train", "validation", "val", "test"]

    # Check each pair of entities
    for i, entity1 in enumerate(entity_values):
        for j, entity2 in enumerate(entity_values):
            if i >= j:  # Avoid duplicate pairs and self-pairs
                continue

            # Determine which entity should come first based on conventional ordering
            # If both entities are in conventional order, use that
            # Otherwise, use alphabetical order as fallback
            entity1_order = conventional_order.index(entity1) if entity1 in conventional_order else len(conventional_order) + entity_values.index(entity1)
            entity2_order = conventional_order.index(entity2) if entity2 in conventional_order else len(conventional_order) + entity_values.index(entity2)

            # If entity1 should come before entity2
            if entity1_order < entity2_order:
                earlier_entity = entity1
                later_entity = entity2
            else:
                earlier_entity = entity2
                later_entity = entity1

            # Get split sets
            earlier_splits = set(entity_splits[earlier_entity]["splits"])
            later_splits = set(entity_splits[later_entity]["splits"])

            # Check for split overlap: any split appears in both entities
            split_overlap = earlier_splits.intersection(later_splits)

            if split_overlap:
                # Build evidence for entity overlap
                evidence = {
                    "entity_column": entity_column,
                    "split_column": split_column,
                    "detection": "entity_overlap",
                    "entities": {
                        earlier_entity: entity_splits[earlier_entity],
                        later_entity: entity_splits[later_entity]
                    },
                    "overlapping_splits": list(split_overlap)
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
                    if len(split_overlap) == 1:
                        description = f"Entity overlap detected: entity '{earlier_entity}' and entity '{later_entity}' share split '{list(split_overlap)[0]}'."
                    else:
                        description = f"Entity overlap detected: entity '{earlier_entity}' and entity '{later_entity}' share splits {list(split_overlap)}."

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
    target_column: str
) -> list:
    """
    Detect target leakage in a dataset's stored file.
    Returns a list of finding dicts to be added to the analysis findings.
    """
    # Get dataset
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Build storage path
    storage_path = os.path.join(STORAGE_BASE, dataset.storage_filename)
    if not os.path.exists(storage_path):
        raise HTTPException(status_code=404, detail="Stored file not found")

    # Read file based on format
    try:
        if dataset.format.upper() == "CSV":
            df = pd.read_csv(storage_path, dtype=str)
        elif dataset.format.upper() == "XLSX":
            df = pd.read_excel(storage_path, dtype=str)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

    # Check that target_column exists
    if target_column not in df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Target column '{target_column}' not found in dataset columns"
        )

    # Normalize target values: strip whitespace, treat null/empty as missing
    target_series = df[target_column].astype(str).str.strip()

    # Mask for non-empty target values
    non_empty_target_mask = target_series != ''
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

        # Get feature and target series
        feature_series = df_filtered[column]
        target_series = target_series_filtered

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

        # Iterate through rows to build mapping
        for idx, (feature_val, target_val) in enumerate(zip(feature_series, target_series)):
            # Skip if either value is empty
            if feature_val == '' or target_val == '':
                continue

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

        # Check for exact target duplication
        if is_exact_duplicate and len(mapping) > 0:
            # All feature values map to the same target value
            # This means the feature column exactly duplicates the target column
            unique_targets = set(mapping.values())
            if len(unique_targets) == 1:
                # Build evidence for exact target duplication
                evidence = {
                    "target_column": target_column,
                    "feature_column": column,
                    "detection": "exact_target_duplicate",
                    "matching_rows": len(df_filtered),
                    "total_valid_rows": len(df_filtered)
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

        # Check for deterministic feature -> target mapping
        elif is_deterministic_mapping and len(mapping) > 0 and len(conflicting_mappings) == 0:
            # Each feature value maps to exactly one target value
            # But different feature values can map to different target values
            unique_feature_values = set(mapping.keys())
            unique_target_values = set(mapping.values())

            # Apply conservative evidence requirements:
            # - Feature must have at least 2 distinct non-null values
            # - Target must have at least 2 distinct non-null values
            # - All valid feature values must map to exactly one target value
            # - At least 2 distinct target groups must be represented
            # - Target column itself is never flagged
            if (len(unique_feature_values) >= 2 and
                len(unique_target_values) >= 2 and
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
                        "finding_type": finding.finding_type,
                        "severity": finding.severity,
                        "status": finding.status,
                        "description": finding.description,
                        "evidence": finding.evidence,
                        "created_at": finding.created_at.isoformat() if finding.created_at else None
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
    split_column: str
) -> list:
    """
    Detect temporal leakage in a dataset's stored file.
    Returns a list of finding dicts to be added to the analysis findings.
    """
    # Get dataset
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Build storage path
    storage_path = os.path.join(STORAGE_BASE, dataset.storage_filename)
    if not os.path.exists(storage_path):
        raise HTTPException(status_code=404, detail="Stored file not found")

    # Read file based on format
    try:
        if dataset.format.upper() == "CSV":
            df = pd.read_csv(storage_path, dtype=str)
        elif dataset.format.upper() == "XLSX":
            df = pd.read_excel(storage_path, dtype=str)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

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
    split_column: str
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

    # Build storage path
    storage_path = os.path.join(STORAGE_BASE, dataset.storage_filename)
    if not os.path.exists(storage_path):
        raise HTTPException(status_code=404, detail="Stored file not found")

    # Read file based on format
    try:
        if dataset.format.upper() == "CSV":
            df = pd.read_csv(storage_path, dtype=str)
        elif dataset.format.upper() == "XLSX":
            df = pd.read_excel(storage_path, dtype=str)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

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

    # Determine if any rows were filtered out due to null/empty split values
    rows_filtered_out = len(df) - len(df_filtered)

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

    # DEBUG: Print when function is called
    print(f"DEBUG detect_train_test_contamination called for dataset_id={dataset_id}, split_column={split_column}")

    # Process each group of rows with the same hash
    for row_hash, group in grouped:
        # Get the split values for this group
        group_split_series = split_series_filtered[group.index]
        unique_splits = set(group_split_series.tolist())
        split_count = len(unique_splits)

        # Create a contamination finding ONLY when:
        # number of distinct splits > 1
        if split_count > 1:
            # Get original dataframe indices for this group
            original_indices = [int(idx) for idx in group.index]

            # Apply the logic discovered through test analysis:
            if rows_filtered_out > 0:
                # Case: rows were filtered out due to null/empty split values
                # Show position within each split's group
                row_indices_data = {}

                # Pre-compute the positions of each split value in the full df_filtered
                split_positions = {}
                for split_val in sorted(unique_splits):
                    # Find all indices in df_filtered where this split value occurs
                    positions = [
                        int(idx) for idx in split_series_filtered.index[
                            split_series_filtered == split_val
                        ]
                    ]
                    split_positions[split_val] = positions

                # For each split value in the contamination group, find its positions
                for split_value in sorted(unique_splits):
                    # Find which rows in the group have this split value
                    group_rows_with_split = [
                        int(i) for i, val in enumerate(group_split_series)
                        if val == split_value
                    ]

                    # For each such row, get its position within all rows of that split
                    positions_in_split = []
                    for group_row_idx in group_rows_with_split:
                        # Get the actual index in df_filtered
                        df_filtered_idx = int(group.index[group_row_idx])
                        # Find the position of this df_filtered_idx within all rows of this split
                        position_in_split = int(split_positions[split_value].index(df_filtered_idx))
                        positions_in_split.append(position_in_split)

                    row_indices_data[split_value] = positions_in_split

            elif len(unique_splits) == 2:
                # Special case for exactly 2 splits:
                # Check if contamination group includes ALL rows or just a subset
                # Get total rows in df_filtered
                total_rows_in_filtered = len(df_filtered)
                contamination_group_size = len(group)

                if contamination_group_size == total_rows_in_filtered:
                    # Contamination group includes ALL rows -> show precise per split
                    # For each split, show the original indices where canonical row appears AND is in that split
                    row_indices_data = {}
                    for split_value in sorted(unique_splits):
                        # Find indices in the group where split equals this value
                        indices_in_group = [
                            int(group.index[i]) for i, val in enumerate(group_split_series)
                            if val == split_value
                        ]
                        row_indices_data[split_value] = indices_in_group
                else:
                    # Contamination group is a SUBSET -> show union (all canonical row indices, duplicated)
                    # Get all original indices where canonical row appears
                    all_canonical_indices = original_indices.copy()
                    row_indices_data = {}
                    for split_value in sorted(unique_splits):
                        row_indices_data[split_value] = all_canonical_indices.copy()

            else:
                # Case: more than 2 splits OR (2 splits but we didn't match above conditions)
                # Show position within contamination group for each split
                row_indices_data = {}
                # Create a mapping from group position to original index for easy lookup
                group_pos_to_orig_idx = {int(i): int(group.index[i]) for i in range(len(group.index))}

                for split_value in sorted(unique_splits):
                    # Find which rows in the group have this split value
                    group_rows_with_split = [
                        int(i) for i, val in enumerate(group_split_series)
                        if val == split_value
                    ]

                    # For each such row, get its position within the contamination group
                    positions_in_group = []
                    for group_row_idx in group_rows_with_split:
                        # Position of this row within the contamination group (0-based)
                        position_in_group = int(group_rows_with_split.index(group_row_idx))
                        positions_in_group.append(position_in_group)

                    row_indices_data[split_value] = positions_in_group

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