import React from 'react';
import {
  ColumnRecommendationsResponse,
  DetectorColumnRole,
} from '../../types';

const roleLabels: Record<DetectorColumnRole, string> = {
  target: 'Target / label',
  entity: 'Entity / identifier',
  split: 'Train/test split',
  timestamp: 'Timestamp / time',
};

export const ColumnRecommendationsPanel: React.FC<{
  recommendations: ColumnRecommendationsResponse;
  selected: Record<DetectorColumnRole, string>;
  onSelect: (role: DetectorColumnRole, column: string) => void;
}> = ({ recommendations, selected, onSelect }) => (
  <section aria-label="Automatic column recommendations" className="space-y-3">
    <div>
      <h3 className="text-sm font-semibold text-slate-900">Automatic recommendations</h3>
      <p className="mt-1 text-[11px] text-slate-500">
        Suggestions use persisted profile metadata and bounded previews. Scores are heuristic ranking points, not probabilities. Nothing is selected or run automatically.
      </p>
    </div>
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      {(Object.keys(roleLabels) as DetectorColumnRole[]).map((role) => {
        const roleResult = recommendations.roles[role];
        const candidate = roleResult.recommendation;
        const alternatives = roleResult.candidates.filter(
          (item) => item.columnName !== candidate?.columnName
        );
        return (
          <article key={role} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
            <h4 className="text-xs font-semibold text-slate-900">{roleLabels[role]}</h4>
            {candidate ? (
              <>
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                  <span className="break-all font-mono text-sm font-semibold text-teal-800">
                    {candidate.columnName}
                  </span>
                  <span className="rounded-full border border-teal-200 bg-white px-2 py-1 text-[10px] font-semibold uppercase text-teal-800">
                    {candidate.confidence} · {candidate.score} heuristic points
                  </span>
                </div>
                <p className="mt-2 text-[11px] leading-relaxed text-slate-700">{candidate.explanation}</p>
                <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
                  <dt className="text-slate-500">Profile type</dt><dd className="text-slate-800">{candidate.profile.dataType}</dd>
                  <dt className="text-slate-500">Unique values</dt><dd className="text-slate-800">{candidate.profile.uniqueCount?.toLocaleString() ?? 'Unavailable'}</dd>
                  <dt className="text-slate-500">Missing values</dt><dd className="text-slate-800">{candidate.profile.missingCount?.toLocaleString() ?? 'Unavailable'}</dd>
                  {candidate.profile.uniqueRatio !== null && <><dt className="text-slate-500">Unique ratio</dt><dd className="text-slate-800">{(candidate.profile.uniqueRatio * 100).toFixed(1)}%</dd></>}
                  {candidate.profile.missingRatio !== null && <><dt className="text-slate-500">Missing ratio</dt><dd className="text-slate-800">{(candidate.profile.missingRatio * 100).toFixed(1)}%</dd></>}
                  {candidate.profile.recognizedSplitLabels.length > 0 && <><dt className="text-slate-500">Recognized split labels</dt><dd className="text-slate-800">{candidate.profile.recognizedSplitLabels.join(', ')}</dd></>}
                  {role === 'timestamp' && <><dt className="text-slate-500">Preview values parsed</dt><dd className="text-slate-800">{candidate.profile.datetimeParseableSampleCount} of up to {candidate.profile.previewRowsConsidered}</dd></>}
                </dl>
                <button
                  type="button"
                  onClick={() => onSelect(role, candidate.columnName)}
                  disabled={selected[role] === candidate.columnName}
                  className="mt-3 rounded-md bg-teal-700 px-3 py-1.5 text-[11px] font-semibold text-white disabled:bg-slate-300"
                >
                  {selected[role] === candidate.columnName ? 'Selected for review' : 'Use recommendation'}
                </button>
                {candidate.warnings.map((warning) => (
                  <p key={warning} className="mt-2 text-[10px] text-amber-800">Warning: {warning}</p>
                ))}
              </>
            ) : (
              <p className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-[11px] text-amber-900">
                No reliable recommendation. Choose a column manually and verify it before analysis.
              </p>
            )}
            {alternatives.length > 0 && (
              <div className="mt-3 border-t border-slate-200 pt-2">
                <h5 className="text-[10px] font-semibold text-slate-600">Alternative candidates</h5>
                <ul className="mt-1 space-y-1">
                  {alternatives.map((alternative) => (
                    <li key={alternative.columnName} className="rounded border border-slate-200 bg-white p-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="break-all text-[10px] text-slate-700">
                          <span className="font-mono">{alternative.columnName}</span>
                          <span className="ml-1 text-slate-500">· {alternative.confidence}, {alternative.score} points</span>
                        </span>
                        <button
                          type="button"
                          onClick={() => onSelect(role, alternative.columnName)}
                          className="rounded border border-slate-300 bg-white px-2 py-1 text-[10px] text-slate-700 hover:bg-slate-100"
                        >
                          Select candidate
                        </button>
                      </div>
                      <details className="mt-1">
                        <summary className="cursor-pointer text-[10px] text-teal-800">Inspect candidate profile</summary>
                        <p className="mt-1 text-[10px] text-slate-600">
                          Type: {alternative.profile.dataType} · unique values: {alternative.profile.uniqueCount?.toLocaleString() ?? 'Unavailable'} · missing: {alternative.profile.missingCount?.toLocaleString() ?? 'Unavailable'}
                          {alternative.profile.recognizedSplitLabels.length > 0
                            ? ` · recognized split labels: ${alternative.profile.recognizedSplitLabels.join(', ')}`
                            : ''}
                        </p>
                      </details>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {roleResult.warnings.map((warning) => (
              <p key={warning} className="mt-2 text-[10px] text-amber-800">{warning}</p>
            ))}
          </article>
        );
      })}
    </div>
    <p className="text-[10px] text-slate-500">
      Profiled columns: {recommendations.profiledColumnCount.toLocaleString()} · sample rows: {recommendations.sampleCount?.toLocaleString() ?? 'Unavailable'}
    </p>
  </section>
);
