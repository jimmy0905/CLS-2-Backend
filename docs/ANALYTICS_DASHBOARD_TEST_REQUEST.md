# QA request: analytics dashboard migration validation

Please test the `wtchk_cls` analytics dashboard migration end to end. The goal
is to confirm that users can log in, discover valid filters, load the default
graph objects, and receive results equivalent to the legacy dashboard endpoints.

## Test flow

1. Open the `wtchk_cls` web application and log in with a valid viewer account.
2. Confirm that the authenticated session can access the governed analytics
   catalog and published charts.
3. Load the available filter values from the analytics filter-options API.
4. Apply filters individually and in combinations, then confirm that the
   available dependent options update correctly.
5. Open each dashboard graph listed below.
6. Capture the legacy endpoint response and the new chart/analytics response
   for the same filter and date context.
7. Compare totals, category labels, sentiment counts, averages, date buckets,
   empty values, and ordering.
8. Record screenshots or response payloads for every discrepancy.

## Dashboard coverage

| Dashboard | Default chart slug | Expected graph |
| --- | --- | --- |
| Sentiment distribution | `dashboard_sentiment_distribution` | Line graph by reported day |
| Store distribution | `dashboard_store_distribution` | Bar graph by store |
| Store-column distribution | `dashboard_store_format_distribution` | Bar graph by store format |
| Channel and delivery service | `dashboard_channel_delivery_distribution` | Bar graph by channel and delivery service |
| Topic sentiment score | `dashboard_topic_sentiment_counts`, `dashboard_overall_topic_sentiment_score`, `dashboard_mixed_topic_sentiment_score` | Sentiment count graph plus KPI tiles |
| Topic distribution | `dashboard_topic_distribution` | Bar graph by topic |
| Department distribution | `dashboard_department_distribution` | Bar graph by department |
| Keyword analysis | `dashboard_keyword_analysis` | Top-10 keyword bar graph |
| Data coverage | `dashboard_first_reported_at`, `dashboard_last_reported_at` | KPI tiles |
| Last updated date | `dashboard_last_updated_at` | KPI tile |

## Filter scenarios

Test the dashboards with the following cases:

- No filters: verify the default full-data result.
- One store selected by key and by name.
- Multiple stores selected.
- One store attribute selected, such as `region` or `store_format`.
- Channel and delivery service filters.
- Topic, department, and keyword filters on their matching dashboard grain.
- `POSITIVE`, `NEGATIVE`, `NEUTRAL`, and `MIXED` response sentiment filters.
- A bounded `from_date`/`to_date` range, including a date boundary.
- A non-UTC timezone, preferably `Asia/Hong_Kong`.
- Numeric score and CLS ranges.
- A filter combination that returns no matching survey rows.
- A master value with no matching survey rows, where zero-filled behavior is
  expected for stores, topics, and departments.

Do not apply a topic filter to a department or keyword assignment graph, or a
department filter to a topic or keyword graph. The governed API intentionally
keeps these assignment grains separate to prevent many-to-many row inflation.

## Comparison requirements

For each scenario, compare the old endpoint with the new graph data for the same
effective filter context:

- Response-level graphs must use `surveys.topic_sentiment` and compare positive,
  negative, neutral, and mixed counts plus average topic sentiment score.
- Topic, department, and keyword graphs must use the assignment sentiment from
  their respective assignment view.
- Daily results must compare the same local day buckets and timezone.
- Store results must compare store key, names, open/close dates, sentiment
  counts, score averages, and `total_count_for_option` support data.
- Topic and department results must include the same zero-filled master values.
- Keyword analysis must return the same top-10 ordering for the same filters.
- Data coverage must compare first and last non-deleted reported timestamps.
- Last updated date must document the active-survey freshness semantic used by
  the governed model.

Allow for the documented Cube freshness window. Record the returned
`freshness_time` and `model_version` with each new analytics response.

## Authentication and authorization checks

- A viewer can log in and read published catalog members and charts.
- An unauthenticated request is rejected.
- A viewer cannot access admin chart-management endpoints.
- The chart list contains only published viewer-visible charts.
- Analytics responses contain `Cache-Control: no-store, private`.

## Evidence to return

Please provide:

1. The test environment and build/image version.
2. The account role used for testing.
3. The filter values and timezone used for each scenario.
4. Legacy response payloads and new chart/analytics payloads, or screenshots
   when payload capture is not available.
5. A pass/fail result for every dashboard in the coverage table.
6. Any mismatch with the endpoint, chart slug, filter context, expected value,
   actual value, and whether it is caused by freshness, zero-fill behavior,
   response shaping, or a genuine calculation difference.

## Acceptance criteria

The migration passes when login and filter discovery work, every default chart
loads, all documented filter scenarios complete without unexpected errors, and
the new results match the legacy calculations after applying the documented
timezone, Cube freshness, assignment-grain, zero-fill, and
`total_count_for_option` rules.

## Reusable pytest runner

The live, repeatable version of this request is
`backend/tests/test_analytics_dashboard_e2e.py`. It is disabled during the
normal unit-test run and can be executed against any deployment that exposes
the application API:

Use `env.testing.example` as the template for the local VS Code/test
environment. Copy its values into the ignored `.env` file, then replace the
credential placeholders with the bootstrap credentials for the deployment.

```bash
ANALYTICS_E2E=1 \
ANALYTICS_E2E_BASE_URL=http://localhost:8000 \
ANALYTICS_E2E_USERNAME=<viewer-user> \
ANALYTICS_E2E_PASSWORD=<viewer-password> \
.venv/bin/python -m pytest -m analytics_e2e -v \
  --log-cli-level=INFO \
  backend/tests/test_analytics_dashboard_e2e.py
```

Use `ANALYTICS_E2E_TOKEN` instead of username/password when a test token is
already available. Set `ANALYTICS_E2E_API_PREFIX=/wtchk/api` when the API is
behind the profile path. The runner defaults to `Asia/Hong_Kong` and a broad
date range; override them with `ANALYTICS_E2E_TIMEZONE`,
`ANALYTICS_E2E_FROM_DATE`, and `ANALYTICS_E2E_TO_DATE`.

The runner logs one `analytics_e2e query_result` record for every HTTP request.
Each record includes the method, URL, status, request payload, and response
result. Secrets are redacted, and logged values are limited to 50,000 bytes by
default; set `ANALYTICS_E2E_LOG_MAX_BYTES` to change the limit.

VS Code Test Explorer loads the workspace `.env` and displays INFO logs using
the checked-in workspace settings. Add `ANALYTICS_E2E=1` to the local `.env`
before running these live tests from Test Explorer. When
`BOOTSTRAP_DEFAULT_ADMIN_USERNAME` and `BOOTSTRAP_DEFAULT_ADMIN_PASSWORD` are
present, the runner uses them automatically and expects the `admin` role;
`ANALYTICS_E2E_EXPECTED_ROLE` can override that expectation. A result shown as
`s` means the live suite was skipped and no HTTP query was made, so there is no
query-result log to display.
When the suite runs, look in VS Code's Python Test Log or integrated terminal;
the `Query Results` panel is a database-query extension and does not receive
these HTTP test logs.

Set `ANALYTICS_E2E_EXPECTED_ROLE=admin` when using the bootstrap administrator
credentials. The default role is `viewer`; chart-management access is expected
to return `403` for a viewer and `200` for an administrator.

Legacy calculation comparison is enabled with
`ANALYTICS_E2E_COMPARISON_MANIFEST=/path/to/cases.json` and optionally
`ANALYTICS_E2E_LEGACY_BASE_URL`. Each manifest case names a legacy request, a
published chart slug, and a `row_key_map` from new row keys to equivalent old
row keys. Rows are sorted before comparison so the test reports calculation
mismatches separately from ordering differences. The runner also validates
authentication, published chart/model-version consistency, filter discovery,
non-UTC bounded dates, numeric/no-match filters, assignment-grain isolation,
freshness metadata, and viewer/admin authorization.
