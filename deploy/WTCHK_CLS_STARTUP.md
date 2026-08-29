# `wtchk_cls` Docker 啟動教學

本指南用於啟動 `wtchk_cls` 部署設定檔的 CLSense 後端及 Cube Analytics 服務。

> Compose 設定檔名稱為使用底線的 `wtchk_cls`。Docker 服務名稱（例如 `backend-wtchk-cls`）使用連字號。

## 1. 先決條件

安裝含 Compose 外掛的 Docker，並從儲存庫根目錄執行所有命令：

```bash
cd /path/to/CLSense-Backend
docker version
docker compose version
```

部署需要：

- 已填妥的根目錄 `.env`，其中包含共用後端資料庫與安全性設定；
- 位於 `deploy/profile/wtchk_cls.env` 的 BU 專屬 Azure OAuth 與回饋設定；
- 已存在的 `connex_network` Docker 網路；
- 該網路上可透過 `postgres:5432` 存取的 PostgreSQL；
- 已存在的 `wtchk_cls` 資料庫；
- Cube 專用的唯讀 PostgreSQL 角色；
- 已測試的 Cube 與 Cube Store `v1.7.26` 映像 digest。

檢查外部網路：

```bash
docker network inspect connex_network
```

若為新的本機環境且網路尚不存在，請建立它：

```bash
docker network create connex_network
```

## 2. 設定 BU 與 Analytics 設定檔

建立被忽略的設定檔環境檔。切勿覆寫既有檔案，因為它可能已包含部署密鑰。聚焦該 BU 的應用程式範本為 [`deploy/bu.env.example`](bu.env.example)，完整設定檔目錄為 [`deploy/profile.env.example`](profile.env.example)，Cube 變數範本為 [`deploy/analytics.env.example`](analytics.env.example)。BU 與 Cube 設定都應放在同一份 `deploy/profile/wtchk_cls.env` 檔案。

```bash
cp deploy/analytics.env.example deploy/profile/wtchk_cls.env
```

加入 `wtchk_cls` BU 應用程式設定：

```dotenv
WTCHK_CLS_AZURE_CLIENT_ID=
WTCHK_CLS_AZURE_CLIENT_SECRET=
WTCHK_CLS_AZURE_TENANT_ID=
WTCHK_CLS_ANALYZE_FEEDBACK_API_URL=
```

主機端名稱必須包含 `WTCHK_CLS_` 前綴。Compose 會將前三個值對應至 `backend-wtchk-cls` 容器內的 `AZURE_CLIENT_ID`、`AZURE_CLIENT_SECRET` 與 `AZURE_TENANT_ID`。刻意不使用通用的主機端 Azure 名稱，因為它們可能在 BU 設定檔間洩漏憑證。

接著在同一檔案設定 Cube Analytics 值：

```dotenv
CUBE_IMAGE_DIGEST=sha256:51d467b223492da5c35139c31760c5329e770028bbe6cb4faa590400e5445941
CUBESTORE_IMAGE_DIGEST=sha256:038d4491cd77799a440655053f8f67ea16d3d2ecceffe812d314e47993f1ce08
CUBESTORE_PLATFORM=linux/amd64

ANALYTICS_DATABASE_PORT=5432
# 本機 Docker PostgreSQL 未啟用 SSL。只有連線至啟用 SSL 的外部 PostgreSQL 伺服器時才設為 true。
ANALYTICS_DATABASE_SSL=false

WTCHK_CLS_ANALYTICS_ENABLED=false
WTCHK_CLS_ANALYTICS_DB_USER=<read-only-postgres-user>
WTCHK_CLS_ANALYTICS_DB_PASSWORD=<password>
WTCHK_CLS_CUBE_API_SECRET=<unique-random-secret-at-least-32-bytes>
WTCHK_CLS_ANALYTICS_METADATA_SECRET=<different-random-secret-at-least-32-bytes>
```

初始的 shadow-validation 期間請維持 `WTCHK_CLS_ANALYTICS_ENABLED=false`。即使互動式 Analytics API 保持停用，內部已簽署的中繼資料端點仍可供 Cube 使用。

Cube 資料庫角色只能具備必要的 `CONNECT`、schema `USAGE` 與報表 `SELECT` 權限，不得擁有資料庫或 schema。

## 3. 啟動前驗證

驗證設定檔專屬的 Analytics 設定：

```bash
python3 scripts/validate_analytics_infra.py \
  --env-file deploy/profile/wtchk_cls.env \
  --profile wtchk_cls
```

驗證合併後的 Compose 設定：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  config --quiet
```

缺少映像 digest 或必要憑證時，該命令會刻意失敗。

## 4. 僅啟動後端

如需在沒有 Cube Analytics 下啟動既有後端：

```bash
docker compose \
  -f docker-compose.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  up -d --build backend-wtchk-cls
```

後端會公開於主機的 `8000` 埠。

### 建立 Cube 唯讀資料庫角色

請先讓後端遷移完成，使受治理的 Analytics view 與 helper function 存在。接著以連線至 `wtchk_cls` 的 PostgreSQL 管理員身分登入 `psql`：

```bash
psql \
  --host <postgres-host> \
  --username postgres \
  --dbname wtchk_cls
```

然後在 `psql` 提示字元中執行佈建檔：

```text
\i scripts/provision_wtchk_cls_analytics_readonly.sql
```

如果資料庫尚未到達 Analytics migration `0009_cube_semantic_catalog`，該 SQL 會執行預檢並在變更角色前停止。

就緒提示字元通常以 `=#` 結尾，例如 `wtchk_cls=#`。以 `-#` 結尾表示先前的 SQL 陳述式尚未完成。佈建檔會自動清除該舊查詢緩衝區；也可在執行 `\i` 前以 `\r` 手動清除。

指令碼會建立或校正 `wtchk_cls_analytics`，並安全提示輸入其密碼。請輸入與 `WTCHK_CLS_ANALYTICS_DB_PASSWORD` 相同的值。它會移除直接的資料表與 sequence 授權，接著只授與資料庫 `CONNECT`、schema `USAGE`、analytics view `SELECT` 與 analytics helper-function `EXECUTE`。重複執行也會透過安全的 `psql` 提示字元輪換該角色密碼。

## 5. 啟動完整 Analytics 堆疊

啟動後端、Cube API、重新整理工作者及被指派的 Cube Store shard：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  up -d --build
```

此設定檔會啟動以下主要服務：

- `backend-wtchk-cls`；
- `cube-api-wtchk-cls`；
- `cube-refresh-wtchk-cls`；
- `cubestore-router-shard-4`；
- `cubestore-worker-1-shard-4`；
- `cubestore-worker-2-shard-4`。

Cube 與 Cube Store 刻意不公開任何主機連接埠。

## 6. 檢查服務健康狀態

顯示服務狀態：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  ps
```

直接檢查後端：

```bash
curl --fail http://localhost:8000/health
```

從私有容器網路內檢查 Cube：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  exec cube-api-wtchk-cls \
  node -e "fetch('http://127.0.0.1:4000/readyz').then(async response => { console.log(response.status, await response.text()); process.exit(response.ok ? 0 : 1); }).catch(error => { console.error(error); process.exit(1); })"
```

## 7. 檢視日誌

持續顯示主要設定檔的日誌：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  logs -f --tail=200 \
  backend-wtchk-cls \
  cube-api-wtchk-cls \
  cube-refresh-wtchk-cls \
  cubestore-router-shard-4
```

## 8. 啟用互動式 Analytics

遷移、中繼資料編譯及 shadow 比較皆健康後，將設定檔設定改為：

```dotenv
WTCHK_CLS_ANALYTICS_ENABLED=true
```

重新建立後端，使其取得新旗標：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  up -d --no-deps --force-recreate backend-wtchk-cls
```

回復方式相反：將旗標改為 `false` 並重新建立後端。這不影響既有的問卷、上傳、儀表板或健康檢查 API。

## 9. 停止設定檔

只停止設定檔專屬後端及 Cube process：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  stop backend-wtchk-cls cube-api-wtchk-cls cube-refresh-wtchk-cls
```

Shard 4 與其他部署設定檔共用。只有在沒有其他 shard-4 設定檔執行時，才停止其 router 與 worker。

若為沒有其他設定檔執行的隔離本機專案，可移除整個 Compose 部署，同時保留 named volume：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  down
```

除非有意刪除 Cube Store 與上傳工作資料，否則請勿加上 `--volumes`。

## 疑難排解

### Compose 回報缺少映像 digest

請將 `CUBE_IMAGE_DIGEST` 及 `CUBESTORE_IMAGE_DIGEST` 設為已於目標架構測試的 `v1.7.26` manifest digest。系統刻意拒絕只提供 tag。

### ARM64 對 Cube Store 回報 `no matching manifest`

Cube 本身有原生 ARM64 manifest，但 Cube Store v1.7.26 只發布 `linux/amd64`。請維持 `CUBESTORE_PLATFORM=linux/amd64`；ARM64 主機上的 Docker Desktop 會透過模擬執行 Cube Store。正式環境及效能／負載驗收必須使用 AMD64 主機，因為模擬會改變延遲與容量。

### 缺少 `connex_network`

以 `docker network create connex_network` 建立它，或啟動通常擁有它的共用基礎設施堆疊。

### Cube 無法連線至 PostgreSQL

確認 `postgres` 已連線至 `connex_network`、`wtchk_cls` 資料庫存在、SSL 設定符合伺服器，且 Analytics 資料庫角色擁有所需的唯讀授權。

### Analytics 端點回傳 404

在 `WTCHK_CLS_ANALYTICS_ENABLED=false` 時這是預期行為。只有 shadow 驗證成功後才啟用旗標。

### Cube 中繼資料編譯失敗

確認 API 與中繼資料 secret 非空、彼此不同、至少含 32 個隨機 bytes，且後端與 Cube 服務中設定一致。接著一併檢查後端及 `cube-api-wtchk-cls` 日誌。
