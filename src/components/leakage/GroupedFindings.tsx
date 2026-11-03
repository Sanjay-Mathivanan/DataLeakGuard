import React from 'react';
import { FindingCounts, PersistedFinding } from '../../types';
import { getFindingTypeLabel } from '../../services/api';
import { SeverityBadge } from '../common/SeverityBadge';
import { StatusBadge } from '../common/StatusBadge';

const detectorOrder = [
  'exact_duplicate',
  'entity_overlap',
  'target_leakage',
  'temporal_leakage',
  'train_test_contamination',
];

const severityOrder = ['low', 'medium', 'high'];

function severityGroup(severity: string): string {
  const normalized = severity.trim().toLowerCase();
  return severityOrder.includes(normalized) ? normalized : 'other';
}

export const GroupedFindings: React.FC<{
  findings: PersistedFinding[];
  counts?: FindingCounts;
  sourceLabel: string;
}> = ({ findings, counts, sourceLabel }) => {
  const byDetector = new Map<string, PersistedFinding[]>();
  for (const finding of findings) {
    const group = byDetector.get(finding.findingType) ?? [];
    group.push(finding);
    byDetector.set(finding.findingType, group);
  }

  const detectorTypes = Array.from(new Set([
    ...detectorOrder,
    ...Object.keys(counts?.detectorCounts ?? {}),
    ...byDetector.keys(),
  ]));

  return (
    <section aria-label={`${sourceLabel} grouped by detector`} className="space-y-3">
      <p className="text-[11px] text-slate-500">{sourceLabel}</p>
      {findings.length === 0 ? (
        <p className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600">
          No findings are present in this result set.
        </p>
      ) : (
        <div className="space-y-2">
          {detectorTypes.map((detector) => {
            const detectorFindings = byDetector.get(detector) ?? [];
            const totalForDetector = counts?.detectorCounts[detector] ?? detectorFindings.length;
            return (
              <details key={detector} open className="rounded-lg border border-slate-200 bg-white">
                <summary className="cursor-pointer list-none px-4 py-3 text-xs font-semibold text-slate-900">
                  <span>{getFindingTypeLabel(detector)}</span>
                  <span className="ml-2 text-slate-500">
                    {totalForDetector.toLocaleString()} matching
                    {totalForDetector !== detectorFindings.length
                      ? ` · ${detectorFindings.length} on this page`
                      : ''}
                  </span>
                </summary>
                {detectorFindings.length === 0 ? (
                  <p className="border-t border-slate-100 px-4 py-3 text-[11px] text-slate-500">
                    No findings from this detector are on the current page.
                  </p>
                ) : (
                  <div className="space-y-2 border-t border-slate-100 p-3">
                    {['low', 'medium', 'high', 'other'].map((severity) => {
                      const severityFindings = detectorFindings.filter(
                        (finding) => severityGroup(finding.severity) === severity
                      );
                      if (severityFindings.length === 0) return null;
                      const severityLabel = severity === 'other'
                        ? 'Other / unclassified severity'
                        : `${severity[0].toUpperCase()}${severity.slice(1)} severity`;
                      return (
                        <details key={severity} open className="rounded-md border border-slate-100">
                          <summary className="cursor-pointer px-3 py-2 text-[11px] font-medium text-slate-700">
                            {severityLabel} · {severityFindings.length.toLocaleString()} on this page
                          </summary>
                          <div className="divide-y divide-slate-100 border-t border-slate-100">
                            {severityFindings.map((finding) => (
                              <details key={finding.id} className="px-3 py-3">
                                <summary className="cursor-pointer flex flex-wrap items-center gap-2 text-xs">
                                  <span className="font-mono font-semibold text-teal-800">
                                    #{finding.id}
                                  </span>
                                  <SeverityBadge severity={finding.severity} size="sm" />
                                  <StatusBadge status={finding.status} size="sm" />
                                </summary>
                                <div className="mt-3 space-y-2 border-l-2 border-teal-100 pl-3">
                                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
                                    <dt className="text-slate-500">Detector</dt>
                                    <dd className="text-slate-800">{getFindingTypeLabel(finding.findingType)}</dd>
                                    <dt className="text-slate-500">Created</dt>
                                    <dd className="text-slate-800">
                                      {finding.createdAt
                                        ? new Date(finding.createdAt).toLocaleString()
                                        : 'Not provided by backend'}
                                    </dd>
                                  </dl>
                                  <p className="text-xs leading-relaxed text-slate-700">{finding.description}</p>
                                  <div>
                                    <h4 className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                                      Evidence
                                    </h4>
                                    {finding.evidence
                                      ? <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 text-[10px] text-slate-700">{JSON.stringify(finding.evidence, null, 2)}</pre>
                                      : <p className="mt-1 text-[10px] text-slate-500">No evidence object was returned.</p>}
                                  </div>
                                </div>
                              </details>
                            ))}
                          </div>
                        </details>
                      );
                    })}
                  </div>
                )}
              </details>
            );
          })}
        </div>
      )}
    </section>
  );
};
