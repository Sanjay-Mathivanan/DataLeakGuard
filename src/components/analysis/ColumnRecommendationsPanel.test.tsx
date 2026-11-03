import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ColumnRecommendationsResponse } from '../../types';
import { ColumnRecommendationsPanel } from './ColumnRecommendationsPanel';
import {
  filterColumnOptions,
  SearchableColumnSelector,
} from './SearchableColumnSelector';

const profile = {
  dataType: 'object',
  kind: 'categorical',
  uniqueCount: 3,
  uniqueRatio: 0.3,
  missingCount: 1,
  missingRatio: 0.1,
  sampleCount: 10,
  recognizedSplitLabels: ['train', 'test'],
  datetimeParseableSampleCount: 0,
  previewRowsConsidered: 6,
};

const candidate = {
  columnName: 'risk_category',
  role: 'target' as const,
  score: 80,
  confidence: 'high' as const,
  explanation: 'Column name and categorical cardinality signals.',
  supportingSignals: ['Exact role token'],
  warnings: [],
  profile,
};

const recommendations: ColumnRecommendationsResponse = {
  profiledColumnCount: 120,
  sampleCount: 10,
  roles: {
    target: { recommendation: candidate, candidates: [candidate], warnings: [] },
    entity: { recommendation: null, candidates: [], warnings: ['No reliable recommendation.'] },
    split: { recommendation: null, candidates: [], warnings: ['Split-dependent detectors need a verified split.'] },
    timestamp: { recommendation: null, candidates: [], warnings: [] },
  },
  limitations: ['Heuristic points are not probabilities.'],
};

test('recommendation panel labels advisory scores and offers explicit selection', () => {
  const markup = renderToStaticMarkup(React.createElement(ColumnRecommendationsPanel, {
    recommendations,
    selected: { target: '', entity: '', split: '', timestamp: '' },
    onSelect: () => {},
  }));
  assert.match(markup, /not probabilities/);
  assert.match(markup, /Use recommendation/);
  assert.match(markup, /No reliable recommendation/);
  assert.match(markup, /risk_category/);
  assert.match(markup, /Recognized split labels/);
});

test('searchable selector matches large schemas by name/type and shows an accessible trigger', () => {
  const columns = Array.from({ length: 1200 }, (_, index) => ({
    name: `feature_${index}`,
    type: index % 2 ? 'object' : 'float64',
  }));
  columns.push({ name: 'patient_id', type: 'object' });
  assert.deepEqual(
    filterColumnOptions(columns, 'PATIENT', 'categorical').map((column) => column.name),
    ['patient_id']
  );
  assert.equal(filterColumnOptions(columns, '', 'numeric').length, 600);
  const markup = renderToStaticMarkup(React.createElement(SearchableColumnSelector, {
    label: 'Target column',
    value: 'patient_id',
    columns,
    onChange: () => {},
  }));
  assert.match(markup, /aria-haspopup="dialog"/);
  assert.match(markup, /patient_id/);
});
