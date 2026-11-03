import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowRight, LoaderCircle } from 'lucide-react';
import { SearchableColumnSelector } from '../components/analysis/SearchableColumnSelector';
import { SplitStrategy, SplitStrategyPanel } from '../components/analysis/SplitStrategyPanel';
import {
  generateDatasetSplit,
  getColumnRecommendations,
  getDatasetById,
} from '../services/api';
import type {
  ColumnRecommendationsResponse,
  Dataset,
  DetectorColumnRole,
  SplitGenerationOperation,
} from '../types';

export interface ConfirmedAnalysisSetup {
  confirmed: true;
  targetColumn: string;
  entityColumn: string;
  splitColumn: string;
  timeColumn: string;
  splitStrategy: SplitStrategy;
  splitRatio: number;
  splitSeed: number;
  splitOperation: SplitGenerationOperation | null;
  confirmedAt: string;
}

export function getAnalysisSetupStorageKey(datasetId: string): string {
  return `dataleakguard:analysis-setup:${datasetId}`;
}

export function loadConfirmedAnalysisSetup(datasetId: string): ConfirmedAnalysisSetup | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(getAnalysisSetupStorageKey(datasetId));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') {
      return null;
    }
    const candidate = parsed as Partial<ConfirmedAnalysisSetup>;
    const validSplitOperation = candidate.splitOperation === null
      || (
        typeof candidate.splitOperation === 'object'
        && typeof candidate.splitOperation.id === 'string'
      );
    if (
      candidate.confirmed !== true
      || !['existing', 'generated', 'none'].includes(String(candidate.splitStrategy))
      || typeof candidate.targetColumn !== 'string'
      || typeof candidate.entityColumn !== 'string'
      || typeof candidate.splitColumn !== 'string'
      || typeof candidate.timeColumn !== 'string'
      || typeof candidate.splitRatio !== 'number'
      || !Number.isFinite(candidate.splitRatio)
      || candidate.splitRatio <= 0
      || candidate.splitRatio >= 1
      || typeof candidate.splitSeed !== 'number'
      || !Number.isInteger(candidate.splitSeed)
      || typeof candidate.confirmedAt !== 'string'
      || !validSplitOperation
      || (candidate.splitStrategy === 'generated' && !candidate.splitOperation)
    ) {
      return null;
    }
    return candidate as ConfirmedAnalysisSetup;
  } catch {
    return null;
  }
}

function saveConfirmedAnalysisSetup(datasetId: string, setup: ConfirmedAnalysisSetup): void {
  window.sessionStorage.setItem(getAnalysisSetupStorageKey(datasetId), JSON.stringify(setup));
}

const ROLE_LABELS: Record<DetectorColumnRole, string> = {
  target: 'Target / outcome',
  entity: 'Entity / identifier',
  split: 'Train/test split column',
  timestamp: 'Timestamp / time',
};

const ROLE_FIELDS: Record<DetectorColumnRole, 'targetColumn' | 'entityColumn' | 'splitColumn' | 'timeColumn'> = {
  target: 'targetColumn',
  entity: 'entityColumn',
  split: 'splitColumn',
  timestamp: 'timeColumn',
};

export const AnalysisSetupPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [recommendations, setRecommendations] = useState<ColumnRecommendationsResponse | null>(null);
  const [recommendationsLoading, setRecommendationsLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [recommendationError, setRecommendationError] = useState<string | null>(null);
  const [selection, setSelection] = useState({
    targetColumn: '',
    entityColumn: '',
    splitColumn: '',
    timeColumn: '',
  });
  const [splitStrategy, setSplitStrategy] = useState<SplitStrategy>('none');
  const [splitRatio, setSplitRatio] = useState(0.2);
  const [splitSeed, setSplitSeed] = useState(42);
  const [generationConfirmed, setGenerationConfirmed] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [splitOperation, setSplitOperation] = useState<SplitGenerationOperation | null>(null);
  const [userConfirmed, setUserConfirmed] = useState(false);

  useEffect(() => {
    let active = true;
    if (!id) {
      setError('A dataset identifier is required.');
      setLoading(false);
      return () => { active = false; };
    }
    setLoading(true);
    setError(null);
    getDatasetById(id)
      .then((result) => {
        if (!active) return;
        if (!result) {
          setError('Dataset not found or is not available to this account.');
          return;
        }
        setDataset(result);
        setRecommendationsLoading(true);
        getColumnRecommendations(id)
          .then((response) => {
            if (active) setRecommendations(response);
          })
          .catch((reason: unknown) => {
            if (active) setRecommendationError(reason instanceof Error ? reason.message : 'Column suggestions are unavailable.');
          })
          .finally(() => {
            if (active) setRecommendationsLoading(false);
          });
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : 'The dataset could not be loaded.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [id]);

  const columns = useMemo(
    () => (dataset?.columns ?? []).map((column) => ({ name: column.name, type: column.type })),
    [dataset],
  );

  const updateColumn = (role: DetectorColumnRole, value: string) => {
    const field = ROLE_FIELDS[role];
    setSelection((current) => ({ ...current, [field]: value }));
    setUserConfirmed(false);
    if (role === 'split' && value) setSplitStrategy('existing');
  };

  const handleGenerateSplit = async () => {
    if (!id || !generationConfirmed || isGenerating) return;
    setIsGenerating(true);
    setGenerationError(null);
    setSplitOperation(null);
    setUserConfirmed(false);
    try {
      const result = await generateDatasetSplit(id, { testRatio: splitRatio, randomSeed: splitSeed });
      setSplitOperation(result);
    } catch (reason: unknown) {
      setGenerationError(reason instanceof Error ? reason.message : 'Split generation failed.');
    } finally {
      setIsGenerating(false);
    }
  };

  const confirmedSelectionReady =
    splitStrategy === 'none'
    || (splitStrategy === 'existing' && Boolean(selection.splitColumn))
    || (splitStrategy === 'generated' && Boolean(splitOperation?.id));

  const continueToAnalysis = () => {
    if (!id || !confirmedSelectionReady || !userConfirmed) return;
    saveConfirmedAnalysisSetup(id, {
      confirmed: true,
      ...selection,
      splitStrategy,
      splitRatio,
      splitSeed,
      splitOperation,
      confirmedAt: new Date().toISOString(),
    });
    navigate(`/analysis/${id}`);
  };

  if (loading) {
    return <div role="status" className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600">
      <LoaderCircle className="h-4 w-4 animate-spin" /> Loading dataset profile and recommendations…
    </div>;
  }
  if (error || !dataset || !id) {
    return <div className="space-y-3">
      <h1 className="text-2xl font-bold text-slate-900">Analysis Setup</h1>
      <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error ?? 'Dataset is unavailable.'}</p>
    </div>;
  }

  return (
    <main className="mx-auto max-w-5xl space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-widest text-teal-700">Configuration · advisory suggestions</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">Analysis Setup</h1>
          <p className="mt-1 text-sm text-slate-600">Choose and confirm the columns and split strategy. Suggestions never change the configuration automatically.</p>
        </div>
        <nav aria-label="Dataset workflow" className="flex flex-wrap gap-2">
          <button type="button" onClick={() => navigate(`/datasets/${id}`)} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">Dataset</button>
          <button type="button" onClick={() => navigate(`/analysis/${id}`)} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">Analysis</button>
          <button type="button" onClick={() => navigate(`/leakage-analysis/${id}`)} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">Findings</button>
          <button type="button" onClick={() => navigate(`/remediation/${id}`)} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">Remediation Center</button>
          <button type="button" onClick={() => navigate(`/datasets/${id}?tab=history`)} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">Audit History</button>
        </nav>
      </header>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Selected dataset</h2>
        <p className="mt-1 text-sm font-medium text-slate-800">{dataset.name}</p>
        <div className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          <div><span className="text-slate-500">Rows</span><p className="font-semibold">{dataset.sampleCount?.toLocaleString() ?? 'Unavailable'}</p></div>
          <div><span className="text-slate-500">Columns</span><p className="font-semibold">{dataset.featureCount?.toLocaleString() ?? columns.length}</p></div>
          <div><span className="text-slate-500">Format</span><p className="font-semibold">{dataset.format}</p></div>
          <div><span className="text-slate-500">ID</span><p className="truncate font-mono font-semibold" title={dataset.id}>{dataset.id}</p></div>
        </div>
      </section>

      {recommendationError && (
        <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          Recommendations unavailable: {recommendationError} Manual selection remains available.
        </p>
      )}

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Column configuration</h2>
        <p className="mt-1 text-xs text-slate-600">Recommendations are optional. Select a suggestion explicitly or search the full column list.</p>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {(Object.keys(ROLE_LABELS) as DetectorColumnRole[]).map((role) => {
            const field = ROLE_FIELDS[role];
            const recommended = recommendations?.roles[role]?.recommendation ?? null;
            return (
              <article key={role} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <SearchableColumnSelector
                  label={ROLE_LABELS[role]}
                  value={selection[field]}
                  columns={columns}
                  onChange={(value) => updateColumn(role, value)}
                  disabled={role === 'split' && splitStrategy !== 'existing'}
                />
                <div className="mt-3 rounded-md border border-slate-200 bg-white p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Recommendation</p>
                    {recommended && (
                      <button type="button" onClick={() => updateColumn(role, recommended.columnName)}
                        className="rounded border border-teal-200 bg-teal-50 px-2 py-1 text-[10px] font-semibold text-teal-800">
                        Use {recommended.columnName}
                      </button>
                    )}
                  </div>
                  {recommendationsLoading ? (
                    <p role="status" className="mt-1 text-[11px] text-slate-500">Loading profile-based suggestion…</p>
                  ) : recommended ? (
                    <>
                      <p className="mt-1 break-all font-mono text-xs font-semibold text-slate-900">{recommended.columnName}</p>
                      <p className="mt-1 text-[11px] text-slate-600">{recommended.explanation}</p>
                      <details className="mt-2">
                        <summary className="cursor-pointer text-[10px] font-semibold text-teal-800">Why recommended? · Advanced details</summary>
                        <div className="mt-2 space-y-1 text-[10px] text-slate-600">
                          <p>Heuristic rank: {recommended.score} points ({recommended.confidence}); not a probability.</p>
                          <p>Type: {recommended.profile.dataType} · unique values: {recommended.profile.uniqueCount ?? 'unavailable'} · missing: {recommended.profile.missingCount ?? 'unavailable'}</p>
                          {recommended.supportingSignals.map((signal) => <p key={signal}>Signal: {signal}</p>)}
                          {recommended.warnings.map((warning) => <p key={warning} className="text-amber-800">Warning: {warning}</p>)}
                          {recommendations?.roles[role]?.candidates
                            .filter((candidate) => candidate.columnName !== recommended.columnName)
                            .map((candidate) => <p key={candidate.columnName}>Alternative: <span className="font-mono">{candidate.columnName}</span> · {candidate.score} heuristic points</p>)}
                        </div>
                      </details>
                    </>
                  ) : (
                    <p className="mt-1 text-[11px] text-slate-500">
                      No reliable recommendation. Choose and verify a column manually.
                    </p>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <SplitStrategyPanel
        strategy={splitStrategy}
        onStrategyChange={(value) => {
          setSplitStrategy(value);
          setSelection((current) => ({ ...current, splitColumn: '' }));
          setSplitOperation(null);
          setGenerationConfirmed(false);
          setUserConfirmed(false);
        }}
        testRatio={splitRatio}
        randomSeed={splitSeed}
        onTestRatioChange={(value) => {
          setSplitRatio(value);
          setSplitOperation(null);
          setGenerationConfirmed(false);
          setUserConfirmed(false);
        }}
        onRandomSeedChange={(value) => {
          setSplitSeed(value);
          setSplitOperation(null);
          setGenerationConfirmed(false);
          setUserConfirmed(false);
        }}
        generationConfirmed={generationConfirmed}
        onGenerationConfirmedChange={setGenerationConfirmed}
        isGenerating={isGenerating}
        generationError={generationError}
        operation={splitOperation}
        onGenerate={() => void handleGenerateSplit()}
      />

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Configuration to be analyzed</h2>
        <dl className="mt-3 grid gap-x-4 gap-y-2 text-xs sm:grid-cols-2">
          <dt className="text-slate-500">Target</dt><dd className="break-all font-mono">{selection.targetColumn || 'Not selected'}</dd>
          <dt className="text-slate-500">Entity</dt><dd className="break-all font-mono">{selection.entityColumn || 'Not selected'}</dd>
          <dt className="text-slate-500">Timestamp</dt><dd className="break-all font-mono">{selection.timeColumn || 'Not selected'}</dd>
          <dt className="text-slate-500">Split strategy</dt><dd>{splitStrategy}</dd>
          <dt className="text-slate-500">Split column</dt><dd className="break-all font-mono">{selection.splitColumn || (splitOperation ? 'Generated split output' : 'Not selected')}</dd>
        </dl>
        {!confirmedSelectionReady && splitStrategy === 'existing' && (
          <p role="alert" className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            Existing Split mode requires you to select and verify a split-membership column. No split will be generated automatically.
          </p>
        )}
        {!confirmedSelectionReady && splitStrategy === 'generated' && (
          <p role="alert" className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            Generate and verify a separate split output before continuing.
          </p>
        )}
        <label className="mt-4 flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
          <input type="checkbox" checked={userConfirmed} onChange={(event) => setUserConfirmed(event.target.checked)} className="mt-0.5" />
          <span>I reviewed these exact selections and confirm that they should be used for analysis. Suggestions remain advisory.</span>
        </label>
        <div className="mt-4 flex justify-end">
          <button type="button" onClick={continueToAnalysis} disabled={!confirmedSelectionReady || !userConfirmed}
            className="flex items-center gap-2 rounded-lg bg-teal-700 px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-40">
            Continue to Analysis <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </section>
    </main>
  );
};
