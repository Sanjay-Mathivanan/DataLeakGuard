import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { DatasetHistoryTimeline, getHistoryStatusClass } from './DatasetHistoryTimeline';

test('audit timeline status style does not label failed operation as successful', () => {
  assert.match(getHistoryStatusClass('failed'), /rose/);
  assert.match(getHistoryStatusClass('completed'), /emerald/);
  assert.match(getHistoryStatusClass('running'), /sky/);
});

test('audit timeline exposes persisted activity filters and loading state', () => {
  const markup = renderToStaticMarkup(
    React.createElement(DatasetHistoryTimeline, { datasetId: 'dataset-12' })
  );
  assert.match(markup, /All activity types/);
  assert.match(markup, /All statuses/);
  assert.match(markup, /History start date/);
  assert.match(markup, /History end date/);
  assert.match(markup, /Loading persisted activity/);
});
