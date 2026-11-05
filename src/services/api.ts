/** Authenticated API service for the DataLeakGuard-CV FastAPI backend. */

import {
  Dataset,
  PersistedFinding,
  DatasetFindingPage,
  FindingPageFilters,
  DatasetHistoryPage,
  DatasetHistoryItem,
  ColumnRecommendationsResponse,
  FindingCategorySummary,
  AnalysisResult,
  AnalysisStage,
  DatasetOperationRecord,
  SplitGenerationOperation,
  CombinedRepairMetadata,
  CombinedRepairPreview,
  RemediationActionRequest,
  RemediationPlanPage,
  RemediationPlanRecord,
  ImputationOperation,
  ImputationPreview,
  ImputationRequest,
  FindingOperationType,
  Model,
  InferenceRecord,
  DistributionShift,
  ImpactAnalysis,
  AssuranceReport,
  PersistedReportContent,
  PersistedReportDataset,
  PersistedReportImpact,
  Activity
} from '../types';

const toCamelCase = (obj: any): any => {
  if (obj === null || typeof obj !== 'object') return obj;
  if (Array.isArray(obj)) {
    return obj.map(toCamelCase);
  }
  return Object.keys(obj).reduce((acc, key) => {
    const camelKey = key.replace(/_([a-z])/g, (_, character) => character.toUpperCase());
    // @ts-ignore
    // Dataset preview row keys are user-provided column names, not API field
    // names. Preserve them verbatim so they continue matching `columns[].name`.
    acc[camelKey] = key === 'preview_rows' ? obj[key] : toCamelCase((obj as any)[key]);
    return acc;
  }, {});
};

const getApiBaseUrl = (): string =>
  (import.meta.env?.VITE_API_BASE_URL || '/api/v1').replace(/\/+$/, '');

const getCookie = (name: string): string | null => {
  if (typeof document === 'undefined') return null;
  const prefix = `${name}=`;
  const item = document.cookie.split('; ').find((cookie) => cookie.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : null;
};

export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {}
): Promise<Response> {
  const headers = new Headers(init.headers);
  const method = (init.method ?? 'GET').toUpperCase();
  const csrfToken = getCookie('dlg_csrf');
  if (csrfToken && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    headers.set('X-CSRF-Token', csrfToken);
  }
  return fetch(input, {
    ...init,
    headers,
    credentials: 'include',
  });
}

export interface ApiUser {
  id: string;
  email: string;
  displayName: string;
  createdAt: string;
}

export interface ApiAuthResponse {
  user: ApiUser;
  csrfToken: string;
}

export interface ApiNotification {
  id: string;
  eventType: string;
  title: string;
  message: string;
  createdAt: string;
  readAt: string | null;
  datasetId: string | null;
  findingId: string | null;
  operationId: string | null;
}

export interface DashboardSummary {
  datasetCount: number;
  findingCount: number;
  openFindingCount: number;
  highOrCriticalFindingCount: number;
  latestAnalysisAt: string | null;
  recentDatasets: Array<{
    id: string;
    name: string;
    status: string | null;
    lastAnalysis: string | null;
  }>;
  recentOperations: Array<{
    id: string;
    datasetId: string;
    operationType: string;
    status: string;
    createdAt: string | null;
  }>;
  models: { available: boolean; count?: number; reason?: string };
  reports: { available: boolean; count?: number; reason?: string };
}

async function readApiError(response: Response, fallback: string): Promise<Error> {
  try {
    const body: unknown = await response.json();
    if (isRecord(body) && typeof body.detail === 'string') return new Error(body.detail);
  } catch {
    // Fall through to status-based message.
  }
  return new Error(`${fallback} (${response.status})`);
}

export async function loginApi(email: string, password: string): Promise<ApiAuthResponse> {
  const response = await apiFetch(`${getApiBaseUrl()}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw await readApiError(response, 'Login failed');
  return toCamelCase(await response.json());
}

export async function registerApi(
  displayName: string,
  email: string,
  password: string
): Promise<ApiAuthResponse> {
  const response = await apiFetch(`${getApiBaseUrl()}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: displayName, email, password }),
  });
  if (!response.ok) throw await readApiError(response, 'Registration failed');
  return toCamelCase(await response.json());
}

export async function getCurrentUserApi(): Promise<ApiAuthResponse | null> {
  const response = await apiFetch(`${getApiBaseUrl()}/auth/me`);
  if (response.status === 401) return null;
  if (!response.ok) throw await readApiError(response, 'Could not load the current user');
  return toCamelCase(await response.json());
}

export async function logoutApi(): Promise<void> {
  const response = await apiFetch(`${getApiBaseUrl()}/auth/logout`, { method: 'POST' });
  if (!response.ok) throw await readApiError(response, 'Logout failed');
}

export async function updateProfileApi(payload: {
  displayName: string;
  email: string;
}): Promise<ApiUser> {
  const response = await apiFetch(`${getApiBaseUrl()}/auth/profile`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: payload.displayName, email: payload.email }),
  });
  if (!response.ok) throw await readApiError(response, 'Profile update failed');
  return toCamelCase(await response.json());
}

export async function changePasswordApi(
  currentPassword: string,
  newPassword: string
): Promise<void> {
  const response = await apiFetch(`${getApiBaseUrl()}/auth/password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (!response.ok) throw await readApiError(response, 'Password change failed');
}

export async function getDashboardSummary(): Promise<DashboardSummary> {
  const response = await apiFetch(`${getApiBaseUrl()}/dashboard/summary`);
  if (!response.ok) throw await readApiError(response, 'Could not load dashboard data');
  return toCamelCase(await response.json());
}

export async function getNotifications(): Promise<ApiNotification[]> {
  const response = await apiFetch(`${getApiBaseUrl()}/notifications?limit=30`);
  if (!response.ok) throw await readApiError(response, 'Could not load notifications');
  return toCamelCase(await response.json());
}

export async function markNotificationRead(id: string): Promise<void> {
  const response = await apiFetch(
    `${getApiBaseUrl()}/notifications/${encodeURIComponent(id)}/read`,
    { method: 'POST' }
  );
  if (!response.ok) throw await readApiError(response, 'Could not update notification');
}

export async function markAllNotificationsRead(): Promise<void> {
  const response = await apiFetch(`${getApiBaseUrl()}/notifications/read-all`, { method: 'POST' });
  if (!response.ok) throw await readApiError(response, 'Could not update notifications');
}

export async function getAccountHistory(limit = 100): Promise<Array<Record<string, unknown>>> {
  const response = await apiFetch(`${getApiBaseUrl()}/account/history?limit=${limit}`);
  if (!response.ok) throw await readApiError(response, 'Could not load account history');
  const data: unknown = await response.json();
  return Array.isArray(data) ? data.map(toCamelCase) : [];
}

export async function getDatasetHistory(datasetId: string): Promise<Array<Record<string, unknown>>> {
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/history`
  );
  if (!response.ok) throw await readApiError(response, 'Could not load dataset history');
  const data: unknown = await response.json();
  return Array.isArray(data) ? data.map(toCamelCase) : [];
}

export async function getDatasetHistoryPage(
  datasetId: string,
  filters: {
    skip?: number;
    limit?: number;
    eventType?: string;
    status?: string;
    startDate?: string;
    endDate?: string;
    search?: string;
  } = {}
): Promise<DatasetHistoryPage> {
  const query = new URLSearchParams();
  if (filters.skip !== undefined) query.set('skip', String(filters.skip));
  if (filters.limit !== undefined) query.set('limit', String(filters.limit));
  if (filters.eventType) query.set('event_type', filters.eventType);
  if (filters.status) query.set('status', filters.status);
  if (filters.startDate) query.set('start_date', filters.startDate);
  if (filters.endDate) query.set('end_date', filters.endDate);
  if (filters.search?.trim()) query.set('search', filters.search.trim());

  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/history/page?${query.toString()}`
  );
  if (!response.ok) throw await readApiError(response, 'Could not load dataset history');
  const raw: unknown = await response.json();
  if (!isRecord(raw) || !Array.isArray(raw.items)) {
    throw new Error('Invalid dataset history page response');
  }
  const items: DatasetHistoryItem[] = raw.items.map((item: unknown) => {
    if (!isRecord(item)) throw new Error('Invalid dataset history item');
    const mapped = toCamelCase(item);
    return {
      id: String(mapped.id ?? ''),
      eventType: String(mapped.eventType ?? ''),
      outcome: String(mapped.outcome ?? ''),
      details: isRecord(item.details) ? item.details : null,
      createdAt: String(mapped.createdAt ?? ''),
      completedAt: typeof mapped.completedAt === 'string' ? mapped.completedAt : null,
      datasetId: String(mapped.datasetId ?? ''),
      datasetName: String(mapped.datasetName ?? ''),
      findingId: typeof mapped.findingId === 'string' ? mapped.findingId : null,
      operationId: typeof mapped.operationId === 'string' ? mapped.operationId : null,
      userId: typeof mapped.userId === 'string' ? mapped.userId : null,
      failureReason: typeof mapped.failureReason === 'string' ? mapped.failureReason : null,
    };
  });
  return {
    items,
    total: typeof raw.total === 'number' ? raw.total : 0,
    skip: typeof raw.skip === 'number' ? raw.skip : 0,
    limit: typeof raw.limit === 'number' ? raw.limit : 25,
  };
}

export async function changePassword(
  currentPassword: string,
  newPassword: string
): Promise<void> {
  await changePasswordApi(currentPassword, newPassword);
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

const requireString = (finding: Record<string, unknown>, field: string): string => {
  const value = finding[field];
  if (typeof value !== 'string') {
    throw new Error(`Invalid finding response: expected "${field}" to be a string`);
  }
  return value;
};

export function mapPersistedFinding(value: unknown): PersistedFinding {
  if (!isRecord(value)) {
    throw new Error('Invalid finding response: expected an object');
  }

  return {
    id: requireString(value, 'id'),
    datasetId: requireString(value, 'dataset_id'),
    findingType: requireString(value, 'finding_type'),
    severity: requireString(value, 'severity'),
    status: requireString(value, 'status'),
    description: requireString(value, 'description'),
    evidence: isRecord(value.evidence) ? value.evidence : null,
    createdAt: typeof value.created_at === 'string' ? value.created_at : null,
  };
}

export function getFindingTypeLabel(findingType: string): string {
  const labels: Record<string, string> = {
    exact_duplicate: 'Exact duplicate',
    entity_overlap: 'Entity overlap',
    target_leakage: 'Target leakage',
    temporal_leakage: 'Temporal leakage',
    train_test_contamination: 'Train/test contamination',
  };
  return labels[findingType] ?? `Unknown finding type (${findingType})`;
}

export function summarizeFindings(
  findings: PersistedFinding[]
): FindingCategorySummary[] {
  const counts = new Map<string, number>();
  for (const finding of findings) {
    counts.set(finding.findingType, (counts.get(finding.findingType) ?? 0) + 1);
  }

  return Array.from(counts, ([findingType, findingsCount]) => ({
    findingType,
    label: getFindingTypeLabel(findingType),
    findingsCount,
  }));
}

// ==========================================
// DATASET OPERATIONS
// ==========================================

export async function getDatasets(): Promise<Dataset[]> {
  const res = await apiFetch(`${getApiBaseUrl()}/datasets`);
  if (!res.ok) {
    throw new Error(`Failed to fetch datasets: ${res.status}`);
  }
  const data = await res.json();
  if (!Array.isArray(data)) {
    throw new Error('Expected an array of datasets from the API');
  }
  return data.map(toCamelCase);
}

export async function getDatasetById(id: string): Promise<Dataset | null> {
  const res = await apiFetch(`${getApiBaseUrl()}/datasets/${encodeURIComponent(id)}`);
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Failed to fetch dataset: ${res.status}`);
  }
  const data = await res.json();
  return toCamelCase(data);
}

export interface DatasetProfilingResult {
  datasetId: string;
  datasetName: string;
  sourceFileSha256: string;
  generatedAt: string;
  profile: NonNullable<Dataset['profile']>;
}

function mapDatasetProfilingResult(raw: unknown): DatasetProfilingResult {
  if (!isRecord(raw) || !isRecord(raw.profile)) {
    throw new Error('Invalid dataset profiling response');
  }
  const mapped = toCamelCase(raw);
  const rawProfile = raw.profile as Record<string, unknown>;
  const profile = mapped.profile as NonNullable<Dataset['profile']>;
  // `dtypes` is an object indexed by caller-provided column names; preserve
  // those keys instead of applying API field-name conversion to them.
  if (isRecord(rawProfile.dtypes)) {
    (profile as Record<string, unknown>).dtypes = rawProfile.dtypes;
  }
  if (
    typeof mapped.datasetId !== 'string' ||
    typeof mapped.datasetName !== 'string' ||
    typeof mapped.sourceFileSha256 !== 'string' ||
    typeof mapped.generatedAt !== 'string' ||
    !Array.isArray(profile.columnProfiles)
  ) {
    throw new Error('Invalid dataset profiling response fields');
  }
  return {
    datasetId: mapped.datasetId,
    datasetName: mapped.datasetName,
    sourceFileSha256: mapped.sourceFileSha256,
    generatedAt: mapped.generatedAt,
    profile,
  };
}

export async function getDatasetProfiling(datasetId: string): Promise<DatasetProfilingResult> {
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/profiling`
  );
  if (!response.ok) throw await readApiError(response, 'Could not load detailed dataset profiling');
  return mapDatasetProfilingResult(await response.json());
}

export async function refreshDatasetProfiling(datasetId: string): Promise<DatasetProfilingResult> {
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/profiling`,
    { method: 'POST' }
  );
  if (!response.ok) throw await readApiError(response, 'Could not refresh dataset profiling');
  return mapDatasetProfilingResult(await response.json());
}

export function getSupportedUploadDetails(
  fileName: string
): { type: 'tabular' | 'computer-vision'; format: 'CSV' | 'XLSX' | 'ZIP' } | null {
  const extension = fileName.includes('.') ? fileName.split('.').pop()?.toLowerCase() : undefined;
  if (extension === 'csv') return { type: 'tabular', format: 'CSV' };
  if (extension === 'xlsx') return { type: 'tabular', format: 'XLSX' };
  if (extension === 'zip') return { type: 'computer-vision', format: 'ZIP' };
  return null;
}

export async function uploadDataset(payload: {
  name: string;
  type: 'tabular' | 'computer-vision';
  format: 'CSV' | 'XLSX' | 'ZIP';
  description: string;
  file: File;
}): Promise<Dataset> {
  const formData = new FormData();
  formData.append('name', payload.name);
  formData.append('type', payload.type);
  formData.append('format', payload.format);
  formData.append('description', payload.description);
  formData.append('file', payload.file);

  const res = await apiFetch(`${getApiBaseUrl()}/datasets`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    throw new Error(`Failed to upload dataset: ${res.statusText}`);
  }
  const data = await res.json();
  return toCamelCase(data);
}

export async function deleteDataset(id: string): Promise<boolean> {
  const res = await apiFetch(`${getApiBaseUrl()}/datasets/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    throw new Error(`Failed to delete dataset: ${res.statusText}`);
  }
  // Backend returns 204 No Content on success; treat any 2xx as success.
  return true;
}

// ==========================================
// ANALYSIS OPERATIONS
// ==========================================

export interface LeakageAnalysisOptions {
  entityColumn?: string;
  entityColumns?: string[];
  contaminationKeyColumns?: string[];
  splitColumn?: string;
  targetColumn?: string;
  timeColumn?: string;
  temporalObjective?: 'future_prediction' | 'randomized_holdout';
  splitStrategy?: 'existing' | 'generated' | 'none';
  splitOperationId?: string;
  configurationConfirmed?: boolean;
}

type DetectorStageStatus = AnalysisStage['status'];

export function buildAnalysisStages(
  typeCounts: Record<string, number>,
  options: LeakageAnalysisOptions = {},
  execution: 'not_started' | 'running' | 'completed' | 'failed' = 'not_started'
): AnalysisStage[] {
  const hasEntity = Boolean(options.entityColumns?.length || options.entityColumn);
  const hasSplit = options.splitStrategy === 'none'
    ? false
    : Boolean(options.splitColumn || (options.splitStrategy === 'generated' && options.splitOperationId));
  const hasTime = Boolean(options.timeColumn);
  const noSplit = options.splitStrategy === 'none';
  const randomizedTemporalHoldout =
    options.temporalObjective === 'randomized_holdout' && hasTime && hasSplit;
  const detectorStages: Array<{
    id: number;
    name: string;
    findingType?: string;
    requested: boolean;
    needsConfiguration?: boolean;
    skipped?: boolean;
    requirement: string;
  }> = [
    {
      id: 1,
      name: 'Dataset Profiling',
      requested: false,
      skipped: true,
      requirement: 'Profiling is not part of the leakage-analysis request.'
    },
    {
      id: 2,
      name: 'Exact Duplicate Detection',
      findingType: 'exact_duplicate',
      requested: true,
      requirement: 'Runs for every leakage-analysis request.'
    },
    {
      id: 3,
      name: 'Entity Overlap',
      findingType: 'entity_overlap',
      requested: hasEntity && hasSplit,
      needsConfiguration: hasEntity && !hasSplit && !noSplit,
      skipped: noSplit,
      requirement: 'Select both an entity/identifier column and a split column.'
    },
    {
      id: 4,
      name: 'Target Leakage',
      findingType: 'target_leakage',
      requested: Boolean(options.targetColumn),
      requirement: 'Select a target column to run this detector.'
    },
    {
      id: 5,
      name: 'Temporal Leakage',
      findingType: 'temporal_leakage',
      requested: hasTime && hasSplit,
      needsConfiguration: hasTime && !hasSplit && !noSplit,
      skipped: noSplit,
      requirement: 'Select both a timestamp/time column and a split column.'
    },
    {
      id: 6,
      name: 'Train/Test Contamination',
      findingType: 'train_test_contamination',
      requested: hasSplit,
      skipped: noSplit,
      requirement: 'Select a split column to run this detector.'
    },
    {
      id: 7,
      name: 'Distribution Analysis',
      requested: false,
      skipped: true,
      requirement: 'No distribution-analysis detector is called by this endpoint.'
    },
    {
      id: 8,
      name: 'Report Generation',
      requested: false,
      skipped: true,
      requirement: 'This endpoint does not generate a report.'
    }
  ];

  return detectorStages.map((stage) => {
    let status: DetectorStageStatus;
    if (stage.skipped || (stage.id === 5 && randomizedTemporalHoldout)) {
      status = 'skipped';
    } else if (stage.needsConfiguration) {
      status = 'needs_configuration';
    } else if (!stage.requested) {
      status = 'not_run';
    } else if (execution === 'running') {
      status = 'running';
    } else if (execution === 'failed') {
      status = 'failed';
    } else if (execution === 'completed') {
      status = 'completed';
    } else {
      status = 'not_run';
    }

    const findingsCount =
      status === 'completed' && stage.findingType
        ? typeCounts[stage.findingType] ?? 0
        : undefined;

    return {
      id: stage.id,
      name: stage.name,
      status,
      ...(findingsCount !== undefined ? { findingsCount } : {}),
      description:
        status === 'completed'
          ? `${stage.requirement} The backend request completed successfully.`
          : stage.skipped && noSplit
            ? `${stage.requirement} Not evaluated because no split strategy was selected.`
            : stage.id === 5 && randomizedTemporalHoldout
              ? 'Temporal range ordering is not interpreted as leakage for a randomized-holdout objective.'
            : stage.requirement
    };
  });
}

export async function runDatasetAnalysis(
  datasetId: string,
  optionsOrProgress: LeakageAnalysisOptions | ((stageIndex: number, stageName: string) => void) = {},
  onProgress?: (stageIndex: number, stageName: string) => void
): Promise<AnalysisResult> {
  // Retain compatibility with the previous callback-as-second-argument form.
  const options = typeof optionsOrProgress === 'function' ? {} : optionsOrProgress;
  const reportProgress = typeof optionsOrProgress === 'function' ? optionsOrProgress : onProgress;
  const url = new URL(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/analyze/leakage`,
    typeof window === 'undefined' ? 'http://localhost' : window.location.origin
  );
  // Legacy requests cannot provide split-dependent columns without a split.
  // Explicit No Split requests can still persist user-confirmed entity/time
  // configuration while the backend correctly marks those detectors skipped.
  if (options.splitColumn) url.searchParams.set('split_column', options.splitColumn);
  if (options.splitStrategy) url.searchParams.set('split_strategy', options.splitStrategy);
  if (options.splitOperationId) url.searchParams.set('split_operation_id', options.splitOperationId);
  if (options.configurationConfirmed) {
    url.searchParams.set('configuration_confirmed', 'true');
  }
  if (options.targetColumn) url.searchParams.set('target_column', options.targetColumn);
  options.contaminationKeyColumns?.forEach((column) => {
    url.searchParams.append('contamination_key_columns', column);
  });
  const hasResolvedSplit = Boolean(
    options.splitColumn
    || (options.splitStrategy === 'generated' && options.splitOperationId)
  );
  const entityColumns = options.entityColumns?.length
    ? options.entityColumns
    : options.entityColumn ? [options.entityColumn] : [];
  const canPersistSplitDependentConfiguration =
    hasResolvedSplit || options.splitStrategy === 'none';
  if (entityColumns.length > 1 && canPersistSplitDependentConfiguration) {
    entityColumns.forEach((column) => url.searchParams.append('entity_columns', column));
  } else if (entityColumns.length === 1 && canPersistSplitDependentConfiguration) {
    url.searchParams.set('entity_column', entityColumns[0]);
  }
  if (options.timeColumn && canPersistSplitDependentConfiguration) {
    url.searchParams.set('time_column', options.timeColumn);
  }
  if (options.timeColumn && options.temporalObjective) {
    url.searchParams.set('temporal_objective', options.temporalObjective);
  }
  const requestUrl = url.origin === 'http://localhost'
    ? `${url.pathname}${url.search}`
    : url.toString();

  const response = await apiFetch(requestUrl, { method: 'POST' });
  if (!response.ok) {
    let detail = '';
    try {
      const errorBody: unknown = await response.json();
      if (isRecord(errorBody) && typeof errorBody.detail === 'string') {
        detail = `: ${errorBody.detail}`;
      }
    } catch {
      // Keep the HTTP status as the useful fallback when the body is not JSON.
    }
    throw new Error(`Leakage analysis failed (${response.status})${detail}`);
  }

  const data: unknown = await response.json();
  if (!isRecord(data) || !Array.isArray(data.findings)) {
    throw new Error('Invalid leakage analysis response: expected a findings array');
  }

  const findings = data.findings.map(mapPersistedFinding);
  const typeCounts: Record<string, number> = {};
  for (const finding of findings) {
    typeCounts[finding.findingType] = (typeCounts[finding.findingType] ?? 0) + 1;
  }

  const responseStrategy =
    data.split_strategy === 'existing' ||
    data.split_strategy === 'generated' ||
    data.split_strategy === 'none'
      ? data.split_strategy
      : options.splitStrategy ?? (options.splitColumn ? 'existing' : 'none');
  const resolvedOptions = { ...options, splitStrategy: responseStrategy };
  const stages = buildAnalysisStages(typeCounts, resolvedOptions, 'completed');
  for (const [index, stage] of stages.entries()) {
    if (stage.status === 'completed') reportProgress?.(index, stage.name);
  }

  const splitConfiguration = isRecord(data.split_configuration)
    ? data.split_configuration
    : {};
  const skippedDetectors = Array.isArray(data.skipped_detectors)
    ? data.skipped_detectors.filter((item): item is string => typeof item === 'string')
    : [];
  const analysisConfiguration = isRecord(data.analysis_configuration)
    ? data.analysis_configuration
    : {};
  const detectorApplicability = isRecord(data.detector_applicability)
    ? data.detector_applicability
    : {};

  return {
    id: `ans-${Date.now().toString(36)}`,
    datasetId,
    timestamp: new Date().toISOString(),
    stages,
    findings,
    summary: {
      totalFindings: findings.length,
      duplicateFindings: typeCounts.exact_duplicate ?? 0,
    },
    splitStrategy: responseStrategy,
    splitConfiguration,
    skippedDetectors,
    splitExplanation:
      typeof data.split_explanation === 'string' ? data.split_explanation : null,
    analysisConfiguration,
    detectorApplicability,
  };
}

export async function generateDatasetSplit(
  datasetId: string,
  configuration: { testRatio: number; randomSeed: number }
): Promise<SplitGenerationOperation> {
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/split-strategies/generate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        test_ratio: configuration.testRatio,
        random_seed: configuration.randomSeed,
      }),
    }
  );
  if (!response.ok) {
    let detail = '';
    try {
      const body: unknown = await response.json();
      if (isRecord(body) && typeof body.detail === 'string') detail = `: ${body.detail}`;
    } catch {
      // Use HTTP status when the error response is not JSON.
    }
    throw new Error(`Split generation failed (${response.status})${detail}`);
  }
  const data: unknown = await response.json();
  if (!isRecord(data) || typeof data.id !== 'string' || typeof data.output_filename !== 'string') {
    throw new Error('Invalid split generation response');
  }
  return toCamelCase(data) as SplitGenerationOperation;
}

// ==========================================
// REMAINING FUNCTIONS (UNCHANGED)
// ==========================================

export async function getCategoryOverviews(
  datasetId: string
): Promise<FindingCategorySummary[]> {
  return summarizeFindings(await getFindings(datasetId));
}

export async function getFindings(datasetId: string): Promise<PersistedFinding[]> {
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/findings`
  );
  if (!response.ok) {
    throw new Error(`Failed to fetch findings: ${response.status}`);
  }

  const data: unknown = await response.json();
  if (!Array.isArray(data)) {
    throw new Error('Invalid findings response: expected an array');
  }
  return data.map(mapPersistedFinding);
}

export async function getFindingsPage(
  datasetId: string,
  filters: FindingPageFilters = {}
): Promise<DatasetFindingPage> {
  const query = new URLSearchParams();
  if (filters.skip !== undefined) query.set('skip', String(filters.skip));
  if (filters.limit !== undefined) query.set('limit', String(filters.limit));
  if (filters.search?.trim()) query.set('search', filters.search.trim());
  if (filters.findingType) query.set('finding_type', filters.findingType);
  if (filters.severity) query.set('severity', filters.severity);
  if (filters.status) query.set('status', filters.status);

  const suffix = query.size ? `?${query.toString()}` : '';
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/findings/page${suffix}`
  );
  if (!response.ok) {
    throw new Error(`Failed to fetch findings page: ${response.status}`);
  }
  const raw: unknown = await response.json();
  if (!isRecord(raw) || !Array.isArray(raw.items)) {
    throw new Error('Invalid findings page response');
  }
  const mapCounts = (value: unknown): DatasetFindingPage['datasetSummary'] => {
    if (!isRecord(value)) throw new Error('Invalid findings summary response');
    const statusCounts = value.status_counts;
    const detectorCounts = value.detector_counts;
    if (!isRecord(statusCounts) || !isRecord(detectorCounts)) {
      throw new Error('Invalid findings summary count maps');
    }
    const requiredCount = (field: string): number => {
      const count = value[field];
      if (typeof count !== 'number' || !Number.isFinite(count) || count < 0) {
        throw new Error(`Invalid findings summary field: ${field}`);
      }
      return count;
    };
    const countMap = (source: Record<string, unknown>) =>
      Object.fromEntries(
        Object.entries(source).filter((entry): entry is [string, number] =>
          typeof entry[1] === 'number' && Number.isFinite(entry[1]) && entry[1] >= 0
        )
      );
    return {
      total: requiredCount('total'),
      open: requiredCount('open'),
      resolved: requiredCount('resolved'),
      low: requiredCount('low'),
      medium: requiredCount('medium'),
      high: requiredCount('high'),
      otherSeverity: requiredCount('other_severity'),
      statusCounts: countMap(statusCounts),
      detectorCounts: countMap(detectorCounts),
    };
  };
  const datasetSummary = mapCounts(raw.dataset_summary);
  return {
    items: raw.items.map(mapPersistedFinding),
    total: typeof raw.total === 'number' ? raw.total : 0,
    skip: typeof raw.skip === 'number' ? raw.skip : 0,
    limit: typeof raw.limit === 'number' ? raw.limit : 25,
    datasetSummary,
    matchingSummary: mapCounts(raw.matching_summary),
    ...(isRecord(raw.detector_summary)
      ? { detectorSummary: mapCounts(raw.detector_summary) }
      : {}),
  };
}

export async function getColumnRecommendations(
  datasetId: string
): Promise<ColumnRecommendationsResponse> {
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/column-recommendations`
  );
  if (!response.ok) {
    throw await readApiError(response, 'Could not load column recommendations');
  }
  const raw: unknown = await response.json();
  if (!isRecord(raw) || !isRecord(raw.roles)) {
    throw new Error('Invalid column recommendations response');
  }
  const mapped = toCamelCase(raw) as ColumnRecommendationsResponse;
  const requiredRoles = ['target', 'entity', 'split', 'timestamp'] as const;
  if (requiredRoles.some((role) => !isRecord(mapped.roles[role]))) {
    throw new Error('Column recommendations response is missing a detector role');
  }
  return mapped;
}

export async function getFindingById(findingId: string): Promise<PersistedFinding | null> {
  const response = await apiFetch(
    `${getApiBaseUrl()}/findings/${encodeURIComponent(findingId)}`
  );
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Failed to fetch finding: ${response.status}`);
  }

  return mapPersistedFinding(await response.json());
}

// ==========================================
// REPAIR & QUARANTINE OPERATIONS
// ==========================================

function requiredOperationString(
  value: Record<string, unknown>,
  keys: string[],
  fieldLabel: string
): string {
  for (const key of keys) {
    if (typeof value[key] === 'string') {
      return value[key] as string;
    }
  }
  throw new Error(`Invalid operation response: expected "${fieldLabel}" to be a string`);
}

function optionalOperationValue(
  value: Record<string, unknown>,
  keys: string[],
  fieldLabel: string,
  isValid: (candidate: unknown) => boolean
): unknown {
  for (const key of keys) {
    if (key in value) {
      const candidate = value[key];
      if (!isValid(candidate)) {
        throw new Error(`Invalid operation response: "${fieldLabel}" has an unexpected value`);
      }
      return candidate;
    }
  }
  return undefined;
}

function mapCombinedRepairMetadata(value: unknown): CombinedRepairMetadata | null {
  if (value === null) return null;
  if (!isRecord(value)) {
    throw new Error('Invalid operation response: operation_metadata must be an object or null');
  }

  const stringArray = (candidate: unknown, field: string): string[] => {
    if (!Array.isArray(candidate) || !candidate.every((item) => typeof item === 'string')) {
      throw new Error(`Invalid operation response: operation_metadata.${field} must be a string array`);
    }
    return candidate;
  };
  const count = (candidate: unknown, field: string): number => {
    if (typeof candidate !== 'number' || !Number.isInteger(candidate) || candidate < 0) {
      throw new Error(`Invalid operation response: operation_metadata.${field} must be a non-negative integer`);
    }
    return candidate;
  };
  const optionalStringArray = (field: string): string[] | undefined => {
    if (value[field] === undefined || value[field] === null) return undefined;
    return stringArray(value[field], field);
  };
  const optionalCount = (field: string): number | undefined => {
    if (value[field] === undefined || value[field] === null) return undefined;
    return count(value[field], field);
  };
  const rawSkippedFindings = Array.isArray(value.skipped_findings)
    ? value.skipped_findings
    : [];
  const skippedFindings = rawSkippedFindings.map((item) => {
    if (
      !isRecord(item) ||
      typeof item.finding_id !== 'string' ||
      typeof item.reason !== 'string'
    ) {
      throw new Error('Invalid operation response: skipped finding metadata is malformed');
    }
    return { findingId: item.finding_id, reason: item.reason };
  });
  const selectedFindingIds = optionalStringArray('selected_finding_ids');
  const appliedFindingIds = optionalStringArray('applied_finding_ids');
  const originalRowCount = optionalCount('original_row_count');
  const finalRowCount = optionalCount('final_row_count');
  const duplicateRowsRemoved = optionalCount('duplicate_rows_removed');

  return {
    ...(selectedFindingIds !== undefined ? { selectedFindingIds } : {}),
    ...(appliedFindingIds !== undefined ? { appliedFindingIds } : {}),
    skippedFindings,
    skippedFindingsRecorded:
      typeof value.skipped_findings_recorded === 'boolean'
        ? value.skipped_findings_recorded
        : Array.isArray(value.skipped_findings),
    ...(originalRowCount !== undefined ? { originalRowCount } : {}),
    ...(finalRowCount !== undefined ? { finalRowCount } : {}),
    ...(duplicateRowsRemoved !== undefined ? { duplicateRowsRemoved } : {}),
    ...(Array.isArray(value.evidence_reference_finding_ids)
      ? { evidenceReferenceFindingIds: stringArray(value.evidence_reference_finding_ids, 'evidence_reference_finding_ids') }
      : {}),
    ...(typeof value.repair_strategy === 'string'
      ? { repairStrategy: value.repair_strategy }
      : {}),
    ...(typeof value.verification_status === 'string'
      ? { verificationStatus: value.verification_status }
      : {}),
    ...(isRecord(value.verification)
      ? { verification: value.verification }
      : {}),
  };
}

export function mapDatasetOperationRecord(value: unknown): DatasetOperationRecord {
  if (!isRecord(value)) {
    throw new Error('Invalid operation response: expected an object');
  }

  const operationType = requiredOperationString(value, ['operation_type'], 'operation_type');
  const idKeys =
    operationType === 'repair'
      ? ['repair_id', 'id', 'quarantine_id']
      : operationType === 'quarantine'
        ? ['quarantine_id', 'id', 'repair_id']
        : ['id', 'repair_id', 'quarantine_id'];
  const record: DatasetOperationRecord = {
    id: requiredOperationString(value, idKeys, 'id'),
    datasetId: requiredOperationString(value, ['dataset_id'], 'dataset_id'),
    operationType,
    status: requiredOperationString(value, ['status'], 'status'),
  };

  const optionalFields: Array<[keyof DatasetOperationRecord, string[], string, (candidate: unknown) => boolean]> = [
    ['findingId', ['finding_id'], 'finding_id', (candidate) => candidate === null || typeof candidate === 'string'],
    ['inputFile', ['input_file'], 'input_file', (candidate) => candidate === null || typeof candidate === 'string'],
    ['inputFileSha256', ['input_file_sha256'], 'input_file_sha256', (candidate) => candidate === null || typeof candidate === 'string'],
    ['outputFilename', ['output_filename', 'output_file'], 'output_filename', (candidate) => candidate === null || typeof candidate === 'string'],
    ['outputFileSha256', ['output_file_sha256'], 'output_file_sha256', (candidate) => candidate === null || typeof candidate === 'string'],
    ['affectedRows', ['affected_rows'], 'affected_rows', (candidate) => candidate === null || (typeof candidate === 'number' && Number.isFinite(candidate))],
    ['createdAt', ['created_at'], 'created_at', (candidate) => candidate === null || typeof candidate === 'string'],
    ['completedAt', ['completed_at'], 'completed_at', (candidate) => candidate === null || typeof candidate === 'string'],
  ];

  for (const [field, keys, fieldLabel, isValid] of optionalFields) {
    const mappedValue = optionalOperationValue(value, keys, fieldLabel, isValid);
    if (mappedValue !== undefined) {
      // The field list above validates each value against its corresponding interface property.
      (record as unknown as Record<string, unknown>)[field] = mappedValue;
    }
  }

  if ('operation_metadata' in value) {
    record.operationMetadata = mapCombinedRepairMetadata(value.operation_metadata);
  }

  return record;
}

export async function getDatasetOperationHistory(
  datasetId: string
): Promise<DatasetOperationRecord[]> {
  // This existing route returns RepairRecord history for the dataset, including
  // both repair and quarantine operation types.
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/repairs`
  );
  if (!response.ok) {
    throw new Error(`Failed to fetch operation history: ${response.status}`);
  }

  const data: unknown = await response.json();
  if (!Array.isArray(data)) {
    throw new Error('Invalid operation history response: expected an array');
  }
  return data.map(mapDatasetOperationRecord);
}

function mapRemediationPlanRecord(value: unknown): RemediationPlanRecord {
  if (!isRecord(value)) throw new Error('Invalid remediation-plan response');
  const mapped = toCamelCase(value) as Partial<RemediationPlanRecord>;
  if (
    typeof mapped.id !== 'string' ||
    typeof mapped.datasetId !== 'string' ||
    typeof mapped.operationType !== 'string' ||
    typeof mapped.status !== 'string' ||
    !isRecord(mapped.plan) ||
    typeof mapped.plan.planId !== 'string' ||
    typeof mapped.plan.previewDigest !== 'string' ||
    typeof mapped.plan.originalFileSha256 !== 'string' ||
    typeof mapped.plan.originalRowCount !== 'number' ||
    typeof mapped.plan.expectedFinalRowCount !== 'number' ||
    !Array.isArray(mapped.plan.actions) ||
    !Array.isArray(mapped.plan.affectedSourceRowPositionsPreview) ||
    !Array.isArray(mapped.plan.selectedFindingIdsPreview) ||
    !Array.isArray(mapped.plan.skippedFindings)
  ) {
    throw new Error('Invalid remediation-plan response fields');
  }
  return mapped as RemediationPlanRecord;
}

export async function previewRemediationPlan(
  datasetId: string,
  actions: RemediationActionRequest[]
): Promise<RemediationPlanRecord> {
  if (!actions.length) throw new Error('Select at least one remediation action.');
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/remediation-plans/preview`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actions }),
    }
  );
  if (!response.ok) {
    throw await readApiError(response, 'Could not create remediation preview');
  }
  return mapRemediationPlanRecord(await response.json());
}

export async function executeRemediationPlan(
  datasetId: string,
  planId: string,
  previewToken: string,
  confirmed: boolean
): Promise<RemediationPlanRecord> {
  if (!previewToken.trim() || confirmed !== true) {
    throw new Error('A current preview token and explicit confirmation are required.');
  }
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/remediation-plans/${encodeURIComponent(planId)}/execute`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preview_token: previewToken, confirmed }),
    }
  );
  if (!response.ok) {
    throw await readApiError(response, 'Could not execute confirmed remediation');
  }
  return mapRemediationPlanRecord(await response.json());
}

export async function cancelRemediationPlan(
  datasetId: string,
  planId: string,
  reason?: string
): Promise<RemediationPlanRecord> {
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/remediation-plans/${encodeURIComponent(planId)}/cancel`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason ?? null }),
    }
  );
  if (!response.ok) {
    throw await readApiError(response, 'Could not cancel remediation preview');
  }
  return mapRemediationPlanRecord(await response.json());
}

export async function getRemediationPlans(
  datasetId: string,
  options: { skip?: number; limit?: number } = {}
): Promise<RemediationPlanPage> {
  const query = new URLSearchParams();
  if (options.skip !== undefined) query.set('skip', String(options.skip));
  if (options.limit !== undefined) query.set('limit', String(options.limit));
  const suffix = query.size ? `?${query.toString()}` : '';
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/remediation-plans${suffix}`
  );
  if (!response.ok) throw await readApiError(response, 'Could not load remediation history');
  const raw: unknown = await response.json();
  if (!isRecord(raw) || !Array.isArray(raw.items)) {
    throw new Error('Invalid remediation-plan history response');
  }
  const mapped = toCamelCase(raw) as RemediationPlanPage;
  return { ...mapped, items: raw.items.map(mapRemediationPlanRecord) };
}

export async function previewTrainOnlyImputation(
  datasetId: string,
  request: ImputationRequest
): Promise<ImputationPreview> {
  if (!request.splitColumn.trim() || !request.trainingPartition.trim() || request.columns.length === 0) {
    throw new Error('Choose a validated training split and at least one missing-value strategy.');
  }
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/preprocessing/imputation/preview`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        split_column: request.splitColumn,
        training_partition: request.trainingPartition,
        ...(request.splitOperationId ? { split_operation_id: request.splitOperationId } : {}),
        columns: request.columns.map((item) => ({
          column: item.column,
          method: item.method,
          ...(item.constantValue !== undefined ? { constant_value: item.constantValue } : {}),
        })),
      }),
    }
  );
  if (!response.ok) throw await readApiError(response, 'Could not preview train-only imputation');
  const raw: unknown = await response.json();
  if (!isRecord(raw)) throw new Error('Invalid train-only imputation preview response');
  const mapped = toCamelCase(raw) as ImputationPreview;
  if (
    typeof mapped.previewToken !== 'string' ||
    typeof mapped.sourceFileSha256 !== 'string' ||
    typeof mapped.splitColumn !== 'string' ||
    typeof mapped.trainingPartition !== 'string' ||
    !Array.isArray(mapped.strategies) ||
    !isRecord(mapped.missingCountsBefore) ||
    !isRecord(mapped.missingCountsAfter) ||
    typeof mapped.expectedRowCount !== 'number' ||
    typeof mapped.expectedColumnCount !== 'number' ||
    !Array.isArray(mapped.protectedColumns)
  ) {
    throw new Error('Invalid train-only imputation preview fields');
  }
  return mapped;
}

export async function executeTrainOnlyImputation(
  datasetId: string,
  request: ImputationRequest,
  previewToken: string,
  confirmed: boolean
): Promise<ImputationOperation> {
  if (!previewToken.trim() || confirmed !== true) {
    throw new Error('A current imputation preview and explicit confirmation are required.');
  }
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/preprocessing/imputation/execute`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        split_column: request.splitColumn,
        training_partition: request.trainingPartition,
        ...(request.splitOperationId ? { split_operation_id: request.splitOperationId } : {}),
        columns: request.columns.map((item) => ({
          column: item.column,
          method: item.method,
          ...(item.constantValue !== undefined ? { constant_value: item.constantValue } : {}),
        })),
        preview_token: previewToken,
        confirmed,
      }),
    }
  );
  if (!response.ok) throw await readApiError(response, 'Could not execute confirmed imputation');
  const raw: unknown = await response.json();
  if (!isRecord(raw)) throw new Error('Invalid train-only imputation operation response');
  const mapped = toCamelCase(raw) as ImputationOperation;
  if (
    typeof mapped.id !== 'string' ||
    typeof mapped.datasetId !== 'string' ||
    mapped.operationType !== 'train_only_imputation' ||
    typeof mapped.status !== 'string' ||
    !Array.isArray(mapped.affectedColumns) ||
    !isRecord(mapped.operationMetadata)
  ) {
    throw new Error('Invalid train-only imputation operation fields');
  }
  return mapped;
}

export async function previewCombinedCleanedDataset(
  datasetId: string,
  selectedFindingIds: string[]
): Promise<CombinedRepairPreview> {
  if (selectedFindingIds.length === 0) {
    throw new Error('Select at least one eligible exact-duplicate finding.');
  }
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/repairs/combined/preview`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selected_finding_ids: selectedFindingIds }),
    }
  );
  if (!response.ok) {
    let detail = '';
    try {
      const body: unknown = await response.json();
      if (isRecord(body) && typeof body.detail === 'string') detail = `: ${body.detail}`;
    } catch {
      // Use the HTTP status if the response is not JSON.
    }
    throw new Error(`Failed to preview combined cleaning (${response.status})${detail}`);
  }

  const body: unknown = await response.json();
  if (
    !isRecord(body) ||
    typeof body.dataset_id !== 'string' ||
    typeof body.input_file_sha256 !== 'string' ||
    !Array.isArray(body.selected_finding_ids) ||
    !Array.isArray(body.applied_finding_ids) ||
    !Array.isArray(body.skipped_findings) ||
    !['preview', 'not_eligible'].includes(String(body.status)) ||
    !(body.preview_token === null || typeof body.preview_token === 'string')
  ) {
    throw new Error('Invalid combined-cleaning preview response');
  }
  const count = (value: unknown, name: string): number => {
    if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
      throw new Error(`Invalid combined-cleaning preview: ${name} must be a non-negative integer`);
    }
    return value;
  };
  const parseStringArray = (value: unknown, name: string): string[] => {
    if (!Array.isArray(value) || !value.every((item) => typeof item === 'string')) {
      throw new Error(`Invalid combined-cleaning preview: ${name} must be a string array`);
    }
    return value;
  };
  const parseOptionalRowIndices = (): number[] | undefined => {
    if (body.affected_row_indices_preview === undefined) return undefined;
    if (
      !Array.isArray(body.affected_row_indices_preview) ||
      !body.affected_row_indices_preview.every(
        (item) => typeof item === 'number' && Number.isInteger(item) && item >= 0
      )
    ) {
      throw new Error('Invalid combined-cleaning preview: affected row references are malformed');
    }
    return body.affected_row_indices_preview;
  };
  const parseOptionalCount = (field: string): number | undefined => {
    if (body[field] === undefined) return undefined;
    return count(body[field], field);
  };
  const parseOptionalBoolean = (field: string): boolean | undefined => {
    if (body[field] === undefined) return undefined;
    if (typeof body[field] !== 'boolean') {
      throw new Error(`Invalid combined-cleaning preview: ${field} must be a boolean`);
    }
    return body[field];
  };
  const parseOptionalDigest = (field: string): string | undefined => {
    if (body[field] === undefined) return undefined;
    if (typeof body[field] !== 'string' || !/^[a-f0-9]{64}$/i.test(body[field])) {
      throw new Error(`Invalid combined-cleaning preview: ${field} must be a SHA-256 digest`);
    }
    return body[field];
  };
  const skippedFindings = body.skipped_findings.map((item) => {
    if (!isRecord(item) || typeof item.finding_id !== 'string' || typeof item.reason !== 'string') {
      throw new Error('Invalid combined-cleaning preview: skipped finding is malformed');
    }
    return { findingId: item.finding_id, reason: item.reason };
  });
  const affectedRowIndicesPreview = parseOptionalRowIndices();
  const affectedRowIndicesCount = parseOptionalCount('affected_row_indices_count');
  const affectedRowIndicesTruncated = parseOptionalBoolean('affected_row_indices_truncated');
  const affectedRowIndicesSha256 = parseOptionalDigest('affected_row_indices_sha256');
  return {
    datasetId: body.dataset_id,
    inputFileSha256: body.input_file_sha256,
    selectedFindingIds: parseStringArray(body.selected_finding_ids, 'selected_finding_ids'),
    appliedFindingIds: parseStringArray(body.applied_finding_ids, 'applied_finding_ids'),
    skippedFindings,
    originalRowCount: count(body.original_row_count, 'original_row_count'),
    finalRowCount: count(body.final_row_count, 'final_row_count'),
    duplicateRowsRemoved: count(body.duplicate_rows_removed, 'duplicate_rows_removed'),
    ...(affectedRowIndicesPreview !== undefined ? { affectedRowIndicesPreview } : {}),
    ...(affectedRowIndicesCount !== undefined ? { affectedRowIndicesCount } : {}),
    ...(affectedRowIndicesTruncated !== undefined ? { affectedRowIndicesTruncated } : {}),
    ...(affectedRowIndicesSha256 !== undefined ? { affectedRowIndicesSha256 } : {}),
    operationType: typeof body.operation_type === 'string' ? body.operation_type : 'combined_repair_preview',
    status: body.status as CombinedRepairPreview['status'],
    previewToken: body.preview_token,
    explanation: typeof body.explanation === 'string' ? body.explanation : 'Preview explanation unavailable.',
  };
}

export async function generateCombinedCleanedDataset(
  datasetId: string,
  selectedFindingIds: string[],
  previewToken: string,
  confirmed: boolean
): Promise<DatasetOperationRecord> {
  if (selectedFindingIds.length === 0) {
    throw new Error('Select at least one eligible exact-duplicate finding.');
  }
  if (!previewToken.trim() || confirmed !== true) {
    throw new Error('A current preview token and explicit confirmation are required.');
  }

  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/repairs/combined`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        selected_finding_ids: selectedFindingIds,
        preview_token: previewToken,
        confirmed,
      }),
    }
  );
  if (!response.ok) {
    let detail = '';
    try {
      const errorBody: unknown = await response.json();
      if (isRecord(errorBody) && typeof errorBody.detail === 'string') {
        detail = `: ${errorBody.detail}`;
      } else if (isRecord(errorBody) && isRecord(errorBody.detail)) {
        const errorDetail = errorBody.detail;
        const message = typeof errorDetail.message === 'string' ? errorDetail.message : '';
        const skipped = Array.isArray(errorDetail.skipped_findings)
          ? errorDetail.skipped_findings
              .filter(
                (item): item is Record<string, unknown> =>
                  isRecord(item) &&
                  typeof item.finding_id === 'string' &&
                  typeof item.reason === 'string'
              )
              .map((item) => `${item.finding_id}: ${item.reason}`)
          : [];
        detail = [
          message,
          skipped.length > 0 ? `Skipped findings — ${skipped.join('; ')}` : '',
        ]
          .filter(Boolean)
          .map((part) => `: ${part}`)
          .join('');
      }
    } catch {
      // Retain the status code when the error body is not JSON.
    }
    throw new Error(`Failed to generate combined cleaned dataset (${response.status})${detail}`);
  }
  return mapDatasetOperationRecord(await response.json());
}

export interface OperationOutputDownload {
  blob: Blob;
  filename: string;
}

function getSafeDownloadFilename(
  response: Response,
  allowedExtensions: readonly string[] = ['csv', 'xlsx']
): string {
  const disposition = response.headers.get('content-disposition');
  if (!disposition) {
    throw new Error('Download response did not include a filename');
  }

  const encodedFilename = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(disposition);
  const plainFilename = /filename\s*=\s*(?:"([^"]+)"|([^;]+))/i.exec(disposition);
  const rawFilename = encodedFilename?.[1] ?? plainFilename?.[1] ?? plainFilename?.[2];
  if (!rawFilename) {
    throw new Error('Download response did not include a valid filename');
  }

  let filename = rawFilename.trim().replace(/^"|"$/g, '');
  if (encodedFilename) {
    try {
      filename = decodeURIComponent(filename);
    } catch {
      throw new Error('Download response included an invalid filename');
    }
  }

  const extensionPattern = allowedExtensions.join('|');
  if (
    filename.includes('..') ||
    filename.includes('/') ||
    filename.includes('\\') ||
    !new RegExp(`^[A-Za-z0-9][A-Za-z0-9._-]*\\.(?:${extensionPattern})$`, 'i').test(filename)
  ) {
    throw new Error('Download response included an unsafe filename');
  }
  return filename;
}

export async function downloadOperationOutput(
  operationId: string
): Promise<OperationOutputDownload> {
  const response = await apiFetch(
    `${getApiBaseUrl()}/operations/${encodeURIComponent(operationId)}/download`
  );
  if (!response.ok) {
    let detail = '';
    try {
      const errorBody: unknown = await response.json();
      if (isRecord(errorBody) && typeof errorBody.detail === 'string') {
        detail = `: ${errorBody.detail}`;
      }
    } catch {
      // Keep the HTTP status as the useful fallback for non-JSON error bodies.
    }
    throw new Error(`Failed to download operation output (${response.status})${detail}`);
  }

  const filename = getSafeDownloadFilename(response);
  return {
    blob: await response.blob(),
    filename,
  };
}

export type RemediationArtifactType = 'dataset' | 'report' | 'manifest' | 'quarantine';

export async function downloadRemediationArtifact(
  operationId: string,
  artifact: RemediationArtifactType
): Promise<OperationOutputDownload> {
  const response = await apiFetch(
    `${getApiBaseUrl()}/operations/${encodeURIComponent(operationId)}/remediation-artifacts/${artifact}`
  );
  if (!response.ok) {
    throw await readApiError(response, 'Could not download remediation artifact');
  }
  const filename = getSafeDownloadFilename(response, ['csv', 'json']);
  if ((artifact === 'manifest') !== filename.toLowerCase().endsWith('.json')) {
    throw new Error('Remediation artifact response filename does not match its type');
  }
  return { blob: await response.blob(), filename };
}

async function createFindingOperation(
  findingId: string,
  operationType: FindingOperationType
): Promise<DatasetOperationRecord> {
  const response = await apiFetch(
    `${getApiBaseUrl()}/findings/${encodeURIComponent(findingId)}/${operationType}`,
    { method: 'POST' }
  );
  if (!response.ok) {
    throw new Error(`Failed to ${operationType} finding: ${response.status}`);
  }
  return mapDatasetOperationRecord(await response.json());
}

export function repairFinding(findingId: string): Promise<DatasetOperationRecord> {
  return createFindingOperation(findingId, 'repair');
}

export function quarantineFinding(findingId: string): Promise<DatasetOperationRecord> {
  return createFindingOperation(findingId, 'quarantine');
}

// ==========================================
// IMPACT ANALYSIS
// ==========================================

export async function getImpactAnalysis(datasetId: string): Promise<ImpactAnalysis> {
  const response = await apiFetch(`${getApiBaseUrl()}/impact-metrics/${encodeURIComponent(datasetId)}`);
  if (!response.ok) throw await readApiError(response, 'Could not load impact metrics');
  const payload = await response.json() as {
    dataset_id: string;
    metrics: Record<string, number>;
  };
  const metrics = [
    ['Findings', payload.metrics.findings_total ?? 0],
    ['Open findings', payload.metrics.findings_open ?? 0],
    ['High severity', payload.metrics.findings_high_severity ?? 0],
    ['Operations', payload.metrics.operations_total ?? 0],
    ['Affected rows', payload.metrics.affected_rows ?? 0],
  ].map(([metric, value]) => ({
    metric: String(metric),
    contaminated: Number(value),
    corrected: Number(value),
    difference: 0,
    percentageInflation: 0,
  }));
  return {
    datasetId: payload.dataset_id,
    modelName: 'No model evaluation configured',
    taskType: 'Persisted dataset impact metrics',
    metrics,
    evaluationInflationSummary: {
      accuracyDifference: 0,
      f1Difference: 0,
      rocAucDifference: 0,
      statement: 'Model performance was not evaluated by this workflow.',
      nuance: 'These metrics describe persisted findings and operations only; they do not claim model accuracy or causal impact.',
    },
  };
}

// ==========================================
// MODEL INTEGRITY
// ==========================================

export async function getModels(): Promise<Model[]> {
  const response = await apiFetch(`${getApiBaseUrl()}/model-artifacts`);
  if (!response.ok) throw await readApiError(response, 'Could not load model artifacts');
  const artifacts = await response.json() as Array<{
    id: string; name: string; version?: string | null; original_filename: string;
    sha256: string; size_bytes: number; created_at?: string;
  }>;
  return artifacts.map((artifact) => ({
    id: artifact.id,
    name: artifact.name,
    version: artifact.version ?? 'unversioned',
    format: 'ONNX',
    sha256: artifact.sha256,
    status: 'Not Available',
    lastVerified: artifact.created_at ?? 'Not verified',
    architecture: 'Metadata only',
    parameters: `${artifact.size_bytes} bytes`,
    framework: artifact.original_filename,
    uploadedAt: artifact.created_at ?? 'Unavailable',
    referenceHash: artifact.sha256,
    fingerprintMatch: false,
    behaviorDriftScore: 0,
    referenceBehaviors: [],
  }));
}

export async function getModelById(id: string): Promise<Model | null> {
  const models = await getModels();
  return models.find((model) => model.id === id) ?? null;
}

export async function verifyModel(modelId: string): Promise<{
  verified: boolean;
  status: Model['status'];
  sha256Match: boolean;
  fingerprintMatch: boolean;
  behaviorScore: number;
  message: string;
}> {
  const response = await apiFetch(`${getApiBaseUrl()}/model-artifacts/${encodeURIComponent(modelId)}/verify`);
  if (!response.ok) throw await readApiError(response, 'Could not verify model artifact');
  const result = await response.json() as { verified: boolean; sha256?: string; reason?: string };
  return {
    verified: result.verified,
    status: result.verified ? 'Verified' : 'Changed',
    sha256Match: result.verified,
    fingerprintMatch: false,
    behaviorScore: 0,
    message: result.verified
      ? 'Artifact SHA-256 matches the persisted trusted hash. No behavioral or inference check was performed.'
      : `Artifact verification failed${result.reason ? `: ${result.reason}` : '.'}`,
  };
}

export async function uploadModelArtifact(
  file: File,
  name: string,
  version?: string,
  metadata?: Record<string, unknown>,
): Promise<Model> {
  const body = new FormData();
  body.append('name', name);
  if (version) body.append('version', version);
  if (metadata) body.append('metadata', JSON.stringify(metadata));
  body.append('file', file);
  const response = await apiFetch(`${getApiBaseUrl()}/model-artifacts`, { method: 'POST', body });
  if (!response.ok) throw await readApiError(response, 'Could not upload model artifact');
  const artifact = await response.json() as { id: string; name: string; version?: string; original_filename: string; sha256: string; size_bytes: number };
  return {
    id: artifact.id, name: artifact.name, version: artifact.version ?? 'unversioned',
    format: 'ONNX', sha256: artifact.sha256, status: 'Not Available',
    lastVerified: 'Not verified', architecture: 'Metadata only',
    parameters: `${artifact.size_bytes} bytes`, framework: artifact.original_filename,
    uploadedAt: 'Just now', referenceHash: artifact.sha256, fingerprintMatch: false,
    behaviorDriftScore: 0, referenceBehaviors: [],
  };
}

export async function downloadModelArtifact(id: string): Promise<void> {
  const response = await apiFetch(`${getApiBaseUrl()}/model-artifacts/${encodeURIComponent(id)}/download`);
  if (!response.ok) throw await readApiError(response, 'Could not download model artifact');
  const url = `${getApiBaseUrl()}/model-artifacts/${encodeURIComponent(id)}/download`;
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.download = response.headers.get('content-disposition')?.match(/filename="([^"]+)"/)?.[1] ?? `${id}.artifact`;
  anchor.click();
  anchor.remove();
}

export async function createProvenanceRecord(datasetId: string, metadata: Record<string, unknown>) {
  const response = await apiFetch(`${getApiBaseUrl()}/provenance`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dataset_id: datasetId, metadata }),
  });
  if (!response.ok) throw await readApiError(response, 'Could not create provenance record');
  return response.json();
}

export async function createDistributionComparison(referenceDatasetId: string, comparisonDatasetId: string) {
  const response = await apiFetch(`${getApiBaseUrl()}/distribution-comparisons`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reference_dataset_id: referenceDatasetId, comparison_dataset_id: comparisonDatasetId }),
  });
  if (!response.ok) throw await readApiError(response, 'Could not compare distributions');
  return response.json();
}

export interface PartitionDistributionResult {
  id: string;
  datasetId: string;
  createdAt: string;
  result: Record<string, unknown>;
}

function mapPartitionDistributionResult(raw: unknown): PartitionDistributionResult {
  if (!isRecord(raw) || !isRecord(raw.result)) {
    throw new Error('Invalid partition distribution response');
  }
  if (
    typeof raw.id !== 'string' ||
    typeof raw.dataset_id !== 'string' ||
    typeof raw.created_at !== 'string'
  ) {
    throw new Error('Invalid partition distribution response fields');
  }
  return {
    id: raw.id,
    datasetId: raw.dataset_id,
    createdAt: raw.created_at,
    // Feature map keys are user-provided column names and must remain verbatim.
    result: raw.result,
  };
}

export async function getPartitionDistributionAnalysis(
  datasetId: string
): Promise<PartitionDistributionResult | null> {
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/distribution-analysis`
  );
  if (response.status === 404) return null;
  if (!response.ok) throw await readApiError(response, 'Could not load partition distribution analysis');
  return mapPartitionDistributionResult(await response.json());
}

export async function createPartitionDistributionAnalysis(
  datasetId: string,
  referencePartition: string,
  comparisonPartition: string
): Promise<PartitionDistributionResult> {
  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/distribution-analysis`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reference_partition: referencePartition,
        comparison_partition: comparisonPartition,
      }),
    }
  );
  if (!response.ok) throw await readApiError(response, 'Could not compare dataset partitions');
  return mapPartitionDistributionResult(await response.json());
}

// ==========================================
// INFERENCE PROVENANCE
// ==========================================

export async function getInferenceRecords(): Promise<InferenceRecord[]> {
  const response = await apiFetch(`${getApiBaseUrl()}/provenance`);
  if (!response.ok) throw await readApiError(response, 'Could not load provenance records');
  const records = await response.json() as Array<{ id: string; dataset_id: string; metadata: Record<string, unknown>; created_at?: string; prediction_status: string }>;
  return records.map((record): InferenceRecord => ({
    id: record.id,
    timestamp: record.created_at ?? 'Unavailable',
    modelId: String(record.metadata.model_id ?? 'not-configured'),
    modelName: 'Provenance metadata only',
    inputHash: String(record.metadata.input_hash ?? 'Not supplied'),
    outputHash: String(record.metadata.output_hash ?? 'Not supplied'),
    configHash: String(record.metadata.config_hash ?? 'Not supplied'),
    nonce: String(record.metadata.nonce ?? 'Not supplied'),
    sequenceNumber: Number(record.metadata.sequence_number ?? 0),
    digitalSignature: String(record.metadata.signature ?? 'Not supplied'),
    verificationStatus: record.prediction_status === 'Tampered' || record.prediction_status === 'Replay Detected'
      ? record.prediction_status
      : 'Metadata persisted',
    prediction: { label: 'No prediction', confidence: null },
    inputMetadata: {
      filename: String(record.metadata.input_filename ?? 'Not supplied'),
      dimensions: 'Not supplied',
      sizeKb: 0,
      preprocessingConfig: String(record.metadata.preprocessing ?? 'Not supplied'),
    },
  }));
}

export async function runInference(_payload: {
  modelId: string;
  imageOrVectorName: string;
  config: string
}): Promise<InferenceRecord> {
  throw new Error(
    'Inference execution is not configured. Create a provenance record with verified metadata instead.'
  );
}

// ==========================================
// DISTRIBUTION SHIFT
// ==========================================

export async function getDistributionShift(): Promise<DistributionShift> {
  const response = await apiFetch(`${getApiBaseUrl()}/distribution-comparisons`);
  if (!response.ok) throw await readApiError(response, 'Could not load distribution comparisons');
  const records = await response.json() as Array<{
    id: string;
    reference_dataset_id: string;
    comparison_dataset_id: string;
    metrics: Record<string, { kind: string; psi?: number; distribution_delta?: number; missing_delta: number }>;
  }>;
  const record = records[0];
  if (!record) throw new Error('No persisted distribution comparison is available yet.');
  const featureShifts = Object.entries(record.metrics).map(([featureName, metric]) => {
    const driftScore = metric.kind === 'numeric' ? metric.psi : metric.distribution_delta;
    if (typeof driftScore !== 'number' || !Number.isFinite(driftScore)) return null;
    return {
      featureName,
      driftScore,
      metricKind: metric.kind === 'numeric' ? 'PSI' as const : 'Distribution delta' as const,
      threshold: metric.kind === 'numeric' ? 0.2 : 0.1,
      status: driftScore >= (metric.kind === 'numeric' ? 0.2 : 0.1) ? 'Shift Detected' as const : 'Nominal' as const,
    };
  }).filter((item): item is NonNullable<typeof item> => item !== null);
  const numericPsi = featureShifts.filter((item) => item.metricKind === 'PSI');
  const psiScore = numericPsi.length
    ? numericPsi.reduce((sum, item) => sum + item.driftScore, 0) / numericPsi.length
    : null;
  return {
    id: record.id,
    referenceDatasetId: record.reference_dataset_id,
    currentDatasetId: record.comparison_dataset_id,
    overallShiftDetected: featureShifts.some((item) => item.status === 'Shift Detected'),
    shiftLevel: featureShifts.some((item) => item.status === 'Shift Detected')
      ? 'Review Required'
      : featureShifts.length
        ? 'No Significant Shift'
        : 'Potential Shift',
    psiScore,
    wassersteinDistance: null,
    oodRate: null,
    classBalanceShift: [],
    featureShifts,
  };
}

// ==========================================
// REPORTS
// ==========================================

export async function getReports(): Promise<AssuranceReport[]> {
  const response = await apiFetch(`${getApiBaseUrl()}/reports`);
  if (!response.ok) throw await readApiError(response, 'Could not load reports');
  const records = await response.json() as Array<{
    id: string; title: string; created_at?: string; dataset_id?: string | null;
    content?: unknown;
  }>;
  return records.map(mapAssuranceReport);
}

function mapAssuranceReport(record: {
  id: string;
  title: string;
  created_at?: string;
  dataset_id?: string | null;
  content?: unknown;
}): AssuranceReport {
  const rawContent =
    record.content && typeof record.content === 'object'
      ? record.content as Record<string, unknown>
      : {};
  const datasets: PersistedReportDataset[] = Array.isArray(rawContent.datasets)
    ? rawContent.datasets
        .filter((value): value is Record<string, unknown> => (
          value !== null && typeof value === 'object' && !Array.isArray(value)
        ))
        .map((dataset) => ({
          id: typeof dataset.id === 'string' ? dataset.id : '',
          name: typeof dataset.name === 'string' ? dataset.name : 'Dataset name unavailable',
          format: typeof dataset.format === 'string' ? dataset.format : 'Format unavailable',
          sha256: typeof dataset.sha256 === 'string' ? dataset.sha256 : null,
        }))
    : [];
  const impactKeys: Array<keyof PersistedReportImpact> = [
    'findings_total',
    'findings_open',
    'findings_high_severity',
    'operations_total',
    'operations_completed',
    'affected_rows',
  ];
  const impact: PersistedReportImpact[] = Array.isArray(rawContent.impact)
    ? rawContent.impact.map((value) => {
        const rawMetrics =
          value && typeof value === 'object' && !Array.isArray(value)
            ? value as Record<string, unknown>
            : {};
        return Object.fromEntries(
          impactKeys.flatMap((key) => (
            typeof rawMetrics[key] === 'number' && Number.isFinite(rawMetrics[key])
              ? [[key, rawMetrics[key] as number]]
              : []
          ))
        ) as PersistedReportImpact;
      })
    : [];
  const persistedContent: PersistedReportContent = { datasets, impact, snapshot: rawContent };
  const firstDataset = datasets[0];
  const datasetName = firstDataset
    ? `${firstDataset.name} (${firstDataset.format})`
    : datasets.length > 1
      ? `${datasets.length} persisted datasets`
      : 'Dataset details unavailable';

  return {
    id: record.id,
    title: record.title,
    datasetId: record.dataset_id ?? firstDataset?.id ?? '',
    datasetName,
    modelId: '',
    modelName: 'No model evaluation configured',
    createdAt: record.created_at ?? 'Unavailable',
    assessmentStatus: 'NOT ASSESSED',
    disposition: 'NOT ASSESSED',
    confidenceScore: null,
    projectDefinedRisk: 'NOT ASSESSED',
    executiveSummary:
      `Persisted snapshot containing ${datasets.length} dataset record(s) and ${impact.length} impact metric record(s). ` +
      'It does not perform model evaluation or assign an assurance rating.',
    findingsCount: { critical: null, high: null, medium: null, low: null },
    persistedContent,
    sections: {
      datasetIntegrity: 'The persisted dataset names, formats, identifiers, and available file hashes are listed below.',
      leakageFindings: 'Finding totals below are persisted counts. Severity breakdowns and full finding evidence are not included in this report snapshot.',
      datasetAnomalies: 'Not assessed by this report generator.',
      modelIntegrity: 'No model-integrity assessment is included.',
      inferenceProvenance: 'No inference or provenance assessment is included.',
      distributionShift: 'No distribution comparison is included in this report snapshot.',
      performanceImpact: 'No model performance evaluation was performed.',
      evidence: 'This report contains dataset metadata and persisted impact counts, not full finding evidence.',
      riskAssessment: 'No risk score or confidence assessment was calculated.',
      limitations: [
        'This snapshot does not execute model evaluation or inference.',
        'Finding severity breakdowns and full finding evidence are not included.',
        'No automated risk score, confidence value, or disposition is assigned.',
      ],
      recommendedDisposition: 'Review the persisted dataset, finding, and operation records; no automated disposition is provided.',
    },
  };
}

export async function getReportById(id: string): Promise<AssuranceReport | null> {
  const response = await apiFetch(`${getApiBaseUrl()}/reports/${encodeURIComponent(id)}`);
  if (response.status === 404) return null;
  if (!response.ok) throw await readApiError(response, 'Could not load report');
  const raw: unknown = await response.json();
  if (!isRecord(raw)) throw new Error('Invalid persisted report response');
  return mapAssuranceReport({
    id: String(raw.id ?? ''),
    title: String(raw.title ?? 'Persisted report'),
    created_at: typeof raw.created_at === 'string' ? raw.created_at : undefined,
    dataset_id: typeof raw.dataset_id === 'string' ? raw.dataset_id : null,
    content: raw.content,
  });
}

export async function generateAssuranceReport(datasetId: string, _modelId: string): Promise<AssuranceReport> {
  const response = await apiFetch(`${getApiBaseUrl()}/reports`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dataset_id: datasetId, title: 'DataLeakGuard persisted report' }),
  });
  if (!response.ok) throw await readApiError(response, 'Could not generate report');
  const created = await response.json() as {
    id: string;
    title: string;
    created_at?: string;
    dataset_id?: string | null;
    content?: unknown;
  };
  return mapAssuranceReport(created);
}

export async function deleteReport(id: string): Promise<boolean> {
  const response = await apiFetch(`${getApiBaseUrl()}/reports/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!response.ok) throw await readApiError(response, 'Could not delete report');
  return true;
}

export async function downloadReport(id: string, format: 'json' | 'html' | 'pdf' | 'csv'): Promise<void> {
  const response = await apiFetch(`${getApiBaseUrl()}/reports/${encodeURIComponent(id)}/download?format=${format}`);
  if (!response.ok) throw await readApiError(response, 'Could not download report');
  const url = `${getApiBaseUrl()}/reports/${encodeURIComponent(id)}/download?format=${format}`;
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.download = `${id}-report.${format}`;
  anchor.click();
  anchor.remove();
}

// ==========================================
// ACTIVITIES & METRICS
// ==========================================

export async function getActivities(): Promise<Activity[]> {
  const history = await getAccountHistory(30);
  return history.map((event, index) => ({
    id: String(event.id ?? index),
    type: String(event.eventType ?? 'activity'),
    title: String(event.eventType ?? 'Activity').replaceAll('_', ' '),
    description: `${String(event.outcome ?? 'recorded')}${event.datasetId ? ` · dataset ${event.datasetId}` : ''}`,
    timestamp: event.createdAt ? new Date(String(event.createdAt)).toLocaleString() : 'Timestamp unavailable',
    targetId: event.datasetId ? String(event.datasetId) : undefined,
  }));
}

export async function getDashboardStats() {
  return getDashboardSummary();
}
