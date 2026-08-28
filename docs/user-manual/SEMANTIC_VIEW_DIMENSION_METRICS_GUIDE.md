# Semantic View、Dimension 與 Metric 使用手冊

> 本手冊已按 goal-first contract 更新。`metric` 現在是業務目標，不是
> `id`、`assignment_id` 或 `survey_id` 等資料欄位。完整 API contract 與
> keyword `A` 範例請參閱
> [Goal-first analytics query contract](../ANALYTICS_GOAL_FIRST_CONTRACT.md)。

本手冊說明 CLSense governed analytics 中 `semantic_view`、Dimension 和
Metric 的組合規則。它同時區分三種情況：

1. API 語法是否合法；
2. 組合的分析意義是否正確；
3. 組合是否符合指定 Chart 類型的形狀要求。

最重要的選擇次序是：

> 先選資料粒度 Semantic View，再選原始 Metric Field 與 Aggregation，最後才選分組方式 Dimension。

相關文件：

- [Analytics API reference](../ANALYTICS_API_REFERENCE.md)
- [Frontend dashboard analytics workflow](../FRONTEND_DASHBOARD_ANALYTICS_WORKFLOW.md)
- [Dashboard analytics migration](../DASHBOARD_ANALYTICS_MIGRATION.md)

## 1. 三個核心概念

```text
Semantic View = 結果底層的一行代表甚麼
Metric Field  = 要數甚麼或計算哪個原始欄位
Aggregation   = 計數、去重、加總、平均、最小值、最大值或中位數
Dimension     = 按甚麼分類或分組
```

例如：

```text
問題：每個 Topic 被多少份不同 Survey 提及？

Semantic View = survey_topics
Dimension     = topic
Metric Field  = survey_id
Aggregation   = distinct_count
```

不要使用：

```text
survey_responses + topic + id/count
```

因為 `topic` 並不屬於 response-level grain。

## 2. Semantic View 完整組合矩陣

### 2.1 `survey_responses`

資料粒度：

```text
一行 = 一份未刪除的 Survey Response
```

#### 常用公開 Metric Options

| Metric Field + Aggregation | 意思 |
| --- | --- |
| `id` + `count` | 問卷回覆數量 |
| `id` + `distinct_count` | 不同 response `id` 數量，通常與 `id/count` 相同 |
| `store_key` + `distinct_count` | 符合目前 filters／日期範圍、且至少有一份回覆的不同 Store 數量 |
| `cls` + `sum`／`average` | CLS 總和／平均值 |
| `topic_sentiment_score` + `sum`／`average`／`median` | Topic sentiment score 統計 |
| `reported_at` + `min`／`max` | 最早／最後回報時間 |
| `updated_at` + `max` | 最後更新時間 |

情緒數量不再以四個 filtered metric 同時查詢。改以
`dimensions: ["topic_sentiment"]` 配 `id/count`，一個查詢回傳各情緒分組。

#### 內建 Dimensions

識別欄位：

```text
id, survey_id, respondent_id
```

時間欄位：

```text
reported_at, created_at, updated_at
```

回覆內容及分數：

```text
comment, topic_sentiment, topic_sentiment_score, cls
```

店舖識別及名稱：

```text
store_key, store_name, store_name_english, store_name_local, bu_key
```

店舖分類及組織欄位：

```text
area_manager, store_format, store_type, operations_controller,
regional_manager, px, csr, dr, mag_type, cf_grouping, store_brand,
competitor, region, area, province, territory, toh, district, city,
operations_manager, district_manager, sic, soc, tech_life_type,
operation_manager_tl, region_manager_tl, relocation
```

店舖位置及生命週期：

```text
latitude, longitude, store_open_date, store_close_date, is_closed
```

渠道及送貨服務：

```text
channel_name, channel_id, delivery_service_name, delivery_service_id
```

適合回答：

- 有多少份問卷回覆？
- 各 Store Format 有多少份回覆？
- 各 Region 的平均 CLS 是多少？
- 整體 Positive、Negative、Neutral、Mixed 分佈如何？
- 每日回覆數量如何變化？
- 哪間店舖的平均 sentiment score 最低？

### 2.2 `survey_topics`

資料粒度：

```text
一行 = 一個 Survey-to-Topic assignment
```

它包含大部分 response-level Dimensions，並增加：

```text
assignment_id, response_id, sentiment, topic_id, topic
```

| Dimension | 意思 |
| --- | --- |
| `topic_sentiment` | 整份 Survey Response 的 sentiment |
| `sentiment` | 當前 Topic assignment 的 sentiment |
| `topic` | Topic 名稱 |
| `assignment_id` | Topic assignment ID |
| `response_id` | 原本 response 的 ID |

#### 常用公開 Metric Options

| Metric Field + Aggregation | 意思 |
| --- | --- |
| `assignment_id` + `count` | Topic assignments 數量 |
| `survey_id` + `distinct_count` | 至少有一個符合條件 Topic assignment 的不同 Survey 數量 |

適合回答：

- 哪個 Topic 出現最多次？
- 哪個 Topic 有最多 Negative assignments？
- 有多少份不同 Survey 提及 Delivery？
- Mall 店舖的 Topic assignments 分佈如何？

### 2.3 `survey_departments`

資料粒度：

```text
一行 = 一個 Survey-to-Department assignment
```

特有 Dimensions：

```text
assignment_id, response_id, sentiment, department_id, department
```

#### 常用公開 Metric Options

| Metric Field + Aggregation | 意思 |
| --- | --- |
| `assignment_id` + `count` | Department assignments 數量 |
| `survey_id` + `distinct_count` | 至少有一個符合條件 Department assignment 的不同 Survey 數量 |

適合回答：

- 哪個 Department 被分配最多次？
- 哪個 Department 有最多 Negative assignments？
- 有多少不同 Survey 涉及 Logistics？
- 各 Store Format 的 Department assignment workload 如何？

### 2.4 `survey_keywords`

資料粒度：

```text
一行 = 一個 Survey-to-Keyword assignment
```

特有 Dimensions：

```text
assignment_id, response_id, sentiment, keyword_id, keyword
```

#### 常用公開 Metric Options

| Metric Field + Aggregation | 意思 |
| --- | --- |
| `assignment_id` + `count` | Keyword assignments 數量 |
| `survey_id` + `distinct_count` | 至少有一個符合條件 Keyword 的不同 Survey 數量 |

適合回答：

- 最常見的 Keywords 是甚麼？
- 哪個 Keyword 最常出現在 Negative context？
- 有多少份不同 Survey 包含 `late`？
- 不同 Region 的 Keyword 分佈如何？

## 3. API 組合規則

對 `POST /analytics/query` 而言，一個基本查詢可以包含：

```text
一個 Semantic View
+ 同一 View 的 0–3 個 Dimensions
+ 同一 View 的剛好一個 Metric Field
+ 剛好一個 Aggregation
+ 同一 View 的 0–20 個 Filters
```

舊 `metrics: []` 格式已移除；缺少 `metric` 或 `aggregation`，或仍傳入
`metrics`，都會回傳 `422`。`aggregation` 使用完整名稱 `average`，不接受
`avg`。

欄位型別容許的 Aggregations：

| Field type | Aggregations |
| --- | --- |
| string / boolean | `count`, `distinct_count` |
| number | `count`, `distinct_count`, `sum`, `average`, `min`, `max`, `median` |
| date / time | `count`, `distinct_count`, `min`, `max` |

此外，該 `(logical metric target, aggregation)` 必須出現在目前 catalog 的
`metric_targets[semantic_view]`。型別合法但未發布，或同一 pair 對應多個
governed measure，都會回傳 `422`。

以下組合合法，因為所有成員都屬於 `survey_responses`：

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_format", "topic_sentiment"],
  "metric": "survey",
  "aggregation": "count"
}
```

以下組合不合法：

```json
{
  "semantic_view": "survey_topics",
  "dimensions": ["topic", "department"],
  "metric": "topic_assignment",
  "aggregation": "count"
}
```

原因是 `topic` 屬於 `survey_topics`，但 `department` 屬於
`survey_departments`。後端會回傳 `422`，防止跨 assignment grain 造成
many-to-many fan-out。

成功結果使用統一的 flat-row 格式。Dimension 保留自己的 key，唯一的
Metric 永遠輸出為 `value`：

```json
{
  "semantic_view": "survey_responses",
  "schema": {
    "dimensions": [
      {"field": "store_format", "label": "Store Format", "type": "string", "key": "store_format"}
    ],
    "time_dimension": null,
    "metric": {
      "field": "id",
      "aggregation": "count",
      "label": "Response Count",
      "type": "number",
      "key": "value"
    }
  },
  "rows": [{"store_format": "Mall", "value": 5}],
  "row_count": 1,
  "warnings": []
}
```

選擇時間欄位時，`schema.time_dimension` 會記錄 field、label、type、
granularity 和 key；沒有選擇時固定為 `null`。

## 4. 十份虛構 Survey

情緒縮寫：

```text
P = POSITIVE
N = NEGATIVE
U = NEUTRAL
M = MIXED
```

| Survey | Store | Format / Region | Overall sentiment | Topics | Departments | Keywords |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | A | Mall / HK Island | N | Delivery N, Speed N | Operations N, Digital N | late N, cold N |
| S2 | A | Mall / HK Island | P | Staff P | Service P | friendly P |
| S3 | A | Mall / HK Island | U | Cleanliness U | Operations U | clean U |
| S4 | B | Street / Kowloon | N | Delivery N | Logistics N | late N |
| S5 | B | Street / Kowloon | M | Food P, Delivery N | Kitchen P, Logistics N | tasty P, late N |
| S6 | C | Mall / New Territories | P | App P, Promotion P | Digital P, Marketing P | easy P, discount P |
| S7 | C | Mall / New Territories | N | Queue N, Staff U | Operations N, Service U | slow N |
| S8 | D | Airport / New Territories | U | Packaging U | Logistics U | package U |
| S9 | D | Airport / New Territories | P | App P | Digital P | fast P |
| S10 | E | Street / HK Island | M | Food P, Price N | Kitchen P, Marketing N | tasty P, expensive N |

基礎總數：

```text
Survey Responses      = 10
Topic Assignments      = 15
Department Assignments = 15
Keyword Assignments    = 14
```

四個總數不同，就是 Semantic View 必須分開的主要原因。

## 5. 同一 Semantic View，不同 Dimension

### 5.1 按 Overall Sentiment 分組

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["topic_sentiment"],
  "metric": "survey",
  "aggregation": "count"
}
```

| topic_sentiment | value |
| --- | ---: |
| POSITIVE | 3 |
| NEGATIVE | 3 |
| NEUTRAL | 2 |
| MIXED | 2 |

總數仍然是 10 responses。

### 5.2 按 Store Format 分組

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_format"],
  "metric": "survey",
  "aggregation": "count"
}
```

| store_format | value |
| --- | ---: |
| Mall | 5 |
| Street | 3 |
| Airport | 2 |

相同 Semantic View 和 Metric/Aggregation、但使用不同 Dimension，代表計數單位不變，
只是分組角度改變。

### 5.3 同時使用兩個 Dimensions

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_format", "topic_sentiment"],
  "metric": "survey",
  "aggregation": "count"
}
```

| store_format | topic_sentiment | value |
| --- | --- | ---: |
| Mall | POSITIVE | 2 |
| Mall | NEGATIVE | 2 |
| Mall | NEUTRAL | 1 |
| Street | NEGATIVE | 1 |
| Street | MIXED | 2 |
| Airport | POSITIVE | 1 |
| Airport | NEUTRAL | 1 |

增加 Dimension 不會改變 grain，但會令分組更細。

## 6. 不同 Semantic View，使用同一 Dimension

`store_format` 存在於全部四個 Views，但不同 grain 下的計數結果不同。

### 6.1 Response grain

```text
survey_responses + store_format + id/count
```

| Format | Count |
| --- | ---: |
| Mall | 5 |
| Street | 3 |
| Airport | 2 |

### 6.2 Topic assignment grain

```text
survey_topics + store_format + assignment_id/count
```

| Format | value（Topic assignment count） |
| --- | ---: |
| Mall | 8 |
| Street | 5 |
| Airport | 2 |

Mall 從 5 變成 8，因為：

```text
S1 = 2 Topics
S2 = 1 Topic
S3 = 1 Topic
S6 = 2 Topics
S7 = 2 Topics

合計 = 8 Topic assignments
```

### 6.3 Keyword assignment grain

```text
survey_keywords + store_format + assignment_id/count
```

| Format | value（Keyword assignment count） |
| --- | ---: |
| Mall | 7 |
| Street | 5 |
| Airport | 2 |

Mall 只有 7，因為 S7 有兩個 Topics，但只有一個 Keyword。

> 相同 Dimension 不代表相同計數單位；真正決定計數單位的是 Semantic View 和 Metric/Aggregation。

## 7. 不同 Semantic View 使用 `survey/count`

```json
{
  "semantic_view": "survey_topics",
  "dimensions": ["store_format"],
  "metric": "survey",
  "aggregation": "count"
}
```

| Format | value |
| --- | ---: |
| Mall | 5 |
| Street | 3 |
| Airport | 2 |

它與 `survey_responses` 的 `survey/count` 相同，只因例子中的十份 Survey 都有
至少一個 Topic。

假設 S8 沒有任何 Keyword：

```text
survey_responses:
Airport id/count = 2

survey_keywords:
Airport survey_id/distinct_count = 1
```

Assignment View 的 `survey_id/distinct_count` 表示至少存在一個符合條件
assignment 的 Surveys，不代表所有 Surveys。

## 8. `topic_sentiment` 在不同 Views 的差異

在 response grain：

```text
survey_responses + topic_sentiment + id/count

Positive = 3
Negative = 3
Neutral  = 2
Mixed    = 2
Total    = 10
```

在 Topic assignment grain：

```text
survey_topics + topic_sentiment + assignment_id/count
```

| Overall topic_sentiment | value（Topic assignment count） |
| --- | ---: |
| POSITIVE | 4 |
| NEGATIVE | 5 |
| NEUTRAL | 2 |
| MIXED | 4 |

這個結果總數是 15 Topic assignments。S1 是一份 Negative Survey，但有
Delivery 和 Speed 兩個 Topic assignments，所以在 response grain 貢獻 1，
在 Topic grain 貢獻 2。

這個組合合法，但回答的是：

> Negative Surveys 產生了多少個 Topic assignments？

如果問題是「有多少份 Negative Surveys」，應使用：

```text
survey_responses + topic_sentiment + id/count
```

或者在 Topic View 使用 `survey_id/distinct_count`，但後者只包含至少有一個
Topic assignment 的 Surveys。

## 9. `topic_sentiment` 與 `sentiment` 的差異

以 S5 為例：

```text
Overall Survey topic_sentiment = MIXED

Topic assignments:
Food     = POSITIVE
Delivery = NEGATIVE

Department assignments:
Kitchen   = POSITIVE
Logistics = NEGATIVE

Keyword assignments:
tasty = POSITIVE
late  = NEGATIVE
```

以下查詢會把 S5 的兩個 Topic assignments 都放在 `MIXED` 組：

```json
{
  "semantic_view": "survey_topics",
  "dimensions": ["topic_sentiment"],
  "metric": "topic_assignment",
  "aggregation": "count"
}
```

以下查詢則會把 Food 放在 `POSITIVE`、Delivery 放在 `NEGATIVE`：

```json
{
  "semantic_view": "survey_topics",
  "dimensions": ["sentiment"],
  "metric": "topic_assignment",
  "aggregation": "count"
}
```

| Dimension | 意思 |
| --- | --- |
| `topic_sentiment` | 整份 Survey Response 的情緒 |
| `sentiment` | 當前 Topic、Department 或 Keyword assignment 的情緒 |

`survey_responses` 沒有公開的 `sentiment` Dimension；response-level 查詢應
使用 `topic_sentiment`。

## 10. 合法但容易誤解的組合

| 組合 | 真正意思 | 風險或建議 |
| --- | --- | --- |
| `survey_topics + store_format + assignment_id/count` | 各 Format 的 Topic 數量 | 不是 Survey 數量 |
| `survey_topics + topic_sentiment + assignment_id/count` | 各整體情緒所產生的 Topic assignments | Topic 多的 Survey 權重較高 |
| `survey_topics + survey_id + assignment_id/count` | 每份 Survey 有多少 Topics | 通常適合 Table，不適合總覽 Chart |
| `survey_keywords + comment + assignment_id/count` | 每段 Comment 產生多少 Keyword assignments | Comment 高基數，而且同一 Comment 會重複 |
| `survey_departments + cls + assignment_id/count` | 每個 CLS 值產生多少 Department assignments | 不是 Survey-level CLS 分佈 |

若要 Survey-level CLS 分佈，應使用：

```text
survey_responses + cls + id/count
```

## 11. 明確不合法的組合

| 組合 | 結果 | 原因 |
| --- | --- | --- |
| `survey_responses + topic + id/count` | `422` | `topic` 不屬於 response view |
| `survey_responses + sentiment + id/count` | `422` | response view 應使用 `topic_sentiment` |
| `survey_topics + department + assignment_id/count` | `422` | Department 屬於另一個 assignment view |
| `survey_topics + keyword + assignment_id/count` | `422` | Keyword 屬於另一個 assignment view |
| `survey_topics + topic + id/count` | `422` | Topic view 沒有 `id` metric option |
| `survey_responses + store_format + assignment_id/count` | `422` | Response view 沒有 `assignment_id` |
| `survey_responses + cls/avg` | `422` | Aggregation 必須使用完整名稱 `average` |
| 未出現在 `metric_targets` 的 target/aggregation | `422` | 只可使用唯一而且已發布的 pair |
| 同時查詢 `topic`、`department`、`keyword` | `422` | 系統禁止跨 assignment grain fan-out |
| `reported_at` 同時放入 `dimensions` 和 `time_dimension` | `422` | 時間欄位不可重複選取 |

## 12. Assignment Views 為何沒有公開 `cls/average`

Assignment Views 雖然帶有 `cls` Dimension，但目前的 `metric_targets`
沒有發布 `cls/average` 或 `topic_sentiment_score/average`。

假設：

```text
S1 CLS = 20，有 2 Topics
S2 CLS = 80，有 1 Topic
```

Response-level 平均是：

```text
(20 + 80) / 2 = 50
```

如果直接在 Topic assignment rows 上平均：

```text
(20 + 20 + 80) / 3 = 40
```

S1 因為有兩個 Topics 而被重複加權，平均值由 50 變成 40。因此
Survey-level score 應優先在 `survey_responses` 計算。

如果需要「每個 Topic 對應 Surveys 的平均 CLS」，必須先明確定義：

- 是否按 assignment 加權；
- 每份 Survey 是否只計一次；
- 多 Topic Survey 是否平均分配權重。

不能直接假設 assignment-row average 是正確答案。

## 13. Chart Dimension／Metric 形狀限制

即使 `/analytics/query` 合法，也不代表可以發布成所有 Chart 類型。

| Query shape | 可用 Chart |
| --- | --- |
| 無 time、0 Dimensions | `kpi`, `table` |
| 無 time、1 Dimension | `bar`, `column`, `pie`, `donut`, `table` |
| 無 time、2 Dimensions | `stacked_bar`, `heatmap`, `table` |
| 無 time、3 Dimensions | `table` |
| 有 granular time、0–1 普通 Dimensions | `line`, `area`, `table` |
| 有 granular time、2–3 普通 Dimensions | `table` |

所有 Chart 都只有一個 Metric/Aggregation。`line`／`area` 必須同時有
`time_dimension` 和 `time_granularity`。除了 `table` 和 `kpi`，Metric
結果必須是 number。`scatter` 與 `store_map` 已移除。

例如以下 aggregate query 合法：

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_format", "region"],
  "metric": "survey",
  "aggregation": "count"
}
```

但不能用作 Pie Chart，因為 Pie 只接受一個 Dimension。它可以用於
Table、Stacked Bar 或 Heatmap。

## 14. 實際選擇流程

### 第一步：選擇計算單位

| 想計算的單位 | Semantic View |
| --- | --- |
| Survey Responses | `survey_responses` |
| Topic assignments | `survey_topics` |
| Department assignments | `survey_departments` |
| Keyword assignments | `survey_keywords` |

### 第二步：選擇 Metric Target 與 Aggregation

| 問題 | Metric Target + Aggregation |
| --- | --- |
| Topic／Department／Keyword 出現了多少次？ | 對應的 `<entity>_assignment` + `count` |
| 有多少份不同 Survey 涉及它？ | `survey` + `count` |
| 有多少份 Survey Responses？ | `survey` + `count` |
| Assignment sentiment 數量 | 加入 `sentiment` Dimension，再使用對應的 assignment target + `count` |

### 第三步：選擇分類角度

這才是 Dimension，例如：

```text
store_format, region, topic_sentiment, topic, department, keyword,
reported_at, channel_name
```

## 15. Catalog、Availability 與執行狀態

本手冊列出的是內建 catalog。管理員發布的自訂 Fields 或 governed Metrics 可能令
實際 catalog 增加更多成員。前端應以以下 endpoint 作為當前部署的最終
allowlist：

```http
GET /analytics/catalog
```

Catalog response 的 `combinations` 是正式、機器可讀的組合合約：

```text
combinations.query          = query 數量及同 View 限制
metric_targets              = 每個 View 可執行的業務 Target／Aggregation methods
combinations.semantic_views = 每個 View 的 grain 和 Dimensions
combinations.charts         = 每種 Chart 的 Dimension／Metric shape
```

前端應直接使用這個結構建立選擇器。例如選定 `survey_topics` 後，只顯示
該項目的 `dimensions` 與 `metric_targets[semantic_view]`；選好 target/method
後再呼叫 `/analytics/query-capabilities`，不要在前端維護另一份手寫清單。

如果產品只希望提供有限、已驗證的查詢，而不是讓使用者自由排列所有
members，應使用：

```http
GET /analytics/query-combinations
GET /analytics/query-combinations?semantic_view=survey_responses
```

每個項目的 `query` 都可以直接送到 `POST /analytics/query`，並附有
`compatible_chart_types` 和 `allowed_overrides`。前端只應修改
`allowed_overrides` 列出的 filters、日期範圍、timezone、order 或 limit；
不要自行把 time dimension 再加入 `dimensions`。例如每日趨勢模板會使用
`time_dimension=reported_at` 和 `time_granularity=day`，而
`dimensions` 明確保持為空陣列。

一個成員出現在 catalog，只代表它已發布及可查詢。要確認該 BU 是否真的
有非空資料，應再查詢：

```http
GET /analytics/catalog/availability?semantic_view=survey_responses
```

最後，即使 Semantic View、Dimension 和 Metric 組合完全合法，仍可能因
Cube pre-aggregation 尚未建立或 analytics dependency 暫時不可用而執行
失敗。這是部署或資料準備問題，不代表語義組合錯誤。
