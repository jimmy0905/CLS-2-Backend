# CLSense Backend

> 文件狀態：現行元件導覽
>
> 最後核對：2026-09-03

FastAPI Backend 提供問卷、CSV 上傳、主資料、策略、translation、legacy dashboard 及受治理
Analytics API。Production image 是 profile-neutral；region、database、API base path、static
bearer、logging identity 及 Cube HMAC secret 都由 superproject 的 regional generator 在 runtime
注入。

## 結構

| 路徑 | 責任 |
| --- | --- |
| [`backend/app.py`](backend/app.py) | ASGI app、middleware、lifecycle 與 router registration |
| [`backend/features/`](backend/features/) | 依功能切分的 HTTP／service／repository code |
| [`backend/infrastructure/`](backend/infrastructure/) | PostgreSQL、migration、Cube、translation 及 collector integrations |
| [`backend/migrations/`](backend/migrations/) | Alembic migrations |
| [`backend/contracts/`](backend/contracts/) | route、OpenAPI 與 metadata snapshots |
| [`backend/tests/`](backend/tests/) | offline、contract 及 opt-in analytics E2E tests |
| [`cube/`](cube/) | shared regional multi-tenant Cube image |
| [`observability/`](observability/) | Grafana dashboards、Loki／Alloy 及 n8n collector assets |
| [`notebooks/`](notebooks/) | 一次性、人工覆核的 legacy data migration notebook；不在 app startup 執行 |
| [`docs/`](docs/) | Analytics 契約、整合指南、QA、遷移狀態與歷史 |

詳細文件先從 [Backend 文件索引](docs/README.md) 進入，不要直接把 migration/history 文件
當作現行 API contract。

## HTTP boundary

主要 router family：

- `/health`：同時驗證 API process 與 database connectivity。
- `/surveys`、`/tasks`、`/stores`、`/departments`、`/channels`、`/delivery_services`、`/topics`：問卷、上傳及主資料。
- `/strategy`、`/translator`：策略生成與翻譯整合。
- `/analytics`、`/admin/analytics`、`/internal/analytics`：受治理分析；完整契約見 [`docs/README.md`](docs/README.md)。
- `/dashboard`：遷移期間保留的 legacy read endpoints；新 client 不應增加依賴。

Production 的外部 prefix 由 profile catalog 生成，例如 `wtchk_cls` 是 `/wtchk/api`；FastAPI
內部 route 本身不硬編碼 customer prefix。Browser 不直接持有 Backend bearer，必須經
Frontend same-origin BFF。

## 本機開發

需求為 Python 3.11 及可連接的 PostgreSQL。從本 submodule root 建立環境：

```sh
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements-dev.txt
```

設定 `backend/core/config.py` 所要求的 database、session、JWT 與 integration environment
後，在 `backend/` 啟動：

```sh
cd backend
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Docs／OpenAPI URL 預設關閉；只在受控本機環境以 `FASTAPI_DOCS_URL`、
`FASTAPI_OPENAPI_URL` 開啟。不要用 production credential 執行本機測試。

整套跨元件本機環境應使用 superproject 的
[generated local bundle](../deployment/README.md#本機開發-bundle)，避免自行建立另一份 Compose。

## Database migration

Production runtime 固定使用 `DATABASE_AUTO_MIGRATE=false`。Regional `deployctl bootstrap`
會針對每個所選 profile 執行專用入口：

```sh
python -m infrastructure.database.migrate
```

該一次性 job 會以 `DATABASE_AUTO_MIGRATE=true` 啟動；失敗時 application container 不會被
替換。只可部署 backward-compatible expand／contract migrations，因 image rollback 不會
downgrade PostgreSQL。Fresh database 會先建立 SQLAlchemy table schema，再安裝 Cube 所需的
SQL-only analytics functions／views，最後 stamp 到 Alembic head；repair revision 亦會修復由舊
fresh-install 路徑建立但缺少這些物件的 database。

通用 analytics readonly role helper 是
[`scripts/provision_analytics_readonly.sql`](scripts/provision_analytics_readonly.sql)。Regional
bundle 使用等效的 profile-parameterized provisioning script；
[`provision_wtchk_cls_analytics_readonly.sql`](scripts/provision_wtchk_cls_analytics_readonly.sql)
只為 legacy 環境保留，新部署不可使用。

## 測試

與 CI 相同的核心檢查如下；測試 environment variable 使用非 production 值：

```sh
ANALYTICS_E2E=0 python -m pytest -q -m "not analytics_e2e"
node --test cube/test/*.test.js
PYTHONPATH=backend python scripts/verify_backend_contracts.py
python -m compileall -q backend
```

Live analytics E2E 是 opt-in。先複製 [`env.testing.example`](env.testing.example)，填入對應
profile 的測試 host／token，再依
[`docs/ANALYTICS_DASHBOARD_TEST_REQUEST.md`](docs/ANALYTICS_DASHBOARD_TEST_REQUEST.md)
執行；不可在一般 offline test 意外連線 production。

Production build／release、secret 及 rollback 規則以 superproject 的
[部署操作手冊](../deployment/README.md)為準。
