# Frontend authentication and observability cutover

Perform this procedure once per deployment profile during a maintenance window.
There is no dual-authentication mode.

1. Back up the profile backend database and record the current application releases.
2. Create `<profile>_frontend` with the root repository's
   `postgresql/create-frontend-database.sql` script and a profile-specific,
   least-privilege login.
3. In the frontend repository, configure the matching profile file with
   `DATABASE_URL` and `BACKEND_DATABASE_URL`, then run:

   ```bash
   npm run db:profile -- wtchk_cls migrate
   npm run auth:profile -- wtchk_cls import-legacy
   ```

   The import is idempotent, preserves administrator UUIDs and Werkzeug hashes,
   verifies the imported count, and writes a SHA-256 count/checksum receipt to
   the backend database. A successful first login upgrades a Werkzeug hash to
   Argon2id.
4. Generate two independent 256-bit values: one for Auth.js sessions and one
   static API bearer token shared only by the matching frontend BFF and backend:

   ```bash
   openssl rand -base64 32
   ```

   Store one generated value as the frontend-only `<PROFILE>_AUTH_SECRET`.
   Generate a second value and store that *same exact value* as
   `<PROFILE>_BACKEND_API_TOKEN` in the frontend and backend profile files.
5. Configure the matching frontend Compose profile and its frontend-only
   Auth.js/Entra variables. Set `AUTH_ORIGIN` to the external scheme and host,
   keep `AUTH_URL` unset, and register exactly
   `<AUTH_ORIGIN><profile-base-path>/api/auth/callback/microsoft-entra-id`
   (for example `<frontend-origin>/wtchk/web/api/auth/callback/microsoft-entra-id`)
   in the Entra app.
6. Pause traffic. Deploy the frontend and backend together. Alembic revision
   `0018_frontend_identity` verifies the import receipt before it snapshots
   historical actors and drops backend users/login records.
7. Verify one authenticated frontend session, one bearer-protected admin-path
   mutation, one governed query/export, and rejection of a missing or wrong
   bearer. The backend no longer evaluates actor headers or user roles.
8. Start the observability overlay and emit one successful request plus one
   synthetic error. Confirm both appear in `CLS/ECLS Backend Operations`.
9. Reopen traffic.

Rollback requires the pre-cutover backend database backup plus the previous
frontend and backend releases. Do not attempt to downgrade revision 0018.
