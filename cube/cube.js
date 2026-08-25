const {
  catalogRepository,
  catalogVersion,
  enforceSecurityContext,
} = require('./lib/catalog-repository');

const appId = process.env.CUBEJS_APP_ID;
const orchestratorId = process.env.CUBEJS_ORCHESTRATOR_ID;
const preAggregationsSchema = process.env.CUBEJS_PRE_AGGREGATIONS_SCHEMA;

if (!appId || !orchestratorId || !preAggregationsSchema || !process.env.CUBEJS_API_SECRET) {
  throw new Error(
    'CUBEJS_APP_ID, CUBEJS_ORCHESTRATOR_ID, CUBEJS_PRE_AGGREGATIONS_SCHEMA, and CUBEJS_API_SECRET are required',
  );
}
if (!process.env.CUBEJS_DB_USER || !process.env.CUBEJS_DB_PASS) {
  throw new Error('A per-profile read-only CUBEJS_DB_USER and CUBEJS_DB_PASS are required');
}

module.exports = {
  contextToAppId: () => appId,
  contextToOrchestratorId: () => orchestratorId,
  preAggregationsSchema: () => preAggregationsSchema,
  repositoryFactory: catalogRepository,
  schemaVersion: catalogVersion,
  queryRewrite: enforceSecurityContext,
  scheduledRefreshContexts: async () => [
    {
      securityContext: {
        profile: process.env.ANALYTICS_PROFILE,
        role: 'admin',
        internalRefresh: true,
      },
    },
  ],
};
