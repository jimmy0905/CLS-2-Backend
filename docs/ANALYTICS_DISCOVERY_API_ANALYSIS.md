# Analytics Discovery API 收斂分析

> 文件狀態：詳細分析與後續建議；本次不移除額外 discovery endpoints
>
> 導覽：[Backend 文件索引](README.md)
>
> 最後核對：2026-09-06

## 結論

目前 discovery surface 同時包含 static catalog、selection resolver、curated presets 及 live-data
lookup，責任邊界並不一致。`builder/measures` 的資訊已完全包含於
`POST /analytics/builder/options {}`，因此本次已移除；`query-capabilities` 與
`query-combinations` 雖有明顯重疊，但仍可能承擔 server preflight 或 external preset contract，
未完成 consumer audit 前不應一併刪除。

長期應收斂成四個清楚層次：immutable metadata、selection-dependent resolution、live-data
discovery、execution。不要建立把四者混在一起的 mega-bootstrap response。

## 現況與可推導性

| Endpoint | 真正新增的資訊 | 可否由其他 response 推導 | 判斷 |
| --- | --- | --- | --- |
| `GET /analytics/catalog` | Versioned fields、metric targets、visibility、grain／query limits | 核心來源 | 保留為唯一 static metadata owner |
| `POST /analytics/query-capabilities` | 指定 target／aggregation pair 的 preflight、fields、filter operators、result type | 大部分可由 catalog 推導 | 有 server-side ambiguity／pair validation 價值，但 response 高度重複 |
| `GET /analytics/query-combinations` | 程式內建並經 active catalog 驗證的 curated query templates | 與 published charts／catalog rules 部分重疊 | 先做 consumer audit；名稱易與 `catalog.combinations` 混淆 |
| `GET /analytics/builder/measures` | 跨 grain flatten、enum-expanded measures | 完全包含於 `builder/options {}` | 已移除，現時回傳 `404` |
| `POST /analytics/builder/options` | Partial selection 的 grain resolution、剩餘合法選項及完成 query | 不能由 static catalog 簡單推導 | 保留為唯一 contextual resolver |
| `GET /analytics/catalog/availability` | 指定 view 的 live non-null counts／rates | 不可由 immutable metadata 推導 | 保留獨立 TTL／成本 |
| `POST /analytics/filter-options` | 受目前 filter、search、cursor 影響的 live distinct values／counts | 不可由 catalog 推導 | 保留獨立 pagination／cache policy |

## 主要重疊

### `query-capabilities` 對 `catalog`

`allowed_dimensions` 實際是指定 resolved view 中 caller 可見的全部 published fields；
`filter_members` 是其中 `filterable=true` 的子集。Operator 目前只由 field `data_type` 決定，
而 `result_type` 已存在於 catalog 的 metric target aggregation。若把 allowed operators 明確加入
catalog field，Frontend 可由 catalog 與 builder resolution 建立相同 selector。

此 endpoint 剩下的獨有價值是 server-side target／aggregation pair preflight：它可在 execution
前拒絕 unknown、ambiguous 或 grain-incompatible pair。移除前必須決定這個 preflight 是由
`builder/options` 承擔，還是讓 `/analytics/query` 成為唯一 validation boundary。

### `query-combinations` 對 catalog／published charts

`catalog.combinations` 描述可組合規則、grain 與上限；`query-combinations` 則回傳 curated、可直接
執行的 query templates。兩者名稱相近但語意不同。部分 template 又與 published chart
definition 重疊，使 consumer 難以判斷它是能力描述、產品 preset，還是 dashboard definition。

目前 Dashboard 只讀取完整 `query-combinations` response 的 `count`，沒有執行 templates。這是
明確的 overfetch，但不能據此推斷沒有其他 external consumer。

### Builder bootstrap

Custom Query 與 Compare 曾同時載入 catalog、measures、options、availability、capabilities，再按
field 呼叫 filter-options。`builder/measures` 是完全重複的 bootstrap，所以已改為共用 query key
的 `builder/options {}`，並從 `available_measures` 建立 selector。Selection 非空時仍呼叫相同
options endpoint；catalog、bootstrap 與 selection response 的 `model_version` 不一致時重新載入。

`builder/options` 每次 selection 變動仍會回傳完整 `available_measures` 與 dimension objects，
payload 有重複，但它維持單一、權威的 contextual resolver。要優化 bandwidth，可日後加入明確
cache／ETag 或 response projection，而不是重新拆一個 measures endpoint。

## 不應合併的 live discovery

`catalog/availability` 與 `filter-options` 依 live database／Cube 結果變動，與 immutable catalog
有不同的 freshness、成本及 failure mode：

- Catalog 以 model version 為 identity，可長時間保存在 client memory。
- Availability 可能掃描 reporting view，現行 TTL 最多 15 分鐘。
- Filter options 受 selection、search、count order 與 cursor 影響，且可能有多頁。
- Live discovery 的 timeout／unavailable 不應使 static catalog bootstrap 整體失敗。

因此不建議把它們塞進一個 mega-bootstrap。這會令低成本 immutable metadata 綁定高成本 live
query，亦無法給各部分正確的 TTL、pagination、retry 與觀測指標。

## 建議的長期分層

1. `GET /analytics/catalog`：唯一 static、role-visible、versioned metadata。
2. `POST /analytics/builder/options`：唯一 selection-dependent resolver；空本文同時是 builder bootstrap。
3. `GET /analytics/catalog/availability` 與 `POST /analytics/filter-options`：獨立 live-data discovery。
4. `POST /analytics/query`：唯一 ad-hoc aggregate executor。
5. `/analytics/charts/*`：published-definition 的讀取與 execution boundary。

## 後續 migration 建議

### A. 收斂 `query-capabilities`

1. 在 catalog field 加入明確 `allowed_filter_operators`，並把它納入 model-version contract tests。
2. Frontend 以 catalog fields、operators 及 `builder/options` resolved view 建立 filter selector。
3. 記錄 `query-capabilities` caller，連續觀察所有 production profiles。
4. 確認沒有 external preflight consumer 後 hard-remove endpoint、BFF allowlist、types 及 tests。

### B. 決定 `query-combinations` 的產品身份

1. 先移除 Dashboard 的 count-only request，因為它沒有產品功能。
2. 搜尋 Frontend 以外的 integration、報表及 automation consumers。
3. 若沒有 template consumer，刪除 endpoint；若 presets 是實際產品能力，將其移至 catalog 的
   明確 `presets` 欄位，避免與 grain `combinations` 同名。
4. Published charts 繼續是 dashboard definition，不與 ad-hoc presets 混用 lifecycle。

### C. 維持非目標

- 不把 availability 或 filter values 合併到 catalog／builder bootstrap。
- 不因 response 重複便把 contextual resolution 複製到 Frontend。
- 不在缺少 external-consumer 證據時刪除 `query-capabilities` 或 `query-combinations`。

本次變更只落實確定重複的 `builder/measures` 移除；上述 A／B 應另開 migration，獨立收集
traffic、更新 contract 並安排 breaking-change rollout。
