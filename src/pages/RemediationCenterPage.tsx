import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  Download,
  FileText,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Wrench,
} from 'lucide-react';
import { FindingEvidencePanel } from '../components/leakage/FindingEvidencePanel';
import { SearchableColumnSelector } from '../components/analysis/SearchableColumnSelector';
import {
  cancelRemediationPlan,
  downloadRemediationArtifact,
  executeRemediationPlan,
  getDatasetById,
  getDatasetHistoryPage,
  getFindingTypeLabel,
  getFindingsPage,
  getRemediationPlans,
  previewRemediationPlan,
} from '../services/api';
import { saveDownloadedFile } from './RepairPage';
import type {
  Dataset,
  DatasetFindingPage,
  DatasetHistoryPage,
  DetectorColumnRole,
  FindingCounts,
  PersistedFinding,
  RemediationActionName,
  RemediationActionRequest,
  RemediationPlanRecord,
} from '../types';

export const REMEDIATION_DETECTORS = [
  {
    type: 'exact_duplicate',
    title: 'Exact Duplicate Detection',
    description: 'Remove only confirmed duplicate copies using deterministic keep-first behavior.',
    actions: [
      {
        value: 'exact_duplicate_keep_first',
        label: 'Keep first, remove evidenced copies',
        explanation: 'Deterministic row removal from a separate output; source data remains unchanged.',
      },
      {
        value: 'quarantine_evidenced_rows',
        label: 'Quarantine evidenced duplicate copies',
        explanation: 'Write the evidenced duplicate copies to a separate quarantine artifact.',
      },
      {
        value: 'review_only',
        label: 'Review only',
        explanation: 'Include the selected findings in the report without transforming dataset rows.',
      },
    ],
  },
  {
    type: 'entity_overlap',
    title: 'Entity Overlap',
    description: 'Keep entity groups intact or quarantine only rows supported by persisted row evidence.',
    actions: [
      {
        value: 'rebuild_group_split',
        label: 'Rebuild a group-aware split',
        explanation: 'Reassign all rows for each entity to one partition; this changes split labels, not records.',
      },
      {
        value: 'quarantine_evidenced_rows',
        label: 'Quarantine evidenced conflicting rows',
        explanation: 'Preserve source records in a separate quarantine artifact; do not delete whole entities.',
      },
      {
        value: 'review_only',
        label: 'Review only',
        explanation: 'Record the overlap for review without changing rows or split membership.',
      },
    ],
  },
  {
    type: 'target_leakage',
    title: 'Target Leakage',
    description: 'Exclude explicitly confirmed input features while retaining the target column.',
    actions: [
      {
        value: 'exclude_target_features',
        label: 'Exclude confirmed feature columns',
        explanation: 'Creates a model-ready output with selected inputs removed; it does not repair causal data collection.',
      },
      {
        value: 'review_only',
        label: 'Review only',
        explanation: 'Record the finding for review without changing the dataset schema.',
      },
    ],
  },
  {
    type: 'temporal_leakage',
    title: 'Temporal Leakage',
    description: 'Use an explicit chronological split cutoff or keep the finding for review.',
    actions: [
      {
        value: 'rebuild_chronological_split',
        label: 'Rebuild chronological split',
        explanation: 'Reassign train/test labels from a confirmed timestamp and cutoff; timestamps and records are preserved.',
      },
      {
        value: 'review_only',
        label: 'Review only',
        explanation: 'Record the temporal risk without changing timestamps or deleting historical records.',
      },
    ],
  },
  {
    type: 'train_test_contamination',
    title: 'Train/Test Contamination',
    description: 'Choose which evidenced partition to retain, or quarantine the evidenced copies.',
    actions: [
      {
        value: 'exclude_contaminated_copies',
        label: 'Retain one explicitly selected partition',
        explanation: 'Removes evidenced copies from other partitions only after you choose the retained partition.',
      },
      {
        value: 'quarantine_evidenced_rows',
        label: 'Quarantine all evidenced copies',
        explanation: 'Preserves all affected source records in a separate quarantine artifact.',
      },
      {
        value: 'review_only',
        label: 'Review only',
        explanation: 'Record the contamination finding without choosing which partition to retain.',
      },
    ],
  },
] as const;

type DetectorType = (typeof REMEDIATION_DETECTORS)[number]['type'];
type SelectionState = { findingIds: string[]; allEligible: boolean };
type DetectorConfiguration = {
  entityColumn?: string;
  splitColumn?: string;
  targetColumn?: string;
  featureColumns?: string[];
  timeColumn?: string;
  cutoff?: string;
  retainedPartition?: string;
  testRatio?: number;
  randomSeed?: number;
  trainLabel?: string;
  testLabel?: string;
};

const EMPTY_COUNTS: FindingCounts = {
  total: 0,
  open: 0,
  resolved: 0,
  low: 0,
  medium: 0,
  high: 0,
  otherSeverity: 0,
  statusCounts: {},
  detectorCounts: {},
};

const COLUMN_ROLES: Record<DetectorColumnRole, string> = {
  target: 'Target',
  entity: 'Entity',
  split: 'Split',
  timestamp: 'Timestamp',
};

function selectableColumns(dataset: Dataset | null) {
  return (dataset?.columns ?? []).map((column) => ({
    name: column.name,
    type: column.type,
  }));
}

export function getActionOptions(findingType: string) {
  return REMEDIATION_DETECTORS.find((detector) => detector.type === findingType)?.actions ?? [];
}

function selectionCount(selection: SelectionState, counts: FindingCounts): number {
  return selection.allEligible ? counts.open : selection.findingIds.length;
}

export function DetectorSection({
  datasetId,
  detector,
  selected,
  selectedFindingCache,
  onSetSelection,
  onCacheFindings,
  onCounts,
  refreshKey,
  dataset,
  actionConfiguration,
  onActionConfiguration,
  locked,
  latestOperationStatus,
}: {
  datasetId: string;
  detector: (typeof REMEDIATION_DETECTORS)[number];
  selected: SelectionState;
  selectedFindingCache: Record<string, PersistedFinding>;
  onSetSelection: (type: DetectorType, selection: SelectionState) => void;
  onCacheFindings: (items: PersistedFinding[]) => void;
  onCounts: (type: DetectorType, counts: FindingCounts) => void;
  refreshKey: number;
  dataset: Dataset | null;
  actionConfiguration?: { action: RemediationActionName; config: DetectorConfiguration };
  onActionConfiguration: (value: { action: RemediationActionName; config: DetectorConfiguration }) => void;
  locked: boolean;
  latestOperationStatus: string | null;
}) {
  const [expanded, setExpanded] = useState(detector.type === 'exact_duplicate');
  const [pageNumber, setPageNumber] = useState(1);
  const [search, setSearch] = useState('');
  const [severity, setSeverity] = useState('');
  const [status, setStatus] = useState('open');
  const [page, setPage] = useState<DatasetFindingPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const pageSize = expanded ? 10 : 1;
  const columns = selectableColumns(dataset);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    const timer = window.setTimeout(() => {
      getFindingsPage(datasetId, {
        skip: expanded ? (pageNumber - 1) * pageSize : 0,
        limit: pageSize,
        search,
        findingType: detector.type,
        ...(severity ? { severity } : {}),
        ...(status ? { status } : {}),
      })
        .then((result) => {
          if (!active) return;
          setPage(result);
          onCacheFindings(result.items);
          onCounts(detector.type, result.detectorSummary ?? result.matchingSummary);
        })
        .catch((reason: unknown) => {
          if (active) setError(reason instanceof Error ? reason.message : 'Findings could not be loaded.');
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, search ? 180 : 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [
    datasetId,
    detector.type,
    expanded,
    pageNumber,
    pageSize,
    expanded,
    search,
    severity,
    status,
    refreshKey,
    retryKey,
    onCacheFindings,
    onCounts,
  ]);

  const rows = page?.items ?? [];
  const maxPage = Math.max(1, Math.ceil((page?.total ?? 0) / pageSize));
  const currentSelectableIds = rows
    .filter((finding) => finding.status.toLowerCase() === 'open')
    .map((finding) => finding.id);
  const selectedOnPage = !selected.allEligible
    && currentSelectableIds.length > 0
    && currentSelectableIds.every((id) => selected.findingIds.includes(id));
  const selectedCount = selected.allEligible ? 'All open candidates' : `${selected.findingIds.length} selected`;

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-4">
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="flex min-w-0 items-center gap-3 text-left"
        >
          {expanded ? <ChevronDown className="h-4 w-4 text-teal-700" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
          <span className="min-w-0">
            <span className="block text-sm font-semibold text-slate-900">{detector.title}</span>
            <span className="mt-0.5 block text-xs text-slate-500">{detector.description}</span>
            <span className="mt-1 block text-[10px] text-slate-500">
              Supported actions: {detector.actions.filter((option) => option.value !== 'review_only').map((option) => option.label).join(' · ')}
            </span>
            <span className="mt-1 block text-[10px] text-slate-500">
              Consolidated operation: {latestOperationStatus ?? 'No persisted plan for this detector'}
            </span>
            <span className="mt-1 block text-[10px] text-slate-500">
              Eligibility is determined by the server from each finding’s current evidence during preview.
            </span>
          </span>
        </button>
        <div className="flex flex-wrap gap-2 text-[11px]">
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">
            {page?.detectorSummary?.total ?? page?.matchingSummary.total ?? '—'} total
          </span>
          <span className="rounded-full bg-amber-50 px-2.5 py-1 text-amber-800">
            {page?.detectorSummary?.open ?? page?.matchingSummary.open ?? '—'} open
          </span>
          <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-emerald-800">
            {page?.detectorSummary?.resolved ?? page?.matchingSummary.resolved ?? '—'} resolved
          </span>
        </div>
      </header>

      {expanded && (
        <fieldset disabled={locked} className="space-y-4 p-4 disabled:opacity-70">
          <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(180px,1fr)_160px_160px_auto]">
            <label className="text-xs font-medium text-slate-700">
              Search findings
              <input
                type="search"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setPageNumber(1);
                }}
                placeholder="ID, description, or evidence"
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
              />
            </label>
            <label className="text-xs font-medium text-slate-700">
              Severity
              <select
                value={severity}
                onChange={(event) => {
                  setSeverity(event.target.value);
                  setPageNumber(1);
                }}
                className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-2"
              >
                <option value="">All severities</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="other">Other / unclassified</option>
              </select>
            </label>
            <label className="text-xs font-medium text-slate-700">
              Status
              <select
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value);
                  setPageNumber(1);
                }}
                className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-2"
              >
                <option value="">All statuses</option>
                <option value="open">Open</option>
                <option value="resolved">Resolved</option>
              </select>
            </label>
            <div className="flex items-end gap-2">
              <button
                type="button"
                disabled={currentSelectableIds.length === 0 || selected.allEligible}
                aria-label={selected.allEligible ? 'Clear all-open selection to select a page' : undefined}
                onClick={() => onSetSelection(detector.type, {
                  allEligible: false,
                  findingIds: selectedOnPage
                    ? selected.findingIds.filter((id) => !currentSelectableIds.includes(id))
                    : Array.from(new Set([...selected.findingIds, ...currentSelectableIds])),
                })}
                className="rounded-md border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-40"
              >
                {selectedOnPage ? 'Deselect page' : 'Select page'}
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 p-3">
            <div className="text-xs text-slate-600">
              {selectedCount}. The all-open selection includes every open finding of this detector, regardless of the current filters; the backend validates evidence and lists unsupported items for review.
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => onSetSelection(detector.type, { findingIds: [], allEligible: true })}
                className={`rounded-md border px-3 py-1.5 text-xs font-semibold ${
                  selected.allEligible ? 'border-teal-600 bg-teal-50 text-teal-800' : 'border-slate-300 bg-white text-slate-700'
                }`}
              >
                {selected.allEligible ? 'All open candidates selected' : 'Select all open across pages'}
              </button>
              <button
                type="button"
                onClick={() => onSetSelection(detector.type, { findingIds: [], allEligible: false })}
                disabled={!selected.allEligible && selected.findingIds.length === 0}
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 disabled:opacity-40"
              >
                Clear selection
              </button>
            </div>
          </div>

          {loading && (
            <div role="status" className="flex items-center gap-2 py-5 text-xs text-slate-500">
              <LoaderCircle className="h-4 w-4 animate-spin" /> Loading this detector page…
            </div>
          )}
          {!loading && error && (
            <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800">
              {error}
              <button type="button" onClick={() => setRetryKey((value) => value + 1)} className="ml-3 underline">Retry</button>
            </div>
          )}
          {!loading && !error && rows.length === 0 && (
            <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500">
              No persisted findings match this detector and filter combination.
            </p>
          )}
          {!loading && !error && rows.length > 0 && (
            <div className="space-y-2">
              {rows.map((finding) => (
                <article key={finding.id} className="rounded-lg border border-slate-200 p-3">
                  <div className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      aria-label={`Select finding ${finding.id}`}
                      checked={selected.allEligible || selected.findingIds.includes(finding.id)}
                      disabled={finding.status.toLowerCase() !== 'open' || selected.allEligible}
                      onChange={() => onSetSelection(detector.type, {
                        allEligible: false,
                        findingIds: selected.findingIds.includes(finding.id)
                          ? selected.findingIds.filter((id) => id !== finding.id)
                          : [...selected.findingIds, finding.id],
                      })}
                      className="mt-1"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="break-all font-mono text-xs font-semibold text-slate-900">{finding.id}</p>
                        <div className="flex items-center gap-2">
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                            finding.severity.toLowerCase() === 'high'
                              ? 'bg-rose-100 text-rose-800'
                              : finding.severity.toLowerCase() === 'medium'
                                ? 'bg-amber-100 text-amber-800'
                                : 'bg-slate-100 text-slate-700'
                          }`}>{finding.severity}</span>
                          <span className="text-[10px] text-slate-500">{finding.status}</span>
                        </div>
                      </div>
                      <p className="mt-1 text-xs text-slate-700">{finding.description}</p>
                      <details className="mt-2">
                        <summary className="cursor-pointer text-[11px] font-semibold text-teal-800">Inspect evidence</summary>
                        <div className="mt-3 rounded-lg bg-slate-50 p-3">
                          <FindingEvidencePanel finding={finding} />
                        </div>
                      </details>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}

          <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3">
            <p className="text-xs text-slate-500">
              Page {Math.min(pageNumber, maxPage)} of {maxPage} · {page?.total ?? 0} matching findings · page size {pageSize}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPageNumber((current) => Math.max(1, current - 1))}
                disabled={pageNumber <= 1 || loading}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40"
              >
                Previous
              </button>
              <label className="sr-only" htmlFor={`page-${detector.type}`}>Go to page</label>
              <input
                id={`page-${detector.type}`}
                type="number"
                min={1}
                max={maxPage}
                value={pageNumber}
                onChange={(event) => {
                  const next = Number(event.target.value);
                  if (Number.isInteger(next) && next >= 1 && next <= maxPage) setPageNumber(next);
                }}
                className="w-16 rounded-md border border-slate-300 px-2 py-1.5 text-xs"
              />
              <button
                type="button"
                onClick={() => setPageNumber((current) => Math.min(maxPage, current + 1))}
                disabled={pageNumber >= maxPage || loading}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </footer>
          <DetectorActionConfiguration
            detector={detector}
            dataset={dataset}
            selected={selected}
            columns={columns}
            selectedFindingCache={selectedFindingCache}
            onConfigurationChange={onActionConfiguration}
            actionConfiguration={actionConfiguration}
          />
        </fieldset>
      )}
    </section>
  );
}

export function DetectorActionConfiguration({
  detector,
  dataset,
  selected,
  columns,
  selectedFindingCache,
  onConfigurationChange,
  actionConfiguration,
}: {
  detector: (typeof REMEDIATION_DETECTORS)[number];
  dataset: Dataset | null;
  selected: SelectionState;
  columns: Array<{ name: string; type: string }>;
  selectedFindingCache: Record<string, PersistedFinding>;
  onConfigurationChange: (value: { action: RemediationActionName; config: DetectorConfiguration }) => void;
  actionConfiguration?: { action: RemediationActionName; config: DetectorConfiguration };
}) {
  const action = actionConfiguration?.action ?? (
    detector.type === 'exact_duplicate'
      ? 'exact_duplicate_keep_first'
      : 'review_only'
  );
  const config = actionConfiguration?.config ?? {};
  const setConfig = (update: (current: DetectorConfiguration) => DetectorConfiguration) => {
    onConfigurationChange({ action, config: update(config) });
  };
  const setAction = (nextAction: RemediationActionName) => {
    onConfigurationChange({ action: nextAction, config });
  };
  const canPreview = selected.allEligible || selected.findingIds.length > 0;
  const evidenceFindings = selected.allEligible
    ? []
    : selected.findingIds
      .map((findingId) => selectedFindingCache[findingId])
      .filter((finding): finding is PersistedFinding => Boolean(finding));
  const evidenceFeatures = Array.from(new Set(evidenceFindings.flatMap((finding) => {
    const feature = finding.evidence?.feature_column;
    return typeof feature === 'string' ? [feature] : [];
  })));
  const partitionNames = Array.from(new Set(evidenceFindings.flatMap((finding) => {
    const rowIndices = finding.evidence?.row_indices;
    return rowIndices && typeof rowIndices === 'object' && !Array.isArray(rowIndices)
      ? Object.keys(rowIndices)
      : [];
  })));
  const roleSelector = (
    role: DetectorColumnRole,
    value: string | undefined,
    onChange: (value: string) => void,
  ) => (
    <SearchableColumnSelector
      label={`${COLUMN_ROLES[role]} column`}
      value={value ?? ''}
      columns={columns}
      onChange={onChange}
    />
  );

  return (
    <div className={`rounded-lg border p-3 ${canPreview ? 'border-teal-200 bg-teal-50/40' : 'border-slate-200 bg-slate-50'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-xs font-semibold text-slate-900">Selected-finding action</h3>
          <p className="mt-0.5 text-[11px] text-slate-600">
            {canPreview
              ? 'Preview validates every selected finding and shows the proposed output before confirmation.'
              : 'Select open findings to configure and preview an action.'}
          </p>
        </div>
        <select
          aria-label={`${detector.title} remediation action`}
          value={action}
          onChange={(event) => setAction(event.target.value as RemediationActionName)}
          className="max-w-full rounded-md border border-slate-300 bg-white px-2 py-2 text-xs"
        >
          {detector.actions.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </div>
      <p className="mt-2 text-[11px] text-slate-600">
        {detector.actions.find((option) => option.value === action)?.explanation}
      </p>

      {action === 'rebuild_group_split' && (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {roleSelector('entity', config.entityColumn, (value) => setConfig((current) => ({ ...current, entityColumn: value })))}
          {roleSelector('split', config.splitColumn, (value) => setConfig((current) => ({ ...current, splitColumn: value })))}
          <label className="text-xs text-slate-700">Test ratio
            <input type="number" min="0.05" max="0.95" step="0.05" value={config.testRatio ?? 0.2}
              onChange={(event) => setConfig((current) => ({ ...current, testRatio: Number(event.target.value) }))}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2" />
          </label>
          <label className="text-xs text-slate-700">Random seed
            <input type="number" step="1" value={config.randomSeed ?? 42}
              onChange={(event) => setConfig((current) => ({ ...current, randomSeed: Number(event.target.value) }))}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2" />
          </label>
          <label className="text-xs text-slate-700">Training label
            <input value={config.trainLabel ?? 'train'} onChange={(event) => setConfig((current) => ({ ...current, trainLabel: event.target.value }))}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2" />
          </label>
          <label className="text-xs text-slate-700">Test label
            <input value={config.testLabel ?? 'test'} onChange={(event) => setConfig((current) => ({ ...current, testLabel: event.target.value }))}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2" />
          </label>
        </div>
      )}
      {action === 'exclude_target_features' && (
        <div className="mt-3 space-y-3">
          {roleSelector('target', config.targetColumn, (value) => setConfig((current) => ({ ...current, targetColumn: value })))}
          <fieldset>
            <legend className="text-xs font-medium text-slate-700">Confirmed feature columns to exclude</legend>
            {evidenceFeatures.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-2">
                {evidenceFeatures.map((feature) => (
                  <label key={feature} className="flex items-center gap-2 rounded border border-slate-200 bg-white px-2 py-1.5 text-xs">
                    <input
                      type="checkbox"
                      checked={(config.featureColumns ?? []).includes(feature)}
                      onChange={() => setConfig((current) => ({
                        ...current,
                        featureColumns: (current.featureColumns ?? []).includes(feature)
                          ? (current.featureColumns ?? []).filter((item) => item !== feature)
                          : [...(current.featureColumns ?? []), feature],
                      }))}
                    />
                    <span className="font-mono">{feature}</span>
                  </label>
                ))}
              </div>
            ) : selected.allEligible ? (
              <p className="mt-2 text-[11px] text-slate-600">
                The server will derive the confirmed feature names from every selected persisted finding and display them in the preview.
              </p>
            ) : (
              <p className="mt-2 text-[11px] text-amber-800">
                Select the finding on the current page to inspect and explicitly confirm its persisted feature name.
              </p>
            )}
          </fieldset>
        </div>
      )}
      {action === 'rebuild_chronological_split' && (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {roleSelector('timestamp', config.timeColumn, (value) => setConfig((current) => ({ ...current, timeColumn: value })))}
          {roleSelector('split', config.splitColumn, (value) => setConfig((current) => ({ ...current, splitColumn: value })))}
          <label className="text-xs text-slate-700">Confirmed cutoff date
            <input type="date" value={config.cutoff ?? ''} onChange={(event) => setConfig((current) => ({ ...current, cutoff: event.target.value }))}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2" />
          </label>
          <label className="text-xs text-slate-700">Train / test labels
            <span className="mt-1 flex gap-2">
              <input aria-label="Training label" value={config.trainLabel ?? 'train'} onChange={(event) => setConfig((current) => ({ ...current, trainLabel: event.target.value }))}
                className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2" />
              <input aria-label="Test label" value={config.testLabel ?? 'test'} onChange={(event) => setConfig((current) => ({ ...current, testLabel: event.target.value }))}
                className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2" />
            </span>
          </label>
        </div>
      )}
      {action === 'exclude_contaminated_copies' && (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {roleSelector('split', config.splitColumn, (value) => setConfig((current) => ({ ...current, splitColumn: value })))}
          <label className="text-xs text-slate-700">Retain partition
            {partitionNames.length > 0 ? (
              <select value={config.retainedPartition ?? ''} onChange={(event) => setConfig((current) => ({ ...current, retainedPartition: event.target.value }))}
                className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2">
                <option value="">Choose the partition to retain</option>
                {partitionNames.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            ) : (
              <input value={config.retainedPartition ?? ''} onChange={(event) => setConfig((current) => ({ ...current, retainedPartition: event.target.value }))}
                placeholder="Type exact partition from finding evidence"
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2" />
            )}
          </label>
        </div>
      )}
      {action === 'quarantine_evidenced_rows' && (
        <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-2.5 text-[11px] text-amber-900">
          Only findings with deterministic persisted row-position evidence can be quarantined. The backend will reject unsupported or stale evidence.
        </p>
      )}
      {action === 'review_only' && (
        <p className="mt-3 rounded-md border border-blue-200 bg-blue-50 p-2.5 text-[11px] text-blue-900">
          No row or column transformation will be requested. The report will retain these findings as unresolved/review required.
        </p>
      )}
      {dataset && <p className="mt-2 text-[10px] text-slate-500">Original: {dataset.name} · no operation overwrites the uploaded source.</p>}
      {canPreview && (
        <p className="mt-2 text-[10px] text-slate-500">
          Selected from this detector: {selected.allEligible ? 'all open findings on the server, validated at preview time' : selected.findingIds.length.toLocaleString()}
        </p>
      )}
    </div>
  );
}

export const RemediationCenterPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [datasetSummary, setDatasetSummary] = useState<FindingCounts>(EMPTY_COUNTS);
  const [countsByDetector, setCountsByDetector] = useState<Record<string, FindingCounts>>({});
  const [findingCache, setFindingCache] = useState<Record<string, PersistedFinding>>({});
  const [selections, setSelections] = useState<Record<string, SelectionState>>({});
  const [actionConfigurations, setActionConfigurations] = useState<
    Record<string, { action: RemediationActionName; config: DetectorConfiguration }>
  >({});
  const [history, setHistory] = useState<RemediationPlanRecord[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historySkip, setHistorySkip] = useState(0);
  const [auditPage, setAuditPage] = useState<DatasetHistoryPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [plan, setPlan] = useState<RemediationPlanRecord | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [downloading, setDownloading] = useState<string | null>(null);

  const loadPageData = useCallback(async () => {
    if (!id) {
      setLoadError('A dataset identifier is required to open the Remediation Center.');
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const [datasetResult, findingsResult, planResult, historyResult] = await Promise.all([
        getDatasetById(id),
        getFindingsPage(id, { skip: 0, limit: 1 }),
        getRemediationPlans(id, { skip: 0, limit: 10 }),
        getDatasetHistoryPage(id, { skip: 0, limit: 8 }),
      ]);
      if (!datasetResult) throw new Error('Dataset not found or is not available to this account.');
      setDataset(datasetResult);
      setDatasetSummary(findingsResult.datasetSummary);
      setHistory(planResult.items);
      setHistoryTotal(planResult.total);
      setHistorySkip(planResult.skip);
      setAuditPage(historyResult);
    } catch (reason: unknown) {
      setLoadError(reason instanceof Error ? reason.message : 'The Remediation Center could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  const loadHistoryPage = useCallback(async (skip: number) => {
    if (!id) return;
    try {
      const result = await getRemediationPlans(id, { skip, limit: 10 });
      setHistory(result.items);
      setHistoryTotal(result.total);
      setHistorySkip(result.skip);
    } catch (reason: unknown) {
      setActionError(reason instanceof Error ? reason.message : 'Remediation history could not be loaded.');
    }
  }, [id]);

  useEffect(() => {
    void loadPageData();
  }, [loadPageData]);

  const cacheFindings = useCallback((items: PersistedFinding[]) => {
    setFindingCache((current) => {
      const next = { ...current };
      for (const item of items) next[item.id] = item;
      return next;
    });
  }, []);

  const updateCounts = useCallback((type: DetectorType, counts: FindingCounts) => {
    setCountsByDetector((current) => ({ ...current, [type]: counts }));
  }, []);

  const setDetectorSelection = useCallback((type: DetectorType, selection: SelectionState) => {
    setSelections((current) => ({ ...current, [type]: selection }));
  }, []);

  const setDetectorActionConfiguration = useCallback((
    type: DetectorType,
    value: { action: RemediationActionName; config: DetectorConfiguration },
  ) => {
    setActionConfigurations((current) => ({ ...current, [type]: value }));
  }, []);

  const selectedFindingCount = useMemo(
    () => REMEDIATION_DETECTORS.reduce((total, detector) => {
      const selected = selections[detector.type] ?? { findingIds: [], allEligible: false };
      const counts = countsByDetector[detector.type] ?? EMPTY_COUNTS;
      return total + selectionCount(selected, counts);
    }, 0),
    [countsByDetector, selections],
  );

  const clearAllSelections = () => {
    setSelections({});
  };

  const buildActions = (): RemediationActionRequest[] => {
    const actions: RemediationActionRequest[] = [];
    for (const detector of REMEDIATION_DETECTORS) {
      const selection = selections[detector.type];
      if (!selection || (!selection.allEligible && selection.findingIds.length === 0)) continue;
      const actionConfiguration = actionConfigurations[detector.type];
      const config = actionConfiguration?.config ?? {};
      const action = actionConfiguration?.action;
      const actionName = action && detector.actions.some((option) => option.value === action)
        ? action
        : detector.type === 'exact_duplicate' ? 'exact_duplicate_keep_first' : 'review_only';
      const payload: RemediationActionRequest = {
        action: actionName,
        selection_mode: selection.allEligible ? 'all_eligible' : 'explicit',
        ...(selection.allEligible
          ? { finding_type: detector.type, finding_ids: [] }
          : { finding_ids: selection.findingIds }),
      };
      if (actionName === 'rebuild_group_split') {
        Object.assign(payload, {
          entity_column: config.entityColumn,
          split_column: config.splitColumn,
          test_ratio: config.testRatio ?? 0.2,
          random_seed: config.randomSeed ?? 42,
          train_label: config.trainLabel || 'train',
          test_label: config.testLabel || 'test',
        });
      } else if (actionName === 'exclude_target_features') {
        Object.assign(payload, {
          target_column: config.targetColumn,
          feature_columns: config.featureColumns ?? [],
        });
      } else if (actionName === 'rebuild_chronological_split') {
        Object.assign(payload, {
          time_column: config.timeColumn,
          split_column: config.splitColumn,
          cutoff: config.cutoff,
          train_label: config.trainLabel || 'train',
          test_label: config.testLabel || 'test',
        });
      } else if (actionName === 'exclude_contaminated_copies') {
        Object.assign(payload, {
          split_column: config.splitColumn,
          retained_partition: config.retainedPartition,
        });
      }
      actions.push(payload);
    }
    return actions;
  };

  const handlePreview = async () => {
    if (!id || busy) return;
    setBusy(true);
    setActionError(null);
    setConfirmed(false);
    try {
      const actions = buildActions();
      if (!actions.length) throw new Error('Select findings in at least one detector section before previewing.');
      const result = await previewRemediationPlan(id, actions);
      setPlan(result);
    } catch (reason: unknown) {
      setActionError(reason instanceof Error ? reason.message : 'Remediation preview failed.');
    } finally {
      setBusy(false);
    }
  };

  const handleCancel = async () => {
    if (!id || !plan || busy) return;
    setBusy(true);
    setActionError(null);
    try {
      const cancelled = await cancelRemediationPlan(id, plan.id, 'Cancelled by the user from the Remediation Center.');
      setPlan(cancelled);
      setConfirmed(false);
      const refreshed = await getRemediationPlans(id, { skip: 0, limit: 10 });
      setHistory(refreshed.items);
      setHistoryTotal(refreshed.total);
      setHistorySkip(0);
    } catch (reason: unknown) {
      setActionError(reason instanceof Error ? reason.message : 'The preview could not be cancelled.');
    } finally {
      setBusy(false);
    }
  };

  const handleExecute = async () => {
    if (!id || !plan || !confirmed || !plan.plan.previewToken || busy) return;
    setBusy(true);
    setActionError(null);
    try {
      const executed = await executeRemediationPlan(id, plan.id, plan.plan.previewToken, true);
      setPlan(executed);
      const [refreshedPlans, refreshedAudit] = await Promise.all([
        getRemediationPlans(id, { skip: 0, limit: 10 }),
        getDatasetHistoryPage(id, { skip: 0, limit: 8 }),
      ]);
      setHistory(refreshedPlans.items);
      setHistoryTotal(refreshedPlans.total);
      setHistorySkip(0);
      setAuditPage(refreshedAudit);
      setRefreshKey((key) => key + 1);
      setSelections({});
      setConfirmed(false);
    } catch (reason: unknown) {
      setActionError(reason instanceof Error ? reason.message : 'The confirmed remediation plan failed.');
    } finally {
      setBusy(false);
    }
  };

  const handleDownload = async (
    operationId: string,
    artifact: 'dataset' | 'report' | 'manifest' | 'quarantine',
  ) => {
    const key = `${operationId}:${artifact}`;
    setDownloading(key);
    setActionError(null);
    try {
      const output = await downloadRemediationArtifact(operationId, artifact);
      saveDownloadedFile(output.blob, output.filename);
    } catch (reason: unknown) {
      setActionError(reason instanceof Error ? reason.message : 'Artifact download failed.');
    } finally {
      setDownloading(null);
    }
  };

  if (loading) {
    return <div role="status" className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600">
      <LoaderCircle className="h-4 w-4 animate-spin" /> Loading dataset, findings, and remediation history…
    </div>;
  }
  if (loadError || !dataset || !id) {
    return <div className="space-y-3">
      <h1 className="text-2xl font-bold text-slate-900">Remediation Center</h1>
      <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{loadError ?? 'Dataset is unavailable.'}</div>
      <button type="button" onClick={() => void loadPageData()} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold">Retry loading</button>
    </div>;
  }

  const knownCount = REMEDIATION_DETECTORS.reduce(
    (total, detector) => total + (datasetSummary.detectorCounts[detector.type] ?? 0),
    0,
  );
  const unclassifiedCount = Math.max(0, datasetSummary.total - knownCount);

  return (
    <main className="mx-auto max-w-7xl space-y-5">
      <header className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-widest text-teal-700">Evidence-backed operations</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">Remediation Center</h1>
          <p className="mt-1 text-sm text-slate-600">
            {dataset.name} · {datasetSummary.total.toLocaleString()} persisted findings · source files are never overwritten.
          </p>
        </div>
        <nav aria-label="Dataset workflow" className="flex flex-wrap gap-2 text-xs">
          <button type="button" onClick={() => navigate(`/datasets/${id}`)} className="rounded-md border border-slate-300 bg-white px-3 py-2">Dataset</button>
          <button type="button" onClick={() => navigate(`/analysis-setup/${id}`)} className="rounded-md border border-slate-300 bg-white px-3 py-2">Analysis Setup</button>
          <button type="button" onClick={() => navigate(`/analysis/${id}`)} className="rounded-md border border-slate-300 bg-white px-3 py-2">Analysis</button>
          <button type="button" onClick={() => navigate(`/leakage-analysis/${id}`)} className="rounded-md border border-slate-300 bg-white px-3 py-2">Findings</button>
          <button type="button" onClick={() => navigate(`/datasets/${id}?tab=history`)} className="rounded-md border border-slate-300 bg-white px-3 py-2">Audit History</button>
        </nav>
      </header>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ['Total findings', datasetSummary.total],
          ['Open', datasetSummary.open],
          ['Resolved', datasetSummary.resolved],
          ['High severity', datasetSummary.high],
        ].map(([label, count]) => (
          <article key={label} className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="text-[11px] font-medium text-slate-500">{label}</p>
            <p className="mt-1 text-2xl font-bold text-slate-900">{Number(count).toLocaleString()}</p>
          </article>
        ))}
      </section>
      {unclassifiedCount > 0 && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          {unclassifiedCount.toLocaleString()} finding(s) use types outside the five supported detector categories. They are not silently assigned to a remediation group.
        </p>
      )}

      <section aria-label="Detector remediation groups" className="space-y-3">
        {REMEDIATION_DETECTORS.map((detector) => (
          <DetectorSection
            key={detector.type}
            datasetId={id}
            detector={detector}
            selected={selections[detector.type] ?? { findingIds: [], allEligible: false }}
            selectedFindingCache={findingCache}
            onSetSelection={setDetectorSelection}
            onCacheFindings={cacheFindings}
            onCounts={updateCounts}
            refreshKey={refreshKey}
            dataset={dataset}
            actionConfiguration={actionConfigurations[detector.type]}
            onActionConfiguration={(value) => setDetectorActionConfiguration(detector.type, value)}
            locked={plan?.status === 'previewed'}
            latestOperationStatus={
              history.find((item) => item.plan.detectorTypes.includes(detector.type))?.status ?? null
            }
          />
        ))}
      </section>

      <section className="rounded-xl border border-teal-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Consolidated remediation plan</h2>
            <p className="mt-1 text-xs text-slate-600">
              {selectedFindingCount.toLocaleString()} selected candidate(s) across detector groups. The backend validates every finding and rejects stale or conflicting plans.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={clearAllSelections} disabled={plan?.status === 'previewed'} className="rounded-md border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-40">Clear all selections</button>
            <button type="button" onClick={() => void handlePreview()} disabled={busy || selectedFindingCount === 0 || plan?.status === 'previewed'}
              className="flex items-center gap-2 rounded-md bg-teal-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">
              {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Wrench className="h-4 w-4" />}
              Preview selected actions
            </button>
          </div>
        </div>
        {actionError && <p role="alert" className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800">{actionError}</p>}
        {plan && (
          <div className="mt-4 space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4" data-testid="remediation-plan">
            <div className="flex items-start gap-3">
              {plan.status === 'completed'
                ? <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-600" />
                : plan.status === 'failed'
                  ? <AlertTriangle className="mt-0.5 h-5 w-5 text-rose-600" />
                  : <ShieldCheck className="mt-0.5 h-5 w-5 text-teal-700" />}
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-semibold text-slate-900">
                  {plan.status === 'previewed'
                    ? 'Review before execution'
                    : plan.plan.finalStatus ?? plan.status.replaceAll('_', ' ')}
                </h3>
                <p className="mt-1 text-xs text-slate-600">
                  {plan.plan.originalRowCount.toLocaleString()} source rows → {plan.plan.expectedFinalRowCount.toLocaleString()} expected output rows ·
                  {' '}{plan.plan.originalColumnCount.toLocaleString()} source columns → {plan.plan.expectedFinalColumnCount.toLocaleString()} expected output columns.
                </p>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <SummaryValue label="Affected source rows" value={`${plan.plan.affectedSourceRowPositionsCount.toLocaleString()}${plan.plan.affectedSourceRowPositionsTruncated ? ' (preview truncated)' : ''}`} />
              <SummaryValue label="Removed rows" value={plan.plan.removedRowCount?.toLocaleString() ?? 'Preview only'} />
              <SummaryValue label="Quarantined rows" value={plan.plan.quarantinedRowCount?.toLocaleString() ?? 'Preview only'} />
              <SummaryValue label="Unresolved findings" value={plan.plan.unresolvedFindingsCount.toLocaleString()} />
            </div>
            {plan.plan.excludedFeatureColumns.length > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950">
                Model-ready output will exclude: <span className="font-mono">{plan.plan.excludedFeatureColumns.join(', ')}</span>. The target column is retained; this is not a claim about causal data collection.
              </div>
            )}
            {plan.plan.splitConfigurations.length > 0 && (
              <details className="rounded-lg border border-slate-200 bg-white p-3">
                <summary className="cursor-pointer text-xs font-semibold text-slate-800">Inspect proposed split changes</summary>
                <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words text-[10px] text-slate-700">
                  {JSON.stringify(plan.plan.splitConfigurations, null, 2)}
                </pre>
              </details>
            )}
            {plan.plan.actions.length > 0 && (
              <div className="rounded-lg border border-slate-200 bg-white p-3">
                <h4 className="text-xs font-semibold text-slate-800">Actions included in this exact preview</h4>
                <ul className="mt-2 space-y-1 text-[11px] text-slate-700">
                  {plan.plan.actions.map((item, index) => (
                    <li key={`${item.action}:${item.findingType ?? 'all'}:${index}`}>
                      <span className="font-mono">{item.action}</span> · {item.findingType ?? 'finding type unavailable'} ·
                      {' '}{item.selectedCount.toLocaleString()} selected · {item.appliedCount.toLocaleString()} supported by evidence
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <p className="text-xs font-semibold text-slate-800">
                Affected source row positions (zero-based): {plan.plan.affectedSourceRowPositionsCount.toLocaleString()}
              </p>
              <p className="mt-1 break-all font-mono text-[10px] text-slate-500">
                Preview: {plan.plan.affectedSourceRowPositionsPreview.join(', ') || 'none'}{plan.plan.affectedSourceRowPositionsTruncated ? ' …' : ''}
              </p>
              <p className="mt-1 break-all text-[10px] text-slate-500">Position-list SHA-256: {plan.plan.affectedSourceRowPositionsSha256}</p>
            </div>
            {plan.plan.skippedFindings.length > 0 && (
              <details className="rounded-lg border border-amber-200 bg-white p-3">
                <summary className="cursor-pointer text-xs font-semibold text-amber-900">
                  Findings requiring review ({plan.plan.skippedFindings.length}{plan.plan.skippedFindingsTruncated ? '+' : ''})
                </summary>
                <ul className="mt-2 space-y-1 text-[11px] text-slate-700">
                  {plan.plan.skippedFindings.map((finding) => (
                    <li key={finding.findingId}><span className="font-mono">{finding.findingId}</span>: {finding.reason}</li>
                  ))}
                </ul>
              </details>
            )}
            {plan.status === 'previewed' && plan.plan.previewToken && (
              <div className="space-y-3 border-t border-slate-200 pt-3">
                <label className="flex items-start gap-2 text-xs text-slate-700">
                  <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5" />
                  <span>
                    I reviewed the current preview (digest <code className="break-all">{plan.plan.previewDigest}</code>) and explicitly confirm generation of a separate output from the unchanged original dataset.
                  </span>
                </label>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => void handleExecute()} disabled={!confirmed || busy}
                    className="rounded-md bg-emerald-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">
                    {busy ? 'Executing and verifying…' : 'Confirm and generate outputs'}
                  </button>
                  <button type="button" onClick={() => void handleCancel()} disabled={busy}
                    className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">
                    Cancel preview
                  </button>
                </div>
              </div>
            )}
            {plan.status === 'completed' && (
              <div className="space-y-3 border-t border-slate-200 pt-3">
                <p className="text-xs text-slate-700">
                  Verification: {plan.plan.verification?.all_checks_passed === true ? 'all recorded checks passed' : 'review required; one or more checks did not pass'} · final status: <strong>{plan.plan.finalStatus ?? 'not classified'}</strong>
                </p>
                <div className="flex flex-wrap gap-2">
                  {(['dataset', 'report', 'manifest', 'quarantine'] as const).map((artifact) => {
                    if (artifact === 'quarantine' && !plan.plan.quarantineOutputSha256) return null;
                    return (
                      <button key={artifact} type="button" onClick={() => void handleDownload(plan.id, artifact)}
                        disabled={downloading === `${plan.id}:${artifact}`}
                        className="flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-50">
                        <Download className="h-3.5 w-3.5" />
                        {downloading === `${plan.id}:${artifact}` ? 'Preparing…' : `Download ${artifact === 'dataset' ? 'final CSV' : artifact === 'report' ? 'repair report' : artifact}`}
                      </button>
                    );
                  })}
                </div>
                <p className="break-all text-[10px] text-slate-500">Original SHA-256: {plan.plan.originalFileSha256}</p>
                <p className="break-all text-[10px] text-slate-500">Final SHA-256: {plan.plan.finalFileSha256 ?? 'unavailable'}</p>
              </div>
            )}
            {plan.status === 'failed' && (
              <div className="space-y-3">
                <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800">
                  Execution did not produce a verified final dataset: {plan.plan.failureReason ?? 'The backend reported a verification or execution failure.'}
                </p>
                <div className="flex flex-wrap gap-2">
                  {plan.plan.repairReportSha256 && (
                    <button type="button" onClick={() => void handleDownload(plan.id, 'report')}
                      className="flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">
                      <Download className="h-3.5 w-3.5" /> Download failure report
                    </button>
                  )}
                  {plan.plan.manifestSha256 && (
                    <button type="button" onClick={() => void handleDownload(plan.id, 'manifest')}
                      className="flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">
                      <Download className="h-3.5 w-3.5" /> Download manifest
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><Clock3 className="h-4 w-4 text-teal-700" /> Remediation history</h2>
          {history.length === 0 ? (
            <p className="mt-3 text-xs text-slate-500">No persisted remediation plans are available for this dataset.</p>
          ) : (
            <ul className="mt-3 divide-y divide-slate-100">
              {history.map((item) => (
                <li key={item.id} className="flex items-start justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <p className="break-all font-mono text-[11px] font-semibold text-slate-800">{item.id}</p>
                    <p className="mt-0.5 text-[10px] text-slate-500">{item.createdAt ? new Date(item.createdAt).toLocaleString() : 'Timestamp unavailable'} · {item.plan.detectorTypes.map(getFindingTypeLabel).join(', ') || 'No detector types recorded'}</p>
                    <details className="mt-1">
                      <summary className="cursor-pointer text-[10px] font-semibold text-teal-800">Inspect persisted operation</summary>
                      <dl className="mt-2 grid gap-x-3 gap-y-1 text-[10px] sm:grid-cols-2">
                        <dt className="text-slate-500">Operation type</dt><dd>{item.operationType}</dd>
                        <dt className="text-slate-500">Selected findings</dt><dd>{item.plan.selectedCount.toLocaleString()}</dd>
                        <dt className="text-slate-500">Applied findings</dt><dd>{item.plan.appliedCount.toLocaleString()}</dd>
                        <dt className="text-slate-500">Affected rows</dt><dd>{item.plan.affectedSourceRowPositionsCount.toLocaleString()}</dd>
                        <dt className="text-slate-500">Original SHA-256</dt><dd className="break-all font-mono">{item.plan.originalFileSha256}</dd>
                        {item.plan.finalFileSha256 && <><dt className="text-slate-500">Final SHA-256</dt><dd className="break-all font-mono">{item.plan.finalFileSha256}</dd></>}
                      </dl>
                      {item.plan.verification && (
                        <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-words text-[9px] text-slate-600">
                          {JSON.stringify(item.plan.verification, null, 2)}
                        </pre>
                      )}
                    </details>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-2">
                    <span className={`rounded-full px-2 py-1 text-[10px] font-semibold uppercase ${item.status === 'completed' ? 'bg-emerald-100 text-emerald-800' : item.status === 'failed' ? 'bg-rose-100 text-rose-800' : 'bg-slate-100 text-slate-700'}`}>{item.status.replaceAll('_', ' ')}</span>
                    <button type="button" onClick={() => { setPlan(item); setConfirmed(false); }}
                      className="rounded border border-slate-300 bg-white px-2 py-1 text-[10px] font-semibold text-slate-700">
                      View plan
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {historyTotal > 10 && (
            <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-3">
              <span className="text-[10px] text-slate-500">
                {historySkip + 1}–{Math.min(historySkip + history.length, historyTotal)} of {historyTotal}
              </span>
              <div className="flex gap-2">
                <button type="button" onClick={() => void loadHistoryPage(Math.max(0, historySkip - 10))}
                  disabled={historySkip <= 0} className="rounded border border-slate-300 px-2 py-1 text-[10px] disabled:opacity-40">Previous</button>
                <button type="button" onClick={() => void loadHistoryPage(historySkip + 10)}
                  disabled={historySkip + 10 >= historyTotal} className="rounded border border-slate-300 px-2 py-1 text-[10px] disabled:opacity-40">Next</button>
              </div>
            </div>
          )}
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><FileText className="h-4 w-4 text-teal-700" /> Recent dataset audit events</h2>
          {!auditPage || auditPage.items.length === 0 ? (
            <p className="mt-3 text-xs text-slate-500">No audit events are available for this dataset.</p>
          ) : (
            <ul className="mt-3 divide-y divide-slate-100">
              {auditPage.items.slice(0, 5).map((event) => (
                <li key={event.id} className="py-2.5">
                  <p className="text-xs font-semibold text-slate-800">{event.eventType.replaceAll('_', ' ')}</p>
                  <p className="mt-0.5 text-[10px] text-slate-500">{event.outcome} · {new Date(event.createdAt).toLocaleString()}</p>
                  {event.operationId && <p className="mt-0.5 break-all font-mono text-[10px] text-slate-500">Operation {event.operationId}</p>}
                  {(event.failureReason || event.details) && (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-[10px] text-teal-800">Inspect event details</summary>
                      <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words text-[9px] text-slate-600">
                        {JSON.stringify({ failureReason: event.failureReason, details: event.details }, null, 2)}
                      </pre>
                    </details>
                  )}
                </li>
              ))}
            </ul>
          )}
          <button type="button" onClick={() => navigate(`/datasets/${id}?tab=history`)}
            className="mt-3 text-[11px] font-semibold text-teal-800 underline underline-offset-2">
            Open full Audit History
          </button>
        </div>
      </section>
      <div className="flex flex-wrap justify-between gap-2">
        <button type="button" onClick={() => void loadPageData()} className="flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">
          <RefreshCw className="h-3.5 w-3.5" /> Refresh center
        </button>
        <button type="button" onClick={() => navigate(`/datasets/${id}`)} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">Back to dataset</button>
      </div>
    </main>
  );
};

function SummaryValue({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-lg border border-slate-200 bg-white p-3">
    <p className="text-[10px] text-slate-500">{label}</p>
    <p className="mt-1 text-sm font-semibold text-slate-900">{value}</p>
  </div>;
}
