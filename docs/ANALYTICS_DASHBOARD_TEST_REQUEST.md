# QA 請求：Analytics 儀表板驗證

> 文件狀態：現行 QA 操作手冊
>
> 導覽：[Backend 文件索引](README.md)
>
> 最後核對：2026-09-06

請端對端測試 `wtchk_cls` 的 Analytics 儀表板。目標是確認使用者可登入、探索有效篩選器、
載入預設圖表物件，並驗證現行 Analytics contract；已移除的 legacy endpoints 不再作比較來源。

## 測試流程

1. 開啟 `wtchk_cls` Web 應用程式，使用有效帳號登入。
2. 確認已驗證的工作階段可存取受治理的 Analytics catalog 與已發佈圖表。
3. 從 Analytics filter-options API 載入可用的篩選值。
4. 個別及組合套用篩選條件，確認可用的相依選項正確更新。
5. 開啟下列列出的每個儀表板圖表。
6. 在相同篩選條件與日期脈絡下，擷取圖表／Analytics 回應。
7. 驗證總數、類別標籤、sentiment 計數、平均值、日期區間、空值與排序。
8. 為每一項失敗記錄螢幕截圖或回應內容。

## 儀表板涵蓋範圍

| 儀表板 | 預設圖表 slug | 預期圖表 |
| --- | --- | --- |
| 情緒分布 | `dashboard_sentiment_distribution` | 依回報日期繪製的折線圖 |
| 門市分布 | `dashboard_store_distribution` | 依門市繪製的長條圖 |
| 門市欄位分布 | `dashboard_store_format_distribution` | 依門市格式繪製的長條圖 |
| 渠道及外送服務 | `dashboard_channel_delivery_distribution` | 依渠道及外送服務繪製的長條圖 |
| 主題情緒分數 | `dashboard_topic_sentiment_counts`、`dashboard_overall_topic_sentiment_score`、`dashboard_mixed_topic_sentiment_score` | 情緒計數圖表加上 KPI 圖塊 |
| 主題分布 | `dashboard_topic_distribution` | 依主題繪製的長條圖 |
| 部門分布 | `dashboard_department_distribution` | 依部門繪製的長條圖 |
| 關鍵字分析 | `dashboard_keyword_analysis` | 前 10 名關鍵字長條圖 |
| 資料涵蓋範圍 | `dashboard_first_reported_at`、`dashboard_last_reported_at` | KPI 圖塊 |
| 最後更新日期 | `dashboard_last_updated_at` | KPI 圖塊 |

## 篩選情境

請以以下案例測試儀表板：

- 無篩選條件：確認預設的完整資料結果。
- 以 key 及名稱各選取一個門市。
- 選取多個門市。
- 選取一項門市屬性，例如 `region` 或 `store_format`。
- 渠道與外送服務篩選。
- 在相符的儀表板 grain 上套用主題、部門及關鍵字篩選。
- `POSITIVE`、`NEGATIVE`、`NEUTRAL` 與 `MIXED` 的回應 sentiment 篩選。
- 有界的 `from_date`／`to_date` 範圍，包含日期邊界。
- 非 UTC 時區，最好使用 `Asia/Hong_Kong`。
- 數值分數與 CLS 範圍。
- 回傳沒有相符問卷列的篩選組合。
- 沒有相符問卷列的主資料值；門市、主題及部門應出現以零補列的行為。

不得將 topic 篩選套用至 department 或 keyword assignment 圖表，也不得將 department 篩選套用至 topic 或 keyword 圖表。受治理 API 刻意將這些 assignment grain 分開，以避免多對多列膨脹。

## 結果要求

每個情境中，請以相同的有效篩選脈絡驗證圖表資料：

- response-level 圖表必須使用 `surveys.topic_sentiment`，並比較正向、負向、中性與混合的計數，以及平均主題情緒分數。
- topic、department 與 keyword 圖表必須使用各自 assignment view 的 assignment sentiment。
- 每日結果必須比較相同的本地日期 bucket 與時區。
- 門市結果必須比較門市 key、名稱、開業／結業日期、sentiment 計數、分數平均值與 `total_count_for_option` 支援資料。
- topic 與 department 結果必須包含相同的以零補列主資料值。
- keyword 分析必須在相同篩選條件下回傳相同的前 10 名排序。
- 資料涵蓋範圍必須比較第一個及最後一個未刪除的回報時間戳記。
- 最後更新日期必須記錄受治理模型採用的有效問卷新鮮度語意。

允許文件所述的 Cube 新鮮度窗口。每個新的 Analytics 回應都要記錄回傳的 `freshness_time` 與 `model_version`。

## 驗證與授權檢查

- 未驗證請求會遭拒絕。
- 持有正確 static bearer 的請求可讀取 catalog、圖表與 `/admin/analytics/charts`。
- 圖表清單只包含此 static bearer 可見的已發佈圖表。
- Analytics 回應包含 `Cache-Control: no-store, private`。

## 應交付的證據

請提供：

1. 測試環境與建置／映像版本。
2. 測試使用的帳號角色。
3. 每個情境使用的篩選值與時區。
4. 圖表／Analytics 回應內容；若無法擷取內容，請提供螢幕截圖。
5. 涵蓋範圍表中每個儀表板的通過／失敗結果。
6. 任何不一致之處，包括端點、圖表 slug、篩選脈絡、預期值、實際值，以及其是否由新鮮度、零補列行為、回應塑形或真實計算差異造成。

## 驗收條件

當登入與篩選器探索可運作、所有預設圖表皆可載入、所有已記錄的篩選情境均不發生未預期
錯誤，且結果符合時區、Cube 新鮮度、assignment grain、零補列及
`total_count_for_option` 規則，即通過驗證。

## 可重複使用的 pytest 執行器

此請求的即時、可重複版本位於 `backend/tests/test_analytics_dashboard_e2e.py`。它在一般單元測試執行期間停用，但可對任何公開應用程式 API 的部署執行：

請將 `env.testing.example` 作為本機 VS Code／測試環境範本。將其值複製到被忽略的 `.env` 檔，並在執行前設定對應 profile 的 static API bearer token。

```bash
ANALYTICS_E2E=1 \\
ANALYTICS_E2E_BASE_URL=http://localhost:8000 \\
ANALYTICS_E2E_API_TOKEN=<profile-backend-api-token> \\
.venv/bin/python -m pytest -m analytics_e2e -v \\
  --log-cli-level=INFO \\
  backend/tests/test_analytics_dashboard_e2e.py
```

後端不再接受使用者名稱／密碼；`ANALYTICS_E2E_API_TOKEN` 必須等於對應 profile 的 256-bit bearer token。若 API 位於設定檔路徑之後，請設定 `ANALYTICS_E2E_API_PREFIX=/wtchk/api`。執行器預設使用 `Asia/Hong_Kong` 與寬廣日期範圍；可透過 `ANALYTICS_E2E_TIMEZONE`、`ANALYTICS_E2E_FROM_DATE` 和 `ANALYTICS_E2E_TO_DATE` 覆寫。

執行器會為每個 HTTP 請求記錄一筆 `analytics_e2e query_result`。每筆紀錄包含方法、URL、狀態、請求內容與回應結果。機密值會遮蔽，且預設將記錄值限制在 50,000 bytes；以 `ANALYTICS_E2E_LOG_MAX_BYTES` 變更上限。

VS Code Test Explorer 會使用工作區的 `.env`，並依已提交的工作區設定顯示 INFO 日誌。從 Test Explorer 執行這些即時測試前，請在本機 `.env` 加入 `ANALYTICS_E2E=1` 與 `ANALYTICS_E2E_API_TOKEN`。結果顯示為 `s` 表示即時套件被略過，且未發出 HTTP 查詢，因此沒有可顯示的 query-result 日誌。
套件執行時，請查看 VS Code 的 Python Test Log 或整合式終端機；`Query Results` 面板屬於資料庫查詢擴充功能，不會接收這些 HTTP 測試日誌。

所有 bearer-authenticated 呼叫端都可存取圖表管理路徑；E2E 測試對 `/admin/analytics/charts` 預期回傳 `200`。

執行器只驗證現行 Analytics：已發佈圖表／model-version 一致性、篩選器探索、非 UTC 的有界
日期、數值／無匹配篩選、assignment-grain 隔離、新鮮度中繼資料及 static bearer 存取。
Legacy comparison manifest 與 legacy base URL environment 已移除。
