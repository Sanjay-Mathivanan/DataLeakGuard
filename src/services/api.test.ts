import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  buildAnalysisStages,
  deleteDataset,
  downloadOperationOutput,
  generateCombinedCleanedDataset,
  getCategoryOverviews,
  getDatasetById,
  getDatasetOperationHistory,
  getDatasets,
  getFindingById,
  getFindings,
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

test('incomplete entity/time selections are omitted instead of sending invalid parameter pairs', async () => {
  await withMockFetch(async (input) => {
    const url = new URL(String(input), 'http://localhost');
    assert.equal(url.searchParams.get('entity_column'), null);
    assert.equal(url.searchParams.get('time_column'), null);
    assert.equal(url.searchParams.get('target_column'), 'label');
    assert.equal(url.searchParams.get('split_column'), null);
    return new Response(JSON.stringify({ findings: [] }), { status: 200 });
  }, async () => {
    const result = await runDatasetAnalysis('dataset-4', {
      entityColumn: 'subject',
      targetColumn: 'label',
      timeColumn: 'captured_at',
    });
    assert.deepEqual(result.stages.filter((stage) => stage.status === 'completed').map((stage) => stage.id), [2, 4]);
    assert.equal(result.stages[2].status, 'needs_configuration');
    assert.equal(result.stages[4].status, 'needs_configuration');
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

test('repair and quarantine actions POST to their finding-specific backend routes', async () => {
  await withMockFetch(async (input, init) => {
    assert.equal(init?.method, 'POST');
    assert.match(String(input), /\/findings\/finding-17\/repair$/);
    return new Response(JSON.stringify(repairOperationResponse), { status: 201 });
  }, async () => {
    const result = await repairFinding('finding-17');
    assert.equal(result.id, 'operation-21');
    assert.equal(result.operationType, 'repair');
    assert.equal(result.affectedRows, 3);
  });

  await withMockFetch(async (input, init) => {
    assert.equal(init?.method, 'POST');
    assert.match(String(input), /\/findings\/finding-17\/quarantine$/);
    return new Response(JSON.stringify({
      ...repairOperationResponse,
      quarantine_id: 'quarantine-23',
      operation_type: 'quarantine',
      output_filename: 'affected-rows.csv',
    }), { status: 201 });
  }, async () => {
    const result = await quarantineFinding('finding-17');
    assert.equal(result.id, 'quarantine-23');
    assert.equal(result.operationType, 'quarantine');
    assert.equal(result.outputFilename, 'affected-rows.csv');
  });
});

test('combined repair posts only selected findings and maps persisted provenance', async () => {
  await withMockFetch(async (input, init) => {
    assert.match(
      String(input),
      /\/datasets\/dataset-4\/repairs\/combined$/
    );
    assert.equal(init?.method, 'POST');
    assert.equal(
      new Headers(init?.headers).get('content-type'),
      'application/json'
    );
    assert.deepEqual(JSON.parse(String(init?.body)), {
      selected_finding_ids: ['duplicate-a', 'duplicate-b'],
    });
    return new Response(JSON.stringify(combinedOperationResponse), { status: 201 });
  }, async () => {
    const result = await generateCombinedCleanedDataset(
      'dataset-4',
      ['duplicate-a', 'duplicate-b']
    );
    assert.equal(result.id, 'combined-operation-31');
    assert.equal(result.operationType, 'combined_repair');
    assert.equal(result.operationMetadata?.originalRowCount, 5);
    assert.equal(result.operationMetadata?.finalRowCount, 3);
    assert.equal(result.operationMetadata?.duplicateRowsRemoved, 2);
    assert.deepEqual(result.operationMetadata?.appliedFindingIds, [
      'duplicate-a',
      'duplicate-b',
    ]);
  });
});

test('combined repair validates empty selection and reports backend errors', async () => {
  await assert.rejects(
    generateCombinedCleanedDataset('dataset-4', []),
    /Select at least one eligible exact-duplicate finding/
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
      generateCombinedCleanedDataset('dataset-4', ['stale-finding']),
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
