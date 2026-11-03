import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  getAnalysisSetupStorageKey,
  loadConfirmedAnalysisSetup,
} from './AnalysisSetupPage';

test('analysis setup uses a dataset-specific session key and does not invent unconfirmed configuration', () => {
  assert.equal(getAnalysisSetupStorageKey('dataset-17'), 'dataleakguard:analysis-setup:dataset-17');
  assert.equal(loadConfirmedAnalysisSetup('dataset-17'), null);
});

test('analysis setup reads only explicitly confirmed, supported split strategies', () => {
  const originalWindow = globalThis.window;
  const store = new Map<string, string>();
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: {
      sessionStorage: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => store.set(key, value),
      },
    },
  });
  try {
    const key = getAnalysisSetupStorageKey('dataset-17');
    store.set(key, JSON.stringify({
      confirmed: true,
      targetColumn: 'readmitted_30d',
      entityColumn: 'patient_id',
      splitColumn: '',
      timeColumn: 'admission_date',
      splitStrategy: 'none',
      splitRatio: 0.2,
      splitSeed: 42,
      splitOperation: null,
      confirmedAt: '2026-11-03T10:00:00Z',
    }));
    assert.equal(loadConfirmedAnalysisSetup('dataset-17')?.targetColumn, 'readmitted_30d');
    store.set(key, JSON.stringify({ confirmed: false, splitStrategy: 'none' }));
    assert.equal(loadConfirmedAnalysisSetup('dataset-17'), null);
    store.set(key, JSON.stringify({ confirmed: true, splitStrategy: 'automatic_magic' }));
    assert.equal(loadConfirmedAnalysisSetup('dataset-17'), null);
  } finally {
    if (originalWindow === undefined) {
      Reflect.deleteProperty(globalThis, 'window');
    } else {
      Object.defineProperty(globalThis, 'window', { configurable: true, value: originalWindow });
    }
  }
});
