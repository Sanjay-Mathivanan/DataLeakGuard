import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Database,
  Play,
  Search,
  Wrench,
  FileSpreadsheet,
  Image,
  Layers,
  CheckCircle2,
  Calendar,
  Tag,
  ArrowRight,
  Info
} from 'lucide-react';
import { Dataset } from '../types';
import { getDatasetById } from '../services/api';
import { StatusBadge } from '../components/common/StatusBadge';
import { StatCard } from '../components/common/StatCard';
import { CardSkeleton, TableSkeleton } from '../components/common/LoadingSkeleton';
import { useToast } from '../context/ToastContext';

export function formatDimensionRange(min: number | null | undefined, max: number | null | undefined): string {
  if (typeof min !== 'number' && typeof max !== 'number') return '—';
  const minLabel = typeof min === 'number' ? min.toLocaleString() : '—';
  const maxLabel = typeof max === 'number' ? max.toLocaleString() : '—';
  return `${minLabel}–${maxLabel}`;
}

export const DatasetDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { error } = useToast();

  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [activeTab, setActiveTab] = useState<'overview' | 'profile' | 'integrity' | 'distribution' | 'history'>('overview');

  useEffect(() => {
    async function load() {
      if (!id) {
        setLoadError(true);
        setLoading(false);
        return;
      }
      try {
        const found = await getDatasetById(id);
        if (found) {
          setDataset(found);
        } else {
          error('Dataset Not Found', `Dataset with ID ${id} does not exist.`);
        }
      } catch {
        setLoadError(true);
        error('Error', 'Failed to retrieve dataset details.');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [id, error]);

  if (loading) {
    return (
      <div className="space-y-6">
        <CardSkeleton />
        <TableSkeleton rows={4} />
      </div>
    );
  }

  if (!dataset) {
    return (
      <div className="p-8 text-center bg-white rounded-xl border border-slate-200 shadow-xs">
        <p className="text-slate-600">
          {loadError ? 'Dataset details could not be loaded.' : 'Dataset not found.'}
        </p>
        <button
          onClick={() => navigate('/datasets')}
          className="mt-4 px-4 py-2 text-xs font-semibold rounded-lg bg-teal-700 hover:bg-teal-800 text-white transition-colors shadow-xs"
        >
          Return to Datasets
        </button>
      </div>
    );
  }

  const isCV = dataset.type === 'computer-vision';

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Top Header Card */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-teal-700 uppercase tracking-wider font-semibold">
                {dataset.format} · {dataset.type === 'computer-vision' ? 'Computer Vision Cohort' : 'Tabular Dataset'}
              </span>
              <StatusBadge status={dataset.status} size="sm" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900 font-mono">
              {dataset.name}
            </h1>
            <p className="text-xs text-slate-500 max-w-2xl leading-relaxed">
              {dataset.description}
            </p>
          </div>

          {/* Action CTAs */}
          <div className="flex flex-wrap items-center gap-2 self-start lg:self-auto">
            <button
              onClick={() => navigate(`/analysis/${dataset.id}`)}
              className="px-3.5 py-2 text-xs font-semibold rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white transition-colors flex items-center gap-1.5 shadow-xs"
            >
              <Play className="w-3.5 h-3.5" />
              <span>Run Integrity Analysis</span>
            </button>

            <button
              onClick={() => navigate(`/leakage-analysis/${dataset.id}`)}
              className="px-3.5 py-2 text-xs font-semibold rounded-lg bg-teal-700 hover:bg-teal-800 text-white transition-colors flex items-center gap-1.5 shadow-xs"
            >
              <Search className="w-3.5 h-3.5" />
              <span>View Leakage Findings</span>
            </button>

            <button
              onClick={() => navigate(`/repair/${dataset.id}`)}
              className="px-3.5 py-2 text-xs font-semibold rounded-lg bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 transition-colors flex items-center gap-1.5 shadow-2xs"
            >
              <Wrench className="w-3.5 h-3.5 text-teal-700" />
              <span>Repair & Evaluate</span>
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="mt-6 pt-4 border-t border-slate-100 flex items-center gap-1 overflow-x-auto">
          {[
            { key: 'overview', label: 'Overview' },
            { key: 'profile', label: isCV ? 'Image ZIP Profile' : 'Feature Profiles' },
            { key: 'integrity', label: 'Persisted Findings' },
            { key: 'distribution', label: 'Distribution & Splits' },
            { key: 'history', label: 'Audit History' }
          ].map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key as any)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap ${
                activeTab === tab.key
                  ? 'bg-teal-50 text-teal-800 border border-teal-200/80 font-semibold shadow-2xs'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab 1: Overview */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          {/* Stat Cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-xs">
              <span className="text-[11px] text-slate-500 block">{isCV ? 'Images in ZIP' : 'Dataset Rows'}</span>
              <span className="text-xl font-bold font-mono text-slate-900 tabular-nums">
                {(dataset.sampleCount ?? (isCV ? dataset.profile?.imageCount : null))?.toLocaleString() ?? '—'}
              </span>
              <span className="text-[10px] text-slate-500 block mt-0.5">Reported by the dataset profiler</span>
            </div>

            <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-xs">
              <span className="text-[11px] text-slate-500 block">{isCV ? 'Image Format' : 'Feature Columns'}</span>
              <span className="text-xl font-bold font-mono text-slate-900 tabular-nums">
                {isCV ? dataset.profile?.format ?? '—' : dataset.featureCount ?? '—'}
              </span>
              <span className="text-[10px] text-slate-500 block mt-0.5">
                {isCV ? 'From the image ZIP profile' : 'From the tabular profile'}
              </span>
            </div>

            <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-xs">
              <span className="text-[11px] text-slate-500 block">Target Classes</span>
              <span className="text-xl font-bold font-mono text-slate-900 tabular-nums">
                {dataset.classCount ?? '—'}
              </span>
              <span className="text-[10px] text-slate-500 block mt-0.5">
                Class metadata is not reported by the current profiler
              </span>
            </div>

            <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-xs">
              <span className="text-[11px] text-slate-500 block">Persisted Findings</span>
              <button
                type="button"
                onClick={() => navigate(`/leakage-analysis/${dataset.id}`)}
                className="mt-1 text-sm font-semibold text-teal-700 hover:text-teal-900"
              >
                Open findings
              </button>
              <span className="text-[10px] text-slate-500 block mt-0.5">Finding totals are not included in this response</span>
            </div>

            <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-xs">
              <span className="text-[11px] text-slate-500 block">Last Analysis Timestamp</span>
              <span className="text-xs font-mono font-medium text-slate-800 block truncate">
                {dataset.lastAnalysis != null ? dataset.lastAnalysis.split(' ')[0] : '—'}
              </span>
              <span className="text-[10px] text-slate-500 block mt-0.5">
                {dataset.lastAnalysis != null ? 'Backend-provided metadata' : 'Not reported by the backend'}
              </span>
            </div>
          </div>

          {/* Tabular vs CV Sample Preview Cards */}
          {isCV ? (
            <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
              <h3 className="text-sm font-semibold text-slate-900 mb-2">Image ZIP Profile</h3>
              <p className="text-xs text-slate-500 mb-4">
                Basic archive and sampled image-dimension metadata returned by the backend profiler.
                This is not label, patient, or duplicate analysis.
              </p>
              {dataset.profile?.error && (
                <p role="alert" className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                  The backend returned a profile error: {dataset.profile.error}
                </p>
              )}
              <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <dt className="text-xs text-slate-500">Images in ZIP</dt>
                  <dd className="mt-1 font-mono text-sm text-slate-900">
                    {dataset.profile?.imageCount?.toLocaleString() ?? '—'}
                  </dd>
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <dt className="text-xs text-slate-500">Image format</dt>
                  <dd className="mt-1 font-mono text-sm text-slate-900">
                    {dataset.profile?.format ?? '—'}
                  </dd>
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <dt className="text-xs text-slate-500">Sampled width range</dt>
                  <dd className="mt-1 font-mono text-sm text-slate-900">
                    {formatDimensionRange(dataset.profile?.widthMin, dataset.profile?.widthMax)}
                  </dd>
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <dt className="text-xs text-slate-500">Sampled height range</dt>
                  <dd className="mt-1 font-mono text-sm text-slate-900">
                    {formatDimensionRange(dataset.profile?.heightMin, dataset.profile?.heightMax)}
                  </dd>
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <dt className="text-xs text-slate-500">Images sampled for dimensions</dt>
                  <dd className="mt-1 font-mono text-sm text-slate-900">
                    {dataset.profile?.sampledImages?.toLocaleString() ?? '—'}
                  </dd>
                </div>
              </dl>
              {!dataset.profile && (
                <p className="mt-4 text-xs text-slate-500">
                  No image profile metadata was returned for this dataset.
                </p>
              )}
              </div>
          ) : (
            <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-slate-900">Raw Data Row Previews (First 6 Records)</h3>
                <span className="text-[11px] font-mono text-slate-500">
                  {dataset.columns?.length ?? dataset.featureCount ?? '—'} columns
                </span>
              </div>

              <div className="overflow-x-auto border border-slate-200 rounded-lg">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 text-slate-500 font-mono uppercase tracking-wider">
                    <tr>
                      {dataset.columns?.map((col) => (
                        <th key={col.name} className="px-3 py-2.5 whitespace-nowrap">
                          {col.name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {dataset.previewRows?.map((row, idx) => (
                      <tr key={idx} className="hover:bg-slate-50/80">
                        {dataset.columns?.map((col) => (
                          <td key={col.name} className="px-3 py-2 font-mono tabular-nums text-slate-700 whitespace-nowrap">
                            {String(row[col.name] ?? '-')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Profile */}
      {activeTab === 'profile' && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4 shadow-xs">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-slate-900">
                {isCV ? 'Image ZIP Profile' : 'Feature Schema & Cardinality'}
              </h3>
              <p className="text-xs text-slate-500">
                {isCV
                  ? 'The current ZIP profiler does not extract annotations, classes, or patient identifiers.'
                  : 'Profiled column names, types, missing values, and unique-value counts from the uploaded file.'}
              </p>
            </div>
            <span className="text-xs font-mono text-slate-500">Backend profile fields</span>
          </div>

          {isCV ? (
            <p className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600">
              Image archive counts and sampled dimensions, when available, are shown in the Overview.
              No annotation or label analysis is returned by this upload profiler.
            </p>
          ) : dataset.columns?.length ? (
            <div className="overflow-x-auto border border-slate-200 rounded-lg">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 text-slate-500 font-mono uppercase">
                  <tr>
                    <th className="px-4 py-2.5">Column Name</th>
                    <th className="px-4 py-2.5">Data Type</th>
                    <th className="px-4 py-2.5">Missing Count</th>
                    <th className="px-4 py-2.5">Unique Values</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {dataset.columns.map((col) => (
                    <tr key={col.name} className="hover:bg-slate-50/80">
                      <td className="px-4 py-2.5 font-semibold text-slate-900 font-mono">{col.name}</td>
                      <td className="px-4 py-2.5 text-slate-500 capitalize">{col.type}</td>
                      <td className="px-4 py-2.5 font-mono tabular-nums text-slate-700">
                        {typeof col.missingCount === 'number'
                          ? `${col.missingCount.toLocaleString()}${
                              typeof dataset.sampleCount === 'number' && dataset.sampleCount > 0
                                ? ` (${((col.missingCount / dataset.sampleCount) * 100).toFixed(1)}%)`
                                : ''
                            }`
                          : '—'}
                      </td>
                      <td className="px-4 py-2.5 font-mono tabular-nums text-slate-700">
                        {typeof col.uniqueCount === 'number' ? col.uniqueCount.toLocaleString() : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600">
              No tabular column profile was returned for this dataset.
            </p>
          )}
        </div>
      )}

      {/* Tab 3: Integrity */}
      {activeTab === 'integrity' && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4 shadow-xs">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-slate-900">Persisted Findings</h3>
              <p className="text-xs text-slate-500">
                Finding records and available evidence are loaded in the Leakage Workspace.
              </p>
            </div>
            <button
              onClick={() => navigate(`/leakage-analysis/${dataset.id}`)}
              className="px-3 py-1.5 text-xs font-semibold rounded bg-teal-700 hover:bg-teal-800 text-white transition-colors shadow-xs"
            >
              Open Leakage Workspace
            </button>
          </div>

          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600">
            The dataset profile does not include a finding summary. An empty profile summary does not
            establish that every detector ran.
          </div>
        </div>
      )}

      {/* Tab 4: Distribution & Splits */}
      {activeTab === 'distribution' && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4 shadow-xs">
          <h3 className="text-sm font-semibold text-slate-900">Distribution &amp; Split Information</h3>
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600">
            No split sizes or distribution metrics are included in the dataset profile. The current
            analysis page does not submit split or feature-column selections, so it does not run
            split-based detectors.
          </div>
        </div>
      )}

      {/* Tab 5: History */}
      {activeTab === 'history' && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-3 shadow-xs">
          <h3 className="text-sm font-semibold text-slate-900">Dataset Timestamps</h3>
          <div className="space-y-2 text-xs">
            <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 flex items-center justify-between">
              <div>
                <p className="font-semibold text-slate-900">Dataset upload recorded</p>
                <p className="text-slate-500 text-[11px]">{dataset.uploadedAt}</p>
              </div>
            </div>

            {dataset.lastAnalysis ? (
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                <p className="font-semibold text-slate-900">Last analysis timestamp recorded</p>
                <p className="text-slate-500 text-[11px]">{dataset.lastAnalysis}</p>
              </div>
            ) : (
              <p className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-slate-600">
                No last-analysis timestamp is reported in this dataset record.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
