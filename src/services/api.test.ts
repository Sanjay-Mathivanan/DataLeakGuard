import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  buildAnalysisStages,
  deleteDataset,
  downloadOperationOutput,
  generateDatasetSplit,
  generateCombinedCleanedDataset,
  previewCombinedCleanedDataset,
  getCategoryOverviews,
  getDatasetById,
  getDatasetHistoryPage,
  getColumnRecommendations,
  getDatasetOperationHistory,
  getRemediationPlans,
  previewRemediationPlan,
  executeRemediationPlan,
  cancelRemediationPlan,
  downloadRemediationArtifact,
  getDatasets,
  getFindingById,
  getFindings,
  getFindingsPage,
  getDistributionShift,
  getReports,
  generateAssuranceReport,
  getSupportedUploadDetails,
  mapDatasetOperationRecord,
  mapPersistedFinding,
  quarantineFinding,
  runDatasetAnalysis,
  repairFinding,
  summarizeFindings,
  uploadDataset,
} from './api';
import { PersistedFinding } from '../types';

const remediationPlanResponse = {
  id: 'plan-1',
  dataset_id: 'dataset-4',
  operation_type: 'remediation_plan',
  status: 'previewed',
  created_at: '2026-11-03T10:00:00Z',
  completed_at: null,
  original_file_sha256: 'a'.repeat(64),
  output_file_sha256: null,
  output_filename: null,
  plan: {
    plan_id: 'plan-1',
    version: 1,
    execution_status: 'previewed',
    user_confirmation: false,
    preview_digest: 'b'.repeat(64),
    preview_token: 'c'.repeat(64),
    original_file_sha256: 'a'.repeat(64),
    original_row_count: 3,
    expected_final_row_count: 2,
    original_column_count: 2,
    expected_final_column_count: 2,
    affected_source_row_positions_preview: [2],
    affected_source_row_positions_count: 1,
    affected_source_row_positions_truncated: false,
    affected_source_row_positions_sha256: 'd'.repeat(64),
    excluded_feature_columns: [],
    split_update_count: 0,
    unresolved_findings_count: 0,
    selected_count: 1,
    selected_finding_ids_preview: ['finding-17'],
    selected_finding_ids_truncated: false,
    detector_types: ['exact_duplicate'],
    applied_count: 1,
    skipped_findings: [],
    skipped_findings_truncated: false,
    split_configurations: [],
    actions: [{
      action: 'exact_duplicate_keep_first',
      selection_mode: 'explicit',
      finding_type: 'exact_duplicate',
      selected_count: 1,
      applied_count: 1,
      configuration: {},
    }],
  },
};

test('analysis stages reflect only requested detectors and do not invent counts', () => {
  const stages = buildAnalysisStages({ exact_duplicate: 1, entity_overlap: 4 }, {}, 'completed');
  assert.equal(buildAnalysisStages({ exact_duplicate: 5 })[1].status, 'not_run');

  assert.deepEqual(
    stages.filter((stage) => stage.status === 'completed').map((stage) => stage.id),
    [2]
  );
  assert.equal(stages[1].findingsCount, 1);
  assert.equal(stages[2].status, 'not_run');
  assert.equal(stages[2].findingsCount, undefined);
  assert.equal(stages[3].status, 'not_run');
  assert.equal(stages[0].status, 'skipped');
});

test('paginated findings API sends server filters and maps dataset and matching summaries', async () => {
  await withMockFetch(async (input) => {
    const url = new URL(String(input), 'http://localhost');
    assert.match(url.pathname, /\/datasets\/dataset-4\/findings\/page$/);
    assert.equal(url.searchParams.get('skip'), '25');
    assert.equal(url.searchParams.get('limit'), '25');
    assert.equal(url.searchParams.get('search'), 'patient');
    assert.equal(url.searchParams.get('finding_type'), 'entity_overlap');
    assert.equal(url.searchParams.get('severity'), 'high');
    assert.equal(url.searchParams.get('status'), 'open');
    const counts = {
      total: 30,
      open: 20,
      resolved: 10,
      low: 5,
      medium: 10,
      high: 12,
      other_severity: 3,
      status_counts: { open: 20, resolved: 10 },
      detector_counts: { entity_overlap: 30 },
    };
    return new Response(JSON.stringify({
      items: [backendFinding],
      total: 30,
      skip: 25,
      limit: 25,
      dataset_summary: counts,
      matching_summary: { ...counts, total: 1, detector_counts: { entity_overlap: 1 } },
    }), { status: 200 });
  }, async () => {
    const result = await getFindingsPage('dataset-4', {
      skip: 25,
      limit: 25,
      search: ' patient ',
      findingType: 'entity_overlap',
      severity: 'high',
      status: 'open',
    });
    assert.equal(result.items[0].id, 'finding-17');
    assert.equal(result.datasetSummary.otherSeverity, 3);
    assert.equal(result.matchingSummary.detectorCounts.entity_overlap, 1);
    assert.equal(result.total, 30);
  });
});

test('remediation preview sends typed actions and maps persisted preview provenance', async () => {
  await withMockFetch(async (input, init) => {
    assert.equal(String(input), '/api/v1/datasets/dataset-4/remediation-plans/preview');
    assert.equal(init?.method, 'POST');
    assert.deepEqual(JSON.parse(String(init?.body)), {
      actions: [{
        action: 'exact_duplicate_keep_first',
        selection_mode: 'explicit',
        finding_ids: ['finding-17'],
      }],
    });
    return new Response(JSON.stringify(remediationPlanResponse), { status: 201 });
  }, async () => {
    const result = await previewRemediationPlan('dataset-4', [{
      action: 'exact_duplicate_keep_first',
      selection_mode: 'explicit',
      finding_ids: ['finding-17'],
    }]);
    assert.equal(result.status, 'previewed');
    assert.equal(result.plan.previewToken, 'c'.repeat(64));
    assert.deepEqual(result.plan.affectedSourceRowPositionsPreview, [2]);
  });
});

test('remediation execution requires confirmation and downloads only typed server artifacts', async () => {
  await assert.rejects(
    executeRemediationPlan('dataset-4', 'plan-1', 'c'.repeat(64), false),
    /explicit confirmation/
  );
  await withMockFetch(async (input, init) => {
    assert.equal(String(input), '/api/v1/datasets/dataset-4/remediation-plans/plan-1/execute');
    assert.equal(init?.method, 'POST');
    assert.deepEqual(JSON.parse(String(init?.body)), {
      preview_token: 'c'.repeat(64),
      confirmed: true,
    });
    return new Response(JSON.stringify({
      ...remediationPlanResponse,
      operation_type: 'consolidated_remediation',
      status: 'completed',
    }), { status: 201 });
  }, async () => {
    const result = await executeRemediationPlan('dataset-4', 'plan-1', 'c'.repeat(64), true);
    assert.equal(result.status, 'completed');
  });
  await withMockFetch(async (input) => {
    assert.equal(String(input), '/api/v1/operations/plan-1/remediation-artifacts/manifest');
    return new Response('{"verified":true}', {
      status: 200,
      headers: { 'Content-Disposition': 'attachment; filename="DataLeakGuard_Repair_Manifest.json"' },
    });
  }, async () => {
    const artifact = await downloadRemediationArtifact('plan-1', 'manifest');
    assert.equal(artifact.filename, 'DataLeakGuard_Repair_Manifest.json');
    assert.equal(await artifact.blob.text(), '{"verified":true}');
  });
});

test('remediation cancellation and history use the authenticated dataset-scoped API', async () => {
  await withMockFetch(async (input, init) => {
    assert.equal(String(input), '/api/v1/datasets/dataset-4/remediation-plans/plan-1/cancel');
    assert.equal(init?.method, 'POST');
    assert.deepEqual(JSON.parse(String(init?.body)), { reason: 'User cancelled' });
    return new Response(JSON.stringify({
      ...remediationPlanResponse,
      status: 'cancelled',
    }), { status: 200 });
  }, async () => {
    const result = await cancelRemediationPlan('dataset-4', 'plan-1', 'User cancelled');
    assert.equal(result.status, 'cancelled');
  });
  await withMockFetch(async (input) => {
    assert.equal(String(input), '/api/v1/datasets/dataset-4/remediation-plans?skip=0&limit=10');
    return new Response(JSON.stringify({
      items: [remediationPlanResponse],
      total: 1,
      skip: 0,
      limit: 10,
    }), { status: 200 });
  }, async () => {
    const page = await getRemediationPlans('dataset-4', { skip: 0, limit: 10 });
    assert.equal(page.total, 1);
    assert.equal(page.items[0].id, 'plan-1');
  });
});

test('paginated dataset history maps filters and activity detail fields', async () => {
  await withMockFetch(async (input) => {
    const url = new URL(String(input), 'http://localhost');
    assert.match(url.pathname, /\/datasets\/dataset-4\/history\/page$/);
    assert.equal(url.searchParams.get('event_type'), 'repair');
    assert.equal(url.searchParams.get('status'), 'failed');
    assert.equal(url.searchParams.get('start_date'), '2026-01-01T00:00:00.000Z');
    assert.equal(url.searchParams.get('search'), 'operation-4');
    return new Response(JSON.stringify({
      items: [{
        id: 'operation:operation-4',
        event_type: 'repair',
        outcome: 'failed',
        details: { operation_metadata: { rows: 2 } },
        created_at: '2026-01-02T00:00:00Z',
        completed_at: '2026-01-02T00:01:00Z',
        dataset_id: 'dataset-4',
        dataset_name: 'Example dataset',
        finding_id: 'finding-17',
        operation_id: 'operation-4',
        user_id: 'user-4',
        failure_reason: 'test-only',
      }],
      total: 1,
      skip: 0,
      limit: 25,
    }), { status: 200 });
  }, async () => {
    const result = await getDatasetHistoryPage('dataset-4', {
      eventType: 'repair',
      status: 'failed',
      startDate: '2026-01-01T00:00:00.000Z',
      search: 'operation-4',
    });
    assert.equal(result.items[0].operationId, 'operation-4');
    assert.equal(result.items[0].failureReason, 'test-only');
    assert.equal(result.items[0].datasetName, 'Example dataset');
    assert.deepEqual(result.items[0].details, { operation_metadata: { rows: 2 } });
  });
});

test('column recommendation API maps owner-scoped heuristic candidates without sample values', async () => {
  await withMockFetch(async (input) => {
    assert.match(String(input), /\/datasets\/dataset-4\/column-recommendations$/);
    return new Response(JSON.stringify({
      profiled_column_count: 120,
      sample_count: 10,
      roles: {
        target: {
          recommendation: {
            column_name: 'risk_category',
            role: 'target',
            score: 80,
            confidence: 'high',
            explanation: 'Name and profile match.',
            supporting_signals: ['categorical type'],
            warnings: [],
            profile: {
              data_type: 'object',
              kind: 'categorical',
              unique_count: 3,
              unique_ratio: 0.3,
              missing_count: 1,
              missing_ratio: 0.1,
              sample_count: 10,
              recognized_split_labels: [],
              datetime_parseable_sample_count: 0,
              preview_rows_considered: 6,
            },
          },
          candidates: [],
          warnings: [],
        },
        entity: { recommendation: null, candidates: [], warnings: [] },
        split: { recommendation: null, candidates: [], warnings: ['No reliable recommendation'] },
        timestamp: { recommendation: null, candidates: [], warnings: [] },
      },
      limitations: ['Heuristic points are not probabilities.'],
    }), { status: 200 });
  }, async () => {
    const result = await getColumnRecommendations('dataset-4');
    assert.equal(result.profiledColumnCount, 120);
    assert.equal(result.roles.target.recommendation?.columnName, 'risk_category');
    assert.equal(result.roles.target.recommendation?.profile.uniqueCount, 3);
    assert.equal(result.roles.split.recommendation, null);
  });
});

test('analysis stage execution covers optional detector requirements and configuration gaps', () => {
  const fullyConfigured = buildAnalysisStages(
    { exact_duplicate: 0, entity_overlap: 2, target_leakage: 1, temporal_leakage: 3, train_test_contamination: 0 },
    { entityColumn: 'subject', splitColumn: 'partition', targetColumn: 'label', timeColumn: 'captured_at' },
    'completed'
  );
  assert.deepEqual(
    fullyConfigured.filter((stage) => stage.status === 'completed').map((stage) => stage.id),
    [2, 3, 4, 5, 6]
  );
  assert.equal(fullyConfigured[2].findingsCount, 2);
  assert.equal(fullyConfigured[5].findingsCount, 0);

  const incomplete = buildAnalysisStages({}, { entityColumn: 'subject', timeColumn: 'captured_at' });
  assert.equal(incomplete[2].status, 'needs_configuration');
  assert.match(incomplete[2].description, /split column/);
  assert.equal(incomplete[4].status, 'needs_configuration');
  assert.equal(incomplete[5].status, 'not_run');

  const failed = buildAnalysisStages({}, { targetColumn: 'label' }, 'failed');
  assert.equal(failed[1].status, 'failed');
  assert.equal(failed[3].status, 'failed');
  assert.equal(failed[2].status, 'not_run');
});

test('upload metadata exposes only backend-supported formats case-insensitively', () => {
  assert.deepEqual(getSupportedUploadDetails('data.CSV'), { type: 'tabular', format: 'CSV' });
  assert.deepEqual(getSupportedUploadDetails('data.xlsx'), { type: 'tabular', format: 'XLSX' });
  assert.deepEqual(getSupportedUploadDetails('images.ZIP'), { type: 'computer-vision', format: 'ZIP' });
  assert.equal(getSupportedUploadDetails('labels.txt'), null);
  assert.equal(getSupportedUploadDetails('annotations.json'), null);
  assert.equal(getSupportedUploadDetails('csv'), null);
});

test('analysis request with no optional columns runs exact duplicates and maps persisted findings', async () => {
  await withMockFetch(async (input, init) => {
    assert.match(String(input), /\/datasets\/dataset-4\/analyze\/leakage$/);
    assert.equal(init?.method, 'POST');
    assert.equal(init?.body, undefined);
    return new Response(JSON.stringify({
      dataset_id: 'dataset-4',
      rows_examined: 3,
      duplicate_group_count: 1,
      duplicated_row_count: 2,
      findings: [{
        id: 'duplicate-1',
        dataset_id: 'dataset-4',
        finding_type: 'exact_duplicate',
        severity: 'medium',
        status: 'open',
        description: 'Two identical rows.',
        evidence: { row_indices: [0, 2] },
        created_at: '2026-01-15T12:30:00Z',
      }],
    }), { status: 200 });
  }, async () => {
    const result = await runDatasetAnalysis('dataset-4');
    assert.deepEqual(
      result.stages.filter((stage) => stage.status === 'completed').map((stage) => stage.id),
      [2]
    );
    assert.equal(result.summary.duplicateFindings, 1);
    assert.deepEqual(result.summary, { totalFindings: 1, duplicateFindings: 1 });
    assert.deepEqual(result.findings[0].evidence, { row_indices: [0, 2] });
    assert.equal(result.splitStrategy, 'none');
    assert.equal(result.stages[5].status, 'skipped');
  });
});

test('generated split analysis sends its operation reference and preserves backend strategy metadata', async () => {
  await withMockFetch(async (input, init) => {
    const url = new URL(String(input), 'http://localhost');
    assert.equal(init?.method, 'POST');
    assert.equal(url.searchParams.get('split_strategy'), 'generated');
    assert.equal(url.searchParams.get('split_operation_id'), 'split-operation-8');
    assert.equal(url.searchParams.get('split_column'), null);
    return new Response(JSON.stringify({
      dataset_id: 'dataset-4',
      rows_examined: 4,
      duplicate_group_count: 0,
      duplicated_row_count: 0,
      findings: [],
      split_strategy: 'generated',
      split_configuration: {
        split_operation_id: 'split-operation-8',
        split_column: '__dataleakguard_split__',
        test_ratio: 0.25,
        random_seed: 8,
      },
      skipped_detectors: [],
      split_explanation: 'Verified generated copy.',
    }), { status: 200 });
  }, async () => {
    const result = await runDatasetAnalysis('dataset-4', {
      splitStrategy: 'generated',
      splitOperationId: 'split-operation-8',
      entityColumn: 'patient_id',
    });
    assert.equal(result.splitStrategy, 'generated');
    assert.equal(result.splitConfiguration?.random_seed, 8);
    assert.equal(result.splitExplanation, 'Verified generated copy.');
    assert.equal(result.stages[2].status, 'completed');
    assert.equal(result.stages[5].status, 'completed');
  });
});

test('analysis request preserves a manually selected target and no-split mode', async () => {
  await withMockFetch(async (input, init) => {
    const url = new URL(String(input), 'http://localhost');
    assert.equal(init?.method, 'POST');
    assert.equal(url.searchParams.get('target_column'), 'readmitted_30d');
    assert.equal(url.searchParams.get('split_strategy'), 'none');
    assert.equal(url.searchParams.get('entity_column'), null);
    assert.equal(url.searchParams.get('time_column'), null);
    return new Response(JSON.stringify({
      dataset_id: 'dataset-4',
      rows_examined: 8,
      duplicate_group_count: 0,
      duplicated_row_count: 0,
      findings: [{
        id: 'target-finding-1',
        dataset_id: 'dataset-4',
        finding_type: 'target_leakage',
        severity: 'high',
        status: 'open',
        description: 'A feature deterministically maps to the selected target.',
        evidence: {
          target_column: 'readmitted_30d',
          feature_column: 'readmission_flag_copy',
          detection: 'exact_target_duplicate',
        },
        created_at: '2026-11-03T00:00:00Z',
      }],
      split_strategy: 'none',
      split_configuration: { strategy: 'none' },
      skipped_detectors: [
        'entity_overlap',
        'temporal_leakage',
        'train_test_contamination',
      ],
      split_explanation: 'Split-dependent checks were not evaluated.',
    }), { status: 200 });
  }, async () => {
    const result = await runDatasetAnalysis('dataset-4', {
      targetColumn: 'readmitted_30d',
      splitStrategy: 'none',
    });
    assert.equal(result.splitStrategy, 'none');
    assert.equal(result.findings[0].evidence?.target_column, 'readmitted_30d');
    assert.deepEqual(result.skippedDetectors, [
      'entity_overlap',
      'temporal_leakage',
      'train_test_contamination',
    ]);
  });
});

test('split generation API submits explicit ratio and seed and maps persisted response', async () => {
  await withMockFetch(async (input, init) => {
    assert.equal(String(input), '/api/v1/datasets/dataset-4/split-strategies/generate');
    assert.equal(init?.method, 'POST');
    assert.deepEqual(JSON.parse(String(init?.body)), {
      test_ratio: 0.3,
      random_seed: 22,
    });
    return new Response(JSON.stringify({
      id: 'split-operation-8',
      dataset_id: 'dataset-4',
      operation_type: 'split_generation',
      status: 'completed',
      split_column: '__dataleakguard_split__',
      test_ratio: 0.3,
      random_seed: 22,
      algorithm: 'sha256_seeded_row_order_v1',
      row_count: 10,
      split_row_counts: { train: 7, test: 3 },
      input_file_sha256: 'input-hash',
      output_file_sha256: 'output-hash',
      output_filename: 'split.csv',
      created_at: null,
      completed_at: null,
      reused: false,
    }), { status: 201 });
  }, async () => {
    const operation = await generateDatasetSplit('dataset-4', {
      testRatio: 0.3,
      randomSeed: 22,
    });
    assert.equal(operation.id, 'split-operation-8');
    assert.equal(operation.datasetId, 'dataset-4');
    assert.deepEqual(operation.splitRowCounts, { train: 7, test: 3 });
    assert.equal(operation.outputFileSha256, 'output-hash');
  });
});

test('analysis query maps valid entity, target, temporal, and split selections to backend names', async () => {
  await withMockFetch(async (input, init) => {
    const url = new URL(String(input), 'http://localhost');
    assert.equal(init?.method, 'POST');
    assert.equal(url.searchParams.get('entity_column'), 'subject id');
    assert.equal(url.searchParams.get('split_column'), 'data split');
    assert.equal(url.searchParams.get('target_column'), 'outcome');
    assert.equal(url.searchParams.get('time_column'), 'event date');
    return new Response(JSON.stringify({
      findings: [
        { ...backendFinding, finding_type: 'entity_overlap' },
        { ...backendFinding, id: 'finding-target', finding_type: 'target_leakage' },
        { ...backendFinding, id: 'finding-time', finding_type: 'temporal_leakage' },
        { ...backendFinding, id: 'finding-contamination', finding_type: 'train_test_contamination' },
      ],
    }), { status: 200 });
  }, async () => {
    const result = await runDatasetAnalysis('dataset-4', {
      entityColumn: 'subject id',
      splitColumn: 'data split',
      targetColumn: 'outcome',
      timeColumn: 'event date',
    });
    assert.deepEqual(result.stages.filter((stage) => stage.status === 'completed').map((stage) => stage.id), [2, 3, 4, 5, 6]);
    assert.equal(result.summary.totalFindings, 4);
  });
});

test('no-split analysis omits split-dependent parameters and marks those checks skipped', async () => {
  await withMockFetch(async (input) => {
    const url = new URL(String(input), 'http://localhost');
    assert.equal(url.searchParams.get('entity_column'), null);
    assert.equal(url.searchParams.get('time_column'), null);
    assert.equal(url.searchParams.get('target_column'), 'label');
    assert.equal(url.searchParams.get('split_column'), null);
    return new Response(JSON.stringify({
      findings: [],
      split_strategy: 'none',
      skipped_detectors: ['entity_overlap', 'temporal_leakage', 'train_test_contamination'],
    }), { status: 200 });
  }, async () => {
    const result = await runDatasetAnalysis('dataset-4', {
      entityColumn: 'subject',
      targetColumn: 'label',
      timeColumn: 'captured_at',
    });
    assert.deepEqual(result.stages.filter((stage) => stage.status === 'completed').map((stage) => stage.id), [2, 4]);
    assert.equal(result.stages[2].status, 'skipped');
    assert.equal(result.stages[4].status, 'skipped');
    assert.equal(result.stages[5].status, 'skipped');
  });
});

test('backend validation errors are surfaced and never returned as completed analysis', async () => {
  await withMockFetch(async () => new Response(JSON.stringify({
    detail: "Target column 'missing_target' not found in dataset columns",
  }), { status: 400 }), async () => {
    await assert.rejects(
      runDatasetAnalysis('dataset-4', { targetColumn: 'missing_target' }),
      /Leakage analysis failed \(400\): Target column 'missing_target' not found/
    );
  });
});

const backendFinding = {
  id: 'finding-17',
  dataset_id: 'dataset-4',
  finding_type: 'entity_overlap',
  severity: 'high',
  status: 'open',
  description: 'One entity appears in more than one split.',
  evidence: { entity_value: 'subject-2', row_indices: { train: [0], test: [4] } },
  created_at: '2026-01-15T12:30:00Z',
};

async function withMockFetch<T>(
  handler: (input: RequestInfo | URL, init?: RequestInit) => Response | Promise<Response>,
  run: () => Promise<T>
): Promise<T> {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = handler as typeof fetch;
  try {
    return await run();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

const backendDataset = {
  id: 'dataset-4',
  name: 'Example dataset',
  type: 'tabular',
  format: 'CSV',
  sample_count: 2,
  feature_count: 1,
  class_count: null,
  status: null,
  issues_count: 0,
  uploaded_at: '2026-01-15T12:30:00Z',
  last_analysis: null,
  description: null,
  profile: { image_count: 2 },
  columns: [{ name: 'first_name', type: 'object', missingCount: 0, uniqueCount: 1 }],
  preview_rows: [{ first_name: 'Ada' }],
};

test('dataset API uses its base URL helper and preserves backend optional values', async () => {
  await withMockFetch(async (input) => {
    assert.equal(String(input), '/api/v1/datasets');
    return new Response(JSON.stringify([backendDataset]), { status: 200 });
  }, async () => {
    const datasets = await getDatasets();
    assert.equal(datasets[0].sampleCount, 2);
    assert.equal(datasets[0].description, null);
    assert.equal(datasets[0].classCount, null);
    assert.deepEqual(datasets[0].profile, { imageCount: 2 });
    assert.deepEqual(datasets[0].columns?.map((column) => column.name), ['first_name']);
    assert.deepEqual(datasets[0].previewRows, [{ first_name: 'Ada' }]);
  });
});

test('getDatasetById treats only 404 as not found and surfaces server failures', async () => {
  await withMockFetch(async (input) => {
    assert.equal(String(input), '/api/v1/datasets/dataset%2F4');
    return new Response(null, { status: 404 });
  }, async () => {
    assert.equal(await getDatasetById('dataset/4'), null);
  });

  await withMockFetch(async () => new Response('failure', { status: 503 }), async () => {
    await assert.rejects(getDatasetById('dataset-4'), /Failed to fetch dataset: 503/);
  });
});

test('upload and delete requests match the dataset API contract', async () => {
  const file = new globalThis.File(['name\nAda\n'], 'sample.csv', { type: 'text/csv' });
  await withMockFetch(async (input, init) => {
    assert.equal(String(input), '/api/v1/datasets');
    assert.equal(init?.method, 'POST');
    const formData = init?.body as FormData;
    assert.equal(formData.get('name'), 'Example dataset');
    assert.equal(formData.get('type'), 'tabular');
    assert.equal(formData.get('format'), 'CSV');
    assert.equal(formData.get('description'), 'Upload contract test');
    assert.equal(formData.get('sample_count'), null);
    assert.equal((formData.get('file') as File).name, 'sample.csv');
    return new Response(JSON.stringify(backendDataset), { status: 201 });
  }, async () => {
    await uploadDataset({
      name: 'Example dataset',
      type: 'tabular',
      format: 'CSV',
      description: 'Upload contract test',
      file,
    });
  });

  await withMockFetch(async (input, init) => {
    assert.equal(String(input), '/api/v1/datasets/dataset%2F4');
    assert.equal(init?.method, 'DELETE');
    return new Response(null, { status: 204 });
  }, async () => {
    assert.equal(await deleteDataset('dataset/4'), true);
  });
});

test('getFindings reads and maps persisted dataset findings without inventing fields', async () => {
  await withMockFetch(async (input) => {
    assert.match(String(input), /\/datasets\/dataset-4\/findings$/);
    return new Response(JSON.stringify([backendFinding]), { status: 200 });
  }, async () => {
    const findings = await getFindings('dataset-4');
    assert.deepEqual(findings, [{
      id: 'finding-17',
      datasetId: 'dataset-4',
      findingType: 'entity_overlap',
      severity: 'high',
      status: 'open',
      description: 'One entity appears in more than one split.',
      evidence: backendFinding.evidence,
      createdAt: '2026-01-15T12:30:00Z',
    }]);
    assert.equal('trainSampleId' in findings[0], false);
    assert.equal('similarity' in findings[0], false);
  });
});

test('finding mapping leaves absent optional evidence and creation time absent', () => {
  const mapped = mapPersistedFinding({
    id: 'finding-18',
    dataset_id: 'dataset-4',
    finding_type: 'future_detector',
    severity: 'unrated',
    status: 'open',
    description: 'A finding from an unrecognized detector.',
  });

  assert.equal(mapped.evidence, null);
  assert.equal(mapped.createdAt, null);
  assert.equal(mapped.findingType, 'future_detector');
});

test('getFindingById uses the persisted finding endpoint and handles not found', async () => {
  await withMockFetch(async (input) => {
    assert.match(String(input), /\/findings\/finding-17$/);
    return new Response(JSON.stringify(backendFinding), { status: 200 });
  }, async () => {
    assert.equal((await getFindingById('finding-17'))?.datasetId, 'dataset-4');
  });

  await withMockFetch(async () => new Response(null, { status: 404 }), async () => {
    assert.equal(await getFindingById('missing'), null);
  });
});

test('finding API rejects server errors and malformed response shapes', async () => {
  await withMockFetch(async () => new Response('failure', { status: 503 }), async () => {
    await assert.rejects(getFindings('dataset-4'), /Failed to fetch findings: 503/);
  });

  await withMockFetch(async () => new Response(JSON.stringify({ findings: [] }), { status: 200 }), async () => {
    await assert.rejects(getFindings('dataset-4'), /expected an array/);
  });
});

test('category summaries count only persisted findings and include unknown types', async () => {
  const mappedFindings: PersistedFinding[] = [
    mapPersistedFinding(backendFinding),
    mapPersistedFinding({ ...backendFinding, id: 'finding-18' }),
    mapPersistedFinding({ ...backendFinding, id: 'finding-19', finding_type: 'future_detector' }),
  ];
  assert.deepEqual(summarizeFindings(mappedFindings), [
    { findingType: 'entity_overlap', label: 'Entity overlap', findingsCount: 2 },
    {
      findingType: 'future_detector',
      label: 'Unknown finding type (future_detector)',
      findingsCount: 1,
    },
  ]);

  await withMockFetch(async (input) => {
    assert.match(String(input), /\/datasets\/dataset-4\/findings$/);
    return new Response(JSON.stringify([backendFinding]), { status: 200 });
  }, async () => {
    assert.deepEqual(await getCategoryOverviews('dataset-4'), [
      { findingType: 'entity_overlap', label: 'Entity overlap', findingsCount: 1 },
    ]);
  });

  assert.deepEqual(summarizeFindings([]), []);
});

const repairOperationResponse = {
  id: 'operation-21',
  dataset_id: 'dataset-4',
  finding_id: 'finding-17',
  operation_type: 'repair',
  status: 'completed',
  input_file: 'source.csv',
  input_file_sha256: 'input-hash',
  output_file: 'processed.csv',
  output_filename: 'processed.csv',
  output_file_sha256: 'output-hash',
  affected_rows: 3,
  created_at: '2026-01-15T13:00:00Z',
  completed_at: '2026-01-15T13:00:01Z',
  // History routes currently return placeholder defaults for these values.
  original_row_count: 0,
  processed_row_count: 0,
};

const combinedOperationResponse = {
  id: 'combined-operation-31',
  dataset_id: 'dataset-4',
  finding_id: null,
  operation_type: 'combined_repair',
  status: 'completed',
  input_file_sha256: 'input-sha256',
  output_filename: 'cleaned.csv',
  output_file_sha256: 'output-sha256',
  affected_rows: 2,
  operation_metadata: {
    selected_finding_ids: ['duplicate-a', 'duplicate-b'],
    applied_finding_ids: ['duplicate-a', 'duplicate-b'],
    skipped_findings: [],
    original_row_count: 5,
    final_row_count: 3,
    duplicate_rows_removed: 2,
  },
};

const combinedRepairPreviewResponse = {
  dataset_id: 'dataset-4',
  input_file_sha256: 'input-sha256',
  selected_finding_ids: ['duplicate-a', 'duplicate-b'],
  applied_finding_ids: ['duplicate-a', 'duplicate-b'],
  skipped_findings: [],
  original_row_count: 5,
  final_row_count: 3,
  duplicate_rows_removed: 2,
  affected_row_indices_preview: [2, 4],
  affected_row_indices_count: 2,
  affected_row_indices_truncated: false,
  affected_row_indices_sha256: 'a'.repeat(64),
  operation_type: 'combined_repair_preview',
  status: 'preview',
  preview_token: 'fresh-preview-token',
  explanation: 'Eligible exact-duplicate findings will be applied to one separate output.',
};

test('operation history maps returned fields and omits placeholder row totals', async () => {
  await withMockFetch(async (input) => {
    assert.match(String(input), /\/datasets\/dataset-4\/repairs$/);
    return new Response(JSON.stringify([repairOperationResponse]), { status: 200 });
  }, async () => {
    const history = await getDatasetOperationHistory('dataset-4');
    assert.deepEqual(history, [{
      id: 'operation-21',
      datasetId: 'dataset-4',
      findingId: 'finding-17',
      operationType: 'repair',
      status: 'completed',
      inputFile: 'source.csv',
      inputFileSha256: 'input-hash',
      outputFilename: 'processed.csv',
      outputFileSha256: 'output-hash',
      affectedRows: 3,
      createdAt: '2026-01-15T13:00:00Z',
      completedAt: '2026-01-15T13:00:01Z',
    }]);
    assert.equal('originalRowCount' in history[0], false);
    assert.equal('processedRowCount' in history[0], false);
  });
});

test('operation mapping preserves absent metadata instead of substituting zeroes', () => {
  const mapped = mapDatasetOperationRecord({
    quarantine_id: 'quarantine-22',
    dataset_id: 'dataset-4',
    finding_id: 'finding-17',
    operation_type: 'quarantine',
    status: 'completed',
  });

  assert.equal(mapped.id, 'quarantine-22');
  assert.equal(mapped.outputFilename, undefined);
  assert.equal(mapped.affectedRows, undefined);
  assert.equal(mapped.createdAt, undefined);
});

test('operation metadata mapping tolerates legacy missing/null skipped findings and preserves recorded values', () => {
  const base = {
    id: 'operation-legacy',
    dataset_id: 'dataset-4',
    operation_type: 'split_generation',
    status: 'completed',
  };
  for (const operationMetadata of [
    { strategy: 'generated' },
    { strategy: 'generated', skipped_findings: null },
    { strategy: 'generated', skipped_findings: 'legacy-unavailable' },
  ]) {
    const mapped = mapDatasetOperationRecord({
      ...base,
      operation_metadata: operationMetadata,
    });
    assert.deepEqual(mapped.operationMetadata?.skippedFindings, []);
    assert.equal(mapped.operationMetadata?.skippedFindingsRecorded, false);
    assert.equal(mapped.operationMetadata?.selectedFindingIds, undefined);
  }

  const empty = mapDatasetOperationRecord({
    ...base,
    operation_metadata: { skipped_findings: [] },
  });
  assert.deepEqual(empty.operationMetadata?.skippedFindings, []);
  assert.equal(empty.operationMetadata?.skippedFindingsRecorded, true);

  const populated = mapDatasetOperationRecord({
    ...base,
    operation_metadata: {
      selected_finding_ids: ['finding-1'],
      applied_finding_ids: [],
      skipped_findings: [{ finding_id: 'finding-1', reason: 'Evidence is stale.' }],
    },
  });
  assert.deepEqual(populated.operationMetadata?.skippedFindings, [
    { findingId: 'finding-1', reason: 'Evidence is stale.' },
  ]);
  assert.equal(populated.operationMetadata?.skippedFindingsRecorded, true);
  assert.deepEqual(populated.operationMetadata?.selectedFindingIds, ['finding-1']);
});

test('operation mapping preserves deterministic repair verification metadata', () => {
  const mapped = mapDatasetOperationRecord({
    repair_id: 'repair-verified',
    dataset_id: 'dataset-4',
    finding_id: 'finding-17',
    operation_type: 'repair',
    status: 'completed',
    operation_metadata: {
      selected_finding_ids: ['finding-17'],
      applied_finding_ids: ['finding-17'],
      skipped_findings: [],
      original_row_count: 8,
      final_row_count: 7,
      duplicate_rows_removed: 1,
      evidence_reference_finding_ids: ['finding-17'],
      repair_strategy: 'exact_duplicate_keep_first',
      verification_status: 'verified',
      verification: {
        output_readable: true,
        output_schema_matches: true,
        output_row_count: 7,
        remaining_evidenced_duplicate_rows: 1,
      },
    },
  });
  assert.equal(mapped.operationMetadata?.repairStrategy, 'exact_duplicate_keep_first');
  assert.equal(mapped.operationMetadata?.verificationStatus, 'verified');
  assert.equal(mapped.operationMetadata?.verification?.output_row_count, 7);
});

test('repair and quarantine actions POST to their finding-specific backend routes', async () => {
  await withMockFetch(async (input, init) => {
    assert.equal(init?.method, 'POST');
    assert.match(String(input), /\/findings\/finding-17\/repair$/);
    return new Response(JSON.stringify({
      ...repairOperationResponse,
      operation_metadata: {
        selected_finding_ids: ['finding-17'],
        skipped_findings: null,
      },
    }), { status: 201 });
  }, async () => {
    const result = await repairFinding('finding-17');
    assert.equal(result.id, 'operation-21');
    assert.equal(result.operationType, 'repair');
    assert.equal(result.affectedRows, 3);
    assert.deepEqual(result.operationMetadata?.skippedFindings, []);
    assert.equal(result.operationMetadata?.skippedFindingsRecorded, false);
  });

  await withMockFetch(async (input, init) => {
    assert.equal(init?.method, 'POST');
    assert.match(String(input), /\/findings\/finding-17\/quarantine$/);
    return new Response(JSON.stringify({
      ...repairOperationResponse,
      quarantine_id: 'quarantine-23',
      operation_type: 'quarantine',
      output_filename: 'affected-rows.csv',
      operation_metadata: null,
    }), { status: 201 });
  }, async () => {
    const result = await quarantineFinding('finding-17');
    assert.equal(result.id, 'quarantine-23');
    assert.equal(result.operationType, 'quarantine');
    assert.equal(result.outputFilename, 'affected-rows.csv');
    assert.equal(result.operationMetadata, null);
  });
});

test('combined repair preview maps the server-computed impact without writing output', async () => {
  await withMockFetch(async (input, init) => {
    assert.match(
      String(input),
      /\/datasets\/dataset-4\/repairs\/combined\/preview$/
    );
    assert.equal(init?.method, 'POST');
    assert.equal(
      new Headers(init?.headers).get('content-type'),
      'application/json'
    );
    assert.deepEqual(JSON.parse(String(init?.body)), {
      selected_finding_ids: ['duplicate-a', 'duplicate-b'],
    });
    return new Response(JSON.stringify(combinedRepairPreviewResponse), { status: 200 });
  }, async () => {
    const result = await previewCombinedCleanedDataset(
      'dataset-4',
      ['duplicate-a', 'duplicate-b']
    );
    assert.equal(result.operationType, 'combined_repair_preview');
    assert.equal(result.status, 'preview');
    assert.equal(result.previewToken, 'fresh-preview-token');
    assert.equal(result.originalRowCount, 5);
    assert.equal(result.finalRowCount, 3);
    assert.equal(result.duplicateRowsRemoved, 2);
    assert.deepEqual(result.affectedRowIndicesPreview, [2, 4]);
    assert.equal(result.affectedRowIndicesCount, 2);
    assert.equal(result.affectedRowIndicesTruncated, false);
    assert.equal(result.affectedRowIndicesSha256, 'a'.repeat(64));
    assert.deepEqual(result.appliedFindingIds, [
      'duplicate-a',
      'duplicate-b',
    ]);
  });
});

test('combined repair requires the preview token and explicit confirmation in its request', async () => {
  await withMockFetch(async (input, init) => {
    assert.match(String(input), /\/datasets\/dataset-4\/repairs\/combined$/);
    assert.equal(init?.method, 'POST');
    assert.deepEqual(JSON.parse(String(init?.body)), {
      selected_finding_ids: ['duplicate-a', 'duplicate-b'],
      preview_token: 'fresh-preview-token',
      confirmed: true,
    });
    return new Response(JSON.stringify(combinedOperationResponse), { status: 201 });
  }, async () => {
    const result = await generateCombinedCleanedDataset(
      'dataset-4',
      ['duplicate-a', 'duplicate-b'],
      'fresh-preview-token',
      true
    );
    assert.equal(result.id, 'combined-operation-31');
    assert.equal(result.operationType, 'combined_repair');
    assert.equal(result.operationMetadata?.originalRowCount, 5);
    assert.equal(result.operationMetadata?.finalRowCount, 3);
    assert.equal(result.operationMetadata?.duplicateRowsRemoved, 2);
  });
});

test('combined repair validates empty selection and rejects missing confirmation before fetch', async () => {
  await assert.rejects(
    generateCombinedCleanedDataset('dataset-4', [], 'token', true),
    /Select at least one eligible exact-duplicate finding/
  );
  await assert.rejects(
    generateCombinedCleanedDataset('dataset-4', ['duplicate-a'], '', true),
    /current preview token and explicit confirmation/
  );
  await assert.rejects(
    generateCombinedCleanedDataset('dataset-4', ['duplicate-a'], 'token', false),
    /current preview token and explicit confirmation/
  );

  await withMockFetch(async () => new Response(JSON.stringify({
    detail: {
      message: 'No selected findings remain eligible for combined repair',
      skipped_findings: [{
        finding_id: 'stale-finding',
        reason: 'Evidence no longer matches the original dataset rows.',
      }],
    },
  }), { status: 409 }), async () => {
    await assert.rejects(
      generateCombinedCleanedDataset('dataset-4', ['stale-finding'], 'stale-token', true),
      /combined cleaned dataset \(409\).*No selected findings remain eligible.*stale-finding.*Evidence no longer matches/
    );
  });
});

test('operation API surfaces backend errors and rejects malformed histories', async () => {
  await withMockFetch(async () => new Response('failure', { status: 500 }), async () => {
    await assert.rejects(getDatasetOperationHistory('dataset-4'), /Failed to fetch operation history: 500/);
    await assert.rejects(repairFinding('finding-17'), /Failed to repair finding: 500/);
  });

  await withMockFetch(async () => new Response(JSON.stringify({ operations: [] }), { status: 200 }), async () => {
    await assert.rejects(getDatasetOperationHistory('dataset-4'), /expected an array/);
  });
});

test('operation output download requests binary data and returns a safe server filename', async () => {
  const payload = 'name,value\nsample,1\n';
  await withMockFetch(async (input, init) => {
    assert.match(
      String(input),
      /\/operations\/operation-21\/download$/
    );
    assert.equal(init?.method, undefined);
    return new Response(new Blob([payload], { type: 'text/csv' }), {
      status: 200,
      headers: {
        'Content-Disposition': 'attachment; filename="processed-copy.csv"',
      },
    });
  }, async () => {
    const result = await downloadOperationOutput('operation-21');
    assert.equal(result.filename, 'processed-copy.csv');
    assert.equal(await result.blob.text(), payload);
    assert.equal(result.blob.type, 'text/csv');
  });
});

test('operation output download surfaces backend errors and rejects unsafe filenames', async () => {
  await withMockFetch(async () => new Response(JSON.stringify({
    detail: 'Operation output failed SHA-256 integrity verification',
  }), { status: 500 }), async () => {
    await assert.rejects(
      downloadOperationOutput('operation-21'),
      /Failed to download operation output \(500\).*integrity verification/
    );
  });

  await withMockFetch(async () => new Response(new Blob(['data']), {
    status: 200,
    headers: {
      'Content-Disposition': 'attachment; filename="../outside.csv"',
    },
  }), async () => {
    await assert.rejects(
      downloadOperationOutput('operation-21'),
      /unsafe filename/
    );
  });
});

test('persisted report mapping preserves backend metrics and does not invent assessments', async () => {
  const persistedReport = {
    id: 'report-21',
    title: 'Persisted snapshot',
    dataset_id: 'dataset-4',
    created_at: '2026-10-29T10:00:00Z',
    content: {
      datasets: [{
        id: 'dataset-4',
        name: 'Example dataset',
        format: 'CSV',
        sha256: 'a'.repeat(64),
      }],
      impact: [{
        findings_total: 4,
        findings_open: 3,
        findings_high_severity: 1,
        operations_total: 2,
        operations_completed: 2,
        affected_rows: 5,
      }],
    },
  };

  await withMockFetch(async (input) => {
    assert.equal(String(input), '/api/v1/reports');
    return new Response(JSON.stringify([persistedReport]), { status: 200 });
  }, async () => {
    const [report] = await getReports();
    assert.equal(report.id, 'report-21');
    assert.equal(report.datasetName, 'Example dataset (CSV)');
    assert.equal(report.disposition, 'NOT ASSESSED');
    assert.equal(report.confidenceScore, null);
    assert.equal(report.projectDefinedRisk, 'NOT ASSESSED');
    assert.deepEqual(report.findingsCount, {
      critical: null,
      high: null,
      medium: null,
      low: null,
    });
    assert.deepEqual(report.persistedContent?.impact[0], persistedReport.content.impact[0]);
    assert.match(report.sections.evidence, /not full finding evidence/);
    assert.match(report.sections.performanceImpact, /No model performance evaluation/);
  });
});

test('report creation maps the persisted response without inventing a fallback report', async () => {
  await withMockFetch(async (input, init) => {
    assert.equal(String(input), '/api/v1/reports');
    assert.equal(init?.method, 'POST');
    assert.deepEqual(JSON.parse(String(init?.body)), {
      dataset_id: 'dataset-4',
      title: 'DataLeakGuard persisted report',
    });
    return new Response(JSON.stringify({
      id: 'report-22',
      title: 'Persisted report',
      dataset_id: 'dataset-4',
      content: {
        datasets: [{ id: 'dataset-4', name: 'Example dataset', format: 'CSV', sha256: 'b'.repeat(64) }],
        impact: [{ findings_total: 0, findings_open: 0, findings_high_severity: 0, operations_total: 0, operations_completed: 0, affected_rows: 0 }],
      },
    }), { status: 201 });
  }, async () => {
    const report = await generateAssuranceReport('dataset-4', '');
    assert.equal(report.id, 'report-22');
    assert.equal(report.disposition, 'NOT ASSESSED');
    assert.equal(report.persistedContent?.impact[0].findings_total, 0);
  });
});

test('distribution comparison exposes persisted metrics and leaves unsupported metrics unavailable', async () => {
  await withMockFetch(async (input) => {
    assert.equal(String(input), '/api/v1/distribution-comparisons');
    return new Response(JSON.stringify([{
      id: 'comparison-1',
      reference_dataset_id: 'dataset-reference',
      comparison_dataset_id: 'dataset-current',
      metrics: {
        age: { kind: 'numeric', psi: 0.24, missing_delta: 0 },
        region: { kind: 'categorical', distribution_delta: 0.16, missing_delta: 0.01 },
      },
    }]), { status: 200 });
  }, async () => {
    const result = await getDistributionShift();
    assert.equal(result.psiScore, 0.24);
    assert.equal(result.wassersteinDistance, null);
    assert.equal(result.oodRate, null);
    assert.equal(result.overallShiftDetected, true);
    assert.deepEqual(result.featureShifts.map(({ featureName, metricKind, driftScore }) => ({
      featureName, metricKind, driftScore,
    })), [
      { featureName: 'age', metricKind: 'PSI', driftScore: 0.24 },
      { featureName: 'region', metricKind: 'Distribution delta', driftScore: 0.16 },
    ]);
  });
});
