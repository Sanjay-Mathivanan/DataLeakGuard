import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  classifyProfileColumn,
  filterAndSortFeatureColumns,
  ProfileColumn,
  summarizeFeatureColumns,
} from './featureProfileUtils';

const columns: ProfileColumn[] = [
  {
    name: 'Age',
    type: 'int64',
    missingCount: 2,
    uniqueCount: 5,
    statistics: { kind: 'numeric', min: 18, max: 80, mean: 40, median: 39 },
  },
  {
    name: 'patient_id',
    type: 'object',
    missingCount: 0,
    uniqueCount: 80,
    statistics: {
      kind: 'categorical',
      topValues: Array.from({ length: 10 }, (_, index) => ({ value: `p-${index}`, count: 1 })),
    },
  },
  {
    name: 'admission_date',
    type: 'datetime64[ns]',
    missingCount: 1,
    uniqueCount: 20,
  },
  {
    name: 'group',
    type: 'object',
    missingCount: 0,
    uniqueCount: 3,
    statistics: { kind: 'categorical', topValues: [{ value: 'A', count: 10 }] },
  },
];

test('feature profile filters use persisted type, missing, name and cardinality metadata', () => {
  assert.deepEqual(
    filterAndSortFeatureColumns(columns, { search: 'PATIENT' }).map((column) => column.name),
    ['patient_id']
  );
  assert.deepEqual(
    filterAndSortFeatureColumns(columns, { kind: 'numeric' }).map((column) => column.name),
    ['Age']
  );
  assert.deepEqual(
    filterAndSortFeatureColumns(columns, { kind: 'datetime' }).map((column) => column.name),
    ['admission_date']
  );
  assert.deepEqual(
    filterAndSortFeatureColumns(columns, { missing: 'with' }).map((column) => column.name).sort(),
    ['Age', 'admission_date']
  );
  assert.deepEqual(
    filterAndSortFeatureColumns(columns, {
      cardinality: 'high',
      rowCount: 100,
    }).map((column) => column.name),
    ['patient_id']
  );
});

test('feature profile sorting is numeric and summaries preserve observed counts', () => {
  assert.deepEqual(
    filterAndSortFeatureColumns(columns, { sortBy: 'unique', direction: 'desc' })
      .map((column) => column.uniqueCount),
    [80, 20, 5, 3]
  );
  assert.equal(classifyProfileColumn(columns[0]), 'numeric');
  assert.equal(classifyProfileColumn(columns[2]), 'datetime');
  assert.deepEqual(summarizeFeatureColumns(columns, 100), {
    totalColumns: 4,
    numericColumns: 1,
    categoricalColumns: 2,
    datetimeColumns: 1,
    totalMissing: 3,
    columnsWithMissing: 2,
    rowCount: 100,
  });
});
