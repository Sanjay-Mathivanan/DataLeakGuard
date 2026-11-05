import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, Clock, Play, RotateCcw } from 'lucide-react';
import {
  buildAnalysisStages,
  generateDatasetSplit,
  getColumnRecommendations,
  getDatasetById,
  runDatasetAnalysis,
} from '../services/api';
import {
  AnalysisResult,
  ColumnRecommendationsResponse,
  Dataset,
  DetectorColumnRole,
  SplitGenerationOperation,
} from '../types';
import { useToast } from '../context/ToastContext';
import { getDatasetWorkflowPath } from '../services/datasetNavigation';
import { GroupedFindings } from '../components/leakage/GroupedFindings';
import { SearchableColumnSelector } from '../components/analysis/SearchableColumnSelector';
import { ColumnRecommendationsPanel } from '../components/analysis/ColumnRecommendationsPanel';
import { SplitStrategy, SplitStrategyPanel } from '../components/analysis/SplitStrategyPanel';
import { findPotentialTargetDerivedFeatures } from '../components/analysis/targetFeatureWarnings';
import { loadConfirmedAnalysisSetup } from './AnalysisSetupPage';
import type { TemporalEvaluationObjective } from './AnalysisSetupPage';

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
  const [recommendations, setRecommendations] = useState<ColumnRecommendationsResponse | null>(null);
  const [recommendationsLoading, setRecommendationsLoading] = useState(false);
  const [recommendationsError, setRecommendationsError] = useState<string | null>(null);
  const [isLoadingDataset, setIsLoadingDataset] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [splitStrategy, setSplitStrategy] = useState<SplitStrategy>('none');
  const [splitRatio, setSplitRatio] = useState(0.2);
  const [splitSeed, setSplitSeed] = useState(42);
  const [splitGenerationConfirmed, setSplitGenerationConfirmed] = useState(false);
  const [isGeneratingSplit, setIsGeneratingSplit] = useState(false);
  const [splitGenerationError, setSplitGenerationError] = useState<string | null>(null);
  const [splitOperation, setSplitOperation] = useState<SplitGenerationOperation | null>(null);
  const [temporalObjective, setTemporalObjective] =
    useState<TemporalEvaluationObjective>('future_prediction');
  const [configurationConfirmed, setConfigurationConfirmed] = useState(false);
  const [setupOrigin, setSetupOrigin] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [attemptedOptions, setAttemptedOptions] = useState<{
    entityColumn?: string;
    splitColumn?: string;
    targetColumn?: string;
    timeColumn?: string;
    temporalObjective?: TemporalEvaluationObjective;
    contaminationKeyColumns?: string[];
  } | null>(null);
  const [selection, setSelection] = useState<Record<ColumnSelection, string>>({
    targetColumn: '',
    entityColumn: '',
    splitColumn: '',
    timeColumn: ''
  });
  const [entityColumns, setEntityColumns] = useState<string[]>([]);
  const [contaminationKeyColumns, setContaminationKeyColumns] = useState<string[]>([]);

  useEffect(() => {
    let active = true;
    const setup = id ? loadConfirmedAnalysisSetup(id) : null;
    setIsLoadingDataset(true);
    setLoadError(null);
    setDataset(null);
    setRecommendations(null);
    setRecommendationsLoading(false);
    setRecommendationsError(null);
    setAnalysisResult(null);
    setAnalysisError(null);
    setAttemptedOptions(null);
    setConfigurationConfirmed(setup?.confirmed === true);
    setSetupOrigin(setup?.confirmed === true);
    setSplitStrategy(setup?.splitStrategy ?? 'none');
    setSplitRatio(setup?.splitRatio ?? 0.2);
    setSplitSeed(setup?.splitSeed ?? 42);
    setSplitGenerationConfirmed(false);
    setIsGeneratingSplit(false);
    setSplitGenerationError(null);
    setSplitOperation(setup?.splitOperation ?? null);
    setTemporalObjective(setup?.temporalObjective ?? 'future_prediction');
    setSelection({
      targetColumn: setup?.targetColumn ?? '',
      entityColumn: setup?.entityColumn ?? '',
      splitColumn: setup?.splitColumn ?? '',
      timeColumn: setup?.timeColumn ?? '',
    });
    setEntityColumns(setup?.entityColumns ?? (
      setup?.entityColumn ? [setup.entityColumn] : []
    ));
    setContaminationKeyColumns(setup?.contaminationKeyColumns ?? []);

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
          setRecommendationsLoading(true);
          getColumnRecommendations(id)
            .then((response) => {
              if (active) setRecommendations(response);
            })
            .catch((err: unknown) => {
              if (active) {
                setRecommendationsError(
                  err instanceof Error ? err.message : 'Recommendations are unavailable.'
                );
              }
            })
            .finally(() => {
              if (active) setRecommendationsLoading(false);
            });
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
    ...(entityColumns.length ? { entityColumns } : {}),
    ...(splitStrategy === 'existing' && selection.splitColumn
      ? { splitColumn: selection.splitColumn }
      : {}),
    ...(selection.targetColumn ? { targetColumn: selection.targetColumn } : {}),
    ...(selection.timeColumn ? { timeColumn: selection.timeColumn } : {}),
    ...(selection.timeColumn ? { temporalObjective } : {}),
    ...(contaminationKeyColumns.length ? { contaminationKeyColumns } : {}),
    configurationConfirmed,
    splitStrategy,
    ...(splitStrategy === 'generated' && splitOperation
      ? { splitOperationId: splitOperation.id }
      : {})
  }), [
    selection,
    entityColumns,
    contaminationKeyColumns,
    splitStrategy,
    splitOperation,
    temporalObjective,
    configurationConfirmed,
  ]);

  const updateSelection = (key: ColumnSelection, value: string) => {
    setSelection((previous) => ({ ...previous, [key]: value }));
    if (key === 'entityColumn') {
      setEntityColumns(value ? [value] : []);
    }
    setConfigurationConfirmed(false);
    setAnalysisResult(null);
    setAnalysisError(null);
    setAttemptedOptions(null);
  };

  const updateSplitStrategy = (value: SplitStrategy) => {
    setSplitStrategy(value);
    setSelection((previous) => ({ ...previous, splitColumn: '' }));
    setSplitOperation(null);
    setSplitGenerationConfirmed(false);
    setSplitGenerationError(null);
    setConfigurationConfirmed(false);
    setAnalysisResult(null);
    setAnalysisError(null);
    setAttemptedOptions(null);
  };

  const handleGenerateSplit = async () => {
    if (!id || !splitGenerationConfirmed || isGeneratingSplit) return;
    setIsGeneratingSplit(true);
    setSplitGenerationError(null);
    setSplitOperation(null);
    setConfigurationConfirmed(false);
    setAnalysisResult(null);
    try {
      const operation = await generateDatasetSplit(id, {
        testRatio: splitRatio,
        randomSeed: splitSeed,
      });
      setSplitOperation(operation);
      success(
        'Split copy generated',
        `${operation.splitRowCounts.train ?? 0} training rows and ${operation.splitRowCounts.test ?? 0} test rows were written to a separate output.`
      );
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'The backend could not generate a split copy.';
      setSplitGenerationError(message);
      error('Split generation failed', message);
    } finally {
      setIsGeneratingSplit(false);
    }
  };

  const splitReady = splitStrategy === 'none'
    || (splitStrategy === 'existing' && Boolean(selection.splitColumn))
    || (splitStrategy === 'generated' && Boolean(splitOperation?.id));

  const startAnalysis = async () => {
    if (!id || !dataset || isRunning || !isTabular(dataset) || !configurationConfirmed || !splitReady) return;
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
  const potentialTargetDerivedFeatures = useMemo(
    () => findPotentialTargetDerivedFeatures(
      selection.targetColumn,
      columns.map((column) => column.name)
    ),
    [columns, selection.targetColumn]
  );
  const visibleColumnSelectors = columnSelectors.filter(
    ({ key }) => key !== 'splitColumn' || splitStrategy === 'existing'
  );
  const selectableColumns = useMemo(
    () => columns.map((column) => ({ name: column.name, type: column.type })),
    [columns]
  );
  const recommendationSelection: Record<DetectorColumnRole, string> = {
    target: selection.targetColumn,
    entity: selection.entityColumn,
    split: selection.splitColumn,
    timestamp: selection.timeColumn,
  };
  const applyRecommendation = (role: DetectorColumnRole, column: string) => {
    const keys: Record<DetectorColumnRole, ColumnSelection> = {
      target: 'targetColumn',
      entity: 'entityColumn',
      split: 'splitColumn',
      timestamp: 'timeColumn',
    };
    if (role === 'split' && splitStrategy !== 'existing') {
      updateSplitStrategy('existing');
    }
    updateSelection(keys[role], column);
  };

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
        {id && (
          <nav aria-label="Dataset workflow" className="flex flex-wrap gap-2">
            <button type="button" onClick={() => navigate(`/datasets/${id}`)} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">Dataset</button>
            <button type="button" onClick={() => navigate(`/analysis-setup/${id}`)} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">Analysis Setup</button>
            <button type="button" onClick={() => navigate(getDatasetWorkflowPath('findings', id))} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">Findings</button>
            <button type="button" onClick={() => navigate(`/remediation/${id}`)} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">Remediation Center</button>
            <button type="button" onClick={() => navigate(`/datasets/${id}?tab=history`)} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">Audit History</button>
          </nav>
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
          <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Analysis overview</h2>
                <p className="mt-1 text-xs text-slate-600">
                  Dataset: <strong>{dataset.name}</strong> · ID: <span className="font-mono">{dataset.id}</span>
                </p>
              </div>
              {id && (
                <button
                  type="button"
                  onClick={() => navigate(getDatasetWorkflowPath('dataset', id))}
                  className="text-xs font-semibold text-teal-800 underline underline-offset-2"
                >
                  Dataset profile and history
                </button>
              )}
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
              <div>
                <dt className="text-slate-500">Rows</dt>
                <dd className="mt-1 font-semibold text-slate-900">{dataset.sampleCount ?? 'Not available'}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Columns</dt>
                <dd className="mt-1 font-semibold text-slate-900">
                  {dataset.featureCount ?? (columns.length > 0 ? columns.length : 'Not available')}
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">Persisted status</dt>
                <dd className="mt-1 font-semibold text-slate-900">{dataset.status || 'Not available'}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Last successful analysis</dt>
                <dd className="mt-1 font-semibold text-slate-900">
                  {dataset.lastAnalysis ? new Date(dataset.lastAnalysis).toLocaleString() : 'Not available'}
                </dd>
              </div>
            </dl>
          </section>

          {setupOrigin ? (
            <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-slate-900">Confirmed analysis configuration</h2>
                  <p className="mt-1 text-xs text-slate-600">
                    These are the exact user-confirmed selections passed to the backend. No recommendation was applied automatically.
                  </p>
                </div>
                {id && (
                  <button type="button" onClick={() => navigate(`/analysis-setup/${id}`)}
                    className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">
                    Change configuration
                  </button>
                )}
              </div>
              <dl className="mt-4 grid gap-x-4 gap-y-2 text-xs sm:grid-cols-2">
                <dt className="text-slate-500">Target</dt><dd className="break-all font-mono">{selection.targetColumn || 'Not selected'}</dd>
                <dt className="text-slate-500">Entity key</dt><dd className="break-all font-mono">{entityColumns.join(' + ') || selection.entityColumn || 'Not selected'}</dd>
                <dt className="text-slate-500">Contamination comparison</dt><dd className="break-all font-mono">{contaminationKeyColumns.join(' + ') || 'Exact row content'}</dd>
                <dt className="text-slate-500">Timestamp</dt><dd className="break-all font-mono">{selection.timeColumn || 'Not selected'}</dd>
                <dt className="text-slate-500">Temporal objective</dt><dd>{temporalObjective === 'future_prediction' ? 'Predict future events' : 'Randomized holdout (chronology skipped)'}</dd>
                <dt className="text-slate-500">Split strategy</dt><dd>{splitStrategy}</dd>
                <dt className="text-slate-500">Split column</dt><dd className="break-all font-mono">{selection.splitColumn || 'Not selected'}</dd>
                {splitOperation && <><dt className="text-slate-500">Generated split operation</dt><dd className="break-all font-mono">{splitOperation.id}</dd></>}
              </dl>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <label className="flex items-start gap-2 text-xs text-slate-700">
                  <input type="checkbox" checked={configurationConfirmed} onChange={(event) => setConfigurationConfirmed(event.target.checked)} disabled={isRunning} className="mt-0.5" />
                  <span>Confirm these selections for this analysis request.</span>
                </label>
                <button
                  onClick={() => void startAnalysis()}
                  disabled={isRunning || isLoadingDataset || !configurationConfirmed || !splitReady}
                  className="px-4 py-2 text-xs font-semibold rounded-lg bg-teal-700 hover:bg-teal-800 text-white disabled:opacity-50 flex items-center gap-2"
                >
                  {isRunning ? <Clock className="w-4 h-4 animate-spin" /> : analysisResult ? <RotateCcw className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                  {isRunning ? 'Analysis running…' : analysisResult ? 'Run again' : 'Run configured analysis'}
                </button>
              </div>
            </section>
          ) : (
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
            {recommendationsLoading && (
              <p role="status" className="mt-3 text-xs text-slate-500">
                Loading profile-based column suggestions…
              </p>
            )}
            {recommendationsError && (
              <p role="alert" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                Automatic suggestions are unavailable: {recommendationsError} You can still choose columns manually.
              </p>
            )}
            {recommendations && (
              <div className="mt-4">
                <ColumnRecommendationsPanel
                  recommendations={recommendations}
                  selected={recommendationSelection}
                  onSelect={applyRecommendation}
                />
              </div>
            )}
            <SplitStrategyPanel
              strategy={splitStrategy}
              onStrategyChange={updateSplitStrategy}
              testRatio={splitRatio}
              randomSeed={splitSeed}
              onTestRatioChange={(value) => {
                setSplitRatio(value);
                setSplitOperation(null);
                setSplitGenerationConfirmed(false);
                setConfigurationConfirmed(false);
                setAnalysisResult(null);
              }}
              onRandomSeedChange={(value) => {
                setSplitSeed(value);
                setSplitOperation(null);
                setSplitGenerationConfirmed(false);
                setConfigurationConfirmed(false);
                setAnalysisResult(null);
              }}
              generationConfirmed={splitGenerationConfirmed}
              onGenerationConfirmedChange={setSplitGenerationConfirmed}
              isGenerating={isGeneratingSplit}
              generationError={splitGenerationError}
              operation={splitOperation}
              onGenerate={() => void handleGenerateSplit()}
            />
            <label className="mt-4 block max-w-xl text-xs font-semibold text-slate-700">
              Temporal evaluation objective
              <select
                value={temporalObjective}
                onChange={(event) => {
                  setTemporalObjective(event.target.value as TemporalEvaluationObjective);
                  setConfigurationConfirmed(false);
                  setAnalysisResult(null);
                  setAttemptedOptions(null);
                }}
                className="mt-1 block w-full rounded border border-slate-300 bg-white px-2 py-2 font-normal"
              >
                <option value="future_prediction">Predict future events</option>
                <option value="randomized_holdout">Randomized holdout</option>
              </select>
              <span className="mt-1 block font-normal text-slate-500">
                Randomized holdout skips timestamp-range interpretation; it does not imply that chronological evaluation passed.
              </span>
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
              {visibleColumnSelectors.map(({ key, label, help }) => (
                <div key={key}>
                  <SearchableColumnSelector
                    label={label}
                    value={selection[key]}
                    columns={selectableColumns}
                    disabled={
                      columns.length === 0
                      || isRunning
                      || (splitStrategy === 'none' && (key === 'entityColumn' || key === 'timeColumn'))
                    }
                    onChange={(value) => updateSelection(key, value)}
                  />
                  <span className="mt-1 block text-[11px] text-slate-500">{help}</span>
                </div>
              ))}
            </div>
            {selection.targetColumn && (
              <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950" role="note">
                <p className="font-semibold">
                  Target and feature-input review: <span className="font-mono">{selection.targetColumn}</span>
                </p>
                <p className="mt-1">
                  All other dataset columns are evaluated as candidate inputs by target-leakage detection.
                  A deterministic association is evidence for review, not proof of causal leakage.
                </p>
                {potentialTargetDerivedFeatures.length > 0 && (
                  <>
                    <p className="mt-2 font-semibold">
                      Possible copied, derived, or post-outcome columns to review:
                    </p>
                    <ul className="mt-1 list-disc space-y-1 pl-5">
                      {potentialTargetDerivedFeatures.map((feature) => (
                        <li key={feature.columnName} className="break-all">
                          <span className="font-mono">{feature.columnName}</span>
                          <span className="text-amber-800"> — {feature.signals.join(' ')}</span>
                        </li>
                      ))}
                    </ul>
                    <p className="mt-1">
                      These names are heuristic warnings only; inspect timing and evidence before treating a finding as leakage.
                    </p>
                  </>
                )}
              </div>
            )}
            <label className="mt-5 flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
              <input
                type="checkbox"
                checked={configurationConfirmed}
                onChange={(event) => setConfigurationConfirmed(event.target.checked)}
                disabled={isRunning}
                className="mt-0.5"
              />
              <span>
                I have reviewed the selected split strategy and detector columns and confirm this configuration.
                Suggestions are advisory; no detector runs until I submit below.
              </span>
            </label>
            <div className="mt-4 flex justify-end">
              <button
                onClick={() => void startAnalysis()}
                disabled={isRunning || isLoadingDataset || !configurationConfirmed || !splitReady}
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
          )}

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
            <>
              <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs">
                <h2 className="text-sm font-semibold text-slate-900">Configuration used for this analysis</h2>
                <p className="mt-2 text-xs text-slate-700">
                  Split strategy: <strong>{analysisResult.splitStrategy || splitStrategy}</strong>
                </p>
                {analysisResult.splitExplanation && (
                  <p className="mt-1 text-xs text-slate-600">{analysisResult.splitExplanation}</p>
                )}
                {analysisResult.splitStrategy === 'existing' && (
                  <>
                    <p className="mt-1 text-xs text-slate-600">
                      Existing split column: {String(analysisResult.splitConfiguration?.split_column ?? 'Not available')}
                    </p>
                    {Array.isArray(analysisResult.splitConfiguration?.warnings)
                      && analysisResult.splitConfiguration.warnings.length > 0 && (
                        <ul className="mt-2 list-disc rounded-lg bg-amber-50 p-3 pl-7 text-xs text-amber-900">
                          {analysisResult.splitConfiguration.warnings.map((warning) => (
                            <li key={String(warning)}>{String(warning)}</li>
                          ))}
                        </ul>
                      )}
                  </>
                )}
                {analysisResult.splitStrategy === 'generated' && (
                  <p className="mt-1 text-xs text-slate-600">
                    Generated operation: {String(analysisResult.splitConfiguration?.split_operation_id ?? 'Not available')} ·
                    {' '}test ratio {String(analysisResult.splitConfiguration?.test_ratio ?? 'Not available')} ·
                    {' '}seed {String(analysisResult.splitConfiguration?.random_seed ?? 'Not available')}
                  </p>
                )}
                {(analysisResult.skippedDetectors ?? []).length > 0 && (
                  <p className="mt-2 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">
                    Not evaluated: {analysisResult.skippedDetectors?.join(', ')}. Skipped checks are not evidence of absence.
                  </p>
                )}
              </section>

              <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
                <h2 className="text-sm font-semibold text-slate-900">Findings returned by this analysis</h2>
                {analysisResult.findings.length === 0 ? (
                  <p className="mt-2 text-xs text-slate-500">
                    No findings were returned for this request. Detectors that were not requested or were skipped were not evaluated.
                  </p>
                ) : (
                  <div className="mt-3">
                    <GroupedFindings
                      findings={analysisResult.findings}
                      sourceLabel="Current analysis response. This is distinct from the complete persisted-findings search and pagination view."
                    />
                  </div>
                )}
              </section>
            </>
          )}
        </>
      ) : null}
    </div>
  );
};

function isTabular(dataset: Dataset): boolean {
  return dataset.format === 'CSV' || dataset.format === 'XLSX';
}
