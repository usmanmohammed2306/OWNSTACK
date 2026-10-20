# Host access performance, October 10, 2026

Implemented and measured a narrower protected-read lookup, not a faster AI model
or a production load-capacity claim. Inference remained off throughout.

## Before and after

Previously `api.observe_read` materialized every variation for the tenant/project
before applying the pure authorization policy. A long history of revoked/expired
grants therefore became Python objects on every document read, including admin
reads that needed no grant at all.

Now `src/ownstack/host_access.py` selects only the exact tenant/project/viewer,
active state and valid time interval. Stable ID ordering and `LIMIT 1` retain the
same first valid grant attribution. Non-contractors and tenant mismatches skip
the grant query. The unchanged `policy.read_decision` still makes the decision;
the browser/model never does. Authorization is not cached. One read-time instant
is shared by SQL selection, policy and the observation, rather than sampled after
loading history. This denotes authorization time, not completion of delivery.
Already authorized in-flight reads can still race revoke, as documented before.

Migration `d74f109a32be` adds the index
`(tenant_id, project_id, viewer_id, state, expires_at)` without rewriting records
or the inference ledger. PostgreSQL EXPLAIN in the saved benchmark shows this
candidate index being used. Extra index storage/write cost is not measured.
Normal index creation can block writes; this local migration is not a proven
zero-downtime production migration.

## Reproducible measurement

Primary artifact: [final PostgreSQL run](evidence/performance-postgres-2026-10-10-r3.json).
PostgreSQL 16.15, Python 3.12.14, SQLAlchemy 2.1.3, Linux aarch64 Docker environment,
10 reported logical CPUs. This is a local synthetic, warm, single-client query
benchmark using a connection-local TEMP table, not the live application's data.

For each size: half the historical grants are revoked, half active-but-expired;
one final grant is valid. Five warmups per variant; 200 samples per variant per
phase; order alternates within pairs. Timing includes Session lifecycle, SQL,
ORM materialization and the pure policy. Both variants in the table below have
the same composite index, deliberately giving the old broad lookup its benefit.
p95 uses nearest rank. Every timed result must attribute `zz-active`.

| Historical grants + one valid grant | Broad lookup p50 / p95, ms | Narrow lookup p50 / p95, ms |
| --- | --- | --- |
| 0 + 1 | 0.144 / 0.191 | 0.179 / 0.219 |
| 100 + 1 | 0.412 / 0.486 | 0.190 / 0.247 |
| 10,000 + 1 | 44.374 / 59.065 | 1.062 / 1.893 |

At 10,000 historical rows: paired p95 reduction is **96.8%**, calculated as
`100 * (1 - 1.893166 / 59.065167)`. Returned ORM candidates fall from 10,001 to
one. The regression additionally checks 10,000 revoked rows plus two valid grants
and requires exactly one, correctly ordered candidate. Database work is not
guaranteed constant: many simultaneously valid/future grants can still require
index scans/filtering/sorting. Do not call this O(1) authorization.

Separate three-run `tracemalloc` measurements at that size show median peak
traced Python allocation of 14,983,084 versus 30,140 bytes, a 99.8% reduction.
That is not process RSS, database memory, container memory or total service usage.
Tracing is disabled during latency samples. With one grant the paired optimized
p95 is about 14% slower, roughly 0.027 ms extra; this optimization targets growing
history, not every workload.

The artifact also preserves the pre-index phase: broad p95 123.522 ms versus
post-index narrow p95 1.893 ms. Do not attribute that whole difference to the
index, and do not select its larger percentage as the headline. Phase ordering,
GC and local resource contention can influence measurements. There are no
confidence intervals, concurrent-load results, cold-cache measurements or
production guarantees.

Preserved exploratory runs: `performance-sqlite-2026-10-10.json`,
`performance-postgres-2026-10-10.json` (40 pairs per variant/size/phase), and
`performance-postgres-2026-10-10-r2.json` (200, overlapped a Docker rebuild).
The noisy r2 is not the résumé source. Final r3 ran after rebuild completion and
before the final test/smoke commands. Raw samples and source hashes are retained.

This excludes authentication, project/document queries, fail-closed observation
commit, response serialization, network/browser rendering, inference and patch
verification. It does not show requests per second, user capacity or full API
latency. TEMP-table behavior is not production shared-buffer/load behavior.

## Run it yourself

From the repository root, the zero-inference memory SQLite comparison is:

```bash
.venv/bin/python scripts/benchmark_host_access.py --rounds 200 --output /tmp/ownstack-perf-new.json
```

For the same local PostgreSQL path, use the already running full stack. This
command does not build an image, start the API command, or invoke inference:

```bash
docker compose -f compose.full.yaml run --rm --no-deps -T \
  -e OWNSTACK_AI_MODE=off -e OWNSTACK_MAX_LIVE_CALLS=0 \
  -e NEBIUS_API_KEY= -e NEBIUS_MODEL_ID= -e NEBIUS_PATCH_MODEL_ID= \
  -e PYTHONPATH=/bench/src \
  -e OWNSTACK_PERF_DATABASE_URL=postgresql+psycopg://ownstack:ownstack@db:5432/ownstack \
  -v "$PWD/src:/bench/src:ro" -v "$PWD/scripts:/bench/scripts:ro" \
  api python /bench/scripts/benchmark_host_access.py --rounds 200
```

Expected JSON: three sizes, 200 raw samples per variant per phase, the same
accepted variation ID verified internally, `ai_calls: 0`, and budget before/after
10 on the existing local database. No timing threshold is asserted, since machines
differ. TEMP fixture writes roll back on exit; no new application database or
inference ledger is created. Preserve previous output paths. Never point this
learning benchmark at a production database.

## Correctness and remaining work

127 Python tests, six frontend tests and web build pass. New tests include 54
role/boundary/fallback combinations, 500 seeded exhaustive-versus-narrow policy
comparisons, zero-query role/tenant paths, no-cache revoke/expiry and bounded
materialization with 10,000 historical rows. These are finite synthetic checks,
not exhaustive security verification. Python statement coverage is 1,340/1,670
(80.24%); the policy and candidate module each have 100% statement coverage, not
proven complete branch/state coverage. Verifier-service Python coverage is 38%,
so the aggregate must not disguise its gaps. See the final coverage JSON.

Existing PostgreSQL upgraded to the new revision, kept its 10/10 budget, and the
AI-off HTTP smoke passed grant, actual read, Nova denial, revoke, independent
sidecar checks and proof digests. No code was deployed publicly or released.

Next performance evidence: a separate isolated full-HTTP workload with realistic
grant distributions and concurrent clients, observation-write cost, p99/error
rates, index/write overhead and a fixed memory/CPU budget. Freeze the workload
before comparing. Do not claim customer throughput until independently measured.

## Twenty-minute explain-back exercise

Before opening `host_access.py`, predict which grant wins when the earliest ID is
expired and the next two are valid. Then predict what happens exactly at expiry,
after revoke, and for an Atlas admin with a Nova project ID. Rebuild the selector
in your learning repository and add those tests. Explain why skipping the grant
query for an admin must not skip the tenant check, why LIMIT 1 is safe only with
all current policy predicates, and why a five-minute permission cache would break
the contract. Run `pytest tests/test_host_access.py tests/test_observations.py`.
Suggested commit after your own work: `perf: bound grant lookup with policy parity tests`.

Read [SQLAlchemy result-fetch performance](https://docs.sqlalchemy.org/en/20/faq/performance.html)
and [PostgreSQL 16 multicolumn indexes](https://www.postgresql.org/docs/16/indexes-multicolumn.html).
The former explains ORM object-loading costs; the latter informs equality-first,
expiry-range index ordering. Next practice: inspect the saved EXPLAIN plan and
design a many-valid-grants counterexample before suggesting another index.
