# Backend 文件索引

> 文件狀態：現行導覽
>
> 最後核對：2026-09-03

本索引是 Backend 詳細文件的入口。文件狀態用來區分可依賴的契約、正在進行的 migration
及只供稽核的歷史紀錄。若本文與 router／tests 不一致，以程式碼為執行事實，並在同一變更
修正本文。

## 現行契約

| 文件 | Canonical responsibility |
| --- | --- |
| [Analytics API 參考](ANALYTICS_API_REFERENCE.md) | endpoint、auth、request／response 及錯誤行為 |
| [Goal-first Analytics 查詢契約](ANALYTICS_GOAL_FIRST_CONTRACT.md) | metric target、aggregation、semantic view grain 與 query discovery |
| [Semantic View、Dimension 與 Metric 使用手冊](user-manual/SEMANTIC_VIEW_DIMENSION_METRICS_GUIDE.md) | 使用者選擇流程、完整組合與範例 |
| [Frontend Dashboard Analytics 工作流程](FRONTEND_DASHBOARD_ANALYTICS_WORKFLOW.md) | Frontend discovery、availability、filter、chart loading 與 cache 行為 |

閱讀順序：先了解 goal-first 心智模型，再查看 API reference；需要 query builder 或產品範例
時才進入 user manual。不要在多份文件各自維護 endpoint 清單，API reference 是唯一 owner。

## QA 操作手冊

| 文件 | 用途 |
| --- | --- |
| [Analytics 儀表板遷移驗證](ANALYTICS_DASHBOARD_TEST_REQUEST.md) | profile 上線前的 E2E、legacy comparison 及證據要求 |

自動化 runner 預設停用 live request，須明確設定 `ANALYTICS_E2E=1`。測試資料、token 及
comparison manifest 都不可提交。

## 遷移中

| 文件 | 目前狀態 |
| --- | --- |
| [Analytics 讀取遷移與舊功能移除](ANALYTICS_READ_MIGRATION_PLAN.md) | 新 Analytics／record query 已存在；`/dashboard/*` routers 尚未移除 |
| [Dashboard → Analytics query book](DASHBOARD_ANALYTICS_MIGRATION.md) | 遷移及等效性測試使用；新 client 應直接使用 `/analytics` |

移除 legacy routes 的 gate 是：所有 production profiles 啟用 Analytics、Frontend 無 legacy
呼叫、query book 等效性通過，且 contract snapshot 更新。未滿足時不得只依計畫文字刪除
router。

## 歷史與稽核

| 文件 | 注意事項 |
| --- | --- |
| [舊端點至 Cube 查詢對照表](LEGACY_ENDPOINT_CUBE_QUERIES.md) | 保存 pre-0012 多 metric 脈絡；範例不可直接執行 |
| [Frontend authentication and observability cutover](FRONTEND_AUTH_OBSERVABILITY_CUTOVER.md) | 一次性 cutover 紀錄；舊 profile deployment path 已淘汰 |

歷史文件不再擁有現行設定。需要部署、backup 或 n8n／Grafana 操作時，使用 superproject 的
[deployment runbook](../../deployment/README.md)；跨元件決策見
[架構決策紀錄](../../.github/DECISIONS.md)。

## 維護規則

- 新增 Analytics endpoint：更新 API reference、route／OpenAPI snapshots 及 tests。
- 改變 query semantics：先更新 goal-first contract，再更新 user manual 範例與 Frontend workflow。
- 完成 migration gate：更新 migration plan、移動本索引分類，並將原因 append 到 decisions log。
- 文件內 URL 應使用 `<public-host>` 或 local example，不放 customer hostname／token。
- 每次變更執行 superproject 的 `python3 -m unittest discover -s deployment/tests -v` 驗證相對連結。
