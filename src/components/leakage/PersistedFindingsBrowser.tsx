import React, { useEffect, useState } from 'react';
import { DatasetFindingPage } from '../../types';
import { getFindingsPage } from '../../services/api';
import { GroupedFindings } from './GroupedFindings';
import { TableSkeleton } from '../common/LoadingSkeleton';

const detectorOptions = [
  ['exact_duplicate', 'Exact duplicate detection'],
  ['entity_overlap', 'Entity overlap detection'],
  ['target_leakage', 'Target leakage detection'],
  ['temporal_leakage', 'Temporal leakage detection'],
  ['train_test_contamination', 'Train/test contamination detection'],
];

function SummaryCard({
  label,
  value,
}: {
  label: string;
  value: number | undefined;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <span className="block text-[10px] text-slate-500">{label}</span>
      <span className="mt-1 block font-mono text-lg font-semibold tabular-nums text-slate-900">
        {typeof value === 'number' ? value.toLocaleString() : '—'}
      </span>
    </div>
  );
}

export const PersistedFindingsBrowser: React.FC<{ datasetId: string }> = ({ datasetId }) => {
  const [page, setPage] = useState<DatasetFindingPage | null>(null);
  const [search, setSearch] = useState('');
  const [findingType, setFindingType] = useState('');
  const [severity, setSeverity] = useState('');
  const [status, setStatus] = useState('');
  const [limit, setLimit] = useState(25);
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError('');
    const timer = window.setTimeout(() => {
      getFindingsPage(datasetId, {
        skip,
        limit,
        search,
        findingType: findingType || undefined,
        severity: severity || undefined,
        status: status || undefined,
      }).then((result) => {
        if (active) setPage(result);
      }).catch((error: unknown) => {
        if (active) {
          setLoadError(error instanceof Error ? error.message : 'Findings could not be loaded.');
          setPage(null);
        }
      }).finally(() => {
        if (active) setLoading(false);
      });
    }, search ? 250 : 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [datasetId, skip, limit, search, findingType, severity, status]);

  const updateFilter = (update: () => void) => {
    setSkip(0);
    update();
  };
  const summary = page?.datasetSummary;
  const matching = page?.matchingSummary;
  const pageStart = page && page.total > 0 ? page.skip + 1 : 0;
  const pageEnd = page ? Math.min(page.skip + page.items.length, page.total) : 0;

  return (
    <div className="space-y-4">
      {summary && matching && (
        <section aria-label="Finding summary" className="space-y-2">
          <div>
            <h3 className="text-xs font-semibold text-slate-800">Dataset-wide totals</h3>
            <p className="text-[10px] text-slate-500">All persisted findings for this dataset, independent of filters.</p>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <SummaryCard label="Total" value={summary.total} />
            <SummaryCard label="Open" value={summary.open} />
            <SummaryCard label="Resolved" value={summary.resolved} />
            <SummaryCard label="Low" value={summary.low} />
            <SummaryCard label="Medium" value={summary.medium} />
            <SummaryCard label="High" value={summary.high} />
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-500">
            <span>Filtered matches: <strong className="text-slate-800">{matching.total.toLocaleString()}</strong></span>
            <span>Open: {matching.open.toLocaleString()}</span>
            <span>Resolved: {matching.resolved.toLocaleString()}</span>
            <span>Low / medium / high: {matching.low.toLocaleString()} / {matching.medium.toLocaleString()} / {matching.high.toLocaleString()}</span>
            {matching.otherSeverity > 0 && <span>Other severity: {matching.otherSeverity.toLocaleString()}</span>}
          </div>
        </section>
      )}

      <section aria-label="Persisted finding filters" className="grid grid-cols-1 gap-2 rounded-xl border border-slate-200 bg-white p-3 sm:grid-cols-2 xl:grid-cols-5">
        <label className="sm:col-span-2 xl:col-span-1">
          <span className="sr-only">Search findings across all matching records</span>
          <input
            type="search"
            value={search}
            onChange={(event) => updateFilter(() => setSearch(event.target.value))}
            placeholder="Search ID, detector, description, evidence…"
            className="w-full rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-xs text-slate-800"
          />
        </label>
        <label>
          <span className="sr-only">Filter by detector type</span>
          <select
            value={findingType}
            onChange={(event) => updateFilter(() => setFindingType(event.target.value))}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-2 text-xs"
          >
            <option value="">All detector types</option>
            {detectorOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            <option value="other">Other / unknown detector</option>
          </select>
        </label>
        <label>
          <span className="sr-only">Filter by severity</span>
          <select
            value={severity}
            onChange={(event) => updateFilter(() => setSeverity(event.target.value))}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-2 text-xs"
          >
            <option value="">All severities</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
            <option value="other">Other / unclassified</option>
          </select>
        </label>
        <label>
          <span className="sr-only">Filter by status</span>
          <select
            value={status}
            onChange={(event) => updateFilter(() => setStatus(event.target.value))}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-2 text-xs"
          >
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="under_review">Under review</option>
            <option value="resolved">Resolved</option>
            <option value="false_positive">False positive</option>
          </select>
        </label>
        <label>
          <span className="sr-only">Findings per page</span>
          <select
            value={limit}
            onChange={(event) => {
              setSkip(0);
              setLimit(Number(event.target.value));
            }}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-2 text-xs"
          >
            {[10, 25, 50, 100].map((size) => <option key={size} value={size}>{size} per page</option>)}
          </select>
        </label>
      </section>

      {loading ? (
        <div role="status" aria-label="Loading findings">
          <TableSkeleton rows={4} />
        </div>
      ) : loadError ? (
        <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-xs text-rose-800">
          Unable to display persisted findings: {loadError}
        </p>
      ) : page ? (
        <>
          {page.total === 0 ? (
            <p className="rounded-lg border border-slate-200 bg-white p-4 text-xs text-slate-600">
              {summary?.total === 0
                ? 'No persisted findings are available. This does not establish that every detector has run.'
                : 'No persisted findings match the selected search and filters.'}
            </p>
          ) : (
            <GroupedFindings
              findings={page.items}
              counts={page.matchingSummary}
              sourceLabel="Persisted findings returned by the backend. Detector counts are filtered-result totals; expanded records are from this page."
            />
          )}
          <nav aria-label="Findings pagination" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2">
            <p className="text-xs text-slate-600">
              Showing {pageStart.toLocaleString()}–{pageEnd.toLocaleString()} of {page.total.toLocaleString()} matching findings
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setSkip(Math.max(0, skip - limit))}
                disabled={skip === 0 || loading}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40"
              >
                Previous
              </button>
              <span className="text-[11px] text-slate-500">
                Page {page.total === 0 ? 0 : Math.floor(skip / limit) + 1} of {page.total === 0 ? 0 : Math.ceil(page.total / limit)}
              </span>
              <button
                type="button"
                onClick={() => setSkip(skip + limit)}
                disabled={skip + limit >= page.total || loading}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </nav>
        </>
      ) : null}
    </div>
  );
};
