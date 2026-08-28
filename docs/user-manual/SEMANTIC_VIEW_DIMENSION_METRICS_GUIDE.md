# Semantic View、Dimension 與 Metric 使用手冊

本手冊說明 CLSense governed analytics 中 `semantic_view`、Dimension 和
Metric 的組合規則。它同時區分三種情況：

1. API 語法是否合法；
2. 組合的分析意義是否正確；
3. 組合是否符合指定 Chart 類型的形狀要求。

最重要的選擇次序是：

> 先選資料粒度 Semantic View，再選計數或計算方式 Metric，最後才選分組方式 Dimension。

相關文件：

- [Analytics API reference](../ANALYTICS_API_REFERENCE.md)
- [Frontend dashboard analytics workflow](../FRONTEND_DASHBOARD_ANALYTICS_WORKFLOW.md)
- [Dashboard analytics migration](../DASHBOARD_ANALYTICS_MIGRATION.md)

## 1. 三個核心概念

```text
Semantic View = 結果底層的一行代表甚麼
Metric        = 要數甚麼或計算甚麼
Dimension     = 按甚麼分類或分組
```

例如：

```text
問題：每個 Topic 被多少份不同 Survey 提及？

Semantic View = survey_topics
Dimension     = topic
Metric        = distinct_survey_count
```

不要使用：

```text
survey_responses + topic + response_count
```

因為 `topic` 並不屬於 response-level grain。

## 2. Semantic View 完整組合矩陣

### 2.1 `survey_responses`

資料粒度：

```text
一行 = 一份未刪除的 Survey Response
```

#### 內建 Metrics

| Metric | 意思 |
| --- | --- |
| `response_count` | 問卷回覆數量 |
| `distinct_survey_count` | 不同 response `id` 數量，通常與 `response_count` 相同 |
| `responding_store_count` | 符合目前 response filters／日期範圍、且至少有一份回覆的不同 `store_key` 數量；不包括零回覆 Store |
| `cls_sum` | CLS 總和 |
| `cls_average` | CLS 平均值 |
| `topic_sentiment_score_sum` | Topic sentiment score 總和 |
| `topic_sentiment_score_average` | Topic sentiment score 平均值 |
| `median_topic_sentiment_score` | Topic sentiment score 中位數 |
| `first_reported_at` | 最早回報時間 |
| `last_reported_at` | 最後回報時間 |
| `last_updated_at` | 最後更新時間 |
| `topic_sentiment_positive_count` | 整份回覆為 Positive 的數量 |
| `topic_sentiment_negative_count` | 整份回覆為 Negative 的數量 |
| `topic_sentiment_neutral_count` | 整份回覆為 Neutral 的數量 |
| `topic_sentiment_mixed_count` | 整份回覆為 Mixed 的數量 |

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

#### 內建 Metrics

| Metric | 意思 |
| --- | --- |
| `assignment_count` | Topic assignments 數量 |
| `distinct_survey_count` | 至少有一個符合條件 Topic assignment 的不同 Survey 數量 |
| `topic_assignment_positive_count` | Positive Topic assignments |
| `topic_assignment_negative_count` | Negative Topic assignments |
| `topic_assignment_neutral_count` | Neutral Topic assignments |

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

#### 內建 Metrics

| Metric | 意思 |
| --- | --- |
| `assignment_count` | Department assignments 數量 |
| `distinct_survey_count` | 至少有一個符合條件 Department assignment 的不同 Survey 數量 |
| `department_assignment_positive_count` | Positive Department assignments |
| `department_assignment_negative_count` | Negative Department assignments |
| `department_assignment_neutral_count` | Neutral Department assignments |

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

#### 內建 Metrics

| Metric | 意思 |
| --- | --- |
| `assignment_count` | Keyword assignments 數量 |
| `distinct_survey_count` | 至少有一個符合條件 Keyword 的不同 Survey 數量 |
| `keyword_assignment_positive_count` | Positive Keyword assignments |
| `keyword_assignment_negative_count` | Negative Keyword assignments |
| `keyword_assignment_neutral_count` | Neutral Keyword assignments |

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
+ 同一 View 的 0–5 個 Metrics
+ 同一 View 的 0–20 個 Filters
```

至少需要一個 Dimension、Metric 或 `time_dimension`。

以下組合合法，因為所有成員都屬於 `survey_responses`：

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_format", "topic_sentiment"],
  "metrics": ["response_count", "cls_average"]
}
```

以下組合不合法：

```json
{
  "semantic_view": "survey_topics",
  "dimensions": ["topic", "department"],
  "metrics": ["assignment_count"]
}
```

原因是 `topic` 屬於 `survey_topics`，但 `department` 屬於
`survey_departments`。後端會回傳 `422`，防止跨 assignment grain 造成
many-to-many fan-out。

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
  "metrics": ["response_count"]
}
```

| topic_sentiment | response_count |
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
  "metrics": ["response_count"]
}
```

| store_format | response_count |
| --- | ---: |
| Mall | 5 |
| Street | 3 |
| Airport | 2 |

相同 Semantic View 和 Metric、但使用不同 Dimension，代表計數單位不變，
只是分組角度改變。

### 5.3 同時使用兩個 Dimensions

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_format", "topic_sentiment"],
  "metrics": ["response_count"]
}
```

| store_format | topic_sentiment | response_count |
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
survey_responses + store_format + response_count
```

| Format | Count |
| --- | ---: |
| Mall | 5 |
| Street | 3 |
| Airport | 2 |

### 6.2 Topic assignment grain

```text
survey_topics + store_format + assignment_count
```

| Format | Topic assignment_count |
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
survey_keywords + store_format + assignment_count
```

| Format | Keyword assignment_count |
| --- | ---: |
| Mall | 7 |
| Street | 5 |
| Airport | 2 |

Mall 只有 7，因為 S7 有兩個 Topics，但只有一個 Keyword。

> 相同 Dimension 不代表相同計數單位；真正決定計數單位的是 Semantic View 和 Metric。

## 7. 不同 Semantic View 使用 `distinct_survey_count`

```json
{
  "semantic_view": "survey_topics",
  "dimensions": ["store_format"],
  "metrics": ["distinct_survey_count"]
}
```

| Format | distinct_survey_count |
| --- | ---: |
| Mall | 5 |
| Street | 3 |
| Airport | 2 |

它與 `survey_responses.response_count` 相同，只因例子中的十份 Survey 都有
至少一個 Topic。

假設 S8 沒有任何 Keyword：

```text
survey_responses:
Airport response_count = 2

survey_keywords:
Airport distinct_survey_count = 1
```

Assignment View 的 `distinct_survey_count` 表示至少存在一個符合條件
assignment 的 Surveys，不代表所有 Surveys。

## 8. `topic_sentiment` 在不同 Views 的差異

在 response grain：

```text
survey_responses + topic_sentiment + response_count

Positive = 3
Negative = 3
Neutral  = 2
Mixed    = 2
Total    = 10
```

在 Topic assignment grain：

```text
survey_topics + topic_sentiment + assignment_count
```

| Overall topic_sentiment | Topic assignment_count |
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
survey_responses + topic_sentiment + response_count
```

或者在 Topic View 使用 `distinct_survey_count`，但後者只包含至少有一個
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
  "metrics": ["assignment_count"]
}
```

以下查詢則會把 Food 放在 `POSITIVE`、Delivery 放在 `NEGATIVE`：

```json
{
  "semantic_view": "survey_topics",
  "dimensions": ["sentiment"],
  "metrics": ["assignment_count"]
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
| `survey_topics + store_format + assignment_count` | 各 Format 的 Topic 數量 | 不是 Survey 數量 |
| `survey_topics + topic_sentiment + assignment_count` | 各整體情緒所產生的 Topic assignments | Topic 多的 Survey 權重較高 |
| `survey_topics + survey_id + assignment_count` | 每份 Survey 有多少 Topics | 通常適合 Table，不適合總覽 Chart |
| `survey_keywords + comment + assignment_count` | 每段 Comment 產生多少 Keyword assignments | Comment 高基數，而且同一 Comment 會重複 |
| `survey_departments + cls + assignment_count` | 每個 CLS 值產生多少 Department assignments | 不是 Survey-level CLS 分佈 |

若要 Survey-level CLS 分佈，應使用：

```text
survey_responses + cls + response_count
```

## 11. 明確不合法的組合

| 組合 | 結果 | 原因 |
| --- | --- | --- |
| `survey_responses + topic + response_count` | `422` | `topic` 不屬於 response view |
| `survey_responses + sentiment + response_count` | `422` | response view 應使用 `topic_sentiment` |
| `survey_topics + department + assignment_count` | `422` | Department 屬於另一個 assignment view |
| `survey_topics + keyword + assignment_count` | `422` | Keyword 屬於另一個 assignment view |
| `survey_topics + topic + response_count` | `422` | Topic view 沒有 `response_count` |
| `survey_responses + store_format + assignment_count` | `422` | Response view 沒有 `assignment_count` |
| `survey_departments + topic_assignment_negative_count` | `422` | Metric 屬於 Topic view |
| `survey_keywords + department_assignment_negative_count` | `422` | Metric 屬於 Department view |
| 同時查詢 `topic`、`department`、`keyword` | `422` | 系統禁止跨 assignment grain fan-out |
| `reported_at` 同時放入 `dimensions` 和 `time_dimension` | `422` | 時間欄位不可重複選取 |

## 12. Assignment Views 為何沒有內建 `cls_average`

Assignment Views 雖然帶有 `cls` Dimension，但目前沒有內建
`cls_average` 或 `topic_sentiment_score_average`。

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

| Chart | Dimension 要求 | Metric 要求 |
| --- | --- | --- |
| `kpi` | 0 | 1 |
| `table` | 0–3 | 0–5；兩者合計至少一個 |
| `bar` / `column` | 1–3 | 1–5 |
| `line` / `area` | 1–3，包括可選 time dimension | 1–5 |
| `stacked_bar` | 正好 2 | 1–5 |
| `pie` / `donut` | 正好 1 | 正好 1 |
| `scatter` | 0–1 | 正好 2 |
| `heatmap` | 正好 2 | 正好 1 |
| `store_map` | 必須是 `store_key`, `store_name`, `latitude`, `longitude` | 正好 1 |

例如以下 aggregate query 合法：

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_format", "region"],
  "metrics": ["response_count"]
}
```

但不能用作 Pie Chart，因為 Pie 只接受一個 Dimension。它可以用於
Table、Bar、Column、Stacked Bar 或 Heatmap。

## 14. 實際選擇流程

### 第一步：選擇計算單位

| 想計算的單位 | Semantic View |
| --- | --- |
| Survey Responses | `survey_responses` |
| Topic assignments | `survey_topics` |
| Department assignments | `survey_departments` |
| Keyword assignments | `survey_keywords` |

### 第二步：選擇 Metric

| 問題 | Metric |
| --- | --- |
| 出現了多少次？ | `assignment_count` |
| 有多少份不同 Survey 涉及它？ | `distinct_survey_count` |
| 有多少份 Survey Responses？ | `response_count` |
| Assignment sentiment 數量 | 對應的 `*_assignment_*_count` |

### 第三步：選擇分類角度

這才是 Dimension，例如：

```text
store_format, region, topic_sentiment, topic, department, keyword,
reported_at, channel_name
```

## 15. Catalog、Availability 與執行狀態

本手冊列出的是內建 catalog。管理員發布的自訂 Fields 或 Metrics 可能令
實際 catalog 增加更多成員。前端應以以下 endpoint 作為當前部署的最終
allowlist：

```http
GET /analytics/catalog
```

Catalog response 的 `combinations` 是正式、機器可讀的組合合約：

```text
combinations.query          = query 數量及同 View 限制
combinations.semantic_views = 每個 View 的 grain、Dimensions 和 Metrics
combinations.charts         = 每種 Chart 的 Dimension／Metric shape
```

前端應直接使用這個結構建立選擇器。例如選定 `survey_topics` 後，只顯示
該項目的 `dimensions` 和 `metrics`；不要在前端再維護另一份手寫清單。

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
