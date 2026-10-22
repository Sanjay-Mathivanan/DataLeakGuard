import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { FindingEvidencePanel } from './FindingEvidencePanel';
import { PersistedFinding } from '../../types';

const persistedFinding: PersistedFinding = {
  id: 'finding-17',
  datasetId: 'dataset-4',
  findingType: 'entity_overlap',
  severity: 'high',
  status: 'open',
  description: 'One entity appears in more than one split.',
  evidence: { entity_value: 'subject-2', row_indices: { train: [0], test: [4] } },
  createdAt: '2026-01-15T12:30:00Z',
};

test('evidence panel renders persisted fields and supplied detector evidence only', () => {
  const markup = renderToStaticMarkup(
    <FindingEvidencePanel finding={persistedFinding} />
  );

  assert.match(markup, /Finding #finding-17/);
  assert.match(markup, /dataset-4/);
  assert.match(markup, /Entity overlap/);
  assert.match(markup, /One entity appears in more than one split/);
  assert.match(markup, /&quot;entity_value&quot;: &quot;subject-2&quot;/);
  assert.match(markup, /High/);
  assert.doesNotMatch(markup, /similarity|confidence|train record|test record|feature values/i);
});

test('evidence panel safely labels unknown types and absent optional evidence fields', () => {
  const unknownFinding: PersistedFinding = {
    ...persistedFinding,
    findingType: 'future_detector',
    severity: 'unrated',
    createdAt: null,
    evidence: null,
  };
  const markup = renderToStaticMarkup(
    <FindingEvidencePanel finding={unknownFinding} />
  );

  assert.match(markup, /Unknown finding type \(future_detector\)/);
  assert.match(markup, /unrated/);
  assert.match(markup, /Not provided by backend/);
  assert.match(markup, /No evidence object was returned by the backend/);
});
