import React from 'react';
import { SplitGenerationOperation } from '../../types';

export type SplitStrategy = 'existing' | 'generated' | 'none';

interface SplitStrategyPanelProps {
  strategy: SplitStrategy;
  onStrategyChange: (strategy: SplitStrategy) => void;
  testRatio: number;
  randomSeed: number;
  onTestRatioChange: (value: number) => void;
  onRandomSeedChange: (value: number) => void;
  generationConfirmed: boolean;
  onGenerationConfirmedChange: (confirmed: boolean) => void;
  isGenerating: boolean;
  generationError: string | null;
  operation: SplitGenerationOperation | null;
  onGenerate: () => void;
}

const strategyOptions: Array<{
  id: SplitStrategy;
  title: string;
  description: string;
}> = [
  {
    id: 'existing',
    title: 'Use an existing split',
    description: 'You choose and confirm a split column; the backend validates every row before analysis.',
  },
  {
    id: 'generated',
    title: 'Generate a separate split copy',
    description: 'Create a deterministic row-level train/test copy without changing the uploaded original.',
  },
  {
    id: 'none',
    title: 'Analyze without a split',
    description: 'Split-dependent checks are skipped and reported as not evaluated.',
  },
];

export const SplitStrategyPanel: React.FC<SplitStrategyPanelProps> = ({
  strategy,
  onStrategyChange,
  testRatio,
  randomSeed,
  onTestRatioChange,
  onRandomSeedChange,
  generationConfirmed,
  onGenerationConfirmedChange,
  isGenerating,
  generationError,
  operation,
  onGenerate,
}) => (
  <section className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
    <h3 className="text-sm font-semibold text-slate-900">Train/test split strategy</h3>
    <p className="mt-1 text-xs text-slate-600">
      Select how split-dependent detectors should interpret this dataset. No split is inferred or generated automatically.
    </p>

    <fieldset className="mt-3 grid grid-cols-1 gap-2 lg:grid-cols-3">
      <legend className="sr-only">Split strategy</legend>
      {strategyOptions.map((option) => (
        <label
          key={option.id}
          className={`flex cursor-pointer items-start gap-2 rounded-lg border p-3 ${
            strategy === option.id
              ? 'border-teal-500 bg-white ring-1 ring-teal-200'
              : 'border-slate-200 bg-white'
          }`}
        >
          <input
            type="radio"
            name="split-strategy"
            value={option.id}
            checked={strategy === option.id}
            onChange={() => onStrategyChange(option.id)}
            disabled={isGenerating}
            className="mt-0.5"
          />
          <span>
            <span className="block text-xs font-semibold text-slate-900">{option.title}</span>
            <span className="mt-1 block text-[11px] leading-4 text-slate-600">{option.description}</span>
          </span>
        </label>
      ))}
    </fieldset>

    {strategy === 'existing' && (
      <p className="mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs text-blue-900">
        Choose the split column below. Analysis will reject missing/blank memberships or fewer than two groups;
        nonstandard labels are disclosed and interpreted only after your explicit selection.
      </p>
    )}

    {strategy === 'none' && (
      <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900" role="status">
        Entity overlap, temporal leakage and train/test contamination cannot be evaluated without split membership.
        They will be marked “Skipped — not evaluated,” not “clear.”
      </p>
    )}

    {strategy === 'generated' && (
      <div className="mt-3 space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-xs font-medium text-slate-700">
            Test proportion
            <input
              type="number"
              min={0.05}
              max={0.95}
              step={0.05}
              value={testRatio}
              disabled={isGenerating}
              onChange={(event) => onTestRatioChange(Number(event.target.value))}
              className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2"
              aria-label="Test proportion"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            Random seed
            <input
              type="number"
              min={-2147483648}
              max={2147483647}
              step={1}
              value={randomSeed}
              disabled={isGenerating}
              onChange={(event) => onRandomSeedChange(Number(event.target.value))}
              className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2"
              aria-label="Random seed"
            />
          </label>
        </div>
        <p className="text-[11px] leading-4 text-amber-900">
          This is a reproducible row-level split. It is not stratified or group-aware; rows for the same
          person/entity may be assigned to different partitions. Review the seed and ratio before generating.
        </p>
        <label className="flex items-start gap-2 rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-700">
          <input
            type="checkbox"
            checked={generationConfirmed}
            onChange={(event) => onGenerationConfirmedChange(event.target.checked)}
            disabled={isGenerating}
            className="mt-0.5"
          />
          <span>
            I confirm creation of a new split copy with the displayed ratio and seed. The original upload must remain unchanged.
          </span>
        </label>
        <button
          type="button"
          onClick={onGenerate}
          disabled={!generationConfirmed || isGenerating || testRatio < 0.05 || testRatio > 0.95 || !Number.isInteger(randomSeed)}
          className="rounded-lg bg-slate-800 px-4 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isGenerating ? 'Generating split copy…' : operation ? 'Generate another split copy' : 'Generate split copy'}
        </button>
        {generationError && (
          <p className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800" role="alert">
            {generationError}
          </p>
        )}
        {operation && (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900" role="status">
            <p className="font-semibold">Verified generated split is ready for analysis.</p>
            <p className="mt-1">
              Operation {operation.id}; {operation.rowCount} rows; {operation.splitRowCounts.train ?? 0} train /
              {' '}{operation.splitRowCounts.test ?? 0} test; seed {operation.randomSeed}; {operation.reused ? 'reused verified output' : 'new output'}.
            </p>
            <p className="mt-1 break-all">Output SHA-256: {operation.outputFileSha256}</p>
          </div>
        )}
      </div>
    )}
  </section>
);
