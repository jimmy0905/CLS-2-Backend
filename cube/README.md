# CLSense regional multi-tenant Cube

Production Cube topology and profile selection are generated only from the
superproject's [`deployment/catalog.json`](../../deployment/catalog.json) and
a regional server manifest.  Do not add a Compose service here.

One regional Cube API and one refresh worker serve the one-to-three profiles
selected for that server.  `multitenant/registry.js` performs the security
boundary: it allow-lists the profile, verifies that profile's HS256 JWT,
audience, expiry, subject and role, then chooses only that profile's database,
metadata endpoint and secret.  It namespaces Cube app IDs, orchestrators and
pre-aggregation schemas as `clsense_<region>_<profile>`.

`lib/catalog-repository.js` caches metadata by profile.  Never make its cache
global again: a cache hit for a different profile is a data isolation failure.
The generated refresh worker contexts enumerate only manifest-selected
profiles.  Cube availability affects analytics features only; the backend must
continue serving health checks, surveys, uploads, and administration.

Run the focused contract tests from this directory:

```sh
node --test test/*.test.js
```
