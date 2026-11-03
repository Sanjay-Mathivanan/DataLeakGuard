import assert from 'node:assert/strict';
import { test } from 'node:test';
import { findPotentialTargetDerivedFeatures } from './targetFeatureWarnings';

test('target feature warnings identify possible derived names without calling them confirmed leakage', () => {
  const candidates = findPotentialTargetDerivedFeatures('readmitted_30d', [
    'readmitted_30d',
    'patient_id',
    'diagnosis',
    'readmission_flag_copy',
    'post_discharge_followup',
  ]);

  assert.deepEqual(
    candidates.map((candidate) => candidate.columnName),
    ['readmission_flag_copy', 'post_discharge_followup']
  );
  assert.ok(candidates[0].signals.some((signal) => signal.includes('shares a term')));
  assert.ok(candidates[1].signals.some((signal) => signal.includes('post-outcome marker')));
  assert.deepEqual(
    findPotentialTargetDerivedFeatures('', ['target_copy']),
    []
  );
});

