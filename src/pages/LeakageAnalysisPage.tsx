import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Search,
  Copy,
  Users,
  Target,
  Clock,
  Sparkles,
  GitBranch,
  Wrench
} from 'lucide-react';
import { FindingCategorySummary, PersistedFinding } from '../types';
import { getFindings, getFindingTypeLabel, summarizeFindings } from '../services/api';
import { StatusBadge } from '../components/common/StatusBadge';
import { SeverityBadge } from '../components/common/SeverityBadge';
import { TableSkeleton } from '../components/common/LoadingSkeleton';
import { FindingEvidencePanel } from '../components/leakage/FindingEvidencePanel';
import { getDatasetWorkflowPath } from '../services/datasetNavigation';

export const LeakageAnalysisPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [categories, setCategories] = useState<FindingCategorySummary[]>([]);
  const [findings, setFindings] = useState<PersistedFinding[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [selectedFinding, setSelectedFinding] = useState<PersistedFinding | null>(null);

  // Filters
  const [search, setSearch] = useState('');
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [typeFilter, setTypeFilter] = useState<string>('all');

  useEffect(() => {
    let cancelled = false;

    if (!id) {
      setLoading(false);
      setLoadError('Select a dataset to view persisted findings.');
      return () => {
        cancelled = true;
      };
    }

    const datasetId = id;
    async function load() {
      setLoading(true);
      setLoadError(null);
      setCategories([]);
      setFindings([]);
      setSelectedFinding(null);
      setSearch('');
      setSeverityFilter('all');
      setTypeFilter('all');

      try {
        const persistedFindings = await getFindings(datasetId);
        if (!cancelled) {
          setFindings(persistedFindings);
          setCategories(summarizeFindings(persistedFindings));
          setSelectedFinding(persistedFindings[0] ?? null);
        }
      } catch (error) {
        if (!cancelled) {
          setLoadError(error instanceof Error ? error.message : 'Unable to load persisted findings.');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    load();

    return () => {
      cancelled = true;
    };
  }, [id]);

  const getCategoryIcon = (findingType: string) => {
    switch (findingType) {
      case 'exact_duplicate':
        return Copy;
      case 'entity_overlap':
        return Users;
      case 'target_leakage':
        return Target;
      case 'temporal_leakage':
        return Clock;
      case 'train_test_contamination':
        return Sparkles;
      default:
        return GitBranch;
    }
  };

  const filteredFindings = findings.filter((f) => {
    const evidenceText = f.evidence === null ? '' : JSON.stringify(f.evidence) ?? '';
    const searchText = `${f.id} ${f.findingType} ${f.description} ${evidenceText}`.toLowerCase();
    const matchesSearch = searchText.includes(search.toLowerCase());
    const matchesSeverity =
      severityFilter === 'all' || f.severity.toLowerCase() === severityFilter.toLowerCase();
    const matchesType = typeFilter === 'all' || f.findingType === typeFilter;
    return matchesSearch && matchesSeverity && matchesType;
  });

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <span className="text-xs font-mono text-teal-700 uppercase tracking-wider font-semibold">
            DataLeakGuard Core
          </span>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 font-mono mt-1">
            Leakage & Integrity Analysis
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Review persisted integrity findings and the detector evidence returned by the backend.
          </p>
        </div>

        <button
          onClick={() => navigate(getDatasetWorkflowPath('repair', id))}
          className="px-4 py-2 text-xs font-semibold rounded-lg bg-teal-700 hover:bg-teal-800 text-white transition-colors flex items-center gap-2 self-start sm:self-auto shadow-xs"
        >
          <Wrench className="w-4 h-4" />
          <span>Proceed to Repair & Quarantine</span>
        </button>
      </div>

      <section aria-label="Persisted finding categories" className="space-y-3">
        <p className="text-[11px] text-slate-500">
          Category counts summarize persisted findings only; this endpoint does not report which detectors ran.
        </p>
        {loadError ? null : loading ? null : categories.length === 0 ? (
          <p className="p-4 rounded-xl border border-slate-200 bg-white text-xs text-slate-600">
            No persisted findings were returned for this dataset. Detector execution status is not available here.
          </p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {categories.map((cat) => {
              const Icon = getCategoryIcon(cat.findingType);
              return (
                <button
                  type="button"
                  key={cat.findingType}
                  onClick={() => setTypeFilter(cat.findingType)}
                  className={`p-4 rounded-xl border text-left transition-all shadow-xs ${
                    typeFilter === cat.findingType
                      ? 'bg-teal-50/70 border-teal-600 shadow-sm'
                      : 'bg-white border-slate-200 hover:border-slate-300'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <div className="p-1.5 rounded-lg bg-teal-50 text-teal-700 border border-teal-100">
                      <Icon className="w-4 h-4" />
                    </div>
                    <h3 className="text-xs font-semibold text-slate-900">{cat.label}</h3>
                  </div>
                  <span className="text-xl font-bold font-mono text-slate-900 tabular-nums">
                    {cat.findingsCount}
                  </span>
                  <span className="text-[10px] text-slate-500 ml-1.5">persisted findings</span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      {/* Filter and Findings Workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Findings Table (2 columns wide on desktop) */}
        <div className="lg:col-span-2 space-y-4">
          <div className="bg-white border border-slate-200 rounded-xl p-4 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 shadow-xs">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
              <input
                type="text"
                placeholder="Search persisted findings by ID, type, description, or evidence..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:border-teal-600"
              />
            </div>

            <div className="flex items-center gap-2">
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                aria-label="Filter findings by leakage type"
                className="bg-slate-50 border border-slate-200 text-xs text-slate-700 rounded-lg px-3 py-1.5 focus:outline-none focus:border-teal-600"
              >
                <option value="all">All Types</option>
                {categories.map((category) => (
                  <option key={category.findingType} value={category.findingType}>
                    {category.label}
                  </option>
                ))}
              </select>

              <select
                value={severityFilter}
                onChange={(e) => setSeverityFilter(e.target.value)}
                aria-label="Filter findings by severity"
                className="bg-slate-50 border border-slate-200 text-xs text-slate-700 rounded-lg px-3 py-1.5 focus:outline-none focus:border-teal-600"
              >
                <option value="all">All Severities</option>
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
          </div>

          {loading ? (
            <TableSkeleton rows={4} />
          ) : loadError ? (
            <p role="alert" className="p-4 rounded-xl border border-rose-200 bg-rose-50 text-xs text-rose-800">
              Unable to display findings: {loadError}
            </p>
          ) : filteredFindings.length === 0 ? (
            <p className="p-4 rounded-xl border border-slate-200 bg-white text-xs text-slate-600">
              {findings.length === 0
                ? 'No persisted findings were returned. This does not establish that every detector ran.'
                : 'No findings match the selected filters.'}
            </p>
          ) : (
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-xs">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 text-slate-500 font-mono uppercase tracking-wider border-b border-slate-200">
                    <tr>
                      <th className="px-4 py-3 font-semibold">Finding ID</th>
                      <th className="px-4 py-3 font-semibold">Type</th>
                      <th className="px-4 py-3 font-semibold">Description</th>
                      <th className="px-4 py-3 font-semibold">Severity</th>
                      <th className="px-4 py-3 font-semibold">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {filteredFindings.map((f) => {
                      const isSelected = selectedFinding?.id === f.id;
                      return (
                        <tr
                          key={f.id}
                          onClick={() => setSelectedFinding(f)}
                          className={`cursor-pointer transition-colors ${
                            isSelected
                              ? 'bg-teal-50/70 border-l-2 border-l-teal-600'
                              : 'hover:bg-slate-50/70'
                          }`}
                        >
                          <td className="px-4 py-3 font-mono font-semibold text-teal-700 whitespace-nowrap">
                            #{f.id}
                          </td>
                          <td className="px-4 py-3 capitalize text-slate-800 whitespace-nowrap">
                            {getFindingTypeLabel(f.findingType)}
                          </td>
                          <td className="px-4 py-3 text-slate-600 max-w-sm">
                            <span className="line-clamp-2">{f.description}</span>
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap">
                            <SeverityBadge severity={f.severity} size="sm" />
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap">
                            <StatusBadge status={f.status} size="sm" />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        {/* Detailed Side Panel (1 column wide on desktop) */}
        <div className="bg-white border border-slate-200 rounded-xl p-5 sticky top-20 self-start space-y-4 shadow-xs">
          {selectedFinding ? (
            <FindingEvidencePanel finding={selectedFinding} />
          ) : (
            <p className="text-xs text-slate-500 text-center py-8">
              {loading
                ? 'Loading persisted findings...'
                : loadError
                ? 'Finding details are unavailable because the request failed.'
                : 'Select a persisted finding row to view its description and available evidence.'}
            </p>
          )}
        </div>
      </div>
    </div>
  );
};
