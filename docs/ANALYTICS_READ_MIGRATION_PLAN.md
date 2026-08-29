# Analytics 讀取遷移與舊功能移除

採用兩階段遷移。第一階段新增受治理的 Analytics 記錄查詢等效能力、以管理員角色保護資料異動，並移除明確淘汰的 action／log／classification API 與資料。第二階段只會在用戶端完成遷移，且每個設定檔皆已啟用 Analytics 後，才移除舊讀取端點。

受治理的 Analytics 語意仍是唯一準則：軟刪除的問卷持續排除、assignment grain 持續分離，並接受 Cube 的新鮮度窗口。為維持相容性，問卷記錄回應會保留舊有 `sentiment` 欄位與標準的 `topic_sentiment`。

## 步驟 1 — 新增受治理的 Analytics 記錄查詢與匯出

- 為 `surveys`、`stores`、`departments`、`channels`、`delivery_services` 與 `topics` 新增 `POST /analytics/records/query`。
- 接受最多 20 個具型別且列入允許清單的篩選條件、最多三個允許排序欄位、頁碼／每頁數量及可選時區。問卷分頁上限為 100，預設為 `reported_at DESC, id DESC`；主資料分頁上限為 1,000，預設為 `id ASC`。
- 回傳資源專屬的分頁項目。問卷項目須保留目前巢狀的門市、渠道、外送服務、部門、主題與關鍵字物件，並包含舊有與標準的 sentiment 欄位。
- 對即時資料庫執行記錄查詢，排除已刪除問卷，並以 `EXISTS` 述詞實作 assignment 篩選以避免重複列。
- 擴充 `POST /analytics/exports`，加入互斥的問卷 `record_query` 輸入，同時保留擁有權、已設定欄位、公式跳脫、到期機制及 250,000 列上限。

## 步驟 2 — 完成儀表板 Analytics 等效能力

- 將內建的 `first_reported_at`、`last_reported_at` 與 `last_updated_at` 指標加入 Python semantic catalog、Cube allowlist 與核心 survey model。
- 驗證儀表板遷移指南中每個 `/dashboard/*` 替代請求本文。
- 彙總資料使用 `/analytics/query`；`total_count_for_option` 使用沒有所選欄位篩選的 `/analytics/filter-options`；需要以零補列的未使用門市、部門及主題使用 `/analytics/records/query`。
- 持續不支援跨 assignment 的彙總篩選，並記錄受治理的 grain 與新鮮度差異。

## 步驟 3 — 強制管理員異動並移除淘汰的 action／log 功能

- 對 survey、channel、delivery-service 與 topic 的 POST、PUT、DELETE 路由要求 `require_admin`，但不限制過渡期間的 GET 路由。
- 移除 `POST /surveys/extract-total` 及其專用 DTO／匯入；保留 ingestion 所使用的擷取輔助程式。
- 移除完整的 `/actions` 與 `/user-behavior-logs` router、action／email 的 LLM 與 SMTP 工具、action／email Pydantic 型別、過時的郵件相依項與範例設定、app 註冊、資料保留 hook 及文件。
- 移除 `Action`、`GeneratedEmail`、`EmailRecord` model 與 User 關聯。
- 新增 Alembic revision `0010`，刪除 `actions`、`generated_emails`、`email_records`。降版會重建空白 schema，但無法還原資料列。

## 步驟 4 — 驗證第一階段行為並遷移用戶端

- 測試記錄篩選、排序、分頁、時區、巢狀回應、舊 sentiment、未使用的主資料值、assignment 篩選與已刪除列排除。
- 測試 viewer/admin 授權、Analytics 功能閘門、no-store 標頭、匯出、儀表板等效性、已移除的 OpenAPI 路徑、遷移中繼資料與資料保留清理。執行完整的後端 pytest 與 Cube 測試套件。
- 發佈 query book 並將用戶端遷移至 Analytics。在每個部署設定檔啟用 Analytics，然後觀察請求日誌，直到連續七天沒有呼叫舊讀取路由。

## 步驟 5 — 移除已遷移的舊讀取路由

- 通過第一階段驗收閘門後，移除所有 `/dashboard/*` 路由。
- 移除 `GET /surveys`、`GET /surveys/{survey_id}` 與 `GET /surveys/download`。
- 移除 `/channels`、`/delivery_services` 與 `/topics` 下的 GET 清單／詳細資料路由，但保留其僅限管理員的異動路由。
- 更新 OpenAPI 與遷移文件，並重新執行等效性、授權、後端及 Cube 回歸測試。

## 假設

- 刪除三張營運歷程表是刻意的決策，不需封存；降版只會還原 schema。
- Analytics 保留業務內容，而非舊回應 envelope。
- 現有未提交的時區與 Analytics 變更屬於使用者，合併時不得覆寫。
