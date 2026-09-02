# 舊端點至 Cube 查詢對照表

> 文件狀態：歷史相容性紀錄；pre-0012 request 不可執行
>
> 導覽：[Backend 文件索引](README.md)
>
> 現行契約：[Analytics API 參考](ANALYTICS_API_REFERENCE.md)

本文件保留 pre-0012 舊儀表板端點的遷移脈絡，供歷史等效性工作使用。舊範例中的 `metrics: []` 為已淘汰的多 metric 契約，**不可執行**。目前可直接送出的單一 metric 請求，請使用[儀表板 Analytics 遷移指南](DASHBOARD_ANALYTICS_MIGRATION.md)。

目前 `POST /analytics/query` 契約要求 0–3 個 `dimensions`、一個邏輯 `metric` 與一個 `aggregation`；彙總值一律在 `value`：

```json
{
  "dimensions": ["topic_sentiment"],
  "metric": "survey",
  "aggregation": "count",
  "order": [{"member": "value", "direction": "desc"}]
}
```

所有目前請求均需要一般應用程式 access token：

```text
POST http://localhost:8000/wtchk/api/analytics/query
Authorization: Bearer <access-token>
Content-Type: application/json
```

## 共用 Filter 轉換

舊 dashboard route 經由 `FilterRequest` 接受 query parameter。多選時，使用對應的受治理 member 搭配 `in`：

| 舊 query parameter | 受治理 member | 範例 |
| --- | --- | --- |
| `store_keys` | `store_key` | `{"member":"store_key","operator":"in","values":[101,102]}` |
| `store_english_names` | `store_name_english` | `{"member":"store_name_english","operator":"in","values":["Central"]}` |
| `store_local_names` | `store_name_local` | `{"member":"store_name_local","operator":"in","values":["中環"]}` |
| 門市屬性（`regions`、`store_formats`、`areas` 等） | 相同的單數 member（`region`、`store_format`、`area` 等） | `{"member":"region","operator":"equals","value":"North"}` |
| `channel_ids`／`channel_names` | `channel_id`／`channel_name` | `{"member":"channel_name","operator":"in","values":["Web"]}` |
| `delivery_service_ids`／`delivery_service_names` | `delivery_service_id`／`delivery_service_name` | `{"member":"delivery_service_name","operator":"in","values":["Foodpanda"]}` |
| `topics` | `survey_topics` 的 `topic` | `{"member":"topic","operator":"in","values":["Delivery"]}` |
| `keywords` | `survey_keywords` 的 `keyword` | `{"member":"keyword","operator":"in","values":["late"]}` |
| `department_ids`／`department_names` | `survey_departments` 的 `department_id`／`department` | `{"member":"department","operator":"in","values":["Service"]}` |
| `topic_sentiments` | `topic_sentiment` | `{"member":"topic_sentiment","operator":"in","values":["NEGATIVE","MIXED"]}` |
| `min_topic_sentiment_score`／`max_topic_sentiment_score` | `topic_sentiment_score` | `{"member":"topic_sentiment_score","operator":"between","values":[-1,1]}` |
| `min_cls`／`max_cls` | `cls` | `{"member":"cls","operator":"between","values":[0,100]}` |
| `from_date`／`to_date` | `time_dimension` + `time_range` | 見下列時間範例 |

舊日期範圍在 `from_date` 為包含、在 `to_date` 為排除。Cube 請使用相同的半開區間：

```json
{
  "time_dimension": "reported_at",
  "time_range": ["2024-08-01T00:00:00Z", "2024-09-01T00:00:00Z"],
  "timezone": "Asia/Hong_Kong"
}
```

舊清單 filter 只有一個值時，`equals` 等同單元素 `in`。Assignment filter 必須限於相符的 assignment view。例如，不得對 department query 套用 `topic` filter；舊 SQL path 可建立這種 cross-assignment join，但受治理模型刻意拒絕。

## 預設圖表呈現

每個下列 query 都是指定圖表的預設資料契約。預設 chart object 由 Alembic revision `0012_single_metric_charts` 建立。前端應從 `GET /analytics/charts/published` 載入已發佈 chart definition，再呼叫 `POST /analytics/charts/{chart_id}/data`；`POST /analytics/query` 請求本文則作為 chart 正式定義及 chart 發佈期間的輔助工具。

遷移會建立以下 chart slug：

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

`store-column` route 在舊 API 中可參數化，因此 `dashboard_store_format_distribution` 是建立的預設圖。其他門市欄位圖可由同一定義改用另一個 allowlisted store dimension 建立。

| 舊端點 | 替代的已發佈圖表 | 使用的受治理查詢 |
| --- | --- | --- |
| `/dashboard/sentiment-distribution` | `dashboard_sentiment_distribution` | `survey_responses` 依 `topic_sentiment` 及 `reported_at/day` 分組，`survey/count`。 |
| `/dashboard/store-distribution` | `dashboard_store_distribution` | `survey_responses` 依門市及 `topic_sentiment` 分組，`survey/count`。 |
| `/dashboard/store-column-sentiment-distribution` | `dashboard_store_format_distribution` | `survey_responses` 依已允許的門市 dimension 與 `topic_sentiment` 分組，`survey/count`。 |
| `/dashboard/channel-and-delivery-service-distribution` | `dashboard_channel_delivery_distribution` | `survey_responses` 依渠道、外送服務及 `topic_sentiment` 分組，`survey/count`。 |
| `/dashboard/topic-sentiment-score` | `dashboard_topic_sentiment_counts`、`dashboard_overall_topic_sentiment_score`、`dashboard_mixed_topic_sentiment_score` | 情緒計數、整體平均分數及只限 `MIXED` 的平均分數，各以一個 query 提供。 |
| `/dashboard/topic-distribution` | `dashboard_topic_distribution` | `survey_topics` 依 `topic` 與 assignment `sentiment` 分組，`topic_assignment/count`。 |
| `/dashboard/department-distribution` | `dashboard_department_distribution` | `survey_departments` 依 `department` 與 assignment `sentiment` 分組，`department_assignment/count`。 |
| `/dashboard/keyword-analysis?k=10` | `dashboard_keyword_analysis` | `survey_keywords` 依 `keyword` 與 assignment `sentiment` 分組，`keyword_assignment/count`，並使用 `limit: 10`。 |
| `/dashboard/data-coverage` | `dashboard_first_reported_at`、`dashboard_last_reported_at` | 兩個 KPI query：`reported_at/min` 與 `reported_at/max`。 |
| `/dashboard/last-updated-date` | `dashboard_last_updated_at` | `survey_responses` 的 `updated_at/max`。 |

完整、可傳送的請求本文請參閱[儀表板 Analytics 遷移指南](DASHBOARD_ANALYTICS_MIGRATION.md#3-dashboard-端點替代方案)。

## 已淘汰的 pre-0012 多 Metric 契約

下列行為僅供理解舊系統的結果塑形；不要再送出 `metrics` array，伺服器會回傳 `422`。

- 情緒分布曾在單一 request 中要求正向、負向、中性、混合計數和平均分數。現在使用依 `topic_sentiment` 分組的 `survey/count`，平均分數另以 `topic_sentiment_score/average` 查詢。
- 門市、渠道和門市欄位分布曾在同一 row 帶有多個情緒 metric。現在以 sentiment dimension 分組，由前端使用 `value` 繪製 series。
- Topic、department、keyword 分布曾取得多個 assignment-sentiment metric。現在依該 assignment view 的 `sentiment` 分組，並使用相符的 `*_assignment/count`。
- 資料涵蓋範圍曾在同一 response 取得最早與最晚時間。現在分別查詢 `reported_at/min` 與 `reported_at/max`。
- `last-updated-date` 現在回傳有效 Analytics fact 中最新的 `updated_at`。語意 view 會排除軟刪除問卷；舊 route 未排除，兩者意義不同。

若前端在過渡期仍需舊 DTO，應將單一 metric 結果的 `rows` 依 dimension key 合併、將 `value` 對應回舊 property name，並將每個 day bucket 的 `reported_at` 起點轉為 `year`／`month`／`day`。

## `total_count_for_option` 與零填補

`total_count_for_option` 是圖表支援資料，不應除非產品明確需要比較或 tooltip，否則呈現為額外 series。

要取得某個 selected option 的總數，呼叫 `POST /analytics/filter-options`，並傳入所有*其他*共用 filter，排除目標 member 的 filter。其 `count` 即為舊端點的 option total。例如門市格式 selector 要傳 region 與 date filter，但不可傳 `store_format` filter。

受治理 aggregate query 刻意只回傳觀察到的 group。若 UI 需顯示沒有相符問卷的門市、topic 或 department，使用 `POST /analytics/records/query` 讀取 master data，再將缺少的 aggregate row 補零：

```json
{
  "resource": "stores",
  "page": 1,
  "size": 1000,
  "order": [{"member": "store_key", "direction": "asc"}]
}
```

將 `stores` 置換為 `topics` 或 `departments`，即可支援相應 card。Record API 會回傳完全未被 survey 參照的 master value，因此它才是舊零填補列的正確資料來源。

## 舊主資料讀取

這些舊 route 是讀取端點，但不是 aggregate Cube query。請改用即時資料庫上的 `POST /analytics/records/query`：

| 舊 route | 替代本文 |
| --- | --- |
| `GET /channels/` | `{ "resource": "channels", "page": 1, "size": 1000 }` |
| `GET /channels/{channel_id}` | `{ "resource": "channels", "filters": [{"member":"id","operator":"equals","value":123}], "page": 1, "size": 1 }` |
| `GET /delivery_services/` | `{ "resource": "delivery_services", "page": 1, "size": 1000 }` |
| `GET /delivery_services/{delivery_service_id}` | `{ "resource": "delivery_services", "filters": [{"member":"id","operator":"equals","value":123}], "page": 1, "size": 1 }` |
| `GET /topics/` | `{ "resource": "topics", "page": 1, "size": 1000 }` |
| `GET /topics/{topic_id}` | `{ "resource": "topics", "filters": [{"member":"id","operator":"equals","value":123}], "page": 1, "size": 1 }` |
| `GET /surveys` | `{ "resource": "surveys", "page": 1, "size": 100 }` |
| `GET /surveys/{survey_id}` | `{ "resource": "surveys", "filters": [{"member":"id","operator":"equals","value":123}], "page": 1, "size": 1 }` |
| `GET /surveys/download` | 以 `record_query: {"resource":"surveys", ...}` 及 `export_format: "csv"` 或 `"xlsx"` 呼叫 `POST /analytics/exports`。 |
| `GET /stores` | `{ "resource": "stores", "page": 1, "size": 1000 }` |
| `GET /departments` | `{ "resource": "departments", "page": 1, "size": 1000 }` |

## 回應塑形與等效性檢核

受治理 API 會回傳共同的 aggregate envelope，其中包含 `query_id`、`model_version`、`semantic_view`、`timezone`、`schema`、flat `rows`、`row_count`、`warnings` 與 `freshness_time`。

用戶端應：

1. 從 `rows` 讀取 aggregate value，而非從舊 list response 讀取。
2. 需要重現 `total_count_for_option` 時，以 dimension key 合併第二個 query 的 count。
3. 從 master-data record query 為門市、topic 與 department 補零。
4. 過渡期需要維持舊 response DTO 時，轉換 daily time bucket，並將 metric 對應回舊 property name。
5. 將 topic、department 與 keyword assignment filter 限制於各自 semantic view。

Aggregate query 最多 1,000 列。大型報表應分頁取得 filter option，或使用受治理 export。Cube 結果也以新鮮度為準；UI 需顯示資料時效時，使用回傳的 `freshness_time`。
