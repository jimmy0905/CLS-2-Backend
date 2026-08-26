# CLSense Backend

## Deployment profiles

The Docker Compose stack has one backend service per Nginx business-unit route. Services
are opt-in Compose profiles named `[bu_name]_[cls|ecls]`; only the selected profile starts.

The Nginx configuration provides 30 CLS profiles:

```
wtchk_cls wtctw_cls wtcmy_cls kvnl_cls sd_cls wtcsg_cls wwhk_cls pnshk_cls
ftrhk_cls wtcth_cls wtcid_cls wtcvn_cls wtccn_cls wtcph_cls drlv_cls drlt_cls
icibe_cls kvbe_cls tps_cls wtcua_cls wtctr_cls mat_cls mch_cls mcz_cls mfr_cls
mhu_cls mit_cls mro_cls msk_cls icinl_cls
```

It provides 31 ECLS profiles:

```
wtchk_ecls wtcph_ecls wtcmy_ecls ftrhk_ecls pnshk_ecls wwhk_ecls wtcth_ecls
wtcsg_ecls wtctw_ecls wtcvn_ecls wtccn_ecls wtcid_ecls sd_ecls drlv_ecls
drlt_ecls icibe_ecls icinl_ecls kvnl_ecls kvbe_ecls mat_ecls mch_ecls mcz_ecls
mfr_ecls mhu_ecls mit_ecls mro_ecls msk_ecls tps_ecls wtctr_ecls wtcua_ecls
svruk_ecls
```

Every profile preserves the API port defined in Nginx and has its own upload volume.
For example, `wtchk_cls` listens on host port 8000 and `wtchk_ecls` listens on
8003. The full mapping is the source of truth in [docker-compose.yml](docker-compose.yml).

### Configuration boundaries

Copy [`.env.example`](.env.example) to `.env` and fill in the shared credentials
and integration settings. For every profile you deploy, create
`deploy/profile/<profile>.env` and copy only its matching block from
[`deploy/profile.env.example`](deploy/profile.env.example). The external
`connex_network` must already contain the `postgres` service.
The legacy misspelled `env.exmaple` remains as a compatibility template; use
`.env.example` for new deployments.

Compose uses the specified `--env-file` values only to interpolate an explicit
environment allowlist. It does not inject either file wholesale into containers,
so one profile's Azure OAuth credentials or analysis-feedback endpoint are never
present in another profile's container.

The following non-secret values are service-local configuration in
[`docker-compose.yml`](docker-compose.yml), rather than values loaded from
`.env`. They are isolated per profile:

| Configuration | Why it is isolated |
| --- | --- |
| `DATABASE_NAME` | Each service uses its own `[bu]_[cls|ecls]` database. |
| `FASTAPI_ROOT_PATH` | Matches the Nginx API route, such as `/wtchk/api` or `/ecls/wtchk/api`. |
| `IS_ECLS_ENABLED` | Selects CLS or ECLS processing behaviour. |
| `DEPLOYMENT_PROFILE`, `LOG_SERVICE_NAME` | Keeps logs and diagnostics attributable to one deployment. |
| `FRONTEND_URL`, `AZURE_REDIRECT_URI` | Compose derives these per-profile paths from shared `PUBLIC_BASE_URL`. |
| Azure AD OAuth credentials | Each service receives its own tenant, client ID, and client secret from its namespaced ignored profile environment file. |
| `ANALYZE_FEEDBACK_API_URL` | Each service receives its own analysis-feedback endpoint from its namespaced ignored profile environment file. |
| `ANALYZE_FEEDBACK_IS_INCLUDE_CHANNEL`, `SURVEY_EXPORT_COLUMN_*` | Each profile has its own Compose values, initially `false`; edit that profile's service block to enable a feature. |

Azure AD OAuth credentials and analysis-feedback endpoints are profile-specific
settings stored only in `deploy/profile/<profile>.env`, which is ignored by
Git. Copy the needed profile block from
[`deploy/profile.env.example`](deploy/profile.env.example) into that file.
For example, `wtchk_cls` consumes only
`WTCHK_CLS_AZURE_TENANT_ID`, `WTCHK_CLS_AZURE_CLIENT_ID`,
`WTCHK_CLS_AZURE_CLIENT_SECRET`, and
`WTCHK_CLS_ANALYZE_FEEDBACK_API_URL`. Generic Azure OAuth and
`ANALYZE_FEEDBACK_API_URL` values are deliberately overridden inside every
service, preventing cross-profile inheritance.

Analysis-feedback channel inclusion and every survey-export column flag are
version-controlled, profile-specific settings in `docker-compose.yml`. They
are no longer read from `.env`; modify only the target profile's service block.

### Start a profile

You must provide the profile name, its profile-specific environment file, and
the shared `.env` file. For example, to start `wtchk_cls`:

```bash
docker compose \
  --profile wtchk_cls \
  --env-file ./deploy/profile/wtchk_cls.env \
  --env-file ./.env \
  up -d --build
```

Keep shared values only in `.env` and do not repeat a variable in both files;
when a variable is present in both, the later `--env-file` takes precedence.

To start several isolated BUs, name every profile and supply each corresponding
profile environment file:

```bash
docker compose \
  --profile wtchk_cls \
  --profile wtchk_ecls \
  --env-file ./deploy/profile/wtchk_cls.env \
  --env-file ./deploy/profile/wtchk_ecls.env \
  --env-file ./.env \
  up -d --build
```

The shared `PUBLIC_BASE_URL` defaults to `http://localhost:3000` for local use. Set it
to the public Nginx origin in `.env` before enabling Azure OAuth, so the generated
per-profile redirect URI is registered with Azure.

## Observability and data retention

Server logs are structured JSON on stdout, suitable for Docker or a centralized log
collector. Each request emits a completion record with UTC timestamp, service,
profile, request ID, method, path, status, duration, and client IP. The request ID
is also returned in `X-Request-ID`; query strings and credentials are never logged
by the request middleware. Unexpected errors include a stack trace.

Docker limits its local JSON log files to ten 10 MiB files per service. For an
additional daily rotating application log, configure `SERVER_LOG_FILE` only when a
writable log mount is supplied; Compose otherwise uses a read-only application
filesystem by design.

`DATA_RETENTION_DAYS=30` is the default and is configured in `.env.example`.
Retention runs after startup and every `RETENTION_CHECK_INTERVAL_SECONDS`
(default 86400). It purges only operational data older than the cutoff:

- login records;
- completed or failed upload tasks and their error rows;
- rotated application log files when `SERVER_LOG_FILE` is configured.

It never deletes surveys, users, stores, departments, topics, delivery services, or
other business data.

## Database migrations

Startup applies committed Alembic migrations when `DATABASE_AUTO_MIGRATE=true`.
Automatic migration generation is disabled by default and is forcibly disabled in
Compose, so production containers never modify the checked-out migration source.

Create and review schema changes manually from the backend directory:

```bash
cd backend
alembic revision --autogenerate -m "describe schema change"
alembic upgrade head
```

`DATABASE_BOOTSTRAP_SCHEMA=true` enables the legacy SQLAlchemy `create_all()`
bootstrap path for a local empty database. Fresh databases do not create an admin
unless `BOOTSTRAP_DEFAULT_ADMIN=true` and a non-empty
`BOOTSTRAP_DEFAULT_ADMIN_PASSWORD` are configured.
