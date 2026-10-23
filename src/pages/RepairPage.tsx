import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Clock3, Download, FileCheck2, LoaderCircle, ShieldAlert, Wrench } from 'lucide-react';
import { SeverityBadge } from '../components/common/SeverityBadge';
import {
  generateCombinedCleanedDataset,
  getDatasetOperationHistory,
  getFindingTypeLabel,
  getFindings,
  quarantineFinding,
  repairFinding,
  downloadOperationOutput,
} from '../services/api';
import type { OperationOutputDownload } from '../services/api';
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

export function canDownloadOperation(operation: DatasetOperationRecord): boolean {
  return (
    typeof operation.id === 'string' &&
    operation.id.trim().length > 0 &&
    operation.status.trim().toLowerCase() === 'completed' &&
    (
      operation.operationType === 'repair' ||
      operation.operationType === 'quarantine' ||
      operation.operationType === 'combined_repair'
    )
  );
}

export function getEligibleCombinedRepairFindings(
  findings: PersistedFinding[],
  datasetId: string | null | undefined,
  history: DatasetOperationRecord[]
): PersistedFinding[] {
  if (!datasetId?.trim()) return [];

  const alreadyRepaired = new Set(
    history
      .filter(
        (operation) =>
          operation.status.trim().toLowerCase() === 'completed' &&
          operation.operationType === 'repair' &&
          typeof operation.findingId === 'string'
      )
      .map((operation) => operation.findingId as string)
  );
  for (const operation of history) {
    if (
      operation.status.trim().toLowerCase() === 'completed' &&
      operation.operationType === 'combined_repair'
    ) {
      operation.operationMetadata?.appliedFindingIds.forEach((findingId) =>
        alreadyRepaired.add(findingId)
      );
    }
  }

  return findings.filter(
    (finding) =>
      finding.datasetId === datasetId &&
      finding.findingType === 'exact_duplicate' &&
      finding.status.trim().toLowerCase() === 'open' &&
      getSupportedFindingOperations(finding, datasetId).includes('repair') &&
      !alreadyRepaired.has(finding.id)
  );
}

export function validateCombinedRepairSelection(
  selectedFindingIds: string[]
): string | null {
  return selectedFindingIds.length === 0
    ? 'Select at least one eligible exact-duplicate finding.'
    : null;
}

export function saveDownloadedFile(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  try {
    anchor.click();
  } finally {
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  }
}

export async function downloadOperationToBrowser(
  operationId: string,
  loadOutput: (id: string) => Promise<OperationOutputDownload> = downloadOperationOutput,
  saveFile: (blob: Blob, filename: string) => void = saveDownloadedFile
): Promise<void> {
  const output = await loadOutput(operationId);
  saveFile(output.blob, output.filename);
}

function downloadErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : 'The output could not be downloaded.';
  if (/\(404\)/.test(message)) {
    return 'The generated output file is missing from storage and could not be downloaded.';
  }
  if (/integrity verification/i.test(message)) {
    return 'The generated output failed its SHA-256 integrity check and was not downloaded.';
  }
  return message;
}

interface RepairPageViewProps {
  datasetId: string | null;
  findings: PersistedFinding[];
  history: DatasetOperationRecord[];
  loading: boolean;
  loadError: string | null;
  operationError: string | null;
  activeOperationKey: string | null;
  downloadingOperationId: string | null;
  downloadError: { operationId: string; message: string } | null;
  eligibleCombinedFindings: PersistedFinding[];
  selectedCombinedFindingIds: string[];
  combinedRepairLoading: boolean;
  combinedRepairError: string | null;
  onRunOperation: (finding: PersistedFinding, operationType: FindingOperationType) => void;
  onDownloadOperation: (operation: DatasetOperationRecord) => void;
  onToggleCombinedFinding: (findingId: string) => void;
  onGenerateCombinedRepair: () => void;
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
  downloadingOperationId,
  downloadError,
  eligibleCombinedFindings,
  selectedCombinedFindingIds,
  combinedRepairLoading,
  combinedRepairError,
  onRunOperation,
  onDownloadOperation,
  onToggleCombinedFinding,
  onGenerateCombinedRepair,
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
              Completed repair, combined-repair, and quarantine operations can download their
              separate output files while those files remain available in storage.
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

          <section
            className="space-y-4 rounded-xl border border-teal-200 bg-white p-5 shadow-xs"
            data-testid="combined-repair"
          >
            <div>
              <h2 className="text-sm font-semibold text-slate-900">
                Combined cleaned dataset
              </h2>
              <p className="mt-1 text-xs text-slate-600">
                Select open, eligible exact-duplicate findings. One processed copy will be
                generated from the original dataset; the original remains unchanged.
              </p>
            </div>

            {eligibleCombinedFindings.length === 0 ? (
              <p className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
                No unrepaired, open exact-duplicate findings with current row evidence are eligible.
              </p>
            ) : (
              <fieldset disabled={combinedRepairLoading} className="space-y-2">
                <legend className="sr-only">Select findings for combined repair</legend>
                {eligibleCombinedFindings.map((finding) => (
                  <label
                    key={finding.id}
                    className="flex cursor-pointer items-start gap-2 rounded border border-slate-200 p-3 text-xs"
                  >
                    <input
                      type="checkbox"
                      checked={selectedCombinedFindingIds.includes(finding.id)}
                      onChange={() => onToggleCombinedFinding(finding.id)}
                      aria-label={`Include finding ${finding.id}`}
                    />
                    <span>
                      <span className="font-semibold text-slate-800">
                        {getFindingTypeLabel(finding.findingType)}
                      </span>
                      <span className="mt-1 block break-all font-mono text-[11px] text-slate-500">
                        {finding.id}
                      </span>
                      <span className="mt-1 block text-slate-600">{finding.description}</span>
                    </span>
                  </label>
                ))}
              </fieldset>
            )}

            {selectedCombinedFindingIds.length === 0 && eligibleCombinedFindings.length > 0 && (
              <p role="status" className="text-xs text-slate-600">
                {validateCombinedRepairSelection(selectedCombinedFindingIds)}
              </p>
            )}
            {combinedRepairError && (
              <p role="alert" className="text-xs text-rose-700">{combinedRepairError}</p>
            )}
            <button
              type="button"
              disabled={combinedRepairLoading || selectedCombinedFindingIds.length === 0}
              onClick={onGenerateCombinedRepair}
              className="inline-flex items-center gap-2 rounded-lg bg-teal-700 px-3 py-2 text-xs font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {combinedRepairLoading && <LoaderCircle className="h-3.5 w-3.5 animate-spin" />}
              {combinedRepairLoading
                ? 'Generating combined cleaned dataset…'
                : 'Generate Combined Cleaned Dataset'}
            </button>
          </section>

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
                            : operation.operationType === 'combined_repair'
                              ? 'Combined cleaned dataset'
                            : `Operation (${operation.operationType})`}
                      </h3>
                    </div>
                    <span className="rounded border border-slate-200 px-2 py-0.5 text-[10px] font-mono uppercase text-slate-600">
                      {operation.status}
                    </span>
                  </div>

                  {operation.operationType === 'combined_repair' && (
                    <p className="mt-2 break-all font-mono text-[11px] text-slate-500">
                      Operation ID: {operation.id}
                    </p>
                  )}
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
                        : operation.operationType === 'combined_repair'
                          ? 'Duplicate rows removed from combined processed copy'
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
                  {operation.operationType === 'combined_repair' && operation.operationMetadata && (
                    <div className="mt-3 space-y-1 rounded-lg bg-teal-50 p-3 text-xs text-slate-700">
                      <p>Original data rows: <strong>{operation.operationMetadata.originalRowCount}</strong></p>
                      <p>Final data rows: <strong>{operation.operationMetadata.finalRowCount}</strong></p>
                      <p>Duplicate rows removed: <strong>{operation.operationMetadata.duplicateRowsRemoved}</strong></p>
                      <p className="break-all">
                        Applied findings:{' '}
                        {operation.operationMetadata.appliedFindingIds.length
                          ? operation.operationMetadata.appliedFindingIds.join(', ')
                          : 'None'}
                      </p>
                      {operation.operationMetadata.skippedFindings.length > 0 && (
                        <div>
                          <p className="font-semibold">Skipped findings:</p>
                          <ul className="list-disc pl-5">
                            {operation.operationMetadata.skippedFindings.map((skipped) => (
                              <li key={skipped.findingId} className="break-all">
                                {skipped.findingId}: {skipped.reason}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
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
                  {canDownloadOperation(operation) && (
                    <div className="mt-3">
                      <button
                        type="button"
                        disabled={downloadingOperationId !== null}
                        onClick={() => onDownloadOperation(operation)}
                        className="inline-flex items-center gap-2 rounded-lg border border-teal-700 px-3 py-2 text-xs font-semibold text-teal-800 transition-colors hover:bg-teal-50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Download className="h-3.5 w-3.5" />
                        {downloadingOperationId === operation.id
                          ? 'Preparing download…'
                          : operation.operationType === 'combined_repair'
                            ? 'Download Final Dataset'
                            : 'Download output'}
                      </button>
                      {downloadError?.operationId === operation.id && (
                        <p role="alert" className="mt-2 text-xs text-rose-700">
                          {downloadError.message}
                        </p>
                      )}
                    </div>
                  )}
                </article>
              ))
            )}
          </section>

          {completedHistory.length > 0 && (
            <p className="text-xs text-slate-500">
              Downloading an operation output does not retrain models or evaluate performance.
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
  const [downloadingOperationId, setDownloadingOperationId] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<{
    operationId: string;
    message: string;
  } | null>(null);
  const [selectedCombinedFindingIds, setSelectedCombinedFindingIds] = useState<string[]>([]);
  const [combinedRepairLoading, setCombinedRepairLoading] = useState(false);
  const [combinedRepairError, setCombinedRepairError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const operationInFlight = useRef(false);
  const downloadInFlight = useRef(false);
  const combinedRepairInFlight = useRef(false);

  useEffect(() => {
    let current = true;
    setOperationError(null);
    setCombinedRepairError(null);
    setSelectedCombinedFindingIds([]);
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

  const handleDownloadOperation = useCallback(async (operation: DatasetOperationRecord) => {
    if (!canDownloadOperation(operation) || downloadInFlight.current) return;

    downloadInFlight.current = true;
    setDownloadingOperationId(operation.id);
    setDownloadError(null);
    try {
      await downloadOperationToBrowser(operation.id);
    } catch (error) {
      setDownloadError({
        operationId: operation.id,
        message: downloadErrorMessage(error),
      });
    } finally {
      downloadInFlight.current = false;
      setDownloadingOperationId(null);
    }
  }, []);

  const eligibleCombinedFindings = getEligibleCombinedRepairFindings(
    findings,
    id,
    history
  );

  const handleToggleCombinedFinding = useCallback((findingId: string) => {
    setCombinedRepairError(null);
    setSelectedCombinedFindingIds((previous) =>
      previous.includes(findingId)
        ? previous.filter((selectedId) => selectedId !== findingId)
        : [...previous, findingId]
    );
  }, []);

  const handleGenerateCombinedRepair = useCallback(async () => {
    if (!id || combinedRepairInFlight.current) return;
    const selectionError = validateCombinedRepairSelection(selectedCombinedFindingIds);
    if (selectionError) {
      setCombinedRepairError(selectionError);
      return;
    }
    const eligibleIds = new Set(
      getEligibleCombinedRepairFindings(findings, id, history).map((finding) => finding.id)
    );
    if (selectedCombinedFindingIds.some((findingId) => !eligibleIds.has(findingId))) {
      setCombinedRepairError(
        'One or more selected findings are no longer eligible. Reload findings before retrying.'
      );
      return;
    }

    combinedRepairInFlight.current = true;
    setCombinedRepairLoading(true);
    setCombinedRepairError(null);
    try {
      const result = await generateCombinedCleanedDataset(id, selectedCombinedFindingIds);
      if (
        result.datasetId !== id ||
        result.operationType !== 'combined_repair' ||
        result.status.toLowerCase() !== 'completed' ||
        !result.operationMetadata
      ) {
        throw new Error('Backend returned an incomplete combined-repair operation record.');
      }
      setHistory((previous) => [
        result,
        ...previous.filter((operation) => operation.id !== result.id),
      ]);
      setSelectedCombinedFindingIds([]);
    } catch (error) {
      setCombinedRepairError(
        error instanceof Error
          ? error.message
          : 'Failed to generate the combined cleaned dataset.'
      );
    } finally {
      combinedRepairInFlight.current = false;
      setCombinedRepairLoading(false);
    }
  }, [findings, history, id, selectedCombinedFindingIds]);

  return (
    <RepairPageView
      datasetId={id ?? null}
      findings={findings}
      history={history}
      loading={loading}
      loadError={loadError}
      operationError={operationError}
      downloadingOperationId={downloadingOperationId}
      downloadError={downloadError}
      eligibleCombinedFindings={eligibleCombinedFindings}
      selectedCombinedFindingIds={selectedCombinedFindingIds}
      combinedRepairLoading={combinedRepairLoading}
      combinedRepairError={combinedRepairError}
      activeOperationKey={
        activeOperationKey
          ? activeOperationKey
          : operationInFlight.current
            ? 'pending'
            : null
      }
      onRunOperation={handleRunOperation}
      onDownloadOperation={handleDownloadOperation}
      onToggleCombinedFinding={handleToggleCombinedFinding}
      onGenerateCombinedRepair={handleGenerateCombinedRepair}
      onRetry={() => setRetryCount((count) => count + 1)}
    />
  );
};
