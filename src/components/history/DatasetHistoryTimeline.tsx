import React, { useEffect, useState } from 'react';
import { DatasetHistoryPage } from '../../types';
import { getDatasetHistoryPage } from '../../services/api';

const operationTypes = [
  'dataset_upload',
  'analysis',
  'repair',
  'combined_repair',
  'quarantine',
];

export function getHistoryStatusClass(value: string): string {
  switch (value.toLowerCase()) {
    case 'completed':
      return 'border-emerald-200 bg-emerald-50 text-emerald-800';
    case 'failed':
      return 'border-rose-200 bg-rose-50 text-rose-800';
    case 'running':
    case 'processing':
      return 'border-sky-200 bg-sky-50 text-sky-800';
    case 'pending':
      return 'border-amber-200 bg-amber-50 text-amber-800';
    default:
      return 'border-slate-200 bg-slate-50 text-slate-700';
  }
}

export const DatasetHistoryTimeline: React.FC<{ datasetId: string }> = ({ datasetId }) => {
  const [page, setPage] = useState<DatasetHistoryPage | null>(null);
  const [eventType, setEventType] = useState('');
  const [status, setStatus] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [search, setSearch] = useState('');
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    const timer = window.setTimeout(() => {
      getDatasetHistoryPage(datasetId, {
        skip,
        limit: 25,
        eventType: eventType || undefined,
        status: status || undefined,
        startDate: startDate
          ? new Date(`${startDate}T00:00:00.000Z`).toISOString()
          : undefined,
        endDate: endDate
          ? new Date(`${endDate}T23:59:59.999Z`).toISOString()
          : undefined,
        search,
      }).then((result) => {
        if (active) setPage(result);
      }).catch((failure: unknown) => {
        if (active) {
          setPage(null);
          setError(failure instanceof Error ? failure.message : 'Dataset history could not be loaded.');
        }
      }).finally(() => {
        if (active) setLoading(false);
      });
    }, search ? 250 : 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [datasetId, skip, eventType, status, startDate, endDate, search]);

  const resetPage = (update: () => void) => {
    setSkip(0);
    update();
  };
  const first = page && page.total ? page.skip + 1 : 0;
  const last = page ? Math.min(page.skip + page.items.length, page.total) : 0;

  return (
    <section aria-label="Dataset audit history" className="space-y-4">
      <div className="grid grid-cols-1 gap-2 rounded-xl border border-slate-200 bg-white p-3 sm:grid-cols-2 lg:grid-cols-3">
        <label>
          <span className="sr-only">Search operation ID or dataset name</span>
          <input
            type="search"
            value={search}
            onChange={(event) => resetPage(() => setSearch(event.target.value))}
            placeholder="Search operation ID or dataset name"
            className="w-full rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-xs"
          />
        </label>
        <label>
          <span className="sr-only">Filter activity type</span>
          <select
            value={eventType}
            onChange={(event) => resetPage(() => setEventType(event.target.value))}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-2 text-xs"
          >
            <option value="">All activity types</option>
            {operationTypes.map((type) => (
              <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="sr-only">Filter activity status</span>
          <select
            value={status}
            onChange={(event) => resetPage(() => setStatus(event.target.value))}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-2 text-xs"
          >
            <option value="">All statuses</option>
            {['completed', 'failed', 'running', 'processing', 'pending', 'recorded', 'unavailable'].map((value) => (
              <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="block text-[10px] text-slate-500">From date</span>
          <input
            aria-label="History start date"
            type="date"
            value={startDate}
            onChange={(event) => resetPage(() => setStartDate(event.target.value))}
            className="w-full rounded-md border border-slate-300 px-2 py-2 text-xs"
          />
        </label>
        <label>
          <span className="block text-[10px] text-slate-500">Through date</span>
          <input
            aria-label="History end date"
            type="date"
            value={endDate}
            onChange={(event) => resetPage(() => setEndDate(event.target.value))}
            className="w-full rounded-md border border-slate-300 px-2 py-2 text-xs"
          />
        </label>
      </div>

      {loading ? (
        <p role="status" className="rounded-lg border border-slate-200 bg-white p-4 text-xs text-slate-500">
          Loading persisted activity…
        </p>
      ) : error ? (
        <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-xs text-rose-800">
          Unable to load audit history: {error}
        </p>
      ) : page?.total === 0 ? (
        <p className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600">
          No persisted activity matches these filters.
        </p>
      ) : page ? (
        <>
          <ol className="relative space-y-3 border-l border-slate-200 pl-4">
            {page.items.map((item) => (
              <li key={item.id} className="relative">
                <span aria-hidden="true" className="absolute -left-[21px] top-4 h-2.5 w-2.5 rounded-full border-2 border-white bg-teal-600 ring-1 ring-slate-300" />
                <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-xs">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <h4 className="text-xs font-semibold capitalize text-slate-900">
                        {item.eventType.replaceAll('_', ' ')}
                      </h4>
                      <p className="mt-1 text-[11px] text-slate-500">
                        {item.datasetName || `Dataset ${item.datasetId}`}
                      </p>
                    </div>
                    <span className={`rounded-full border px-2 py-1 text-[10px] font-semibold uppercase ${getHistoryStatusClass(item.outcome)}`}>
                      {item.outcome}
                    </span>
                  </div>
                  <p className="mt-2 text-[11px] text-slate-600">
                    {item.createdAt ? new Date(item.completedAt ?? item.createdAt).toLocaleString() : 'Timestamp unavailable'}
                    {item.completedAt && ` · started ${new Date(item.createdAt).toLocaleString()}`}
                  </p>
                  <details className="mt-3 border-t border-slate-100 pt-2">
                    <summary className="cursor-pointer text-[11px] font-medium text-teal-800">
                      Inspect activity details
                    </summary>
                    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[10px]">
                      <dt className="text-slate-500">Activity ID</dt><dd className="break-all font-mono text-slate-700">{item.id}</dd>
                      {item.operationId && <><dt className="text-slate-500">Operation ID</dt><dd className="break-all font-mono text-slate-700">{item.operationId}</dd></>}
                      {item.findingId && <><dt className="text-slate-500">Finding ID</dt><dd className="break-all font-mono text-slate-700">{item.findingId}</dd></>}
                      {item.userId && <><dt className="text-slate-500">Actor ID</dt><dd className="break-all font-mono text-slate-700">{item.userId}</dd></>}
                    </dl>
                    {item.failureReason && (
                      <p className="mt-2 rounded bg-rose-50 p-2 text-[11px] text-rose-800">
                        Failure reason: {item.failureReason}
                      </p>
                    )}
                    {item.details && (
                      <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 text-[10px] text-slate-700">
                        {JSON.stringify(item.details, null, 2)}
                      </pre>
                    )}
                    {!item.details && !item.failureReason && (
                      <p className="mt-2 text-[10px] text-slate-500">No additional operation details were persisted.</p>
                    )}
                  </details>
                </article>
              </li>
            ))}
          </ol>
          <nav aria-label="Audit history pagination" className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2">
            <p className="text-xs text-slate-600">
              Showing {first.toLocaleString()}–{last.toLocaleString()} of {page.total.toLocaleString()} activities
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setSkip(Math.max(0, skip - page.limit))}
                disabled={skip === 0 || loading}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40"
              >Previous</button>
              <button
                type="button"
                onClick={() => setSkip(skip + page.limit)}
                disabled={skip + page.limit >= page.total || loading}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40"
              >Next</button>
            </div>
          </nav>
        </>
      ) : null}
    </section>
  );
};
