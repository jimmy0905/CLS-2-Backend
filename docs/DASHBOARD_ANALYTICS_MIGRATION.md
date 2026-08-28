# Replacing dashboard routes with governed analytics queries

This is the migration query book for the existing `/dashboard/*` API. It uses
`POST /analytics/query` and the governed semantic catalog rather than direct
SQL. It is written for the `wtchk_cls` data model, where the canonical response
sentiment is `surveys.topic_sentiment`. The legacy `surveys.sentiment` field is
not used.

For the frontend bootstrap sequence—from catalog and field availability through
filter options and published chart data—see
[Frontend dashboard analytics workflow](FRONTEND_DASHBOARD_ANALYTICS_WORKFLOW.md).

There is not one request that can replace all dashboard cards: each card asks a
question at a different row grain. The requests below replace each endpoint
with the built-in single-metric catalog. A frontend may run the request body
verbatim after adding its current common filters.

Base URL in the local profile:

```text
http://localhost:8000/wtchk/api
```

All examples require:

```http
Authorization: Bearer <access-token>
Content-Type: application/json
```

## 1. Single-metric dashboard contract

Every aggregate request selects exactly one raw `metric` field and one
`aggregation`; the removed `metrics: []` field is rejected. Common pairs are
`id/count` for responses, `assignment_id/count` for assignment rows,
`survey_id/distinct_count` for unique surveys, `cls/average`, and
`topic_sentiment_score/average`. Use only pairs advertised by
`GET /analytics/catalog` under `metric_options`.

`store_key/distinct_count` counts distinct stores over matching response
rows. It counts stores represented in the current response filters and date
range; it intentionally does not count stores with zero matching responses.

Filtered, weighted, variance, standard-deviation, percentile, and confidence-
interval governed metrics may remain in admin/Cube metadata, but are not public
query options. Sentiment distributions now group by the relevant sentiment
Dimension and use a normal row count, rather than selecting several filtered
metrics in one request.

### Response-level sentiment counts

The response-level governed metrics `topic_sentiment_positive_count`,
`topic_sentiment_negative_count`, `topic_sentiment_neutral_count`, and
`topic_sentiment_mixed_count`. They require no setup. The example below is
kept as a reference for creating comparable BU-specific filtered metrics.

```bash
curl -X POST 'http://localhost:8000/wtchk/api/admin/analytics/metrics' \
  -H 'Authorization: Bearer <admin-token>' -H 'Content-Type: application/json' \
  -d '{
    "slug": "topic_sentiment_positive_count",
    "label": "Positive response count",
    "semantic_view": "survey_responses",
    "source_member": "topic_sentiment",
    "operation": "filtered_count",
    "definition": {"filter": {"operator": "equals", "value": "POSITIVE"}},
    "visibility": "viewer"
  }'
```

These names are retained in governance metadata, not accepted as public query
`metric` fields. Their historical definitions are:

| Slug | Filter value |
| --- | --- |
| `topic_sentiment_positive_count` | `POSITIVE` |
| `topic_sentiment_negative_count` | `NEGATIVE` |
| `topic_sentiment_neutral_count` | `NEUTRAL` |
| `topic_sentiment_mixed_count` | `MIXED` |

### Assignment-level sentiment counts

The department, topic, and keyword tables have their own assignment
`sentiment`. These standard `filtered_count` metrics are also built in:

| Semantic view | Positive | Negative | Neutral |
| --- | --- | --- | --- |
| `survey_topics` | `topic_assignment_positive_count` | `topic_assignment_negative_count` | `topic_assignment_neutral_count` |
| `survey_departments` | `department_assignment_positive_count` | `department_assignment_negative_count` | `department_assignment_neutral_count` |
| `survey_keywords` | `keyword_assignment_positive_count` | `keyword_assignment_negative_count` | `keyword_assignment_neutral_count` |

For BU-specific filtered metrics beyond this standard pack, use this body as a
template (with a new unique slug):

```json
{
  "slug": "department_assignment_negative_count",
  "label": "Negative department assignment count",
  "semantic_view": "survey_departments",
  "source_member": "sentiment",
  "operation": "filtered_count",
  "definition": {"filter": {"operator": "equals", "value": "NEGATIVE"}},
  "visibility": "viewer"
}
```

For each BU-specific metric `id` returned, validate and publish it, then
activate a catalog version:

```bash
curl -X POST "http://localhost:8000/wtchk/api/admin/analytics/metrics/<id>/validate" \
  -H 'Authorization: Bearer <admin-token>'
curl -X POST "http://localhost:8000/wtchk/api/admin/analytics/metrics/<id>/publish" \
  -H 'Authorization: Bearer <admin-token>'
curl -X POST 'http://localhost:8000/wtchk/api/admin/analytics/catalog/publish' \
  -H 'Authorization: Bearer <admin-token>' -H 'Content-Type: application/json' \
  -d '{"description":"Dashboard semantic metric pack"}'
```

Use `GET /analytics/catalog` to verify the executable `metric_options` after the
deployment. Metrics can still be governed in the admin UI, but only unique
simple source-field/aggregation pairs enter the public query contract.

## 2. Common filter translation

The semantic API accepts filters in the JSON body. Convert old dashboard query
parameters directly to governed member slugs. For example, this old filter
intent:

```text
regions=Kowloon&store_formats=Mall&topic_sentiments=NEGATIVE
from_date=2024-08-01T00:00:00Z&to_date=2024-09-01T00:00:00Z
```

becomes:

```json
"filters": [
  {"member": "region", "operator": "equals", "value": "Kowloon"},
  {"member": "store_format", "operator": "equals", "value": "Mall"},
  {"member": "topic_sentiment", "operator": "equals", "value": "NEGATIVE"}
],
"time_dimension": "reported_at",
"time_range": ["2024-08-01T00:00:00Z", "2024-09-01T00:00:00Z"]
```

Use `in` plus `values` for a multi-select:

```json
{"member": "store_format", "operator": "in", "values": ["Mall", "Commercial"]}
```

The new API has deliberately separate assignment views. Do not apply a
`topic`/`keyword`/`department` assignment filter while querying another
assignment view: it would reintroduce many-to-many fan-out. Keep those filter
controls scoped to their matching view.

## 3. Dashboard endpoint replacements

In each request below, `filters` may be omitted or replaced with the common
filters from the previous section. `limit` is the maximum number of aggregated
groups returned; it is not a survey-row limit.

### `GET /dashboard/sentiment-distribution`

One row per reported day and sentiment, based on `surveys.topic_sentiment`:

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["topic_sentiment"],
  "metric": "id",
  "aggregation": "count",
  "time_dimension": "reported_at",
  "time_granularity": "day",
  "time_range": ["2024-08-01T00:00:00Z", "2024-09-01T00:00:00Z"],
  "order": [{"member": "reported_at", "direction": "asc"}],
  "limit": 1000
}
```

The returned `reported_at` is the **start of the day bucket** (for example
`2024-08-01T00:00:00.000`), not the first matching survey. The metric values
aggregate every matching response during that day.

### `GET /dashboard/store-distribution`

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_name_english", "topic_sentiment"],
  "metric": "id",
  "aggregation": "count",
  "filters": [
    {"member": "reported_at", "operator": "between", "values": ["2024-08-01T00:00:00Z", "2024-09-01T00:00:00Z"]}
  ],
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 1000
}
```

For more than 1,000 store groups, paginate the selector using
`POST /analytics/filter-options` with `member: "store_key"`, increasing its
`cursor`; analytical aggregate queries are intentionally capped at 1,000 rows.
For a full report, use a governed CSV/XLSX export. See the API reference for
the filter-options cursor contract.

### `GET /dashboard/store-column-sentiment-distribution`

This is the same response-level request with the chosen store field as its
single dimension. For the existing `column=store_format` case:

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_format", "topic_sentiment"],
  "metric": "id",
  "aggregation": "count",
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 1000
}
```

Substitute any published store dimension such as `region`, `area`,
`district`, `area_manager`, `store_brand`, `is_closed`, or `store_open_date`.
Do not build member names from untrusted client text: only use slugs returned
by `GET /analytics/catalog`.

### `GET /dashboard/channel-and-delivery-service-distribution`

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["channel_name", "delivery_service_name", "topic_sentiment"],
  "metric": "id",
  "aggregation": "count",
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 1000
}
```

### `GET /dashboard/topic-sentiment-score`

Run the sentiment-count request:

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["topic_sentiment"],
  "metric": "id",
  "aggregation": "count",
  "limit": 10
}
```

Run a second request for the overall average:

```json
{
  "semantic_view": "survey_responses",
  "metric": "topic_sentiment_score",
  "aggregation": "average",
  "limit": 1
}
```

For `average_mix_topic_score`, run a third request with the same common filters
plus this filter:

```json
{
  "semantic_view": "survey_responses",
  "metric": "topic_sentiment_score",
  "aggregation": "average",
  "filters": [{"member": "topic_sentiment", "operator": "equals", "value": "MIXED"}],
  "limit": 1
}
```

These separate requests are intentional: every aggregate has exactly one
metric field and aggregation.

### `GET /dashboard/topic-distribution`

Use the topic-assignment grain. These counts reflect
`survey_topics.sentiment`, not the response’s `topic_sentiment`:

```json
{
  "semantic_view": "survey_topics",
  "dimensions": ["topic", "sentiment"],
  "metric": "assignment_id",
  "aggregation": "count",
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 1000
}
```

### `GET /dashboard/department-distribution`

Use the department-assignment grain. These counts reflect
`survey_departments.sentiment`:

```json
{
  "semantic_view": "survey_departments",
  "dimensions": ["department", "sentiment"],
  "metric": "assignment_id",
  "aggregation": "count",
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 1000
}
```

### `GET /dashboard/keyword-analysis?k=10`

Use the keyword-assignment grain. `limit: 10` replaces `k=10`:

```json
{
  "semantic_view": "survey_keywords",
  "dimensions": ["keyword", "sentiment"],
  "metric": "assignment_id",
  "aggregation": "count",
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 10
}
```

### `GET /dashboard/data-coverage`

Run two KPI queries; the first uses `reported_at/min`:

```json
{
  "semantic_view": "survey_responses",
  "metric": "reported_at",
  "aggregation": "min",
  "limit": 1
}
```

The second uses the same body with `"aggregation": "max"`.

### `GET /dashboard/last-updated-date`

Query the latest active update directly:

```json
{
  "semantic_view": "survey_responses",
  "metric": "updated_at",
  "aggregation": "max",
  "limit": 1
}
```

The semantic view deliberately excludes soft-deleted surveys. Therefore this
is the latest update among active survey rows; the legacy endpoint did not
apply that exclusion. This is normally the safer reporting meaning.

## 4. Differences to resolve before removing `/dashboard/*`

The semantic requests above replace the analytical calculations. Three legacy
response-shaping behaviours need an explicit frontend/product decision before
the old endpoints can be removed completely:

1. **`total_count_for_option`.** Old distribution routes remove their own
   selected-field filter when calculating option totals. Call
   `POST /analytics/filter-options` for the target field with every *other*
   common filter, excluding the target-field filter. Its `count` is the
   equivalent option total. Example: for a store-format selector, pass region
   and date filters but do not pass a `store_format` filter.
2. **Zero-count master values.** Old store/topic/department routes return
   master-data entries even when they have no matching survey, filled with
   zeros. Semantic aggregate queries intentionally return observed groups only.
   Use `POST /analytics/records/query` for the relevant master resource, then
   join/zero-fill its values against aggregate results when the UI must display
   inactive stores or unused topic/department definitions.
3. **Cross-assignment filters.** The old generic filter object can apply a
   topic filter while rendering a department/keyword card. The semantic layer
   forbids that fan-out-prone combination. Scope topic, department, and keyword
   filters to their own cards, or define an approved response-level derived
   cohort before introducing cross-assignment analysis.

With those three UI adaptations and the published metric pack, the semantic
API supplies the data for every existing dashboard card without calling
`/dashboard/*`.
