import assert from 'node:assert/strict';
import { test } from 'node:test';

import { formatDimensionRange } from './DatasetDetailPage';

test('image profile dimension ranges preserve missing bounds instead of inventing values', () => {
  assert.equal(formatDimensionRange(undefined, null), '—');
  assert.equal(formatDimensionRange(320, 640), '320–640');
  assert.equal(formatDimensionRange(320, undefined), '320–—');
});
