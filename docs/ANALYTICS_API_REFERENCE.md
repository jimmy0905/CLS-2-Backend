# Analytics API 參考

> 公開 aggregate API 採用目標優先模式。實作 query builder 前，請先閱讀[目標優先的 Analytics 查詢契約](ANALYTICS_GOAL_FIRST_CONTRACT.md)，其中定義邏輯 metric target、`/analytics/query-capabilities` 與現行 response schema。

本文件說明受治理的 Cube Analytics API。它只涵蓋 Analytics route；既有 `/dashboard/*`、survey、upload 與 authentication route 不受影響。

目前 dashboard card 的端點逐一替代方案及可直接送出的本文，請參閱[儀表板 Analytics 遷移指南](DASHBOARD_ANALYTICS_MIGRATION.md)。前端呼叫順序、availability、filter discovery 及 chart loading loop，請參閱[前端儀表板 Analytics 工作流程](FRONTEND_DASHBOARD_ANALYTICS_WORKFLOW.md)。如需含十份虛構問卷範例的中文 Semantic View、Dimension、Metric 手冊，請參閱[Semantic View、Dimension 與 Metric 使用手冊](user-manual/SEMANTIC_VIEW_DIMENSION_METRICS_GUIDE.md)。

## Base URL、存取與共同行為

以下路徑是 FastAPI 路徑。在 `wtchk_cls` 部署中，外部 API 一般位於：

```text
https://<api-host>/wtchk/api
```

例如：

```text
GET https://<api-host>/wtchk/api/analytics/catalog
Authorization: Bearer <profile-api-bearer>
```

所有公開 Analytics endpoint 均只需相符 profile 的 static API bearer；後端不會讀取使用者、角色或 actor header。`ANALYTICS_ENABLED=false` 時會回傳 `404`，讓 BU 可在不向使用者公開 Analytics 的 shadow mode 中編譯 Cube metadata。Analytics response 均帶有 `Cache-Control: no-store, private`。

| 呼叫端 | 存取權 |
| --- | --- |
| Static bearer | 所有公開 Analytics 路徑，包括 chart governance、publication 與所有 export job。 |
| Cube service | 僅私有 internal catalog endpoint，使用 profile-bound HMAC 驗證；不是 browser endpoint。 |

## Semantic View 與資料粒度

支援的 semantic view 為 `survey_responses`、`survey_topics`、`survey_departments`、`survey_keywords` 與 `survey_assignments`。每一個都是獨立 grain。Aggregate caller 提供邏輯 metric、dimension、time 與 filter；伺服器選出能安全回答該組合的最窄 grain。Cube query 仍只使用一個 view，絕不 join cube。

| Semantic View | 一列代表 | Canonical response sentiment | Assignment sentiment | 適用情境 |
| --- | --- | --- | --- | --- |
| `survey_responses` | 一個未刪除 survey response | `topic_sentiment` = `surveys.topic_sentiment`；score = `topic_sentiment_score` | 無。舊 `surveys.sentiment` 不是公開 semantic field。 | 整體 response volume、CLS、store／channel 分析及 response-level sentiment。 |
| `survey_topics` | 一個 topic assignment | 同上 | `sentiment` = `survey_topics.sentiment` | 依 `topic` 分析；使用 `topic_assignment/count` 或 `survey/count`。 |
| `survey_departments` | 一個 department assignment | 同上 | `sentiment` = `survey_departments.sentiment` | 依 `department` 分析；使用 `department_assignment/count` 或 `survey/count`。 |
| `survey_keywords` | 一個 keyword assignment | 同上 | `sentiment` = `survey_keywords.sentiment` | 依／篩選 `keyword`；使用 `keyword_assignment/count` 或 `survey/count`。 |
| `survey_assignments` | 一個 `(response, keyword, department, topic)` 組合 | 同上 | `keyword_sentiment`、`department_sentiment`、`topic_assignment_sentiment` | 交叉兩個 assignment family，例如 keyword × department；只提供計數。 |

在 `survey_responses` 中一律使用 `topic_sentiment`；`sentiment` 不是有效 public member。在 assignment view 中，`topic_sentiment` 仍表示 response-level 值，`sentiment` 則只表示該 assignment row。既有 response-level metric、chart、saved query、drilldown 或 frontend selector 若使用 `sentiment`，應改為 `topic_sentiment` 後再 validate／publish 新 catalog version。

不得在同一 query 結合 `survey_topics`、`survey_departments` 與 `survey_keywords`。一份 response 可有多個 assignment，join 會乘大 row 數並使 count／average 模糊。確實需要兩個 assignment family 時使用 `survey_assignments`：它明確產生組合列，並以 distinct response count 回答。由於 `cls/sum` 與 `cls/average` 會受組合數加權，它們在此 grain 刻意不存在；單一 family 應使用其專屬 grain。

## 共用查詢契約

`POST /analytics/query`、chart data 與 aggregate export 一律使用已發佈的 field *slug*，絕不接受 raw SQL、Cube member name 或 governed metric slug。每個 aggregate 選擇一個邏輯業務 target 作為 `metric`，以及一種 `aggregation`；伺服器會將 pair 對應至 resolved fact grain 中一個已發佈的 Cube measure。

| 欄位 | 規則 |
| --- | --- |
| `semantic_view` | 已棄用的相容欄位。若傳送會被忽略；response 會回報實際選定的 grain。 |
| `dimensions` | 0–3 個已發佈 dimension slug；連同 filter／time 決定 grain。 |
| `metric` | resolved grain 可回答的一個邏輯 target。 |
| `aggregation` | target 在 resolved grain 發佈的一種方法；使用 `average`，而非 `avg`。 |
| `filters` | 最多 20 個具型別 filter。operator 包含 `equals`、`not_equals`、`contains`、`not_contains`、`starts_with`、`ends_with`、比較 operator、`in`、`not_in`、`set`、`not_set` 與 `between`（依 member type 決定）。 |
| `time_dimension` | 已發佈的 date/time dimension；可搭配 `time_range`、`time_granularity`，但不得同時作為一般 dimension。 |
| `time_range` | 兩個 ISO-8601 date/datetime 值，每個最多 64 字元，開始不得晚於結束。 |
| `time_granularity` | 當 time member 支援時，可用 `day`、`week`、`month`、`quarter`、`year` 等 Cube 粒度。 |
| `timezone` | 可選 IANA timezone，例如 `Asia/Hong_Kong`；用於 time-range boundary、time bucket 與 timestamp display。未提供時為 UTC。 |
| `order` | `{ "member": "<slug-or-value>", "direction": "asc" \| "desc" }` 清單。member 必須是已選 dimension、selected time dimension 或 `value`。 |
| `limit` | Aggregate query 允許 1–1,000 列。 |

| Field type | 可發佈 aggregation |
| --- | --- |
| String／boolean | `count`、`distinct_count` |
| Number | `count`、`distinct_count`、`sum`、`average`、`min`、`max`、`median` |
| Date／time | `count`、`distinct_count`、`min`、`max` |

型別表只決定可發佈的方法類別，並非自行構成 allowlist。確切的邏輯 `(metric, aggregation)` pair 必須出現在 active catalog、且屬於伺服器 resolved semantic view 的 `metric_targets`。缺少或 ambiguous pair 會回傳 `422`。

成功 aggregate response 使用 flat row，metric cell 固定為 `value`：

```json
{
  "query_id": "8f5c…",
  "model_version": 8,
  "semantic_view": "survey_responses",
  "timezone": "Asia/Hong_Kong",
  "schema": {
    "dimensions": [
      {"field": "region", "label": "Region", "type": "string", "key": "region"}
    ],
    "time_dimension": null,
    "metric": {
      "target": "survey",
      "aggregation": "count",
      "label": "Response Count",
      "type": "number",
      "key": "value"
    }
  },
  "rows": [{"region": "North", "value": 120}],
  "row_count": 1,
  "warnings": [],
  "freshness_time": "2026-08-25T10:15:00Z"
}
```

Dimension 與 time value 會保留 `schema` 宣告的 key。未選 time dimension 時，`schema.time_dimension` 為 `null`；即使結果為空，`rows` 與 `warnings` 也必定存在。Weighted、filtered、variance、standard-deviation、percentile 與 confidence-interval measure 可保留在 governance metadata，但不透過簡化 query contract 公開。

常見錯誤：`401`（缺少、無效、已刪除或錯誤 profile 的 token）、`404`（Analytics 停用或資源不存在）、`422`（無效的受治理輸入或遭拒的 semantic query）、`503`（Cube 或 Analytics 資料庫無法使用）。錯誤訊息刻意不洩漏 Cube／PostgreSQL 實作細節。

## Static-bearer Endpoint

### `GET /analytics/catalog`

回傳 static bearer 可使用的 active immutable catalog，包括 active model version、semantic view、可見 field 與可執行的邏輯 `metric_targets`。不會揭露 candidate header、raw payload key、SQL expression、governed Cube metric slug 或 draft definition。每個 field 另提供 `filter_control`（`select`、`search` 或 `input`）及 `minimum_search_length`；前端必須依此決定是否可載入 option。

在建立探索 UI 前先呼叫此 endpoint。用戶端只能將本 response 回傳的 slug 送至 query endpoint。`combinations` 提供可供機器讀取的 query limit 與 grain definition；chart renderer compatibility 由前端依 response shape 決定。

### `POST /analytics/query-capabilities`

使用者選擇一個 goal 與 method 後，先呼叫此 endpoint 再顯示其餘 selector：

```json
{
  "metric": "survey",
  "aggregation": "count"
}
```

它以與 query execution 相同的 resolver 驗證 pair，並回傳 `allowed_dimensions`、帶型別 operator 的 `filter_members`、`allowed_time_dimensions`、`result_type` 與 `warnings`。這是 query builder 發現哪些 breakdown 仍有意義的標準方式。

### `GET /analytics/query-combinations`

回傳有限且精選的 aggregate query template。前端只提供已知正確組合時使用此 endpoint，而不要由 `GET /analytics/catalog` 任意排列。

可選 `semantic_view` query parameter 將 collection 限制於一個 view：

```text
GET /analytics/query-combinations?semantic_view=survey_responses
```

每個回傳的 `query` 都是可直接執行、且已通過 active-catalog、member visibility、semantic-view、time-dimension 與 metric validation 的 `POST /analytics/query` body。用戶端只可修改其 `allowed_overrides` 中的欄位。回傳 count 是依 semantic-view 與 static bearer visibility 過濾後的 template 數。

`responding_stores_by_region` 類 template 使用 `survey_responses` 的 `store/count`，計算至少有一筆相符 response 的相異門市。response date range 表示「期間內有回應的門市」；零筆相符 response 的門市無法出現在 response-grain view。需要完整門市主檔時，使用受治理 `stores` record resource。

### `GET /analytics/catalog/availability`

回傳某一 semantic view 中、呼叫端可見的 field 實際是否含資料，供前端隱藏完全為 null 的 field，而非從 catalog definition 猜測。

| Query parameter | 必填 | 說明 |
| --- | --- | --- |
| `semantic_view` | 否，預設 `survey_responses` | `survey_responses`、`survey_topics`、`survey_departments` 或 `survey_keywords` 之一。 |

相同 static bearer／view／model-version 的首次請求可能掃描 reporting view；相同請求最多快取 15 分鐘。`available: true` 只表示至少有一筆 reporting row 有非 null 值，不表示每一列完整。

### `POST /analytics/filter-options`

回傳可填入一個前端 filter control 的 value。目標 `member` 必須是指定 semantic view 中已發佈、且 static bearer 可見的 dimension。回應排除 null value、依相符 row count 排序，且絕不公開 raw／unpromoted payload key。

```json
{
  "semantic_view": "survey_responses",
  "member": "store_format",
  "filters": [
    {"member": "topic_sentiment", "operator": "equals", "value": "NEGATIVE"}
  ],
  "search": "Mall",
  "limit": 100,
  "cursor": 0
}
```

`semantic_view` 與 `member` 為必填。`filters` 可用於相依選擇，例如選定門市格式後才列出門市；`search` 僅限 string field。UI 需要隱藏完全無資料 dimension 時，先呼叫 `GET /analytics/catalog/availability`。

此 endpoint 只適用於 catalog 宣告為 `select` 或 `search` 的 field。`search` field 必須帶有至少 `minimum_search_length` 個字元的 `search`；`input` field（例如 response／survey ID、assignment ID、組合 ID）只接受使用者輸入的 exact value，呼叫此 endpoint 會得到 `422`。前端不得在開啟 filter UI 時自動查詢 `search` field，亦不得把 cursor page 全部載入；`select` 最多顯示首 100 個 value，若 `has_more` 為 true 應提示使用者先縮窄條件。

此 endpoint 只回傳 option value 及其相符 row count；不接受 `metric`、`aggregation` 或已移除的 `metrics`，也不回傳 `metric_columns` 或各 option 的 metric object。超過 1,000 個 value 時，將 response `next_cursor` 作為下一請求 `cursor`；先按相符 row count 遞減、再按 value 遞增排序。`has_more` 在頁面滿時為 true；總數剛好是 `limit` 倍數時，最後一次請求可能回傳空頁。

### `POST /analytics/query`

執行一個受治理 aggregate query。伺服器根據 metric 與 selected member 選擇單一安全 semantic view，response 會列出 resolved view。

```json
{
  "dimensions": ["store_name_english", "store_format"],
  "metric": "cls",
  "aggregation": "average",
  "filters": [{"member": "topic_sentiment", "operator": "equals", "value": "NEGATIVE"}],
  "time_dimension": "reported_at",
  "time_range": ["2024-08-01", "2024-08-31"],
  "time_granularity": "month",
  "timezone": "Asia/Hong_Kong",
  "order": [{"member": "value", "direction": "desc"}],
  "limit": 1000
}
```

送至私有 Cube 前，伺服器會驗證 visibility、member type、limit、filter operator、推導 grain，以及 `(metric, aggregation)` 是否恰好解析至一個 active governed measure。缺少 `metric`／`aggregation`、傳送已移除 `metrics` array、超過三個 dimension、不相容 aggregation 或未發佈／ambiguous pair 均為 `422`；`503` 表示 Cube 無法服務。

### `POST /analytics/records/query`

直接對即時 application database 執行受治理 record query。支援 `surveys`、`stores`、`departments`、`channels`、`delivery_services`、`topics`。Filter 與 order 只接受具型別、resource-specific 的 allowlisted field。使用 `member` 表示欄位名（`field` 是可接受 input alias）；scalar operator 使用 `value`，`in`、`not_in`、`between` 使用 `values`。

Survey result 排除軟刪除列，並保留既有 nested store、channel、delivery-service、department、topic、keyword object。Survey response 同時包含舊 `sentiment` 與 canonical `topic_sentiment`。Survey 的 topic、department、keyword filter 使用 `EXISTS` predicate，不會因 assignment match 重複 survey row。

Survey page 上限 100，預設 `reported_at DESC, id DESC`；master-data page 上限 1,000，預設 primary key 遞增。Master-data query 會回傳未被 survey 引用的 value，可供 dashboard selector 零填補。

### `GET /analytics/charts/published`

列出 active catalog 中、static bearer 可見的已發佈 chart。每個 chart 包含 ID、slug、title、type、semantic view、governed definition、visibility、lifecycle status、validation state 與 model-version metadata。Draft、archived 或 invalid chart 不會出現在此路徑。

### `POST /analytics/charts/{chart_id}/data`

以 numeric ID 執行已發佈 chart。Chart 的 dimension、metric、aggregation 固定於已發佈 definition；caller 只可提供安全的 exploration override：`filters`、`time_range`、`time_granularity`、`timezone`、`order` 與 `limit`。

Response 包含 `chart` 及與 `/analytics/query` 相同的 `schema`、flat `rows`、`row_count`、`warnings`、freshness field。後端不按 `chart_type` 截斷 series、加入 `Other` 或補零；renderer 使用完整 governed rows 自行呈現。不存在或不可見的 chart 回傳 `404`。

### `POST /analytics/drilldown`

只從 `survey_responses` 回傳 cursor-paginated response-level row。它用於檢視 aggregate 背後的 row，不是任意 raw-data access。

`fields` 可取 1–50 個允許的 core／promoted field，`filters` 最多 20 個相容 filter，`limit` 為 1–250。可選 IANA `timezone` 套用本地 timestamp filter 並格式化回傳 timestamp；未提供時為 UTC。response 會連同 `{ "rows": [...], "next_cursor": 100, "has_more": true }` 回傳有效 `timezone`。只回傳 static bearer 可見的 promoted field；unpromoted payload key 與 raw JSON payload 永不回傳。容量保護可回傳 `429` 並帶 `Retry-After`；資料庫 timeout／不可用時為 `503`。

### `POST /analytics/exports`

建立非同步 CSV 或 XLSX export。本文必須在 aggregate query、drilldown query、即時 record query 三者之中**恰選一個**。`export_format` 為 `csv` 或 `xlsx`。

Export job 建立後狀態為 `queued`。系統在受理時記錄固定 static-bearer attribution、model version、query 與 visibility rule。Export 上限 250,000 列，CSV/XLSX formula prefix 會跳脫，artifact 在 24 小時後到期。每個 profile 的 queue limit 會回傳 `429`。

### `GET /analytics/exports/{job_id}`

回傳 static bearer 可見的 export-job metadata。Status 為 `queued`、`processing`、`completed` 或 `failed`，並包含 timestamp、format、可用的 row count、expiry 與安全的 failure information。過期 job 仍會保留為歷史 metadata，但 download 回傳 `410`。

### `GET /analytics/exports/{job_id}/download`

將已完成 CSV/XLSX artifact 串流至持有 static bearer 的呼叫端。Job 未完成時回傳 `409`、不存在時為 `404`、到期或已移除時為 `410`。File response 明確不可快取。

## `/admin` 路徑

本節所有路徑只需要已驗證 static bearer，並受 feature gate 控制。首次 rollout 刻意只公開**chart management**。Standard field 與 metric 為內建；candidate、field、metric、catalog-version administration 並非 public endpoint，藉此縮小 operational surface，同時保留受治理 chart definition 與 audit history。

### 已移除的 candidate、field 與 metric administration

這些 endpoint 僅保留為 private implementation handler，未掛載至 public API；對 caller 回傳 `404`。下列資訊僅保留遷移脈絡，請使用 built-in catalog 的 chart definition。

| Endpoint | 歷史行為 |
| --- | --- |
| `GET /admin/analytics/candidates` | 列出上傳發現的 header candidate，包含 inferred／conflicting type、sample value、occurrence metadata、source key 與 promotion state。因 raw header／sample 可能敏感，未列為 public endpoint。 |
| `GET /admin/analytics/fields`、`GET /admin/analytics/fields/{field_id}` | 列出或取得 local governed field，包含 draft／archived state 與 discovery metadata。 |
| `POST`／`PUT`／`validate`／`publish`／`archive` 的 `/admin/analytics/fields/{field_id}` 路由 | 建立、修改、驗證、發佈或封存 raw-JSON field；修改後必須重新 validate／publish。若已發佈 metric 或 chart 仍參照 field，archive 會被拒絕。 |
| `GET /admin/analytics/metrics`、`GET /admin/analytics/metrics/{metric_id}` | 列出或取得 metric record、source／weight reference、operation、confidence configuration、lifecycle 與 audit/version data。 |
| `POST`／`PUT`／`validate`／`publish`／`archive` 的 `/admin/analytics/metrics/{metric_id}` 路由 | 建立、修改、驗證、發佈或封存 governed metric。`definition` 不接受任意 SQL、JavaScript 或 expression，只接受 operation 所允許的 declarative parameter。 |

歷史 metric operation 包含 count／distinct／filtered count／rate、numeric sum／average／weighted sum／weighted average／min／max／variance／standard deviation／median／percentile／confidence interval 及 date/time min／max。Weight 必須是非負 numeric governed member；median／percentile 明確不加權。

### Chart（圖表）

Chart 本文含 `slug`、`title`、可選 `description`、`chart_type`、`semantic_view`、受治理 `definition` 與 `visibility`。Definition 指定 0–3 個 dimension、恰一個 `metric` field 與 `aggregation`，可另含 filter、time setting、order 與 bounded limit。後端保存 `chart_type` 供 renderer 使用，但不以它驗證 query shape；前端依資料形狀決定可選圖型。`scatter`、`store_map` 不再接受。

| Endpoint | 行為 |
| --- | --- |
| `GET /admin/analytics/charts`、`GET /admin/analytics/charts/{chart_id}` | 列出或取得所有 chart，包含 draft、archive、validation error、definition、visibility 及 version metadata。 |
| `POST /admin/analytics/charts` | 建立 draft chart definition；不會觸發 visual rendering，前端消費 chart contract。 |
| `PUT /admin/analytics/charts/{chart_id}` | 更新 definition，並使其回到 draft。 |
| `POST /admin/analytics/charts/{chart_id}/publish` | validate、publish 並立即啟用新 catalog version。response 含 `model_version`；持有相符 static bearer 的呼叫端隨後可從 `GET /analytics/charts/published` 取得 chart。 |
| `DELETE /admin/analytics/charts/{chart_id}` | 軟刪除 chart、記錄 audit event，並立即啟用不含該 chart 的 catalog version；持有相符 static bearer 的呼叫端將不再取得該 chart。 |

### Catalog version（Catalog 版本）

| Endpoint | 行為 |
| --- | --- |
| `GET /admin/analytics/catalog/versions` | 列出 model-version history：catalog version、status（`active`、`superseded` 等）、definition hash、creator、timestamp 與 validation error；清單不含 immutable snapshot。 |
| `GET /admin/analytics/catalog/versions/{version_id}` | 回傳一個 version、其 immutable catalog snapshot 與 generated Cube catalog information，供 audit／debug；因可包含 local source key，未列為 public endpoint。 |
| `POST /admin/analytics/catalog/publish` | 可選本文 `{ "description": "Quarterly metrics release" }`。重新驗證所有已發佈 field／metric／chart、檢查 catalog size 與 dependency constraint、編譯 chart rollup definition、建立 immutable version 並以 atomic 方式啟用。成功回傳 `201`；無效 definition 為 `422`，lifecycle／concurrency conflict 為 `409`。 |

## 內部 Cube Metadata Endpoint

### `GET /internal/analytics/catalog`

這不是供人員操作的 administration API。它向每個 BU 的 Cube compiler 提供 active chart／catalog metadata。它刻意不受 `ANALYTICS_ENABLED` 控制，讓七天 shadow phase 即使 user-facing Analytics 停用仍能編譯。它只能在 private Analytics network 上存取。

必要 header：

```text
X-Analytics-Profile: wtchk_cls
X-Analytics-Timestamp: <unix seconds>
X-Analytics-Signature: <HMAC-SHA256 of "<timestamp>:<profile>">
```

Profile 必須符合 deployment profile、timestamp 必須新鮮，且 signature 使用該 BU 的 metadata secret。Response 包含 Cube 編譯所需的 catalog version、field／metric definition 與已核准的 local rollup。無效 signature／timestamp 為 `401`；錯誤 profile 為 `403`。此 response 亦明確為 `Cache-Control: no-store, private`。

## 歷史生命週期範例

以下 dynamic field／metric flow 未在 chart-only rollout 啟用：

1. Upload 發現 candidate；operator 透過 `GET /admin/analytics/candidates` 檢視。
2. Operator 使用 `POST /admin/analytics/fields/{field_id}/promote` promotion 與設定 field。
3. Operator 建立使用該 field 的 metric 或 chart，接著呼叫相關 `validate`、`publish` endpoint。
4. Operator 呼叫 `POST /admin/analytics/catalog/publish`。
5. Cube 經由 internal endpoint 取得新的 immutable catalog；使用者經由 `GET /analytics/catalog` 與 `GET /analytics/charts/published` 看見它。

修改或 archive definition 不會改寫舊 catalog snapshot。已發佈的 chart／export 會維持與該操作記錄的 model version 綁定，因此 governance 與 audit history 可重現。
