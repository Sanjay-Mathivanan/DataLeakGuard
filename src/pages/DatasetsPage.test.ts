import assert from 'node:assert/strict';
import { test } from 'node:test';

import { filterDatasets, getDatasetListState } from './DatasetsPage';
import { Dataset } from '../types';

const datasetWithoutDescription: Dataset = {
  id: 'dataset-1',
  name: 'Example dataset',
  type: 'tabular',
  format: 'CSV',
  uploadedAt: '2026-01-15T12:30:00Z',
  description: null,
  issuesCount: 0,
};

test('dataset search safely handles nullable backend descriptions', () => {
  assert.deepEqual(
    filterDatasets([datasetWithoutDescription], 'missing', 'all'),
    []
  );
  assert.deepEqual(
    filterDatasets([datasetWithoutDescription], 'example', 'all'),
    [datasetWithoutDescription]
  );
  assert.deepEqual(
    filterDatasets([datasetWithoutDescription], '', 'computer-vision'),
    []
  );
});

test('dataset list distinguishes an API error from a genuinely empty result', () => {
  assert.equal(getDatasetListState(true, null, 0), 'loading');
  assert.equal(getDatasetListState(false, 'request failed', 0), 'error');
  assert.equal(getDatasetListState(false, null, 0), 'empty');
  assert.equal(getDatasetListState(false, null, 2), 'ready');
});
