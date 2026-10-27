import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import {
  getCurrentUserApi,
  getDashboardSummary,
  getNotifications,
  loginApi,
  markNotificationRead,
  registerApi,
} from './api';

const originalFetch = globalThis.fetch;
const originalDocument = globalThis.document;

afterEach(() => {
  globalThis.fetch = originalFetch;
  Object.defineProperty(globalThis, 'document', {
    configurable: true,
    value: originalDocument,
  });
});

test('login and registration use credentialed backend requests and never persist credentials locally', async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = async (input, init) => {
    requests.push({ url: String(input), init });
    return new Response(JSON.stringify({
      user: { id: 'user-1', email: 'person@example.test', display_name: 'Person', created_at: '2026-01-01T00:00:00Z' },
      csrf_token: 'csrf-value',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  await loginApi('person@example.test', 'private-password');
  await registerApi('Person', 'person@example.test', 'private-password');
  assert.equal(requests.length, 2);
  assert.ok(requests.every(({ init }) => init?.credentials === 'include'));
  assert.match(requests[0].url, /\/auth\/login$/);
  assert.match(requests[1].url, /\/auth\/register$/);
  assert.equal((requests[1].init?.body as string).includes('private-password'), true);
});

test('unsafe authenticated API requests attach the readable CSRF cookie as a header', async () => {
  Object.defineProperty(globalThis, 'document', {
    configurable: true,
    value: { cookie: 'dlg_csrf=csrf-cookie-value' },
  });
  let request: RequestInit | undefined;
  globalThis.fetch = async (_input, init) => {
    request = init;
    return new Response(JSON.stringify({ id: 'n-1' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  await markNotificationRead('n-1');
  assert.equal(new Headers(request?.headers).get('X-CSRF-Token'), 'csrf-cookie-value');
  assert.equal(request?.credentials, 'include');
});

test('current-user 401 is an unauthenticated state, while dashboard and notifications map persisted data', async () => {
  let calls = 0;
  globalThis.fetch = async (input) => {
    calls += 1;
    const url = String(input);
    if (url.endsWith('/auth/me')) return new Response('', { status: 401 });
    if (url.endsWith('/dashboard/summary')) {
      return new Response(JSON.stringify({
        dataset_count: 2,
        finding_count: 3,
        open_finding_count: 1,
        high_or_critical_finding_count: 1,
        latest_analysis_at: null,
        recent_datasets: [],
        recent_operations: [],
        models: { available: false, reason: 'No model registry' },
        reports: { available: false, reason: 'No report registry' },
      }), { status: 200 });
    }
    return new Response(JSON.stringify([{
      id: 'notification-1',
      event_type: 'analysis',
      title: 'Analysis completed',
      message: 'Saved',
      created_at: '2026-01-01T00:00:00Z',
      read_at: null,
      dataset_id: null,
      finding_id: null,
      operation_id: null,
    }]), { status: 200 });
  };
  assert.equal(await getCurrentUserApi(), null);
  const summary = await getDashboardSummary();
  assert.equal(summary.datasetCount, 2);
  const notifications = await getNotifications();
  assert.equal(notifications[0].eventType, 'analysis');
  assert.equal(calls, 3);
});
