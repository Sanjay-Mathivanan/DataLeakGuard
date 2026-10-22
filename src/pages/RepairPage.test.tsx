import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { DatasetOperationRecord, PersistedFinding } from '../types';
import { getSupportedFindingOperations, RepairPageView } from './RepairPage';

const finding: PersistedFinding = {
  id: 'finding-17',
  datasetId: 'dataset-4',
  findingType: 'exact_duplicate',
  severity: 'high',
  status: 'open',
  description: 'Two rows are exact duplicates.',
  evidence: { duplicate_count: 2, row_indices: [2, 7] },
  createdAt: '2026-01-15T12:30:00Z',
};

const operation: DatasetOperationRecord = {
  id: 'operation-21',
  datasetId: 'dataset-4',
  findingId: finding.id,
  operationType: 'repair',
  status: 'completed',
  outputFilename: 'processed.csv',
  affectedRows: 1,
  createdAt: '2026-01-15T13:00:00Z',
};

function renderView(
  overrides: Partial<React.ComponentProps<typeof RepairPageView>> = {}
): string {
  const props: React.ComponentProps<typeof RepairPageView> = {
    datasetId: 'dataset-4',
    findings: [finding],
    history: [],
    loading: false,
    loadError: null,
    operationError: null,
    activeOperationKey: null,
    onRunOperation: () => {},
    onRetry: () => {},
    ...overrides,
  };
  return renderToStaticMarkup(React.createElement(RepairPageView, props));
}

test('operation eligibility is restricted to supported types with matching identifiers', () => {
  assert.deepEqual(getSupportedFindingOperations(finding, 'dataset-4'), ['repair', 'quarantine']);
  assert.deepEqual(
    getSupportedFindingOperations({
      ...finding,
      findingType: 'entity_overlap',
      evidence: { row_indices: { train: [1], test: [4] } },
    }, 'dataset-4'),
    ['quarantine']
  );
  assert.deepEqual(
    getSupportedFindingOperations(
      {
        ...finding,
        findingType: 'train_test_contamination',
        evidence: { row_indices: { train: [1], test: [4] } },
      },
      'dataset-4'
    ),
    ['quarantine']
  );
  assert.deepEqual(
    getSupportedFindingOperations({ ...finding, findingType: 'target_leakage' }, 'dataset-4'),
    []
  );
  assert.deepEqual(getSupportedFindingOperations(finding, 'another-dataset'), []);
  assert.deepEqual(getSupportedFindingOperations({ ...finding, id: '' }, 'dataset-4'), []);
  assert.deepEqual(
    getSupportedFindingOperations({ ...finding, evidence: { row_indices: [2, 7] } }, 'dataset-4'),
    ['quarantine']
  );
  assert.deepEqual(
    getSupportedFindingOperations({ ...finding, evidence: null }, 'dataset-4'),
    []
  );
});

test('loading, fetch-error, and empty states are explicit and do not imply detector coverage', () => {
  assert.match(renderView({ loading: true }), /Loading persisted findings and operation history/);
  assert.match(renderView({ loading: false, loadError: 'Backend unavailable' }), /Backend unavailable/);
  assert.match(
    renderView({ operationError: 'Failed to quarantine finding: 500' }),
    /Failed to quarantine finding: 500/
  );
  assert.match(
    renderView({ findings: [] }),
    /An empty list does not establish that every detector ran successfully/
  );
});

test('unsupported findings do not expose repair or quarantine controls', () => {
  const html = renderView({
    findings: [{ ...finding, findingType: 'unknown_detector' }],
  });

  assert.match(html, /Unknown finding type \(unknown_detector\)/);
  assert.match(html, /No automated operation is available/);
  assert.doesNotMatch(html, /Create duplicate-repaired copy/);
  assert.doesNotMatch(html, /Create quarantine output/);
});

test('a missing dataset identifier does not render operation controls', () => {
  const html = renderView({ datasetId: null });
  assert.match(html, /No dataset identifier is available/);
  assert.doesNotMatch(html, /Create duplicate-repaired copy/);
  assert.doesNotMatch(html, /Create quarantine output/);
});

test('completed and in-flight operations disable controls against accidental resubmission', () => {
  const completedHtml = renderView({ history: [operation] });
  assert.match(completedHtml, /Create duplicate-repaired copy \(completed\)/);
  assert.match(completedHtml, /disabled=""/);
  assert.match(completedHtml, /Create quarantine output/);

  const activeHtml = renderView({ activeOperationKey: 'repair:finding-17' });
  assert.match(activeHtml, /Operation in progress/);
  assert.match(activeHtml, /disabled=""/);

  const pendingHtml = renderView({
    history: [{ ...operation, status: 'processing' }],
  });
  assert.match(pendingHtml, /Create duplicate-repaired copy \(processing\)/);
  assert.match(pendingHtml, /disabled=""/);
});

test('operation history distinguishes quarantine files from processed repair copies', () => {
  const quarantine: DatasetOperationRecord = {
    ...operation,
    id: 'operation-22',
    operationType: 'quarantine',
    outputFilename: 'affected-rows.csv',
    affectedRows: 4,
    outputFileSha256: 'quarantine-hash',
  };
  const html = renderView({ history: [operation, quarantine] });

  assert.match(html, /Exact-duplicate processed copy/);
  assert.match(html, /Later duplicate rows removed from processed copy/);
  assert.match(html, /Quarantine output/);
  assert.match(html, /Rows written to separate quarantine output/);
  assert.match(html, /processed\.csv/);
  assert.match(html, /affected-rows\.csv/);
  assert.match(html, /quarantine-hash/);
  assert.match(html, /uploaded original dataset is not modified/);
  assert.match(html, /Downloads are not available yet/);
  assert.doesNotMatch(html, /<a\\b/);
});

test('unknown operation metadata and absent row counts render without fabricated zeroes', () => {
  const unknownOperation: DatasetOperationRecord = {
    id: 'operation-unknown',
    datasetId: 'dataset-4',
    operationType: 'future_operation',
    status: 'pending',
  };
  const html = renderView({ findings: [], history: [unknownOperation] });

  assert.match(html, /Operation \(future_operation\)/);
  assert.doesNotMatch(html, /0 rows/);
  assert.doesNotMatch(html, /Rows written to separate quarantine output/);
  assert.match(html, /Affected-row count was not available/);
});
