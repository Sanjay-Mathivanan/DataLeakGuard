import React from 'react';
import { PersistedFinding } from '../../types';
import { getFindingTypeLabel } from '../../services/api';
import { SeverityBadge } from '../common/SeverityBadge';
import { StatusBadge } from '../common/StatusBadge';

export const FindingEvidencePanel: React.FC<{ finding: PersistedFinding }> = ({
  finding,
}) => {
  const evidenceText =
    finding.evidence === null
      ? null
      : JSON.stringify(finding.evidence, null, 2);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 pb-3 border-b border-slate-100">
        <div className="min-w-0">
          <span className="text-[10px] font-mono uppercase tracking-wider text-teal-700 font-semibold">
            Persisted finding
          </span>
          <h3 className="text-base font-bold font-mono text-slate-900 break-all">
            Finding #{finding.id}
          </h3>
        </div>
        <SeverityBadge severity={finding.severity} size="sm" />
      </div>

      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-[11px]">
        <dt className="text-slate-500">Type</dt>
        <dd className="text-slate-800">{getFindingTypeLabel(finding.findingType)}</dd>
        <dt className="text-slate-500">Dataset ID</dt>
        <dd className="font-mono text-slate-800 break-all">{finding.datasetId}</dd>
        <dt className="text-slate-500">Status</dt>
        <dd><StatusBadge status={finding.status} size="sm" /></dd>
        <dt className="text-slate-500">Created</dt>
        <dd className="text-slate-800 break-all">
          {finding.createdAt ?? 'Not provided by backend'}
        </dd>
      </dl>

      <section>
        <h4 className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider font-mono">
          Description
        </h4>
        <p className="text-slate-700 mt-1 leading-relaxed bg-slate-50 p-2.5 rounded border border-slate-200 text-[11px]">
          {finding.description}
        </p>
      </section>

      <section>
        <h4 className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider font-mono">
          Detector evidence
        </h4>
        {evidenceText === null ? (
          <p className="text-slate-500 mt-1 text-[11px]">
            No evidence object was returned by the backend.
          </p>
        ) : (
          <pre
            aria-label="Finding evidence"
            className="text-slate-700 mt-1 leading-relaxed bg-slate-50 p-2.5 rounded border border-slate-200 text-[11px] whitespace-pre-wrap break-words overflow-auto max-h-64"
          >
            {evidenceText}
          </pre>
        )}
      </section>

      <p className="text-[10px] text-slate-500">
        Detector evidence describes an observed association; it does not by itself establish causal leakage.
      </p>
    </div>
  );
};
