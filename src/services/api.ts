/**
 * DataLeakGuard-CV Mock API Service Layer
 *
 * NOTE FOR BACKEND INTEGRATION:
 * This module is designed to be a direct 1:1 drop-in replacement for a FastAPI backend.
 * Each function returns a Promise. When migrating to FastAPI:
 * Replace mock storage updates with standard `fetch('/api/v1/...')` calls.
 *
 * Example:
 * export async function getDatasets(): Promise<Dataset[]> {
 *   const res = await fetch('/api/v1/datasets');
 *   return res.json();
 * }
 */

import {
  Dataset,
  PersistedFinding,
  FindingCategorySummary,
  AnalysisResult,
  AnalysisStage,
  DatasetOperationRecord,
  CombinedRepairMetadata,
  FindingOperationType,
  Model,
  InferenceRecord,
  DistributionShift,
  ImpactAnalysis,
  AssuranceReport,
  Activity
} from '../types';

import { initialDatasets } from '../data/mockDatasets';
import { initialModels } from '../data/mockModels';
import { initialInferenceRecords } from '../data/mockInference';
import { mockImpactData, mockDistributionShiftData } from '../data/mockImpact';
import { initialReports } from '../data/mockReports';
import { initialActivities } from '../data/mockActivities';

// In-memory state holding dynamic modifications
let datasetsStore: Dataset[] = [...initialDatasets];
let modelsStore: Model[] = [...initialModels];
let inferenceStore: InferenceRecord[] = [...initialInferenceRecords];
let reportsStore: AssuranceReport[] = [...initialReports];
let activitiesStore: Activity[] = [...initialActivities];

const delay = (ms = 400) => new Promise((resolve) => setTimeout(resolve, ms));

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
  models: { available: boolean; reason?: string };
  reports: { available: boolean; reason?: string };
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
  splitColumn?: string;
  targetColumn?: string;
  timeColumn?: string;
}

type DetectorStageStatus = AnalysisStage['status'];

export function buildAnalysisStages(
  typeCounts: Record<string, number>,
  options: LeakageAnalysisOptions = {},
  execution: 'not_started' | 'running' | 'completed' | 'failed' = 'not_started'
): AnalysisStage[] {
  const hasEntity = Boolean(options.entityColumn);
  const hasSplit = Boolean(options.splitColumn);
  const hasTime = Boolean(options.timeColumn);
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
      needsConfiguration: hasEntity && !hasSplit,
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
      needsConfiguration: hasTime && !hasSplit,
      requirement: 'Select both a timestamp/time column and a split column.'
    },
    {
      id: 6,
      name: 'Train/Test Contamination',
      findingType: 'train_test_contamination',
      requested: hasSplit,
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
    if (stage.skipped) {
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
  // The route rejects an entity or time parameter without a split parameter.
  // Omit incomplete optional pairs while still allowing independent detectors
  // (exact duplicates, target leakage, and split-only contamination) to run.
  if (options.splitColumn) url.searchParams.set('split_column', options.splitColumn);
  if (options.targetColumn) url.searchParams.set('target_column', options.targetColumn);
  if (options.entityColumn && options.splitColumn) {
    url.searchParams.set('entity_column', options.entityColumn);
  }
  if (options.timeColumn && options.splitColumn) {
    url.searchParams.set('time_column', options.timeColumn);
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

  const stages = buildAnalysisStages(typeCounts, options, 'completed');
  for (const [index, stage] of stages.entries()) {
    if (stage.status === 'completed') reportProgress?.(index, stage.name);
  }

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
  };
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
  if (!Array.isArray(value.skipped_findings)) {
    throw new Error('Invalid operation response: operation_metadata.skipped_findings must be an array');
  }

  const skippedFindings = value.skipped_findings.map((item) => {
    if (
      !isRecord(item) ||
      typeof item.finding_id !== 'string' ||
      typeof item.reason !== 'string'
    ) {
      throw new Error('Invalid operation response: skipped finding metadata is malformed');
    }
    return { findingId: item.finding_id, reason: item.reason };
  });

  return {
    selectedFindingIds: stringArray(value.selected_finding_ids, 'selected_finding_ids'),
    appliedFindingIds: stringArray(value.applied_finding_ids, 'applied_finding_ids'),
    skippedFindings,
    originalRowCount: count(value.original_row_count, 'original_row_count'),
    finalRowCount: count(value.final_row_count, 'final_row_count'),
    duplicateRowsRemoved: count(value.duplicate_rows_removed, 'duplicate_rows_removed'),
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

export async function generateCombinedCleanedDataset(
  datasetId: string,
  selectedFindingIds: string[]
): Promise<DatasetOperationRecord> {
  if (selectedFindingIds.length === 0) {
    throw new Error('Select at least one eligible exact-duplicate finding.');
  }

  const response = await apiFetch(
    `${getApiBaseUrl()}/datasets/${encodeURIComponent(datasetId)}/repairs/combined`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selected_finding_ids: selectedFindingIds }),
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

function getSafeDownloadFilename(response: Response): string {
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

  if (
    filename.includes('..') ||
    filename.includes('/') ||
    filename.includes('\\') ||
    !/^[A-Za-z0-9][A-Za-z0-9._-]*\.(?:csv|xlsx)$/i.test(filename)
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
  await delay(200);
  return mockImpactData[datasetId] || mockImpactData['ds-adult-income'];
}

// ==========================================
// MODEL INTEGRITY
// ==========================================

export async function getModels(): Promise<Model[]> {
  await delay(200);
  return [...modelsStore];
}

export async function getModelById(id: string): Promise<Model | null> {
  await delay(150);
  const found = modelsStore.find((m) => m.id === id);
  return found ? { ...found } : null;
}

export async function verifyModel(modelId: string): Promise<{
  verified: boolean;
  status: Model['status'];
  sha256Match: boolean;
  fingerprintMatch: boolean;
  behaviorScore: number;
  message: string;
}> {
  await delay(500);
  const model = modelsStore.find((m) => m.id === modelId);
  if (!model) {
    return {
      verified: false,
      status: 'Not Available',
      sha256Match: false,
      fingerprintMatch: false,
      behaviorScore: 1.0,
      message: 'Model artifact not found in registry.'
    };
  }

  const shaMatch = model.sha256 === model.referenceHash;
  const status = shaMatch && model.behaviorDriftScore < 0.01 ? 'Verified' : !shaMatch ? 'Changed' : 'Review Required';
  model.status = status;
  model.lastVerified = new Date().toISOString().replace('T', ' ').substring(0, 19) + ' UTC';

  activitiesStore = [
    {
      id: `act-${Date.now()}`,
      type: 'model_verified',
      title: `Model Verification (${model.name})`,
      description: shaMatch ? 'Cryptographic SHA-256 and golden behavior matched registered spec.' : 'SHA-256 binary hash mismatch detected.',
      timestamp: 'Just now',
      targetId: model.id,
      severity: shaMatch ? 'Low' : 'Critical'
    },
    ...activitiesStore
  ];

  return {
    verified: shaMatch,
    status,
    sha256Match: shaMatch,
    fingerprintMatch: model.fingerprintMatch,
    behaviorScore: model.behaviorDriftScore,
    message: shaMatch
      ? 'Verified under configured checks: File hash and behavioral golden vectors match specification.'
      : 'Potential issue detected: SHA-256 checksum differed from stored baseline.'
  };
}

// ==========================================
// INFERENCE PROVENANCE
// ==========================================

export async function getInferenceRecords(): Promise<InferenceRecord[]> {
  await delay(200);
  return [...inferenceStore];
}

export async function runInference(payload: {
  modelId: string;
  imageOrVectorName: string;
  config: string
}): Promise<InferenceRecord> {
  await delay(500);
  const model = modelsStore.find((m) => m.id === payload.modelId) || modelsStore[0];

  const isCV = payload.imageOrVectorName.includes('.jpg') || payload.imageOrVectorName.includes('.png');
  const isChest = payload.imageOrVectorName.includes('xray') || model.id.includes('resnet');

  const record: InferenceRecord = {
    id: `PRV-${new Date().getFullYear()}-${Math.floor(1000 + Math.random() * 9000)}`,
    timestamp: new Date().toISOString().replace('T', ' ').substring(0, 19) + ' UTC',
    modelId: model.id,
    modelName: `${model.name} (${model.version})`,
    inputHash: '7f9a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcd',
    outputHash: '1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b',
    configHash: '01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b',
    nonce: `0x${Math.floor(Math.random() * 0xffffffff).toString(16)}`,
    sequenceNumber: 1043 + inferenceStore.length,
    digitalSignature: 'MEQCIDx489f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8AiBy781c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b==',
    verificationStatus: 'Verified',
    prediction: isCV ? (isChest ? {
      label: 'Normal',
      confidence: 0.978,
      secondaryClass: 'Bacterial Pneumonia',
      secondaryConfidence: 0.018,
      boundingBoxes: [
        { label: 'Clear Lung Field', box: [18, 20, 30, 52], confidence: 0.95 },
        { label: 'Clear Lung Field', box: [54, 22, 32, 50], confidence: 0.96 }
      ]
    } : {
      label: 'missing_hole',
      confidence: 0.942,
      secondaryClass: 'spurious_copper',
      secondaryConfidence: 0.045,
      boundingBoxes: [
        { label: 'missing_hole', box: [38, 42, 16, 20], confidence: 0.94 }
      ]
    }) : {
      label: '<=50K',
      confidence: 0.925,
      secondaryClass: '>50K',
      secondaryConfidence: 0.075
    },
    inputMetadata: {
      filename: payload.imageOrVectorName,
      dimensions: isCV ? '1024x1024' : '14 Features',
      sizeKb: isCV ? 1840 : 1.2,
      preprocessingConfig: payload.config
    }
  };

  inferenceStore = [record, ...inferenceStore];
  return record;
}

export async function simulateTampering(recordId: string, modifiedConfidence: number): Promise<InferenceRecord | null> {
  await delay(300);
  const rec = inferenceStore.find((r) => r.id === recordId);
  if (!rec) return null;

  rec.prediction.confidence = modifiedConfidence;
  rec.verificationStatus = 'Tampered';
  rec.tamperedFields = ['prediction.confidence', 'digitalSignature'];
  return { ...rec };
}

export async function simulateReplay(recordId: string): Promise<InferenceRecord | null> {
  await delay(300);
  const rec = inferenceStore.find((r) => r.id === recordId);
  if (!rec) return null;

  rec.verificationStatus = 'Replay Detected';
  return { ...rec };
}

export async function verifyProvenanceRecord(recordId: string): Promise<{
  verified: boolean;
  status: 'Verified' | 'Tampered' | 'Replay Detected';
  details: string;
}> {
  await delay(350);
  const rec = inferenceStore.find((r) => r.id === recordId);
  if (!rec) {
    return { verified: false, status: 'Tampered', details: 'Record not found in cryptographic log.' };
  }

  if (rec.verificationStatus === 'Tampered') {
    return {
      verified: false,
      status: 'Tampered',
      details: 'TAMPERING DETECTED: The payload hash or output confidence does not match the registered digital signature.'
    };
  }

  if (rec.verificationStatus === 'Replay Detected') {
    return {
      verified: false,
      status: 'Replay Detected',
      details: 'REPLAY DETECTED: Nonce or sequence number has already been retired in previous log epoch.'
    };
  }

  return {
    verified: true,
    status: 'Verified',
    details: 'PROVENANCE VERIFIED: Hash chain, sequence number, and digital signature verified under configured checks.'
  };
}

// ==========================================
// DISTRIBUTION SHIFT
// ==========================================

export async function getDistributionShift(): Promise<DistributionShift> {
  await delay(250);
  return { ...mockDistributionShiftData };
}

// ==========================================
// REPORTS
// ==========================================

export async function getReports(): Promise<AssuranceReport[]> {
  await delay(200);
  return [...reportsStore];
}

export async function getReportById(id: string): Promise<AssuranceReport | null> {
  await delay(200);
  const rep = reportsStore.find((r) => r.id === id);
  return rep ? { ...rep } : null;
}

export async function generateAssuranceReport(datasetId: string, modelId: string): Promise<AssuranceReport> {
  await delay(700);
  const ds = datasetsStore.find((d) => d.id === datasetId) || datasetsStore[0];
  const mdl = modelsStore.find((m) => m.id === modelId) || modelsStore[0];

  const newReport: AssuranceReport = {
    id: `REP-${new Date().getFullYear()}-${Math.floor(1000 + Math.random() * 9000)}`,
    title: `${ds.name} Assurance Report`,
    datasetId: ds.id,
    datasetName: `${ds.name} (${ds.format})`,
    modelId: mdl.id,
    modelName: `${mdl.name} (${mdl.version})`,
    createdAt: new Date().toISOString().replace('T', ' ').substring(0, 19) + ' UTC',
    assessmentStatus: 'REVIEW REQUIRED',
    disposition: 'REVIEW',
    confidenceScore: 89,
    projectDefinedRisk: 'HIGH',
    findingsCount: {
      critical: 24,
      high: 142,
      medium: 18,
      low: 4
    },
    executiveSummary: `Automated assurance audit conducted on ${ds.name} using model ${mdl.name}. Detected leakage patterns across validation splits resulting in observed evaluation inflation.`,
    sections: {
      datasetIntegrity: `${ds.sampleCount} records evaluated against duplicate, entity, and temporal integrity vectors.`,
      leakageFindings: 'Multiple cross-split duplicate pairs identified along with global preprocessing leakage.',
      datasetAnomalies: 'Label consistency checks flagged potential label disagreement across identical feature profiles.',
      modelIntegrity: `Model ${mdl.name} verified against SHA-256 fingerprint. Architecture matches stored specification.`,
      inferenceProvenance: 'Inference signing verified HMAC and sequence ordering under configured criteria.',
      distributionShift: 'Distribution analysis shows moderate shift across numerical feature distributions.',
      performanceImpact: 'Observed evaluation inflation of +7.4% between contaminated baseline and corrected evaluation.',
      evidence: 'Appendix contains complete list of flagged hash pairs and statistical divergence scores.',
      riskAssessment: 'Project-defined risk assessed as HIGH due to observed evaluation discrepancy.',
      limitations: [
        'Checks bounded by configured threshold parameters (similarity >= 95%).',
        'Not a guarantee against undetectable covert adversarial perturbations.'
      ],
      recommendedDisposition: 'REVIEW: Quarantine flagged entries and retrain using isolated validation pipeline.'
    }
  };

  reportsStore = [newReport, ...reportsStore];
  activitiesStore = [
    {
      id: `act-${Date.now()}`,
      type: 'report_generated',
      title: 'Assurance Report Generated',
      description: `Compiled assurance report ${newReport.id} for ${ds.name}.`,
      timestamp: 'Just now',
      targetId: newReport.id,
      severity: 'Medium'
    },
    ...activitiesStore
  ];

  return newReport;
}

export async function deleteReport(id: string): Promise<boolean> {
  await delay(200);
  reportsStore = reportsStore.filter((r) => r.id !== id);
  return true;
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
