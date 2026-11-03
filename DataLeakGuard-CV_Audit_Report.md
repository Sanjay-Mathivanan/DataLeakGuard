# DataLeakGuard-CV Complete Application Audit Report

**Generated:** 2026-10-29  
**Repository:** `Sanjay-Mathivanan/DataLeakGuard`  
**Branch:** `main`  
**Audit mode:** Local-only, evidence-first; no production or external services  
**Report status:** Complete

## 1. Executive summary

The current application is a working FastAPI plus React/Vite system for authenticated tabular dataset upload, profiling, leakage detection, evidence retrieval, repair, quarantine, and operation downloads. The backend and frontend verification suites pass, and the live API workflows exercised in this audit persisted and returned real records from the configured SQLite database.

The core implemented path is credible but bounded:

- **Works:** health, registration/login/logout, session persistence on the matching host, CSRF-protected unsafe requests, user-scoped dataset access, CSV upload, five leakage detector paths, persisted findings/evidence, exact-duplicate repair, quarantine, combined-repair code path, operation downloads, notifications, history, and deletion protection.
- **Broken or risky:** the documented `127.0.0.1:3000` browser origin does not retain authenticated API state when the frontend is configured to call `http://localhost:8000`; `AUTH_COOKIE_SECURE` defaults to `false` and there is no HTTPS enforcement in the application; repeated repair was idempotent in the live test, but the API still returns `201` rather than a distinct replay/idempotent status.
- **Mock or frontend-only:** model integrity, inference provenance, distribution shift, impact analysis, and reports are implemented in the frontend service layer with in-memory/mock data. They are not persisted backend workflows.
- **Unverified:** full browser interaction for upload/analysis/repair, XLSX and ZIP live flows, rate-limit behavior under load, deployment proxy behavior, session expiry, and production HTTPS configuration.

No application source code was changed. The only intentional deliverable added by this audit is this report.

## 2. Environment and actual server URLs

| Item | Result |
|---|---|
| Repository root | `C:\Users\sanja\my_project\dataleakguard-cv` |
| Branch | `main` |
| Python | 3.11.9 |
| Node.js | 20.13.1 |
| Docker | Unavailable/not installed; no Docker-based infrastructure was required |
| Backend | `http://127.0.0.1:8000` |
| Backend health | `GET /api/v1/health` → HTTP 200 |
| Frontend | `http://127.0.0.1:3000` and `http://localhost:3000` |
| Database resolved by backend | `C:\Users\sanja\my_project\dataleakguard-cv\backend\test.db` |
| Database integrity | `PRAGMA integrity_check` → `ok` |
| Browser tooling | Integrated browser/Playwright available |

The live database contained pre-existing records before testing. The authorized audit added two disposable accounts and two disposable datasets; no pre-existing account or dataset was deleted or altered. The application has no user-deletion route, and the disposable datasets have findings/history, so the existing deletion policy correctly blocks their deletion.

## 3. Documentation reviewed

Read completely before source inspection:

- [DataLeakGuard-CV_PROJECT_MASTER_CONTEXT.md](./DataLeakGuard-CV_PROJECT_MASTER_CONTEXT.md)
- [README.md](./README.md)

The documentation accurately warned that historical test counts were not fresh, that the database path is relative, that broader model/report pages are mock or partial, and that browser-level verification was still missing. The live audit confirmed those limitations.

## 4. Architecture and initial risk summary

### Architecture observed

- React 19/Vite 8 SPA with React Router.
- FastAPI application under `backend/app`.
- SQLAlchemy 2 and SQLite by default.
- Database metadata separated from original, processed, and quarantine filesystem artifacts.
- API service layer uses real backend calls for auth, workspace, datasets, findings, evidence, repair, quarantine, and history.
- The same service layer retains mock stores for models, reports, inference, impact, distribution shift, and activities fallback behavior.

### Initial risks confirmed or requiring attention

1. Relative `sqlite:///./test.db` depends on the process working directory.
2. `AUTH_COOKIE_SECURE` is false by default and the application does not enforce HTTPS.
3. `VITE_API_BASE_URL` is `http://localhost:8000/api/v1`, while users can open the frontend at `http://127.0.0.1:3000`; host mismatch causes browser cookie/SameSite problems.
4. The frontend production bundle is large (862.46 kB minified JavaScript).
5. Node 20.13.1 is below Vite's stated 20.19+ minimum.
6. Several Pydantic/SQLAlchemy/Pandas deprecation warnings remain.
7. SQLite operation records do not declare dataset/finding foreign keys; service-level ownership checks are relied on.
8. The broader product screens can appear authoritative while using deterministic mock data unless their UI disclaimers are noticed.

## 5. Test-account results

The supplied User A credential was used only in memory and is not included here. Two unique disposable User B accounts were created locally for isolated workflow tests; passwords were generated in memory and not printed, stored in the repository, or written to this report.

| Test | Status | Evidence |
|---|---|---|
| User A login | PASS | HTTP 200 |
| User A current-user endpoint | PASS | HTTP 200 |
| User A dataset list/dashboard | PASS | HTTP 200; records were user-scoped |
| Invalid User A password | PASS | HTTP 401 |
| User A logout | PASS | HTTP 204 |
| User A protected request after logout | PASS | HTTP 401 |
| User B registration | PASS | HTTP 201 |
| User B current-user and refresh | PASS | HTTP 200 on both requests |
| User B upload and analysis | PASS | HTTP 201 upload; HTTP 200 analysis |
| User B cannot read User A dataset | PASS | HTTP 404 |
| User B cannot list User A findings | PASS | HTTP 404 |
| User B cannot delete User A dataset | PASS | HTTP 404 |
| User B notifications/read-all | PASS | HTTP 200 |
| User B logout/protected request after logout | PASS | HTTP 204 then HTTP 401 |

The API returned 404 for cross-user resources rather than revealing whether a resource exists. This is the expected privacy-preserving behavior for these routes.

## 6. Browser route and navigation checklist

### Browser evidence

- Login page loaded and rendered at `http://localhost:3000/login`.
- User A login redirected to `/dashboard`.
- Dashboard rendered persisted counts and recent activity from the backend when opened at the matching `localhost` host.
- Refresh at the matching host retained the authenticated session.
- Sign out navigated to `/login`; backend logs recorded HTTP 204 for logout.
- Route smoke checks completed for `/dashboard`, `/datasets`, `/model-integrity`, `/inference-provenance`, `/distribution-shift`, `/impact-analysis`, `/reports`, and `/account`.
- No blank page or `Authentication required` alert was observed at the matching `localhost` origin after login.

### Reproduced browser defect

| Status | Route/steps | Observed behavior |
|---|---|---|
| FAIL | Open `http://127.0.0.1:3000/login`, log in, then load dashboard | Login returns success, but dashboard API calls return 401 and the page displays `Authentication required`. |
| PASS | Open `http://localhost:3000/login`, log in, then load dashboard | Dashboard API calls return 200 and persisted dashboard content renders. |

Cause: [.env.local](./.env.local) configures `VITE_API_BASE_URL=http://localhost:8000/api/v1`, while the first browser origin is `127.0.0.1`. The host-only cookie plus `SameSite=Lax` behavior prevents the cross-host fetch from carrying the session as expected. This should be fixed by using one canonical local origin or deriving the API origin consistently.

The first browser route attempt generated only expected unauthenticated 401 responses during session probing; after matching the configured host, the authenticated route checks succeeded.

## 7. Leakage-detector test matrix

| Detector | Valid live test | Persistence/evidence | Negative/control | Status |
|---|---|---|---|---|
| Exact duplicates | Duplicate rows injected in disposable CSV | Finding list/detail/evidence returned HTTP 200 | Detector unit/API suite covers non-duplicate cases | PASS |
| Entity overlap | Entity `A` appears in train and test | Finding and evidence returned | Existing detector suite covers controls | PASS |
| Target leakage | Target/configured feature association present | Finding persisted in analysis result | Existing target leakage suite covers controls | PASS |
| Temporal leakage | Overlapping train/test date ranges | Finding persisted in analysis result | Existing temporal suite covers invalid/no-valid-time controls | PASS |
| Train/test contamination | Matching content across split values | Finding persisted in analysis result | Existing contamination suite covers controls | PASS |
| Invalid/missing detector configuration | Unsupported repair target and ownership cases | HTTP 400/404, no false success | API tests cover validation paths | PASS |

Live analysis used a small disposable CSV with `id`, `entity`, `split`, `target`, `time`, and `feature` columns. The API returned persisted finding records and a separate evidence response; the UI service maps persisted finding fields rather than fabricating evidence for these core routes.

## 8. Repair, quarantine, and history

| Test | Status | Evidence |
|---|---|---|
| Exact-duplicate repair | PASS | HTTP 201; operation detail HTTP 200 |
| Repair output download | PASS | HTTP 200 from operation download route |
| Repeated equivalent repair | PASS | HTTP 201 response reused the existing completed operation; database had one repair record for the disposable dataset |
| Entity-overlap quarantine | PASS | HTTP 201; detail and list both HTTP 200 |
| Unsupported target-leakage repair | PASS | HTTP 400 |
| Dataset deletion after findings/history | PASS | HTTP 409, audit-preserving deletion guard |
| Original preservation | PASS by observed workflow/code contract | Operations wrote separate outputs; originals were not rewritten |

The live database showed two operation records for the disposable operations dataset: one repair and one quarantine. Existing records and runtime artifacts were not bulk-cleaned.

## 9. API test results

### Commands and exact results

| Command | Result |
|---|---|
| `Set-Location backend; python -m pytest tests/ -q` | **235 passed, 1 skipped**, exit code 0, 183 warnings |
| `node --import tsx --test ...` (seven existing frontend test files) | **48 passed, 0 failed, 0 skipped**, exit code 0 |
| `npm run lint` | TypeScript check passed, exit code 0 |
| `npm run build` | Build passed, exit code 0 |
| `GET http://127.0.0.1:8000/api/v1/health` | HTTP 200 |
| Allowed CORS preflight from `http://127.0.0.1:3000` | HTTP 200 |
| Disallowed CORS preflight from `http://evil.example` | HTTP 400 |

### Warnings

- Vite reported Node 20.13.1 below its 20.19+ requirement.
- Vite warned that `__dirname` is unsupported by the planned native config loader.
- Vite reported an 862.46 kB minified JavaScript chunk.
- Pydantic reported deprecated class-based config/`orm_mode`.
- SQLAlchemy reported the legacy `declarative_base()` import.
- Pandas reported a future PyArrow dependency and timestamp-inference warning.

## 10. Mock versus real integration matrix

| Feature | Classification | Evidence |
|---|---|---|
| Auth/session/profile/password | Fully connected and API-backed | `src/services/api.ts`, live account tests |
| Dashboard counts/activity | Partially connected; counts/history are backend-backed | Live dashboard HTTP 200; activities derive from account history |
| Dataset upload/list/detail/delete | Fully connected for supported tabular workflows | Live upload/list and API tests |
| Leakage analysis/findings/evidence | Fully connected and persisted | Live detector/evidence tests |
| Repair/quarantine/download/history | Fully connected for supported finding types | Live operations and API tests |
| Model integrity | Mock/simulated frontend | `getModels`/`verifyModel` use `modelsStore` in `src/services/api.ts` |
| Inference provenance | Mock/simulated frontend | `runInference` synthesizes hashes, nonce, signature, and records in memory |
| Distribution shift | Mock/simulated frontend | `getDistributionShift` returns `mockDistributionShiftData` |
| Impact analysis | Mock/simulated frontend | `getImpactAnalysis` returns `mockImpactData` |
| Reports | Mock/simulated frontend | `getReports`, `generateAssuranceReport`, and `deleteReport` use `reportsStore` |
| ZIP/CV analysis | Partial | Basic image ZIP profiling exists; no general CV leakage analysis was verified |
| Download history persistence | Not implemented/NOT VERIFIED | No persisted download-history route or record was verified |

## 11. Security findings

| # | Severity | File | Lines | Vulnerability | Confidence |
|---|---|---|---|---|---|
| 1 | 🟠 HIGH | `backend/app/core/config.py` | 24 | `AUTH_COOKIE_SECURE` defaults to `False`, and `backend/app/main.py` has no HTTPS enforcement. If exposed over HTTP, a session cookie can be intercepted and replayed. | 9/10 |
| 2 | 🟡 MEDIUM | `.env.local`, frontend runtime configuration | N/A | Local host mismatch (`127.0.0.1` frontend versus `localhost` API) breaks authenticated browser requests and can lead operators to disable cookie/CORS protections as a workaround. | 9/10 |
| 3 | 🟡 MEDIUM | `backend/app/core/config.py` | 32-49 | The default rate-limit storage is process-local `memory://`; multi-worker/multi-instance deployments do not share authentication limits unless a compatible shared backend is installed and configured. | 8/10 |
| 4 | ⚪ LOW | `backend/app/db/models.py` | 29-34, 73-105 | `RepairRecord` and audit-related dataset/finding references rely on service validation rather than database foreign keys, increasing orphan/integrity risk during future maintenance or direct DB operations. | 8/10 |

### Security controls that passed review

- Passwords use Werkzeug scrypt hashes.
- Session tokens are random and only token digests are persisted.
- Session cookies are HttpOnly and SameSite=Lax.
- Unsafe methods require a matching CSRF cookie/header and stored session hash.
- Origin/Referer validation is applied to registration/login.
- Upload storage names are UUID-derived rather than attacker-controlled paths.
- Download paths use stored filenames, basename/containment checks, and SHA-256 verification.
- ORM query construction was used; no exploitable raw SQL construction was found.
- Owner checks were present across datasets, findings, operations, quarantines, notifications, and downloads.

## 12. UI and usability issues

| Priority | Issue | Evidence |
|---|---|---|
| High | Local browser host mismatch causes authenticated dashboard failure at `127.0.0.1`. | Reproduced browser route test above |
| Medium | Model, inference, distribution, impact, and report screens present polished assurance-style data despite in-memory/mock implementation. | Service-layer inspection and route smoke tests |
| Medium | Reports UI's “PDF” action only displays delayed success messaging; no PDF download was observed or backed by an API. | `ReportsPage.tsx` `handleDownloadPDF` |
| Low | Large production bundle can slow initial page load. | `npm run build` Vite warning |
| Low | Several forms use generic failure messages, reducing diagnosis for backend validation failures. | Upload/report/model page catch blocks |

No redesign was performed. No claim is made about responsive layout beyond the observed desktop browser route smoke checks.

## 13. Reproduction steps for failures

### Host mismatch

1. Start backend from `backend/` on port 8000.
2. Start frontend on port 3000.
3. Open `http://127.0.0.1:3000/login`.
4. Log in with a valid local account.
5. Observe successful redirect followed by dashboard `Authentication required` and 401 API responses.
6. Open `http://localhost:3000/login` instead and repeat; dashboard requests succeed.

### Insecure deployment default

1. Start the backend with default settings over HTTP.
2. Inspect the `dlg_session` cookie after login.
3. The cookie is issued without `Secure` unless `AUTH_COOKIE_SECURE=true` or the request is HTTPS.
4. Deployments without an enforcing TLS edge can expose replayable session cookies.

## 14. Limitations and tests not performed

- No production or external service was contacted.
- User A's password, session tokens, CSRF values, and disposable passwords were not recorded.
- No existing user or pre-existing dataset was deleted or reset.
- Browser upload, XLSX upload, ZIP upload, full analysis UI configuration, finding evidence panel navigation, and repair UI clicks were not exhaustively driven end-to-end.
- Session expiration was not waited out.
- Rate limiting was not stress-tested; only normal login/registration paths were exercised.
- No multi-worker/shared-rate-limit deployment was run.
- No Docker infrastructure was available or needed for this SQLite-local audit.
- No screenshots were captured for the report; browser accessibility snapshots and console/network evidence were used.
- The report does not treat the passing existing tests as proof of production deployment behavior.

## 15. Prioritized recommendations

1. **Fix the canonical local/prod origin configuration.** Use one host consistently or derive the API URL from the current origin; add a browser regression test for both documented local URLs.
2. **Fail closed for production transport security.** Make secure cookies mandatory outside an explicit development profile, enforce HTTPS at the trusted edge, and document the deployment check.
3. **Provide shared rate-limit storage or enforce equivalent ingress limits.** Validate the provider in a multi-worker test before production use.
4. **Separate mock screens from the assurance product surface.** Add explicit “simulation/demo data” labeling and disable actions that imply persisted model/report workflows until backend contracts exist.
5. **Add browser E2E coverage for the core journey.** Login → upload CSV/XLSX → configure detectors → review evidence → repair/quarantine → download → logout, including a test that asserts the original file remains unchanged.

## 16. Runtime validation verdict

```text
environment:
  docker: UNAVAILABLE — docker command/daemon was not available
  node: AVAILABLE — v20.13.1 (below Vite's stated 20.19+ minimum; build still passed)
  playwright: AVAILABLE — integrated browser navigation and route smoke checks completed
  infra-tier: FALLBACK(embedded/local SQLite) — project is configured for local SQLite and Docker was unavailable
  browser-tier: PRIMARY(Playwright) — localhost browser flows and route smoke checks completed
startup: PASS — uvicorn on 127.0.0.1:8000, Vite on 127.0.0.1:3000, health HTTP 200
integration: PASS — exit_code: 0, passed: 235, failed: 0, skipped: 1, backend suite
e2e: PARTIAL — exit_code: 0 for browser route checks, core login/logout verified; upload/repair UI journey not fully automated
overall: NEEDS_SIGNOFF — core backend workflow passes, but host mismatch and production cookie/rate-limit risks require remediation
```

## 17. Final verdict

**Works correctly:** the authenticated, persisted tabular integrity workflow and its tested API operations are functional on the matching local host. The backend suite, frontend tests, type-check, build, health endpoint, CORS checks, and live two-account isolation tests all produced evidence supporting that conclusion.

**Broken:** the `127.0.0.1` browser origin is incompatible with the configured `localhost` API/cookie setup for authenticated dashboard calls.

**Mocked/incomplete:** model integrity, inference provenance, distribution shift, impact analysis, and assurance reports are in-memory/mock frontend features; CV ZIP support is profiling-only.

**Insecure/risky:** production transport security defaults are permissive, default rate limiting is process-local, and database references for operation/audit records are not fully enforced by foreign keys.

**Remaining unverified:** full browser core journey, deployment topology, shared rate limits, HTTPS edge behavior, session expiry, and non-CSV live uploads.

## Batch 1 addendum — Findings, history, profiles, and recommendations (2026-11-02)

This is a follow-up implementation/test addendum, not a re-audit of the earlier
runtime evidence above. Batch 1 added paginated owner-scoped findings and
history APIs, metadata-driven Feature Profiles controls, and an explainable
column-role recommendation service/UI. No database schema migration was
introduced.

Fresh isolated regression: backend **245 passed, 1 skipped, 191 warnings**;
frontend **61 passed**; TypeScript/lint passed; production build passed.
Warnings and exact commands are recorded in
`DataLeakGuard-CV_E2E_TEST_REPORT.md`. No browser E2E run was possible in this
environment, so interactive flows remain NOT VERIFIED. This addendum does not
change the earlier audit's production deployment/security caveats. Batch 2
status is recorded separately below.

## Batch 2 implementation verification addendum (2026-11-03)

This is an implementation/regression addendum, not a fresh security audit or
production-readiness assessment. Batch 2 adds the split-strategy flow,
analysis workspace integration, confirmed combined exact-duplicate cleaning,
and verification safeguards for the existing exact-duplicate repair path.
Ownership checks, request validation, source-file preservation, operation
metadata, and persisted audit/evidence references are covered by automated
tests. No new Batch 2 database schema or migration was introduced or applied.

Fresh isolated regression results: backend **256 passed, 1 skipped, 0 failed**
in a disposable project copy; frontend **74 passed, 0 failed**; TypeScript
lint passed; production build passed. The initial backend regression exposed
seven legacy split API compatibility failures. The route was corrected to
keep explicit Phase 5 split validation strict while preserving prior legacy
request behavior; the final full suite passed. Detailed commands and
expected/actual evidence are in the E2E report.

No browser-based Batch 2 test was performed; confirmation dialogs, analysis
navigation, and activity rendering remain NOT VERIFIED. No production
deployment, multi-worker environment, proxy, external service, project
database, project storage, or backup was exercised. The existing warnings
about production HTTPS/cookies, trusted proxy configuration, shared
rate-limit storage, and deployment topology remain unresolved; this addendum
does not declare the project production-ready.

## Maintenance addendum — 2026-11-03

This is implementation regression evidence, not a new security assessment.
The repair/quarantine history parsing failure was caused by assuming every
persisted operation had combined-repair metadata. Response serialization now
normalizes legacy missing/null skipped-finding data without rewriting stored
records. Existing owner authorization remains in the protected routes.

Combined-cleaning preview provides actual zero-based source row references
(bounded), count, truncation indicator and digest, with cancellation and
explicit confirmation retained. Raw row contents are intentionally omitted.
Target recommendation changes are deterministic heuristics only; manual
target selection remains authoritative, and potential derived feature names
are warnings rather than confirmed leakage.

Fresh disposable tests: backend **263 passed, 1 skipped**; frontend **78
passed**; TypeScript/lint and production build passed. No migration or schema
change occurred. No browser verification was performed; the target synthetic
CSV and browser automation dependencies were unavailable. These results do
not resolve the pre-existing production deployment caveats documented above.

## Remediation Center / Analysis Setup implementation addendum — 2026-11-03

This is a code-path and regression-test review, not a new penetration test or
full security audit.

- The remediation routes require the existing authenticated-user dependency.
  Dataset ownership is checked for preview, execute, cancel, history and
  artifact resolution. Finding selection is reloaded and validated against
  the dataset server-side; the frontend selection state is not trusted.
- Preview/execution bind to the source file SHA-256 and a selected finding
  evidence/status snapshot. Execution requires the current preview token and
  explicit confirmation. Stale input is rejected; original source bytes are
  not overwritten. Output artifacts are resolved from persisted operation
  metadata and ownership-scoped operation records.
- Supported transforms are constrained by evidence: deterministic duplicate
  keep-first; entity group reassignment or evidenced quarantine; target
  feature exclusion retaining the target; chronological split rebuilding from
  explicit timestamps/cutoff; and contamination handling only with explicit
  partition retention or evidence-backed quarantine. Unsupported findings
  remain unresolved/review-only. Recommendation scores are not interpreted as
  probabilities and are not automatically applied.
- No schema or migration change was made. Full isolated backend regression:
  **277 passed, 1 skipped, 0 failed**. Frontend regression: **86 passed**;
  TypeScript/lint and Python compilation passed; production build passed.
  Detailed commands/environment are in the E2E report.

Residual security/operational limitations:
- Authenticated browser access, cross-user behavior in a deployed browser,
  real attachment downloads, and the full user workflow are **NOT VERIFIED**
  in this maintenance task. The backend authorization/API tests ran only in
  isolated test fixtures.
- Remediation execution is synchronous and uses the current dataframe-based
  service architecture; large-file resource limits, request timeouts,
  background-job reliability and multi-worker locking were not tested.
- Existing HTTPS/cookie, trusted-proxy, shared rate-limit storage and
  deployment-topology caveats remain. This addendum does not certify
  production readiness.

