import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, Database, PlusCircle, ShieldAlert, Clock } from 'lucide-react';
import { CardSkeleton, TableSkeleton } from '../components/common/LoadingSkeleton';
import { DashboardSummary, getActivities, getDashboardSummary } from '../services/api';
import { Activity } from '../types';

const formatTimestamp = (value: string | null): string =>
  value ? new Date(value).toLocaleString() : 'Not available';

export const DashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState<DashboardSummary | null>(null);
  const [activities, setActivities] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    let active = true;
    Promise.all([getDashboardSummary(), getActivities()])
      .then(([summary, history]) => {
        if (!active) return;
        setStats(summary);
        setActivities(history);
      })
      .catch((error: unknown) => {
        if (active) setLoadError(error instanceof Error ? error.message : 'Dashboard data is unavailable.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">{Array.from({ length: 4 }, (_, i) => <CardSkeleton key={i} />)}</div>
        <TableSkeleton rows={4} />
      </div>
    );
  }

  if (loadError || !stats) {
    return <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-800">{loadError || 'Dashboard data is unavailable.'}</div>;
  }

  const cards = [
    { label: 'Datasets', value: stats.datasetCount, icon: Database, href: '/datasets' },
    { label: 'Persisted Findings', value: stats.findingCount, icon: AlertCircle, href: '/datasets' },
    { label: 'Open Findings', value: stats.openFindingCount, icon: ShieldAlert, href: '/datasets' },
    { label: 'High / Critical', value: stats.highOrCriticalFindingCount, icon: AlertCircle, href: '/datasets' },
  ];

  return (
    <div className="space-y-7 animate-in fade-in duration-200">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 font-mono">Dataset Integrity Overview</h1>
          <p className="text-xs text-slate-500 mt-1">Counts below come from persisted records belonging to your account.</p>
        </div>
        <button onClick={() => navigate('/datasets')} className="px-4 py-2 text-xs font-semibold rounded-lg bg-teal-700 hover:bg-teal-800 text-white flex items-center gap-2">
          <PlusCircle className="w-4 h-4" /> Upload or analyze dataset
        </button>
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        {cards.map(({ label, value, icon: Icon, href }) => (
          <button key={label} onClick={() => navigate(href)} className="text-left p-4 rounded-xl border border-slate-200 bg-white shadow-xs hover:border-teal-300">
            <div className="flex items-center justify-between text-slate-500"><span className="text-xs">{label}</span><Icon className="w-4 h-4 text-teal-700" /></div>
            <div className="mt-3 text-2xl font-bold font-mono text-slate-900">{value.toLocaleString()}</div>
            <div className="mt-1 text-[10px] text-slate-500">Persisted record count</div>
          </button>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
          <div className="flex items-center gap-2"><Clock className="w-4 h-4 text-teal-700" /><h2 className="text-sm font-semibold text-slate-900">Analysis activity</h2></div>
          <p className="mt-3 text-xs text-slate-500">Most recent completed analysis</p>
          <p className="mt-1 font-mono text-sm text-slate-900">{formatTimestamp(stats.latestAnalysisAt)}</p>
        </section>
        <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
          <h2 className="text-sm font-semibold text-slate-900">Model and report metrics</h2>
          <p className="mt-2 text-xs text-slate-600">Models: unavailable — {stats.models.reason || 'no persisted model registry'}</p>
          <p className="mt-1 text-xs text-slate-600">Reports: unavailable — {stats.reports.reason || 'no persisted report registry'}</p>
        </section>
      </div>

      <section className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-xs">
        <div className="p-5 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-900">Recently analyzed datasets</h2>
        </div>
        {stats.recentDatasets.length === 0 ? (
          <p className="p-5 text-xs text-slate-500">No datasets are associated with this account yet.</p>
        ) : (
          <div className="divide-y divide-slate-100">
            {stats.recentDatasets.map((dataset) => (
              <button key={dataset.id} onClick={() => navigate(`/datasets/${dataset.id}`)} className="w-full text-left px-5 py-3 hover:bg-slate-50 flex items-center justify-between gap-4">
                <span><span className="block text-xs font-semibold text-slate-800">{dataset.name}</span><span className="block mt-1 text-[10px] text-slate-500">{formatTimestamp(dataset.lastAnalysis)}</span></span>
                <span className="text-[10px] text-slate-600">{dataset.status || 'Status unavailable'}</span>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-xs">
        <div className="p-5 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-900">Recent recorded activity</h2>
          <p className="text-xs text-slate-500 mt-1">Only events persisted by the application are listed.</p>
        </div>
        {activities.length === 0 ? <p className="p-5 text-xs text-slate-500">No recorded events yet.</p> : (
          <div className="divide-y divide-slate-100">
            {activities.map((event) => (
              <button key={event.id} onClick={() => event.targetId && navigate(`/datasets/${event.targetId}`)} className="w-full text-left p-4 hover:bg-slate-50">
                <span className="text-xs font-semibold text-slate-800">{event.title}</span>
                <span className="block mt-1 text-xs text-slate-600">{event.description}</span>
                <span className="block mt-1 text-[10px] text-slate-400">{event.timestamp}</span>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
};
