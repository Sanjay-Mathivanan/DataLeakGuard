import React, { useMemo, useState } from 'react';
import { Dataset } from '../../types';
import {
  classifyProfileColumn,
  filterAndSortFeatureColumns,
  ProfileColumnKind,
  ProfileSortKey,
  summarizeFeatureColumns,
} from './featureProfileUtils';

const PAGE_SIZE = 50;

export const FeatureProfiles: React.FC<{ dataset: Dataset }> = ({ dataset }) => {
  const columns = dataset.columns ?? [];
  const [search, setSearch] = useState('');
  const [kind, setKind] = useState('');
  const [missing, setMissing] = useState('');
  const [cardinality, setCardinality] = useState('');
  const [sortBy, setSortBy] = useState<ProfileSortKey>('name');
  const [direction, setDirection] = useState<'asc' | 'desc'>('asc');
  const [pageIndex, setPageIndex] = useState(0);

  const summary = useMemo(
    () => summarizeFeatureColumns(columns, dataset.sampleCount),
    [columns, dataset.sampleCount]
  );
  const filtered = useMemo(
    () => filterAndSortFeatureColumns(columns, {
      search,
      kind: kind as ProfileColumnKind | '',
      missing: missing as 'with' | 'without' | '',
      cardinality: cardinality as 'high' | 'normal' | '',
      rowCount: dataset.sampleCount,
      sortBy,
      direction,
    }),
    [columns, search, kind, missing, cardinality, dataset.sampleCount, sortBy, direction]
  );
  const pageCount = Math.ceil(filtered.length / PAGE_SIZE);
  const visible = filtered.slice(pageIndex * PAGE_SIZE, (pageIndex + 1) * PAGE_SIZE);

  const updateFilter = (update: () => void) => {
    setPageIndex(0);
    update();
  };
  const toggleSort = (key: ProfileSortKey) => {
    if (sortBy === key) setDirection((previous) => previous === 'asc' ? 'desc' : 'asc');
    else {
      setSortBy(key);
      setDirection('asc');
    }
  };

  if (columns.length === 0) {
    return (
      <p className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600">
        No tabular column profile was returned for this dataset.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <section aria-label="Feature profile summary">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          {[
            ['Columns', summary.totalColumns],
            ['Numeric', summary.numericColumns],
            ['Categorical', summary.categoricalColumns],
            ['Date/time', summary.datetimeColumns],
            ['Missing values', summary.totalMissing],
            ['Columns with missing', summary.columnsWithMissing],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-lg border border-slate-200 bg-white p-3">
              <span className="block text-[10px] text-slate-500">{label}</span>
              <strong className="mt-1 block font-mono text-lg tabular-nums text-slate-900">
                {typeof value === 'number' ? value.toLocaleString() : 'Unavailable'}
              </strong>
            </div>
          ))}
        </div>
        {summary.totalMissing === null && (
          <p className="mt-2 text-[10px] text-slate-500">
            Missing-value totals are unavailable because the stored profile does not include every column count.
          </p>
        )}
      </section>

      <section aria-label="Feature profile filters" className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <label>
          <span className="sr-only">Search columns by name</span>
          <input
            type="search"
            value={search}
            onChange={(event) => updateFilter(() => setSearch(event.target.value))}
            placeholder="Search columns by name"
            className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-xs"
          />
        </label>
        <label>
          <span className="sr-only">Filter columns by data type</span>
          <select
            value={kind}
            onChange={(event) => updateFilter(() => setKind(event.target.value))}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-2 text-xs"
          >
            <option value="">All data types</option>
            <option value="numeric">Numeric</option>
            <option value="categorical">Categorical</option>
            <option value="datetime">Date/time</option>
            <option value="other">Other or unclassified</option>
          </select>
        </label>
        <label>
          <span className="sr-only">Filter columns by missing values</span>
          <select
            value={missing}
            onChange={(event) => updateFilter(() => setMissing(event.target.value))}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-2 text-xs"
          >
            <option value="">Any missing-value state</option>
            <option value="with">Has missing values</option>
            <option value="without">No missing values</option>
          </select>
        </label>
        <label>
          <span className="sr-only">Filter columns by cardinality</span>
          <select
            value={cardinality}
            onChange={(event) => updateFilter(() => setCardinality(event.target.value))}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-2 text-xs"
          >
            <option value="">Any cardinality</option>
            <option value="high">High cardinality</option>
            <option value="normal">Not high cardinality</option>
          </select>
        </label>
      </section>

      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full min-w-[900px] text-left text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              {([
                ['name', 'Column name'],
                ['type', 'Data type'],
                ['missing', 'Missing count'],
                ['missingPercent', 'Missing %'],
                ['unique', 'Unique values'],
              ] as Array<[ProfileSortKey, string]>).map(([key, label]) => (
                <th key={key} className="px-3 py-2.5">
                  <button
                    type="button"
                    onClick={() => toggleSort(key)}
                    aria-label={`Sort by ${label}`}
                    className="font-semibold hover:text-slate-900"
                  >
                    {label}{sortBy === key ? (direction === 'asc' ? ' ↑' : ' ↓') : ''}
                  </button>
                </th>
              ))}
              <th className="px-3 py-2.5 font-semibold">Observed statistics</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {visible.map((column) => {
              const columnKind = classifyProfileColumn(column);
              const missingPercent = typeof column.missingCount === 'number'
                && typeof dataset.sampleCount === 'number'
                && dataset.sampleCount > 0
                ? (column.missingCount / dataset.sampleCount) * 100
                : null;
              const topValues = column.statistics?.topValues ?? [];
              return (
                <tr key={column.name} className="align-top hover:bg-slate-50/70">
                  <td className="max-w-xs break-words px-3 py-3 font-mono font-semibold text-slate-900">
                    {column.name}
                  </td>
                  <td className="px-3 py-3 text-slate-600">
                    <span className="capitalize">{column.type}</span>
                    <span className="mt-1 block text-[10px] text-slate-400">{columnKind}</span>
                  </td>
                  <td className="px-3 py-3 font-mono tabular-nums text-slate-700">
                    {typeof column.missingCount === 'number' ? column.missingCount.toLocaleString() : 'Unavailable'}
                  </td>
                  <td className="px-3 py-3 font-mono tabular-nums text-slate-700">
                    {missingPercent === null ? 'Unavailable' : `${missingPercent.toFixed(1)}%`}
                  </td>
                  <td className="px-3 py-3 font-mono tabular-nums text-slate-700">
                    {typeof column.uniqueCount === 'number' ? column.uniqueCount.toLocaleString() : 'Unavailable'}
                  </td>
                  <td className="max-w-xl px-3 py-3 text-slate-600">
                    {column.statistics?.kind === 'numeric' ? (
                      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
                        {([
                          ['Min', column.statistics.min],
                          ['Max', column.statistics.max],
                          ['Mean', column.statistics.mean],
                          ['Median', column.statistics.median],
                        ] as Array<[string, number | null | undefined]>).map(([label, value]) => (
                          <div key={label} className="flex gap-1">
                            <dt className="text-slate-400">{label}</dt>
                            <dd className="font-mono text-slate-700">
                              {typeof value === 'number' ? value.toLocaleString() : 'Unavailable'}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    ) : topValues.length ? (
                      <div>
                        <ul className="space-y-1">
                          {topValues.slice(0, 3).map((entry, index) => (
                            <li key={`${column.name}-preview-${index}`} className="break-words">
                              <span className="font-mono">{entry.value}</span>
                              <span className="text-slate-400"> · {entry.count.toLocaleString()}</span>
                            </li>
                          ))}
                        </ul>
                        {topValues.length > 3 && (
                          <details className="mt-2">
                            <summary className="cursor-pointer text-[10px] font-medium text-teal-800">
                              Show all {topValues.length} stored top values
                            </summary>
                            <ul className="mt-2 space-y-1 border-l border-slate-200 pl-2">
                              {topValues.slice(3).map((entry, index) => (
                                <li key={`${column.name}-extra-${index}`} className="break-words">
                                  <span className="font-mono">{entry.value}</span>
                                  <span className="text-slate-400"> · {entry.count.toLocaleString()}</span>
                                </li>
                              ))}
                            </ul>
                          </details>
                        )}
                      </div>
                    ) : columnKind === 'datetime' ? (
                      <span className="text-[10px] text-slate-500">Date/time profile detected; range statistics are unavailable.</span>
                    ) : (
                      <span className="text-[10px] text-slate-500">No additional statistics are available.</span>
                    )}
                  </td>
                </tr>
              );
            })}
            {visible.length === 0 && (
              <tr><td colSpan={6} className="p-5 text-center text-xs text-slate-500">No columns match the selected search and filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {filtered.length > PAGE_SIZE && (
        <nav aria-label="Feature profile pagination" className="flex items-center justify-between text-xs">
          <span className="text-slate-500">
            Showing {pageIndex * PAGE_SIZE + 1}–{Math.min((pageIndex + 1) * PAGE_SIZE, filtered.length)} of {filtered.length} columns
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setPageIndex((previous) => Math.max(0, previous - 1))}
              disabled={pageIndex === 0}
              className="rounded border border-slate-300 px-3 py-1.5 disabled:opacity-40"
            >Previous</button>
            <span className="py-1.5 text-slate-500">Page {pageIndex + 1} of {pageCount}</span>
            <button
              type="button"
              onClick={() => setPageIndex((previous) => Math.min(pageCount - 1, previous + 1))}
              disabled={pageIndex >= pageCount - 1}
              className="rounded border border-slate-300 px-3 py-1.5 disabled:opacity-40"
            >Next</button>
          </div>
        </nav>
      )}
    </div>
  );
};
