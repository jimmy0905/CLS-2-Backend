# 以受治理的 Analytics 查詢取代儀表板路由

> 文件狀態：已完成遷移的歷史 query book；不是 endpoint canonical reference
>
> 導覽：[Backend 文件索引](README.md)
>
> 最後核對：2026-09-06

> 此 query book 使用 [目標優先的 Analytics 查詢契約](ANALYTICS_GOAL_FIRST_CONTRACT.md) 所述的目前 logical-target contract。

這是已移除 `/dashboard/*` API 的歷史遷移 query book。舊路徑現時回傳 `404`；現行 client 使用
`POST /analytics/query` 及受治理的 semantic catalog。文件以 `wtchk_cls` 資料模型為準，其標準
response sentiment 是 `surveys.topic_sentiment`；不使用舊有的 `surveys.sentiment` 欄位。

如需從 catalog、field availability、filter option 到已發佈 chart data 的前端初始化順序，請參閱[前端儀表板 Analytics 工作流程](FRONTEND_DASHBOARD_ANALYTICS_WORKFLOW.md)。

沒有單一請求能取代所有 dashboard card：每張卡片提問時使用的 row grain 不同。以下請求以內建 single-metric catalog 取代各端點。前端可在加入目前共用 filter 後，直接執行請求本文。

本機設定檔的 Base URL：

```text
http://localhost:8000/wtchk/api
```

所有範例皆需：

```http
Authorization: Bearer <access-token>
Content-Type: application/json
```

## 1. 單一 Metric 儀表板契約

每個 aggregate request 恰好選取一個邏輯 `metric` target 與一個 `aggregation`；已移除的 `metrics: []` 欄位會被拒絕。常用 pair 包含 `survey/count`、`topic_assignment/count`、`department_assignment/count`、`keyword_assignment/count`、`store/count`、`cls/average` 及 `topic_sentiment_score/average`。只可使用 `GET /analytics/catalog` 的 `metric_targets` 下所宣告的方法。

`store/count` 會在符合條件的 response row 中計算相異 store。它計算目前 response filter 與 date range 所涵蓋的門市；刻意不計入零筆相符 response 的門市。

經篩選、加權、變異數、標準差、百分位數與 confidence-interval 的受治理 metric 可保留於 admin／Cube metadata，但不屬於公開 query option。情緒分布現在會依相關 sentiment Dimension 分組並使用一般 row count，而非在同一請求中選取多個 filtered metric。

### Response-level 情緒計數

Response-level 的受治理 metric：`topic_sentiment_positive_count`、`topic_sentiment_negative_count`、`topic_sentiment_neutral_count` 與 `topic_sentiment_mixed_count`。它們無需設定。以下範例保留作為建立可比較、BU 專屬 filtered metric 的參考。

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

這些名稱保留在 governance metadata 中，而非可接受的公開 query `metric` field。其歷史定義如下：

| Slug | 篩選值 |
| --- | --- |
| `topic_sentiment_positive_count` | `POSITIVE` |
| `topic_sentiment_negative_count` | `NEGATIVE` |
| `topic_sentiment_neutral_count` | `NEUTRAL` |
| `topic_sentiment_mixed_count` | `MIXED` |

### Assignment-level 情緒計數

Department、topic 與 keyword table 各自有其 assignment `sentiment`。下列標準 `filtered_count` metric 亦為內建：

| Semantic View | Positive | Negative | Neutral |
| --- | --- | --- | --- |
| `survey_topics` | `topic_assignment_positive_count` | `topic_assignment_negative_count` | `topic_assignment_neutral_count` |
| `survey_departments` | `department_assignment_positive_count` | `department_assignment_negative_count` | `department_assignment_neutral_count` |
| `survey_keywords` | `keyword_assignment_positive_count` | `keyword_assignment_negative_count` | `keyword_assignment_neutral_count` |

對此標準組合以外的 BU 專屬 filtered metric，請以以下本文作範本（並使用新的唯一 slug）：

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

每個回傳的 BU 專屬 metric `id`，均應先驗證並發佈，再啟用 catalog version：

```bash
curl -X POST "http://localhost:8000/wtchk/api/admin/analytics/metrics/<id>/validate" \
  -H 'Authorization: Bearer <admin-token>'
curl -X POST "http://localhost:8000/wtchk/api/admin/analytics/metrics/<id>/publish" \
  -H 'Authorization: Bearer <admin-token>'
curl -X POST 'http://localhost:8000/wtchk/api/admin/analytics/catalog/publish' \
  -H 'Authorization: Bearer <admin-token>' -H 'Content-Type: application/json' \
  -d '{"description":"Dashboard semantic metric pack"}'
```

部署後，使用 `GET /analytics/catalog` 驗證可執行的 `metric_targets`。Metric 仍可在 admin UI 中受治理，但只有唯一的 logical target／method mapping 會進入公開 query contract。

## 2. 共用 Filter 轉換

Semantic API 接受 JSON 本文中的 filter。將舊 dashboard query parameter 直接轉換為受治理 member slug。例如，下列舊 filter 目的：

```text
regions=Kowloon&store_formats=Mall&topic_sentiments=NEGATIVE
from_date=2024-08-01T00:00:00Z&to_date=2024-09-01T00:00:00Z
```

轉為：

```json
"filters": [
  {"member": "region", "operator": "equals", "value": "Kowloon"},
  {"member": "store_format", "operator": "equals", "value": "Mall"},
  {"member": "topic_sentiment", "operator": "equals", "value": "NEGATIVE"}
],
"time_dimension": "reported_at",
"time_range": ["2024-08-01T00:00:00Z", "2024-09-01T00:00:00Z"]
```

多選時使用 `in` 加上 `values`：

```json
{"member": "store_format", "operator": "in", "values": ["Mall", "Commercial"]}
```

新 API 會刻意區分 assignment view。不得在查詢某個 assignment view 時套用 `topic`／`keyword`／`department` assignment filter，否則會重新引入 many-to-many fan-out。應將這些 filter control 限制在相符的 view。

## 3. Dashboard 端點替代方案

以下每個請求中，`filters` 可省略，或由前一節的共用 filter 取代。`limit` 是回傳 aggregate group 的最大數量，不是 survey row 上限。

### `GET /dashboard/sentiment-distribution`（情緒分布）

每個 reported day 與 sentiment 各一列，以 `surveys.topic_sentiment` 為準：

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["topic_sentiment"],
  "metric": "survey",
  "aggregation": "count",
  "time_dimension": "reported_at",
  "time_granularity": "day",
  "time_range": ["2024-08-01T00:00:00Z", "2024-09-01T00:00:00Z"],
  "order": [{"member": "reported_at", "direction": "asc"}],
  "limit": 1000
}
```

回傳的 `reported_at` 是**日 bucket 的起點**（例如 `2024-08-01T00:00:00.000`），而不是第一份相符 survey 的時間。Metric value 會彙總該日內所有相符的 response。

### `GET /dashboard/store-distribution`（門市分布）

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_name_english", "topic_sentiment"],
  "metric": "survey",
  "aggregation": "count",
  "filters": [
    {"member": "reported_at", "operator": "between", "values": ["2024-08-01T00:00:00Z", "2024-09-01T00:00:00Z"]}
  ],
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 1000
}
```

當門市 group 超過 1,000 個時，以 `POST /analytics/filter-options` 搭配 `member: "store_key"` 並遞增其 `cursor` 來分頁 selector；分析 aggregate query 刻意限制為最多 1,000 列。完整報表請使用受治理的 CSV/XLSX export。filter-options cursor contract 請參閱 API reference。

### `GET /dashboard/store-column-sentiment-distribution`（門市欄位情緒分布）

這是相同的 response-level request，只是將所選 store field 作為唯一 dimension。既有的 `column=store_format` 情境：

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["store_format", "topic_sentiment"],
  "metric": "survey",
  "aggregation": "count",
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 1000
}
```

可替換為任何已發佈 store dimension，例如 `region`、`area`、`district`、`area_manager`、`store_brand`、`is_closed` 或 `store_open_date`。不可從不受信任的用戶端文字建構 member name：只能使用 `GET /analytics/catalog` 回傳的 slug。

### `GET /dashboard/channel-and-delivery-service-distribution`（渠道與外送服務分布）

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["channel_name", "delivery_service_name", "topic_sentiment"],
  "metric": "survey",
  "aggregation": "count",
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 1000
}
```

### `GET /dashboard/topic-sentiment-score`（主題情緒分數）

執行情緒計數請求：

```json
{
  "semantic_view": "survey_responses",
  "dimensions": ["topic_sentiment"],
  "metric": "survey",
  "aggregation": "count",
  "limit": 10
}
```

再執行第二個請求取得整體平均值：

```json
{
  "semantic_view": "survey_responses",
  "metric": "topic_sentiment_score",
  "aggregation": "average",
  "limit": 1
}
```

若為 `average_mix_topic_score`，執行第三個請求，包含相同的共用 filter 及以下 filter：

```json
{
  "semantic_view": "survey_responses",
  "metric": "topic_sentiment_score",
  "aggregation": "average",
  "filters": [{"member": "topic_sentiment", "operator": "equals", "value": "MIXED"}],
  "limit": 1
}
```

這些拆分請求是刻意設計：每個 aggregate 都只有一個 metric field 與 aggregation。

### `GET /dashboard/topic-distribution`（主題分布）

使用 topic-assignment grain。這些計數反映 `survey_topics.sentiment`，而非 response 的 `topic_sentiment`：

```json
{
  "semantic_view": "survey_topics",
  "dimensions": ["topic", "sentiment"],
  "metric": "topic_assignment",
  "aggregation": "count",
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 1000
}
```

### `GET /dashboard/department-distribution`（部門分布）

使用 department-assignment grain。這些計數反映 `survey_departments.sentiment`：

```json
{
  "semantic_view": "survey_departments",
  "dimensions": ["department", "sentiment"],
  "metric": "department_assignment",
  "aggregation": "count",
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 1000
}
```

### `GET /dashboard/keyword-analysis?k=10`（關鍵字分析）

使用 keyword-assignment grain。`limit: 10` 取代 `k=10`：

```json
{
  "semantic_view": "survey_keywords",
  "dimensions": ["keyword", "sentiment"],
  "metric": "keyword_assignment",
  "aggregation": "count",
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 10
}
```

### `GET /dashboard/data-coverage`（資料涵蓋範圍）

執行兩個 KPI query；第一個使用 `reported_at/min`：

```json
{
  "semantic_view": "survey_responses",
  "metric": "reported_at",
  "aggregation": "min",
  "limit": 1
}
```

第二個使用相同本文，並將 `"aggregation": "max"`。

### `GET /dashboard/last-updated-date`（最後更新日期）

直接查詢最新的有效更新：

```json
{
  "semantic_view": "survey_responses",
  "metric": "updated_at",
  "aggregation": "max",
  "limit": 1
}
```

Semantic view 刻意排除軟刪除 survey。因此，這代表有效 survey row 中的最新更新；舊端點沒有套用此排除。對報表而言，這通常是更安全的意義。

## 4. 移除 `/dashboard/*` 時已處理的差異

以上 semantic request 已取代分析計算。Hard removal 前已對下列三項舊 response-shaping 行為作出明確 frontend／product 決策：

1. **`total_count_for_option`。** 舊 distribution route 在計算 option total 時會移除自身 selected-field filter。請以目標 field 呼叫 `POST /analytics/filter-options`，傳入所有*其他*共用 filter，但排除目標 field filter。其 `count` 即為等效 option total。範例：對 store-format selector，傳入 region 與 date filter，但不要傳入 `store_format` filter。
2. **零計數 master value。** 舊 store／topic／department route 即使沒有相符 survey，也會回傳 master-data entry 並以零填補。Semantic aggregate query 刻意只回傳觀察到的 group。當 UI 必須顯示 inactive store 或未使用的 topic／department definition 時，請為對應 master resource 使用 `POST /analytics/records/query`，再將其 value 與 aggregate result join／zero-fill。
3. **跨 assignment filter。** 舊 generic filter object 可在繪製 department／keyword card 時套用 topic filter。Semantic layer 禁止這種容易 fan-out 的組合。應將 topic、department 與 keyword filter 限制於各自 card，或在引入跨 assignment analysis 前定義已核准的 response-level derived cohort。

完成上述三項 UI 調整並發佈 metric pack 後，semantic API 即可為現有的每張 dashboard card 提供資料，無須呼叫 `/dashboard/*`。
