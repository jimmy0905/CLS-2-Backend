'use strict';

/*
 * Regional Cube profile registry.  This is deliberately environment-only:
 * deployment/generate.py emits the allow-list and one set of credentials per
 * selected profile, while this module ensures a request cannot select another
 * profile by merely changing a JWT claim.
 */
const crypto = require('crypto');

const PROFILE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/;
const ROLE = new Set(['viewer', 'admin', 'refresh_worker']);

function requireValue(value, name) {
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function profilePrefix(profile) {
  return profile.toUpperCase();
}

function selectedProfiles(environment = process.env) {
  // Keeping this one-profile fallback makes an existing developer Cube setup
  // usable during the migration.  Generated production bundles always set the
  // explicit allow-list and never rely on these legacy variables.
  const raw = environment.ANALYTICS_PROFILES || environment.ANALYTICS_PROFILE;
  requireValue(raw, 'ANALYTICS_PROFILES');
  const profiles = raw.split(',').map((item) => item.trim()).filter(Boolean);
  if (!profiles.length || new Set(profiles).size !== profiles.length || profiles.some((item) => !PROFILE.test(item))) {
    throw new Error('ANALYTICS_PROFILES must be a unique, comma-separated profile allow-list');
  }
  return profiles;
}

function profileConfig(profile, environment = process.env) {
  if (!selectedProfiles(environment).includes(profile)) {
    throw new Error('Cube profile is not enabled in this regional deployment');
  }
  const prefix = profilePrefix(profile);
  const legacy = !environment.ANALYTICS_PROFILES && environment.ANALYTICS_PROFILE === profile;
  return {
    profile,
    region: environment.CLSENSE_REGION || 'local',
    database: profile,
    databaseUser: environment[`${prefix}_ANALYTICS_DB_USER`] || (legacy && environment.CUBEJS_DB_USER),
    databasePassword: environment[`${prefix}_ANALYTICS_DB_PASSWORD`] || (legacy && environment.CUBEJS_DB_PASS),
    jwtSecret: environment[`${prefix}_CUBE_API_SECRET`] || (legacy && environment.CUBEJS_API_SECRET),
    metadataUrl: requireValue(environment[`${prefix}_ANALYTICS_METADATA_URL`] || (legacy && environment.ANALYTICS_METADATA_URL), `${prefix}_ANALYTICS_METADATA_URL`),
    metadataSecret: requireValue(environment[`${prefix}_ANALYTICS_METADATA_SECRET`] || (legacy && environment.ANALYTICS_METADATA_SECRET), `${prefix}_ANALYTICS_METADATA_SECRET`),
  };
}

function base64urlJson(value, label) {
  try {
    const decoded = Buffer.from(value, 'base64url').toString('utf8');
    return JSON.parse(decoded);
  } catch (_) {
    throw new Error(`Invalid Cube JWT ${label}`);
  }
}

function constantTimeEqual(left, right) {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

function audienceIncludes(audience, expected) {
  return audience === expected || (Array.isArray(audience) && audience.includes(expected));
}

function verifyToken(token, environment = process.env, now = Math.floor(Date.now() / 1000)) {
  if (typeof token !== 'string') throw new Error('Cube JWT is required');
  const parts = token.split('.');
  if (parts.length !== 3) throw new Error('Invalid Cube JWT');
  const header = base64urlJson(parts[0], 'header');
  const payload = base64urlJson(parts[1], 'payload');
  if (header.alg !== 'HS256' || header.typ !== 'JWT') throw new Error('Unsupported Cube JWT algorithm');
  const profile = payload.profile || payload.profile_id;
  if (typeof profile !== 'string' || !PROFILE.test(profile)) throw new Error('Cube JWT profile is invalid');
  const config = profileConfig(profile, environment);
  if (!Number.isSafeInteger(payload.exp) || payload.exp <= now) throw new Error('Cube JWT has expired');
  const expected = crypto.createHmac('sha256', requireValue(config.jwtSecret, `${profilePrefix(profile)}_CUBE_API_SECRET`)).update(`${parts[0]}.${parts[1]}`).digest('base64url');
  if (!constantTimeEqual(parts[2], expected)) throw new Error('Cube JWT signature is invalid');
  if (!audienceIncludes(payload.aud, environment.CUBEJS_JWT_AUDIENCE || 'cube')) throw new Error('Cube JWT audience is invalid');
  if (payload.nbf !== undefined && (!Number.isSafeInteger(payload.nbf) || payload.nbf > now)) throw new Error('Cube JWT is not active');
  if (!Number.isSafeInteger(payload.iat) || payload.iat > now + 60) throw new Error('Cube JWT issued-at time is invalid');
  if (payload.sub !== `analytics:${profile}`) throw new Error('Cube JWT subject is invalid');
  if (!ROLE.has(payload.role)) throw new Error('Cube JWT role is invalid');
  if (payload.securityContext && payload.securityContext.profile && payload.securityContext.profile !== profile) {
    throw new Error('Cube JWT security context profile is invalid');
  }
  return { ...payload, profile, securityContext: { ...(payload.securityContext || {}), profile, role: payload.role } };
}

async function checkAuth(req, auth) {
  const claims = verifyToken(auth);
  // Cube reads securityContext from the request after checkAuth.  Preserve the
  // validated claims (including profile/role) rather than trusting the token's
  // nested object directly.
  req.securityContext = claims;
  return claims;
}

function profileFromContext(context) {
  const securityContext = context && (context.securityContext || context);
  const profile = securityContext && (securityContext.profile || securityContext.profile_id);
  if (typeof profile !== 'string') {
    const enabled = selectedProfiles();
    if (enabled.length !== 1) throw new Error('Cube security context profile is required');
    return enabled[0];
  }
  profileConfig(profile);
  return profile;
}

function namespace(profile, environment = process.env) {
  const config = profileConfig(profile, environment);
  return `clsense_${config.region}_${profile}`;
}

function driverFactory({ securityContext } = {}) {
  const config = profileConfig(profileFromContext(securityContext));
  return {
    type: 'postgres',
    host: process.env.CUBEJS_DB_HOST,
    port: Number(process.env.CUBEJS_DB_PORT || '5432'),
    database: config.database,
    user: requireValue(config.databaseUser, `${profilePrefix(config.profile)}_ANALYTICS_DB_USER`),
    password: requireValue(config.databasePassword, `${profilePrefix(config.profile)}_ANALYTICS_DB_PASSWORD`),
    ssl: process.env.CUBEJS_DB_SSL === 'true',
  };
}

function refreshContexts(environment = process.env) {
  return selectedProfiles(environment).map((profile) => ({
    securityContext: { profile, role: 'refresh_worker', internalRefresh: true },
  }));
}

module.exports = {
  checkAuth,
  driverFactory,
  namespace,
  profileConfig,
  profileFromContext,
  refreshContexts,
  selectedProfiles,
  verifyToken,
};
