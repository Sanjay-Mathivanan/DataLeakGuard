# Step 3.2: Entity / Identity Overlap Detection - Implementation Summary

## Overview
Implemented deterministic Entity / Identity Overlap detection for Phase 3, Step 3.2 as requested. Extended the existing leakage analysis API to support optional `entity_column` and `split_column` query parameters while preserving existing Step 3.1 exact duplicate detection behavior.

## Changes Made

### 1. Service Layer (`backend/app/services/leakage_detection_service.py`)
- Added `detect_entity_overlap` function that:
  - Takes `dataset_id`, `db`, `entity_column`, and `split_column` parameters
  - Reads dataset file (CSV/XLSX) from storage
  - Validates column existence
  - Normalizes entity values (strips whitespace, treats null/empty as missing)
  - Groups by entity value and detects overlaps across splits
  - Builds evidence structure: `{entity_column, split_column, entity_value, splits[], row_indices:{split_value: [row_indices]}}`
  - Implements idempotency by checking for existing LeakageFinding records with matching evidence
  - Creates new LeakageFinding records with `finding_type="entity_overlap"`, `severity="high"`
  - Returns list of finding dicts compatible with API response format

### 2. API Layer (`backend/app/api/v1/datasets.py`)
- Updated import: `from app.services.leakage_detection_service import detect_exact_duplicates, detect_entity_overlap`
- Updated `analyze_leakage` endpoint:
  - Added optional `entity_column: Optional[str] = None` and `split_column: Optional[str] = None` parameters
  - Always runs exact duplicate detection first (preserving Step 3.1 behavior)
  - If both parameters provided: runs entity overlap detection and combines findings
  - If only one parameter provided: returns HTTP 400 with detail "Both entity_column and split_column must be provided for entity overlap detection"
  - If neither parameter provided: runs only exact duplicate detection (original behavior)

### 3. Test Suite (`backend/tests/test_entity_overlap_detection.py`)
- Created comprehensive test suite with 9 test functions:
  1. `test_entity_overlap_detected` - Basic overlap detection and evidence structure
  2. `test_no_entity_overlap` - Dataset with no overlap returns empty findings
  3. `test_multiple_overlapping_entities` - Handles multiple entities with overlaps
  4. `test_missing_entity_column` - Validates both parameters required
  5. `test_only_one_parameter_supplied` - Duplicate of above (kept for clarity)
  6. `test_repeated_analysis_idempotent` - Ensures idempotent behavior
  7. `test_existing_step31_behavior` - Preserves exact duplicate detection when no params provided
  8. `test_findings_api_returns_entity_overlap` - Integration with dataset findings endpoint
  9. `test_individual_finding_api_returns_entity_overlap` - Integration with individual finding endpoint

## Key Features
- **Deterministic**: Consistent normalization and evidence building
- **Idempotent**: Repeated analyses with same parameters don't create duplicate findings
- **Backward Compatible**: Existing Step 3.1 behavior unchanged when parameters not provided
- **Correct Evidence Structure**: Matches specification exactly including row_indices per split
- **Proper Error Handling**: Returns HTTP 400 for invalid parameter combinations
- **Reuse of Existing Components**: Leverages existing LeakageFinding model, database session, and file storage patterns

## Verification
- All new tests pass (9/9)
- All existing leakage API tests continue to pass (6/6)
- Manual verification confirms correct behavior for various scenarios

## Files Modified
1. `backend/app/services/leakage_detection_service.py` - Added detect_entity_overlap function
2. `backend/app/api/v1/datasets.py` - Updated analyze_leakage endpoint and imports
3. `backend/tests/test_entity_overlap_detection.py` - New comprehensive test suite

## Files Not Modified (as per restrictions)
- Frontend files
- Base models
- File storage service (`file_storage.py`)
- Dataset service (`dataset_service.py`)
- Database models (reused existing LeakageFinding model)

The implementation satisfies all requirements for Phase 3, Step 3.2 and is ready for review.