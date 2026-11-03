# DataLeakGuard-CV — Project Master Context

> **Project title:** DataLeakGuard-CV — An Evidence-Based Integrity Assurance Platform for Trustworthy Machine Learning and Computer Vision Pipelines  
> **Updated:** 29 October 2026  
> **Purpose:** A reusable project context for future ChatGPT, Claude Code, and developer sessions.

## 1. Project Goal

DataLeakGuard-CV helps assess dataset and ML/CV pipeline integrity by profiling datasets, detecting leakage and integrity risks, preserving evidence, and supporting repair or quarantine of eligible records.

**Intended workflow**
1. Upload and profile a dataset.
2. Run configured leakage and integrity checks.
3. Review persisted findings and supporting evidence.
4. Repair or quarantine eligible records.
5. Review operation history and re-analyse where supported.
6. Extend integrity assurance to model, inference, CV and distribution-shift workflows where implemented.
7. Produce assurance reports where implemented.

> **Scope note:** This is the intended product workflow. Not every stage has been confirmed as fully implemented or connected to the real backend. Verify the current code before making feature claims.

## 2. Technology Stack

### Frontend
- React
- TypeScript
- Vite
- React Router
- Lucide React, Recharts, Motion and Tailwind/Vite tooling (reported in the project)

### Backend
- Python
- FastAPI
- Uvicorn
- SQLAlchemy 2
- Pydantic 2 and pydantic-settings
- Pandas
- openpyxl for XLSX
- Pillow for basic image-ZIP profiling

### Database and file storage
- SQLite was used in the reviewed snapshot.
- The reviewed snapshot configured `DATABASE_URL` as `sqlite:///./test.db`.
- The relative database URL depends on the process working directory. Run Uvicorn from `backend/` when intending to use `backend/test.db`.
- Storage directories:
  - `backend/storage/original/`
  - `backend/storage/processed/`
  - `backend/storage/quarantine/`
- Uploaded files use UUID-based storage names and a SHA-256 digest is calculated.

## 3. Leakage Detection

The project has been reported to support five leakage/integrity detector categories:

1. **Exact duplicate detection**
2. **Entity overlap detection**
3. **Target leakage detection**
4. **Temporal leakage detection**
5. **Train/test contamination detection**

Detection depends on valid input data and the required configuration/columns. These checks should not be described as a general-purpose model retraining or model-quality evaluation engine.

## 4. Evidence, Repair and Quarantine

Later project progress reports describe:
- Persisted leakage findings and evidence.
- Finding detail and evidence API workflows.
- Repair and quarantine operations.
- Operation/history records.
- Combined repair support and regression fixes for recorded hash-excluded-column settings, stale settings, idempotency and legacy evidence enrichment.

**Important limitation:** Do not assume every finding category has a complete automated repair path. Verify current service rules and tests before claiming support for a specific finding type.

## 5. Authentication and Account Features

Later progress reports describe:
- Password hashing using scrypt.
- Opaque random sessions with token hashes.
- Default session expiry of 12 hours.
- Session revocation.
- HttpOnly session cookie and `SameSite=Lax`.
- CSRF cookie/checks and Origin/Referer validation on login and registration.
- Default rate limits reported as 5 login attempts per minute and 3 registrations per hour.
- Profile/account APIs, ownership checks, dashboard data, notifications and audit events.

Security configuration notes:
- Process-local rate limiting was the default. Shared multi-worker rate-limit storage was configurable but not reported as fully installed/tested.
- `AUTH_COOKIE_SECURE` was reported to default to `false` for local HTTP; production behind TLS should set it to `true`.
- CORS should allow the exact frontend origin. Do not use wildcard CORS as a shortcut for credentialed requests.
- Review trusted-proxy/client-IP assumptions before production deployment.

These are reported implementation details, not a substitute for a fresh security review.

## 6. Frontend Integration and Verification

The original reviewed ZIP snapshot described some pages as mock-driven, while later project reports described additional backend integration. Therefore, inspect the current `src/services/api.ts` and relevant page/service before classifying any screen as real API-backed.

Later reports included:
- Dashboard data wiring checked through isolated API tests.
- Authentication lifecycle and access-denial checks through API workflows.
- Persisted findings/timestamps and failed-analysis timestamp behavior.
- Repair/quarantine/history and download hash verification.
- Notification persistence, read state and user isolation through API checks.

Still requiring browser-level confirmation in the reports:
- Notification UI click/navigation.
- Complete dataset-tab UI workflows.
- Full end-to-end browser behavior across the app.
- Download history persistence was reported as not implemented.
- Dataset distribution/split counts should not be presented as a distribution-shift detector without further evidence.

## 7. Test Results (Historical Reports)

The following are historical test results from different project states, not a single current run:
- Phase D report: backend 215 passed, 1 skipped; frontend 48 passed; TypeScript/build passed.
- Phase E report: backend 227 passed, 1 skipped; frontend 48 passed; TypeScript/build passed.
- Later repair/functional verification report: focused backend tests 22 passed; full backend suite 229 passed, 1 skipped; frontend 48 passed; TypeScript/build passed.
- Earlier reports also mentioned 147 backend tests passing.

Warnings reported:
- Node 20.13.1 was below the stated Vite requirement of Node 20.19+ or 22.12+.
- Vite `__dirname` configuration warning.
- Large frontend JavaScript chunk warning (>500 kB).
- Pydantic `orm_mode` deprecation in favor of `from_attributes`.
- Pandas parsing/deprecation warnings.

Run relevant tests against the current working tree before using these counts as current status. Avoid repeated artifact-generating full test runs.

## 8. Run Locally

### Backend
Run from the backend directory:

```powershell
cd C:\Users\sanja\my_project\dataleakguard-cv\backend
python -m uvicorn app.main:app --reload
```

Health endpoint reported by the project:

```text
http://127.0.0.1:8000/api/v1/health
```

The `/health` route returned 404 in a prior run; use `/api/v1/health` if that remains the route in the current code.

### Frontend
Use the existing frontend setup and inspect `package.json` for the current start command and port. The reviewed snapshot declared Vite port 3000, while prior local runs used port 3001. Confirm the browser address before changing settings.

### CORS / Login `Failed to fetch`
A previous local run reported `OPTIONS /api/v1/auth/login` and `OPTIONS /api/v1/auth/register` returning 400. This may mean the exact frontend origin/port is not included in `BACKEND_CORS_ORIGINS`.

1. Confirm the frontend origin in the browser address bar, including the port.
2. Allow that exact local origin in backend CORS configuration.
3. Preserve credentialed requests and existing Origin/Referer/CSRF checks.
4. Do not use wildcard CORS.
5. Test that allowed-origin preflight succeeds and disallowed-origin preflight is rejected.
6. Do not rerun database migrations to fix CORS.

A 401 from `/api/v1/auth/me` while logged out may be expected. A missing `/favicon.ico` is usually non-critical.

## 9. Database Migration and Backups

A migration was reported as applied once to this local database only:

```text
C:\Users\sanja\my_project\dataleakguard-cv\backend\test.db
```

Reported checks:
- `users`, `auth_sessions`, `audit_events`, and `notifications` tables created.
- `datasets.owner_user_id` nullable.
- SQLite integrity check passed; no foreign-key violations.
- Counts preserved at that time: 10 datasets, 23 leakage findings, 17 repair records.
- Existing repair metadata was preserved.
- Ten legacy datasets remained unowned.
- Migration was not rerun after success.

Reported backup locations:
- `C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-backup-20261027-db1307ba43c941128c74cfce9ba68f3a`
- `C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-storage-backup-20261027-13d5d91ebc9748adb971d5ea4e7d2dfb`

These are historical paths. Confirm that backups still exist and are valid before relying on them. Do not assume another database, such as production, was migrated.

## 10. Important Source Paths

### Backend
- `backend/app/main.py`
- `backend/app/core/config.py`
- `backend/app/core/dataset_service.py`
- `backend/app/db/base.py`
- `backend/app/db/session.py`
- `backend/app/db/models.py`
- `backend/app/db/leakage_models.py`
- `backend/app/db/schemas.py`
- `backend/app/api/v1/health.py`
- `backend/app/api/v1/datasets.py`
- `backend/app/api/v1/findings.py`
- `backend/app/api/v1/repairs.py`
- `backend/app/api/v1/quarantine.py`
- `backend/app/services/leakage_detection_service.py`
- `backend/app/services/evidence_service.py`
- `backend/app/services/repair_service.py`
- `backend/app/services/quarantine_service.py`
- `backend/app/services/repair_quarantine_utils.py`
- `backend/app/utils/file_storage.py`
- `backend/app/utils/row_hashing.py`
- `backend/app/utils/profiling/tabular.py`
- `backend/app/utils/profiling/image_zip.py`

### Frontend
- `src/App.tsx`
- `src/services/api.ts`
- `src/types/index.ts`
- `src/pages/DatasetsPage.tsx`
- `src/pages/DatasetDetailPage.tsx`
- `src/pages/LeakageAnalysisPage.tsx`
- `src/pages/RepairPage.tsx`
- `src/components/common/StatusBadge.tsx`
- Other feature pages under `src/pages/`

### Tests
Tests are under `backend/tests/`. Reported coverage includes upload, health, leakage detection, evidence, repair and quarantine. Verify the current test tree before relying on this list.

## 11. Git and Repository Safety

The reviewed ZIP snapshot contained databases, dependencies/build output, logs/debug scripts, storage files and a `.git` directory. Its historical status report showed 560 modified tracked paths, 26 deleted tracked paths and 11,502 untracked paths. These numbers are snapshot-specific.

The project `.gitignore` was reported updated to ignore database files/sidecars, storage, Python bytecode/caches, pytest cache and local environment files while allowing `.env.example`. Ignoring files does not untrack files already in Git.

Rules:
- Never run `git reset`, `git clean`, `git checkout .`, broad restore commands or bulk storage deletion.
- Do not restore or remove deleted files without inspecting exact paths and diffs.
- Preserve source files, tests and intentional changes.
- Do not delete storage merely because a file is absent from current database rows.
- Inspect exact tracked generated files before changing the Git index; `git rm --cached` stages index removals.
- Do not stage, commit or push unless explicitly requested.
- Never print secrets from `.env.local` or other environment files.

## 12. Known Risks and Limits

1. Relative SQLite paths can open/create a different database if the working directory is wrong.
2. Current frontend integration may differ from the older ZIP snapshot.
3. Verify whether debug prints or `debug_api.txt` writes remain in the current code.
4. Verify whether dataset deletion also removes stored files; check retention requirements first.
5. Broad exception handling in profiling was a concern in the older snapshot; verify current code.
6. Basic image-ZIP metadata profiling is not equivalent to full CV leakage, out-of-distribution, label-anomaly or model-integrity detection.
7. Automated repair support may differ by finding category.
8. Download history was reported as not persisted.
9. API/unit tests do not prove full browser end-to-end behavior.
10. Production auth requires review of secure cookies, HTTPS, rate-limit storage, proxy configuration and secrets.
11. Do not claim model retraining, inference provenance, distribution-shift detection or real assurance-report generation unless implemented and tested.

## 13. Rules for Future ChatGPT / Claude Code Sessions

- Read this README and inspect the current source before proposing changes.
- The live working tree takes precedence over this document if they differ.
- Follow: **understand → verify → plan → smallest safe change → test once → confirm**.
- Address one blocking issue at a time.
- Do not redesign UI or refactor unrelated modules.
- For coding prompts, specify files, expected behavior, non-goals, safety constraints and verification commands.
- Ask for inspection and a proposed diff before editing when scope is unclear.
- Verify exact changed paths and command output after edits.
- Do not claim “done” without actual verification.
- Label historical test results as historical.
- Do not expose credentials, session tokens, secrets or personal data in logs or reports.

---

**Status note:** This README is a maintained project-context document based on an uploaded snapshot and later progress reports. It is not a fresh independent audit. Current source code, database path, and newly captured test output take precedence over historical notes.

## 14. Batch 1 implementation update (2026-11-02)

Completed Batch 1 Phases 1–4 only:

- Persisted findings use a new owner-scoped paginated/filterable endpoint
  (`GET /api/v1/datasets/{dataset_id}/findings/page`) while the legacy array
  endpoint remains available. The UI groups actual detector types and
  severities and distinguishes page records from global and filtered counts.
- Dataset Audit History uses the new owner-scoped paginated endpoint
  (`GET /api/v1/datasets/{dataset_id}/history/page`) and a timeline with
  event/status/date/search filters and persisted operation details.
- Feature Profiles search, filter, sort, summarize, and paginate stored
  profiling metadata without rescanning dataset files.
- Detector configuration uses `GET
  /api/v1/datasets/{dataset_id}/column-recommendations`, a deterministic
  metadata-only heuristic service for target/entity/split/timestamp roles.
  Suggestions do not auto-select or execute detectors; submission requires
  explicit user confirmation.

No database schema or migration change was introduced. Focused API/service
tests cover pagination, ownership, historical null-owner denial, heuristic
signals, ambiguous candidates, missing profile data, and large schemas.
Final isolated regression: backend **245 passed, 1 skipped**; frontend
**61 passed**; TypeScript/lint and production build passed. Browser interaction
for the new controls is NOT VERIFIED because no browser automation tool was
available. Phases 5–8 were not included in Batch 1.

## Batch 2 implementation and verification update (2026-11-03)

Batch 2 work now covers:

- **Phase 5:** explicit `existing`, `generated`, and `none` split strategies
  in `POST /api/v1/datasets/{dataset_id}/analyze/leakage`; deterministic,
  separately stored generated-split outputs at
  `POST /api/v1/datasets/{dataset_id}/split-strategies/generate`; split
  validation and strategy/audit metadata. Explicit existing mode requires
  complete membership. Legacy callers without `split_strategy` retain
  established API semantics, including ignoring rows with absent split
  membership and returning the previous paired-column validation errors.
- **Phase 6:** the Analysis workspace integrates profile/configuration
  summaries, split mode, advisory recommendations, detector execution
  results, skipped-check explanations, grouped findings, and navigation to
  persisted findings and dataset history.
- **Phase 7:** combined cleaning uses a read-only preview, explicit
  confirmation, a recomputed preview token, separate output, operation
  metadata/evidence references, stale-input rejection, and idempotent
  retries. Exact duplicates only are eligible.
- **Phase 8:** individual automatic repair remains deterministic
  exact-duplicate “keep first” only. It validates current finding evidence,
  verifies output hash/schema/row count and the affected duplicate group,
  and persists verification details. Other detector types remain
  unsupported for automatic repair.

These workflows reuse `RepairRecord.operation_metadata`, `AuditEvent`, and
existing dataset profile data. No new Batch 2 database schema or migration
was added or applied. Existing model/identity migrations are a separate
project concern and were not run in this continuation.

Final automated regression on 2026-11-03: backend full suite in a disposable
copy **256 passed, 1 skipped, 0 failed**; frontend configured suite **74
passed, 0 failed**; `npm run lint`/TypeScript passed; Vite production build
passed. Build emitted environment/configuration advisories: installed Node
v20.13.1 is below the Vite requirement, the Vite config uses `__dirname`
under native config loading, and one JS bundle exceeds 500 kB. No live
browser verification was run for Batch 2, so interactive workflows remain
NOT VERIFIED despite automated test results. The failed initial backend run
and compatibility correction are documented in the E2E report.

Preserve the inherited dirty Git worktree, including the staged and unstaged
state of `backend/test.db`. No staging, commit, reset, clean, migration,
project DB/storage/backup access, or destructive cleanup was performed for
this Batch 2 continuation.

## Browser-verification maintenance addendum — 2026-11-03

- Added response-only operation metadata normalization for repair, quarantine,
  combined-cleaning and audit/history responses. Historical missing/null
  `skipped_findings` becomes `[]` with an explicit unavailable indicator;
  persisted records are not rewritten.
- Frontend operation parsing and Repair & Quarantine rendering tolerate
  legacy metadata and distinguish missing historical information from an
  actual recorded empty list.
- Combined-cleaning preview exposes bounded actual source row positions,
  total count, truncation, and a digest of the complete row-position list;
  UI supports cancel before explicit confirmation. Raw row contents are not
  returned to limit sensitive-data exposure.
- Readmission target name tokens improve recommendation ranking, while
  derived/post-outcome names receive heuristic warnings/downranking.
  Recommendations remain advisory, user-selected targets are not overridden,
  and analysis context/evidence continues to use the submitted target.
- Fresh disposable regression: backend **263 passed, 1 skipped**; frontend
  **78 passed**; TypeScript/lint and production build passed. Detailed
  commands/evidence are in the E2E report.
- The supplied 6,224-row CSV was not located in the repository root, and no
  browser automation package was installed. Browser workflows remain NOT
  VERIFIED; automated split-mode coverage does not establish live UI behavior.
- No database schema/migration or project data changed. Preserve the inherited
  dirty worktree and `backend/test.db` index/worktree state.

## Remediation Center / Analysis Setup implementation addendum — 2026-11-03

- Frontend routes: `/analysis-setup/:id` is the explicit column/split setup;
  `/analysis/:id` presents a confirmed configuration and executes only after
  a separate user action; `/remediation/:id` is the consolidated
  detector-grouped remediation workflow. `/repair/:id` remains a compatible
  entry route to the center.
- `RemediationCenterPage` uses the owner-scoped findings page endpoint.
  Collapsed detector summaries are bounded to one item; expanded pages contain
  at most 10 findings. Search/severity/status are server-filtered; backend
  ordering remains stable. All-open selection is server-resolved and described
  as candidates because the preview may identify evidence-ineligible findings.
- Remediation actions are supported only when evidence and configuration
  validate: exact duplicate keep-first; entity group split or row-evidence
  quarantine; confirmed target-feature exclusion; explicit-cutoff chronological
  split; and contamination handling with explicit retained partition or
  quarantine. Unknown or unsupported findings remain review-only/unresolved.
- Plans bind source SHA-256 and a finding/evidence snapshot; preview supports
  cancellation and explicit confirmed execution. Output files are separate
  from source and include final CSV, repair report CSV, JSON manifest and
  optional quarantine CSV. Post-output verification/status and output hashes
  are stored in existing repair-operation metadata; audit events use existing
  audit records.
- Analysis Setup passes the user's confirmed choices to Analysis via
  dataset-keyed sessionStorage; no role recommendation is silently applied
  and no detector runs as a result of selecting a suggestion.
- No schema/migration change was required. Fresh isolated regression:
  backend 277 passed/1 skipped; frontend 86 passed; lint/typecheck and Python
  compilation passed; build passed with existing Node/Vite/config/chunk
  warnings. Exact commands and limitations are in the E2E report.
- Live browser, authenticated workflow, real click-through/download events,
  supplied synthetic dataset execution and production-scale memory/latency
  are NOT VERIFIED. Existing deployment caveats remain; no production-ready
  claim is made.
