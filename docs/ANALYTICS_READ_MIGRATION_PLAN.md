# Analytics Read Migration and Legacy Feature Removal

Use a two-stage migration. Stage one adds governed analytics record-query parity,
protects data mutations with the admin role, and removes the explicitly retired
action/log/classification APIs and data. Stage two removes legacy read endpoints
only after clients have migrated and analytics is enabled in every profile.

Governed analytics semantics remain authoritative: soft-deleted surveys stay
excluded, assignment grains remain separate, and Cube freshness is accepted.
Survey record responses retain the legacy `sentiment` field alongside canonical
`topic_sentiment` for compatibility.

## Step 1 — Add governed analytics record queries and exports

- Add `POST /analytics/records/query` for `surveys`, `stores`, `departments`,
  `channels`, `delivery_services`, and `topics`.
- Accept up to 20 typed allowlisted filters, up to three allowlisted order fields,
  page/size, and optional timezone. Survey pages are capped at 100 and default to
  `reported_at DESC, id DESC`; master-data pages are capped at 1,000 and default
  to `id ASC`.
- Return resource-specific paginated items. Survey items preserve the current
  nested store, channel, delivery-service, department, topic, and keyword objects,
  including both legacy and canonical sentiment fields.
- Execute record queries against the live database, exclude deleted surveys, and
  implement assignment filters with `EXISTS` predicates to avoid duplicate rows.
- Extend `POST /analytics/exports` with a mutually exclusive survey
  `record_query` input while retaining ownership, configured columns, formula
  escaping, expiry, and the 250,000-row cap.

## Step 2 — Complete dashboard analytics parity

- Add built-in `first_reported_at`, `last_reported_at`, and `last_updated_at`
  metrics to the Python semantic catalog, Cube whitelist, and core survey model.
- Verify each `/dashboard/*` replacement body in the dashboard migration guide.
- Use `/analytics/query` for aggregates, `/analytics/filter-options` without the
  selected-field filter for `total_count_for_option`, and
  `/analytics/records/query` for unused stores, departments, and topics that need
  zero-filled rows.
- Keep cross-assignment aggregate filters unsupported and document the governed
  grain and freshness differences.

## Step 3 — Enforce admin mutations and remove retired action/log features

- Require `require_admin` for survey, channel, delivery-service, and topic POST,
  PUT, and DELETE routes without restricting transitional GET routes.
- Remove `POST /surveys/extract-total` and only its route-specific DTOs/imports;
  preserve extraction helpers used by ingestion.
- Remove the complete `/actions` and `/user-behavior-logs` routers, action/email
  LLM and SMTP utilities, action/email Pydantic types, obsolete mail dependencies
  and example configuration, app registrations, retention hooks, and docs.
- Remove the `Action`, `GeneratedEmail`, and `EmailRecord` models and User
  relationships.
- Add Alembic revision `0010` dropping `actions`, `generated_emails`, and
  `email_records`. Downgrade recreates empty schemas but cannot recover rows.

## Step 4 — Validate stage-one behavior and migrate clients

- Test record filters, ordering, pagination, timezones, nested responses, legacy
  sentiment, unused master values, assignment filtering, and deleted-row exclusion.
- Test viewer/admin authorization, analytics feature gating, no-store headers,
  exports, dashboard parity, removed OpenAPI paths, migration metadata, and
  retention cleanup. Run the complete backend pytest and Cube test suites.
- Publish the query book and migrate clients to analytics. Enable analytics in
  every deployment profile, then observe request logs until no legacy read routes
  are called for seven consecutive days.

## Step 5 — Remove migrated legacy read routes

- After the stage-one acceptance gate, remove all `/dashboard/*` routes.
- Remove `GET /surveys`, `GET /surveys/{survey_id}`, and
  `GET /surveys/download`.
- Remove GET list/detail routes under `/channels`, `/delivery_services`, and
  `/topics`, while retaining their admin-only mutation routes.
- Update OpenAPI and migration documentation and rerun parity, authorization,
  backend, and Cube regression tests.

## Assumptions

- Dropping the three operational-history tables is intentional and requires no
  archive. A downgrade restores schemas only.
- Analytics preserves business content rather than legacy response envelopes.
- Existing uncommitted timezone and analytics changes are user-owned and must be
  merged without being overwritten.
