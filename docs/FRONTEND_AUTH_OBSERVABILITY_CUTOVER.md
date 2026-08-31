# Frontend authentication and observability cutover

Perform this procedure once per deployment profile during a maintenance window.
There is no dual-authentication mode.

1. Back up the profile backend database and record the current application releases.
2. Create `<profile>_frontend_auth` with the root repository's
   `postgresql/create-frontend-auth-database.sql` script and a profile-specific,
   least-privilege login.
3. In the frontend repository, set `AUTH_PROFILE`,
   `FRONTEND_AUTH_DATABASE_URL`, and `BACKEND_DATABASE_URL`, then run:

   ```bash
   npm run auth:admin -- migrate
   npm run auth:admin -- import-legacy
   ```

   The import is idempotent, preserves administrator UUIDs and Werkzeug hashes,
   verifies the imported count, and writes a SHA-256 count/checksum receipt to
   the backend database. A successful first login upgrades a Werkzeug hash to
   Argon2id.
4. Generate a dedicated key pair:

   ```bash
   openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out frontend-api-jwt.pem
   openssl pkey -in frontend-api-jwt.pem -pubout -out frontend-api-jwt.pub.pem
   ```

   Put the private PEM only in the matching frontend's
   `BACKEND_JWT_PRIVATE_KEY`. Put the public PEM in the matching backend
   `<PROFILE>_API_JWT_PUBLIC_KEY` variable.
5. Configure frontend-only Auth.js Entra variables and register exactly
   `<frontend-origin>/api/auth/callback/microsoft-entra-id` in the Entra app.
6. Pause traffic. Deploy the frontend and backend together. Alembic revision
   `0018_frontend_identity` verifies the import receipt before it snapshots
   historical actors and drops backend users/login records.
7. Verify an Entra viewer, a local administrator, an admin account mutation,
   one governed query/export, and a rejected cross-profile token.
8. Start the observability overlay and emit one successful request plus one
   synthetic error. Confirm both appear in `CLS/ECLS Backend Operations`.
9. Reopen traffic.

Rollback requires the pre-cutover backend database backup plus the previous
frontend and backend releases. Do not attempt to downgrade revision 0018.
