# DataLeakGuard-CV Implementation Report

## Scope

This implementation connects the previously frontend-only model, provenance,
distribution, impact, and report workflows to owner-scoped FastAPI endpoints.
The scope follows the approved product contract:

- model artifacts are registered and verified by SHA-256;
- provenance records persist supplied metadata and explicitly use
  `prediction_status=no_prediction`;
- distribution comparisons persist tabular reference/current metrics;
- impact metrics persist findings, operations, and affected-row counts;
- reports persist JSON payloads and support JSON/HTML downloads.

No inference engine, model retraining, behavioral model verification, accuracy
comparison, HMAC signing, or PDF generator was added.

## Backend changes

- Added additive SQLite tables for artifacts, provenance, comparisons, impact
  metrics, and report metadata.
- Added authenticated, owner-scoped create/list/read/verify/download routes in
  [`backend/app/api/v1/workflows.py`](backend/app/api/v1/workflows.py).
- Added workflow schemas, tabular metric calculations, report HTML rendering,
  and isolated artifact storage.
- Added the forward-only migration
  [`backend/migrations/001_add_scoped_workflows.sql`](backend/migrations/001_add_scoped_workflows.sql).
- Created and validated a SQLite backup before migration. Existing data was
  preserved and `PRAGMA integrity_check` returned `ok`.

## Frontend changes

- Replaced model listing and verification mock calls with artifact APIs.
- Replaced provenance listing with persisted metadata records.
- Replaced distribution, impact, and report reads with API calls.
- Replaced simulated PDF success with actual HTML report download.
- Fixed HTML report rendering and removed the fabricated accuracy-inflation
  value from the report detail view.
- Removed fabricated inference execution from the request path; the UI now
  receives an explicit configuration error because no inference engine exists.
- Added service methods for artifact upload, provenance creation, distribution
  comparison, and report download.
- Connected the model upload modal to real file selection/upload/download
  behavior.
- Added owned-dataset selectors for distribution comparison, impact metrics,
  and provenance metadata creation.
- Removed unsupported contaminated-versus-sanitized impact claims from the
  impact page and corrected dashboard model/report counts.
- Updated the README endpoint and capability documentation.

## Verification

| Check | Result |
|---|---|
| Backend regression suite | 235 passed, 1 skipped |
| Frontend tests | 48 passed, 0 failed |
| TypeScript check | Passed |
| Vite production build | Passed |
| Python compilation | Passed |
| SQLite integrity check | Passed before and after migration |

The build reports existing environment warnings: Node 20.13.1 is below the
preferred Vite 20.19+ floor, the bundle is large, and dependency deprecations
remain. These warnings did not prevent the build.

## Live browser verification

A fresh browser run registered disposable users, uploaded disposable CSV
datasets, exercised all five configured detector paths, inspected persisted
findings/evidence, completed exact-duplicate repair and entity-overlap
quarantine, verified artifact tamper detection and restoration, validated
report JSON/HTML responses, and confirmed cross-user isolation plus post-logout
401 rejection. The supplied hospital dataset was also uploaded and exercised:
76 findings were persisted across five completed detectors, with repair and
quarantine operations recorded. The detailed matrix and exact
PASS/PARTIAL/NOT VERIFIED scenarios are in
[`DataLeakGuard-CV_E2E_TEST_REPORT.md`](DataLeakGuard-CV_E2E_TEST_REPORT.md).

## Remaining limitations

The backend remains a local SQLite application and is not production
deployment hardening. Browser download-event capture remains incomplete because
the integrated browser reports attachment requests as `ERR_ABORTED`;
authenticated response bytes and SHA-256 values were independently validated
for model artifacts and reports, while the supplied-dataset operation download
object was not exposed. User A was unavailable, so disposable users were used
for isolation.

## Codex continuation — report honesty correction (2026-10-29)

Read-only code review found the report API mapper was synthesizing severity
counts, a 0% confidence score, `MODERATE` risk, and `REVIEW` disposition even
though the persisted report payload contains only dataset manifest fields and
impact counts. The frontend now maps the persisted payload, labels unsupported
assessment fields `NOT ASSESSED`/unavailable, displays the persisted dataset
manifest and impact counts, and states that model performance, full evidence,
severity breakdowns, risk scoring, and disposition are not provided by this
report generator. Report list/detail also display API errors separately from
empty/not-found states.

Fresh focused verification after this change:

- `rtk proxy node --import tsx --test src/services/api.test.ts`: 25 passed,
  0 failed, including two new report mapping/creation tests.
- Post-fix `rtk proxy npm test`: 50 passed, 0 failed, 0 skipped.
- Post-fix `rtk proxy npm run lint` (`tsc --noEmit`): passed without diagnostics.
- Production build after the fix was pending at the time of this report update;
  its result is recorded in the E2E report after completion.
- No backend, database, migration, storage, or report-record changes were
  made. Browser rendering of the changed report pages remains NOT VERIFIED.

### Codex continuation — honest distribution and provenance states (2026-10-29)

The frontend distribution mapper now consumes persisted per-column metrics
without substituting zero for absent scores. Numeric PSI and categorical
distribution deltas remain distinguishable; the displayed mean PSI includes
numeric columns only. The UI explicitly marks Wasserstein distance, OOD rate,
and target-class prevalence unavailable because these are not persisted by the
current comparison workflow, and avoids claiming a fixed/moderate drift result
without evidence.

Metadata-only provenance records now carry a null confidence value, which the
UI displays as unavailable rather than `0%`. Provenance-entry controls no
longer start with fictional sample asset names, a made-up model ID, or
preselected preprocessing settings. This does not add model inference,
behavioral verification, or target-distribution analysis.

Fresh checks on 2026-10-29: frontend suite **51 passed**; TypeScript
`npm run lint` passed; production build passed to a new temporary output
directory outside the repository. Browser rendering remains NOT VERIFIED.

The final display-only refinement separates the numeric PSI chart from
categorical distribution deltas and uses a truthful empty state when there are
no numeric PSI metrics. Metadata-only confidence no longer renders an empty
zero-width confidence bar. Final frontend tests (51 passed), TypeScript check,
and production build all passed after these refinements.

## Batch 1 — Phase 1: Findings UI and server pagination (2026-11-02)

Added an authenticated owner-scoped paginated findings endpoint at
`GET /api/v1/datasets/{dataset_id}/findings/page`. It validates page offsets and
sizes, supports server-side search over persisted finding ID, detector type,
description, and serialized evidence, plus detector/severity/status filters.
The response separates dataset-wide totals from the totals matching the
current search and filters. Unknown detector and nonstandard severity values
are retained as “other”; they are not mapped to one of the five known
detectors. The existing array endpoint remains unchanged for compatibility.

The frontend now has reusable detector/severity grouping, a paginated
persisted-findings browser, summary totals, server-backed search/filter
controls, and pagination. Persisted findings in the dataset detail tab and
Leakage Analysis workspace use the browser. The current analysis response uses
the grouping component with a distinct source label and is not presented as
the complete persisted query. Finding ID, type, severity, status, creation
time, description, and evidence remain inspectable.

No new database table, column, or migration was introduced. Focused isolated
backend verification: 4 passed. Focused frontend/API verification: 29 passed;
TypeScript check passed. Browser interaction has not been verified. Details
and exact commands are in `DataLeakGuard-CV_E2E_TEST_REPORT.md`.

## Batch 1 — Phase 2: Dataset audit-history timeline (2026-11-02)

Added `GET /api/v1/datasets/{dataset_id}/history/page` while retaining the
existing history array API. The endpoint checks dataset ownership, combines
persisted `AuditEvent` and `RepairRecord` rows, avoids duplicating operation
records already linked to audit events, and supports bounded pagination,
activity type, status, date range, and operation/dataset search. It exposes
only fields available from the persisted models, including operation IDs,
finding IDs, actor ID, start/completion timestamps, operation metadata, and
failure reason where present. Timestamp-based upload/analysis fallback items
remain identified by their persisted source metadata rather than presented as
independent audit records.

The Dataset Detail → Audit History tab now renders a filterable timeline with
distinct loading, error, and empty states, expandable details, and
status-specific styling. No database schema or migration change was needed.
Focused isolated backend coverage passed (6 tests including Phase 1); frontend
suite passed (56 tests); TypeScript passed. Browser interaction is NOT
VERIFIED. Detailed test evidence is in the E2E report.

## Batch 1 — Phase 3: Feature Profiles (2026-11-02)

Enhanced the existing Feature Profiles tab using only persisted
`dataset.columns` metadata. Added case-insensitive column-name search, type,
missing-value, and high-cardinality filters, numeric/string sorting, a
50-column display page, and summary counts for columns by identified profile
kind and stored missing values. Numeric statistics remain distinct from
categorical top-value frequencies. Categorical frequencies show a short
preview and expand to the stored values (at most the backend's existing top
ten); absent metadata is labelled unavailable instead of being filled with
zeroes.

Column kinds use the stored dtype/profile metadata. Date/time identification
is limited to dtype markers containing date/time/timestamp. High-cardinality
is an explicit display heuristic: unique count >20 and unique/sample ratio
≥0.5; it is not a statistical claim. No backend, schema, or migration change.
Frontend suite passed (58 tests) and TypeScript passed; browser interaction is
NOT VERIFIED. See E2E report for command evidence.

## Batch 1 — Phase 4: Intelligent detector-column configuration (2026-11-02)

Added the metadata-only service
`backend/app/services/column_recommendation_service.py` and authenticated,
owner-scoped `GET /api/v1/datasets/{dataset_id}/column-recommendations`.
Supported tabular CSV/XLSX datasets use persisted profile columns and no more
than six stored preview rows; no repeated full file scan or third-party AI
service is used. Arbitrary raw preview values are not returned. Split-label
evidence is limited to the recognized train/test/validation vocabulary.

The service ranks candidates for target, entity, split, and timestamp roles
using token-aware names, stored dtype, unique/missing ratios, recognized split
labels, and bounded date parsing. Scores are heuristic points, never
probabilities. Weights and confidence/acceptance cutoffs are recorded in the
E2E report and covered by representative score tests. It returns reasons,
signals, candidate profile fields, alternatives, ambiguity warnings, and
“no reliable recommendation” when the best score is below 50.

The analysis UI now displays candidates and profile metadata without
auto-selecting them. A searchable type-filtered selector renders 50 columns at
a time, with keyboard/tab-accessible native controls. Manual selections and
recommendation choices are possible, and a separate explicit configuration
confirmation is required before running detector analysis. No change to
detector algorithms, database schema, or migration. Focused backend tests: 10
passed including Phases 1–2; frontend suite: 61 passed; TypeScript passed.
Browser interaction and actual analysis submission through these controls
remain NOT VERIFIED.

## Batch 1 final regression (2026-11-02)

The complete backend suite passed in a disposable source copy: **245 passed,
1 skipped, 191 warnings**. The frontend suite passed: **61 passed**; the
TypeScript/lint command passed; the production build passed to a new temporary
directory. Build warnings are the installed Node 20.13.1 version below Vite's
minimum, Vite's existing native config-loader/`__dirname` warning, and the
advisory oversized JavaScript chunk. Browser interaction for the new controls
remains NOT VERIFIED. The full diff check is PARTIAL due to pre-existing
trailing whitespace on master-context lines 3–4. No database migration or
schema change was made.

## Batch 2 — Phase 5: Dataset split strategy (2026-11-02)

Added an owner-scoped split-copy generation endpoint,
`POST /api/v1/datasets/{dataset_id}/split-strategies/generate`, with bounded
test ratio and signed 32-bit random seed validation. Generation writes a
separate CSV/XLSX output using the deterministic
`sha256_seeded_row_order_v1` row-order algorithm; the original is never
overwritten. Equivalent requests reuse a completed output only when the input
digest, configuration, and output digest still verify. The operation is
persisted in the existing `repair_records` metadata and a corresponding
`AuditEvent` records configuration and hashes.

The existing analysis endpoint now explicitly supports `existing`, `generated`,
and `none` strategies while preserving legacy requests (`split_column` means
existing split; no split column means no split). Existing splits are manually
selected and validated for column existence, nonblank membership, and at
least two groups. Generated analysis requires a dataset-owned completed split
operation, a matching source digest, a verified output digest, and valid split
metadata. In no-split mode, split-dependent checks are omitted and returned as
`skipped_detectors`; they are not reported as clean. The chosen strategy is
stored in dataset profile metadata and analysis audit details. Detector
services accept an optional in-memory frame, retaining existing call
signatures and avoiding repeated full-file reads.

No schema migration or database change was introduced. Focused verification
ran in the disposable backend copy
`C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-B2-phase5-20261102-splits`:
`rtk proxy python -m pytest tests/test_split_strategy.py tests/test_leakage_api.py -q -p no:cacheprovider`
passed **14 tests, 0 failed, 21 warnings**. Coverage includes all three
strategies, split validation, generated-output determinism/reuse, audit and
profile persistence, source preservation, owner isolation, request bounds,
and compatibility with existing analysis tests. The first run exposed a test
harness issue (an import-time reference bypassed the fixture's disposable DB
monkeypatch); the test was corrected to resolve the fixture session at
runtime, then the command passed. The frontend configuration and browser
status are superseded by the Batch 2 continuation entry below.

## Batch 2 continuation — Phases 5–7 (2026-11-02)

The Analysis workspace now offers explicit existing/generated/no-split
selection, a confirmed deterministic split-copy generation flow, and
configuration/profile/result summaries. Detector recommendations remain
advisory and are not silently applied. The workspace keeps current-run
findings separate from paginated persisted findings, reports skipped
split-dependent checks explicitly, and links to dataset profile, findings and
history. The split-generation operation and analysis strategy use existing
repair/audit metadata; no schema migration was added.

Combined cleaning now has a read-only server preview and a separate confirmed
execution step. The preview token binds the current source digest, selected
and eligible finding IDs, excluded-finding reasons, row counts, and affected
indices. The execution endpoint requires explicit confirmation and a token
that still matches the recomputed preview. It writes a separate output and
persists evidence references and preview provenance in existing operation
metadata. Equivalent confirmed request retries return the existing operation.
Only exact-duplicate findings are eligible; unsupported or stale findings are
reported as excluded, while cross-dataset selections are rejected.

No database schema or migration changes were required. Focused isolated
verification on 2026-11-02: backend combined-cleaning and authentication
tests **31 passed, 0 failed**; frontend API and RepairPage tests **49 passed,
0 failed**; TypeScript check passed. Browser interaction remains NOT
VERIFIED. Phase 8 individual-repair preview/confirmation and post-repair
verification are not yet complete; automatic repair remains limited to
exact duplicates. Full regression is pending. No project database, storage,
backup, migration, or Git index was modified.

## Batch 2 final verification update — Phases 5–8 (2026-11-03)

The previously noted Phase 8/full-regression status above is historical and
is superseded by this final continuation:

- **Phase 5 — split strategy:** existing, generated-copy, and no-split modes
  are integrated into the analysis endpoint and workspace. Explicit existing
  mode rejects missing split membership; generated mode verifies its
  dataset-owned operation and source/output digests; no-split reports
  split-dependent detectors as skipped. Generated output is separate and
  deterministic. A regression check found that legacy API callers without an
  explicit strategy had lost their previous behavior for sparse split
  columns and incomplete entity/time configuration. The route now preserves
  the legacy HTTP 400 validation messages and permits legacy detectors to
  ignore rows without split membership, while explicit Phase 5 existing mode
  remains strict.
- **Phase 6 — analysis workspace:** the UI displays split strategy and
  selected configuration, uses recommendations as advisory inputs, shows
  actual run status/findings and skipped-check explanations, and links to
  persisted findings/history. Current-run and persisted findings remain
  distinct. Automated tests cover the existing grouped-findings and split
  controls; live browser workflows remain NOT VERIFIED.
- **Phase 7 — combined cleaning:** owner-scoped preview is read-only;
  execution requires explicit confirmation and a still-valid preview token.
  Exact-duplicate findings are the only eligible type. A separate output,
  evidence/operation metadata, stale-preview rejection and idempotent retry
  are covered by automated tests.
- **Phase 8 — repair safeguards:** automatic repair remains deterministic
  exact-duplicate “keep first” only. Current evidence and row positions are
  checked before output creation; output hash, schema, row count and the
  remaining duplicate group are verified and recorded. Unsupported detector
  findings receive no invented automatic repair.

No database schema change, migration, or project-data operation was made.
The final backend regression ran against disposable copy
`C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-B2-final-backend-e674dbdb09014248a693fb3e26ac3a50`:
`rtk proxy python -m pytest tests -q -p no:cacheprovider` — **256 passed,
1 skipped, 0 failed, 202 warnings**. The first full run had 7 failures in
legacy split-route expectations. After the compatibility correction, the
same full suite passed. The frontend suite (`rtk proxy npm test`) reported
**74 passed, 0 failed**; `rtk proxy npm run lint` passed; the production build
completed after an initial sandbox path-access denial. The successful build
transformed 2,277 modules. Existing warnings include Node 20.13.1 being
below the installed Vite requirement (20.19+ or 22.12+), Vite's
`__dirname` config-loader warning, and a large JS chunk advisory.

Browser-based Batch 2 workflows are NOT VERIFIED; automated component/API
tests do not substitute for live browser verification. The staged and
unstaged `backend/test.db` worktree state was present before this continuation
and was not accessed. No storage, backup, migration, Git index, or Git history
was modified.

## Browser-verification maintenance addendum — 2026-11-03

### Operation metadata response contract

Added a backward-compatible response normalizer for repair/quarantine/
combined-cleaning operations and operation history. The repair-history route
includes all operation kinds, while split-generation metadata has a different
shape than combined repair; requiring combined-only fields was the underlying
response-contract mismatch. Every normalized
`operation_metadata` object contains an array-valued `skipped_findings`.
`skipped_findings_recorded` distinguishes a persisted empty list from legacy
missing/null metadata. Populated findings and unrelated existing metadata are
preserved. This is response serialization only: historical JSON is not
rewritten and there is no database migration.

The frontend operation mapper now accepts historical metadata without
combined-cleaning fields and renders unavailable fields as “Not recorded”.
The Repair & Quarantine page no longer fails solely because a historical
operation predates `skipped_findings`.

### Recommendation and preview usability

Target recommendations include explicit readmission outcome terms and
conservative downranking/warnings for copied, derived, proxy, and post-outcome
column names. The service remains deterministic, metadata-based and advisory;
it does not assign a target or change detector behavior. The Analysis page
shows the manually selected target and heuristic feature-name warnings.
Target-leakage findings remain tied to the target column explicitly submitted
by the user and stored in the analysis profile/audit event.

Combined-cleaning preview returns bounded zero-based source row positions,
total affected-position count, truncation state and SHA-256 of the full sorted
position list. The UI displays this actual row-reference preview and allows
cancellation before confirmation. It intentionally does not include raw row
values in the preview, to avoid broad disclosure of potentially sensitive
dataset contents.

### Verification and limitations

Fresh isolated regression on 2026-11-03: backend focused tests **71 passed**;
full backend suite **263 passed, 1 skipped**; frontend suite **78 passed**;
TypeScript/lint passed; Vite production build passed (2,278 modules). Exact
commands, corrected initial test-run issues, and warning details are recorded
in `DataLeakGuard-CV_E2E_TEST_REPORT.md`.

No Split and Existing Split have automated-test coverage, not browser
verification. Combined preview/cancel/confirmation and the full 6,224-row
synthetic dataset workflow remain NOT VERIFIED in a browser: the supplied CSV
was not found at the repository root and no Playwright/Puppeteer package was
installed. No database schema or migration was changed.

## Remediation Center — backend implementation in progress (2026-11-03)

The first backend work unit adds:

- `backend/app/schemas/remediation.py` for bounded, validated remediation
  actions and explicit-confirmation requests.
- `backend/app/services/remediation_service.py` for persisted, source-hash-
  and finding-snapshot-bound preview plans, deterministic transformations,
  separate output generation, post-output verification, cancellation, plan
  history and SHA-256-checked artifacts.
- `backend/app/api/v1/remediation.py`, registered in `main.py`, for
  authenticated owner-scoped preview, execute, cancel, paginated history and
  artifact download routes.
- A compatibility extension to repair operation serialization/downloads for
  the consolidated-remediation operation type.
- `backend/tests/test_remediation_plans.py` for the action/API/provenance
  contract.

The implementation reuses the existing `RepairRecord` JSON metadata and
`AuditEvent`; no schema or migration change is required. The original source
file is only read and SHA-256-checked. Outputs are new files in processed
storage. Evidence schemas are checked against current source rows/ranges
before planning and again before execution. Exact duplicate removal is
keep-first; entity overlap supports seeded group-aware split rebuilding or
quarantine of the selected evidenced entity rows; target leakage supports
confirmed feature exclusion with target retention; temporal leakage supports
an explicit-cutoff chronological split; contamination requires the user to
choose the retained partition or explicitly quarantine all evidenced copies.
No unsupported finding is changed, and review-only findings remain
unresolved.

### Final Remediation Center and Analysis UX implementation — 2026-11-03

The frontend now has:
- `src/pages/RemediationCenterPage.tsx`: five detector groups backed by the
  paginated findings API; current-page and all-open server-side selection;
  detector-specific safe action forms; evidence inspection; server preview,
  cancel, explicit execute confirmation; paginated plan history; audit-event
  summary; and owner-authenticated artifact downloads.
- `src/pages/AnalysisSetupPage.tsx`: separate setup route with compact
  advisory recommendations, searchable manual selectors, split strategy and
  explicit confirmation. Configuration moves to Analysis through
  dataset-keyed session storage only after user confirmation.
- `src/pages/AnalysisPage.tsx`: a concise confirmed configuration summary for
  setup-originated analysis and a separate explicit run action. Direct legacy
  analysis route remains usable.
- `src/App.tsx` and `src/pages/DatasetDetailPage.tsx`: `/analysis-setup/:id`,
  `/remediation/:id`, compatible `/repair/:id`, and workflow navigation,
  including the dataset Audit History tab.
- API contract and view tests are registered in `package.json`.

The remediation API/service, added earlier in this task continuation, reuses
persisted `RepairRecord.operation_metadata` and `AuditEvent`; there is no
schema change or migration. Preview/execution routes are owner-scoped and
revalidate dataset hash plus finding snapshot. Action policies are:
exact duplicate keep-first; entity group-aware split rebuild or evidenced
quarantine; target feature exclusion while preserving target; explicit-cutoff
chronological split rebuild; contamination removal only after an explicit
retained-partition choice or quarantine of evidenced copies; review-only
otherwise. Unknown types are not mapped into supported categories. Source
files remain unchanged. Outputs are separate
`DataLeakGuard_Final_Cleaned_Dataset.csv`,
`DataLeakGuard_Final_Repair_Report.csv`,
`DataLeakGuard_Repair_Manifest.json`, and optional quarantine CSV. Verification
results/status are persisted; unresolved findings are not marked resolved.

Final fresh automated checks: backend **277 passed, 1 skipped, 0 failed**;
frontend **86 passed, 0 failed**; `npm run lint` / TypeScript passed; Python
compilation passed; Vite production build passed (2,281 modules). Exact
commands, warning detail and isolated-copy location are recorded in the E2E
report. Browser E2E is **NOT VERIFIED**; no authenticated live-browser
workflow or supplied synthetic dataset run was performed. The implementation
does not claim production-readiness or large-scale performance.

### Remediation Center and Analysis Setup UI checkpoint — 2026-11-03

The new frontend Remediation Center is routed at `/remediation/:id`; the
existing `/repair/:id` bookmark remains compatible and resolves to the same
center. Detector groups use server-side filtering and page size 10, with
bounded fetching while collapsed. The screen exposes evidence, eligible
action choices, current-page and all-open candidate selection, consolidated
preview, explicit confirmation/cancel, plan history, audit-event summary, and
owner-authenticated artifact downloads. The server remains authoritative for
selection/evidence validation and operation status.

`/analysis-setup/:id` is a separate setup page. It reuses recommendations,
searchable column selection and split strategy components; recommendations
are compact/advisory and are not auto-applied. A user-confirmed setup is held
in session storage only for navigation to Analysis; the analysis run still
requires its own explicit run action. Analysis entered directly by legacy
routes retains the prior configuration form.

Fresh UI verification at this checkpoint: frontend suite **81 passed**;
`npx tsc --noEmit` passed; focused isolated backend remediation suite
**14 passed**. Full backend regression, production build, live browser
interaction and real download verification remain pending and must not be
inferred from these results. No database schema change was made.
