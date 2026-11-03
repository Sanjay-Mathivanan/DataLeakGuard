import React, { useMemo, useState } from 'react';

export interface SelectableColumn {
  name: string;
  type: string;
}

type ColumnTypeFilter = '' | 'numeric' | 'categorical' | 'datetime' | 'other';

function selectorKind(type: string): Exclude<ColumnTypeFilter, ''> {
  const value = type.toLowerCase();
  if (/(datetime|timestamp|date)/.test(value)) return 'datetime';
  if (/^(u?int|float|double|decimal|numeric|number)/.test(value)) return 'numeric';
  if (/^(object|string|str|bool|boolean|category)/.test(value)) return 'categorical';
  return 'other';
}

export function filterColumnOptions(
  columns: SelectableColumn[],
  search: string,
  kind: ColumnTypeFilter
): SelectableColumn[] {
  const normalized = search.trim().toLocaleLowerCase();
  return columns.filter((column) => (
    column.name.toLocaleLowerCase().includes(normalized)
    && (!kind || selectorKind(column.type) === kind)
  ));
}

export const SearchableColumnSelector: React.FC<{
  label: string;
  value: string;
  columns: SelectableColumn[];
  disabled?: boolean;
  onChange: (value: string) => void;
}> = ({ label, value, columns, disabled = false, onChange }) => {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [kind, setKind] = useState<ColumnTypeFilter>('');
  const [visibleCount, setVisibleCount] = useState(50);
  const filtered = useMemo(
    () => filterColumnOptions(columns, search, kind),
    [columns, search, kind]
  );

  const openSelector = () => {
    setSearch('');
    setKind('');
    setVisibleCount(50);
    setOpen(true);
  };

  return (
    <div className="block">
      <span className="mb-1 block text-xs font-medium text-slate-700">{label}</span>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={disabled || columns.length === 0}
          onClick={openSelector}
          aria-haspopup="dialog"
          className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-left text-sm text-slate-800 disabled:bg-slate-100"
        >
          {value || 'Choose a column'}
        </button>
        {value && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange('')}
            aria-label={`Clear ${label.toLowerCase()}`}
            className="rounded-lg border border-slate-300 px-3 text-xs text-slate-600 disabled:opacity-50"
          >
            Clear
          </button>
        )}
      </div>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setOpen(false);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-label={`Select ${label}`}
            onKeyDown={(event) => {
              if (event.key === 'Escape') setOpen(false);
            }}
            className="flex max-h-[85vh] w-full max-w-xl flex-col rounded-xl border border-slate-200 bg-white p-4 shadow-xl"
          >
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-slate-900">Select {label}</h3>
              <button type="button" onClick={() => setOpen(false)} className="rounded px-2 py-1 text-xs text-slate-600 hover:bg-slate-100">
                Close
              </button>
            </div>
            <label className="mt-3">
              <span className="sr-only">Search column names</span>
              <input
                autoFocus
                type="search"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setVisibleCount(50);
                }}
                placeholder="Search column names…"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="mt-2">
              <span className="sr-only">Filter columns by type</span>
              <select
                value={kind}
                onChange={(event) => {
                  setKind(event.target.value as ColumnTypeFilter);
                  setVisibleCount(50);
                }}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs"
              >
                <option value="">All data types</option>
                <option value="numeric">Numeric</option>
                <option value="categorical">Categorical</option>
                <option value="datetime">Date/time</option>
                <option value="other">Other or unclassified</option>
              </select>
            </label>
            <p className="mt-2 text-[11px] text-slate-500" role="status">
              {filtered.length.toLocaleString()} matching columns · showing {Math.min(visibleCount, filtered.length).toLocaleString()}
            </p>
            <div role="listbox" aria-label="Matching columns" className="mt-2 min-h-0 flex-1 overflow-y-auto rounded-lg border border-slate-200">
              {filtered.slice(0, visibleCount).map((column) => (
                <button
                  key={column.name}
                  type="button"
                  role="option"
                  aria-selected={column.name === value}
                  onClick={() => {
                    onChange(column.name);
                    setOpen(false);
                  }}
                  className={`flex w-full items-center justify-between gap-3 border-b border-slate-100 px-3 py-2 text-left last:border-b-0 hover:bg-teal-50 ${
                    column.name === value ? 'bg-teal-50' : 'bg-white'
                  }`}
                >
                  <span className="break-all font-mono text-xs text-slate-900">{column.name}</span>
                  <span className="shrink-0 text-[10px] text-slate-500">{column.type}</span>
                </button>
              ))}
              {filtered.length === 0 && (
                <p className="p-4 text-center text-xs text-slate-500">No columns match this search and type filter.</p>
              )}
            </div>
            {filtered.length > visibleCount && (
              <button
                type="button"
                onClick={() => setVisibleCount((count) => count + 50)}
                className="mt-2 rounded border border-slate-300 px-3 py-2 text-xs text-slate-700"
              >
                Show next 50 columns
              </button>
            )}
          </section>
        </div>
      )}
    </div>
  );
};
