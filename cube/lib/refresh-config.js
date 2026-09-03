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

function preAggregationExternalRefresh(environment = process.env) {
  // A refresh worker must always be able to build pre-aggregations.
  if (environment.CUBEJS_REFRESH_WORKER === 'true') return false;

  const raw = environment.ANALYTICS_API_PRE_AGGREGATION_FALLBACK || 'false';
  if (raw !== 'true' && raw !== 'false') {
    throw new Error(
      'ANALYTICS_API_PRE_AGGREGATION_FALLBACK must be true or false',
    );
  }

  // externalRefresh=true makes an API node consume only partitions built by
  // the dedicated refresh worker. Local development opts into an on-demand
  // fallback so a catalog/schema change cannot strand queries indefinitely.
  return raw !== 'true';
}

module.exports = { preAggregationExternalRefresh, scheduledRefreshTimer };
