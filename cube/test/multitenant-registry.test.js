'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const test = require('node:test');

const {
  namespace,
  profileConfig,
  refreshContexts,
  verifyToken,
} = require('../multitenant/registry');

const environment = {
  CLSENSE_REGION: 'asia',
  ANALYTICS_PROFILES: 'alpha_cls,beta_cls',
  CUBEJS_JWT_AUDIENCE: 'cube',
  ALPHA_CLS_ANALYTICS_DB_USER: 'alpha_reader',
  ALPHA_CLS_ANALYTICS_DB_PASSWORD: 'alpha-db-secret',
  ALPHA_CLS_CUBE_API_SECRET: 'alpha-jwt-secret',
  ALPHA_CLS_ANALYTICS_METADATA_URL: 'http://alpha/api/catalog',
  ALPHA_CLS_ANALYTICS_METADATA_SECRET: 'alpha-metadata-secret',
  BETA_CLS_ANALYTICS_DB_USER: 'beta_reader',
  BETA_CLS_ANALYTICS_DB_PASSWORD: 'beta-db-secret',
  BETA_CLS_CUBE_API_SECRET: 'beta-jwt-secret',
  BETA_CLS_ANALYTICS_METADATA_URL: 'http://beta/api/catalog',
  BETA_CLS_ANALYTICS_METADATA_SECRET: 'beta-metadata-secret',
};

function token(profile, secret, overrides = {}) {
  const now = 1_800_000_000;
  const encode = (value) => Buffer.from(JSON.stringify(value)).toString('base64url');
  const header = encode({ alg: 'HS256', typ: 'JWT' });
  const payload = encode({
    aud: 'cube', exp: now + 600, iat: now - 10, sub: `analytics:${profile}`,
    profile, role: 'viewer', ...overrides,
  });
  const signature = crypto.createHmac('sha256', secret).update(`${header}.${payload}`).digest('base64url');
  return `${header}.${payload}.${signature}`;
}

test('profiles keep database, metadata, and namespace identity separate', () => {
  const alpha = profileConfig('alpha_cls', environment);
  const beta = profileConfig('beta_cls', environment);
  assert.notEqual(alpha.databaseUser, beta.databaseUser);
  assert.notEqual(alpha.metadataUrl, beta.metadataUrl);
  assert.equal(namespace('alpha_cls', environment), 'clsense_asia_alpha_cls');
  assert.equal(namespace('beta_cls', environment), 'clsense_asia_beta_cls');
  assert.deepEqual(refreshContexts(environment).map((context) => context.securityContext.profile), ['alpha_cls', 'beta_cls']);
});

test('JWT validation rejects cross-profile, expired, forged, and unknown-profile tokens', () => {
  const now = 1_800_000_000;
  assert.equal(verifyToken(token('alpha_cls', 'alpha-jwt-secret'), environment, now).profile, 'alpha_cls');
  assert.throws(() => verifyToken(token('alpha_cls', 'beta-jwt-secret'), environment, now), /signature/);
  assert.throws(() => verifyToken(token('alpha_cls', 'alpha-jwt-secret', { exp: now }), environment, now), /expired/);
  assert.throws(() => verifyToken(token('unknown_cls', 'alpha-jwt-secret'), environment, now), /not enabled/);
  assert.throws(() => verifyToken(token('alpha_cls', 'alpha-jwt-secret', { securityContext: { profile: 'beta_cls' } }), environment, now), /security context/);
});
