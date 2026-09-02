# 定向預先彙總重新整理契約

> 文件狀態：現行 Cube／Backend internal contract
>
> 導覽：[Cube 安全邊界與測試](../README.md)
>
> 最後核對：2026-09-03

上傳提交後，FastAPI 會將受影響的報表月份分組為連續日期範圍，並呼叫該設定檔的私有 Cube API：

```http
POST /cubejs-api/v1/pre-aggregations/jobs
Authorization: <短效 profile/refresh_worker Cube JWT>
Content-Type: application/json
```

```json
{
  "action": "post",
  "selector": {
    "contexts": [
      {
        "securityContext": {
          "profile": "wtchk_cls",
          "role": "refresh_worker"
        }
      }
    ],
    "timezones": ["UTC", "Asia/Hong_Kong"],
    "preAggregations": [
      "survey_responses.daily_core",
      "survey_responses.monthly_core",
      "survey_topics.daily_assignments",
      "survey_departments.daily_assignments",
      "survey_keywords.daily_assignments",
      "survey_assignments.daily_topic_departments"
    ],
    "dateRange": ["2026-07-01", "2026-09-01"]
  }
}
```

`dateRange` 只會選取建置範圍與指定範圍相交的分割區。結束日期是最後一個受影響月份之後那個月的第一天。部署的 `ANALYTICS_CUBE_REFRESH_TIME_ZONES` 設定會同時套用至排程重新整理工作者與上傳觸發的重新整理請求。它必須包含儀表板預期提供服務的所有時區；預設值為 UTC 加上 `Asia/Hong_Kong`。
語意檢視受影響的已發佈圖表彙總，會從啟用中的 catalog 版本附加至請求；這對精確維度的非可加性彙總尤其重要。

每個 `survey_assignments` 指標都是對 response key 的相異計數，因此都不可加；其彙總只能用於維度完全相同的查詢。由於 `topic` 與 `department` 來自封閉的擷取清單、且組合數維持很小，因此會建置 `daily_topic_departments`；涉及 `keyword` 的組合則交由 PostgreSQL，因為該維度沒有上限。呼叫端會將請求狀態記錄在上傳作業上。遭拒的請求會顯示為 `analytics_refresh_status=failed`，但不會使已提交的上傳失敗。排查重新整理延遲時，操作人員可透過 Cube 的 `action: get` 契約輪詢回傳的工作 token。

Catalog 發佈獨立運作。它會遞增 `catalogVersion`；Cube 的 `schemaVersion` 回呼會在五秒的本機中繼資料快取內觀察到新版本並重新編譯。絕不可將 catalog 版本變更視為重新整理資料分割區的替代方案。
