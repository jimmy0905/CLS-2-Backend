# Legacy endpoint to Cube query book

This document maps every legacy dashboard read endpoint to a governed analytics
request. The requests are sent to `POST /analytics/query`; they use published
semantic-view and member slugs, never raw SQL or Cube member names.

The examples are valid request bodies. Add the active dashboard filters to the
`filters` array as described below. All requests require the normal application
access token.

```text
POST http://localhost:8000/wtchk/api/analytics/query
Authorization: Bearer <access-token>
Content-Type: application/json
```

## Common filter translation

The old dashboard routes accepted query parameters through `FilterRequest`. Use
the corresponding governed member with `in` for a multi-select:

| Legacy query parameter | Cube member | Example |
| --- | --- | --- |
| `store_keys` | `store_key` | `{"member":"store_key","operator":"in","values":[101,102]}` |
| `store_english_names` | `store_name_english` | `{"member":"store_name_english","operator":"in","values":["Central"]}` |
| `store_local_names` | `store_name_local` | `{"member":"store_name_local","operator":"in","values":["中環"]}` |
| store attributes (`regions`, `store_formats`, `areas`, etc.) | same singular member (`region`, `store_format`, `area`, etc.) | `{"member":"region","operator":"equals","value":"North"}` |
| `channel_ids` / `channel_names` | `channel_id` / `channel_name` | `{"member":"channel_name","operator":"in","values":["Web"]}` |
| `delivery_service_ids` / `delivery_service_names` | `delivery_service_id` / `delivery_service_name` | `{"member":"delivery_service_name","operator":"in","values":["Foodpanda"]}` |
| `topics` | `topic` in `survey_topics` | `{"member":"topic","operator":"in","values":["Delivery"]}` |
| `keywords` | `keyword` in `survey_keywords` | `{"member":"keyword","operator":"in","values":["late"]}` |
| `department_ids` / `department_names` | `department_id` / `department` in `survey_departments` | `{"member":"department","operator":"in","values":["Service"]}` |
| `topic_sentiments` | `topic_sentiment` | `{"member":"topic_sentiment","operator":"in","values":["NEGATIVE","MIXED"]}` |
| `min_topic_sentiment_score` / `max_topic_sentiment_score` | `topic_sentiment_score` | `{"member":"topic_sentiment_score","operator":"between","values":[-1,1]}` |
| `min_cls` / `max_cls` | `cls` | `{"member":"cls","operator":"between","values":[0,100]}` |
| `from_date` / `to_date` | `time_dimension` + `time_range` | see the time example below |

The old date range was inclusive at `from_date` and exclusive at `to_date`.
Use the same half-open range in Cube:

```json
{
  "time_dimension": "reported_at",
  "time_range": ["2024-08-01T00:00:00Z", "2024-09-01T00:00:00Z"],
  "timezone": "Asia/Hong_Kong"
}
```

For an old list filter with one value, `equals` is equivalent to a one-element
`in`. Keep assignment filters on their matching assignment view. For example,
do not apply a `topic` filter to a department query; that cross-assignment join
was possible in the old SQL path but is intentionally rejected by the governed
model.

## Default graph presentation

Each query below is the default data contract for the graph named here. The
default chart objects are seeded by Alembic revision
`0011_default_analytics_charts`. The frontend should load the published
chart definition from
`GET /analytics/charts/published` and call
`POST /analytics/charts/{chart_id}/data`; the raw `POST /analytics/query` body
is included as the canonical query definition and is useful while charts are
being published.

The migration creates these chart slugs:

```text
dashboard_sentiment_distribution
dashboard_store_distribution
dashboard_store_format_distribution
dashboard_channel_delivery_distribution
dashboard_topic_sentiment_counts
dashboard_overall_topic_sentiment_score
dashboard_mixed_topic_sentiment_score
dashboard_topic_distribution
dashboard_department_distribution
dashboard_keyword_analysis
dashboard_first_reported_at
dashboard_last_reported_at
dashboard_last_updated_at
```

The `store-column` route is parameterized in the legacy API, so
`dashboard_store_format_distribution` is the seeded default. Additional store
column graphs can be created from the same definition with another allowlisted
store dimension.

| Legacy endpoint | Default graph | Graph axes / values |
| --- | --- | --- |
| `/dashboard/sentiment-distribution` | Line | X: reported day; Y: four sentiment counts and average score |
| `/dashboard/store-distribution` | Bar | X: store; Y: positive, negative, neutral, and mixed counts |
| `/dashboard/store-column-sentiment-distribution` | Bar | X: selected store attribute; Y: four sentiment counts |
| `/dashboard/channel-and-delivery-service-distribution` | Bar | X: channel + delivery service; Y: four sentiment counts |
| `/dashboard/topic-sentiment-score` | KPI tiles (`kpi`) | Four counts, overall average, and mixed-only average |
| `/dashboard/topic-distribution` | Bar | X: topic; Y: assignment sentiment counts |
| `/dashboard/department-distribution` | Bar | X: department; Y: assignment sentiment counts |
| `/dashboard/keyword-analysis` | Bar | X: keyword; Y: assignment sentiment counts; top `k` |
| `/dashboard/data-coverage` | KPI tiles (`kpi`) | First and last reported timestamps |
| `/dashboard/last-updated-date` | KPI | Latest active survey update timestamp |

The `total_count_for_option` and zero-fill requests documented below are graph
support data. They should not be rendered as additional series unless the
product explicitly wants a comparison or tooltip for the selected option.

## Dashboard endpoint replacements

### `GET /dashboard/sentiment-distribution`

Legacy response: one row per local reported date with `year`, `month`, `day`,
four response-level sentiment counts, and the average response sentiment score.
Default graph: line chart.

```json
{
  "semantic_view": "survey_responses",
  "metrics": [
    "topic_sentiment_positive_count",
    "topic_sentiment_negative_count",
    "topic_sentiment_neutral_count",
    "topic_sentiment_mixed_count",
    "topic_sentiment_score_average"
  ],
  "time_dimension": "reported_at",
  "time_granularity": "day",
  "time_range": ["2024-08-01T00:00:00Z", "2024-09-01T00:00:00Z"],
  "timezone": "Asia/Hong_Kong",
  "order": [{"member": "reported_at", "direction": "asc"}],
  "limit": 1000
}
```

The Cube `reported_at` value is the start of each day bucket. Shape that value
into the old `year`/`month`/`day` fields in the client.

### `GET /dashboard/store-distribution`

Legacy response: one row per store with store identity, open/close dates,
response-level sentiment counts, average score, and `total_count_for_option`.
Default graph: bar chart; store identity is the category axis and the
four sentiment counts are stacked values.

Main Cube query:

```json
{
  "semantic_view": "survey_responses",
  "dimensions": [
    "store_key",
    "store_name_english",
    "store_name_local",
    "store_open_date",
    "store_close_date"
  ],
  "metrics": [
    "topic_sentiment_positive_count",
    "topic_sentiment_negative_count",
    "topic_sentiment_neutral_count",
    "topic_sentiment_mixed_count",
    "topic_sentiment_score_average"
  ],
  "order": [{"member": "topic_sentiment_negative_count", "direction": "desc"}],
  "limit": 1000
}
```

To reproduce `total_count_for_option`, run a second query with the same active
filters except all `store_key`, `store_name_english`, and `store_name_local`
filters. Group by `store_key` and request `response_count`:

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_key"],
  "metrics": ["response_count"],
  "order": [{"member": "store_key", "direction": "asc"}],
  "limit": 1000
}
```

Join the two responses by `store_key`. If the UI must retain the old rows for
stores with no matching survey, fetch all master values with the governed
record query shown in the [master-data appendix](#legacy-master-data-reads),
then zero-fill missing aggregate rows.

### `GET /dashboard/store-column-sentiment-distribution?column={column}`

Legacy response: one row per non-null selected store attribute with response-
level sentiment counts, average score, and `total_count_for_option`.
Default graph: bar chart; the selected `column` is the category axis.

Use the allowlisted Cube member corresponding to `column`; never construct a
member from arbitrary client input. The old `column` values map as follows:

```text
bu_key, area_manager, store_format, store_type, operations_controller,
regional_manager, px, csr, dr, mag_type, cf_grouping, store_brand,
competitor, region, area, province, territory, toh, district, city,
operations_manager, district_manager, sic, soc, tech_life_type,
operation_manager_tl, region_manager_tl, relocation, latitude, longitude,
store_open_date, store_close_date, is_closed, store_key,
store_english_name, store_local_name
```

For example, `column=store_format` becomes:

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_format"],
  "metrics": [
    "topic_sentiment_positive_count",
    "topic_sentiment_negative_count",
    "topic_sentiment_neutral_count",
    "topic_sentiment_mixed_count",
    "topic_sentiment_score_average"
  ],
  "filters": [{"member": "store_format", "operator": "set"}],
  "order": [{"member": "topic_sentiment_negative_count", "direction": "desc"}],
  "limit": 1000
}
```

For `total_count_for_option`, run the same query with only `response_count` as
the metric and remove filters for the selected member. Join by the selected
dimension. The `set` filter on the main query preserves the old non-null
behaviour.

### `GET /dashboard/channel-and-delivery-service-distribution`

Legacy response: one row per observed channel/delivery-service combination,
including null values, response-level sentiment counts, average score, and the
combination total.
Default graph: bar chart with channel and delivery service as the
category key.

Main query:

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["channel_name", "delivery_service_name"],
  "metrics": [
    "topic_sentiment_positive_count",
    "topic_sentiment_negative_count",
    "topic_sentiment_neutral_count",
    "topic_sentiment_mixed_count",
    "topic_sentiment_score_average"
  ],
  "order": [{"member": "topic_sentiment_negative_count", "direction": "desc"}],
  "limit": 1000
}
```

Run a second query with the same filters except channel and delivery-service
filters, request `response_count`, and keep both dimensions. Join by the pair
`(channel_name, delivery_service_name)` to obtain the old total.

### `GET /dashboard/topic-sentiment-score`

Legacy response: counts of responses by `surveys.topic_sentiment`, the overall
average response score, and the average score for mixed responses.
Default graph: KPI group. Use one KPI tile per returned metric; the mixed-only
average comes from the second query.

Main query:

```json
{
  "semantic_view": "survey_responses",
  "metrics": [
    "topic_sentiment_positive_count",
    "topic_sentiment_negative_count",
    "topic_sentiment_neutral_count",
    "topic_sentiment_mixed_count",
    "topic_sentiment_score_average"
  ],
  "limit": 1
}
```

Mixed-only average query:

```json
{
  "semantic_view": "survey_responses",
  "metrics": ["topic_sentiment_score_average"],
  "filters": [{"member": "topic_sentiment", "operator": "equals", "value": "MIXED"}],
  "limit": 1
}
```

Map the five returned values to the old response property names on the client.

### `GET /dashboard/topic-distribution`

Legacy response: every topic master value, assignment-level neutral/positive/
negative counts, and `total_count_for_option`. Counts are based on
`survey_topics.sentiment`, not response-level `topic_sentiment`.
Default graph: bar chart.

```json
{
  "semantic_view": "survey_topics",
  "dimensions": ["topic"],
  "metrics": [
    "assignment_count",
    "topic_assignment_positive_count",
    "topic_assignment_negative_count",
    "topic_assignment_neutral_count"
  ],
  "order": [{"member": "assignment_count", "direction": "desc"}],
  "limit": 1000
}
```

The `assignment_count` value is the old total count for an unfiltered topic
query. For a selected topic filter, calculate the old
`total_count_for_option` with `POST /analytics/filter-options` using
`semantic_view: "survey_topics"`, `member: "topic"`, `metrics: []`, and every
other active filter, but omit the topic filter itself. Fetch all topic master
values with the record query in the appendix and zero-fill groups absent from
the Cube result.

### `GET /dashboard/department-distribution`

Legacy response: every department master value, assignment-level neutral/
positive/negative counts, and `total_count_for_option`.
Default graph: bar chart.

```json
{
  "semantic_view": "survey_departments",
  "dimensions": ["department"],
  "metrics": [
    "assignment_count",
    "department_assignment_positive_count",
    "department_assignment_negative_count",
    "department_assignment_neutral_count"
  ],
  "order": [{"member": "assignment_count", "direction": "desc"}],
  "limit": 1000
}
```

Use `POST /analytics/filter-options` with `member: "department"` and all
other active filters, excluding the department filter, for option totals. Use
the master-data record query and zero-fill to retain unused departments.

### `GET /dashboard/keyword-analysis?k=10`

Legacy response: the top `k` keyword values with assignment-level neutral,
positive, and negative counts. `k` maps directly to Cube `limit`.
Default graph: bar chart limited to the top `k` keywords.

```json
{
  "semantic_view": "survey_keywords",
  "dimensions": ["keyword"],
  "metrics": [
    "assignment_count",
    "keyword_assignment_positive_count",
    "keyword_assignment_negative_count",
    "keyword_assignment_neutral_count"
  ],
  "order": [{"member": "assignment_count", "direction": "desc"}],
  "limit": 10
}
```

### `GET /dashboard/data-coverage`

Legacy response: first and last non-deleted `reported_at` timestamps, formatted
in the requested timezone.
Default graph: two-value KPI group.

```json
{
  "semantic_view": "survey_responses",
  "metrics": ["first_reported_at", "last_reported_at"],
  "timezone": "Asia/Hong_Kong",
  "limit": 1
}
```

The response metrics are the direct replacements for
`first_data_reported_date` and `last_data_reported_date`.

### `GET /dashboard/last-updated-date`

```json
{
  "semantic_view": "survey_responses",
  "metrics": ["last_updated_at"],
  "timezone": "Asia/Hong_Kong",
  "limit": 1
}
```

This returns the latest `updated_at` among active analytics facts. The legacy
route queried the operational survey table without excluding soft-deleted rows;
the governed model intentionally excludes deleted surveys. Treat this as the
documented freshness semantic for the replacement.
Default graph: single KPI tile.

## Legacy master-data reads

These routes are read endpoints, but they are not aggregate Cube queries. Use
`POST /analytics/records/query` against the live database:

| Legacy route | Replacement body |
| --- | --- |
| `GET /channels/` | `{ "resource": "channels", "page": 1, "size": 1000 }` |
| `GET /channels/{channel_id}` | `{ "resource": "channels", "filters": [{"member":"id","operator":"equals","value":123}], "page": 1, "size": 1 }` |
| `GET /delivery_services/` | `{ "resource": "delivery_services", "page": 1, "size": 1000 }` |
| `GET /delivery_services/{delivery_service_id}` | `{ "resource": "delivery_services", "filters": [{"member":"id","operator":"equals","value":123}], "page": 1, "size": 1 }` |
| `GET /topics/` | `{ "resource": "topics", "page": 1, "size": 1000 }` |
| `GET /topics/{topic_id}` | `{ "resource": "topics", "filters": [{"member":"id","operator":"equals","value":123}], "page": 1, "size": 1 }` |
| `GET /surveys` | `{ "resource": "surveys", "page": 1, "size": 100 }` |
| `GET /surveys/{survey_id}` | `{ "resource": "surveys", "filters": [{"member":"id","operator":"equals","value":123}], "page": 1, "size": 1 }` |
| `GET /surveys/download` | `POST /analytics/exports` with `record_query: {"resource":"surveys", ...}` and `export_format: "csv"` or `"xlsx"` |
| `GET /stores` | `{ "resource": "stores", "page": 1, "size": 1000 }` |
| `GET /departments` | `{ "resource": "departments", "page": 1, "size": 1000 }` |

For the dashboard zero-fill path, the relevant master query is:

```json
{
  "resource": "stores",
  "page": 1,
  "size": 1000,
  "order": [{"member": "store_key", "direction": "asc"}]
}
```

Replace `stores` with `topics` or `departments` for the corresponding card.
The record API returns master values that are not referenced by any survey,
which is why it is the correct source for the old zero-filled rows.

## Response shaping and parity checklist

The governed API returns a common aggregate envelope:

```json
{
  "query_id": "…",
  "model_version": 4,
  "timezone": "UTC",
  "columns": [],
  "rows": [],
  "confidence": [],
  "warnings": [],
  "freshness_time": "…"
}
```

The client should:

1. Read aggregate values from `rows`, not from the legacy list response.
2. Join second-query counts by the dimension key to recreate
   `total_count_for_option`.
3. Zero-fill stores, topics, and departments from the master-data record query.
4. Convert daily time buckets and map metric slugs to the old property names
   where an unchanged response DTO is temporarily required.
5. Keep topic, department, and keyword assignment filters scoped to their own
   semantic view.

Aggregate queries are capped at 1,000 rows. Paginate filter options or use a
governed export for larger reports. Cube results are also freshness-based; use
the returned `freshness_time` when the UI needs to show data currency.
