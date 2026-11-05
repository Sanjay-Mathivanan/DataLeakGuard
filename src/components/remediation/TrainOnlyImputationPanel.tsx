import React, { useMemo, useState } from 'react';
import { CheckCircle2, Download, LoaderCircle, WandSparkles } from 'lucide-react';
import {
  downloadOperationOutput,
  executeTrainOnlyImputation,
  previewTrainOnlyImputation,
} from '../../services/api';
import type {
  Dataset,
  ImputationColumnSelection,
  ImputationMethod,
  ImputationOperation,
  ImputationPreview,
} from '../../types';

const GENERATED_SPLIT_COLUMN = '__dataleakguard_split__';
const METHODS: ImputationMethod[] = ['mean', 'median', 'mode', 'constant', 'leave_missing'];

export function availableImputationMethods(columnType: string): ImputationMethod[] {
  const normalized = columnType.toLowerCase();
  const numeric = /int|float|double|decimal|numeric|number/.test(normalized);
  return numeric
    ? METHODS
    : ['mode', 'constant', 'leave_missing'];
}

function protectedDatasetColumns(dataset: Dataset): Set<string> {
  const analysis = dataset.profile?.analysisColumns;
  return new Set([
    analysis?.targetColumn,
    analysis?.splitColumn,
    analysis?.timeColumn,
    analysis?.entityColumn,
    ...(analysis?.entityColumns ?? []),
    ...(analysis?.contaminationKeyColumns ?? []),
  ].filter((value): value is string => typeof value === 'string' && value.length > 0));
}

function isVerified(operation: ImputationOperation | null): boolean {
  return operation?.status === 'completed'
    && operation.operationMetadata.verification !== null
    && typeof operation.operationMetadata.verification === 'object'
    && (operation.operationMetadata.verification as Record<string, unknown>).status === 'verified';
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const TrainOnlyImputationPanel: React.FC<{ dataset: Dataset }> = ({ dataset }) => {
  const analysis = dataset.profile?.analysisColumns;
  const splitStrategy = dataset.profile?.splitStrategy ?? {};
  const generated = splitStrategy.strategy === 'generated';
  const splitOperationId = typeof splitStrategy.splitOperationId === 'string'
    ? splitStrategy.splitOperationId
    : undefined;
  const splitColumn = generated
    ? GENERATED_SPLIT_COLUMN
    : analysis?.splitColumn ?? '';
  const splitAvailable = generated
    ? Boolean(splitOperationId)
    : Boolean(splitColumn && dataset.columns?.some((column) => column.name === splitColumn));
  const protectedColumns = useMemo(() => protectedDatasetColumns(dataset), [dataset]);
  const missingColumns = useMemo(
    () => (dataset.columns ?? []).filter((column) => column.missingCount > 0),
    [dataset.columns],
  );
  const [trainingPartition, setTrainingPartition] = useState('train');
  const [selections, setSelections] = useState<Record<string, {
    method: ImputationMethod | '';
    constantValue: string;
  }>>({});
  const [preview, setPreview] = useState<ImputationPreview | null>(null);
  const [operation, setOperation] = useState<ImputationOperation | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloadBusy, setDownloadBusy] = useState(false);

  const selectedColumns = useMemo<ImputationColumnSelection[]>(() => (
    missingColumns.flatMap((column) => {
      const selected = selections[column.name];
      if (!selected?.method || protectedColumns.has(column.name)) return [];
      if (selected.method === 'constant' && !selected.constantValue.trim()) return [];
      return [{
        column: column.name,
        method: selected.method,
        ...(selected.method === 'constant' ? { constantValue: selected.constantValue } : {}),
      }];
    })
  ), [missingColumns, protectedColumns, selections]);

  const buildPreview = async () => {
    if (!splitAvailable || !selectedColumns.length) return;
    setBusy(true);
    setError(null);
    setOperation(null);
    setConfirmed(false);
    try {
      const result = await previewTrainOnlyImputation(dataset.id, {
        splitColumn,
        trainingPartition,
        ...(generated && splitOperationId ? { splitOperationId } : {}),
        columns: selectedColumns,
      });
      setPreview(result);
    } catch (reason: unknown) {
      setPreview(null);
      setError(reason instanceof Error ? reason.message : 'Imputation preview failed.');
    } finally {
      setBusy(false);
    }
  };

  const execute = async () => {
    if (!preview || !confirmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await executeTrainOnlyImputation(
        dataset.id,
        {
          splitColumn,
          trainingPartition,
          ...(generated && splitOperationId ? { splitOperationId } : {}),
          columns: selectedColumns,
        },
        preview.previewToken,
        true,
      );
      setOperation(result);
      setPreview(null);
      setConfirmed(false);
      if (result.status !== 'completed'
        || (result.operationMetadata.verification as Record<string, unknown> | undefined)?.status !== 'verified') {
        setError('The output did not pass post-operation verification and is not available for download.');
      }
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : 'Confirmed imputation failed.');
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    if (!operation || !isVerified(operation)) return;
    setDownloadBusy(true);
    setError(null);
    try {
      const result = await downloadOperationOutput(operation.id);
      saveBlob(result.blob, result.filename);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : 'The verified imputed copy could not be downloaded.');
    } finally {
      setDownloadBusy(false);
    }
  };

  return (
    <section className="rounded-xl border border-sky-200 bg-white p-4 shadow-sm">
      <header className="flex items-start gap-2">
        <WandSparkles className="mt-0.5 h-4 w-4 text-sky-700" />
        <div>
          <h2 className="text-sm font-semibold text-slate-900">Optional train-only missing-value preprocessing</h2>
          <p className="mt-1 text-xs text-slate-600">
            Fit selected imputers on the validated training partition only, then apply those fitted values to a separate copy. The uploaded original is unchanged.
          </p>
        </div>
      </header>

      {!splitAvailable ? (
        <p role="status" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          A validated existing split or completed generated split is required. No-split analysis cannot safely fit preprocessing values on training data.
        </p>
      ) : (
        <>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <p className="text-xs text-slate-600">
              Split: <code className="font-mono">{splitColumn}</code>
              {generated && splitOperationId ? <> · operation <code className="font-mono">{splitOperationId}</code></> : null}
            </p>
            <label className="ml-auto text-xs font-medium text-slate-700">
              Training partition
              <input
                value={trainingPartition}
                onChange={(event) => {
                  setTrainingPartition(event.target.value);
                  setPreview(null);
                  setOperation(null);
                  setConfirmed(false);
                }}
                maxLength={100}
                className="ml-2 w-28 rounded border border-slate-300 px-2 py-1"
              />
            </label>
          </div>

          {missingColumns.length === 0 ? (
            <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900">
              The persisted dataset profile reports no missing values.
            </p>
          ) : (
            <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full min-w-[620px] text-left text-xs">
                <thead className="bg-slate-50 text-[10px] uppercase tracking-wide text-slate-500">
                  <tr><th className="px-3 py-2">Column</th><th className="px-3 py-2">Missing</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Strategy</th><th className="px-3 py-2">Constant</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {missingColumns.map((column) => {
                    const isProtected = protectedColumns.has(column.name);
                    const selected = selections[column.name] ?? { method: '', constantValue: '' };
                    const denominator = dataset.sampleCount;
                    return (
                      <tr key={column.name}>
                        <td className="break-all px-3 py-2 font-mono text-slate-800">{column.name}</td>
                        <td className="px-3 py-2 text-slate-700">
                          {column.missingCount.toLocaleString()}
                          {typeof denominator === 'number' && denominator > 0
                            ? ` (${(column.missingCount / denominator * 100).toFixed(2)}%)`
                            : ' (percentage unavailable)'}
                        </td>
                        <td className="px-3 py-2 text-slate-600">{column.type}</td>
                        <td className="px-3 py-2">
                          {isProtected ? (
                            <span className="text-amber-800">Protected analysis column</span>
                          ) : (
                            <select
                              aria-label={`Imputation strategy for ${column.name}`}
                              value={selected.method}
                              onChange={(event) => {
                                const method = event.target.value as ImputationMethod | '';
                                setSelections((current) => ({
                                  ...current,
                                  [column.name]: { ...selected, method },
                                }));
                                setPreview(null);
                                setOperation(null);
                                setConfirmed(false);
                              }}
                              className="rounded border border-slate-300 bg-white px-2 py-1"
                            >
                              <option value="">Choose…</option>
                              {availableImputationMethods(column.type).map((method) => (
                                <option key={method} value={method}>{method.replace('_', ' ')}</option>
                              ))}
                            </select>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          {!isProtected && selected.method === 'constant' && (
                            <input
                              aria-label={`Constant value for ${column.name}`}
                              value={selected.constantValue}
                              onChange={(event) => {
                                setSelections((current) => ({
                                  ...current,
                                  [column.name]: { ...selected, constantValue: event.target.value },
                                }));
                                setPreview(null);
                                setOperation(null);
                                setConfirmed(false);
                              }}
                              className="w-28 rounded border border-slate-300 px-2 py-1"
                              required
                            />
                          )}
                          {isProtected && (
                            <span className="text-[10px] text-slate-500">Target, entity, configured comparison-key, timestamp and split columns are not imputed.</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <button
            type="button"
            onClick={() => void buildPreview()}
            disabled={busy || !selectedColumns.length || !trainingPartition.trim()}
            className="mt-3 flex items-center gap-2 rounded-md bg-sky-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
          >
            {busy && !preview ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : null}
            Preview train-only transformation
          </button>
        </>
      )}

      {error && <p role="alert" className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800">{error}</p>}

      {preview && (
        <div className="mt-3 space-y-3 rounded-lg border border-sky-200 bg-sky-50 p-3">
          <h3 className="text-xs font-semibold text-sky-950">Actual backend preview</h3>
          <p className="text-[11px] text-slate-700">
            {preview.fitRowCount.toLocaleString()} training rows used for fitting; output preserves {preview.expectedRowCount.toLocaleString()} rows and {preview.expectedColumnCount.toLocaleString()} columns.
          </p>
          <ul className="space-y-1 text-[11px] text-slate-700">
            {preview.strategies.map((strategy) => (
              <li key={strategy.column}>
                <code>{strategy.column}</code>: {strategy.method}
                {strategy.fittedValue !== null ? ` → ${String(strategy.fittedValue)}` : ''}
                {' · '}missing {preview.missingCountsBefore[strategy.column] ?? 0} → {preview.missingCountsAfter[strategy.column] ?? 0}
                {' · '}fitted on training rows only
              </li>
            ))}
          </ul>
          <label className="flex items-start gap-2 text-xs text-slate-700">
            <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5" />
            <span>I reviewed and confirm creation of a separate training-fitted output. No source data will be overwritten.</span>
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => void execute()} disabled={!confirmed || busy} className="rounded-md bg-emerald-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">
              {busy ? 'Executing and verifying…' : 'Confirm and create copy'}
            </button>
            <button type="button" onClick={() => { setPreview(null); setConfirmed(false); }} disabled={busy} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">
              Cancel preview
            </button>
          </div>
        </div>
      )}

      {operation && (
        <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <p className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
            {isVerified(operation) ? <CheckCircle2 className="h-4 w-4 text-emerald-700" /> : null}
            Operation {operation.id} · {isVerified(operation) ? 'verified' : operation.status}
          </p>
          {isVerified(operation) && (
            <>
              <p className="mt-1 break-all text-[10px] text-slate-600">Output SHA-256: {operation.outputFileSha256}</p>
              <button type="button" onClick={() => void download()} disabled={downloadBusy} className="mt-2 flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-50">
                <Download className="h-3.5 w-3.5" />{downloadBusy ? 'Downloading…' : 'Download verified copy'}
              </button>
            </>
          )}
        </div>
      )}
    </section>
  );
};
