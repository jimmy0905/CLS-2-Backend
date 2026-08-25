# CLSense Cube runtime

This directory is the version-controlled core of the governed survey semantic
layer. `docker-compose.analytics.yml` adds a private Cube API and refresh worker
for each of the 61 application profiles, plus four independently persisted Cube
Store clusters. It is an overlay: always use it together with the existing
`docker-compose.yml`.

For a complete canary startup walkthrough, see
[`deploy/WTCHK_CLS_STARTUP.md`](../deploy/WTCHK_CLS_STARTUP.md).

## Runtime boundaries

- Cube and Cube Store are pinned to `v1.7.26`. Operators must supply tested
  registry manifest digests; the repository intentionally contains no guessed
  digest.
- Cube API instances publish no host ports. They join `connex_network` to reach
  their matching backend/PostgreSQL database and only their assigned
  `analytics_store_shard_N` network to reach Cube Store. Each of the four shard
  networks is internal and isolated from the other unauthenticated Cube Store
  clusters.
- Every profile receives a unique app ID, orchestrator ID, pre-aggregation
  schema, read-only PostgreSQL principal, API signing secret, metadata signing
  secret, and feature flag.
- The core models maintain four explicit grains. No joins connect topic,
  department, and keyword assignment cubes, and the query rewrite rejects a
  request that names more than one assignment cube.

The persisted allocation is `deploy/analytics/profiles.json`: sorted profile
names are assigned round-robin to four shards. `wtchk_cls` and `wtchk_ecls` are
rollout wave 0; remaining profiles are split into sorted waves of at most ten.
Regenerate and validate after a profile is added or removed:

```bash
python scripts/generate_analytics_compose.py
python scripts/validate_analytics_infra.py
```

The empty `deploy/analytics/shard-overrides.json` is the reviewed escape hatch
for an operational rebalance. Add only the overloaded profiles and their new
shard numbers, regenerate, then rebuild the affected profiles' pre-aggregations.
Rebalance after either CPU or memory remains above 70% for the agreed sustained
monitoring window, or Cube Store partition scans exceed the 100 ms target; a
single transient spike is not a rebalance signal. Treat this as a planned cache
move because open-source Cube Store does not replicate shard state.

## Configure and start a profile

Resolve the multi-platform image manifest digests from the trusted registry,
deploy them to a non-production environment, run the semantic integration and
load suites, then record those tested `sha256:...` values. A registry lookup is
not by itself a test. Copy `deploy/analytics.env.example` into the ignored
profile environment file and add the matching namespaced block.

The analytics database role must not own the database or schema. Grant only
`CONNECT` on its BU database, `USAGE` on the reporting schema, and `SELECT` on
the reporting views/helper functions required by the model. Verify its grants
with `SET ROLE <role>` before enabling the profile. The static validator checks
that a dedicated username is configured, but cannot prove PostgreSQL grants;
this database-side verification is a mandatory deployment gate. Both signing
secrets must contain at least 32 random bytes, differ by purpose, and be unique
across every profile validated in the deployment wave.

```bash
python scripts/validate_analytics_infra.py \
  --env-file deploy/profile/wtchk_cls.env \
  --profile wtchk_cls

docker compose \
  -f docker-compose.yml \
  -f docker-compose.analytics.yml \
  --profile wtchk_cls \
  --env-file .env \
  --env-file deploy/profile/wtchk_cls.env \
  up -d
```

`WTCHK_CLS_ANALYTICS_ENABLED=false` keeps viewer/admin analytics routes disabled
while Cube runs shadow queries. Set it to `true` only after the comparison gate.
Rollback sets the flag back to `false`; the ordinary health, upload, survey, and
dashboard paths have no dependency on Cube health.

## Dynamic catalog contract

At compile time Cube calls the profile backend's
`GET /internal/analytics/catalog` endpoint with:

- `X-Analytics-Profile`
- `X-Analytics-Timestamp` (Unix seconds)
- `X-Analytics-Signature` (`HMAC-SHA256(secret, "timestamp:profile")`)

The response follows `contracts/catalog.schema.json`. The compiler accepts
structured field and metric definitions only: it validates identifiers, types,
operations, field references, filter values, visibility, and catalog monotonicity
before generating YAML. It never evaluates JavaScript or accepts arbitrary SQL
from the metadata endpoint. The endpoint and secret are profile-local. A
canonical content hash also rejects changed metadata at an unchanged catalog
version, preventing API and refresh processes from compiling divergent models.

Core members use a version-controlled per-view type and SQL-alias registry.
This preserves assignment aliases such as `department -> department_name` and
`sentiment -> assignment_sentiment`; signed metadata cannot invent a physical
core column. Chart rollups are validated against the same core registry and the
published local catalog. Confidence and weighted rollups automatically include
the supporting confidence/data-quality measures FastAPI requests.

Confidence-interval metrics expose supporting measures using the stable suffix
contract below. FastAPI requests these together with the estimate and uses SciPy
to calculate bounds:

- unweighted mean: `__sample_count`, `__value_sum`,
  `__value_square_sum`, `__variance_sample`;
- unweighted proportion: `__success_count`, `__sample_count`;
- weighted metrics: `__pair_count`, `__weight_sum`,
  `__weight_sum_squares`, `__weighted_value_sum`,
  `__weighted_value_square_sum`, plus `__success_weight_sum` for rates;
- every weighted metric: `__invalid_weight_count` and
  `__invalid_value_count`.

Negative, NaN, and infinite weights (and non-finite numeric values in weighted
moments) make the estimate null and increment the data-quality measures. FastAPI
must return a visible data-quality failure whenever either count is non-zero.
Zero weights remain valid; rows with a null value or null weight are excluded.

Median and percentile measures use stable PostgreSQL `PERCENTILE_CONT`
expressions and remain unweighted/non-additive. They are intentionally absent
from the shared rollups; a matching chart-specific non-additive rollup must use
the chart's exact dimensions, otherwise Cube falls back to PostgreSQL.

See `contracts/preaggregation-refresh.md` for the affected-month refresh call.

## Azure Blob limitation in Cube Core

The approved design requests a separate Azure Blob prefix per Cube Store shard.
The overlay reserves and validates four distinct prefixes, but the open-source
Cube Store image does **not** support Azure Blob persistent storage in Cube's
current production documentation; that capability is Enterprise-only. The OSS
overlay therefore persists each shard in an isolated Docker named volume.

Do not treat `ANALYTICS_AZURE_BLOB_PREFIX` as an active Cube Store setting: it is
an explicit handoff to an approved offline backup process or an Enterprise image.
Exact Azure-backed pre-aggregation persistence requires either Cube Enterprise,
a supported OSS remote store such as S3/GCS, or a separately reviewed quiesced
backup/restore process. Live file copying is not a safe substitute for Cube
Store's consistency contract.

Open-source Cube Store also has no node replication. Each shard limits failure
scope to roughly one quarter of profiles and can be rebuilt from PostgreSQL, but
the topology is operational recovery, not transparent HA.
