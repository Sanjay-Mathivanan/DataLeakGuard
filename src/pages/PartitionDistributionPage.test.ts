import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  buildPartitionCategoryChartData,
  getPartitionDistributionContentState,
} from './PartitionDistributionPage';

test('partition comparison UI distinguishes loading, missing configuration, empty, and ready states', () => {
  const base = {
    loading: false,
    datasetSelected: true,
    datasetAvailable: true,
    configuredSplit: true,
    analysisAvailable: true,
  };

  assert.equal(
    getPartitionDistributionContentState({ ...base, loading: true }),
    'loading'
  );
  assert.equal(
    getPartitionDistributionContentState({ ...base, datasetSelected: false }),
    'select_dataset'
  );
  assert.equal(
    getPartitionDistributionContentState({ ...base, datasetAvailable: false }),
    'dataset_unavailable'
  );
  assert.equal(
    getPartitionDistributionContentState({ ...base, configuredSplit: false }),
    'requires_configuration'
  );
  assert.equal(
    getPartitionDistributionContentState({ ...base, analysisAvailable: false }),
    'empty'
  );
  assert.equal(getPartitionDistributionContentState(base), 'ready');
});

test('target/category charts use actual backend proportions and arbitrary partition labels', () => {
  assert.deepEqual(
    buildPartitionCategoryChartData(
      [
        {
          category: 'review',
          reference_percentage: 25,
          comparison_percentage: 75,
        },
        {
          category: 'stable',
          reference_percentage: 75,
          comparison_percentage: 25,
        },
      ],
      'development cohort',
      'future holdout'
    ),
    [
      {
        category: 'review',
        'development cohort': 25,
        'future holdout': 75,
      },
      {
        category: 'stable',
        'development cohort': 75,
        'future holdout': 25,
      },
    ]
  );
  assert.equal(
    buildPartitionCategoryChartData({ malformed: true }, 'left', 'right').length,
    0
  );
});
