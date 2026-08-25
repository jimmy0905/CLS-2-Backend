# `wtchk_cls` Docker Startup Tutorial

This guide starts the CLSense backend and Cube analytics services for the
`wtchk_cls` deployment profile.

> The Compose profile is `wtchk_cls` with an underscore. Docker service names,
> such as `backend-wtchk-cls`, use hyphens.

## 1. Prerequisites

Install Docker with the Compose plugin, then run all commands from the repository
root:

```bash
cd /path/to/CLSense-Backend
docker version
docker compose version
```

The deployment expects:

- a populated root `.env` containing shared backend database and security
  configuration;
- BU-specific Azure OAuth and feedback settings in
  `deploy/profile/wtchk_cls.env`;
- an existing `connex_network` Docker network;
- PostgreSQL reachable as `postgres:5432` on that network;
- an existing `wtchk_cls` database;
- a dedicated read-only PostgreSQL role for Cube;
- tested Cube and Cube Store `v1.7.26` image digests.

Check the external network:

```bash
docker network inspect connex_network
```

If this is a new local environment and the network does not exist, create it:

```bash
docker network create connex_network
```

## 2. Configure the BU and analytics profile

Create the ignored profile environment file. Do not overwrite an existing file
that may already contain deployment secrets. The focused BU application
template is [`deploy/bu.env.example`](bu.env.example), the complete profile
catalog is [`deploy/profile.env.example`](profile.env.example), and the Cube
variable template is [`deploy/analytics.env.example`](analytics.env.example).
The BU and Cube settings belong in the same `deploy/profile/wtchk_cls.env` file.

```bash
cp deploy/analytics.env.example deploy/profile/wtchk_cls.env
```

Add the `wtchk_cls` BU application settings:

```dotenv
WTCHK_CLS_AZURE_CLIENT_ID=
WTCHK_CLS_AZURE_CLIENT_SECRET=
WTCHK_CLS_AZURE_TENANT_ID=
WTCHK_CLS_ANALYZE_FEEDBACK_API_URL=
```

The host-side names must include the `WTCHK_CLS_` prefix. Compose maps the
first three values to `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, and
`AZURE_TENANT_ID` inside `backend-wtchk-cls`. Generic host-side Azure names are
intentionally not used because they could leak credentials between BU
profiles.

Then set the Cube analytics values in the same file:

```dotenv
CUBE_IMAGE_DIGEST=sha256:51d467b223492da5c35139c31760c5329e770028bbe6cb4faa590400e5445941
CUBESTORE_IMAGE_DIGEST=sha256:038d4491cd77799a440655053f8f67ea16d3d2ecceffe812d314e47993f1ce08
CUBESTORE_PLATFORM=linux/amd64

ANALYTICS_DATABASE_PORT=5432
# Local Docker PostgreSQL does not enable SSL. Set true only for an SSL-enabled
# external PostgreSQL server.
ANALYTICS_DATABASE_SSL=false

WTCHK_CLS_ANALYTICS_ENABLED=false
WTCHK_CLS_ANALYTICS_DB_USER=<read-only-postgres-user>
WTCHK_CLS_ANALYTICS_DB_PASSWORD=<password>
WTCHK_CLS_CUBE_API_SECRET=<unique-random-secret-at-least-32-bytes>
WTCHK_CLS_ANALYTICS_METADATA_SECRET=<different-random-secret-at-least-32-bytes>
```

Keep `WTCHK_CLS_ANALYTICS_ENABLED=false` for the initial shadow-validation
period. The internal signed metadata endpoint remains available to Cube while
interactive analytics APIs stay disabled.

The Cube database role must have only the required `CONNECT`, schema `USAGE`,
and reporting `SELECT` permissions. It must not own the database or schema.

## 3. Validate before startup

Validate the profile-specific analytics settings:

```bash
python3 scripts/validate_analytics_infra.py \
  --env-file deploy/profile/wtchk_cls.env \
  --profile wtchk_cls
```

Validate the merged Compose configuration:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  config --quiet
```

The command intentionally fails when image digests or mandatory credentials are
missing.

## 4. Start the backend only

For the existing backend without Cube analytics:

```bash
docker compose \
  -f docker-compose.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  up -d --build backend-wtchk-cls
```

The backend is published on host port `8000`.

### Provision the Cube read-only database role

Allow the backend migration to finish before this step so the governed analytics
views and helper functions exist. First, log in with `psql` as a PostgreSQL
administrator connected to `wtchk_cls`:

```bash
psql \
  --host <postgres-host> \
  --username postgres \
  --dbname wtchk_cls
```

Then run the provisioning file from the `psql` prompt:

```text
\i scripts/provision_wtchk_cls_analytics_readonly.sql
```

The SQL performs a preflight check and stops before changing the role if the
database has not reached analytics migration `0009_cube_semantic_catalog`.

The ready prompt normally ends in `=#`, for example `wtchk_cls=#`. A prompt
ending in `-#` means an earlier SQL statement is unfinished. The provisioning
file clears that stale query buffer automatically; you can also clear it
manually with `\r` before running `\i`.

The script creates or reconciles `wtchk_cls_analytics` and securely prompts for
its password. Enter the same value configured as
`WTCHK_CLS_ANALYTICS_DB_PASSWORD`. It removes direct table and sequence grants,
then grants only database `CONNECT`, schema `USAGE`, analytics-view `SELECT`,
and analytics helper-function `EXECUTE`. Re-running it also rotates the role's
password through the secure `psql` prompt.

## 5. Start the complete analytics stack

Start the backend, Cube API, refresh worker, and assigned Cube Store shard:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  up -d --build
```

The profile starts these primary services:

- `backend-wtchk-cls`;
- `cube-api-wtchk-cls`;
- `cube-refresh-wtchk-cls`;
- `cubestore-router-shard-4`;
- `cubestore-worker-1-shard-4`;
- `cubestore-worker-2-shard-4`.

Cube and Cube Store intentionally publish no host ports.

## 6. Check service health

Show service status:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  ps
```

Check the backend directly:

```bash
curl --fail http://localhost:8000/health
```

Check Cube from inside its private container network:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  exec cube-api-wtchk-cls \
  node -e "fetch('http://127.0.0.1:4000/readyz').then(async response => { console.log(response.status, await response.text()); process.exit(response.ok ? 0 : 1); }).catch(error => { console.error(error); process.exit(1); })"
```

## 7. Inspect logs

Follow the main profile logs:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  logs -f --tail=200 \
  backend-wtchk-cls \
  cube-api-wtchk-cls \
  cube-refresh-wtchk-cls \
  cubestore-router-shard-4
```

## 8. Enable interactive analytics

After migrations, metadata compilation, and shadow comparisons are healthy,
change the profile setting to:

```dotenv
WTCHK_CLS_ANALYTICS_ENABLED=true
```

Recreate the backend so it receives the new flag:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  up -d --no-deps --force-recreate backend-wtchk-cls
```

Rollback is the reverse: set the flag to `false` and recreate the backend. This
does not affect the existing survey, upload, dashboard, or health APIs.

## 9. Stop the profile

Stop only the profile-specific backend and Cube processes:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  stop backend-wtchk-cls cube-api-wtchk-cls cube-refresh-wtchk-cls
```

Shard 4 is shared with other deployment profiles. Stop its router and workers
only when no other shard-4 profile is running.

For an isolated local project where no other profile is running, remove the
whole Compose deployment while retaining named volumes:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  down
```

Do not add `--volumes` unless deleting Cube Store and upload-task data is
intentional.

## Troubleshooting

### Compose reports a missing image digest

Set both `CUBE_IMAGE_DIGEST` and `CUBESTORE_IMAGE_DIGEST` to architecture-tested
`v1.7.26` manifest digests. Tags alone are intentionally rejected.

### ARM64 reports `no matching manifest` for Cube Store

Cube itself has a native ARM64 manifest, but Cube Store v1.7.26 publishes only
`linux/amd64`. Keep `CUBESTORE_PLATFORM=linux/amd64`; Docker Desktop on an ARM64
machine will run Cube Store through emulation. Use an AMD64 host for production
and performance/load acceptance because emulation changes latency and capacity.

### `connex_network` is missing

Create it with `docker network create connex_network`, or start the shared
infrastructure stack that normally owns it.

### Cube cannot connect to PostgreSQL

Confirm that `postgres` is connected to `connex_network`, the `wtchk_cls`
database exists, SSL settings match the server, and the analytics database role
has the required read-only grants.

### Analytics endpoints return 404

This is expected while `WTCHK_CLS_ANALYTICS_ENABLED=false`. Enable the flag only
after shadow validation succeeds.

### Cube metadata compilation fails

Confirm that the API and metadata secrets are non-empty, different, at least 32
random bytes, and match between the backend and Cube services. Then inspect the
backend and `cube-api-wtchk-cls` logs together.
