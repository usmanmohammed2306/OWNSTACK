# Real-process recovery lab

October 10, 2026. This is a completed local fault-injection implementation, not a
live provider outage, production SLA or comprehensive security test. The provider
is an explicitly synthetic stub. The API, HTTP calls, PostgreSQL transactions,
worker processes, process deaths, persisted records and host reads are real.

## Observed result

Primary artifact: [r3 report](evidence/reliability-2026-10-10-r3/report.json).

| Measurement | Observed denominator | Meaning |
| --- | --- | --- |
| Passing scenario executions | 36/36, 12 scenarios repeated three times | The declared local matrix passed, not 36 distinct failure types |
| Deliberate SIGKILLs | 12: nine workers and three APIs | Each killed process returned -9; normal final cleanup is excluded |
| Defective baselines detected | 5/5, one execution each | Oracles caught five specified in-memory mutations, not arbitrary bugs |
| Unresolved control attempts | 0 across 39 control requests | No queued/running attempts remained in the positive-control histories |
| Child processes reaped | 85/85 | Includes ordinary workers, reapers, API restarts and mutant processes |
| Real HTTP requests | 256 | Mixed endpoints and concurrent/sequential phases, not a load test |
| Recovery observations | Nine, median 1,200.14 ms, max 1,390.55 ms | Kill to verified saved outcome with short injected deadlines and explicit retry |
| Live inference / budget | Zero new calls; main and lab counters stay 10 | Existing exhausted allowance was copied, never renewed |

The recovery p95 is also 1,390.55 ms under nearest-rank estimation, equal to the
maximum with nine samples. Do not advertise it as production recovery time. The
timer includes reaper/worker startup, explicit HTTP retry and outcome verification;
it does not include a normal twenty-second remote inference timeout. HTTP raw
timings mix login, errors, reads and writes and must not become an overall API p95.

r1 was a one-repeat implementation check. r2 repeated the original matrix three
times. Those runs used already-saved create-key replays. r3 intentionally tightened
that case to eight barrier-aligned cold submissions, then eight queued repeats
and eight running repeats. All three reports and child traces are retained. Do
not pool their results as independent benchmark trials or hide the workload change.

## What runs and what fails

| Scenario | Injection / independent observation | Required outcome |
| --- | --- | --- |
| Duplicate fanout | Eight cold same-key HTTP creates, eight queued interpretations, four competing worker processes, eight repeats while the provider is blocked | One request, one attempt, one synthetic dispatch, saved progress, one proposal |
| Kill after claim | SIGKILL while provider is blocked, after claim transaction commits | No proposal; deadline reaper plus explicit retry produces exactly one saved result |
| Kill before commit | SIGKILL after acceptance writes but before transaction commit | PostgreSQL rolls back uncommitted proposal/event/outbox; retry succeeds |
| Kill after commit | SIGKILL after acceptance commits; kill/restart the API too | GET returns the same accepted pointer; repeated interpretation returns the same attempt |
| Late attempt | Hold attempt 1, shorten its deadline, reap, accept attempt 2, release attempt 1 | Only attempt 2's proposal survives as accepted |
| Cancel then late | Hold attempt 1, cancel locally, accept attempt 2, release attempt 1 | Same fence holds; remote cancellation remains explicitly unverified |
| Invalid output | Synthetic ValueError at the worker's provider seam | Durable failed state; engineer creates a proposal without AI |
| Provider 429 | Constructed HTTPStatusError, never sent over the network | Durable model error; inspectable failed attempt and manual recovery |
| Provider timeout | Synthetic ReadTimeout | Durable timeout error; manual recovery without a fabricated answer |
| Stale approval | Change the lab document after preview | HTTP 409, zero variation effects |
| Grant/revoke/expiry | Eight aligned approval calls, actual contractor/Nova reads, revoke, separate four-second grant | One approval/effect; Nova 404; contractor 403 after revoke and natural expiry |
| Accepted redelivery | Deliver another result for an already accepted attempt | Original accepted attempt and proposal remain unchanged |

For positive controls, each event must have an outbox row and no attempt may
remain queued/running. The report includes exact request IDs and state snapshots.
It does not test external outbox delivery, full event replay or all isolation levels.

## A real defect found and fixed

Previously `accept_result` treated an accepted attempt's duplicate delivery as
stale work and relabeled the attempt `superseded`. Its proposal remained saved,
leaving inconsistent terminal history. The new accepted-state guard records a
discarded duplicate without rewriting the original acceptance. It does not accept
a second answer. See `src/ownstack/service.py:accept_result` and
`tests/test_api.py:test_redelivered_accepted_result_preserves_terminal_history`.

The lab removes this guard in one child process and observes the original defect:
attempt becomes superseded. Four other explicit mutations remove the late-result
fence, outbox insert, fresh-preview comparison or tenant predicate. Observed
violations respectively include two proposals/overwritten pointer, two events
without outbox rows, an incorrectly approved stale variation and Nova receiving
an Atlas control record. Only synthetic lab records are exposed. Every mutation
must match exactly one AST node or refuse to run. Source hashes are checked before
and after; repository source is never edited by the lab. This is a five-defect
mutation baseline, not a general mutation-coverage percentage.

## Files and boundaries

- `scripts/run_reliability_lab.py`: explicit local database, bounded repeats,
  new output path, credential clearing and failure exit status.
- `ops/reliability/harness.py`: schema fixture, HTTP clients, aligned fanout,
  processes, checkpoint orchestration, persisted-state oracles and report.
- `ops/reliability/child.py`: real API/worker/reaper entrypoints with synthetic
  provider, checkpoint gates and instrumented transaction boundaries.
- `ops/reliability/mutations.py`: strict in-memory AST defects, never source edits.
- `tests/test_reliability_lab.py`: 15 safety/mutation/cleanup tests, including
  actual child cleanup on a failed run and sanitized initialization failure.
- `.github/workflows/ci.yml`: one-repeat lab and retained traces in the full-stack
  job. Configured locally; public GitHub execution remains unverified.

The API uses the local teaching bearer path, not the production cookie/CSRF path.
Cookie behavior remains separately tested in the existing suite and full-stack
smoke. Worker instrumentation calls the real `run_one` and real acceptance logic;
it substitutes only provider behavior and pauses at specific boundaries.

## Reproduce without inference

Use the existing local full-stack database, already migrated and seeded. Do not
start an alternate inference budget. This command builds no paid resource and
mounts only public source components, not `.env`. From the repository root:

```bash
docker compose -f compose.full.yaml run --rm --no-deps -T \
  -e OWNSTACK_AI_MODE=off -e OWNSTACK_MAX_LIVE_CALLS=0 \
  -e NEBIUS_API_KEY= -e NEBIUS_MODEL_ID= -e NEBIUS_PATCH_MODEL_ID= \
  -e PYTHONPATH=/lab/src:/lab \
  -e OWNSTACK_LAB_DATABASE_URL=postgresql+psycopg://ownstack:ownstack@db:5432/ownstack \
  -v "$PWD/src:/lab/src:ro" \
  -v "$PWD/ops:/lab/ops:ro" \
  -v "$PWD/scripts:/lab/scripts:ro" \
  -v "$PWD/docs/evidence:/results" \
  api python /lab/scripts/run_reliability_lab.py \
    --repeats 3 --output /results/reliability-your-new-run
```

Choose a never-used output directory. If bind-volume permissions fail on Linux,
add `--user "$(id -u):$(id -g)"` before the environment options. If Docker is not
running, start it first. Do not wipe volumes to make the lab pass. If your existing
database is exposed at loopback, the host alternative is:

```bash
OWNSTACK_LAB_DATABASE_URL='postgresql+psycopg://ownstack:ownstack@127.0.0.1:5432/ownstack' \
  .venv/bin/python scripts/run_reliability_lab.py \
  --repeats 3 --output docs/evidence/reliability-your-new-run
```

The full-stack Compose database is not published at host port 5432; use the first
command for that stack. Expected final summary: status passed, checks_passed 36,
mutants_detected 5, live_calls 0, all_children_reaped true, exit status zero.

## Safety, failures and evidence

The lab creates one `ownstack_lab_<uuid>` schema inside the existing PostgreSQL
database. Its search path contains that schema and `pg_catalog`, not `public`.
The fixture copies the current reservation count and forces live cap zero. Child
credentials/model IDs are empty, the environment is allowlisted, and children
start outside the workspace so they cannot discover its `.env`. A Python socket
guard blocks non-database outbound connections, but native libraries can bypass
Python hooks. This is a harness guard, not OS network isolation or a sandbox.
Schema namespacing also is not database-role isolation: the trusted test process
uses the local database role. Never run this against production or real tenants.

Main request/attempt/proposal/approval/variation/event/outbox counts and the
durable budget are read before/after and must match.
This is not a byte-for-byte checksum of every main row. Concurrent legitimate
runtime activity may fail that comparison; preserve the report and investigate.
Lab schemas and traces remain for inspection, including defective mutant history.
No DROP or cleanup of durable evidence is performed. Repeated runs consume local
disk space, not inference credits. Do not present mutant effects as product state.

Each child directory retains `process.log`, `trace.jsonl` and any release marker.
On checkpoint timeout, inspect that child's log and ordered trace. On assertion
failure, retain `report.json` and its failure status. Initialization failures save
only the error type, not connection exception text that may contain credentials.
Finalization attempts to reap every child even on failure and records cleanup or
database-verification errors. Parent SIGKILL, machine loss and escaped hostile
descendants are outside this cleanup claim. This lab never runs hostile code.

## Learn and rebuild it

Prediction first: a worker wrote the proposal but died before commit. Will a new
API process see that proposal? What if the worker died immediately after commit?
Explain how these differ from losing a browser response.

1. Rebuild `accepted` redelivery handling and one regression in your own repo.
   Run `.venv/bin/pytest tests/test_api.py -k redelivered -q` in the reference for
   comparison. Suggested personal commit: `fix: preserve accepted attempt on redelivery`.
2. Implement only the before-commit crash case using `Popen`, a checkpoint and
   PostgreSQL. Save the failed state before retry, then assert a single saved
   proposal after explicit recovery. Suggested commit:
   `test: prove rollback after worker process death`.
3. Intentionally bypass your late-result fence in an isolated test copy. Your
   oracle must fail. Restore the fence and show it passes. Suggested commit:
   `test: detect broken stale-result fencing`.

Use these as advanced exercises for Days 15 and 27 of LEARNING_GUIDE, not invented
past commits. The reference is agent-authored assistance; your reconstruction and
explain-back are separate evidence. Run the local unit checks with
`.venv/bin/pytest tests/test_reliability_lab.py -q`; expected 15 pass.

Read [Python subprocess](https://docs.python.org/3.12/library/subprocess.html) for
Popen, explicit environments, kill and wait;
[PostgreSQL transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html)
for transaction visibility; and
[CREATE SCHEMA](https://www.postgresql.org/docs/16/sql-createschema.html) for
namespace setup. Practice one crash boundary before extending the matrix.
Future work: model-independent held-out evaluation, real outbox delivery,
backup/restore, full-service load and stronger hostile-code isolation. None follows
automatically from these passing checks.
