import assert from 'node:assert/strict';
import { test } from 'node:test';

import { getDatasetWorkflowPath } from './datasetNavigation';

test('dataset workflow navigation uses the dataset picker instead of demo IDs', () => {
  assert.equal(getDatasetWorkflowPath('findings'), '/datasets');
  assert.equal(getDatasetWorkflowPath('repair', null), '/datasets');
  assert.equal(getDatasetWorkflowPath('repair', '  '), '/datasets');
});

test('dataset workflow navigation encodes a supplied backend dataset ID', () => {
  assert.equal(getDatasetWorkflowPath('dataset', 'dataset/4'), '/datasets/dataset%2F4');
  assert.equal(getDatasetWorkflowPath('findings', 'dataset-4'), '/leakage-analysis/dataset-4');
  assert.equal(getDatasetWorkflowPath('repair', 'dataset-4'), '/repair/dataset-4');
});
