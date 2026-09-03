'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const {
  preAggregationExternalRefresh,
  scheduledRefreshTimer,
} = require('../lib/refresh-config');

test('refresh worker checks scheduled refreshes every 30 seconds by default', () => {
  assert.equal(scheduledRefreshTimer({ CUBEJS_REFRESH_WORKER: 'true' }), 30);
});

test('API nodes never run the scheduled refresh timer', () => {
  assert.equal(scheduledRefreshTimer({ CUBEJS_REFRESH_WORKER: 'false' }), false);
});

test('refresh interval accepts positive whole seconds only', () => {
  assert.equal(scheduledRefreshTimer({
    CUBEJS_REFRESH_WORKER: 'true',
    ANALYTICS_SCHEDULED_REFRESH_INTERVAL_SECONDS: '45',
  }), 45);
  assert.throws(
    () => scheduledRefreshTimer({
      CUBEJS_REFRESH_WORKER: 'true',
      ANALYTICS_SCHEDULED_REFRESH_INTERVAL_SECONDS: '0',
    }),
    /positive whole number/,
  );
  assert.throws(
    () => scheduledRefreshTimer({
      CUBEJS_REFRESH_WORKER: 'true',
      ANALYTICS_SCHEDULED_REFRESH_INTERVAL_SECONDS: '30.5',
    }),
    /positive whole number/,
  );
});

test('API nodes use only refresh-worker-built pre-aggregations by default', () => {
  assert.equal(preAggregationExternalRefresh({
    CUBEJS_REFRESH_WORKER: 'false',
  }), true);
});

test('local API fallback permits on-demand pre-aggregation builds', () => {
  assert.equal(preAggregationExternalRefresh({
    CUBEJS_REFRESH_WORKER: 'false',
    ANALYTICS_API_PRE_AGGREGATION_FALLBACK: 'true',
  }), false);
});

test('refresh workers always build pre-aggregations', () => {
  assert.equal(preAggregationExternalRefresh({
    CUBEJS_REFRESH_WORKER: 'true',
  }), false);
});

test('API fallback accepts true or false only', () => {
  assert.throws(
    () => preAggregationExternalRefresh({
      CUBEJS_REFRESH_WORKER: 'false',
      ANALYTICS_API_PRE_AGGREGATION_FALLBACK: 'yes',
    }),
    /must be true or false/,
  );
});
