import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowRight, CheckCircle2, Clock, Play, RotateCcw } from 'lucide-react';
import { buildAnalysisStages, getDatasetById, runDatasetAnalysis } from '../services/api';
import { AnalysisResult, Dataset } from '../types';
import { useToast } from '../context/ToastContext';
import { getDatasetWorkflowPath } from '../services/datasetNavigation';

type ColumnSelection = 'targetColumn' | 'entityColumn' | 'splitColumn' | 'timeColumn';

const columnSelectors: Array<{
  key: ColumnSelection;
  label: string;
  help: string;
}> = [
  {
    key: 'targetColumn',
    label: 'Target column',
    help: 'Select the label/outcome to check for deterministic feature-to-target associations.'
  },
  {
    key: 'entityColumn',
    label: 'Entity / identifier column',
    help: 'Entity-overlap detection also requires a split column.'
  },
  {
    key: 'splitColumn',
    label: 'Train/test or split column',
    help: 'Enables train/test contamination detection; also required for entity and temporal checks.'
  },
  {
    key: 'timeColumn',
    label: 'Timestamp / time column',
    help: 'Temporal leakage detection also requires a split column.'
  }
];

const statusLabels: Record<string, string> = {
  not_run: 'Not run',
  needs_configuration: 'Needs configuration',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  skipped: 'Skipped'
};

export const AnalysisPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { success, error } = useToast();
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [isLoadingDataset, setIsLoadingDataset] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [attemptedOptions, setAttemptedOptions] = useState<{
    entityColumn?: string;
    splitColumn?: string;
    targetColumn?: string;
    timeColumn?: string;
  } | null>(null);
  const [selection, setSelection] = useState<Record<ColumnSelection, string>>({
    targetColumn: '',
    entityColumn: '',
    splitColumn: '',
    timeColumn: ''
  });

  useEffect(() => {
    let active = true;
    setIsLoadingDataset(true);
    setLoadError(null);
    setDataset(null);
    setAnalysisResult(null);
    setAnalysisError(null);
    setAttemptedOptions(null);
    setSelection({
      targetColumn: '',
      entityColumn: '',
      splitColumn: '',
      timeColumn: ''
    });

    if (!id) {
      setLoadError('No dataset was selected.');
      setIsLoadingDataset(false);
      return () => { active = false; };
    }

    getDatasetById(id)
      .then((result) => {
        if (!active) return;
        if (!result) {
          setLoadError('Dataset not found.');
        } else {
          setDataset(result);
        }
      })
      .catch((err: unknown) => {
        if (active) setLoadError(err instanceof Error ? err.message : 'Unable to load this dataset.');
      })
      .finally(() => {
        if (active) setIsLoadingDataset(false);
      });

    return () => { active = false; };
  }, [id]);

  const options = useMemo(() => ({
    ...(selection.entityColumn ? { entityColumn: selection.entityColumn } : {}),
    ...(selection.splitColumn ? { splitColumn: selection.splitColumn } : {}),
    ...(selection.targetColumn ? { targetColumn: selection.targetColumn } : {}),
    ...(selection.timeColumn ? { timeColumn: selection.timeColumn } : {})
  }), [selection]);

  const updateSelection = (key: ColumnSelection, value: string) => {
    setSelection((previous) => ({ ...previous, [key]: value }));
    setAnalysisResult(null);
    setAnalysisError(null);
    setAttemptedOptions(null);
  };

  const startAnalysis = async () => {
    if (!id || !dataset || isRunning || !isTabular(dataset)) return;
    setIsRunning(true);
    setAnalysisError(null);
    setAnalysisResult(null);
    setAttemptedOptions(options);

    try {
      const result = await runDatasetAnalysis(id, options);
      setAnalysisResult(result);
      success(
        'Analysis request completed',
        `${result.findings.length} persisted finding${result.findings.length === 1 ? '' : 's'} returned. Only configured detectors were requested.`
      );
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'The backend analysis request failed.';
      setAnalysisError(message);
      error('Analysis failed', message);
    } finally {
      setIsRunning(false);
    }
  };

  const stageOptions = attemptedOptions ?? options;
  const stages = analysisResult?.stages ?? buildAnalysisStages(
    {},
    stageOptions,
    isRunning ? 'running' : analysisError ? 'failed' : 'not_started'
  );
  const completedCount = stages.filter((stage) => stage.status === 'completed').length;
  const attemptedCount = stages.filter((stage) =>
    ['completed', 'failed', 'running'].includes(stage.status)
  ).length;
  const isCompleted = analysisResult !== null && !isRunning;
  const columns = dataset?.columns ?? [];

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-in fade-in duration-200">
      <header className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <span className="text-xs font-mono text-teal-700 uppercase tracking-wider font-semibold">
            Pipeline Execution Node
          </span>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 font-mono mt-1">
            Leakage Analysis
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Configure optional columns for {dataset?.name || id || 'the selected dataset'}. Exact-duplicate detection always runs.
          </p>
        </div>
        {isCompleted && id && (
          <button
            onClick={() => navigate(getDatasetWorkflowPath('findings', id))}
            className="px-4 py-2 text-xs font-semibold rounded-lg bg-teal-700 hover:bg-teal-800 text-white transition-colors flex items-center gap-2"
          >
            View persisted findings <ArrowRight className="w-4 h-4" />
          </button>
        )}
      </header>

      {isLoadingDataset ? (
        <div className="p-5 bg-white border border-slate-200 rounded-xl text-sm text-slate-500" role="status">
          Loading dataset columns…
        </div>
      ) : loadError ? (
        <div className="p-5 bg-rose-50 border border-rose-200 rounded-xl text-sm text-rose-800" role="alert">
          {loadError}
        </div>
      ) : dataset && !isTabular(dataset) ? (
        <div className="p-5 bg-amber-50 border border-amber-200 rounded-xl text-sm text-amber-900">
          Leakage analysis is supported here only for CSV and XLSX tabular datasets. This dataset is {dataset.format}.
        </div>
      ) : dataset ? (
        <>
          <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
            <h2 className="text-sm font-semibold text-slate-900">Detector column configuration</h2>
            <p className="text-xs text-slate-500 mt-1">
              Select only columns relevant to this dataset. Unselected optional detectors will not run.
              A deterministic target association is a signal for review, not proof of causal leakage.
            </p>
            {columns.length === 0 && (
              <p className="mt-3 text-xs text-amber-800" role="status">
                Column metadata is unavailable; optional detectors cannot be configured. Exact duplicates can still run.
              </p>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
              {columnSelectors.map(({ key, label, help }) => (
                <label key={key} className="block">
                  <span className="block text-xs font-medium text-slate-700 mb-1">{label}</span>
                  <select
                    value={selection[key]}
                    onChange={(event) => updateSelection(key, event.target.value)}
                    disabled={columns.length === 0 || isRunning}
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 disabled:bg-slate-100"
                  >
                    <option value="">Not selected</option>
                    {columns.map((column) => (
                      <option key={`${key}-${column.name}`} value={column.name}>{column.name}</option>
                    ))}
                  </select>
                  <span className="block text-[11px] text-slate-500 mt-1">{help}</span>
                </label>
              ))}
            </div>
            <div className="mt-5 flex justify-end">
              <button
                onClick={() => void startAnalysis()}
                disabled={isRunning || isLoadingDataset}
                className="px-4 py-2 text-xs font-semibold rounded-lg bg-teal-700 hover:bg-teal-800 text-white disabled:opacity-50 flex items-center gap-2"
              >
                {isRunning
                  ? <Clock className="w-4 h-4 animate-spin" />
                  : analysisResult
                    ? <RotateCcw className="w-4 h-4" />
                    : <Play className="w-4 h-4" />}
                {isRunning ? 'Analysis running…' : analysisResult ? 'Run again' : 'Run configured analysis'}
              </button>
            </div>
          </section>

          <section className="p-5 bg-white border border-slate-200 rounded-xl shadow-xs" aria-live="polite">
            <div className="flex items-center justify-between gap-4 mb-3">
              <div>
                <h2 className="text-sm font-semibold text-slate-900">
                  {isRunning ? 'Backend analysis request in progress' : isCompleted ? 'Analysis request completed' : 'Analysis stages'}
                </h2>
                <p className="text-xs text-slate-500 mt-1">
                  {isCompleted
                    ? `${analysisResult.summary.totalFindings} finding${analysisResult.summary.totalFindings === 1 ? '' : 's'} returned by the backend.`
                    : 'Only a successful backend response marks configured detectors completed.'}
                </p>
              </div>
              <span className="text-xs font-mono font-bold text-teal-800 whitespace-nowrap">
                {attemptedCount
                  ? `${completedCount}/${attemptedCount} configured detectors completed`
                  : 'Not run yet'}
              </span>
            </div>
            <div className="h-2 w-full rounded-full bg-slate-200 overflow-hidden">
              <div
                className="h-full bg-teal-600 transition-all"
                style={{ width: `${attemptedCount ? (completedCount / attemptedCount) * 100 : 0}%` }}
              />
            </div>

            <div className="mt-4 divide-y divide-slate-100">
              {stages.map((stage) => (
                <div key={stage.id} className="py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <p className="text-xs font-semibold text-slate-900">{stage.name}</p>
                    <p className="text-[11px] text-slate-500">{stage.description}</p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    {stage.status === 'completed' && (
                      <span className="text-[11px] text-emerald-700 font-mono">
                        {stage.findingsCount} findings
                      </span>
                    )}
                    {stage.status === 'failed' && <AlertTriangle className="w-4 h-4 text-rose-600" />}
                    {stage.status === 'completed' && <CheckCircle2 className="w-4 h-4 text-emerald-600" />}
                    {stage.status === 'running' && <Clock className="w-4 h-4 text-teal-600 animate-spin" />}
                    <span className={`text-[11px] font-mono ${
                      stage.status === 'failed' ? 'text-rose-700' :
                      stage.status === 'needs_configuration' ? 'text-amber-700' :
                      stage.status === 'completed' ? 'text-emerald-700' : 'text-slate-500'
                    }`}>
                      {statusLabels[stage.status]}
                    </span>
                  </div>
                </div>
              ))}
            </div>

            {analysisError && (
              <p className="mt-3 p-3 bg-rose-50 border border-rose-200 rounded-lg text-xs text-rose-800" role="alert">
                {analysisError}
              </p>
            )}
          </section>

          {analysisResult && (
            <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
              <h2 className="text-sm font-semibold text-slate-900">Findings returned by this analysis</h2>
              {analysisResult.findings.length === 0 ? (
                <p className="mt-2 text-xs text-slate-500">
                  No findings were returned for this request. Detectors that were not requested were not evaluated.
                </p>
              ) : (
                <div className="mt-3 space-y-3">
                  {analysisResult.findings.map((finding) => (
                    <details key={finding.id} className="border border-slate-200 rounded-lg p-3">
                      <summary className="cursor-pointer text-xs font-semibold text-slate-800">
                        {finding.findingType} · {finding.severity} · {finding.status}
                      </summary>
                      <p className="mt-2 text-xs text-slate-700">{finding.description}</p>
                      <p className="mt-1 text-[11px] text-slate-500">Finding ID: {finding.id}</p>
                      <h3 className="mt-3 text-[11px] font-semibold text-slate-700">Backend evidence</h3>
                      {finding.evidence
                        ? <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 text-[11px] text-slate-700">{JSON.stringify(finding.evidence, null, 2)}</pre>
                        : <p className="mt-1 text-[11px] text-slate-500">No evidence object was returned.</p>}
                    </details>
                  ))}
                </div>
              )}
            </section>
          )}
        </>
      ) : null}
    </div>
  );
};

function isTabular(dataset: Dataset): boolean {
  return dataset.format === 'CSV' || dataset.format === 'XLSX';
}
