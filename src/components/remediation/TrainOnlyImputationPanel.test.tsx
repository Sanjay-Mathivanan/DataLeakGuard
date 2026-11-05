import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { Dataset } from '../../types';
import {
  availableImputationMethods,
  TrainOnlyImputationPanel,
} from './TrainOnlyImputationPanel';

test('imputation options are appropriate for numeric and categorical types', () => {
  assert.deepEqual(
    availableImputationMethods('float64'),
    ['mean', 'median', 'mode', 'constant', 'leave_missing'],
  );
  assert.deepEqual(
    availableImputationMethods('object'),
    ['mode', 'constant', 'leave_missing'],
  );
});

test('panel explains no-split limitations without offering fake preprocessing execution', () => {
  const dataset = {
    id: 'dataset-no-split',
    name: 'generic input',
    type: 'tabular',
    format: 'CSV',
    issuesCount: 0,
    uploadedAt: '2026-11-04T00:00:00Z',
    sampleCount: 100,
    columns: [
      { name: 'feature', type: 'float64', missingCount: 3, uniqueCount: 40 },
      { name: 'target', type: 'object', missingCount: 2, uniqueCount: 2 },
    ],
    profile: {
      analysisColumns: { targetColumn: 'target' },
      splitStrategy: { strategy: 'none' },
    },
  } as Dataset;
  const markup = renderToStaticMarkup(React.createElement(TrainOnlyImputationPanel, { dataset }));
  assert.match(markup, /validated existing split or completed generated split is required/i);
  assert.match(markup, /uploaded original is unchanged/i);
  assert.doesNotMatch(markup, /Confirm and create copy/);
});

test('panel displays missing-value percentages and protects confirmed target columns', () => {
  const dataset = {
    id: 'dataset-with-split',
    name: 'generic input',
    type: 'tabular',
    format: 'CSV',
    issuesCount: 0,
    uploadedAt: '2026-11-04T00:00:00Z',
    sampleCount: 100,
    columns: [
      { name: 'feature', type: 'float64', missingCount: 5, uniqueCount: 40 },
      { name: 'target', type: 'object', missingCount: 2, uniqueCount: 2 },
      { name: 'partition', type: 'object', missingCount: 0, uniqueCount: 2 },
      { name: 'comparison key', type: 'object', missingCount: 1, uniqueCount: 40 },
    ],
    profile: {
      analysisColumns: {
        targetColumn: 'target',
        splitColumn: 'partition',
        contaminationKeyColumns: ['comparison key'],
      },
      splitStrategy: { strategy: 'existing' },
    },
  } as Dataset;
  const markup = renderToStaticMarkup(React.createElement(TrainOnlyImputationPanel, { dataset }));
  assert.match(markup, /feature/);
  assert.match(markup, /5 \(5\.00%\)/);
  assert.match(markup, /target/);
  assert.match(markup, /comparison key/);
  assert.match(markup, /configured comparison-key/);
  assert.doesNotMatch(markup, /Imputation strategy for comparison key/);
  assert.match(markup, /Protected analysis column/);
  assert.match(markup, /Imputation strategy for feature/);
});
