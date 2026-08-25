# Analytics API reference

This document describes the governed Cube analytics API. It covers the analytics routes only; existing `/dashboard/*`, survey, upload, and authentication routes are unchanged.

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
| `order` | A list of `{ "member": "<slug>", "direction": "asc" | "desc" }`. |
| `limit` | Aggregate queries allow 1–1,000 rows. Published charts can set their own governed limit up to 5,000 where the chart type allows it. |

A successful aggregate response has this shape:

```json
{
  "query_id": "8f5c…",
  "model_version": 4,
  "columns": [{"name": "region", "label": "Region", "type": "string", "kind": "dimension"}],
  "rows": [{"region": "North", "response_count": 120}],
  "confidence": [],
  "warnings": [],
  "freshness_time": "2026-08-25T10:15:00Z"
}
```

Confidence-interval metrics add entries to `confidence` with estimate, lower/upper bounds, level, sample/effective sample size, and method. Weighted metric data-quality failures (negative or non-finite values/weights) appear in `warnings`; they are never silently treated as valid data.

Common errors are `401` for a missing, invalid, deleted, or wrong-profile token; `403` for an insufficient role; `404` when analytics is disabled or a resource is not visible; `422` for invalid governed input or a rejected semantic query; and `503` when Cube or the analytics database dependency is unavailable. Cube/PostgreSQL implementation details are deliberately not exposed in error messages.

## Viewer endpoints

### `GET /analytics/catalog`

Returns the active immutable catalog the current role is allowed to use. It includes the active model version, semantic views, visible fields, visible metrics, and supported chart types. It does not reveal candidate headers, admin-only fields, raw payload keys, SQL expressions, or draft definitions.

Use this endpoint before building an exploration UI. A client should only send slugs returned here to the query endpoints.

### `POST /analytics/query`

Runs one governed aggregate query against a single semantic view. The request body is the shared query shape:

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["region"],
  "metrics": ["response_count", "average_cls"],
  "filters": [{"member": "channel_name", "operator": "equals", "value": "App"}],
  "time_dimension": "reported_at",
  "time_range": ["2026-01-01", "2026-03-31"],
  "time_granularity": "month",
  "order": [{"member": "response_count", "direction": "desc"}],
  "limit": 1000
}
```

The server validates visibility, member types, limits, filter operators, and metric dependencies before sending a short-lived role/profile token to private Cube. It returns the common aggregate response. `422` means the query cannot be expressed by the active catalog; `503` means Cube cannot currently serve it.

### `GET /analytics/charts/published`

Lists published charts visible to the caller in the active catalog. Each chart includes its ID, slug, title, type, semantic view, governed definition, visibility, lifecycle status, validation state, and model-version metadata. Draft, archived, invalid, or admin-only charts are omitted for viewers.

### `POST /analytics/charts/{chart_id}/data`

Runs a published chart by numeric ID. The chart’s dimensions and metrics are fixed by its published definition; callers may only supply safe exploration overrides:

```json
{
  "filters": [{"member": "region", "operator": "in", "values": ["North", "South"]}],
  "time_range": ["2026-01-01", "2026-06-30"],
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
  "fields": ["survey_id", "reported_at", "store_name", "sentiment", "comment"],
  "filters": [{"member": "region", "operator": "equals", "value": "North"}],
  "cursor": 0,
  "limit": 100
}
```

`fields` accepts 1–50 permitted core/promoted fields, `filters` accepts up to 20 compatible filters, and `limit` is 1–250. The response is `{ "rows": [...], "next_cursor": 100, "has_more": true }`. Only current-role-visible promoted fields are returned; unpromoted payload keys and the raw JSON payload are never returned. Capacity protection can return `429` with `Retry-After`; a database timeout/unavailability returns `503`.

### `POST /analytics/exports`

Creates an asynchronous CSV or XLSX export. The body uses **exactly one** of an aggregate query or a drilldown query:

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

It returns the newly created export job with status `queued`. The exact role, model version, query, and visibility rules are captured when admitted; the job re-checks the requester’s current account/role before producing data. Exports are capped at 250,000 rows, CSV/XLSX formula prefixes are escaped, and artifacts expire after 24 hours. Per-user and per-profile queue limits return `429`.

### `GET /analytics/exports/{job_id}`

Returns the current export-job metadata for its owner or an admin. Status is `queued`, `processing`, `completed`, or `failed`, along with timestamps, format, row count when available, expiry, and safe failure information. Other users receive `404` rather than confirmation that a job exists. An expired job remains visible as historical job metadata, but its download returns `410`.

### `GET /analytics/exports/{job_id}/download`

Streams the completed CSV/XLSX artifact to its owner or an authorized admin. It returns `409` while the job is not complete, `404` when it is not visible, and `410` after expiry or removal. The file response is explicitly non-cacheable.

## Administrator endpoints

All paths in this section require an authenticated admin and are also feature-gated. Definitions are governed lifecycle records: editing a published definition moves it back to draft; publishing a definition makes it eligible for the next catalog activation; `POST /admin/analytics/catalog/publish` revalidates all published definitions and activates a new immutable catalog version. Archive is used instead of destructive deletion.

### Candidate discovery and fields

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
| `POST /admin/analytics/charts/{chart_id}/validate` | Validates chart shape, members, filters, time range/granularity, and active catalog compatibility; returns validation results without activating it. |
| `POST /admin/analytics/charts/{chart_id}/publish` | Publishes a valid chart definition, making it eligible for catalog activation and chart-specific pre-aggregation planning. |
| `POST /admin/analytics/charts/{chart_id}/archive` | Archives the chart so it is no longer included in future published catalogs. |

### Catalog versions

| Endpoint | Detailed behaviour |
| --- | --- |
| `GET /admin/analytics/catalog/versions` | Lists model-version history: catalog version, status (`active`, `superseded`, etc.), definition hash, creator, timestamps, and validation errors. The immutable snapshot is not included in this list response. |
| `GET /admin/analytics/catalog/versions/{version_id}` | Returns one version including its immutable catalog snapshot and generated Cube catalog information, for audit/debugging. It is admin-only because it can include local source keys. |
| `POST /admin/analytics/catalog/publish` | Optional body: `{ "description": "Quarterly metrics release" }`. Revalidates every published field/metric/chart, checks catalog-size and dependency constraints, compiles chart rollup definitions, records an immutable version, and atomically makes it active. Returns `201` with the new version. Invalid definitions produce `422`; lifecycle/concurrency conflicts produce `409`. |

## Internal Cube metadata endpoint

### `GET /internal/analytics/catalog`

This route supplies the active local catalog to the per-BU Cube compiler. It is intentionally not controlled by `ANALYTICS_ENABLED`, allowing the seven-day shadow phase to compile while user-facing analytics remains disabled. It must be reachable only on the private analytics network.

Required headers are:

```text
X-Analytics-Profile: wtchk_cls
X-Analytics-Timestamp: <unix seconds>
X-Analytics-Signature: <HMAC-SHA256 of "<timestamp>:<profile>">
```

The profile must match the deployment profile, the timestamp must be fresh, and the signature must use that BU’s metadata secret. The response contains the catalog version, field/metric definitions, and approved local rollups required for Cube compilation. Invalid signature/timestamp receives `401`; a wrong profile receives `403`. This response is explicitly `Cache-Control: no-store, private`.

## Lifecycle example

1. An upload discovers a candidate; an admin examines it using `GET /admin/analytics/candidates`.
2. The admin promotes and configures it using `POST /admin/analytics/fields/{field_id}/promote`.
3. The admin creates a metric or chart that uses the field, then calls the relevant `validate` and `publish` endpoints.
4. The admin calls `POST /admin/analytics/catalog/publish`.
5. Cube receives the new immutable catalog through the internal endpoint, and users see it through `GET /analytics/catalog` and `GET /analytics/charts/published`.

Changing or archiving a definition does not rewrite prior catalog snapshots. A published chart/export remains tied to the model version recorded for that operation, which keeps governance and audit history reproducible.
