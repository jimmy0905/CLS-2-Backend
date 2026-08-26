# Targeted pre-aggregation refresh contract

After an upload commits, FastAPI groups the affected reporting months into
contiguous date ranges and calls the private Cube API for that profile:

```http
POST /cubejs-api/v1/pre-aggregations/jobs
Authorization: <short-lived profile/refresh_worker Cube JWT>
Content-Type: application/json
```

```json
{
  "action": "post",
  "selector": {
    "contexts": [
      {
        "securityContext": {
          "profile": "wtchk_cls",
          "role": "refresh_worker"
        }
      }
    ],
    "timezones": ["UTC", "Asia/Hong_Kong"],
    "preAggregations": [
      "survey_responses.daily_core",
      "survey_responses.monthly_core",
      "survey_topics.daily_assignments",
      "survey_departments.daily_assignments",
      "survey_keywords.daily_assignments"
    ],
    "dateRange": ["2026-07-01", "2026-09-01"]
  }
}
```

`dateRange` selects only partitions whose build ranges intersect the supplied
range. The end date is the start of the month after the last affected month.
The deployment's `ANALYTICS_CUBE_REFRESH_TIME_ZONES` setting is applied to
both the scheduled refresh worker and upload-triggered refresh requests. It
must include every timezone that the dashboard is expected to serve; the
default is UTC plus `Asia/Hong_Kong`.
Published chart rollups whose semantic view is affected are appended from the
active catalog version; this is especially important for exact-dimension
non-additive rollups.
The caller records the request state on the upload. A rejected request is
visible as `analytics_refresh_status=failed` but does not fail the already
committed upload. Operators can poll returned job tokens through Cube's
`action: get` contract when diagnosing refresh latency.

Catalog publication is independent. It increments `catalogVersion`; Cube's
`schemaVersion` callback observes the new version within the five-second local
metadata cache and recompiles. Catalog version changes must never be used as a
substitute for refreshing data partitions.
