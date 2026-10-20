# Bounded engineering repair

October 18 security follow-up: [SECURITY_HARDENING](SECURITY_HARDENING.md) adds
mandatory kernel candidate restrictions and current profile/provenance fencing.
Changing that source intentionally makes older repair verdicts stale; rerun checks
or take over, never relabel a historical pass. Exact trusted local fixture checks
are explicitly not sandboxed and cannot satisfy production candidate acceptance.
The real HTTP sidecar path passes with AI off; no live repair quality is added.

October 18 extension: the default worker now executes the real LangGraph evidence
workflow documented in [LANGGRAPH](LANGGRAPH.md). Existing SQL attempt/claim/budget
semantics below remain authoritative. New saved workflow identity and tool-review
events support inspection, source fencing and a sequential baseline. No native
graph checkpoint, implicit node retry, new inference or autonomous release.

October 12-13, 2026 implementation and experiments. This is a server-side reference workflow, not
autonomous deployment or evidence of successful model repair. Current live call
allowance is exhausted at ten. The main runtime remains AI-off. None of this work
authorizes another inference call, a fresh allowance, or a paid resource.

## Implemented boundary

An engineer can start a run against one exact saved failed patch, with one or two
attempts. The repair run keeps the original patch and check history. It does not
replace the selected engineering patch while the model or verifier is running.

`queued -> generating -> candidate_ready -> verifying -> passed | failed`

A failed candidate may queue the second attempt, with bounded failure feedback.
After two failures the run stops at `manual_handoff`. A passing candidate stops at
`awaiting_review`. The engineer must explicitly **adopt** that exact hash before
the existing separate accept-for-manual-release decision becomes available.
Adoption preserves the failed original and copies the exact passing evidence.
Nothing accepts, merges, or deploys automatically.

The model can propose only one replacement for `sample_app/report.py`. It cannot
choose file paths, verifier commands, tests, permissions, or deployment actions.
The external PDF oracle judges returned bytes outside the candidate process. A
successful exit or model-written success message is insufficient. Seven exact
oracle case IDs, the oracle version, patch hash, source/check/oracle/driver hashes,
and build revision must match. The oracle supports a narrow owned PDF format, not
arbitrary PDF libraries or general repositories.

## Reliability details

| Boundary | Implementation |
| --- | --- |
| Duplicate POST and refresh | Tenant-scoped idempotency keys point to a durable run. Repeated requests return its current saved state, never dispatch work. GET only reads. |
| Worker restart | Generation and verification are separate committed phases. `candidate_ready` resumes verification without another model call. |
| Death after generation claim | The committed reservation and claim remain. The worker never re-dispatches that claim. After its local deadline, reaping can create the second attempt. |
| Late attempt 1 | Only the current attempt in the exact expected state and before its deadline can save output. A late payload is discarded, not stored as a candidate. |
| Human takeover | The repair take-over endpoint clears its operation and restores manual correction. The existing work-item human decision also invalidates the run. |
| Version changes | Request revision/text, original item hash, operation ID, source, checks, oracle, driver, and build revision fence acceptance. |
| Configuration changes | Mode/model/timeout, generator source hash, prompt/parser code and decoding settings are frozen per run. A fixture job cannot become a live call after restart. AI-off prevents generation; already saved candidates can still be verified. |
| Budget | Every live-mode generation claim calls the existing `reserve_live_call` inside the transaction before dispatch. Timeouts/failures keep the reservation. |
| Feedback | Error text and failed case reasons are bounded, labeled untrusted, and included as data. No model-authored shell commands are accepted. |
| Queue fairness | Each worker cycle services interpretation and repair once. A continuously nonempty interpretation queue cannot short-circuit repair processing. |

Local cancellation/deadline **does not establish that remote inference stopped**.
The real implementation still needs stronger arbitrary-code isolation and
production operational validation. A finite check pass is not a security claim.

## Exact files

- `src/ownstack/repair_models.py`: run and attempt records.
- `src/ownstack/repair.py`: transitions, claims, fences, budget and adoption.
- `src/ownstack/repair_api.py`: authenticated tenant-scoped control routes.
- `src/ownstack/patch_agent.py`: bounded previous-candidate and failure input.
- `src/ownstack/worker.py`: independent server-side queue processing.
- `migrations/versions/e8c1a7b4d209_bounded_repair.py`: additive schema migration;
  predecessor `d74f109a32be`, with no inference-budget update.
- `tests/test_repair.py`: synthetic model/verifier tests, explicitly not live proof.
- `scripts/run_repair_lab.py`: real process exit/restart and Docker-check lab.
- `scripts/run_repair_postgres_lab.py`: barrier-aligned PostgreSQL claims, actual
  committed-worker SIGKILL, restarted reaper and stale-result fencing.

The Compose worker needs the same verifier queue environment and jobs volume as
the API. Apply the migration before starting the new worker. Do not change the
main runtime from AI-off just to demonstrate these routes.

## API contract

Existing authentication, Origin/CSRF checks, roles and tenant scoping apply.
Administrative read access does not permit repair/adoption actions.

| Method | Route | Required input |
| --- | --- | --- |
| POST | `/v1/engineering/{item_id}/repairs` | Engineer; `Idempotency-Key`; JSON `patch_hash` and `max_attempts` of 1 or 2 |
| GET | `/v1/engineering/{item_id}/repairs` | Tenant engineer/admin; all saved runs for the item |
| GET | `/v1/repairs/{run_id}` | Tenant engineer/admin; current state, candidates, checks, usage and errors |
| POST | `/v1/repairs/{run_id}/take-over` | Engineer; no model call; repeat is safe |
| POST | `/v1/repairs/{run_id}/adopt` | Engineer; JSON `patch_hash` of the exact passing current candidate |

Example request body, with the real current failed patch hash substituted:

```json
{"patch_hash": "<64-character failed patch hash>", "max_attempts": 2}
```

`AI_OFF` means saved evidence and manual patching remain available. A cap failure
is terminal manual handoff, not a retry that resets the allowance. A verification
infrastructure failure also stops rather than spending more on an unavailable
oracle. A syntax or behavioral failure from the functioning oracle can be repaired.

## Reproduce the offline experiment

From the repository root, with Docker Desktop and an already available local
`python:3.12-slim` image. No image download is performed by the checker.

```bash
.venv/bin/pytest tests/test_repair.py --tb=short
.venv/bin/python scripts/run_repair_lab.py \
  --output docs/evidence/repair-lab-your-new-run
```

The output directory must not already exist. Every run retains `report.json` and
an ignored local SQLite fixture `synthetic-state.db`. The script forces empty
credentials, fixture mode and cap zero, seeds the explicitly exhausted count ten,
and never connects to the main database. Each worker phase is a new process. One
child exits immediately after committing its generation claim. Docker executes
only the bounded owned candidate with no network; the external oracle checks it.

Final focused regression run: **32/32 repair tests pass** in 5.11 seconds, with
one existing Starlette/httpx dependency warning. These include injected synthetic
provider/oracle fixtures and do not count as live model evaluations.

Observed final r3: **17/17 assertions passed**, five child processes exited with the
expected codes, the first synthetic candidate failed all seven PDF checks, and
the second known reference candidate passed all seven. The original selected
patch stayed unchanged and the run stopped for human review. Duplicate start,
candidate persistence, timeout reaping, late-result discard, takeover, zero
remaining active attempts and unchanged exhausted fixture budget were checked.
Artifact: `evidence/repair-lab-2026-10-13-r3/report.json`. Earlier r1/r2 artifacts
remain as historical source revisions, not substitutes for this final run.

This is a constructed repair-control experiment, not evidence that Nemotron can
repair the patch, a model-quality benchmark, PostgreSQL concurrency proof, or
production fault tolerance. The proposal generator deliberately returns a bad
fixture and then the known correct implementation. Live repair evaluation stays
blocked on renewed, explicitly bounded inference approval.

Intermediate development results are not hidden: the first expanded focused run
failed two tests because injected oracle IDs no longer matched the strengthened
exact seven-ID contract. The fixtures were corrected, not the production guard.
A later test addition had an unmatched parenthesis and failed collection, then
was corrected. An independent code review identified queue starvation from a
short-circuiting worker expression; `run_cycle` and a regression corrected it.
When the oracle added mandatory PDF digests, three synthetic-test expectations
failed until their deliberately synthetic evidence fields were updated. The
strict production guard was retained. Another review identified generator/prompt
version drift across repair attempts; a source hash and decoding configuration
now fence generation. Specific timeout/rate-limit/truncation codes replace a
single generic model failure while excluding raw provider error bodies.

## Real PostgreSQL concurrency and process death

`scripts/run_repair_postgres_lab.py` requires an explicitly supplied local
`OWNSTACK_LAB_DATABASE_URL` and a new output directory. It accepts only the
existing local PostgreSQL host, requires the currently exhausted counter ten,
and creates a generated `ownstack_lab_<uuid>` schema. It copies that counter,
sets empty keys/cap zero, and never changes the public allowance. The schema is
retained for inspection. Child socket guards permit only that database address;
this is a test-harness guard, not a security sandbox.

The October 13 r1 run passed **17/17 assertions**:

- Two separate processes waited at a barrier, then claimed the same queued run.
  Exactly one obtained the generation claim.
- The winning process was actually killed with SIGKILL after its transaction
  committed, before any proposal call. Its claim survived.
- After advancing only the lab deadline, a new reaper process created attempt 2.
- A separate late-result process could not save attempt 1's payload.
- A restarted process claimed attempt 2. Explicit takeover ended the run, leaving
  zero active attempts. All five child processes were reaped.
- Main table counts and the main exhausted counter were identical before/after.
  The isolated fixture counter also remained ten. Provider calls were zero.

Artifact: `evidence/repair-postgres-2026-10-13-r1/report.json`. The exact schema
name, child exit codes/traces, main snapshots, source hashes and final run state
are retained there. This establishes a finite PostgreSQL claim/death/reaper
scenario, not full HTTP concurrency, machine loss, external failover or an SLA.
No model or candidate was executed in this particular experiment.

On the existing unexposed Compose database, run this in a one-off API container
using the pattern in `.github/workflows/ci.yml`: explicit AI-off, cap zero and
empty model keys; read-only mounts for `src`, `ops`, `scripts`, `sample_app` and
`checks`; `PYTHONPATH=/lab/src:/lab`; `OWNSTACK_SOURCE_ROOT=/lab`; the existing
local DB URL; a writable results-only mount; and this command:

```bash
python /lab/scripts/run_repair_postgres_lab.py --output /results/new-repair-run
```

Do not publish a database port or use production credentials to reproduce it.

## Learn it by reconstructing the boundary

1. Predict: a worker dies after reserving a call but before sending it. Should
   the same attempt be sent again? Explain the at-most-once dispatch tradeoff.
2. Rebuild just `save_candidate` and its four fences without reading the reference.
   Write tests for timeout, an older attempt, changed request revision, and takeover.
3. Add the intermediate `candidate_ready` record. Kill a fixture worker between
   phases. Prove a new worker verifies the saved candidate without generation.
4. Implement a two-attempt limit. Preserve both candidates and failed checks.
   Explain why accepting the passing result is still not a human release decision.
5. Rebuild the idempotent start endpoint, then compare SQLite and PostgreSQL row
   locking. Do not claim a SQLite unit test proves PostgreSQL concurrency.

Suggested narrow commits, only after doing the work yourself: durable repair
records; exact-result fences; bounded retry with preserved evidence; explicit
human adoption; fault experiment and limitations. Do not backdate or manufacture
a daily contribution history from this agent-authored reference.

Official reading: [SQLAlchemy transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html),
[PostgreSQL explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html),
[Python subprocess management](https://docs.python.org/3/library/subprocess.html),
and [FastAPI dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/).
