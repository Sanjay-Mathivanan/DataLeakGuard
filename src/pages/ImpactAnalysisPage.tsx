import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  TrendingDown,
  AlertTriangle,
  Info,
  ArrowRight,
  ShieldCheck,
  FileText,
  BarChart2,
  CheckCircle2
} from 'lucide-react';
import { getDatasets, getImpactAnalysis } from '../services/api';
import { ImpactAnalysis } from '../types';
import { CardSkeleton } from '../components/common/LoadingSkeleton';

export const ImpactAnalysisPage: React.FC = () => {
  const navigate = useNavigate();
  const [data, setData] = useState<ImpactAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [datasetId, setDatasetId] = useState('');
  const [datasets, setDatasets] = useState<Awaited<ReturnType<typeof getDatasets>>>([]);

  useEffect(() => {
    async function load() {
      try {
        const datasets = await getDatasets();
        if (datasets.length === 0) return;
        setDatasets(datasets);
        setDatasetId((current) => current || datasets[0].id);
        const res = await getImpactAnalysis(datasetId || datasets[0].id);
        setData(res);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [datasetId]);

  if (loading || !data) {
    return (
      <div className="space-y-6">
        <CardSkeleton />
        <CardSkeleton />
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <span className="text-xs font-mono text-teal-700 uppercase tracking-wider font-semibold">
            Persisted Impact Metrics
          </span>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 font-mono mt-1">
            Findings & Operations Impact
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Review persisted findings and repair-operation counts. This workflow does not evaluate model accuracy.
          </p>
        </div>
        <select
          aria-label="Impact dataset"
          value={datasetId}
          onChange={(event) => setDatasetId(event.target.value)}
          className="px-3 py-2 text-xs border border-slate-200 rounded-lg bg-white"
        >
          {datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}
        </select>

        <button
          onClick={() => navigate('/reports/REP-2026-0042')}
          className="px-4 py-2 text-xs font-semibold rounded-lg bg-teal-700 hover:bg-teal-800 text-white transition-colors flex items-center gap-2 self-start sm:self-auto shadow-xs"
        >
          <FileText className="w-4 h-4" />
          <span>Generate Persisted Report</span>
        </button>
      </div>

      {/* Highlighted Evaluation Inflation Card */}
      <div className="bg-white border border-amber-200 rounded-2xl p-6 relative overflow-hidden shadow-xs">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="space-y-2 max-w-xl">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono font-bold text-amber-800 uppercase tracking-wider">
                Assurance Metric Highlight
              </span>
              <span className="text-[10px] px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-mono border border-slate-200">
                Persisted operational counts
              </span>
            </div>

            <h2 className="text-xl md:text-2xl font-bold font-mono text-slate-900">
            No model-performance claim is made
            </h2>

            <p className="text-xs text-slate-600 leading-relaxed">
              <strong className="text-amber-800">Persisted operational metrics:</strong>{' '}
              Counts below are derived from owned findings and operations; no contaminated-versus-corrected accuracy comparison is generated.
            </p>
          </div>

          <div className="flex items-center gap-4 shrink-0 bg-slate-50 p-4 rounded-xl border border-slate-200 shadow-2xs">
            <div className="text-center px-2">
              <span className="text-[11px] text-slate-500 block font-mono">Findings</span>
              <span className="text-2xl font-bold font-mono text-rose-600 tabular-nums">{data.metrics[0]?.contaminated ?? 0}</span>
            </div>
            <span className="text-slate-400 text-xl font-mono">→</span>
            <div className="text-center px-2">
              <span className="text-[11px] text-slate-500 block font-mono">Affected rows</span>
              <span className="text-2xl font-bold font-mono text-emerald-600 tabular-nums">{data.metrics[4]?.contaminated ?? 0}</span>
            </div>
          </div>
        </div>

        {/* Causal Disclaimer Note */}
        <div className="mt-4 pt-3 border-t border-slate-200 flex items-start gap-2 text-xs text-slate-600">
          <Info className="w-4 h-4 text-teal-700 shrink-0 mt-0.5" />
          <p className="leading-relaxed">
            {data.evaluationInflationSummary.nuance}
          </p>
        </div>
      </div>

      {/* Comparison Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
        {data.metrics.map((m) => (
          <div key={m.metric} className="p-4 rounded-xl border border-slate-200 bg-white shadow-xs flex flex-col justify-between">
            <div>
              <span className="text-xs font-semibold text-slate-700">{m.metric}</span>
              <div className="mt-2 flex items-baseline justify-between">
                <span className="text-lg font-bold font-mono text-slate-900 tabular-nums">
                  {m.corrected.toFixed(1)}%
                </span>
                <span className="text-xs font-mono text-rose-600 tabular-nums line-through opacity-70">
                  {m.contaminated.toFixed(1)}%
                </span>
              </div>
            </div>

            <div className="mt-3 pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] font-mono">
              <span className="text-slate-500">Inflation Delta:</span>
              <span className="text-amber-700 font-bold tabular-nums">+{m.difference.toFixed(1)} pp</span>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs">
        <h3 className="text-sm font-semibold text-slate-900">Persisted metric interpretation</h3>
        <p className="text-xs text-slate-600 mt-2">
          The values above are counts from this dataset&apos;s persisted findings and operations. No contaminated-versus-sanitized
          evaluation or model-performance comparison is available.
        </p>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-3 shadow-xs">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-800 font-mono flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-teal-700" />
          <span>Metric scope and limitations</span>
        </h4>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs text-slate-600 leading-relaxed">
          <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
            <span className="text-slate-900 font-semibold block mb-1">Persisted findings</span>
            <p>Counts include only findings currently persisted for the selected owned dataset.</p>
          </div>
          <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
            <span className="text-slate-900 font-semibold block mb-1">Persisted operations</span>
            <p>Operation and affected-row counts are read from persisted repair and quarantine records.</p>
          </div>
          <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
            <span className="text-slate-900 font-semibold block mb-1">No model evaluation</span>
            <p>Accuracy, F1, ROC-AUC, causal impact, and generalization claims are outside this workflow.</p>
          </div>
        </div>
      </div>
    </div>
  );
};
