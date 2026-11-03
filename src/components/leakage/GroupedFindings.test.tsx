import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { FindingCounts, PersistedFinding } from '../../types';
import { GroupedFindings } from './GroupedFindings';

const counts: FindingCounts = {
  total: 3,
  open: 2,
  resolved: 1,
  low: 1,
  medium: 1,
  high: 0,
  otherSeverity: 1,
  statusCounts: { open: 2, resolved: 1 },
  detectorCounts: { exact_duplicate: 2, future_detector: 1 },
};

const findings: PersistedFinding[] = [
  {
    id: 'duplicate-low',
    datasetId: 'dataset',
    findingType: 'exact_duplicate',
    severity: 'low',
    status: 'open',
    description: 'Repeated row group',
    evidence: { row_indices: [1, 3] },
    createdAt: '2026-01-01T00:00:00Z',
  },
  {
    id: 'duplicate-critical',
    datasetId: 'dataset',
    findingType: 'exact_duplicate',
    severity: 'critical',
    status: 'resolved',
    description: 'Critical duplicate record',
    evidence: null,
    createdAt: null,
  },
  {
    id: 'unknown',
    datasetId: 'dataset',
    findingType: 'future_detector',
    severity: 'informational',
    status: 'open',
    description: 'A future detector finding',
    evidence: {},
    createdAt: null,
  },
];

test('grouped findings show detector groups, severity expansion, evidence, and unknown values', () => {
  const markup = renderToStaticMarkup(
    React.createElement(GroupedFindings, {
      findings,
      counts,
      sourceLabel: 'Persisted records',
    })
  );
  assert.match(markup, /Exact duplicate/);
  assert.match(markup, /Low severity/);
  assert.match(markup, /Other \/ unclassified severity/);
  assert.match(markup, /future_detector/);
  assert.match(markup, /Repeated row group/);
  assert.match(markup, /row_indices/);
  assert.match(markup, /Critical duplicate record/);
  assert.match(markup, /open=""/);
});
