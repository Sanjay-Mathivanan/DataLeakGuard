# DataLeakGuard-CV End-to-End Test Report

**Generated:** 2026-10-29T12:35:00+05:30  
**Browser:** Playwright-backed VS Code browser, Chromium  
**Frontend:** `http://127.0.0.1:3000`  
**Backend:** `http://127.0.0.1:8000`  
**Database:** `backend/test.db` (resolved by starting Uvicorn from `backend/`)

## Codex continuation — current-state handover (2026-10-29)

The browser scenarios and regression counts below are inherited evidence from
the prior Copilot run; they are not fresh Codex verification. The worktree was
already dirty at continuation start, including modified application files,
both project database artifacts, generated Python bytecode, reports, and
untracked workflow modules. `backend/test.db` appeared both staged and
unstaged (`MM`). No Git state was changed by this handover.

Fresh, read-only checks in this continuation:

| Check | Result | Evidence |
|---|---|---|
| Backend health | PASS | `GET http://127.0.0.1:8000/api/v1/health` returned HTTP 200 and the DataLeakGuard-CV project identifier. |
| Frontend route response | PASS | `GET http://127.0.0.1:3000/login` returned HTTP 200. |
| Runtime data paths | PARTIAL | Code defaults to `sqlite:///./test.db`; the previous report resolved it to `backend/test.db` when Uvicorn was started from `backend/`. Storage directories exist at `backend/storage/{original,processed,quarantine}`. This continuation did not independently establish the running process's working directory. |
| Browser automation availability | BLOCKED | No browser automation tool was exposed to this session. The repository has no local Playwright package; `npx --offline --yes playwright --version` failed with `ENOTCACHED`. No browser workflow was run in this continuation. |

No migration, database write, storage operation, or application restart was
performed for these checks. Subsequent API/test verification will be marked
separately from the inherited browser evidence.

## Environment and startup

| Check | Result | Evidence |
|---|---|---|
| Docker | NOT AVAILABLE / not required for this SQLite run | `docker info` was not available |
| Node.js | PASS | `v20.13.1` |
| Playwright | PASS | `npx playwright --version` returned `1.64.1`; browser automation executed |
| Backend startup | PASS | Uvicorn on `127.0.0.1:8000`; `GET /api/v1/health` returned HTTP 200 |
| Frontend startup | PASS | Vite on `0.0.0.0:3000`; `/login` returned HTTP 200 |
| Browser console/network | PARTIAL | Authenticated requests succeeded. Immediate route navigation during Vite HMR reproduced `useAuth must be used within an AuthProvider`; a fresh page/wait restored the authenticated UI. The error was not persistent after the app settled. |

## Supplied dataset inspection

The requested files were found in `C:\Users\sanja\Downloads`:

- `Hospital_Patient_Risk_3000_Synthetic.csv`
- `Hospital_Patient_Risk_Test_Scenarios.csv`

The files were inspected locally before any upload attempt. Patient-level rows
are not reproduced in this report.

| File | Rows | Columns | Missing values | Duplicate rows |
|---|---:|---:|---|---:|
| Hospital_Patient_Risk_3000_Synthetic.csv | 3,030 | 22 | None in inspected columns | 30 |
| Hospital_Patient_Risk_Test_Scenarios.csv | 10 | 5 | None | Not applicable |

Main dataset observations:

- Columns include `record_id`, `patient_id`, `admission_date`,
  `discharge_date`, `readmission_risk_score`, `readmitted_30d`,
  `readmission_target_code`, `post_discharge_review`, `scenario_tag`, and
  `qa_notes`.
- `record_id` has 3,000 unique values; `patient_id` has 2,960 unique values.
- `split` contains `train` (2,130), `test` (450), and `validation` (450).
- The scenario checklist H01 notes “21 columns,” but the actual supplied main
  CSV contains 22 columns. The actual file shape is used as the authoritative
  observation; the checklist discrepancy is not silently corrected.

The supplied main CSV was subsequently uploaded through the real frontend by a
new disposable account. The dataset detail page showed 3,030 rows and 22
feature columns. Feature Profiles showed zero missing values for all displayed
columns, and Distribution & Splits showed train 2,130, test 450, and
validation 450. The five-column scenario checklist was not uploaded as a
detector dataset because it is a test-plan document rather than patient-level
tabular data.

## Test account categories

- **Disposable User B:** registered through the real registration UI during this run. The generated email/password are intentionally not recorded.
- **User A:** owner-supplied credential was not available in this continuation context, so fresh User A browser scenarios are **NOT VERIFIED**. Historical User A evidence remains in the audit report.
- No passwords, session tokens, CSRF values, or secret material are recorded here.

## Browser test matrix

| Feature and scenario | Account | Expected result | Actual result | Status | Reproduction / evidence |
|---|---|---|---|---|---|
| Registration, login/session, dashboard | Disposable User B | Registration creates a session and dashboard loads owned counts | Registration UI redirected to `/dashboard`; dashboard loaded with zero owned datasets; refresh restored the session | PASS | Register via `/register`, reload, observe dashboard and account identity |
| Model artifact upload/persistence | Disposable User B | File and metadata persist | Harmless 36-byte `.onnx` artifact registered; after page navigation it remained listed with name/version/size/SHA-256 | PASS | `/model-integrity` → Upload Model Artifact; SHA-256 recorded as `15fba8...ee06` |
| Model artifact verification | Disposable User B | Original stored bytes verify | Verify action returned success and explicitly stated that no behavioral/inference check was performed | PASS | `/model-integrity` → Verify |
| Model artifact download | Disposable User D | Download returns original bytes and browser captures attachment | Authenticated download request was initiated, but the integrated browser reported `net::ERR_ABORTED` and did not expose a Playwright download object. A browser `fetch` of the same authenticated route returned HTTP 200 and bytes whose SHA-256 matched the registered digest `fb873b...ed07b` | PARTIAL | `/model-integrity` → Download; request event plus byte/hash evidence captured, download-event object unavailable |
| Model artifact tamper detection | Disposable User D | Changed stored bytes fail verification, then disposable bytes are restored | Appended controlled bytes only to the disposable artifact storage file; verify returned `verified:false` with digest `6e6c...607bc`; original 14 bytes were restored and the registered digest was unchanged | PASS | Controlled storage mutation, `/model-artifacts/{id}/verify`, restoration completed |
| Provenance metadata creation/persistence | Disposable User B | Metadata persists with `no_prediction` | Record created from the UI; ledger showed record ID, timestamp, dataset, model metadata, and `No prediction`; refresh persistence was not separately completed | PASS | `/inference-provenance` → Save Provenance Metadata |
| Provenance unsupported capability messaging | Disposable User D | No signature, replay, tampering simulation, or inference execution is presented as implemented | Removed legacy simulator, signature, replay, and cryptographic verification controls; page now presents metadata-only status and explicit limitations | PASS | `/inference-provenance`; no unsupported action remains |
| Distribution dataset selection/comparison | Disposable User B | User selects two owned datasets and backend persists metrics | Two disposable CSVs uploaded; selectors showed both; comparison produced real metrics including numeric PSI, categorical deltas, and missing-value deltas | PASS | `/distribution-shift` → select A/B → Compare datasets; result showed PSI `7.972` and owned dataset IDs |
| Distribution refresh persistence | Disposable User B | Comparison remains after reload | Not separately completed after the comparison result | NOT VERIFIED | Reload `/distribution-shift` and assert the persisted result |
| Impact dataset selection/retrieval | Disposable User B | User selects an owned dataset and sees persisted counts | Selector showed both disposable datasets; Dataset A displayed zero findings, operations, and affected rows | PASS | `/impact-analysis`; select `Browser Dataset A` |
| Reports generation and persistence | Disposable User D | Report is generated from owned persisted dataset records, listed, and survives navigation | Generated report `2ebe5bf7-7371-4267-bfd9-eb88614e17f1`; detail page displayed the persisted dataset and no-model-evaluation status | PASS | `/reports` → Generate New Report; detail page showed `Browser Report Dataset (CSV)` |
| Report JSON download and parsing | Disposable User D | JSON downloads and parses with persisted dataset values | Authenticated browser fetch returned HTTP 200; JSON parsed and contained `Browser Report Dataset` and its persisted SHA-256 | PASS | `/reports/{id}/download?format=json` |
| Report HTML download and content | Disposable User D | HTML downloads and contains expected report content | Authenticated browser fetch returned HTTP 200; HTML length 755 and contained the persisted dataset name and report title. Attachment event was not surfaced by the integrated browser | PARTIAL | `/reports/{id}/download?format=html`; content verified, browser download object unavailable |
| Cross-user isolation | Disposable User D ↔ Disposable User E | Neither account can read or mutate the other’s protected resources | User E was registered through the UI. E received 404 for D’s artifact read/verify/download, impact, dataset/findings/evidence, operation download, and report download; 403 for cross-user provenance/distribution creation and report deletion. E’s list endpoints returned only its own empty scope | PASS | Authenticated browser fetch matrix against D’s disposable IDs |
| Logout and logged-out workflow rejection | Disposable User E | Logout revokes session and protected calls fail | Sign-out navigated to `/login`; subsequent authenticated browser request to `/model-artifacts` returned HTTP 401 | PASS | Sign out, then call protected endpoint |
| Core upload/profile/analyze/evidence/repair/quarantine/history/download journey | Disposable User D | Full journey and five detector categories execute with persisted evidence | Uploaded/profiled six-row dataset; configured all four optional columns; backend returned 6 persisted findings and 5/5 configured detectors completed. Findings/evidence inspected. Exact-duplicate repair completed with one duplicate removed, input/output SHA-256 and operation history persisted. Quarantine was available for the entity-overlap finding but was not executed in this pass; operation download request was initiated but no browser download object was surfaced | PARTIAL | `/datasets` → upload → Run Analysis → persisted findings/evidence → Repair; train/test detector completed with 0 findings as the negative/control result |
| Supplied hospital dataset H01 upload/profile | Disposable User G | Main CSV uploads and profile data persists | Upload succeeded; dataset detail showed 3,030 rows and 22 columns. Feature Profiles showed zero missing values; split counts were train 2,130, test 450, validation 450 | PASS | `/datasets` → upload supplied main CSV → dataset detail → Feature Profiles / Distribution & Splits |
| Supplied hospital dataset H02–H06 configured detector run | Disposable User G | All five configured detectors execute and persisted findings/evidence are available | Backend returned 76 findings and 5/5 completed: exact duplicates 30, entity overlap 40, target leakage 3, temporal leakage 3, train/test contamination 0. Findings page displayed persisted finding IDs, severity, status, timestamps, and evidence text | PASS | Configure target `readmitted_30d`, entity `patient_id`, split `split`, time `admission_date` in `/analysis/{datasetId}`; run; open persisted findings |
| Supplied hospital dataset H08 repair | Disposable User G | Supported duplicate finding produces a persisted cleaned output | Exact-duplicate finding repaired through UI; operation completed, removed one later duplicate row, and persisted input/output SHA-256 values | PASS | `/repair/{datasetId}` → first exact-duplicate finding → Create duplicate-repaired copy |
| Supplied hospital dataset H09 quarantine | Disposable User G | Eligible overlap finding produces a separate quarantine output | Entity-overlap quarantine completed through UI; operation history reported 2 rows written, input/output SHA-256 values, output filename, and completed status | PASS | `/repair/{datasetId}` → eligible entity-overlap finding → Create quarantine output |
| Supplied hospital dataset H10 history/download | Disposable User G | Operations persist and outputs are available for download | Repair and quarantine operations remained listed with hashes and row counts. Authenticated download requests were initiated; integrated browser still did not expose a download object, so direct browser attachment capture remains unverified | PARTIAL | `/repair/{datasetId}` → Operation history → Download output |

## Core detector coverage

The five detector categories were exercised in the browser:

1. Exact duplicates — 30 findings
2. Entity overlap — 40 findings
3. Target leakage — 3 findings
4. Temporal leakage — 3 findings
5. Train/test contamination — 0 findings (negative/control result)

The current backend regression suite covers these areas, and the historical
audit report contains prior API/live evidence, but those sources are not
substituted for the requested fresh browser journey.

## Codex continuation — operation download verification

### Existing repair output: read-only byte-level verification

| Item | Result |
|---|---|
| Operation | Existing completed repair, ID prefix `09ca07dc`; output identified from the read-only operation record. |
| Input | The associated 3,030-row, 22-column synthetic dataset original. No dataset values were printed. |
| Expected | Apply the recorded finding's duplicate row indices using the current individual-repair rule (keep the first indexed row and remove later indexed rows); output should have 3,029 rows and the same ordered columns. |
| Actual | Output exists (786,894 bytes); CSV parsed; output has 3,029 rows and the same 22 ordered columns; parsed output exactly equals the expected transformed input. |
| Integrity/preservation | Output SHA-256 matched the operation record. Original-file SHA-256 matched the dataset record. |
| Status | PARTIAL — stored output bytes and the persisted digest/repair result agree, but this was read-only filesystem/database validation, not an authenticated HTTP download or frontend/browser download event. |

Verification command (read-only SQLite URI, hashes file bytes, and compares
parsed CSV frames without printing row contents):

```powershell
rtk proxy python -c "import sqlite3,json,hashlib,pathlib,pandas as pd; c=sqlite3.connect('file:backend/test.db?mode=ro',uri=True); r=c.execute('SELECT r.id,r.finding_id,r.affected_rows,r.output_filename,r.output_file_sha256,d.storage_filename,d.file_sha256,f.evidence FROM repair_records r JOIN datasets d ON d.id=r.dataset_id JOIN leakage_findings f ON f.id=r.finding_id WHERE d.sample_count=? AND r.operation_type=? AND r.status=? ORDER BY r.created_at LIMIT 1',(3030,'repair','completed')).fetchone(); base=pathlib.Path('backend/storage'); src=base/'original'/r[5]; out_path=base/'processed'/r[3]; original=pd.read_csv(src,dtype=str); actual=pd.read_csv(out_path,dtype=str); evidence=json.loads(r[7]) if isinstance(r[7],str) else r[7]; indices=sorted(int(i) for i in evidence['row_indices']); expected=original.copy(); [expected.drop(index=i,inplace=True) for i in reversed(indices[1:]) if i<len(expected)]; expected=expected.reset_index(drop=True); print({'operation_id_prefix':r[0][:8],'output_bytes':out_path.stat().st_size,'output_hash_matches_record':hashlib.sha256(out_path.read_bytes()).hexdigest()==r[4],'input_hash_matches_record':hashlib.sha256(src.read_bytes()).hexdigest()==r[6],'input_rows':len(original),'affected_rows_recorded':r[2],'actual_output_rows':len(actual),'expected_output_rows':len(expected),'columns_match':list(actual.columns)==list(original.columns),'rows_match_repair_algorithm':actual.equals(expected),'column_names':list(actual.columns)})"
```

The command completed successfully. Pandas emitted its existing optional-PyArrow
future-dependency warning. No database or storage file was modified.

### Existing quarantine outputs: read-only byte-level verification

| Item | Result |
|---|---|
| Operations | Two existing completed quarantine records from the same 3,030-row synthetic dataset; both point to `entity_overlap` findings. Operation ID prefixes: `28fe162b`, `400b9708`. |
| Expected | Each output should contain exactly the source rows selected by its finding's persisted entity-overlap row-index evidence, in source order, with all source columns. |
| Actual | Both output files exist (841 and 848 bytes), parse as CSV, contain 2 rows × 22 columns, and exactly equal the corresponding source-row subsets selected from the original. |
| Integrity/preservation | For both operations, output SHA-256 matched the persisted output digest and source SHA-256 matched the dataset record. |
| Status | PARTIAL — stored output bytes and persisted evidence/digests agree, but no authenticated HTTP response or frontend/browser download event was captured. |

Verification command:

```powershell
rtk proxy python -c "import sqlite3,json,hashlib,pathlib,pandas as pd; c=sqlite3.connect('file:backend/test.db?mode=ro',uri=True); rows=c.execute('SELECT r.id,r.finding_id,r.affected_rows,r.output_filename,r.output_file_sha256,d.storage_filename,d.file_sha256,f.finding_type,f.evidence FROM repair_records r JOIN datasets d ON d.id=r.dataset_id JOIN leakage_findings f ON f.id=r.finding_id WHERE d.sample_count=? AND r.operation_type=? AND r.status=? ORDER BY r.created_at',(3030,'quarantine','completed')).fetchall(); base=pathlib.Path('backend/storage'); flatten=lambda ev: sorted(set(int(i) for i in sum([list(v) if isinstance(v,list) else [v] for v in (ev['row_indices'].values() if isinstance(ev['row_indices'],dict) else [ev['row_indices']])],[]))); check=lambda r: (r[0][:8],r[7],r[3],(src:=base/'original'/r[5]).is_file(),(out:=base/'quarantine'/r[3]).is_file(),out.stat().st_size,hashlib.sha256(out.read_bytes()).hexdigest()==r[4],hashlib.sha256(src.read_bytes()).hexdigest()==r[6],(orig:=pd.read_csv(src,dtype=str)).shape,(actual:=pd.read_csv(out,dtype=str)).shape,r[2],actual.equals(orig.iloc[flatten(json.loads(r[8]) if isinstance(r[8],str) else r[8])].reset_index(drop=True)),list(actual.columns)); print('quarantine_count',len(rows)); [print(check(r)) for r in rows]"
```

The command completed successfully. Pandas emitted its existing optional-PyArrow
future-dependency warning. No database or storage file was modified.

## Regression evidence

| Command | Exit code | Result |
|---|---:|---|
| `npm run lint` | 0 | TypeScript check passed |
| `npm test` | 0 | 48 passed, 0 failed |
| `python -m pytest backend/tests -q` | 0 | 235 passed, 1 skipped |
| `python -m compileall -q backend/app` | 0 | Passed |
| `GET http://127.0.0.1:8000/api/v1/health` | 0 / HTTP 200 | Passed |

The final frontend regression command was run exactly as configured (`npm
test`) after the browser verification updates. An earlier exploratory
invocation incorrectly appended `--runInBand` to this Node test script and
returned exit code 1; it was not the configured test command and was
superseded by the passing run above.

## Remaining blockers and limitations

- User A’s owner-supplied credential was not available in this continuation
  context; no password was requested to be printed or stored.
- Quarantine execution now passed for the supplied dataset and its persisted
  operation reports two quarantined rows plus input/output hashes. Direct
  byte-level validation of that operation download remains unverified because
  the integrated browser does not expose attachment download objects.
- The supplied scenario checklist is documentation, not a detector input; its
  stated 21-column expectation conflicts with the actual 22-column main CSV.
- The integrated browser did not expose a Playwright download object for direct
  attachment requests; authenticated response bytes were independently checked
  for the model artifact and report payload content.
- Existing Vite HMR produced transient React provider errors during hot reload.
  A new page and wait restored the authenticated UI.

## Codex continuation — focused download/repair regression (2026-10-29)

This is fresh automated backend evidence and is separate from the inherited
browser and regression results above. Tests ran from a disposable source copy
at `C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-download-audit-20261029-9d30ea61\backend`.
The copied `tests/conftest.py` routes the SQLAlchemy test session to a
per-test SQLite file under pytest's temporary directory and maps application
storage constants to per-test temporary directories. No project database or
storage directory was copied into or used by this test run.

| Feature and scenario | Method / input | Expected result | Actual result | Status |
|---|---|---|---|---|
| Authenticated operation download endpoint tests | `rtk proxy python -m pytest tests/test_operation_downloads.py tests/test_repair_quarantine_integration.py tests/test_combined_repair.py -q`; synthetic per-test datasets and operations | Download authorization, path/hash validation, repair/quarantine output isolation, and combined-repair behavior pass without writing to project data | Exit code 0; **31 passed, 1 skipped** in 16.06s. Existing deprecation/future warnings included Starlette/httpx, SQLAlchemy declarative base, Pydantic config, and optional PyArrow. | PASS |
| Browser attachment event for these operations | No browser automation tool or standalone Playwright package is available in this environment | Capture the actual browser download object and compare downloaded bytes | Not run; focused API tests do not constitute browser download-event verification. | NOT VERIFIED |

Command was executed with the disposable backend copy as its working directory.
No migration was run, and no application/project database, project storage
artifact, or verified backup was modified.

## Codex continuation — AuthProvider/HMR structure review (2026-10-29)

| Scenario | Method / evidence | Actual result | Status |
|---|---|---|---|
| Provider coverage for registered routes | Read-only inspection of `src/main.tsx`, `src/App.tsx`, and `src/context/AuthContext.tsx` | `main.tsx` renders one `App`; `App` places `AuthProvider` above `ToastProvider`, `BrowserRouter`, and the complete `Routes` tree. Both route guards and all route elements are descendants. No second provider/context import or import/export mismatch was found in this structure. | PASS (structural inspection only) |
| Fresh-load, navigation, protected-route refresh, logout/login, and HMR reproduction | Browser automation tool search plus local package/cache check recorded in the continuation handover; no usable browser driver is available | No new browser session could be run. The prior report's transient HMR error followed by recovery remains historical evidence only; current reproduction and normal-navigation regression are not established. No code change was justified by the structural inspection alone. | NOT VERIFIED |

Inspection command: read-only `rtk proxy python` dump of the listed source files;
route search was attempted but RTK could not resolve the Claude config directory
for that invocation. The source dump itself establishes the provider nesting.
Implementation report unchanged because no runtime behavior was modified.

## Codex continuation — fresh backend regression suite (2026-10-29)

Before running the full suite, inspected the disposable copy's test configuration
and references. Its autouse fixture maps imported original/processed/quarantine
storage constants into a per-test `tmp_path`; its database fixture creates a
fresh per-test SQLite file and replaces the test session factory. The
authentication tests use an in-memory `sqlite://` database. The only test
constructing a bare `TestClient` is the health endpoint test, which makes no
database or storage calls. Read-only SHA-256 comparison confirmed all 73 Python
files under `backend/app`, `backend/tests`, and `backend/migrations` in the copy
exactly match the current checkout.

| Command | Environment | Actual result | Status |
|---|---|---|---|
| `rtk proxy python -m pytest tests -q` | Disposable backend copy at `C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-download-audit-20261029-9d30ea61\backend` | Exit code 0; **235 passed, 1 skipped**, 184 warnings, 88.06s. Warnings include existing Starlette/httpx deprecations, SQLAlchemy declarative-base deprecation, Pydantic config deprecations, optional PyArrow warning, and one pandas date-inference warning in a temporal detector test. | PASS |

No migration was run. Test database and storage paths were temporary; no
project database, project storage artifact, or backup was modified.

### Frontend regression attempt — sandbox limitation

| Command | Actual result | Status / next action |
|---|---|---|
| `rtk proxy npm test` | Node could not `lstat C:\Users\sanja` and each child test exited before loading (`EPERM`). | BLOCKED in the restricted execution context; request approved elevated execution before deciding whether this is a code failure. |
| `rtk proxy npm run lint` | TypeScript process could not `lstat C:\Users\sanja` (`EPERM`) before type checking. | BLOCKED in the restricted execution context; retry with the required filesystem permission. |

These attempts did not produce frontend test or type-check results and are not
counted as application failures.

### Frontend regression, type-check, and production build (fresh, 2026-10-29)

The same configured frontend commands were retried with the filesystem access
required by Node after the restricted invocation failed before startup.

| Command | Actual result | Status |
|---|---|---|
| `rtk proxy npm test` | Exit code 0; **48 passed, 0 failed, 0 skipped**. Includes API mapping/download handling, login/register credentialed request and CSRF behavior, dataset page states, repair/quarantine controls, and evidence rendering tests. | PASS |
| `rtk proxy npm run lint` (`tsc --noEmit`) | Exit code 0; no TypeScript diagnostics. | PASS |
| `rtk proxy npm run build -- --outDir C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-final-e2e-build-20261029-6cc71cbd` | Exit code 0; Vite transformed 2,275 modules and emitted the production bundle outside the repository. The path was confirmed absent before the build. | PASS |

Build warnings/limitations: installed Node is **20.13.1**, below Vite's stated
minimum **20.19+** (the build nevertheless completed); Vite reported the
existing `__dirname`/native config-loader warning; the emitted JavaScript chunk
is about 857 kB and exceeds the 500 kB advisory threshold. No frontend source,
project database, project storage, or backup was modified by these checks.

### Live HTTP route smoke check (2026-10-29; not browser-render verification)

Read-only requests to the already-running local services returned HTTP 200 for
backend `GET /api/v1/health` and frontend SPA document requests for `/login`,
`/register`, `/dashboard`, `/datasets`, `/datasets/e2e-smoke`,
`/analysis/e2e-smoke`, `/leakage-analysis/e2e-smoke`, `/repair/e2e-smoke`,
`/impact-analysis`, `/model-integrity`, `/inference-provenance`,
`/distribution-shift`, `/reports`, `/reports/e2e-smoke`, and `/account`.
Command: `rtk proxy python -X utf8 -c "<urllib GET smoke-check>"`. These
responses establish that the services answered and the SPA fallback returned
HTTP 200; they do **not** establish that React rendered each page, that data
requests succeeded, or that controls/interactions work. Browser page audit
remains NOT VERIFIED.

The download implementation was also re-inspected: RepairPage fetches the
credentialed operation endpoint as a Blob and invokes a hidden-anchor save;
the backend endpoint scopes the operation to the authenticated owner, checks
completed status and storage containment, verifies the recorded SHA-256 when
present, and returns an attachment. Focused `test_operation_downloads.py`
asserts HTTP 200, exact response body bytes, content type, attachment header,
missing/unknown operation behavior, rejected traversal/symlink paths, digest
mismatch rejection, and incomplete-operation rejection. Combined-repair tests
also assert downloaded CSV content and disposition. This supports API-level
download behavior but is not capture of the pre-existing hospital operations'
authenticated download response. Browser download event remains NOT VERIFIED;
the prior `net::ERR_ABORTED` is not sufficient evidence of server failure.

### Confirmed report-detail placeholder defect (2026-10-29)

Read-only inspection of the current report path found that the backend persists
only dataset identifiers/names/formats/SHA-256 values and persisted impact
counts, while `getReports()` fills in unpersisted severity counts as zero,
confidence as `0%`, risk as `MODERATE`, and a review disposition. The detail
page then labels these as an assurance report and displays the unsupported
values. This is a confirmed mismatch between persisted report content and
frontend claims; the earlier browser report only verified that the report
payload contained dataset data, not that those additional UI fields were
evidence-backed.

| Scenario | Expected | Actual from current code inspection | Status / next action |
|---|---|---|---|
| Report list/detail must not invent evaluation, confidence, severity, or risk metrics | Display persisted dataset/impact records and label unsupported assessments unavailable | Frontend synthesizes zero severity values, 0% confidence, moderate risk, and a disposition absent from the backend payload | FAIL — implement an honest persisted-report view and add focused mapping/UI tests, then rerun frontend tests, type check, and build. |

### Report placeholder fix — focused verification (2026-10-29)

The report API mapper and pages were changed to show only persisted dataset
manifest and impact-count fields; unsupported severity counts, confidence,
risk, and disposition now read as unavailable/not assessed. Report list/detail
also distinguish API errors from empty/no-match states. The E2E source-inspection
failure above is retained as historical evidence; the data-mapping fix is
verified by focused frontend API tests, while browser rendering remains
unverified.

| Command / scenario | Actual result | Status |
|---|---|---|
| `rtk proxy node --import tsx --test src/services/api.test.ts` | Exit code 0; **25 passed, 0 failed**. New tests assert persisted report content/impact values are preserved, unsupported assessments remain null/not assessed, and create-response mapping does not fabricate a fallback report. | PASS |
| Render report list/detail in browser and exercise persisted/empty/error states | No browser driver available; no UI session run. | NOT VERIFIED |

### Post-fix frontend regression (2026-10-29)

| Command | Actual result | Status |
|---|---|---|
| `rtk proxy npm test` | Exit code 0; **50 passed, 0 failed, 0 skipped**. Includes the two new persisted-report mapping/creation tests. | PASS |
| `rtk proxy npm run lint` (`tsc --noEmit`) | Exit code 0; no TypeScript diagnostics after report type/page changes. | PASS |
| Production build after report fix | Not yet rerun at this point. | NOT VERIFIED |

### Codex continuation — distribution and provenance placeholder correction (2026-10-29)

Source review found unsupported presentation in the distribution and
provenance screens: the distribution mapper supplied zero for unimplemented
Wasserstein/OOD values, mixed numeric PSI with categorical deltas in one
aggregate, and the page claimed moderate drift and showed illustrative class
balance. Provenance records were mapped to a zero confidence score, and the
metadata form began prefilled with fictional asset/model/preprocessing examples.

The mapper now averages only persisted numeric PSI values, identifies each
persisted column score by method, leaves unavailable Wasserstein/OOD values
null, and does not infer overall status from a mixed-score average. The
distribution UI labels target prevalence, Wasserstein, and OOD as unavailable
where no stored metric exists. The provenance UI no longer supplies fictional
defaults and labels confidence unavailable for metadata-only records. The
inactive mock fixture was updated only for the shared TypeScript shape; it is
not used as production API data.

| Verification | Actual result | Status |
|---|---|---|
| Source inspection of distribution mapper/page, workflow persistence, and provenance page | Confirmed the unsupported zeroes, mixed metric aggregation, unsupported class-balance claim, and demo defaults described above | PASS (defect confirmed) |
| Initial `rtk proxy npm test` after changes | Tests themselves reported **51 passed, 0 failed, 0 skipped**, but a wrapper expression emitted a PowerShell parse error afterward; superseded by the clean rerun below | PARTIAL |
| Initial `rtk proxy npm run lint` | TypeScript found 7 errors from the nullable/new metric types (5 mock-fixture fields and 2 confidence dereferences); all were corrected | FAIL (compile defect found and fixed) |
| `rtk proxy npm test` after follow-up fixes | Exit code 0; **51 passed, 0 failed, 0 skipped** | PASS |
| `rtk proxy npm run lint` after follow-up fixes | Exit code 0; `tsc --noEmit` emitted no diagnostics | PASS |
| `rtk proxy npm run build -- --outDir C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-final-continuation-build-20261029-4c75e2a1` | Exit code 0; 2,270 modules transformed; output outside repository | PASS |
| Browser interaction/rendering of changed distribution/provenance pages | Browser automation unavailable; no interactive page verification performed | NOT VERIFIED |

Build warnings remain: Node 20.13.1 is below Vite's required 20.19+/22.12+;
Vite emitted its native config-loader/`__dirname` warning; the JS bundle is
841.67 kB and exceeds the advisory 500 kB threshold. The earlier
`git diff --check` reported trailing whitespace in the pre-existing
`DataLeakGuard-CV_PROJECT_MASTER_CONTEXT.md`; that unrelated file was not
edited. No migration was run and no project database, storage file, or backup
was modified.

Final frontend rerun after the final chart/provenance display edits:

| Command | Actual result | Status |
|---|---|---|
| `rtk proxy npm test` | Exit code 0; **51 passed, 0 failed, 0 skipped** | PASS |
| `rtk proxy npm run lint` (`tsc --noEmit`) | Exit code 0; no diagnostics | PASS |
| `rtk proxy npm run build -- --outDir C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-final-continuation-build-20261029-8a3914bc` | Exit code 0; 2,270 modules transformed; generated output only in the new temporary directory | PASS |
| `git diff --check` for the changed distribution, provenance, mapper, type, and mock-fixture source paths | No whitespace errors reported for those selected tracked source paths; Git emitted line-ending notices. An earlier whole-worktree check still reports pre-existing trailing whitespace in `DataLeakGuard-CV_PROJECT_MASTER_CONTEXT.md`. | PASS (selected source paths) |

The worktree remains dirty with unrelated earlier modifications, including
`backend/test.db`, tracked Python bytecode, backend source, and untracked
workflow/report files. These were preserved; no stage/commit/reset/cleanup was
performed. Git also warned that its user-level ignore file could not be read
(`C:\Users\sanja\.config\git\ignore` access denied). No backend, migration,
database, storage, or backup action was performed during this continuation.

## Batch 1 baseline — 2026-11-02 (before Batch 1 source edits)

The baseline is fresh for this checkout and distinct from the October 29
historical results above.

| Command | Environment | Result | Status |
|---|---|---|---|
| `rtk proxy python -m pytest tests -q` | Disposable backend copy `C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-B1-baseline-20261102-7f3d1b\backend`; app/tests/migrations/requirements copied without project DB or storage | Exit 0; **235 passed, 1 skipped, 184 warnings**, 59.32s. Existing Starlette/httpx, SQLAlchemy, Pydantic, optional PyArrow, and pandas date parsing warnings. | PASS |
| `rtk proxy npm test` | Frontend working tree; tests use mocked/local test data | Exit 0; **51 passed, 0 failed, 0 skipped**. | PASS |
| `rtk proxy npm run lint` (`tsc --noEmit`) | Frontend working tree | Exit 0; passed with no TypeScript diagnostics. | PASS |
| `rtk proxy npm run build -- --outDir C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-B1-baseline-build-20261102-42de7d` | Frontend working tree; output outside repository | First sandbox invocation was blocked by Node `EPERM` resolving `C:\Users\sanja`; approved retry exited 0, transformed 2,270 modules, emitted the build outside the repository. | PASS |

Build warnings: Node 20.13.1 is below Vite's 20.19+/22.12+ requirement;
Vite's existing native config-loader/`__dirname` warning; output chunk about
841.89 kB (advisory 500 kB limit).

Source audit for this batch found:
- Persisted findings API/UI currently returns and loads every finding, with
  client-only search/type/severity filters and no status filter/pagination.
- Dataset Audit History currently loads a capped response but the backend
  materializes all matching repair operations before truncation; the tab shows
  only event type/outcome/time.
- Feature Profiles renders every stored column row and top categorical values
  without search/filter/sorting/summary.
- Analysis configuration uses four unsearchable native selects; no automatic
  recommendation endpoint exists.

These are the implementation baselines, not browser-render results. No browser
automation was available for this session. The baseline tests did not modify
the configured project DB or repository storage; the backend suite ran from a
disposable copy with isolated fixture DB/storage.

## Batch 1 Phase 1 — Findings UI and pagination (2026-11-02)

Fresh implementation verification; this section does not replace the baseline
or historical reports above.

| Test / input | Expected result | Actual result / evidence | Status |
|---|---|---|---|
| `rtk proxy python -m pytest tests/test_findings_pagination.py -q -p no:cacheprovider` in disposable backend copy `C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-B1-phase1-4057a951635b4c658667821b68367f07` | Page bounds/order, global vs filtered totals, search by ID/type/description/evidence, filters, unknown categories, and denial for other-owned/null-owner datasets | **4 passed, 0 failed**. Test data was synthetic and written only to per-test `tmp_path` SQLite/storage. One intermediate run exposed test code holding a stale pre-fixture session factory; corrected to resolve the monkeypatched factory dynamically. | PASS |
| Focused UI/API tests: `rtk proxy node --import tsx --test src/services/api.test.ts src/components/leakage/GroupedFindings.test.tsx src/pages/DatasetDetailPage.test.ts` | Request filter mapping, snake/camel summary mapping, grouped detector/severity output, evidence and unknown detector display | Final run: **29 passed, 0 failed**. Initial run found dictionary key camel-casing changed detector IDs (`entity_overlap`); mapper now preserves dictionary keys and the final test passes. | PASS |
| `rtk proxy npx tsc --noEmit` | Frontend type-check | Exit 0; no diagnostics. | PASS |
| Browser interaction of Findings / Analysis pages | Confirm real rendered filters, pagination and accessible expand/collapse | No browser automation was established or run for this phase. Static-render/UI unit tests and API tests are not browser E2E evidence. | NOT VERIFIED |

Phase 1 implementation: added owner-scoped `GET
/api/v1/datasets/{dataset_id}/findings/page` with bounded server pagination,
search over finding ID/type/description/evidence, detector/severity/status
filters, and both dataset-wide and matching summaries. Kept the existing
unpaginated array endpoint for compatibility. Persisted Findings and the
dataset detail tab now use the paginated browser; current analysis response
findings use the reusable detector/severity grouping but remain explicitly
separate from the full persisted query.

No schema migration, configured project database, project storage, or backup
was accessed or modified. Focused backend verification ran from the disposable
copy named above.

## Batch 1 Phase 2 — Dataset audit-history timeline (2026-11-02)

| Test / input | Expected result | Actual result / evidence | Status |
|---|---|---|---|
| `rtk proxy python -m pytest tests/test_findings_pagination.py tests/test_dataset_history_page.py -q -p no:cacheprovider` in `C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-B1-phase1-4057a951635b4c658667821b68367f07` | Merge persisted audit events and operation records, de-duplicate linked operation events, paginate, filter by type/status/date, search operation identifiers, expose failure detail, and deny other/null-owner datasets | Exit 0; **6 passed, 0 failed, 13 warnings**. Synthetic operations/events only in per-test SQLite. | PASS |
| `rtk proxy npm test` | Frontend service and component regression tests | Exit 0; **56 passed, 0 failed, 0 skipped**. Includes history query mapping and timeline filter/status rendering tests. | PASS |
| `rtk proxy npx tsc --noEmit` | Frontend type-check | Exit 0; no diagnostics. | PASS |
| Browser activity timeline interaction | Verify actual live event rows, filter results and detail expansion in browser | Browser automation not run; component/API tests do not establish live browser behavior. | NOT VERIFIED |

Added `GET /api/v1/datasets/{dataset_id}/history/page`, retaining the existing
array endpoint. The new endpoint applies owner checks, bounded pagination,
event/status/date/search filters, and limits database retrieval to the
requested window plus offset. It merges audit events with repair/quarantine
records, de-duplicates operations already represented by audit events, and
returns dataset/operation/finding/actor identifiers, created/completed times,
available operation metadata, and persisted failure reason when present.
Dataset upload/last-analysis fallback entries are explicitly derived from
persisted dataset timestamps and marked as such.

No schema migration or project database/storage/backup access occurred. Full
backend and frontend regression after Batch 1 is still pending.

## Batch 1 Phase 3 — Feature Profiles (2026-11-02)

| Test / input | Expected result | Actual result / evidence | Status |
|---|---|---|---|
| `rtk proxy npm test` | Search/type/missing/cardinality filtering, numeric sorting, profile summaries and regression coverage | Exit 0; **58 passed, 0 failed, 0 skipped**. New utility tests use synthetic stored-profile metadata for numeric, categorical, datetime, missing-value, cardinality, sorting and summary cases. | PASS |
| `rtk proxy npx tsc --noEmit` | Type-check the profile component and existing frontend | Final exit 0; no diagnostics. An initial check found a case-only module filename collision on Windows and a type-index error; helper file was renamed to `featureProfileUtils.ts`, import type corrected, then check passed. | PASS |
| Feature Profiles browser interaction | Verify actual profile rendering, table sorting, filters, categorical expansion and pagination in browser | No browser automation was run; unit tests validate filtering/sorting utilities but not interactive event behavior. | NOT VERIFIED |

Phase 3 uses stored `dataset.columns` metadata only (dtype, missing count,
unique count, numeric statistics, and up to ten categorical top values). It
adds client-side search/filter/sorting, a 50-column page size, metadata-derived
summaries, and collapsed categorical-value expansion. Date/time classification
uses stored dtype markers; no repeated file scan or date parsing was added.
High cardinality is a deterministic UI heuristic: unique count greater than
20 and unique/sample ratio at least 0.5. No backend or database change.

## Batch 1 Phase 4 — Intelligent detector-column configuration (2026-11-02)

| Test / input | Expected result | Actual result / evidence | Status |
|---|---|---|---|
| `rtk proxy python -m pytest tests/test_findings_pagination.py tests/test_dataset_history_page.py tests/test_column_recommendations.py -q -p no:cacheprovider` in disposable backend copy `C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-B1-phase1-4057a951635b4c658667821b68367f07` | Role recommendations, deterministic points/confidence, ambiguity, missing values, split labels, repeated entities, ISO dates, 252-column schema, no-profile response, ownership and unsupported formats | Final exit 0; **10 passed, 0 failed, 14 warnings**. The first run had 8 passed/2 failed due test assertions assuming a different tie order and missing-count warning; assertions were corrected to test deterministic tie behavior and actual threshold. No service defect was indicated by those assertions. All synthetic DB/storage writes stayed in per-test temporary paths. | PASS |
| `rtk proxy npm test` | Recommendation request mapping, advisory/no-auto-selection display, searchable selector large-schema search/type filtering, and previous phase regressions | Exit 0; **61 passed, 0 failed, 0 skipped**. A synthetic 1,201-column selector dataset was used by helper tests. | PASS |
| `rtk proxy npx tsc --noEmit` | Type-check recommendation UI/API and application | Exit 0; no diagnostics. | PASS |
| Browser interaction of recommendation acceptance, manual override, confirmation checkbox and analysis submission | Verify full interactive flow in browser | No browser automation tool is available in this environment (`tool_search` found no browser automation tools); no backend/frontend service was started. UI interaction and actual analysis submission from the new controls remain unverified. | NOT VERIFIED |

Added authenticated owner-scoped
`GET /api/v1/datasets/{dataset_id}/column-recommendations` for tabular
CSV/XLSX datasets. It consumes stored column profile metadata and at most six
stored preview rows; arbitrary sample values are not returned. It returns
target/entity/split/timestamp candidates, candidate metadata, deterministic
supporting signals, warnings and bounded alternatives. Recommendation fields
are advisory and never alter selection; the analysis page now requires an
explicit user confirmation before submitting any detector configuration.
Searchable column selection filters by name/type and displays at most 50
options at once, with an explicit “show next 50” action.

Scoring weights are heuristic points (not probabilities): target name hints
target +60, label/outcome +55, diagnosis/risk_category +50, class +40;
categorical type +10/numeric +4; cardinality 2–20 +20, 21–50 +8, singleton
−25, >50 −15. Entity identifier+entity-name +55, identifier/key +45, exact
`id` token +32; supported type +5; unique ratio ≥0.8 +15, ≥0.2 +10, otherwise
+5 (repetition is retained). Split-name hint +55; at least two recognized
partition labels +35, one +15; categorical +5; 2–10 unique values +8.
Timestamp name hint +45; stored datetime dtype +35 or at least two of up to
six preview values parseable +20; at least two unique values +5. Missing ratio
>0.5 subtracts 10 and >0.2 subtracts 5. Scores clamp to 0–100; recommendation
requires ≥50; confidence categories are high ≥75, medium ≥55, low ≥35, else
not recommended. The tests assert representative scores and ambiguous/no
recommendation cases. No schema change or migration.

## Batch 1 final regression (2026-11-02)

| Command | Environment / expected safety | Actual result | Status |
|---|---|---|---|
| `rtk proxy python -m pytest tests -q -p no:cacheprovider` | Disposable backend copy `C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-B1-phase1-4057a951635b4c658667821b68367f07`; app/tests/migrations only, no project DB/storage; conftest uses per-test temp DB/storage | **245 passed, 1 skipped, 191 warnings** in 60.79s. | PASS |
| `rtk proxy npm test` | Frontend suite with mocked/local test inputs | **61 passed, 0 failed, 0 skipped**. | PASS |
| `rtk proxy npm run lint` (`tsc --noEmit`) | Frontend type-check | Exit 0; no diagnostics. | PASS |
| `rtk proxy npm run build -- --outDir C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-B1-final-build-20261102-9f64c01c` | Production build, output outside repository | Exit 0; 2,276 modules transformed; output placed in new temporary directory. | PASS |
| `rtk git diff --check` | Read-only whitespace validation | No whitespace diagnostics in new/changed implementation additions, but command exits 1 because the pre-existing modified `DataLeakGuard-CV_PROJECT_MASTER_CONTEXT.md` has trailing spaces on lines 3–4. Git also emitted LF→CRLF notices for modified files; prior lines were preserved. | PARTIAL |
| Browser E2E | Verify interactive controls/routes end-to-end | No browser automation tool was available; no live service/browser workflow was run. | NOT VERIFIED |

Build warnings: installed Node.js 20.13.1 is below Vite's 20.19+/22.12+
minimum; Vite emitted its existing native config-loader `__dirname` warning;
the production JS chunk is 868.91 kB and exceeds the 500 kB advisory. Backend
warnings include SQLAlchemy/Pydantic/httpx deprecations, optional PyArrow, one
pandas datetime-inference warning, and test-client warnings.

No migration or database schema change was made. Backend tests ran only in
the disposable copy; frontend tests used mocked/local test data. Project
databases, storage, and backups were not accessed by this Batch 1 verification.

## Batch 2 Phase 5 — Dataset split strategy (2026-11-02)

| Test / input | Expected result | Actual result / evidence | Status |
|---|---|---|---|
| `rtk proxy python -m pytest tests/test_split_strategy.py tests/test_leakage_api.py -q -p no:cacheprovider` in disposable backend copy `C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-B2-phase5-20261102-splits` | Validate existing split, generated split, no-split behavior, reproducibility, audit/profile persistence, input preservation, parameter bounds, ownership and legacy API behavior | Exit 0; **14 passed, 0 failed, 21 warnings**. Synthetic test uploads are isolated by `conftest.py` to each test's SQLite DB and temporary storage. The generated endpoint returned the same completed operation and verified output digest for the repeated ratio/seed request; source bytes remained unchanged. Existing-split analysis returned train/test contamination for the synthetic cross-partition match. No-split explicitly returned entity-overlap, temporal-leakage and train/test-contamination as skipped. | PASS |
| Initial focused test attempt | Establish phase test correctness | Initial run: 3 failed, 11 passed because new tests retained an import-time `TestingSessionLocal` reference and bypassed the fixture's per-test database monkeypatch. The test import was corrected; this was a test-harness defect, not a product-code failure. | PARTIAL |
| Browser split mode, generation confirmation and analysis workflow | Verify user interaction, warnings and results through the running frontend | Frontend mode controls are not yet implemented; no browser run was performed. | NOT VERIFIED |

Implementation evidence: added authenticated owner-scoped
`POST /api/v1/datasets/{dataset_id}/split-strategies/generate`. The request
accepts `test_ratio` in `[0.05, 0.95]` and a signed 32-bit `random_seed`.
Generation adds `__dataleakguard_split__` to a separately written CSV/XLSX
copy; algorithm `sha256_seeded_row_order_v1` deterministically assigns rows
without stratification or group-awareness. The original remains unchanged.
The persisted split-generation operation includes input/output SHA-256,
configuration, row counts and algorithm. An audit event records the same
configuration and digest references.

`POST /api/v1/datasets/{dataset_id}/analyze/leakage` accepts
`split_strategy=existing|generated|none`. Existing mode validates a
user-selected column and membership; generated mode requires an operation ID
owned by that dataset and verifies the current source hash and generated
output hash; no-split mode explicitly omits split-dependent detectors and
returns them in `skipped_detectors`, never as negative findings. Legacy callers
remain compatible. Strategy data is persisted in the dataset profile and
analysis audit event. No DB schema migration was introduced. Frontend
configuration, confirmation UI and browser behavior are not yet verified.

## Batch 2 Phase 7 — Combined cleaning preview and confirmation (2026-11-02)

| Test / input | Expected result | Actual result / evidence | Status |
|---|---|---|---|
| `rtk proxy python -m pytest tests/test_combined_repair.py tests/test_authentication.py -q -p no:cacheprovider` in disposable copy `C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-B2-phase7-72965e22fda74cd795e9c285079fba4a` | Preview without writing; explicit confirmation and fresh token for execution; deterministic row counts; mixed eligible/ineligible findings; duplicate selections; stale-preview rejection; output/download SHA-256; original preservation; idempotent retry; owner isolation | Final exit 0: **31 passed, 0 failed, 39 warnings**. Fixtures used per-test SQLite and temporary storage. An intermediate run had one assertion failure because the persisted operation now correctly includes `preview_token` and `evidence_reference_finding_ids`; the assertion was updated to validate those fields, and the final run passed. | PASS |
| `rtk proxy node --import tsx --test src/services/api.test.ts src/pages/RepairPage.test.tsx` | Validate preview request/response mapping, confirmation payload, UI confirmation, no-eligible state, history and download regressions | **49 passed, 0 failed**. Initial sandbox run hit Node `EPERM` resolving `C:\Users\sanja`; approved outside-sandbox retry passed. | PASS |
| `rtk proxy npx tsc --noEmit` (chained after focused frontend tests) | Type-check the combined-cleaning UI and API | Command chain exited 0; no TypeScript diagnostics were emitted. | PASS |
| Browser combined-cleaning interaction | Select findings, inspect preview, confirm, verify generated output in a browser | No browser automation was available or run. Static UI and API tests do not establish browser interaction. | NOT VERIFIED |

The flow uses
`POST /api/v1/datasets/{dataset_id}/repairs/combined/preview` followed by
`POST /api/v1/datasets/{dataset_id}/repairs/combined` with `confirmed: true`
and the preview token. Preview reports original/final row counts, rows to
remove, eligible IDs, and excluded findings/reasons without writing a file or
operation record. Execution recomputes current inputs, rejects stale tokens,
writes one separate output, and persists selected/applied IDs, exclusions,
evidence references, and preview token. Replaying the same confirmed request
is idempotent and returns the existing operation. Mixed same-dataset requests
exclude unsupported or stale findings; cross-dataset selection is rejected.
Exact duplicates remain the only combined-cleaning strategy. No schema
change, migration, project database/storage access, or Git-index operation
occurred.

## Batch 2 Phase 8 — Individual exact-duplicate repair safeguards (2026-11-03)

| Test / input | Expected result | Actual result / evidence | Status |
|---|---|---|---|
| `rtk proxy python -m pytest tests/test_repair_service.py tests/test_repairs_api.py tests/test_combined_repair.py tests/test_authentication.py -q -p no:cacheprovider` in disposable backend copy `C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-B2-phase8-ee133faa865f453e8d84c008fd63d6c1` | Preserve exact-duplicate repair behavior; reject malformed/stale row evidence before output; verify generated schema/row count/hash and duplicate condition; persist verification; retain ownership, idempotency, combined cleaning, downloads and cross-user restrictions | Final exit 0: **60 passed, 0 failed, 68 warnings**. Successful repair test verifies source bytes remain intact, output SHA-256 and row results; the added stale-evidence test changes isolated evidence to point at a nonduplicate row group and confirms HTTP 409 with no output file and unchanged source. Original run of that added test returned 422 because its synthetic upload omitted the required description; the fixture was corrected and the rerun passed. | PASS |
| `rtk proxy node --import tsx --test src/services/api.test.ts src/pages/RepairPage.test.tsx` | Test repair eligibility messaging, confirmation text, persisted verification status, metadata mapping, and previous workflow regression | **52 tests passed, 0 failed** (after Phase 8 changes). | PASS |
| `rtk proxy npx tsc --noEmit` | Type-check updated repair history/UI metadata | Passed, no diagnostics (rerun with frontend tests). | PASS |
| Browser individual-repair confirmation and history view | Verify confirmation dialog, operation, and verification summary in a live browser | No browser automation available/run. | NOT VERIFIED |

The individual repair path remains limited to deterministic
`exact_duplicate` “keep first” behavior. The service now validates integer,
unique, in-range row indices and the duplicate count; recomputes the current
duplicate group using the finding’s recorded hash exclusions; rejects stale
evidence before output creation; then checks output readability, SHA-256,
column schema, expected row count, and that exactly one row remains from the
evidenced duplicate group. Verification status/details and evidence references
are persisted in the existing operation metadata. The UI explains eligibility
and requires explicit confirmation before execution; legacy operation records
without verification metadata are labelled unavailable. Target leakage,
temporal leakage, entity overlap, and contamination do not gain automatic
repair strategies. No schema or migration change.

## Batch 2 regression and release status — historical note

The initial pending status below was accurate when written, but is superseded
by the final verification addendum at the end of this report. Browser E2E
remains NOT VERIFIED.

Fresh full backend regression, frontend suite, lint/type check, and production
build had not yet been run at the time this note was added. The prior Batch 1
baseline numbers are historical and must not be treated as Batch 2 results.
No project database, storage, backup, migration, or Git index was accessed or
changed by those earlier checks.

## Batch 2 final regression and compatibility correction — 2026-11-03

### Phase status matrix

| Phase | Automated verification | Status | Remaining limitation |
|---|---|---|---|
| 5 — Dataset split strategy | Existing/generated/no-split API tests, validation, deterministic output/reuse, digest checks, source preservation, audit/profile persistence, owner restriction, plus full backend regression | PASS | Browser workflow NOT VERIFIED. Explicit existing mode is strict; legacy requests retain sparse-membership compatibility. |
| 6 — Analysis/workspace | Grouped-findings, split-panel and API tests; complete frontend suite, lint/type-check and build | PARTIAL | No live browser verification of the complete analysis/configuration/evidence/history journey. |
| 7 — Combined cleaning | Preview/confirmation, current preview token, mixed eligible/ineligible IDs, stale-preview rejection, idempotency, output/evidence metadata, authorization; frontend API and RepairPage tests | PASS | Browser interaction NOT VERIFIED. Exact duplicates remain the only eligible combined-cleaning type. |
| 8 — Expanded repair | Exact-duplicate repair evidence validation, separate output, hash/schema/row-count and post-repair duplicate verification, idempotency/history and authorization tests | PASS | Browser confirmation/history interaction NOT VERIFIED. Other detector categories are intentionally unsupported for automatic repair. |

### Fresh regression commands and results

| Command and isolated environment | Expected | Actual evidence | Status |
|---|---|---|---|
| `rtk proxy python -m pytest tests -q -p no:cacheprovider` from disposable backend copy `C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-B2-final-backend-e674dbdb09014248a693fb3e26ac3a50` | Full backend suite; every test uses disposable SQLite and per-test temporary storage | **256 passed, 1 skipped, 0 failed, 202 warnings**, exit 0, 65.29s. No project DB or project storage was used. | PASS |
| `rtk proxy npm test` from the project frontend | Full configured frontend component/API test suite | **74 passed, 0 failed**. The configured suite includes API, RepairPage, grouped-findings, dataset-history, feature-profile, column-recommendation and split-panel tests. | PASS |
| `rtk proxy npm run lint` | TypeScript check (`tsc --noEmit`) | Exit 0; no diagnostics. | PASS |
| `rtk proxy npm run build -- --outDir C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-B2-final-build-20261103-56a331` | Production Vite build without writing `dist/` in the repository | Exit 0; 2,277 modules transformed. Warnings: runtime Node v20.13.1 is below Vite's stated v20.19+/22.12+ requirement, `__dirname` config-loader compatibility, and a >500 kB JS chunk. An initial sandbox `EPERM` was resolved by approved outside-sandbox execution. | PASS |

### Backend compatibility failure and fix evidence

The first full run in the disposable copy produced **249 passed, 1 skipped,
7 failed**. The affected legacy API tests covered entity/time requests without
a split, missing split-column status, and null/blank membership rows. The
failure was caused by applying Phase 5's stricter explicit-existing-split
validation to legacy requests. The smallest correction now distinguishes an
explicit `split_strategy=existing` request from a legacy request: explicit
mode still rejects incomplete membership; legacy mode retains HTTP 400
validation for incomplete entity/time pairs and missing columns, and permits
the existing detectors to ignore rows with absent membership. The existing
focused run after the behavior change had **41 passed, 2 failed** because
those two assertions expected the legacy error-message text. The messages
were aligned with the established API contract; the subsequent full
post-fix regression passed **256 passed, 1 skipped**.

### Browser and preservation record

No browser automation was run for this Batch 2 continuation. Phase 6
end-to-end navigation, Phase 7/8 confirmation dialogs, and visible
operation-history rendering remain NOT VERIFIED; passing unit/API tests do
not establish browser behavior.

All test writes were confined to the disposable backend copy's per-test
SQLite files and temporary storage. Frontend build output was directed to the
unique temporary directory above. No migration was run; no project database,
storage, or backup was accessed or modified. No Git staging, commit, reset,
clean, or history operation was performed.

Read-only final Git inspection showed the inherited dirty worktree and
`backend/test.db` in `MM` state (staged and unstaged modifications already
present); no deleted paths were listed. `git diff --check` reported only the
previously documented trailing whitespace on
`DataLeakGuard-CV_PROJECT_MASTER_CONTEXT.md` lines 3–4. Those lines were not
changed to avoid altering unrelated project context. No index action was
performed.

## Browser-verification maintenance — 2026-11-03

This is fresh evidence for the Repair & Quarantine response issue, target
selection, split-mode regressions, and combined-cleaning preview. It does not
replace the earlier Batch 2 results above.

### Investigation and corrections

- **Repair & Quarantine response mismatch:** `GET /datasets/{id}/repairs`
  returns all `RepairRecord` operation types, including split-generation
  records whose metadata shape does not contain combined-cleaning fields. The
  generic frontend mapper treated every metadata object as combined repair
  metadata and required `skipped_findings` to be an array. This is a
  reproducible contract mismatch in current code; the exact historical row
  that produced the reported browser message was not read from the protected
  project database. Older repair/quarantine and failed/partial records can
  also have missing/null metadata. A response-only
  serializer now supplies an empty array and
  `skipped_findings_recorded: false` for absent/null/malformed legacy values,
  preserves populated arrays, and marks a real empty array as recorded. It
  does not update persisted historical records. Repair, quarantine,
  combined-cleaning and history responses use the normalized contract.
- **Combined-cleaning preview:** server preview now exposes the actual
  zero-based source row positions selected for omission, bounded to 200
  positions, plus total count, truncation flag, and a SHA-256 digest of the
  complete sorted position list. This identifies actual records without
  returning potentially sensitive row contents. The UI offers Cancel Preview
  and retains explicit confirmation and stale-token validation. It does not
  expose raw patient values; users needing record-value review must inspect
  the source dataset/evidence separately.
- **Target recommendation:** deterministic name-token heuristics now rank
  readmission outcome columns above `diagnosis` for the matching synthetic
  profile and reduce/warn on copied, derived, proxy, and post-outcome names.
  Recommendations remain advisory and dataset-specific; no target is
  hardcoded or silently selected. Manual target parameters are passed to
  analysis and persisted in dataset profile/audit context. The frontend
  explicitly labels the selected target and warns about possible derived
  feature names without asserting confirmed leakage.
- **Split modes:** existing backend tests exercise no-split, generated split,
  and explicitly confirmed/validated existing split. This maintenance added
  assertions for no-split continuing exact-duplicate and target checks,
  persisting strategy and skipped detector identifiers, and preserving the
  input. Existing mode is not allowed to auto-generate a split.

### Fresh regression evidence

| Command / environment | Actual result | Status |
|---|---|---|
| `rtk proxy python -m pytest tests/test_operation_metadata.py tests/test_repairs_api.py tests/test_quarantine_api.py tests/test_combined_repair.py tests/test_split_strategy.py tests/test_column_recommendations.py tests/test_leakage_api.py -q -p no:cacheprovider` from disposable backend copy `C:\Users\sanja\AppData\Local\Temp\DLCV-current-maintenance-20261103-3d223d164ef34d1b8c6992cb622901a0\backend` | **71 passed, 0 failed, 71 warnings**, exit 0. The first run had four test-fixture/assertion issues (two test APIs return arrays, the wrong session import in a test, and duplicate fixture rows not actually duplicated); all were corrected and the focused rerun passed. | PASS |
| `rtk proxy python -m pytest tests -q -p no:cacheprovider` from the same disposable backend copy | **263 passed, 1 skipped, 0 failed, 205 warnings**, exit 0, 65.46s. | PASS |
| `rtk proxy npm test` from project frontend | **78 passed, 0 failed**, exit 0. | PASS |
| `rtk proxy npm run lint` | TypeScript `tsc --noEmit`, exit 0, no diagnostics. | PASS |
| `rtk proxy npm run build -- --outDir C:\Users\sanja\AppData\Local\Temp\DataLeakGuard-CV-maintenance-build-20261103-9f8e77a1` | Exit 0; Vite transformed 2,278 modules. Existing advisories: Node v20.13.1 is below the installed Vite minimum, native-loader `__dirname` warning, and an 892 kB minified JS chunk. | PASS |

The first direct Node test invocation and an initial build invocation inside
the sandbox failed with `EPERM` on `C:\Users\sanja`; the configured `npm test`
and lint passed, and the build passed after the authorized outside-sandbox
retry. These environmental failures did not modify project data.

### Verification status and limitations

| Workflow | Status | Evidence / limitation |
|---|---|---|
| Repair/quarantine/combined and legacy metadata parsing | PASS | Backend serializer/API regression tests and frontend API/page tests include missing, null, empty and populated skipped-findings values, failed/partial/legacy history, and quarantine/repair/combined paths. |
| Target recommendation and manual target confirmation | PASS | Disposable API fixture verifies recommendation preference, manual switching from `readmitted_30d` to `diagnosis`, persisted analysis context, and detector evidence referencing the requested target. Frontend heuristic-warning and API-request tests pass. |
| No-split mode | PASS (automated) | Disposable API test verifies exact-duplicate and target detectors still run, split-dependent detectors are skipped, and operation/profile context records `none`. Live UI workflow NOT VERIFIED. |
| Existing split mode | PASS (automated) | Existing split-strategy suite verifies validation, detector use, operation/audit context, and original-file preservation. Live UI workflow NOT VERIFIED. |
| Combined-cleaning selection/preview/cancel/confirm | PARTIAL | Backend preview, mixed eligible/ineligible findings, stale token, idempotency, failure cleanup, audit, and source preservation are tested. The frontend now exposes the server-computed row-position preview and cancellation. Actual browser click-through and review remain NOT VERIFIED. |
| Full synthetic hospital workflow | NOT VERIFIED | `DataLeakGuard_Synthetic_Hospital_6200_NoSplit.csv` was not found in the repository root; no safe external copy was confirmed. Browser automation packages (`playwright`, `playwright-core`, `puppeteer`) are not installed. No browser E2E test ran. Do not claim the requested 6,224-row journey was verified. |

No schema change or migration was made. All backend test databases and
storage were created under the disposable temporary backend environment.
The project database (`backend/test.db`), project storage, supplied backups,
and Git index were not intentionally opened or modified. The pre-existing
dirty worktree and staged/unstaged `backend/test.db` state were preserved.

## Remediation Center task — pre-change baseline and evidence review (2026-11-03)

All six required project documents were reviewed before implementation.
Read-only inspection confirmed the current detector evidence contracts and
the inherited dirty worktree. The backend evidence formats do not justify
arbitrary row deletion for target or temporal findings; those are planned as
feature exclusion and explicit chronological split rebuilding respectively.
Existing group overlap is not considered safe to delete; a split reassignment
must preserve every entity's rows. Original dataset storage remains
read-only.

Fresh pre-change checks:

| Command / environment | Actual result | Status |
|---|---|---|
| `rtk proxy python -m pytest tests -q -p no:cacheprovider` from isolated copy `C:\Users\sanja\AppData\Local\Temp\DLCV-remediation-baseline-backend-20261103-31d9` | **263 passed, 1 skipped, 205 warnings**, exit 0, 66.04s. Per-test databases/storage were temporary; no project DB/storage was copied. | PASS |
| `rtk proxy npm test` | **78 passed, 0 failed**, exit 0. | PASS |
| `rtk proxy npm run lint` (`tsc --noEmit`) | Exit 0, no diagnostics. | PASS |
| `rtk proxy npm run build -- --outDir C:\Users\sanja\AppData\Local\Temp\DLCV-remediation-baseline-20261103-6f42` | Exit 0; Vite transformed 2,278 modules. Existing warnings: Node 20.13.1 below Vite's minimum, config-loader `__dirname`, and an 892.13 kB JS chunk. | PASS |

Initial frontend checks in the restricted sandbox failed with Node `EPERM`
while resolving `C:\Users\sanja`. The same configured commands were rerun
outside the sandbox with approval and passed. These initial environment
failures are retained here rather than counted as application-test failures.

Implementation plan is recorded in
`DataLeakGuard-CV_WORKING_CONTEXT.txt`. Browser E2E remains NOT VERIFIED at
this checkpoint; no live browser operation or project dataset was used.

## Consolidated remediation engine — backend work unit (2026-11-03)

Added the owner-scoped remediation-plan API and service using existing
`RepairRecord.operation_metadata` and `AuditEvent` storage; no schema change
or migration was introduced. Plans bind the original SHA-256, selected
finding status/description/evidence snapshot, actions and a deterministic
preview digest. Execution requires a matching persisted plan, explicit
confirmation and a fresh source/finding recomputation. Stale plans cannot be
executed. Pending preview cancellation and paginated plan history are
persisted.

Supported evidence-backed actions in this work unit:

| Detector | Supported plan action | Validation and preservation |
|---|---|---|
| Exact duplicate | Keep first; optionally quarantine later copies | Recompute hash groups using persisted hash exclusions; evidence must identify the complete source group; output is separate. |
| Entity overlap | Seeded group-aware train/test reassignment; or quarantine all specifically evidenced rows | Revalidate entity, partition and row references; group reassignment retains each entity's rows and seed/ratio; no silent entity deletion. |
| Target leakage | Exclude confirmed feature column(s), preserve target | Target/feature must match selected persisted findings and the actual source evidence; output is labelled as model-ready feature exclusion, not causal repair. |
| Temporal leakage | Rebuild train/test labels using a user-supplied cutoff | Revalidate current split ranges and timestamp completeness; invalid/missing dates reject preview; output is verified for strict train-before-test chronology. |
| Train/test contamination | Exclude copies outside the explicitly retained partition; or quarantine all evidenced copies | Revalidate every current matching row hash and partition position; no partition is chosen implicitly. |

Combined plans reject duplicate/conflicting selection and conflicting changes
to the same split column. The fixed output artifacts are a separate final
CSV, repair-report CSV, and JSON manifest; a quarantine CSV is generated only
when a confirmed quarantine action is selected. Original uploaded bytes are
not written. The output is re-read, SHA-256 checked, and verified for the
selected rules. Unresolved findings remain open and are reflected as
`partially_remediated` or `review_required`, not marked repaired.

New routes:
- `POST /api/v1/datasets/{dataset_id}/remediation-plans/preview`
- `POST /api/v1/datasets/{dataset_id}/remediation-plans/{plan_id}/execute`
- `POST /api/v1/datasets/{dataset_id}/remediation-plans/{plan_id}/cancel`
- `GET /api/v1/datasets/{dataset_id}/remediation-plans?skip=&limit=`
- `GET /api/v1/operations/{operation_id}/remediation-artifacts/{dataset|report|manifest|quarantine}`

The existing operation download endpoint also recognizes completed
consolidated-remediation final CSV outputs. Report/manifest downloads remain
available for failed verification records; an unverified final dataset is
not downloadable through the artifact route. Ownership is checked for every
route. The public preview response bounds row references to 200 and finding
IDs/skipped rows to 50; complete provenance remains in the owner-scoped
persisted plan and downloadable manifest.

Fresh isolated focused test:

| Command / environment | Actual result | Status |
|---|---|---|
| `rtk proxy python -m pytest tests/test_remediation_plans.py -q -p no:cacheprovider` from isolated copy `C:\Users\sanja\AppData\Local\Temp\DLCV-remediation-phase1e-backend-20261103-b8e1` | **14 passed, 0 failed, 21 warnings**, exit 0, 5.50s. Covers all five action families, source preservation, confirmation, repeat execution, deterministic group split preview, explicit retained partition, manifest/report/final/quarantine CSV downloads and hashes, stale source/finding rejection, review-only state, all-eligible server selection, invalid requests, and dataset ownership. | PASS |

The test was first run three times while adjusting incorrect duplicate
fixtures, the all-eligible count assertion, and the expected partition rows;
the final focused run passed. Those failures were test or verification issues,
not suppressed; the final test asserts current backend behavior.

This is backend service/API verification only. The Remediation Center page,
selection UI, Analysis Setup separation, full regression, TypeScript/lint,
production build, and live browser verification remain NOT VERIFIED at this
checkpoint.

## Remediation Center UI and Analysis Setup work unit — 2026-11-03

Implemented frontend work:
- Added a detector-grouped Remediation Center using the existing owner-scoped
  paginated findings endpoint. Each detector requests at most 10 visible
  findings; collapsed groups request one row for counts. Search, severity and
  status filters are server-side. Stable page order remains the backend's
  created-at/id ordering.
- Added explicit row selection, current-page selection, server-side all-open
  selection, clear controls, evidence expansion, detector-specific supported
  action choices, and preview/cancel/confirm controls. The server validates
  selected IDs/evidence and generates a separate final CSV, report, manifest,
  and optional quarantine artifact. Unknown detector types are not mapped to a
  supported group.
- Added a separate Analysis Setup route with compact advisory recommendations,
  explicit manual selection and confirmation, and existing split-strategy
  controls. A confirmed configuration is passed to the Analysis route through
  tab-scoped session storage; no analysis starts automatically. The Analysis
  page displays the confirmed configuration summary and still requires a
  separate run click.
- Existing `/repair/:id` is preserved as a route and now opens the
  Remediation Center; `/remediation/:id` is the explicit new route. The old
  `RepairPage` component and its individual-operation tests remain in source.

Fresh verification:

| Command | Actual result | Status |
|---|---|---|
| `rtk proxy python -m pytest tests/test_remediation_plans.py -q -p no:cacheprovider` in isolated copy `C:\Users\sanja\AppData\Local\Temp\DLCV-remediation-continuation-backend-20261103` | **14 passed, 0 failed, 21 warnings**, exit 0, 4.96s. Copy excluded databases, storage, bytecode and pytest cache. | PASS |
| `rtk proxy npm test` | **81 passed, 0 failed, 0 skipped**, exit 0. Includes three new Remediation Center render/action-contract tests and the existing frontend suite. | PASS |
| `rtk proxy npx tsc --noEmit` | Exit 0; no diagnostics. | PASS |

Not yet verified at this checkpoint: full backend regression after the
frontend/backend snapshot changes, production build/lint command, actual
browser behavior, interaction with a live dataset, CSV download bytes through
the browser, and Analysis Setup session handoff in an authenticated browser.
Automated render/API/service tests are not browser E2E evidence.

## Remediation Center task — final automated verification — 2026-11-03

The current implementation includes the consolidated owner-scoped remediation
service/API and the frontend Remediation Center and Analysis Setup routes.
The center uses the five supported detector groups, server-side page size 10,
backend-validated selections, actual persisted plan previews, cancellation,
explicit confirmation, operation history, and SHA-256-checked artifact
downloads. Analysis Setup carries only a user-confirmed configuration to
Analysis; it does not run detection.

Fresh verification commands and actual results:

| Command / environment | Actual result | Status |
|---|---|---|
| `rtk proxy python -m pytest tests -q -p no:cacheprovider` from isolated backend copy `C:\Users\sanja\AppData\Local\Temp\DLCV-remediation-continuation-backend-20261103` | **277 passed, 1 skipped, 0 failed, 219 warnings**, exit 0, 81.81s. The copy contained app/tests/migrations/requirements, excluded project DB/storage/bytecode/cache; test fixtures used temporary DB/storage. | PASS |
| `rtk proxy python -m compileall -q app tests` in the same isolated copy | Exit 0. | PASS |
| `rtk proxy npm test` | **86 passed, 0 failed, 0 skipped**, exit 0. Includes RepairPage legacy regressions, Remediation Center action/pagination rendering, API preview/confirm/history/download contracts, Analysis Setup confirmation storage, and prior Batch 1/2 frontend tests. | PASS |
| `rtk proxy npm run lint` | Exit 0; configured command is `tsc --noEmit`. | PASS |
| `rtk proxy npm run build -- --outDir C:\Users\sanja\AppData\Local\Temp\DLCV-remediation-final-build-20261103-r4` | Exit 0; Vite transformed 2,281 modules. Bundle output is outside the project. | PASS |

Existing build advisories remain: local Node v20.13.1 is below the installed
Vite minimum; the native config loader warns about `__dirname`; the generated
JavaScript chunk is about 923.85 kB and triggers the 500 kB advisory. No
database schema/migration change or project DB/storage access was made.

Verification boundary and remaining limitations:
- Backend service/API tests execute real transformations, verify separate
  output bytes/hashes, source preservation, evidence, stale-plan rejection,
  authorization and result metadata using disposable fixtures. Frontend
  artifact calls use mocked fetch in API contract tests.
- **Browser E2E remains NOT VERIFIED.** No authenticated browser session or
  live application workflow was executed. The supplied synthetic hospital
  CSV was not present in the inspected repository. Do not treat automated
  tests as proof of browser navigation, modal/selection behavior, or download
  events.
- Remediation currently processes tabular files synchronously using the
  existing pandas/dataframe architecture. Large-scale memory/latency,
  background-job behavior, and multi-worker deployments were not tested.
- Manual browser instructions are in the final completion note below; execute
  them with a disposable dataset and account before declaring UI E2E PASS.

Manual browser checklist (NOT VERIFIED):
1. Sign in and open a disposable tabular dataset; navigate Dataset → Analysis
   Setup. Search/select columns manually, choose Existing/Generated/No Split,
   confirm, continue, and verify the Analysis page shows the selections.
2. Run the analysis and verify status/results are actual backend responses;
   open persisted findings and inspect evidence.
3. Navigate to `/remediation/{dataset_id}` (and verify the legacy
   `/repair/{dataset_id}` bookmark). Expand each detector, search/filter,
   paginate, select current-page and all-open candidates, inspect evidence,
   and verify unsupported actions are absent.
4. Create a preview, inspect counts/rows/columns/split changes and skipped
   findings; cancel one preview. Create a fresh preview, explicitly confirm,
   wait for server verification, then download final CSV, report, manifest
   and optional quarantine file. Validate response bytes and SHA-256 against
   the persisted plan.
5. Use remediation history to reopen a plan and the Audit History link to
   inspect persisted events. Verify the uploaded source hash/bytes are
   unchanged.
