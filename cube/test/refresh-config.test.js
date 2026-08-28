'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { scheduledRefreshTimer } = require('../lib/refresh-config');

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
