import React, { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Dataset } from '../types';
import {
  createPartitionDistributionAnalysis,
  getDatasetById,
  getDatasets,
  getPartitionDistributionAnalysis,
  PartitionDistributionResult,
} from '../services/api';
import { CardSkeleton } from '../components/common/LoadingSkeleton';

type JsonRecord = Record<string, unknown>;

const asRecord = (value: unknown): JsonRecord =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonRecord
    : {};

const asNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

const formatMetric = (value: unknown): string => {
  const number = asNumber(value);
  return number === null ? '—' : number.toLocaleString(undefined, { maximumFractionDigits: 4 });
};

const statusLabel = (value: unknown): string =>
  typeof value === 'string' ? value.replaceAll('_', ' ') : 'Unavailable';

export type PartitionDistributionContentState =
  | 'loading'
  | 'select_dataset'
  | 'dataset_unavailable'
  | 'requires_configuration'
  | 'empty'
  | 'ready';

export function getPartitionDistributionContentState(input: {
  loading: boolean;
  datasetSelected: boolean;
  datasetAvailable: boolean;
  configuredSplit: boolean;
  analysisAvailable: boolean;
}): PartitionDistributionContentState {
  if (input.loading) return 'loading';
  if (!input.datasetSelected) return 'select_dataset';
  if (!input.datasetAvailable) return 'dataset_unavailable';
  if (!input.configuredSplit) return 'requires_configuration';
  if (!input.analysisAvailable) return 'empty';
  return 'ready';
}

export function buildPartitionCategoryChartData(
  values: unknown,
  referencePartition: string,
  comparisonPartition: string,
  limit = 20
): Array<Record<string, string | number>> {
  if (!Array.isArray(values)) return [];
  return values.slice(0, limit).map((value) => {
    const item = asRecord(value);
    return {
      category: String(item.category ?? ''),
      [referencePartition]: asNumber(item.reference_percentage) ?? 0,
      [comparisonPartition]: asNumber(item.comparison_percentage) ?? 0,
    };
  });
}

export const PartitionDistributionPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const requestedDatasetId = searchParams.get('datasetId') ?? '';
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState(requestedDatasetId);
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [analysis, setAnalysis] = useState<PartitionDistributionResult | null>(null);
  const [referencePartition, setReferencePartition] = useState('');
  const [comparisonPartition, setComparisonPartition] = useState('');
  const [categoricalColumn, setCategoricalColumn] = useState('');
  const [loadingDatasets, setLoadingDatasets] = useState(true);
  const [loadingDataset, setLoadingDataset] = useState(false);
  const [running, setRunning] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    let active = true;
    getDatasets()
      .then((items) => {
        if (active) {
          setDatasets(items);
          if (requestedDatasetId) setDatasetId(requestedDatasetId);
        }
      })
      .catch((failure) => {
        if (active) setErrorMessage(failure instanceof Error ? failure.message : 'Could not load datasets.');
      })
      .finally(() => {
        if (active) setLoadingDatasets(false);
      });
    return () => { active = false; };
  }, [requestedDatasetId]);

  useEffect(() => {
    let active = true;
    setDataset(null);
    setAnalysis(null);
    setReferencePartition('');
    setComparisonPartition('');
    setCategoricalColumn('');
    setErrorMessage('');
    if (!datasetId) {
      setLoadingDataset(false);
      return () => { active = false; };
    }
    setLoadingDataset(true);
    Promise.all([
      getDatasetById(datasetId),
      getPartitionDistributionAnalysis(datasetId),
    ])
      .then(([found, persisted]) => {
        if (!active) return;
        if (!found) {
          setErrorMessage('Dataset not found or no longer available to this account.');
          return;
        }
        setDataset(found);
        setAnalysis(persisted);
      })
      .catch((failure) => {
        if (active) setErrorMessage(failure instanceof Error ? failure.message : 'Could not load partition analysis.');
      })
      .finally(() => {
        if (active) setLoadingDataset(false);
      });
    return () => { active = false; };
  }, [datasetId]);

  const configuredSplit = dataset?.profile?.analysisColumns?.splitColumn
    ?? dataset?.profile?.splitColumn
    ?? '';
  const partitionCounts = dataset?.profile?.splitRowCounts ?? {};
  const partitionLabels = Object.keys(partitionCounts);

  const result = analysis?.result ?? {};
  const summary = asRecord(result.summary);
  const target = asRecord(result.target);
  const features = asRecord(result.features);
  const numericChartData = useMemo(() => Object.entries(features)
    .flatMap(([name, value]) => {
      const metric = asRecord(value);
      if (metric.kind !== 'numeric') return [];
      const reference = asRecord(metric.reference);
      const comparison = asRecord(metric.comparison);
      const referenceMean = asNumber(reference.mean);
      const comparisonMean = asNumber(comparison.mean);
      return referenceMean === null || comparisonMean === null
        ? []
        : [{ feature: name, [String(result.reference_partition ?? 'Reference')]: referenceMean,
          [String(result.comparison_partition ?? 'Comparison')]: comparisonMean }];
    }), [features, result.reference_partition, result.comparison_partition]);

  const categoricalColumns = Object.entries(features)
    .filter(([, value]) => asRecord(value).kind === 'categorical')
    .map(([name]) => name);
  const selectedCategoricalColumn = categoricalColumns.includes(categoricalColumn)
    ? categoricalColumn
    : categoricalColumns[0] ?? '';
  const categoricalMetric = asRecord(features[selectedCategoricalColumn]);
  const categoryRows = Array.isArray(categoricalMetric.categories)
    ? categoricalMetric.categories
    : [];
  const referenceLabel = String(result.reference_partition ?? 'Reference');
  const comparisonLabel = String(result.comparison_partition ?? 'Comparison');
  const categoryChartData = buildPartitionCategoryChartData(
    categoryRows,
    referenceLabel,
    comparisonLabel
  );
  const targetClassRows = Array.isArray(target.class_distribution)
    ? target.class_distribution.map((value) => asRecord(value))
    : Array.isArray(target.categories)
      ? target.categories.map((value) => asRecord(value))
      : [];
  const targetChartData = buildPartitionCategoryChartData(
    targetClassRows,
    referenceLabel,
    comparisonLabel
  );

  const contentState = getPartitionDistributionContentState({
    loading: loadingDataset,
    datasetSelected: Boolean(datasetId),
    datasetAvailable: Boolean(dataset),
    configuredSplit: Boolean(configuredSplit),
    analysisAvailable: Boolean(analysis),
  });

  const runAnalysis = async () => {
    if (!datasetId || !referencePartition.trim() || !comparisonPartition.trim()) return;
    setRunning(true);
    setErrorMessage('');
    setAnalysis(null);
    try {
      const completed = await createPartitionDistributionAnalysis(
        datasetId,
        referencePartition,
        comparisonPartition
      );
      setAnalysis(completed);
    } catch (failure) {
      setErrorMessage(failure instanceof Error ? failure.message : 'Partition comparison failed.');
    } finally {
      setRunning(false);
    }
  };

  if (loadingDatasets) {
    return <div className="space-y-4"><CardSkeleton /><CardSkeleton /></div>;
  }

  return (
    <main className="mx-auto max-w-7xl space-y-6">
      <header>
        <span className="text-xs font-mono font-semibold uppercase tracking-wider text-teal-700">
          Within-dataset comparison
        </span>
        <h1 className="mt-1 text-2xl font-bold text-slate-900">Partition Distribution Analysis</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          Compare explicitly selected labels from the dataset&apos;s persisted split configuration.
          Distribution shift is descriptive and does not by itself indicate leakage.
        </p>
      </header>

      <section className="grid gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-xs md:grid-cols-4">
        <label className="text-xs font-medium text-slate-700">
          Dataset
          <select
            aria-label="Dataset"
            value={datasetId}
            onChange={(event) => setDatasetId(event.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2"
          >
            <option value="">Select a dataset</option>
            {datasets.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="text-xs font-medium text-slate-700">
          Reference partition
          <input
            aria-label="Reference partition"
            list="configured-partitions"
            value={referencePartition}
            onChange={(event) => setReferencePartition(event.target.value)}
            placeholder="Choose observed label"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            disabled={!dataset}
          />
        </label>
        <label className="text-xs font-medium text-slate-700">
          Comparison partition
          <input
            aria-label="Comparison partition"
            list="configured-partitions"
            value={comparisonPartition}
            onChange={(event) => setComparisonPartition(event.target.value)}
            placeholder="Choose a different label"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            disabled={!dataset}
          />
        </label>
        <datalist id="configured-partitions">
          {partitionLabels.map((label) => <option key={label} value={label} />)}
        </datalist>
        <div className="flex items-end">
          <button
            type="button"
            disabled={!dataset || !configuredSplit || !referencePartition.trim()
              || !comparisonPartition.trim() || referencePartition.trim() === comparisonPartition.trim()
              || running || loadingDataset}
            onClick={() => void runAnalysis()}
            className="w-full rounded-md bg-teal-700 px-4 py-2 text-xs font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running ? 'Analyzing…' : 'Run comparison'}
          </button>
        </div>
        {dataset && (
          <p className="text-xs text-slate-600 md:col-span-4">
            Configured split column: <strong>{configuredSplit || 'Not configured'}</strong>
            {partitionLabels.length > 0 && ` · Observed labels: ${partitionLabels.join(', ')}`}
          </p>
        )}
      </section>

      {errorMessage && (
        <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          {errorMessage}
        </div>
      )}
      {contentState === 'loading' && <div className="space-y-4"><CardSkeleton /><CardSkeleton /></div>}
      {contentState === 'select_dataset' && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-5 text-sm text-slate-700">
          Select an owned dataset to compare its configured partitions.
        </div>
      )}
      {contentState === 'dataset_unavailable' && !errorMessage && (
        <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          The selected dataset could not be loaded for this account.
        </div>
      )}
      {contentState === 'requires_configuration' && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          No persisted split column is configured. Configure and confirm a split in Analysis Setup before comparing partitions.
        </div>
      )}
      {contentState === 'empty' && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-5 text-sm text-slate-700">
          No persisted partition comparison is available for this dataset and source version. Choose two observed labels and run a comparison.
        </div>
      )}

      {contentState === 'ready' && analysis && (
        <>
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              ['Result', statusLabel(summary.status)],
              ['Features compared', String(summary.feature_count ?? 0)],
              ['Potential shifts', String(summary.potential_shift_count ?? 0)],
              ['Statistical differences', String(summary.significant_difference_count ?? 0)],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-slate-200 bg-white p-4">
                <span className="text-xs text-slate-500">{label}</span>
                <strong className="mt-1 block text-sm capitalize text-slate-900">{value}</strong>
              </div>
            ))}
          </section>

          <section
            aria-label="Target class distribution"
            className="rounded-xl border border-slate-200 bg-white p-5"
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Target / class distribution</h2>
                <p className="mt-1 text-xs text-slate-600">
                  {typeof target.column === 'string' ? `Configured target: ${target.column}` : 'No target is configured.'}
                  {' · '}Status: {statusLabel(target.status === 'analyzed'
                    ? target.distribution_status
                    : target.status)}
                </p>
              </div>
              {target.status === 'analyzed' && typeof target.column === 'string' && (
                <span className="rounded bg-slate-100 px-2 py-1 text-[10px] text-slate-600">
                  {String(result.reference_partition)} vs {String(result.comparison_partition)}
                </span>
              )}
            </div>
            {target.status === 'skipped' ? (
              <p className="mt-3 rounded-md bg-amber-50 p-3 text-xs text-amber-900">
                {String(target.reason ?? 'Target comparison was not performed.')}
              </p>
            ) : target.kind === 'categorical' && targetChartData.length > 0 ? (
              <div className="mt-4 h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={targetChartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="category" />
                    <YAxis unit="%" />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey={String(result.reference_partition ?? 'Reference')} fill="#64748b" />
                    <Bar dataKey={String(result.comparison_partition ?? 'Comparison')} fill="#0f766e" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : target.kind === 'numeric' ? (
              <dl className="mt-3 grid gap-3 sm:grid-cols-3">
                <div className="rounded-md bg-slate-50 p-3">
                  <dt className="text-[10px] text-slate-500">Reference mean</dt>
                  <dd className="mt-1 font-mono text-sm">{formatMetric(asRecord(target.reference).mean)}</dd>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <dt className="text-[10px] text-slate-500">Comparison mean</dt>
                  <dd className="mt-1 font-mono text-sm">{formatMetric(asRecord(target.comparison).mean)}</dd>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <dt className="text-[10px] text-slate-500">Mean difference</dt>
                  <dd className="mt-1 font-mono text-sm">{formatMetric(target.mean_difference)}</dd>
                </div>
              </dl>
            ) : (
              <p className="mt-3 text-xs text-slate-500">
                {target.status === 'analyzed'
                  ? 'The target was inspected, but there is insufficient data to compare its distribution.'
                  : 'Target/class distribution is unavailable.'}
              </p>
            )}
            {target.status === 'analyzed' && target.missing_target_values !== undefined && (
              <p className="mt-3 text-[10px] text-slate-500">
                Missing target values: {JSON.stringify(target.missing_target_values)}
              </p>
            )}
          </section>

          <section className="grid gap-5 lg:grid-cols-2">
            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h2 className="text-sm font-semibold text-slate-900">Numerical feature means</h2>
              <p className="mb-4 mt-1 text-xs text-slate-500">
                Means are descriptive; scale differences across columns are not normalized.
              </p>
              {numericChartData.length ? (
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={numericChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="feature" />
                      <YAxis />
                      <Tooltip />
                      <Legend />
                      <Bar dataKey={String(result.reference_partition ?? 'Reference')} fill="#64748b" />
                      <Bar dataKey={String(result.comparison_partition ?? 'Comparison')} fill="#0f766e" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : <p className="py-12 text-center text-xs text-slate-500">No numerical feature comparisons have sufficient data.</p>}
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h2 className="text-sm font-semibold text-slate-900">Categorical proportions</h2>
                  <p className="mt-1 text-xs text-slate-500">Displayed categories come from persisted backend counts.</p>
                </div>
                {categoricalColumns.length > 0 && (
                  <select
                    aria-label="Categorical feature"
                    value={selectedCategoricalColumn}
                    onChange={(event) => setCategoricalColumn(event.target.value)}
                    className="rounded-md border border-slate-300 px-2 py-1.5 text-xs"
                  >
                    {categoricalColumns.map((column) => <option key={column} value={column}>{column}</option>)}
                  </select>
                )}
              </div>
              {categoryChartData.length ? (
                <div className="mt-4 h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={categoryChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="category" />
                      <YAxis unit="%" />
                      <Tooltip />
                      <Legend />
                      <Bar dataKey={String(result.reference_partition ?? 'Reference')} fill="#64748b" />
                      <Bar dataKey={String(result.comparison_partition ?? 'Comparison')} fill="#0f766e" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : <p className="py-12 text-center text-xs text-slate-500">No categorical feature comparison is available.</p>}
            </div>
          </section>

          <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-sm font-semibold text-slate-900">Per-feature metrics</h2>
            <p className="text-xs text-slate-600">
              Target: {typeof asRecord(result.target).column === 'string'
                ? String(asRecord(result.target).column)
                : 'Not configured'} · Partitions:{' '}
              {String(result.reference_partition)} vs {String(result.comparison_partition)}
            </p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[700px] text-left text-xs">
                <thead className="border-b bg-slate-50 text-slate-600">
                  <tr>
                    <th className="p-2">Column</th>
                    <th className="p-2">Type</th>
                    <th className="p-2">Status</th>
                    <th className="p-2">Mean / TV difference</th>
                    <th className="p-2">PSI</th>
                    <th className="p-2">KS p-value (approx.)</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(features).map(([name, value]) => {
                    const metric = asRecord(value);
                    return (
                      <tr key={name} className="border-b last:border-b-0">
                        <td className="p-2 font-mono">{name}</td>
                        <td className="p-2 capitalize">{String(metric.kind ?? 'unknown')}</td>
                        <td className="p-2 capitalize">{statusLabel(metric.status)}</td>
                        <td className="p-2 font-mono">
                          {formatMetric(metric.mean_difference ?? metric.total_variation_distance)}
                        </td>
                        <td className="p-2 font-mono">{formatMetric(metric.population_stability_index)}</td>
                        <td className="p-2 font-mono">{formatMetric(metric.kolmogorov_smirnov_p_value_approximate)}</td>
                      </tr>
                    );
                  })}
                  {Object.keys(features).length === 0 && (
                    <tr><td colSpan={6} className="p-5 text-center text-slate-500">No feature metrics were returned.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
          <p className="text-[11px] text-slate-500">
            Persisted analysis ID {analysis.id} · Source SHA-256 {String(result.source_file_sha256 ?? 'unavailable')}
          </p>
        </>
      )}
    </main>
  );
};
