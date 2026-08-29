# CLSense Cube 執行環境

此目錄是受治理問卷語意層受版本控制的核心。`docker-compose.analytics.yml` 會為全部 61 個應用程式設定檔各自加入私有 Cube API 與重新整理工作者，並建立四個獨立持久化的 Cube Store 叢集。它是疊加設定，務必與既有的 `docker-compose.yml` 一同使用。

如需完整的 Canary 啟動操作說明，請參閱 [`deploy/WTCHK_CLS_STARTUP.md`](../deploy/WTCHK_CLS_STARTUP.md)。

如需所有 viewer、admin 與內部語意層端點，請參閱 [`docs/ANALYTICS_API_REFERENCE.md`](../docs/ANALYTICS_API_REFERENCE.md)。

## 執行環境邊界

- Cube 與 Cube Store 固定使用 `v1.7.26` 官方 manifest-index digest。操作人員仍必須在正式上線前，於目標架構驗證這些不可變映像。
- Cube Store v1.7.26 僅發布 `linux/amd64` 執行環境映像。Compose 疊加設定指定 `CUBESTORE_PLATFORM=linux/amd64`，讓 Docker Desktop 的 ARM64 開發可透過模擬執行。正式環境與負載測試必須使用 AMD64。
- Cube API 執行個體不公開主機連接埠。它們加入 `connex_network` 以連線至各自的後端／PostgreSQL 資料庫，並且只加入被指派的 `analytics_store_shard_N` 網路以連線至 Cube Store。四個 shard 網路皆為內部網路，與其他未驗證的 Cube Store 叢集相互隔離。
- 每個設定檔都會取得唯一的 app ID、orchestrator ID、pre-aggregation schema、唯讀 PostgreSQL principal、API signing secret、metadata signing secret 與功能旗標。
- 核心模型維護五個明確 grain。它們之間沒有 join；查詢改寫會拒絕指定多於一個 cube 的請求。
- 跨越兩個 assignment family 時，必須以 `survey_assignments` grain 表示：它針對每個 `(response, keyword, department, topic)` 組合各有一列，而非放寬上述規則。由於 response 在此會為每個組合重複，這個 grain 只提供依 response key 去重的指標；CLS 等 response 加總及平均值仍屬於 `survey_responses`。

持久化的配置位於 `deploy/analytics/profiles.json`：已排序的設定檔名稱會以 round-robin 方式分配至四個 shard。`wtchk_cls` 與 `wtchk_ecls` 屬於 rollout wave 0；其餘設定檔分為每批最多十個、依排序排列的 wave。新增或移除設定檔後，請重新產生並驗證：

```bash
python scripts/generate_analytics_compose.py
python scripts/validate_analytics_infra.py
```

空白的 `deploy/analytics/shard-overrides.json` 是供營運重新平衡使用、經審核的例外入口。僅加入過載設定檔及其新 shard 編號，重新產生設定，然後重建受影響設定檔的 pre-aggregation。只有當 CPU 或記憶體在已同意的持續監測窗口內維持高於 70%，或 Cube Store partition scan 超過 100 ms 目標時，才應重新平衡；單次短暫尖峰不是重新平衡信號。這應被視為計畫性的快取搬移，因為開源 Cube Store 不會複寫 shard 狀態。

## 設定並啟動設定檔

從受信任的 registry 解析多平台映像 manifest digest，將映像部署至非正式環境，執行語意整合與負載套件，再記錄已測試的 `sha256:...` 值。單純查詢 registry 不構成測試。將 `deploy/analytics.env.example` 複製到被忽略的設定檔環境檔，並加入相符的具命名空間區塊。

Analytics 資料庫角色不得擁有資料庫或 schema。只授與其 BU 資料庫的 `CONNECT`、報表 schema 的 `USAGE`，以及模型所需報表 view／helper function 的 `SELECT`。啟用設定檔前，請以 `SET ROLE <role>` 驗證授權。靜態驗證器會檢查是否設定專屬使用者名稱，但無法證明 PostgreSQL 授權；此資料庫端驗證是必要的部署閘門。兩個 signing secret 都必須至少含 32 個隨機 bytes、用途不同，並且在部署 wave 中驗證的每個設定檔皆不重複。

```bash
python scripts/validate_analytics_infra.py \
  --env-file deploy/profile/wtchk_cls.env \
  --profile wtchk_cls

docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  up -d
```

`WTCHK_CLS_ANALYTICS_ENABLED=false` 會讓 viewer／admin Analytics 路由保持停用，同時 Cube 執行 shadow query。只有通過比較閘門後才將它設為 `true`。回復時改回 `false`；一般健康檢查、上傳、問卷與儀表板路徑皆不依賴 Cube 健康狀態。

Compose 疊加設定公開兩個具正式環境安全預設值的全域重新整理設定：

| 設定 | 預設值 | 說明 |
| --- | --- | --- |
| `ANALYTICS_PRE_AGGREGATION_REFRESH_EVERY` | `15 minute` | 編譯至 core 與已發佈圖表 rollup 的 Cube `refresh_key.every` 值。 |
| `ANALYTICS_SCHEDULED_REFRESH_INTERVAL_SECONDS` | `30` | 每個 refresh-worker 容器啟動一次 scheduled-refresh cycle 的頻率。API 容器會始終停用計時器。 |

在建立 Compose 服務前，請於根目錄 `.env` 設定覆寫值。變更 pre-aggregation 重新整理值會變更編譯出的 Cube schema，且需要重建受影響的 partition。

## 動態 Catalog 契約

編譯時，Cube 會以以下標頭呼叫設定檔後端的 `GET /internal/analytics/catalog` 端點：

- `X-Analytics-Profile`
- `X-Analytics-Timestamp`（Unix 秒數）
- `X-Analytics-Signature`（`HMAC-SHA256(secret, "timestamp:profile")`）

回應必須符合 `contracts/catalog.schema.json`。編譯器只接受結構化欄位與 metric 定義：它會在產生 YAML 前驗證識別字、型別、運算、欄位參照、篩選值、可見性與 catalog 單調性。它絕不執行 JavaScript，也不接受中繼資料端點提供的任意 SQL。端點與 secret 均為設定檔本機專屬。標準化內容雜湊還會拒絕在未變更 catalog version 下變更的中繼資料，避免 API 與 refresh process 編譯出不同模型。

核心 member 使用由版本控制的、每個 view 專屬的型別與 SQL alias registry。這可保留 `department -> department_name` 及 `sentiment -> assignment_sentiment` 等 assignment alias；已簽署中繼資料不能憑空建立實體 core column。圖表 rollup 會以同一個核心 registry 與已發佈的本機 catalog 驗證。confidence 與 weighted rollup 會自動包含 FastAPI 所要求的支援 confidence／data-quality metric。

confidence interval metric 會依下列穩定 suffix 契約公開支援 metric。FastAPI 會連同 estimate 請求這些 metric，並使用 SciPy 計算邊界：

- 未加權平均值：`__sample_count`、`__value_sum`、`__value_square_sum`、`__variance_sample`；
- 未加權比例：`__success_count`、`__sample_count`；
- 加權 metric：`__pair_count`、`__weight_sum`、`__weight_sum_squares`、`__weighted_value_sum`、`__weighted_value_square_sum`；比率另含 `__success_weight_sum`；
- 所有加權 metric：`__invalid_weight_count` 與 `__invalid_value_count`。

負數、NaN 與無限大的權重（以及加權 moment 中非有限的數值）會令 estimate 成為 null，並增加 data-quality metric。任一計數非零時，FastAPI 必須回傳可見的資料品質失敗。零權重仍然有效；值或權重為 null 的資料列會被排除。

中位數與百分位數 metric 使用穩定的 PostgreSQL `PERCENTILE_CONT` 表達式，並保持未加權／不可加。它們刻意不納入共用 rollup；相符的圖表專屬不可加 rollup 必須使用圖表的精確 dimensions，否則 Cube 會回退至 PostgreSQL。

受影響月份的重新整理呼叫請參閱 `contracts/preaggregation-refresh.md`。

## Cube Core 的 Azure Blob 限制

核准的設計要求每個 Cube Store shard 使用獨立 Azure Blob prefix。疊加設定保留並驗證四個不同 prefix，但依 Cube 目前的正式文件，開源 Cube Store 映像**不支援** Azure Blob 持久儲存；該能力僅限 Enterprise。OSS 疊加設定因此會將每個 shard 持久化至隔離的 Docker named volume。

不要將 `ANALYTICS_AZURE_BLOB_PREFIX` 視為作用中的 Cube Store 設定：它是交由已核准的離線備份流程或 Enterprise 映像的明確交接。精確的 Azure 支援 pre-aggregation 持久化需要 Cube Enterprise、受支援的 OSS 遠端儲存（例如 S3/GCS），或另外審查過的靜止備份／還原流程。即時複製檔案不是 Cube Store 一致性契約的安全替代方式。

開源 Cube Store 同樣沒有節點複寫。每個 shard 將故障範圍限制在約四分之一的設定檔，並可由 PostgreSQL 重建，但此拓撲屬於營運復原，並非透明高可用性。
