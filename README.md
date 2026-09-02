# CLSense backend

The backend image is profile-neutral.  The regional deployment generator in
the superproject assigns its database, API base path, bearer token, logging
identity, and profile-specific Cube HMAC secret at runtime.  It is never built
by production Compose.

Production migrations run once per selected profile through:

```sh
python -m infrastructure.database.migrate
```

The running API uses `DATABASE_AUTO_MIGRATE=false`.  Deploy only
backward-compatible expand/contract migrations: regional image rollback does
not downgrade PostgreSQL.

The generic read-only analytics role helper is
[`scripts/provision_analytics_readonly.sql`](scripts/provision_analytics_readonly.sql).
Regional bundles invoke the equivalent non-interactive provisioning job after
migrations; the legacy `wtchk_cls`-only role procedure must not be used for
new deployments.
