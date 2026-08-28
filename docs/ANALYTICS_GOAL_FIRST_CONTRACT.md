# Goal-first analytics query contract

This is the authoritative public aggregate-query contract from catalog version
`0013_goal_first_analytics` onward. It replaces the raw-column metric selector.

## Mental model

An aggregate query answers these questions in order:

1. Which fact grain contains the question (`semantic_view`)?
2. What business result should be measured (`metric`)?
3. How should that target be calculated (`aggregation`)?
4. How should the result be grouped (`dimensions` and optional time)?
5. Which rows qualify (`filters`)?

`metric` is a logical target, not a database column. Users do not select
`id`, `assignment_id`, `survey_id`, or `store_key` to count records. The server
resolves a published `(metric, aggregation)` pair to one governed Cube measure
at the selected view's grain.

| Question | Semantic view | Public target | Method | Governed meaning |
| --- | --- | --- | --- | --- |
| How many surveys? | `survey_responses` | `survey` | `count` | Response-grain survey count |
| How many unique surveys mention a keyword? | `survey_keywords` | `survey` | `count` | Distinct survey count at keyword-assignment grain |
| How many keyword assignments? | `survey_keywords` | `keyword_assignment` | `count` | Keyword assignment row count |
| How many topic assignments? | `survey_topics` | `topic_assignment` | `count` | Topic assignment row count |
| How many responding stores? | `survey_responses` | `store` | `count` | Distinct represented stores |
| What is average CLS? | `survey_responses` | `cls` | `average` | Average governed CLS measure |

The same `survey/count` goal intentionally resolves to different physical
measures at different grains. This prevents assignment fan-out from inflating a
survey count.

## Discovery flow

Load `GET /analytics/catalog`, choose one item in
`metric_targets[semantic_view]`, and then choose exactly one item in that
target's `aggregations` array. Next call:

```http
POST /analytics/query-capabilities
Content-Type: application/json

{
  "semantic_view": "survey_keywords",
  "metric": "survey",
  "aggregation": "count"
}
```

The response supplies the allowed dimensions, filter members and operators,
time dimensions, result type, and warnings for that exact goal. A frontend
must use these capabilities instead of deriving arbitrary metric operations
from a column's storage type.

Catalog fields include:

- `scope`: `response` or `assignment`
- `usage`: `chart` or `table_only`
- `filterable`: whether it may be filtered
- `time_dimension`: whether it may be used as granular time

A governed field can be a dimension without being a metric target. Identifier,
free-text, coordinate, and other high-cardinality fields are normally
`table_only`; they remain available for tables and controlled filters where
appropriate.

## Query examples

Count surveys whose response-level topic sentiment is `MIXED`:

```json
{
  "semantic_view": "survey_responses",
  "dimensions": [],
  "metric": "survey",
  "aggregation": "count",
  "filters": [
    {"member": "topic_sentiment", "operator": "equals", "value": "MIXED"}
  ],
  "timezone": "Asia/Hong_Kong",
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 100
}
```

Show the assignment-sentiment distribution for keyword `A`, counting keyword
assignments:

```json
{
  "semantic_view": "survey_keywords",
  "dimensions": ["sentiment"],
  "metric": "keyword_assignment",
  "aggregation": "count",
  "filters": [
    {"member": "keyword", "operator": "equals", "value": "A"}
  ],
  "timezone": "Asia/Hong_Kong",
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 100
}
```

To answer “how many unique surveys mentioning keyword `A` fall in each
assignment sentiment?”, change only the target to `survey/count`. To analyse
the survey's response-level sentiment rather than the keyword assignment's own
sentiment, group by `topic_sentiment` instead.

Count surveys by store format and response sentiment over time:

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_format", "topic_sentiment"],
  "metric": "survey",
  "aggregation": "count",
  "filters": [],
  "time_dimension": "reported_at",
  "time_granularity": "day",
  "timezone": "Asia/Hong_Kong",
  "order": [{"member": "reported_at", "direction": "asc"}],
  "limit": 100
}
```

That last shape is table-only because it combines granular time with two
ordinary dimensions.

## Request and response rules

- `dimensions` contains zero to three ordinary dimensions.
- `metric` and `aggregation` are both required and singular.
- The removed `metrics` field is rejected with `422`.
- Only pairs published under `metric_targets` are accepted.
- `time_dimension` cannot also appear in `dimensions` and requires a
  `time_granularity` for line/area charts.
- `order.member` is a selected dimension, the selected time dimension, or
  `value`.
- Query, chart data, and aggregate export all use this contract.
- `filter-options`, record query, and drilldown retain their specialised
  response shapes.

Every aggregate result uses flat rows and one fixed result key:

```json
{
  "query_id": "…",
  "model_version": 13,
  "semantic_view": "survey_responses",
  "timezone": "Asia/Hong_Kong",
  "schema": {
    "dimensions": [
      {"field": "store_format", "label": "Store Format", "type": "string", "key": "store_format"}
    ],
    "time_dimension": null,
    "metric": {
      "target": "survey",
      "aggregation": "count",
      "label": "Survey Count",
      "type": "number",
      "key": "value"
    }
  },
  "rows": [{"store_format": "Mall", "value": 42}],
  "row_count": 1,
  "warnings": [],
  "freshness_time": "2026-08-28T05:00:00Z"
}
```

`schema.time_dimension` is always `null` when it was not selected. `rows` and
`warnings` are always present, including empty results.

## Chart compatibility

| Shape | Compatible chart types |
| --- | --- |
| No time, 0 dimensions | KPI, table |
| No time, 1 dimension | bar, column, pie, donut, table |
| No time, 2 dimensions | stacked bar, heatmap, table |
| No time, 3 dimensions | table |
| Time, 0–1 ordinary dimension | line, area, table |
| Time, 2–3 ordinary dimensions | table |

Except for table and KPI, the result must be numeric. Any selected
`table_only` dimension restricts the result to table. `scatter` and
`store_map` are not part of the public chart contract.
