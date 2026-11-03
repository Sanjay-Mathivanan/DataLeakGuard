import React from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Wrench } from 'lucide-react';
import { PersistedFindingsBrowser } from '../components/leakage/PersistedFindingsBrowser';
import { getDatasetWorkflowPath } from '../services/datasetNavigation';

export const LeakageAnalysisPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <span className="text-xs font-mono font-semibold uppercase tracking-wider text-teal-700">
            DataLeakGuard Core
          </span>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900 font-mono">
            Leakage &amp; Integrity Findings
          </h1>
          <p className="mt-1 text-xs text-slate-500">
            Search and review persisted backend findings. Current-run detector results are shown separately on the analysis page.
          </p>
        </div>
        {id && (
          <button
            type="button"
            onClick={() => navigate(getDatasetWorkflowPath('repair', id))}
            className="flex items-center gap-2 self-start rounded-lg bg-teal-700 px-4 py-2 text-xs font-semibold text-white shadow-xs transition-colors hover:bg-teal-800 sm:self-auto"
          >
            <Wrench className="h-4 w-4" />
            <span>Proceed to Repair &amp; Quarantine</span>
          </button>
        )}
      </header>
      {id ? (
        <PersistedFindingsBrowser datasetId={id} />
      ) : (
        <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900">
          Select a dataset to view its persisted findings.
        </p>
      )}
    </div>
  );
};
