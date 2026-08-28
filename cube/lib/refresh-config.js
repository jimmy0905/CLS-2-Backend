'use strict';

function scheduledRefreshTimer(environment = process.env) {
  if (environment.CUBEJS_REFRESH_WORKER !== 'true') return false;

  const raw = environment.ANALYTICS_SCHEDULED_REFRESH_INTERVAL_SECONDS || '30';
  if (!/^[1-9][0-9]*$/.test(raw)) {
    throw new Error(
      'ANALYTICS_SCHEDULED_REFRESH_INTERVAL_SECONDS must be a positive whole number',
    );
  }
  return Number(raw);
}

module.exports = { scheduledRefreshTimer };
