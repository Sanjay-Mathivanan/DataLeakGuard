import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Clock3, FileCheck2, LoaderCircle, ShieldAlert, Wrench } from 'lucide-react';
import { SeverityBadge } from '../components/common/SeverityBadge';
import {
  getDatasetOperationHistory,
  getFindingTypeLabel,
  getFindings,
  quarantineFinding,
  repairFinding,
} from '../services/api';
import {
  DatasetOperationRecord,
  FindingOperationType,
  PersistedFinding,
} from '../types';

export function getSupportedFindingOperations(
  finding: PersistedFinding,
  datasetId: string | null | undefined
): FindingOperationType[] {
  if (!datasetId?.trim() || !finding.id.trim() || finding.datasetId !== datasetId) {
    return [];
  }

  const rowIndices = finding.evidence?.row_indices;
  const isValidIndex = (index: unknown): index is number =>
    typeof index === 'number' && Number.isInteger(index) && index >= 0;

  if (finding.findingType === 'exact_duplicate') {
    if (!Array.isArray(rowIndices) || rowIndices.length === 0 || !rowIndices.every(isValidIndex)) {
      return [];
    }

    const operations: FindingOperationType[] = ['quarantine'];
    const duplicateCount = finding.evidence?.duplicate_count;
    if (
      rowIndices.length > 1 &&
      typeof duplicateCount === 'number' &&
      Number.isInteger(duplicateCount) &&
      duplicateCount > 0
    ) {
      operations.unshift('repair');
    }
    return operations;
  }
  if (
    finding.findingType === 'entity_overlap' ||
    finding.findingType === 'train_test_contamination'
  ) {
    if (
      !rowIndices ||
      typeof rowIndices !== 'object' ||
      Array.isArray(rowIndices)
    ) {
      return [];
    }
    const splitIndices = Object.values(rowIndices as Record<string, unknown>);
    if (
      splitIndices.length === 0 ||
      !splitIndices.every(
        (indices) => Array.isArray(indices) && indices.every(isValidIndex)
      ) ||
      !splitIndices.some((indices) => (indices as unknown[]).length > 0)
    ) {
      return [];
    }
    return ['quarantine'];
  }
  return [];
}

function operationKey(findingId: string, operationType: FindingOperationType): string {
  return `${operationType}:${findingId}`;
}

function getRecordedOperation(
  findingId: string,
  operationType: FindingOperationType,
  history: DatasetOperationRecord[]
): DatasetOperationRecord | undefined {
  return history.find(
    (operation) =>
      operation.findingId === findingId &&
      operation.operationType === operationType
  );
}

interface RepairPageViewProps {
  datasetId: string | null;
  findings: PersistedFinding[];
  history: DatasetOperationRecord[];
  loading: boolean;
  loadError: string | null;
  operationError: string | null;
  activeOperationKey: string | null;
  onRunOperation: (finding: PersistedFinding, operationType: FindingOperationType) => void;
  onRetry: () => void;
}

export const RepairPageView: React.FC<RepairPageViewProps> = ({
  datasetId,
  findings,
  history,
  loading,
  loadError,
  operationError,
  activeOperationKey,
  onRunOperation,
  onRetry,
}) => {
  const completedHistory = history.filter(
    (operation) => operation.status.toLowerCase() === 'completed'
  );

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header>
        <span className="text-xs font-mono font-semibold uppercase tracking-wider text-teal-700">
          Evidence-based operations
        </span>
        <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">
          Repair &amp; Quarantine
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          Operations use persisted findings for this dataset. They create separate output files;
          the uploaded original dataset is not modified.
        </p>
      </header>

      <section className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
        <div className="flex items-start gap-2">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="space-y-1">
            <p>
              Quarantine writes only the finding&apos;s affected rows to a separate output file.
              Exact-duplicate repair writes a processed copy with later duplicate rows removed.
            </p>
            <p>
              Downloads are not available yet: the current API returns operation metadata, not a
              file response or a downloadable URL.
            </p>
          </div>
        </div>
      </section>

      {!datasetId && !loading && (
        <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          No dataset identifier is available. Open this page from a dataset with a persisted ID.
        </div>
      )}

      {loading && (
        <div role="status" className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-5 text-sm text-slate-600">
          <LoaderCircle className="h-4 w-4 animate-spin" />
          Loading persisted findings and operation history…
        </div>
      )}

      {!loading && loadError && (
        <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          <p>{loadError}</p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 rounded border border-rose-300 bg-white px-3 py-1.5 text-xs font-semibold hover:bg-rose-100"
          >
            Retry loading
          </button>
        </div>
      )}

      {!loading && !loadError && datasetId && (
        <>
          {operationError && (
            <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
              {operationError}
            </div>
          )}

          <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-xs">
            <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
              <Wrench className="h-4 w-4 text-teal-700" />
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Persisted findings</h2>
                <p className="text-xs text-slate-500">Dataset ID: {datasetId}</p>
              </div>
            </div>

            {findings.length === 0 ? (
              <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-600">
                No persisted findings are available for this dataset. An empty list does not
                establish that every detector ran successfully.
              </p>
            ) : (
              findings.map((finding) => {
                const supportedOperations = getSupportedFindingOperations(finding, datasetId);
                return (
                  <article
                    key={finding.id}
                    className="rounded-lg border border-slate-200 p-4"
                    data-testid={`finding-${finding.id}`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h3 className="text-sm font-semibold text-slate-900">
                          {getFindingTypeLabel(finding.findingType)}
                        </h3>
                        <p className="mt-1 break-all font-mono text-[11px] text-slate-500">
                          Finding ID: {finding.id}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <SeverityBadge severity={finding.severity} size="sm" />
                        <span className="rounded border border-slate-200 px-2 py-0.5 text-[10px] font-mono uppercase text-slate-600">
                          {finding.status}
                        </span>
                      </div>
                    </div>
                    <p className="mt-3 text-sm text-slate-700">{finding.description}</p>
                    {finding.createdAt && (
                      <p className="mt-2 text-[11px] text-slate-500">
                        Finding created: {finding.createdAt}
                      </p>
                    )}

                    <div className="mt-4 flex flex-wrap gap-2">
                      {supportedOperations.map((operationType) => {
                        const recordedOperation = getRecordedOperation(
                          finding.id,
                          operationType,
                          history
                        );
                        const active = activeOperationKey === operationKey(finding.id, operationType);
                        const disabled = activeOperationKey !== null || recordedOperation !== undefined;
                        const label =
                          operationType === 'repair'
                            ? 'Create duplicate-repaired copy'
                            : 'Create quarantine output';

                        return (
                          <button
                            key={operationType}
                            type="button"
                            disabled={disabled}
                            onClick={() => onRunOperation(finding, operationType)}
                            className="rounded-lg bg-teal-700 px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {active
                              ? 'Operation in progress…'
                              : recordedOperation
                                ? `${label} (${recordedOperation.status})`
                                : label}
                          </button>
                        );
                      })}
                      {supportedOperations.length === 0 && (
                        <p className="text-xs text-slate-500">
                          No automated operation is available. The finding type, dataset ID, and
                          required deterministic row-index evidence must all be supported.
                        </p>
                      )}
                    </div>
                  </article>
                );
              })
            )}
          </section>

          <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-xs">
            <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
              <Clock3 className="h-4 w-4 text-slate-600" />
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Operation history</h2>
                <p className="text-xs text-slate-500">Values below come from the backend operation records.</p>
              </div>
            </div>

            {history.length === 0 ? (
              <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-600">
                No repair or quarantine operations are recorded for this dataset.
              </p>
            ) : (
              history.map((operation) => (
                <article
                  key={operation.id}
                  className="rounded-lg border border-slate-200 p-4"
                  data-testid={`operation-${operation.id}`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <FileCheck2 className="h-4 w-4 text-teal-700" />
                      <h3 className="text-sm font-semibold text-slate-900">
                        {operation.operationType === 'quarantine'
                          ? 'Quarantine output'
                          : operation.operationType === 'repair'
                            ? 'Exact-duplicate processed copy'
                            : `Operation (${operation.operationType})`}
                      </h3>
                    </div>
                    <span className="rounded border border-slate-200 px-2 py-0.5 text-[10px] font-mono uppercase text-slate-600">
                      {operation.status}
                    </span>
                  </div>

                  {operation.findingId && (
                    <p className="mt-2 break-all font-mono text-[11px] text-slate-500">
                      Finding ID: {operation.findingId}
                    </p>
                  )}
                  {operation.outputFilename && (
                    <p className="mt-2 break-all text-xs text-slate-700">
                      Output filename: <span className="font-mono">{operation.outputFilename}</span>
                    </p>
                  )}
                  {typeof operation.affectedRows === 'number' && operation.affectedRows > 0 && (
                    <p className="mt-1 text-xs text-slate-700">
                      {operation.operationType === 'quarantine'
                        ? 'Rows written to separate quarantine output'
                        : 'Later duplicate rows removed from processed copy'}
                      : <span className="font-mono">{operation.affectedRows}</span>
                    </p>
                  )}
                  {!(typeof operation.affectedRows === 'number' && operation.affectedRows > 0) && (
                    <p className="mt-1 text-xs text-slate-500">
                      Affected-row count was not available in this operation response.
                    </p>
                  )}
                  {operation.inputFileSha256 && (
                    <p className="mt-2 break-all text-[11px] text-slate-500">
                      Input SHA-256: <code>{operation.inputFileSha256}</code>
                    </p>
                  )}
                  {operation.outputFileSha256 && (
                    <p className="mt-1 break-all text-[11px] text-slate-500">
                      Output SHA-256: <code>{operation.outputFileSha256}</code>
                    </p>
                  )}
                  {operation.createdAt && (
                    <p className="mt-2 text-[11px] text-slate-500">
                      Created: {operation.createdAt}
                    </p>
                  )}
                  {operation.completedAt && (
                    <p className="mt-1 text-[11px] text-slate-500">
                      Completed: {operation.completedAt}
                    </p>
                  )}
                </article>
              ))
            )}
          </section>

          {completedHistory.length > 0 && (
            <p className="text-xs text-slate-500">
              Completed operations are shown as records only. This page does not retrain models or
              evaluate performance.
            </p>
          )}
        </>
      )}
    </div>
  );
};

export const RepairPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [findings, setFindings] = useState<PersistedFinding[]>([]);
  const [history, setHistory] = useState<DatasetOperationRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [activeOperationKey, setActiveOperationKey] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const operationInFlight = useRef(false);

  useEffect(() => {
    let current = true;
    setOperationError(null);
    if (!id?.trim()) {
      setFindings([]);
      setHistory([]);
      setLoadError(null);
      setLoading(false);
      return () => {
        current = false;
      };
    }

    setLoading(true);
    setLoadError(null);
    Promise.all([getFindings(id), getDatasetOperationHistory(id)])
      .then(([persistedFindings, operationHistory]) => {
        if (current) {
          setFindings(persistedFindings);
          setHistory(operationHistory);
        }
      })
      .catch((error: unknown) => {
        if (current) {
          setLoadError(
            error instanceof Error ? error.message : 'Failed to load persisted repair data.'
          );
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });

    return () => {
      current = false;
    };
  }, [id, retryCount]);

  const handleRunOperation = useCallback(
    async (finding: PersistedFinding, operationType: FindingOperationType) => {
      if (
        !id ||
        !getSupportedFindingOperations(finding, id).includes(operationType) ||
        operationInFlight.current ||
        getRecordedOperation(finding.id, operationType, history)
      ) {
        return;
      }

      operationInFlight.current = true;
      setActiveOperationKey(operationKey(finding.id, operationType));
      setOperationError(null);
      try {
        const result =
          operationType === 'repair'
            ? await repairFinding(finding.id)
            : await quarantineFinding(finding.id);

        if (
          result.datasetId !== id ||
          result.findingId !== finding.id ||
          result.operationType !== operationType
        ) {
          throw new Error('Backend returned an operation that does not match the requested finding.');
        }
        setHistory((previous) => [
          result,
          ...previous.filter((operation) => operation.id !== result.id),
        ]);
      } catch (error) {
        setOperationError(
          error instanceof Error ? error.message : `Failed to ${operationType} this finding.`
        );
      } finally {
        operationInFlight.current = false;
        setActiveOperationKey(null);
      }
    },
    [history, id]
  );

  return (
    <RepairPageView
      datasetId={id ?? null}
      findings={findings}
      history={history}
      loading={loading}
      loadError={loadError}
      operationError={operationError}
      activeOperationKey={
        activeOperationKey
          ? activeOperationKey
          : operationInFlight.current
            ? 'pending'
            : null
      }
      onRunOperation={handleRunOperation}
      onRetry={() => setRetryCount((count) => count + 1)}
    />
  );
};
