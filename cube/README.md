# CLSense regional multi-tenant Cube

> 文件狀態：現行安全邊界與元件導覽
>
> 最後核對：2026-09-03

每區只有一套 shared Cube，服務 regional manifest 所選取的 1–3 個 profiles。Production
topology 與 allow-list 只由 superproject 的 [`deployment/catalog.json`](../../deployment/catalog.json)
及 regional server manifest 生成；本目錄不維護 Compose。

## Topology

| Process | 數量／區 | 責任 |
| --- | --- | --- |
| `cube-api` | 1 | 驗證 Backend 簽發的 profile JWT、執行 query |
| `cube-refresh` | 1 | 只 refresh manifest allow-list 中的 profile contexts |
| `cubestore-router` | 1 | Cube Store routing |
| `cubestore-worker` | 1 | 初始 query／pre-aggregation worker，可在量測後增加 |

所有 selected Backend 都連到 `http://cube-api:4000`。Cube 不經 Nginx 對外公開；Cube
unavailable 時只能令 analytics 暫停，Backend `/health`、問卷、上傳及管理功能仍須可用。

## Profile isolation boundary

[`multitenant/registry.js`](multitenant/registry.js) 是主要 security boundary。它必須：

1. 先拒絕不在 regional allow-list 的 profile。
2. 以該 profile 專屬 HS256 secret 完整驗證 signature、audience、expiry、subject、role 及 security context。
3. 只回傳該 profile 的 PostgreSQL database／readonly role、metadata URL 及 signing secret。
4. 將 Cube app ID、orchestrator ID 及 pre-aggregation schema namespace 成 `clsense_<region>_<profile>`。

[`lib/catalog-repository.js`](lib/catalog-repository.js) 的 metadata cache 以 profile 分開；不可改回
global singleton cache。不同 profile 的 cache hit、driver、JWT 或 pre-aggregation 交叉都屬資料
隔離事故，不是一般 functional bug。

[`lib/refresh-config.js`](lib/refresh-config.js) 只產生 generator 注入的 profile contexts；不得
從 catalog 自動 refresh 同區所有未選 profiles。

Production 的 `cube-api` 只讀由 `cube-refresh` 建立的 pre-aggregation。Local Compose 另開啟
API on-demand fallback：catalog 或 schema 變更令舊 partition 失效時，第一個 query 可自行建立
缺少的 partition；此設定不得帶到 production。

## Model 與 image

- [`cube.js`](cube.js) 組合 registry、catalog repository 與 refresh config。
- [`model/core/`](model/core/) 保存 shared semantic models；customer/profile 差異由 metadata catalog 與 security context 解決。
- [`contracts/catalog.schema.json`](contracts/catalog.schema.json) 驗證 Backend metadata shape。
- [`contracts/preaggregation-refresh.md`](contracts/preaggregation-refresh.md) 定義 upload 後的定向 refresh 契約。
- [`Dockerfile`](Dockerfile) 建置私人 `clsense-cube` image；production 由 root release workflow 推送並鎖定 digest。

不要把 database password、profile JWT secret 或真實 metadata response 放進 image layer、model
檔或測試 fixture。

## 測試

從本目錄執行：

```sh
node --test test/*.test.js
```

測試至少要涵蓋不同 profiles 的 JWT secret／database／catalog、偽造與過期 token、未知與跨
profile token、cache namespace、app/orchestrator ID、pre-aggregation schema，以及 refresh
allow-list。變更 topology 後另須執行 generator tests 及兩 profile sentinel-data smoke test。

部署、擴容門檻與故障處理見 [regional deployment runbook](../../deployment/README.md)。
