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
| How many responses are `MIXED`? | `survey_responses` | `topic_sentiment_mixed` | `count` | Filtered response count |
| How many `MIXED` responses per keyword and department? | `survey_assignments` | `topic_sentiment_mixed` | `count` | Distinct responses at the combination grain |

The same `survey/count` goal intentionally resolves to different physical
measures at different grains. This prevents assignment fan-out from inflating a
survey count.

### Enum-valued dimensions are measurable one value at a time

A dimension with a closed value set also publishes one metric target per value,
named `<field>_<value>`. Measuring `topic_sentiment_mixed/count` answers "how
many are MIXED" without spending a group-by slot on the sentiment breakdown,
which is what makes a two-dimension cross tabulation of some other pair
possible. Grouping by the dimension itself remains available and is still the
right choice when every value is wanted at once.

Enum targets publish `count` only. Sentiment is a string, so summing or
averaging it has no meaning; to average a number, measure that number.

The declared enum dimensions are `topic_sentiment` (`POSITIVE`, `NEGATIVE`,
`NEUTRAL`, `MIXED`), the assignment `sentiment` of each single-family grain, and
`keyword_sentiment`, `department_sentiment`, and `topic_assignment_sentiment` at
the combination grain (each `POSITIVE`, `NEGATIVE`, `NEUTRAL`). An arbitrary
string dimension is not expanded, because it has no closed value set.

### The `survey_assignments` grain

`keyword`, `department`, and `topic` each live in their own grain and cannot be
joined, so crossing two of them needs a grain that already holds all three. One
`survey_assignments` row is one `(response, keyword, department, topic)`
combination, so a response repeats once per product of its assignment counts.

Only measures that deduplicate on the response key are published there. A count
becomes a distinct response count; response-level sums and averages such as
`cls/sum` and `cls/average` are deliberately absent, because the fan-out would
weight each response by its combination count. Choose this grain only to cross
assignment families; for a single family, its own grain is both cheaper and
exact.

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
    },
    "layout": {
      "chart_type": null,
      "row_dimension": "store_format",
      "column_dimension": null,
      "value_key": "value",
      "series_limit": null,
      "truncated_series": false,
      "other_series_label": null,
      "filled_cells": 0
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

`schema.layout` names the axes so a client need not infer them from long-format
rows. A cross tabulation puts the first dimension on rows and the second on
columns; a time chart puts the bucket on rows and the remaining dimension on
columns, which is what makes each of its values one line. It is `null` only when
there is nothing to lay out, as for a KPI.

## Chart compatibility

| Shape | Compatible chart types |
| --- | --- |
| No time, 0 dimensions | KPI, table |
| No time, 1 dimension | bar, column, pie, donut, table |
| No time, 2 dimensions | stacked bar, grouped bar, heatmap, table |
| No time, 3 dimensions | table |
| Time, 0–1 ordinary dimension | line, area, table |
| Time, 2–3 ordinary dimensions | table |

Except for table and KPI, the result must be numeric. Any selected
`table_only` dimension restricts the result to table. `scatter` and
`store_map` are not part of the public chart contract.

An aggregate query may carry an optional `chart_type`. When present the server
validates the shape above before running anything, so an incompatible pairing
fails with `422` instead of producing rows a client cannot draw.

### Series limits and grid filling

A chart stops being readable long before a query stops being valid, so a chart
type with a series axis caps it: pie and donut keep the top twelve slices and
aggregate the rest into `Other`, because their parts must still sum to the whole;
line, area, stacked bar, grouped bar, and heatmap keep the top ten series and
drop the rest, because an aggregated extra line or column would be meaningless.
`series_limit` overrides the cap up to fifty, and `schema.layout` reports both
the applied limit and whether anything was dropped.

The cap exists for unbounded dimensions. `keyword` has tens of thousands of
values and `store_name_english` hundreds, while `topic` and `department` come
from closed extraction lists of about twenty and ten values and so are never
truncated at the default.

Setting `fill_empty` completes a cross tabulation into a full grid by adding
zero-valued rows for observed row and column pairs that returned no data. It
requires a column axis and is rejected otherwise.
