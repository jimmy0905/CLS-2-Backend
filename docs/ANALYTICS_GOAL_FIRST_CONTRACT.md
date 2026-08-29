# 目標優先的 Analytics 查詢契約

這是自 catalog version `0013_goal_first_analytics` 起，具權威性的公開彙總查詢契約。它取代了原始欄位的 metric selector。

## 心智模型

彙總查詢依序回答以下問題：

1. 要衡量哪項業務結果（`metric`）？
2. 該目標應如何計算（`aggregation`）？
3. 結果應如何分組（`dimensions` 與可選的時間）？
4. 哪些資料列符合條件（`filters`）？
5. 哪個 fact grain 能安全回答它？伺服器會自行推導，並在回應中以 `semantic_view` 回報。

`metric` 是邏輯目標，而不是資料庫欄位。使用者不會選取 `id`、`assignment_id`、`survey_id` 或 `store_key` 來計數紀錄。伺服器會在推導出的 view grain，將已發佈的 `(metric, aggregation)` 組合解析為一個受治理的 Cube measure。

| 問題 | Semantic View | 公開目標 | 方法 | 受治理意義 |
| --- | --- | --- | --- | --- |
| 有多少份問卷？ | `survey_responses` | `survey` | `count` | response-grain 問卷數 |
| 有多少份不重複的問卷提到關鍵字？ | `survey_keywords` | `survey` | `count` | keyword-assignment grain 的相異問卷數 |
| 有多少個 keyword assignment？ | `survey_keywords` | `keyword_assignment` | `count` | keyword assignment 列數 |
| 有多少個 topic assignment？ | `survey_topics` | `topic_assignment` | `count` | topic assignment 列數 |
| 有多少間有回應的門市？ | `survey_responses` | `store` | `count` | 被涵蓋的相異門市數 |
| 平均 CLS 是多少？ | `survey_responses` | `cls` | `average` | 平均受治理 CLS measure |
| 每個 keyword 的平均 assignment sentiment 是多少？ | `survey_keywords` | `keyword_sentiment` | `average` | keyword assignment score 的平均值 |
| 每個 department 的平均 assignment sentiment 是多少？ | `survey_departments` | `department_sentiment` | `average` | department assignment score 的平均值 |
| 每個 topic 的平均 assignment sentiment 是多少？ | `survey_topics` | `topic_assignment_sentiment` | `average` | topic assignment score 的平均值 |
| 有多少個回應為 `MIXED`？ | `survey_responses` | `topic_sentiment_mixed` | `count` | 經篩選的 response 數 |
| 每個 keyword 與 department 組合有多少個 `MIXED` 回應？ | `survey_assignments` | `topic_sentiment_mixed` | `count` | combination grain 的相異 response 數 |

相同的 `survey/count` 目標會刻意在不同 grain 解析為不同的實體 measure。如此可避免 assignment fan-out 將問卷數膨脹。

### Enum 值維度可一次衡量一個值

具有封閉值集合的 dimension，也會針對每個值發佈一個名為 `<field>_<value>` 的 metric target。衡量 `topic_sentiment_mixed/count` 可回答「有多少筆是 MIXED」，而不需使用 group-by 額度做 sentiment breakdown，因此可對其他一組 dimension 進行雙維交叉表。仍可依 dimension 本身分組；當需要同時取得所有值時，這仍是正確做法。

Enum-value target 只提供 `count`。assignment sentiment 另有三個受治理的 average target：`keyword_sentiment`、`department_sentiment` 與 `topic_assignment_sentiment`。它們不會直接平均字串，而是使用內部 assignment score：`POSITIVE=1`、`NEGATIVE=0`、`NEUTRAL=-1`。因此 average 等同於 `(positive_count - neutral_count) / assignment_count`；score backing field 不會公開為 dimension 或 filter。

宣告的 enum dimension 包含 `topic_sentiment`（`POSITIVE`、`NEGATIVE`、`NEUTRAL`、`MIXED`）、各個 single-family grain 的 assignment `sentiment`，以及 combination grain 中的 `keyword_sentiment`、`department_sentiment`、`topic_assignment_sentiment`（各為 `POSITIVE`、`NEGATIVE`、`NEUTRAL`）。任意字串 dimension 不會展開，因為它沒有封閉值集合。

### `survey_assignments` grain（指派組合粒度）

`keyword`、`department` 與 `topic` 各自存在於不同 grain，且不能 join；若要交叉其中兩者，必須使用已持有三者的 grain。一列 `survey_assignments` 就是一個 `(response, keyword, department, topic)` 組合，因此 response 會依 assignment 數量的乘積重複出現。

此 grain 只發佈依 response key 去重的 measure。計數會成為相異 response 計數；`cls/sum` 與 `cls/average` 等 response-level 加總及平均值刻意不提供，因為 fan-out 會使每個 response 按其組合數加權。只有要交叉 assignment family 時才選擇此 grain；對單一 family 而言，專屬 grain 更省資源且精確。

同樣地，三個 assignment sentiment average 只發佈於各自的 single-family grain；不可在 `survey_assignments` combination grain 計算，否則每個 assignment 會因其他 family 的組合數而被錯誤加權。

## 探索流程

載入 `GET /analytics/builder/measures`，選擇一個可衡量 target 及其中一項 aggregation，接著以 `POST /analytics/builder/options` 探索相容 dimension。直接呼叫 `POST /analytics/query` 時，傳送相同的 metric、aggregation 及已選 member；伺服器會解析 grain。`GET /analytics/catalog` 仍可用於受治理中繼資料及 view-scope 的管理／探索端點。

```http
POST /analytics/query-capabilities
Content-Type: application/json

{
  "semantic_view": "survey_keywords",
  "metric": "survey",
  "aggregation": "count"
}
```

回應會為此精確目標提供允許的 dimension、filter member 與 operator、time dimension、result type 及 warning。前端必須使用這些 capability，而非從欄位的儲存型別推導任意 metric operation。

Catalog field 包含：

- `scope`：`response` 或 `assignment`
- `filterable`：是否可用於篩選
- `time_dimension`：是否可作為具粒度的時間

受治理 field 可以是 dimension，卻不是 metric target。所有角色可見的 dimension 都可用於 query；renderer 自行決定如何呈現 identifier、free-text、coordinate 與其他高 cardinality 欄位。

## 查詢範例

計算 response-level topic sentiment 為 `MIXED` 的問卷數：

```json
{
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

顯示 keyword `A` 的 assignment-sentiment 分布，並計算 keyword assignment：

```json
{
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

如要回答「提到 keyword `A` 的不重複問卷中，各 assignment sentiment 分別有多少筆？」，只需將 target 改為 `survey/count`。若要分析問卷的 response-level sentiment，而非 keyword assignment 本身的 sentiment，則改以 `topic_sentiment` 分組。

計算每個 keyword 的平均 assignment sentiment：

```json
{
  "dimensions": ["keyword"],
  "metric": "keyword_sentiment",
  "aggregation": "average",
  "filters": [],
  "timezone": "Asia/Hong_Kong",
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 100
}
```

依門市格式與 response sentiment，按時間統計問卷數：

```json
{
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

最後一種形狀結合具粒度時間與兩個一般 dimension，因此僅能用於 table。

## 請求與回應規則

- `dimensions` 包含零至三個一般 dimension。
- `metric` 與 `aggregation` 均為必填，且各只能有一個。
- `semantic_view` 不再是 query selector。舊用戶端仍可傳送它，但伺服器會忽略它並回傳實際推導出的 grain。
- 已移除的 `metrics` field 會以 `422` 拒絕。
- 只接受在 `metric_targets` 下發佈的 pair。
- `time_dimension` 不可同時出現於 `dimensions`；前端若以它繪製 line／area，必須同時提供 `time_granularity`。
- `order.member` 必須是已選 dimension、已選 time dimension 或 `value`。
- query、chart data 與 aggregate export 皆使用此契約。
- `filter-options`、record query 與 drilldown 保留各自專用的回應形狀。

每個 aggregate result 都使用 flat row，並有一個固定 result key：

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

未選擇時間時，`schema.time_dimension` 一律為 `null`。即使結果為空，`rows` 與 `warnings` 仍會存在。

## Renderer-neutral query

`/analytics/query` 與 builder query 只接受 governed metric、dimension、filter、time、order 與 limit，並回傳 long-format rows。它們不接受 `chart_type`、`series_limit` 或 `fill_empty`，也不提供 layout、series truncation、`Other` bucket 或補零格線。前端 renderer 依 `schema.dimensions`、`schema.time_dimension`、`schema.metric` 與 rows 自行選圖及處理高 cardinality 資料。
