# Analytics API reference

This document describes the governed Cube analytics API. It covers the analytics routes only; existing `/dashboard/*`, survey, upload, and authentication routes are unchanged.

For an endpoint-by-endpoint replacement guide and ready-to-send bodies for the
current dashboard cards, see [Dashboard analytics migration](DASHBOARD_ANALYTICS_MIGRATION.md).
For the frontend call order, availability checks, filter discovery, and chart
loading loop, see
[Frontend dashboard analytics workflow](FRONTEND_DASHBOARD_ANALYTICS_WORKFLOW.md).

## Base URL, access, and common behaviour

The paths below are FastAPI paths. In the `wtchk_cls` deployment, the external API is normally served under:

```text
https://<api-host>/wtchk/api
```

For example, `GET /analytics/catalog` is requested as:

```text
GET https://<api-host>/wtchk/api/analytics/catalog
Authorization: Bearer <access-token>
```

All viewer and administrator analytics endpoints require a normal application access token. They return `404` while `ANALYTICS_ENABLED=false`; this lets a BU compile Cube metadata in shadow mode without exposing analytics to users. The API sends `Cache-Control: no-store, private` for analytics responses.

Roles are enforced at the API boundary:

| Caller | Access |
| --- | --- |
| Viewer | Published, viewer-visible catalog members; querying, charts, drilldown, and own exports. |
| Admin | Viewer access plus candidate discovery, governance definitions, publication, and all export jobs. |
| Cube service | The private internal catalog endpoint only, authenticated by profile-bound HMAC. It is not a browser endpoint. |

The only supported semantic views are `survey_responses`, `survey_topics`, `survey_departments`, and `survey_keywords`. Each is a separate grain. A request always names exactly one view, so assignment views cannot be combined and inflate response counts through topic/department/keyword fan-out.

### Semantic-view grains and sentiment mapping

`survey_responses` is plural—there is no `survey_response` view. Choose the view based on the question you are asking, not simply on which word “sentiment” appears in its source table.

| Semantic view | One row represents | Database source | Canonical response sentiment | Assignment sentiment | Use it for |
| --- | --- | --- | --- | --- | --- |
| `survey_responses` | One non-deleted survey response | `surveys`, joined to `stores`, `channels`, and `delivery_services` | `topic_sentiment` = `surveys.topic_sentiment`; score = `surveys.topic_sentiment_score` | None. The legacy `surveys.sentiment` is intentionally not a public semantic field. | Overall response volume, CLS, store/channel analysis, and response-level sentiment. `response_count` counts survey rows. |
| `survey_topics` | One topic assigned to a survey | `survey_topics` joined to the survey facts and `topics` | `topic_sentiment` = `surveys.topic_sentiment`; score remains `surveys.topic_sentiment_score` | `sentiment` = `survey_topics.sentiment` | Topic analysis: group by `topic`, use `assignment_count` for topic assignments, or `distinct_survey_count` for unique surveys. |
| `survey_departments` | One department assigned to a survey | `survey_departments` joined to the survey facts and `departments` | `topic_sentiment` = `surveys.topic_sentiment`; score remains `surveys.topic_sentiment_score` | `sentiment` = `survey_departments.sentiment` | Department analysis: group by `department`, then use assignment or distinct-survey counts as appropriate. |
| `survey_keywords` | One keyword assigned to a survey | `survey_keywords` joined to the survey facts and `keywords` | `topic_sentiment` = `surveys.topic_sentiment`; score remains `surveys.topic_sentiment_score` | `sentiment` = `survey_keywords.sentiment` | Keyword analysis: group/filter by `keyword`, then use assignment or distinct-survey counts. |

In `survey_responses`, always use `topic_sentiment`; `sentiment` is not a valid public member. In assignment views, use `topic_sentiment` for the response-level value and `sentiment` only for that topic/department/keyword assignment row. This keeps the legacy `surveys.sentiment` out of analytics.

Migration note: update any existing response-level metric, chart, saved query, drilldown, or frontend field selector that names `sentiment` to use `topic_sentiment`, then validate/publish a new catalog version. Do **not** change `sentiment` in an assignment-view definition unless you specifically mean the response-level value; in that case use `topic_sentiment`.

Do not combine `survey_topics`, `survey_departments`, and `survey_keywords` in one query. A response can have multiple assignments of each kind, so doing so would multiply rows and make counts/averages ambiguous.

### Shared query concepts

`POST /analytics/query`, chart data, and exports use published member *slugs*, never raw SQL or Cube member names.

| Property | Rule |
| --- | --- |
| `semantic_view` | One of the four views above. |
| `dimensions` | Up to three published dimension slugs for an ad-hoc query. |
| `metrics` | Up to five published metric slugs for an ad-hoc query. |
| `filters` | Up to 20 typed filters. Operators are `equals`, `not_equals`, `contains`, `not_contains`, `starts_with`, `ends_with`, comparison operators, `in`, `not_in`, `set`, `not_set`, and `between`, when compatible with the member type. |
| `time_dimension` | A published date/time dimension. It may be paired with `time_range` and `time_granularity`; do not also include it as an ordinary dimension. |
| `time_range` | Two ISO-8601 date/datetime values, each at most 64 characters, with start no later than end. |
| `time_granularity` | Cube-supported granularity such as day, week, month, quarter, or year, when valid for the time member. |
| `timezone` | Optional IANA timezone (for example, `Asia/Hong_Kong` or `America/New_York`) used for time-range boundaries, time buckets, and timestamp display. UTC is used when omitted. |
| `order` | A list of `{ "member": "<slug>", "direction": "asc" | "desc" }`. |
| `limit` | Aggregate queries allow 1–1,000 rows. Published charts can set their own governed limit up to 5,000 where the chart type allows it. |

A successful aggregate response has this shape:

```json
{
  "query_id": "8f5c…",
  "model_version": 4,
  "timezone": "Asia/Hong_Kong",
  "columns": [{"name": "region", "label": "Region", "type": "string", "kind": "dimension"}],
  "rows": [{"region": "North", "response_count": 120}],
  "confidence": [],
  "warnings": [],
  "freshness_time": "2026-08-25T10:15:00Z"
}
```

Confidence-interval metrics add entries to `confidence` with estimate, lower/upper bounds, level, sample/effective sample size, and method. Weighted metric data-quality failures (negative or non-finite values/weights) appear in `warnings`; they are never silently treated as valid data.

Common errors are `401` for a missing, invalid, deleted, or wrong-profile token; `403` for an insufficient role; `404` when analytics is disabled or a resource is not visible; `422` for invalid governed input or a rejected semantic query; and `503` when Cube or the analytics database dependency is unavailable. Cube/PostgreSQL implementation details are deliberately not exposed in error messages.

### Request field requirements and examples

Swagger/ReDoc marks required JSON fields from the OpenAPI schema. The following guide makes the contract explicit before you call an endpoint.

| Request model | Required fields | Optional fields / rules | Example |
| --- | --- | --- | --- |
| Aggregate query | `semantic_view`; at least one of `dimensions`, `metrics`, or `time_dimension` | `dimensions`, `metrics`, `filters`, time controls, `timezone`, `order`, `limit`. `time_range`/`time_granularity` require `time_dimension`. | `{ "semantic_view": "survey_responses", "dimensions": ["store_format"], "metrics": ["response_count"], "timezone": "Asia/Hong_Kong" }` |
| Filter | `member`, `operator` | `value` is required for scalar comparisons; `values` is required for `in`, `not_in`, and `between`; neither is used for `set`/`not_set`. | `{ "member": "topic_sentiment", "operator": "equals", "value": "NEGATIVE" }` |
| Drilldown | None: defaults select common response fields | `semantic_view` is fixed to `survey_responses`; choose `fields` (1–50), `filters` (0–20), `cursor`, `limit` (1–250), and optional `timezone` for local timestamp filters/display. | `{ "fields": ["survey_id", "respondent_id", "store_key", "reported_at", "comment", "topic_sentiment", "cls"], "limit": 100, "timezone": "Asia/Hong_Kong" }` |
| Create field | `slug`, `label`, `data_type`, `source_key` | `semantic_view` defaults to `survey_responses`; `source_kind` is fixed to `raw_json`; `description` and `visibility` are optional. | `{ "slug": "overall_score", "label": "Overall score", "data_type": "number", "source_key": "Overall Score" }` |
| Promote candidate | `data_type` | `visibility`, `label`, `description`. | `{ "data_type": "number", "visibility": "viewer", "label": "Overall score" }` |
| Create metric | `slug`, `label`, `operation` | `semantic_view` defaults to `survey_responses`; use at most one of `field_id`/`source_member`, and at most one of `weight_field_id`/`weight_member`. A source is required when the operation needs one; CI operations require `confidence_level` (0.8–0.999). | `{ "slug": "negative_response_rate", "label": "Negative response rate", "source_member": "topic_sentiment", "operation": "filtered_rate", "definition": { "filter": { "operator": "equals", "value": "NEGATIVE" } } }` |
| Create chart | `slug`, `title`, `chart_type`, `semantic_view`, `definition` | `description`, `visibility`; definition members depend on chart type. | `{ "slug": "responses_by_store_format", "title": "Responses by store format", "chart_type": "bar", "semantic_view": "survey_responses", "definition": { "dimensions": ["store_format"], "metrics": ["response_count"] } }` |
| Chart data override | None | `filters`, `time_range`, `time_granularity`, `timezone`, `order`, `limit` only; it cannot replace the chart’s governed dimensions or metrics. | `{ "time_range": ["2026-01-01", "2026-03-31"], "time_granularity": "month", "timezone": "Asia/Hong_Kong" }` |
| Filter options | `semantic_view`, `member` | `filters` (up to 18), optional governed `metrics` (up to 4), string-only `search`, optional `timezone`, `limit` (1–1,000), and offset `cursor` (0–1,000,000). The endpoint automatically excludes null values. | `{ "semantic_view": "survey_responses", "member": "store_format", "metrics": ["topic_sentiment_score_average"], "search": "Mall", "timezone": "Asia/Hong_Kong", "cursor": 0 }` |
| Record query | `resource` | `filters` (up to 20 typed allowlisted filters), `order` (up to 3 allowlisted fields), `page`, `size`, and optional IANA `timezone`. Survey pages are capped at 100; master-data pages at 1,000. | `{ "resource": "surveys", "filters": [{"member": "topic_sentiment", "operator": "equals", "value": "NEGATIVE"}], "size": 100 }` |
| Export | `export_format`; exactly one of `query`, `drilldown`, or `record_query` | `export_format` is `csv` or `xlsx`; its selected object follows the relevant query model above. Record exports are live-DB queries and retain configured survey columns. | `{ "export_format": "csv", "record_query": { "resource": "surveys", "size": 100 } }` |
| Catalog publication | None | `description` is optional release/audit text. | `{ "description": "Quarterly metric release" }` |

## Viewer endpoints

### `GET /analytics/catalog`

Returns the active immutable catalog the current role is allowed to use. It includes the active model version, semantic views, visible fields, visible metrics, and supported chart types. It does not reveal candidate headers, admin-only fields, raw payload keys, SQL expressions, or draft definitions.

Use this endpoint before building an exploration UI. A client should only send slugs returned here to the query endpoints.

### `GET /analytics/catalog/availability`

Returns which visible fields actually contain data for one semantic view. It is the intended way for a frontend to hide fields that are entirely null instead of guessing from the catalog definition.

Query parameter:

| Field | Required | Description |
| --- | --- | --- |
| `semantic_view` | Optional; defaults to `survey_responses` | One of `survey_responses`, `survey_topics`, `survey_departments`, or `survey_keywords`. |

Example:

```text
GET /analytics/catalog/availability?semantic_view=survey_responses
```

Illustrative response shape—the counts are calculated from the target BU when called:

```json
{
  "model_version": 4,
  "semantic_view": "survey_responses",
  "total_rows": 28143,
  "fields": [
    {
      "slug": "store_name_english",
      "label": "Store Name English",
      "data_type": "string",
      "non_null_count": 28143,
      "null_count": 0,
      "availability_rate": 1.0,
      "available": true
    },
    {
      "slug": "delivery_service_name",
      "label": "Delivery Service Name",
      "data_type": "string",
      "non_null_count": 0,
      "null_count": 28143,
      "availability_rate": 0.0,
      "available": false
    }
  ],
  "generated_at": "2026-08-26T08:00:00+00:00",
  "cached": false
}
```

The result contains only fields visible to the caller—viewer requests do not disclose admin-only fields. The first request for a role/view/model-version may scan the reporting view; identical requests are cached for up to 15 minutes. `available: true` means at least one reporting row has a non-null value, not that every row is complete.

### `POST /analytics/filter-options`

Returns values that can populate one frontend filter control. The target `member` must be a published, role-visible dimension in the specified semantic view. The response excludes null values, orders options by matching-row count, and never exposes raw/unpromoted payload keys.

```json
{
  "semantic_view": "survey_responses",
  "member": "store_format",
  "metrics": ["topic_sentiment_score_average"],
  "filters": [
    {"member": "topic_sentiment", "operator": "equals", "value": "NEGATIVE"}
  ],
  "search": "Mall",
  "limit": 100,
  "cursor": 0
}
```

`semantic_view` and `member` are required. `filters` is optional and can express dependent choices (for example, list stores only after choosing a store format). `search` is optional and accepted only for string fields. Use `GET /analytics/catalog/availability` first if the UI should hide dimensions containing no data at all.

`metrics` is optional and accepts at most four unique, published, role-visible metrics owned by the requested semantic view. The view's fixed count metric must not be included because it is returned separately as `count`; unknown, duplicate, cross-view, or inaccessible metrics are rejected with `422`. Every response includes `metric_columns` and every option includes a `metrics` object, even when no optional metrics were requested.

For more than 1,000 values, use `next_cursor` from the response as the next request’s `cursor`. Values are ordered by matching-row count descending, then the value ascending for stable paging. `has_more` is true when the page was full; one final request can return an empty page when the total is an exact multiple of `limit`.

```json
{
  "query_id": "…",
  "model_version": 4,
  "semantic_view": "survey_responses",
  "member": "store_format",
  "label": "Store Format",
  "data_type": "string",
  "metric_columns": [
    {
      "name": "topic_sentiment_score_average",
      "label": "Topic Sentiment Score Average",
      "type": "number",
      "kind": "metric"
    }
  ],
  "cursor": 0,
  "next_cursor": 100,
  "has_more": true,
  "values": [
    {"value": "Mall", "count": 245, "metrics": {"topic_sentiment_score_average": 0.42}},
    {"value": "Commercial", "count": 81, "metrics": {"topic_sentiment_score_average": 0.18}}
  ],
  "warnings": [],
  "freshness_time": "2026-08-26T08:00:00Z"
}
```

### `POST /analytics/query`

Runs one governed aggregate query against a single semantic view. The request body is the shared query shape:

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_name_english", "store_format"],
  "metrics": ["response_count", "cls_average"],
  "filters": [{"member": "topic_sentiment", "operator": "equals", "value": "NEGATIVE"}],
  "time_dimension": "reported_at",
  "time_range": ["2024-08-01", "2024-08-31"],
  "time_granularity": "month",
  "timezone": "Asia/Hong_Kong",
  "order": [{"member": "response_count", "direction": "desc"}],
  "limit": 1000
}
```

The server validates visibility, member types, limits, filter operators, and metric dependencies before sending a short-lived role/profile token to private Cube. It returns the common aggregate response. `422` means the query cannot be expressed by the active catalog; `503` means Cube cannot currently serve it.

### `POST /analytics/records/query`

Runs a governed record query directly against the live application database. The
supported resources are `surveys`, `stores`, `departments`, `channels`,
`delivery_services`, and `topics`. Filters and ordering accept only typed,
resource-specific allowlisted fields. Use `member` for a field name (`field` is
accepted as an input alias), and use `value` for scalar operators or `values`
for `in`, `not_in`, and `between`.

Survey results exclude soft-deleted rows and preserve the existing nested store,
channel, delivery-service, department, topic, and keyword objects. Survey
responses include both the legacy `sentiment` and canonical `topic_sentiment`
fields. Topic, department, and keyword filters on a survey use `EXISTS`
predicates, so assignment matches do not duplicate survey rows.

```json
{
  "resource": "surveys",
  "filters": [
    {"member": "topic", "operator": "equals", "value": "Delivery"},
    {"member": "reported_at", "operator": "between", "values": ["2026-01-01", "2026-02-01"]}
  ],
  "order": [
    {"member": "reported_at", "direction": "desc"},
    {"member": "id", "direction": "desc"}
  ],
  "page": 1,
  "size": 100,
  "timezone": "Asia/Hong_Kong"
}
```

The response is `{ "resource", "items", "page", "size", "total",
"has_more", "timezone" }`. Surveys default to `reported_at DESC, id DESC`;
master-data resources default to their primary key ascending. Master-data queries
return unused values as well as values referenced by surveys, which supports
zero-filling dashboard selectors.

### `GET /analytics/charts/published`

Lists published charts visible to the caller in the active catalog. Each chart includes its ID, slug, title, type, semantic view, governed definition, visibility, lifecycle status, validation state, and model-version metadata. Draft, archived, invalid, or admin-only charts are omitted for viewers.

### `POST /analytics/charts/{chart_id}/data`

Runs a published chart by numeric ID. The chart’s dimensions and metrics are fixed by its published definition; callers may only supply safe exploration overrides:

```json
{
  "filters": [{"member": "store_format", "operator": "in", "values": ["Mall", "Commercial"]}],
  "time_range": ["2024-08-01", "2024-08-31"],
  "time_granularity": "month",
  "order": [{"member": "response_count", "direction": "desc"}],
  "limit": 100
}
```

The response contains `chart` plus the common aggregate result. Chart-specific shaping is applied: pie/donut results are top 12 categories plus `Other`; scatter uses two metrics and optional category; heatmaps use two dimensions and one metric; store maps cap output at 5,000 points. `404` is returned for a non-existent or non-visible chart.

### `POST /analytics/drilldown`

Returns cursor-paginated response-level rows from `survey_responses` only. It is intended for inspecting the rows behind an aggregate, not for arbitrary raw-data access.

```json
{
  "fields": ["survey_id", "respondent_id", "store_key", "reported_at", "comment", "topic_sentiment", "topic_sentiment_score", "cls"],
  "filters": [{"member": "topic_sentiment", "operator": "equals", "value": "NEGATIVE"}],
  "cursor": 0,
  "limit": 100
}
```

`fields` accepts 1–50 permitted core/promoted fields, `filters` accepts up to 20 compatible filters, and `limit` is 1–250. An optional IANA `timezone` applies local timestamp filters and formats returned timestamp fields; UTC is used when omitted. The response includes the effective `timezone` alongside `{ "rows": [...], "next_cursor": 100, "has_more": true }`. Only current-role-visible promoted fields are returned; unpromoted payload keys and the raw JSON payload are never returned. Capacity protection can return `429` with `Retry-After`; a database timeout/unavailability returns `503`.

### `POST /analytics/exports`

Creates an asynchronous CSV or XLSX export. The body uses **exactly one** of an aggregate query, a drilldown query, or a live record query:

```json
{
  "export_format": "xlsx",
  "query": {
    "semantic_view": "survey_responses",
    "dimensions": ["region"],
    "metrics": ["response_count"]
  }
}
```

or:

```json
{
  "export_format": "csv",
  "drilldown": {
    "fields": ["survey_id", "comment"],
    "filters": []
  }
}
```

or:

```json
{
  "export_format": "csv",
  "record_query": {
    "resource": "surveys",
    "filters": [{"member": "topic_sentiment", "operator": "equals", "value": "NEGATIVE"}]
  }
}
```

It returns the newly created export job with status `queued`. The exact role, model version, query, and visibility rules are captured when admitted; the job re-checks the requester’s current account/role before producing data. Exports are capped at 250,000 rows, CSV/XLSX formula prefixes are escaped, and artifacts expire after 24 hours. Per-user and per-profile queue limits return `429`.

### `GET /analytics/exports/{job_id}`

Returns the current export-job metadata for its owner or an admin. Status is `queued`, `processing`, `completed`, or `failed`, along with timestamps, format, row count when available, expiry, and safe failure information. Other users receive `404` rather than confirmation that a job exists. An expired job remains visible as historical job metadata, but its download returns `410`.

### `GET /analytics/exports/{job_id}/download`

Streams the completed CSV/XLSX artifact to its owner or an authorized admin. It returns `409` while the job is not complete, `404` when it is not visible, and `410` after expiry or removal. The file response is explicitly non-cacheable.

## Administrator endpoints

All paths in this section require an authenticated admin and are feature-gated.
The first rollout deliberately exposes **chart management only**. Standard fields
and metrics are built in; candidate, field, metric, and catalog-version
administration are not public endpoints. This keeps the operational surface
small while retaining governed chart definitions and audit history.

### Removed candidate, field, and metric administration

These endpoints are retained only as private implementation handlers and are
not mounted in the public API. They return `404` to callers. The historical
details below are retained for migration context only; use chart definitions
over the built-in catalog instead.

| Endpoint | Detailed behaviour |
| --- | --- |
| `GET /admin/analytics/candidates` | Lists imported header candidates discovered from uploads. Each item includes inferred type, conflicting types, bounded sample values, occurrence metadata, source key, and promotion state. It is admin-only because raw headers and samples may be sensitive. |
| `GET /admin/analytics/fields` | Lists all local governed fields, including draft/archived state and discovery metadata. |
| `GET /admin/analytics/fields/{field_id}` | Returns one field record or `404`. |
| `POST /admin/analytics/fields` | Creates a draft raw-JSON field. Body: `slug`, `label`, optional `description`, `data_type` (`string`, `number`, `boolean`, `date`, `time`), `source_key`, optional `visibility` (`viewer`/`admin`), and `semantic_view` (currently `survey_responses`). It validates safe identifiers and type/source compatibility. |
| `PUT /admin/analytics/fields/{field_id}` | Updates an existing field. A changed field becomes draft and must be revalidated/published before catalog activation. |
| `POST /admin/analytics/fields/{field_id}/promote` | Promotes a discovered candidate into a governed draft field. Body selects `data_type`, `visibility`, and optional `label`/`description`; source key and candidate history stay traceable. |
| `POST /admin/analytics/fields/{field_id}/validate` | Runs field validation and returns the field plus validation result/errors. It does not activate the catalog. |
| `POST /admin/analytics/fields/{field_id}/publish` | Marks a valid, promoted field as published and records an audit event. It is still not visible to viewers until a catalog version is published. |
| `POST /admin/analytics/fields/{field_id}/archive` | Archives a field. It refuses the request when a published metric or chart still references the field (including dimensions, time dimension, filters, and ordering). |

### Metrics

Metric creation supports both promoted field IDs and fixed governed core members. A body contains `slug`, `label`, optional `description`, `semantic_view`, one source (`field_id` or `source_member`) where required, `operation`, optional weight (`weight_field_id` or `weight_member`), optional `confidence_level`, optional declarative `definition`, and `visibility`.

Supported operations include count/distinct/filtered count and rates for all types; numeric sum, average, weighted sum/average, min/max, sample/population variance and standard deviation, weighted dispersion, median, percentile, and confidence intervals; and date/time min/max. Weights must be non-negative numeric governed members. Median/percentile are explicitly unweighted.

| Endpoint | Detailed behaviour |
| --- | --- |
| `GET /admin/analytics/metrics` | Lists all metric records, their source/weight references, operation, confidence configuration, lifecycle status, and audit/version data. |
| `GET /admin/analytics/metrics/{metric_id}` | Returns one metric or `404`. |
| `POST /admin/analytics/metrics` | Creates a draft governed metric. No arbitrary SQL, JavaScript, or expressions are accepted in `definition`; only the validated declarative parameters for the selected operation are allowed. |
| `PUT /admin/analytics/metrics/{metric_id}` | Updates a metric and returns it to draft, requiring fresh validation/publication. |
| `POST /admin/analytics/metrics/{metric_id}/validate` | Checks source type, operation, weight validity, visibility dependencies, confidence level (80%–99.9%), percentile/filter parameters, and semantic-view compatibility. |
| `POST /admin/analytics/metrics/{metric_id}/publish` | Marks a valid metric published and audits the change. Catalog activation remains a separate step. |
| `POST /admin/analytics/metrics/{metric_id}/archive` | Archives a metric unless a published chart still references it. |

### Charts

A chart body contains `slug`, `title`, optional `description`, `chart_type`, `semantic_view`, a governed `definition`, and `visibility`. The definition names published dimensions/metrics and may include filters, time settings, ordering, and a bounded limit. Chart validation enforces the member visibility/type rules and chart shape: KPI has one metric; pie/donut one dimension + one metric; scatter two metrics plus optional category; heatmap two dimensions + one metric; and store map requires store identity/location plus one metric and at most 5,000 points.

| Endpoint | Detailed behaviour |
| --- | --- |
| `GET /admin/analytics/charts` | Lists every chart, including drafts, archived charts, validation errors, definitions, visibility, and version metadata. |
| `GET /admin/analytics/charts/{chart_id}` | Returns one chart or `404`. |
| `POST /admin/analytics/charts` | Creates a draft chart definition. It has no visualization rendering side effect; the frontend consumes the chart contract. |
| `PUT /admin/analytics/charts/{chart_id}` | Updates the definition and returns it to draft. |
| `POST /admin/analytics/charts/{chart_id}/publish` | Validates, publishes, and immediately activates a new catalog version. The response includes `model_version`; viewers can then obtain the chart through `GET /analytics/charts/published`. |
| `DELETE /admin/analytics/charts/{chart_id}` | Soft-deletes the chart, records an audit event, and immediately activates a catalog version without it. It is no longer visible to viewers. |

### Catalog versions

| Endpoint | Detailed behaviour |
| --- | --- |
| `GET /admin/analytics/catalog/versions` | Lists model-version history: catalog version, status (`active`, `superseded`, etc.), definition hash, creator, timestamps, and validation errors. The immutable snapshot is not included in this list response. |
| `GET /admin/analytics/catalog/versions/{version_id}` | Returns one version including its immutable catalog snapshot and generated Cube catalog information, for audit/debugging. It is admin-only because it can include local source keys. |
| `POST /admin/analytics/catalog/publish` | Optional body: `{ "description": "Quarterly metrics release" }`. Revalidates every published field/metric/chart, checks catalog-size and dependency constraints, compiles chart rollup definitions, records an immutable version, and atomically makes it active. Returns `201` with the new version. Invalid definitions produce `422`; lifecycle/concurrency conflicts produce `409`. |

## Internal Cube metadata endpoint

### `GET /internal/analytics/catalog`

This is not a human administration API. It supplies active chart/catalog metadata
to the per-BU Cube compiler. It is intentionally not controlled by
`ANALYTICS_ENABLED`, allowing the seven-day shadow phase to compile while
user-facing analytics remains disabled. It must be reachable only on the
private analytics network.

Required headers are:

```text
X-Analytics-Profile: wtchk_cls
X-Analytics-Timestamp: <unix seconds>
X-Analytics-Signature: <HMAC-SHA256 of "<timestamp>:<profile>">
```

The profile must match the deployment profile, the timestamp must be fresh, and the signature must use that BU’s metadata secret. The response contains the catalog version, field/metric definitions, and approved local rollups required for Cube compilation. Invalid signature/timestamp receives `401`; a wrong profile receives `403`. This response is explicitly `Cache-Control: no-store, private`.

## Historical lifecycle example

The dynamic field/metric flow below is not enabled in the chart-only rollout.

1. An upload discovers a candidate; an admin examines it using `GET /admin/analytics/candidates`.
2. The admin promotes and configures it using `POST /admin/analytics/fields/{field_id}/promote`.
3. The admin creates a metric or chart that uses the field, then calls the relevant `validate` and `publish` endpoints.
4. The admin calls `POST /admin/analytics/catalog/publish`.
5. Cube receives the new immutable catalog through the internal endpoint, and users see it through `GET /analytics/catalog` and `GET /analytics/charts/published`.

Changing or archiving a definition does not rewrite prior catalog snapshots. A published chart/export remains tied to the model version recorded for that operation, which keeps governance and audit history reproducible.
