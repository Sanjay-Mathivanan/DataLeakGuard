# DataLeakGuard-CV --- Project Master Context

**Review basis:** `dataleakguard-cv (2).zip` uploaded on 15 October
2026\
**Purpose:** Reusable context for future ChatGPT and Claude Code
sessions.\
**Important:** This document describes the uploaded ZIP snapshot. The
live working folder may have changed since the ZIP was created.

## 1. Project identity and goal

**Project title:** DataLeakGuard-CV --- An Evidence-Based Integrity
Assurance Platform for Trustworthy Machine Learning and Computer Vision
Pipelines.

**Goal:** Help users assess dataset and ML/CV pipeline integrity by
detecting leakage or data-quality/integrity risks, recording evidence,
repairing or quarantining affected records, and ultimately supporting
trustworthy evaluation and assurance reporting.

Intended end-to-end lifecycle: 1. Upload and profile a dataset. 2.
Detect integrity/leakage findings. 3. Preserve evidence explaining why a
finding was raised. 4. Repair or quarantine affected data. 5.
Re-evaluate the dataset/model and measure impact. 6. Check
CV/model/inference integrity and distribution shift. 7. Produce an
assurance report.

This is the intended product workflow. Not every stage is implemented
against the real backend in the uploaded snapshot.

## 2. Technology stack

### Frontend

-   React + TypeScript + Vite.
-   React Router for pages/navigation.
-   Lucide React, Recharts, Motion and Tailwind/Vite plugin in
    `package.json`.
-   `src/services/api.ts` is the frontend service layer.
-   `.env.local` configures `VITE_API_BASE_URL` as
    `http://localhost:8000/api/v1` in the uploaded snapshot. Do not
    print or expose the contents of environment files in future logs.

### Backend

-   Python, FastAPI, Uvicorn.
-   SQLAlchemy 2, Pydantic 2, pydantic-settings.
-   SQLite configured by `DATABASE_URL = "sqlite:///./test.db"` in
    `backend/app/core/config.py`.
-   Pandas for tabular profiling/analysis, openpyxl for XLSX, Pillow for
    image ZIP profiling.
-   Requirements are pinned in `backend/requirements.txt`.

### Database and storage

-   The uploaded snapshot contains `backend/test.db` (53,248 bytes) with
    tables `datasets`, `repair_records`, and `leakage_findings`; dataset
    table has 4 rows and leakage findings table has 3 rows in this
    snapshot.
-   Root `test.db` is 0 bytes in this snapshot.
-   `backend/app/db/session.py` resolves the relative SQLite URL against
    the backend process's working directory. Start Uvicorn from
    `backend/` to use `backend/test.db`.
-   File storage paths are rooted from
    `backend/app/utils/file_storage.py`:
    -   `backend/storage/original/`
    -   `backend/storage/processed/`
    -   `backend/storage/quarantine/`
-   Uploaded files are saved under UUID-based names and a SHA-256 hash
    is calculated.

## 3. Backend architecture and implemented endpoints in the snapshot

### Application entry point

`backend/app/main.py` creates the FastAPI application, configures CORS
and includes routers for health, datasets, findings, repairs and
quarantine. API prefix defaults to `/api/v1`.

### Health

-   `GET /api/v1/health`

### Dataset upload, list, details and profiling

Implemented in `backend/app/api/v1/datasets.py` and
`backend/app/core/dataset_service.py`: - `POST /api/v1/datasets` ---
multipart upload with `name`, `type`, `format`, `description`, and
`file`. - `GET /api/v1/datasets` - `GET /api/v1/datasets/{dataset_id}` -
`GET /api/v1/datasets/{dataset_id}/profile` -
`DELETE /api/v1/datasets/{dataset_id}` -
`POST /api/v1/datasets/{dataset_id}/analyze/leakage` -
`GET /api/v1/datasets/{dataset_id}/findings`

Dataset upload validates extension/size, stores the file, calculates
SHA-256, profiles it, and saves a database record. For tabular CSV/XLSX,
it also computes sample count, feature count, column metadata and up to
six preview rows. `class_count` and `cv_stats` are currently left unset
in the tabular upload path.

### Leakage detection

The current backend service is
`backend/app/services/leakage_detection_service.py`. The dataset
analysis route wires up: - Exact duplicate detection. - Entity overlap
detection (requires entity and split columns). - Target leakage
detection (requires target column). - Temporal leakage detection
(requires time and split columns). - Train/test contamination detection
(requires split column).

The route documents validation rules for invalid combinations. The
actual data columns must exist in the uploaded dataset. This is not a
general ML model re-evaluation engine.

### Finding details and evidence

In `backend/app/api/v1/findings.py`: -
`GET /api/v1/findings/{finding_id}` -
`GET /api/v1/findings/{finding_id}/evidence`

Evidence service: `backend/app/services/evidence_service.py`.

### Repair and quarantine

Repair endpoints in `backend/app/api/v1/repairs.py`: -
`POST /api/v1/findings/{finding_id}/repair` -
`POST /api/v1/datasets/{dataset_id}/repairs` -
`GET /api/v1/repairs/{repair_id}` -
`GET /api/v1/datasets/{dataset_id}/repairs`

Quarantine endpoints in `backend/app/api/v1/quarantine.py`: -
`POST /api/v1/findings/{finding_id}/quarantine` -
`GET /api/v1/datasets/{dataset_id}/quarantines` -
`GET /api/v1/quarantines/{quarantine_id}`

Services: - `backend/app/services/repair_service.py` -
`backend/app/services/quarantine_service.py` -
`backend/app/services/repair_quarantine_utils.py`

The repair route explicitly says it currently processes exact-duplicate
findings. Do not claim all detection types have a complete automated
repair path without verifying implementation and tests.

## 4. Frontend status: real versus mock behavior

The frontend has pages for: - Dashboard - Dataset list and dataset
details - Analysis and leakage analysis - Repair - Impact analysis -
Model integrity - Inference provenance - Distribution shift - Reports
and report details - Login and registration

`src/services/api.ts` imports in-memory mock datasets, findings, models,
inference records, reports, activities and impact/distribution data. In
the uploaded snapshot: - Real HTTP calls are present for dataset list,
dataset detail, dataset upload and dataset deletion. - Most other
service functions still use in-memory mock data and simulated delays.
These include analysis progress/results, findings, repair UI operations,
model verification, inference/provenance, distribution shift, impact
analysis, reports, activities and dashboard stats. - Therefore, a UI
page rendering successfully does not mean its full workflow is connected
to the backend. - Keep the existing UI design. Integration should be
incremental and limited to the feature explicitly being worked on.

The `api.ts` file has a recursive snake_case-to-camelCase converter used
for backend dataset responses. Backend JSON uses snake_case; TypeScript
interfaces largely use camelCase.

## 5. Important source paths

### Backend core

-   `backend/app/main.py`
-   `backend/app/core/config.py`
-   `backend/app/core/dataset_service.py`
-   `backend/app/db/base.py`
-   `backend/app/db/session.py`
-   `backend/app/db/models.py`
-   `backend/app/db/leakage_models.py`
-   `backend/app/db/schemas.py`

### Backend routes

-   `backend/app/api/v1/health.py`
-   `backend/app/api/v1/datasets.py`
-   `backend/app/api/v1/findings.py`
-   `backend/app/api/v1/repairs.py`
-   `backend/app/api/v1/quarantine.py`

### Backend services/utilities

-   `backend/app/services/leakage_detection_service.py`
-   `backend/app/services/evidence_service.py`
-   `backend/app/services/repair_service.py`
-   `backend/app/services/quarantine_service.py`
-   `backend/app/services/repair_quarantine_utils.py`
-   `backend/app/utils/file_storage.py`
-   `backend/app/utils/row_hashing.py`
-   `backend/app/utils/profiling/tabular.py`
-   `backend/app/utils/profiling/image_zip.py`

### Frontend

-   `src/App.tsx`
-   `src/services/api.ts`
-   `src/types/index.ts`
-   `src/pages/DatasetsPage.tsx`
-   `src/pages/DatasetDetailPage.tsx`
-   `src/pages/LeakageAnalysisPage.tsx`
-   `src/pages/RepairPage.tsx`
-   `src/components/common/StatusBadge.tsx`
-   Other feature pages under `src/pages/`

### Tests

Tests are under `backend/tests/`, including dataset upload, health,
leakage API, exact duplicates, entity overlap, target leakage, temporal
leakage, train/test contamination, evidence, repair and quarantine
APIs/services/integration.

## 6. Project state found in the uploaded ZIP

The ZIP includes the `.git` directory, frontend dependencies, build
output, database files, debug logs/scripts and many storage files. It is
a snapshot, not a clean source-only archive.

Read-only `git status --porcelain=v1 -uall` run against the extracted
ZIP snapshot reported: - 560 modified tracked paths. - 26 deleted
tracked paths. - 11,502 untracked paths. - 12,088 status entries in
total.

Many of these are generated storage/cache/debug artifacts, but some are
legitimate source/test/report files. Do not use broad cleanup commands.

Storage paths represented in Git status: - `backend/storage/original/`:
10,026 status entries --- 526 modified tracked files, 10 deleted tracked
files, 9,490 untracked files. - `backend/storage/processed/`: 1,346
untracked files. - `backend/storage/quarantine/`: 604 untracked files.

The large status count explains why prior reports that used
default/abbreviated Git status were incomplete. Do not assume all
storage files are safe to delete merely because they are not referenced
by the current four dataset rows.

### Modified source/test paths in the ZIP snapshot

-   Backend: `backend/app/api/v1/datasets.py`,
    `backend/app/api/v1/findings.py`,
    `backend/app/core/dataset_service.py`, `backend/app/db/models.py`,
    `backend/app/main.py`,
    `backend/app/services/leakage_detection_service.py`.
-   Tests: `backend/tests/test_dataset_upload.py`,
    `test_entity_overlap_detection.py`,
    `test_exact_duplicate_detection.py`, `test_leakage_api.py`,
    `test_temporal_leakage_detection.py`,
    `test_train_test_contamination.py`.
-   Frontend: `src/components/common/StatusBadge.tsx`,
    `src/pages/DatasetDetailPage.tsx`, `src/pages/DatasetsPage.tsx`,
    `src/services/api.ts`.
-   Other changes include Python caches, database files, debug logs and
    storage uploads.

### New untracked application source files observed

These are source files and must be preserved: -
`backend/app/api/v1/quarantine.py` - `backend/app/api/v1/repairs.py` -
`backend/app/schemas/evidence.py` -
`backend/app/services/evidence_service.py` -
`backend/app/services/quarantine_service.py` -
`backend/app/services/repair_quarantine_utils.py` -
`backend/app/services/repair_service.py`

The previous audit claimed `backend/app/schemas/quarantine.py` and
`backend/app/schemas/repair.py`, but those files were not present in the
uploaded snapshot's schema directory. Always check the actual file tree
rather than copying old audit claims.

## 7. Known risks / items requiring cautious verification

1.  **Relative database URL:** `sqlite:///./test.db` depends on
    Uvicorn's working directory. Run from `backend/`; do not run a
    second backend accidentally.
2.  **Mixed frontend integration:** only dataset CRUD is real API-backed
    in the current snapshot; most feature pages remain mock-driven.
3.  **Debug side effects:** `backend/app/api/v1/datasets.py` writes to
    `debug_api.txt` when leakage analysis is called and includes
    multiple debug prints. This can generate artifacts during API use.
4.  **Dataset deletion:** the route deletes the database row and
    commits; it does not visibly remove the corresponding original
    storage file. Verify intended retention policy before changing this.
5.  **Profiling error handling:** extra metadata calculation in
    `dataset_service.py` catches broad exceptions and silently leaves
    fields unset; this can hide why preview/column metadata is missing.
6.  **CV profiling scope:** the image ZIP profiler returns basic image
    metadata/statistics. Do not describe this as full CV
    leakage/OOD/label-anomaly detection unless separately implemented
    and verified.
7.  **Test artifacts:** temporary preview tests, debug scripts, SQLite
    test DBs, logs, Python bytecode and storage uploads are present.
    Classify before cleanup.
8.  **Git deletions:** 26 tracked files are deleted in the snapshot. Do
    not restore or remove them automatically; inspect exact paths and
    diffs and ask before destructive changes.
9.  **Environment files:** `.env.local` is included in the ZIP. Do not
    print or copy secrets from environment files into prompts, logs,
    reports or public repositories.
10. **Frontend port:** package script declares `vite --port=3000`, while
    the developer's prior working setup used port 3001. Confirm the
    actual running frontend and use the existing setup rather than
    changing the port blindly.
11. **CORS:** backend defaults include `http://localhost:3001` and
    `http://localhost:8000`; if frontend runs at 3000, verify CORS
    configuration before changing it.

## 8. Previously reported verification (conversation context, not rerun on this ZIP)

The developer previously reported: - Backend full suite: 147 passed
(several runs). - Focused dataset upload tests: 4 passed. - Frontend
`npm run lint` and `npm run build` passed after dataset
integration/null-safe rendering changes. - Manual Swagger checks passed
for phases 1--5. - Dataset detail page was made null-safe for sample
count and last analysis; preview rows were under investigation.

These results are historical reports from prior work, not tests run as
part of this ZIP inspection. Do not rerun the full test suite
automatically because test runs have previously generated large numbers
of storage artifacts.

## 9. Working rules for future sessions

-   First read this document and inspect the current files before
    proposing code changes.
-   Treat the current working tree as the source of truth if it differs
    from this snapshot.
-   One step at a time: identify one blocking issue, make the smallest
    targeted change, verify it, then proceed.
-   Do not redesign the UI or refactor unrelated modules.
-   Do not run the full test suite repeatedly; choose targeted tests and
    avoid artifact-generating tests until cleanup/test isolation is
    planned.
-   Never run `git reset`, `git clean`, `git checkout .`, broad restore
    commands, or bulk storage deletion.
-   Preserve all source files, tests and intentional changes. No
    automatic cleanup based only on filename, age or missing database
    references.
-   Ask Claude Code to inspect first and propose a diff before editing
    when scope is unclear.
-   After edits, verify exact changed paths and command output. A claim
    of "done" is not verification.
-   For Claude Code prompts, specify exact files, expected behavior,
    non-goals, safety constraints, and verification commands.
-   Work in this order: understand → verify → plan → smallest change →
    test once → confirm.
