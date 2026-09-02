const {
  catalogRepository,
  catalogVersion,
  contextToApiScopes,
  enforceSecurityContext,
} = require('./lib/catalog-repository');
const { scheduledRefreshTimer } = require('./lib/refresh-config');
const {
  checkAuth,
  driverFactory,
  namespace,
  profileFromContext,
  refreshContexts,
  selectedProfiles,
} = require('./multitenant/registry');

if (!process.env.CUBEJS_API_SECRET) {
  throw new Error(
    'CUBEJS_API_SECRET is required',
  );
}
selectedProfiles();

module.exports = {
  checkAuth,
  driverFactory,
  contextToAppId: ({ securityContext } = {}) => namespace(profileFromContext(securityContext)),
  contextToOrchestratorId: ({ securityContext } = {}) => namespace(profileFromContext(securityContext)),
  preAggregationsSchema: ({ securityContext } = {}) => namespace(profileFromContext(securityContext)),
  repositoryFactory: catalogRepository,
  schemaVersion: catalogVersion,
  queryRewrite: enforceSecurityContext,
  contextToApiScopes,
  scheduledRefreshTimer: scheduledRefreshTimer(),
  scheduledRefreshContexts: async () => refreshContexts(),
};
