# CLSense 後端

## 部署設定檔

Docker Compose 堆疊會為每個 Nginx 事業單位路由建立一個後端服務。服務採用選擇性啟動的 Compose 設定檔，名稱為 `[bu_name]_[cls|ecls]`；只有被選取的設定檔會啟動。

Nginx 設定提供 30 個 CLS 設定檔：

```
wtchk_cls wtctw_cls wtcmy_cls kvnl_cls sd_cls wtcsg_cls wwhk_cls pnshk_cls
ftrhk_cls wtcth_cls wtcid_cls wtcvn_cls wtccn_cls wtcph_cls drlv_cls drlt_cls
icibe_cls kvbe_cls tps_cls wtcua_cls wtctr_cls mat_cls mch_cls mcz_cls mfr_cls
mhu_cls mit_cls mro_cls msk_cls icinl_cls
```

並提供 31 個 ECLS 設定檔：

```
wtchk_ecls wtcph_ecls wtcmy_ecls ftrhk_ecls pnshk_ecls wwhk_ecls wtcth_ecls
wtcsg_ecls wtctw_ecls wtcvn_ecls wtccn_ecls wtcid_ecls sd_ecls drlv_ecls
drlt_ecls icibe_ecls icinl_ecls kvnl_ecls kvbe_ecls mat_ecls mch_ecls mcz_ecls
mfr_ecls mhu_ecls mit_ecls mro_ecls msk_ecls tps_ecls wtctr_ecls wtcua_ecls
svruk_ecls
```

每個設定檔都會保留 Nginx 定義的 API 連接埠，並擁有獨立的上傳磁碟區。例如，`wtchk_cls` 在主機的 8000 埠監聽，而 `wtchk_ecls` 在 8003 埠監聽。完整對應表以 [docker-compose.yml](docker-compose.yml) 為準。

### 設定範圍

將 [`.env.example`](.env.example) 複製為 `.env`，填入共用憑證與整合設定。每部署一個設定檔，請建立 `deploy/profile/<profile>.env`，並只從 [`deploy/profile.env.example`](deploy/profile.env.example) 複製相符的區塊。外部 `connex_network` 必須已包含 `postgres` 服務。舊有拼字錯誤的 `env.exmaple` 仍保留作為相容範本；新的部署請使用 `.env.example`。

Compose 僅使用指定的 `--env-file` 值來插入明確允許的環境變數；它不會將任一檔案完整注入容器。因此，一個設定檔的前端 JWT 公鑰或分析回饋端點，絕不會存在於另一個設定檔的容器中。

下列非機密值是 [`docker-compose.yml`](docker-compose.yml) 中各服務專屬的設定，而非從 `.env` 載入。它們會依設定檔隔離：

| 設定 | 隔離原因 |
| --- | --- |
| `DATABASE_NAME` | 每個服務使用自己的 `[bu]_[cls|ecls]` 資料庫。 |
| `FASTAPI_ROOT_PATH` | 對應 Nginx API 路由，例如 `/wtchk/api` 或 `/ecls/wtchk/api`。 |
| `IS_ECLS_ENABLED` | 選擇 CLS 或 ECLS 處理行為。 |
| `DEPLOYMENT_PROFILE`、`LOG_SERVICE_NAME` | 讓日誌與診斷資訊可歸屬至單一部署。 |
| `API_JWT_PUBLIC_KEY` | 每個服務只取得相符前端的 RS256 公鑰；私鑰只存在前端。 |
| `ANALYZE_FEEDBACK_API_URL` | 每個服務會從具命名空間且被忽略的設定檔環境檔取得自己的分析回饋端點。 |
| `ANALYZE_FEEDBACK_IS_INCLUDE_CHANNEL`、`SURVEY_EXPORT_COLUMN_*` | 每個設定檔各有 Compose 值，初始為 `false`；如需啟用功能，請編輯該設定檔的服務區塊。 |

前端 JWT 公鑰與分析回饋端點皆為設定檔專屬設定，只會儲存在被 Git 忽略的 `deploy/profile/<profile>.env`。例如，`wtchk_cls` 只會使用 `WTCHK_CLS_API_JWT_PUBLIC_KEY` 與 `WTCHK_CLS_ANALYZE_FEEDBACK_API_URL`。Microsoft Entra 的租用戶、用戶端 ID、用戶端密鑰與回呼只設定在相符的 Next.js 前端。

分析回饋是否包含渠道，以及所有問卷匯出欄位旗標，都是由版本控制的設定檔專屬設定，位於 `docker-compose.yml`。它們不再從 `.env` 讀取；請只修改目標設定檔的服務區塊。

### 啟動設定檔

必須提供設定檔名稱、其專屬環境檔與共用 `.env`。例如，啟動 `wtchk_cls`：

```bash
docker compose \\
  --profile wtchk_cls \\
  --env-file ./deploy/profile/wtchk_cls.env \\
  --env-file ./.env \\
  up -d --build
```

共用值只應放在 `.env`，不要在兩個檔案中重複宣告同一變數；若變數同時存在，較後面的 `--env-file` 會優先。

如需啟動多個彼此隔離的 BU，請列出所有設定檔，並提供每個設定檔對應的環境檔：

```bash
docker compose \\
  --profile wtchk_cls \\
  --profile wtchk_ecls \\
  --env-file ./deploy/profile/wtchk_cls.env \\
  --env-file ./deploy/profile/wtchk_ecls.env \\
  --env-file ./.env \\
  up -d --build
```

FastAPI 只接受相符前端簽發、有效期 60 秒的 RS256 Bearer token。簽發者為 `clsense-frontend:<profile>`，受眾為 `clsense-api:<profile>`；後端不再提供登入、續期、Entra 回呼或使用者管理端點。

### 區域部署群組

每個後端服務除了原本的個別設定檔外，亦會加入一個區域 Compose
設定檔。以 `--profile asia` 或 `--profile eu` 可啟動整個區域；對應的
環境檔必須包含該群組全部設定檔的有效值。

```bash
# Asia: WTCHK, WTCMY, WTCSG, WWHK, PNSHK, FTRHK, WTCTH, WTCID,
#       WTCTW, WTCPH, WTCVN, WTCCN
docker compose --env-file ./deploy/profile/asia.env --env-file ./.env \
  --profile asia up -d --build

# EU: SD, KVNL, DRLV, DRLT, ICIBE, ICINL, KVBE, MAT, MCH, MCZ, MFR,
#     MHU, MIT, MRO, MSK, TPS, WTCTR, WTCUA, SVRUK
docker compose --env-file ./deploy/profile/eu.env --env-file ./.env \
  --profile eu up -d --build
```

[`deploy/profile-groups.json`](deploy/profile-groups.json) is the source of
truth for the BU-to-group mapping. It applies to both CLS and ECLS profiles;
SVRUK has an ECLS profile only. The analytics overlay inherits the same group
profiles when used with the main Compose file.

## 可觀測性與資料保留

伺服器會同步將結構化 JSON 日誌輸出至 stdout 與每日輪替的持久化檔案。`docker logs` 可查看即時及近期紀錄；每個設定檔專屬的 `/var/log/clsense/server.log` volume 則保存完整歷史。每個請求都會產生完成紀錄，包含 UTC 時間戳記、服務、設定檔、請求 ID、方法、路徑、狀態、耗時、用戶端 IP、程式來源與執行緒。請求 ID 亦會在 `X-Request-ID` 回傳；請求中介層絕不記錄 query string、HTTP body 或憑證。未預期錯誤會包含類型、原因與堆疊追蹤。

`SERVER_LOG_RETENTION_DAYS=30` 為預設值，定義於 `.env.example`，並控制每日輪替應用程式日誌的保存期。無法建立或寫入持久化檔案時，服務會繼續只輸出 stdout，並在 `docker logs` 寫出一筆 `CRITICAL` 診斷事件。Docker 仍將每個服務的本機 JSON log 限制為十個、每個 10 MiB，因此精確的 30 天歷史應從持久化 volume 讀取。

私有營運儀表板由 Grafana、Loki 與 Alloy overlay 提供：

```bash
GRAFANA_ADMIN_PASSWORD='replace-me' docker compose \
  -f docker-compose.yml -f docker-compose.observability.yml up -d loki alloy grafana
```

Grafana 預設只在 `127.0.0.1:3300` 監聽。Loki 與 Alloy 沒有主機連接埠，且只加入 internal network。Alloy 唯讀掛載全部 61 個設定檔的日誌 volume，只追蹤目前的 `server.log`；輪替檔案仍作為非 Loki 備援，不會自動回填。Loki 使用單機 TSDB/filesystem 並由 compactor 保存 30 天。

### n8n execution dashboard

`n8n Execution Operations` dashboard is supplied with the observability overlay.
It uses a dedicated collector, rather than a Grafana REST plugin, to poll n8n's
public API every 30 seconds and write safe, completed-execution summaries to
Loki. The collector retains its SQLite outbox in a Docker volume, backfills up
to 30 days where n8n history is available, and never stores node input/output,
error messages, stacks, URLs, or credentials.

Create an n8n API key in **Settings > n8n API**. On n8n Enterprise, give it
only `execution:list`, `execution:read`, and `workflow:list`. Put the key in
the ignored deployment `.env` as `N8N_API_KEY`; never commit it. The Kafka/n8n
Compose stack must also be running after the checked-in shared
`connex_network` attachment has been applied.

```bash
GRAFANA_ADMIN_PASSWORD='replace-me' N8N_API_KEY='replace-me' docker compose \
  -f docker-compose.yml -f docker-compose.observability.yml up -d \
  loki alloy grafana n8n-execution-collector
```

The collector has no host port. Its Docker health check becomes healthy only
after a successful n8n poll and Loki heartbeat; failed delivery remains in the
outbox and is replayed on the next successful poll.

If Loki was already running before this change, restart it once so it reloads
the 720-hour ingestion-age setting from its mounted configuration.

`DATA_RETENTION_DAYS=30` 只控制營運資料。資料保留會在啟動後及每個 `RETENTION_CHECK_INTERVAL_SECONDS`（預設為 86400）週期執行，並只會清除早於截止日的資料：

- 已完成或失敗的上傳工作及其錯誤列；

它絕不刪除問卷、門市、部門、主題、外送服務或其他業務資料。

## 資料庫遷移

當 `DATABASE_AUTO_MIGRATE=true` 時，啟動程序會套用已提交的 Alembic 遷移。自動產生遷移預設停用，並在 Compose 中強制停用，因此正式環境容器絕不會修改已簽出的遷移原始碼。

請從後端目錄手動建立並檢閱結構變更：

```bash
cd backend
alembic revision --autogenerate -m "描述結構變更"
alembic upgrade head
```

`DATABASE_BOOTSTRAP_SCHEMA=true` 可為空白的本機資料庫啟用 SQLAlchemy `create_all()` 初始化流程。管理員只存在每個設定檔的 Next.js frontend auth 資料庫。
