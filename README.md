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

Compose 僅使用指定的 `--env-file` 值來插入明確允許的環境變數；它不會將任一檔案完整注入容器。因此，一個設定檔的 Azure OAuth 憑證或分析回饋端點，絕不會存在於另一個設定檔的容器中。

下列非機密值是 [`docker-compose.yml`](docker-compose.yml) 中各服務專屬的設定，而非從 `.env` 載入。它們會依設定檔隔離：

| 設定 | 隔離原因 |
| --- | --- |
| `DATABASE_NAME` | 每個服務使用自己的 `[bu]_[cls|ecls]` 資料庫。 |
| `FASTAPI_ROOT_PATH` | 對應 Nginx API 路由，例如 `/wtchk/api` 或 `/ecls/wtchk/api`。 |
| `IS_ECLS_ENABLED` | 選擇 CLS 或 ECLS 處理行為。 |
| `DEPLOYMENT_PROFILE`、`LOG_SERVICE_NAME` | 讓日誌與診斷資訊可歸屬至單一部署。 |
| `FRONTEND_URL`、`AZURE_REDIRECT_URI` | Compose 會依設定檔，從共用的 `PUBLIC_BASE_URL` 推導這些路徑。 |
| Azure AD OAuth 憑證 | 每個服務會從具命名空間且被忽略的設定檔環境檔取得自己的租用戶、用戶端 ID 與用戶端密鑰。 |
| `ANALYZE_FEEDBACK_API_URL` | 每個服務會從具命名空間且被忽略的設定檔環境檔取得自己的分析回饋端點。 |
| `ANALYZE_FEEDBACK_IS_INCLUDE_CHANNEL`、`SURVEY_EXPORT_COLUMN_*` | 每個設定檔各有 Compose 值，初始為 `false`；如需啟用功能，請編輯該設定檔的服務區塊。 |

Azure AD OAuth 憑證與分析回饋端點皆為設定檔專屬設定，只會儲存在被 Git 忽略的 `deploy/profile/<profile>.env`。請將 [`deploy/profile.env.example`](deploy/profile.env.example) 中所需的設定檔區塊複製到該檔案。例如，`wtchk_cls` 只會使用 `WTCHK_CLS_AZURE_TENANT_ID`、`WTCHK_CLS_AZURE_CLIENT_ID`、`WTCHK_CLS_AZURE_CLIENT_SECRET` 與 `WTCHK_CLS_ANALYZE_FEEDBACK_API_URL`。通用 Azure OAuth 與 `ANALYZE_FEEDBACK_API_URL` 值會在每個服務中刻意覆寫，以避免跨設定檔繼承。

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

共用的 `PUBLIC_BASE_URL` 預設為本機使用的 `http://localhost:3000`。啟用 Azure OAuth 前，請在 `.env` 將它設為公開的 Nginx 來源，以確保產生的各設定檔重新導向 URI 已向 Azure 註冊。

## 可觀測性與資料保留

伺服器會同步將結構化 JSON 日誌輸出至 stdout 與每日輪替的持久化檔案。`docker logs` 可查看即時及近期紀錄；每個設定檔專屬的 `/var/log/clsense/server.log` volume 則保存完整歷史。每個請求都會產生完成紀錄，包含 UTC 時間戳記、服務、設定檔、請求 ID、方法、路徑、狀態、耗時、用戶端 IP、程式來源與執行緒。請求 ID 亦會在 `X-Request-ID` 回傳；請求中介層絕不記錄 query string、HTTP body 或憑證。未預期錯誤會包含類型、原因與堆疊追蹤。

`SERVER_LOG_RETENTION_DAYS=30` 為預設值，定義於 `.env.example`，並控制每日輪替應用程式日誌的保存期。無法建立或寫入持久化檔案時，服務會繼續只輸出 stdout，並在 `docker logs` 寫出一筆 `CRITICAL` 診斷事件。Docker 仍將每個服務的本機 JSON log 限制為十個、每個 10 MiB，因此精確的 30 天歷史應從持久化 volume 讀取。

`DATA_RETENTION_DAYS=30` 只控制營運資料。資料保留會在啟動後及每個 `RETENTION_CHECK_INTERVAL_SECONDS`（預設為 86400）週期執行，並只會清除早於截止日的資料：

- 登入紀錄；
- 已完成或失敗的上傳工作及其錯誤列；

它絕不刪除問卷、使用者、門市、部門、主題、外送服務或其他業務資料。

## 資料庫遷移

當 `DATABASE_AUTO_MIGRATE=true` 時，啟動程序會套用已提交的 Alembic 遷移。自動產生遷移預設停用，並在 Compose 中強制停用，因此正式環境容器絕不會修改已簽出的遷移原始碼。

請從後端目錄手動建立並檢閱結構變更：

```bash
cd backend
alembic revision --autogenerate -m "描述結構變更"
alembic upgrade head
```

`DATABASE_BOOTSTRAP_SCHEMA=true` 可為空白的本機資料庫啟用舊版 SQLAlchemy `create_all()` 初始化流程。除非同時設定 `BOOTSTRAP_DEFAULT_ADMIN=true` 與非空的 `BOOTSTRAP_DEFAULT_ADMIN_PASSWORD`，否則新資料庫不會建立管理員。
