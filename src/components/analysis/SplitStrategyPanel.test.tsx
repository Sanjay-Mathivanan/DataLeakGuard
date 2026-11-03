import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { SplitGenerationOperation } from '../../types';
import { SplitStrategyPanel, SplitStrategy } from './SplitStrategyPanel';

const completedOperation: SplitGenerationOperation = {
  id: 'split-operation-1',
  datasetId: 'dataset-1',
  operationType: 'split_generation',
  status: 'completed',
  splitColumn: '__dataleakguard_split__',
  testRatio: 0.25,
  randomSeed: 17,
  algorithm: 'sha256_seeded_row_order_v1',
  rowCount: 8,
  splitRowCounts: { train: 6, test: 2 },
  inputFileSha256: 'source-digest',
  outputFileSha256: 'output-digest',
  outputFilename: 'generated.csv',
  createdAt: null,
  completedAt: null,
  reused: false,
};

function renderPanel(
  strategy: SplitStrategy,
  overrides: Partial<React.ComponentProps<typeof SplitStrategyPanel>> = {}
): string {
  return renderToStaticMarkup(
    React.createElement(SplitStrategyPanel, {
      strategy,
      onStrategyChange: () => {},
      testRatio: 0.25,
      randomSeed: 17,
      onTestRatioChange: () => {},
      onRandomSeedChange: () => {},
      generationConfirmed: false,
      onGenerationConfirmedChange: () => {},
      isGenerating: false,
      generationError: null,
      operation: null,
      onGenerate: () => {},
      ...overrides,
    })
  );
}

test('split configuration presents explicit existing, generated and no-split choices', () => {
  const html = renderPanel('existing');
  assert.match(html, /Use an existing split/);
  assert.match(html, /Generate a separate split copy/);
  assert.match(html, /Analyze without a split/);
  assert.match(html, /checked=""/);
  assert.match(html, /Choose the split column below/);
});

test('no-split mode clearly says split-dependent checks are skipped, not clear', () => {
  const html = renderPanel('none');
  assert.match(html, /Skipped — not evaluated/);
  assert.match(html, /not “clear\./);
});

test('generated split requires explicit confirmation and exposes algorithm limitations', () => {
  const unconfirmed = renderPanel('generated');
  assert.match(unconfirmed, /disabled=""/);
  assert.match(unconfirmed, /not stratified or group-aware/);
  assert.match(unconfirmed, /I confirm creation of a new split copy/);

  const confirmed = renderPanel('generated', { generationConfirmed: true });
  assert.doesNotMatch(confirmed, /disabled=""/);
});

test('verified generated split summary shows persisted counts, seed and digest', () => {
  const html = renderPanel('generated', {
    operation: completedOperation,
    generationConfirmed: true,
  });
  assert.match(html, /Verified generated split is ready for analysis/);
  assert.match(html, /8 rows; 6 train \/ 2 test; seed 17/);
  assert.match(html, /output-digest/);
});

test('generation errors are distinct and exposed accessibly', () => {
  const html = renderPanel('generated', {
    generationError: 'Split generation failed (422)',
  });
  assert.match(html, /role="alert"/);
  assert.match(html, /Split generation failed \(422\)/);
});
