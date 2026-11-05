import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { Dataset, PersistedFinding } from '../types';
import {
  DetectorActionConfiguration,
  DetectorSection,
  getActionOptions,
  hydrateActionConfigurations,
  REMEDIATION_DETECTORS,
} from './RemediationCenterPage';

const finding: PersistedFinding = {
  id: 'finding-target-1',
  datasetId: 'dataset-1',
  findingType: 'target_leakage',
  severity: 'high',
  status: 'open',
  description: 'Persisted target association requires review.',
  evidence: {
    target_column: 'readmitted_30d',
    feature_column: 'readmission_flag_copy',
    matching_rows: 12,
  },
  createdAt: '2026-11-03T10:00:00Z',
};

test('Remediation Center action menu only exposes strategies supported for each detector', () => {
  assert.deepEqual(
    getActionOptions('exact_duplicate').map((item) => item.value),
    ['exact_duplicate_keep_first', 'quarantine_evidenced_rows', 'review_only'],
  );
  assert.deepEqual(
    getActionOptions('target_leakage').map((item) => item.value),
    ['exclude_target_features', 'review_only'],
  );
  assert.deepEqual(
    getActionOptions('temporal_leakage').map((item) => item.value),
    ['rebuild_chronological_split', 'review_only'],
  );
  assert.deepEqual(getActionOptions('future_detector'), []);
  assert.equal(
    REMEDIATION_DETECTORS.some((detector) => detector.actions.some((action) => /delete all/i.test(action.label))),
    false,
  );
});

test('confirmed analysis columns hydrate remediation selectors without selecting automatic actions', () => {
  const dataset = {
    id: 'sensor-dataset',
    name: 'sensor events',
    type: 'tabular',
    format: 'CSV',
    issuesCount: 0,
    uploadedAt: '2026-11-04T00:00:00Z',
    profile: {
      analysisColumns: {
        targetColumn: 'anomaly_label',
        entityColumn: 'sensor_id',
        timeColumn: 'event_time',
        splitColumn: 'dataset_split',
      },
      splitStrategy: {
        strategy: 'existing',
        testRatio: 0.25,
        randomSeed: 17,
      },
    },
    columns: [
      { name: 'anomaly_label', type: 'bool', missingCount: 0, uniqueCount: 2 },
      { name: 'sensor_id', type: 'string', missingCount: 0, uniqueCount: 2 },
      { name: 'event_time', type: 'datetime', missingCount: 0, uniqueCount: 2 },
      { name: 'dataset_split', type: 'string', missingCount: 0, uniqueCount: 2 },
    ],
  } as Dataset;
  const hydrated = hydrateActionConfigurations(dataset);
  assert.equal(hydrated.entity_overlap.config.entityColumn, 'sensor_id');
  assert.equal(hydrated.entity_overlap.config.targetColumn, 'anomaly_label');
  assert.equal(hydrated.temporal_leakage.config.timeColumn, 'event_time');
  assert.equal(hydrated.train_test_contamination.config.splitColumn, 'dataset_split');
  assert.equal(hydrated.entity_overlap.action, 'review_only');
  assert.equal(hydrated.exact_duplicate.action, 'exact_duplicate_keep_first');

  const manuallyChanged = hydrateActionConfigurations(dataset, {
    ...hydrated,
    entity_overlap: {
      action: 'rebuild_group_split',
      config: { entityColumn: 'machine_id', randomSeed: 19 },
    },
  });
  assert.equal(manuallyChanged.entity_overlap.config.entityColumn, 'machine_id');
  assert.equal(manuallyChanged.entity_overlap.config.targetColumn, 'anomaly_label');
  assert.equal(manuallyChanged.entity_overlap.action, 'rebuild_group_split');
});

test('target remediation requires explicit target and feature review while preserving target', () => {
  const detector = REMEDIATION_DETECTORS.find((item) => item.type === 'target_leakage')!;
  const markup = renderToStaticMarkup(React.createElement(DetectorActionConfiguration, {
    detector,
    dataset: null,
    selected: { findingIds: [finding.id], allEligible: false },
    columns: [
      { name: 'readmitted_30d', type: 'bool' },
      { name: 'readmission_flag_copy', type: 'bool' },
    ],
    selectedFindingCache: { [finding.id]: finding },
    actionConfiguration: {
      action: 'exclude_target_features',
      config: {
        targetColumn: 'readmitted_30d',
        featureColumns: ['readmission_flag_copy'],
      },
    },
    onConfigurationChange: () => {},
  }));
  assert.match(markup, /readmitted_30d/);
  assert.match(markup, /readmission_flag_copy/);
  assert.match(markup, /Confirmed feature columns to exclude/);
  assert.match(markup, /does not repair causal data collection/);
});

test('detector groups expose server-side pagination controls and evidence action without loading all findings', () => {
  const detector = REMEDIATION_DETECTORS[0];
  const markup = renderToStaticMarkup(React.createElement(DetectorSection, {
    datasetId: 'dataset-1',
    detector,
    selected: { findingIds: [], allEligible: false },
    selectedFindingCache: {},
    onSetSelection: () => {},
    onCacheFindings: () => {},
    onCounts: () => {},
    refreshKey: 0,
    dataset: null,
    actionConfiguration: undefined,
    onActionConfiguration: () => {},
    locked: false,
    latestOperationStatus: null,
  }));
  assert.match(markup, /Exact Duplicate Detection/);
  assert.match(markup, /Select all open across pages/);
  assert.match(markup, /Page 1 of 1/);
  assert.match(markup, /page size 10/);
  assert.match(markup, /No persisted findings match/);
});
