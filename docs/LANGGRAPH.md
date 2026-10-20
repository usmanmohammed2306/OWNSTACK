# LangGraph: evidence-guided repair, not autonomous release

October 19 source-binding clarification: r3 below is a historical October 18
benchmark, not a rerun on the later security revision. Its raw `repair.py` binding
differs from current source; the other three recorded bindings still match.
Because the workflow identity includes `repair.py`, do not substitute today's
hashes into that report or treat its saved workflow identity as current. The
later security report matches its 47 canonical source digests and six raw boundary
hashes, but that static agreement and its recorded regression suite do not rerun
the graph comparator. Original r1/r2/r3 results and failures remain preserved.

The denominator is 16 authored cases x 2 engines x 3 repetitions = 96 executions,
not 96 unique scenarios. Historical local p95 adds about 1.095 ms for the graph
(8.661 versus 7.566 ms plain). Recovery remains SQL-authoritative, not native
checkpoint persistence. These are local/synthetic results, not model-quality,
production or independent-adoption evidence. This documentation-only follow-up
runs no tests, services, database access or inference, changes no archive and
marks no independent rebuild slice or new personal mastery complete.

Implemented October 18, 2026. LangGraph 1.2.16 is the default execution engine for
the existing bounded PDF repair worker. This is real `StateGraph` execution, not a
diagram or an added chatbot. The existing Nebius generator remains behind the same
budget gate. No new inference was performed; the ten-call allowance is exhausted.

## Why this workflow

OwnStack needs safe variation, not more agents. A failed customer-specific patch
is a useful place for explicit routing, bounded feedback, parallel independent
tools and a human handoff. Access authorization stays in the host; Convergence
promotion stays human-owned. Neither benefits from an autonomous agent swarm.

The distinctive design is an **evidence graph over a durable SQL ledger**. Tools
produce witnesses tied to one candidate; the graph cannot vote a stale candidate
into validity. The final transaction independently rechecks the current snapshot.
This is an engineering hypothesis tested against a simpler controller, not a
claim of a novel research algorithm or universal framework superiority.

```text
Worker cycle -> committed SQL phase claim
  generating -> one bounded generator call -> scope review -> save candidate
  verifying  -> scope review
                   invalid -> manual handoff, no execution
                   valid   -> [artifact oracle || current-snapshot review]
                                            -> join -> fenced SQL result
  idle       -> saved outcome

Failed checks -> next SQL claim, at most two attempts -> manual handoff
Passing checks -> awaiting_review -> authenticated exact adoption
                                 -> separate human release decision
                                 -> no merge or deployment tool
```

Patterns used: conditional routing, a bounded evaluator/repair loop across SQL
phases, parallel tool checks, worker orchestration and durable human review.
The two reviewers are deterministic tools, not two LLMs. The artifact oracle is a
third independent authority. There is no majority vote, model-written command,
automatic promotion, open-ended planning or cross-tenant agent memory.

## The persistence decision matters

Each invocation executes one committed phase. SQL owns request revisions, claims,
attempt IDs, budget reservations, deadlines, candidates and human decisions.
LangGraph owns the execution topology inside that phase. No native checkpointer
or native `interrupt()` is used in the application. `awaiting_review` is the
existing authenticated database/API gate, not a suspended graph process.

This deliberately avoids introducing a second recovery authority or replaying
paid inference from a graph checkpoint. Death after a generation claim can consume
a reservation without delivering a candidate. We prefer that bounded loss to
silently repeating an uncertain external side effect. A saved candidate can
continue verification after restart without regenerating. Local cancellation does
not prove remote inference stopped.

The teaching control in `scripts/run_graph_lab.py` uses the real native interrupt
API with `InMemorySaver`: a synthetic dispatch before an interrupt runs twice on
resume, while a separate completed generation node runs once. This reproduces
[documented interrupt semantics](https://docs.langchain.com/oss/python/langgraph/interrupts),
not a new library vulnerability. Its in-memory checkpoint is not durable process
recovery. Native persistent human interrupts could be evaluated later, but must
not replace authenticated SQL approval or replay external calls blindly.

## Exact implementation

| File | Responsibility |
| --- | --- |
| `src/ownstack/repair_graph.py` | Typed state, reducers, conditional routing, actual parallel fan-out/join, cached compile |
| `src/ownstack/repair_execution.py` | Trusted operations shared by graph and sequential comparator |
| `src/ownstack/repair.py` | Existing authoritative claims, budget, late-answer fences, adoption; now defaults to graph |
| `src/ownstack/worker.py` | Existing fair interpretation/repair worker cycle |
| `web/src/BoundedRepair.tsx`, `repairView.ts` | Read-only saved phase/node/reviewer evidence, synthetic/live labels |
| `tests/test_repair_graph.py` | Eighteen graph-specific tests, including actual parallel overlap and tracing opt-out |
| `tests/test_graph_lab.py` | Sixteen paired authored cases and interrupt replay control |
| `scripts/run_graph_lab.py` | Reproducible offline baseline, fault and latency experiment |
| `scripts/prepare_graph_demo.py` | New private, zero-inference trusted-fixture demonstration |

Graph state contains IDs, booleans and bounded reviewer records. Prompt, source,
credentials and provider settings remain in a per-invocation execution context.
External LangSmith tracing is explicitly disabled, even if a developer enables it
in their environment; callbacks are empty. This is not a general egress firewall.
Transactional `repair.workflow_phase` events/outbox records retain sanitized
evidence. GET and refresh read saved records, never execute the graph.

Run configuration freezes the workflow schema, framework version and source hash.
Claim, result acceptance and adoption reject changed workflow identity. A source
upgrade can invalidate old pending work; manual inspection/re-verification is the
intentional migration path. No new database migration or workflow server is needed.

## Measured results, including the cost

Primary report: `evidence/langgraph-2026-10-18-r3/report.json`.
All scenarios use synthetic generator and verifier callbacks; no candidate code
executes inside this lab. Both engines share trusted safety operations, so this
compares orchestration, not independently implemented safety architectures.

- Sixteen authored scenarios x two engines x three repetitions: **96/96** scheduler-case
  executions pass, with **48/48** paired saved outcomes matching. Repetitions are
  not distinct failure scenarios. Cases include invalid output/scope, forged or
  partial verdict, verifier failure, stale revision/workflow, human takeover,
  late first candidate, AI-off, budget exhaustion and saved-state replay.
- Two real child-process exits, after committed claim and after committed candidate,
  preserve SQL state. Restart does not regenerate; the saved candidate reaches
  human review. These are deliberate `os._exit` faults, not power-loss or SIGKILL.
- Native interrupt control: synthetic dispatch count **2** versus **1** when
  separating the dispatch node from the interrupted review node. No model call.
- 135 timed worker invocations per engine on local SQLite: sequential median
  **5.161 ms**, p95 **7.566 ms**; graph median **6.130 ms**, p95 **8.661 ms**.
  Graph adds about **1.095 ms p95** here. Cold compile **0.751 ms** excludes imports.
  This is orchestration/SQL timing, not API latency, inference, throughput or an SLA.

No improvement in model quality or overall speed is established. The reason to
keep the graph is explicit topology, enforceable evidence joins, inspection and
testability. The sequential baseline remains available internally as `engine="plain"`.
Earlier r1/r2 reports are retained; timing overlapped tests/build and is not the
primary comparison. The r3 run had no intentionally overlapping local workload.

Full regression: **348 Python tests** pass in 26.02 seconds; JUnit in
`evidence/langgraph-2026-10-18-tests-r1.xml`. **26 frontend tests** and TypeScript/Vite
build pass. Optional 3D chunk remains 559.85 kB / 142.60 kB gzip and triggers Vite's
large-chunk warning. These checks are not security certification.

## Reproduce without credits

From the reference project directory, with Python 3.12:

```bash
.venv/bin/python -m pip install -c constraints.txt -e '.[dev]'
.venv/bin/python -m pip check
.venv/bin/pytest tests/test_repair_graph.py tests/test_graph_lab.py -q
.venv/bin/python scripts/run_graph_lab.py --repeats 3 --output .private/graph-my-run
```

Choose a new output directory every time. Expected: 35 focused tests pass, lab
report has `passed: true`, `executions: 96`, `live_calls: 0` and matching outcomes.
The lab clears provider credentials, uses cap zero and conservatively exhausted
fixture ledgers; it does not touch the main runtime database or reset an allowance.
The CI command runs one repetition and saves artifacts; remote CI is not yet proved.

Initial dependency resolution rejected `websockets==17.1` because the SDK requires
`>=14,<17`. The tested lock uses `16.1.1`, LangGraph `1.2.16` and pinned transitive
dependencies. `pip check` passes. Do not bypass this by ignoring dependencies.
An initial restricted-network package-index lookup failed; official PyPI access
and compatible installation subsequently succeeded.

### Inspect the honest demonstration

```bash
OWNSTACK_AI_MODE=off OWNSTACK_MAX_LIVE_CALLS=0 NEBIUS_API_KEY= NEBIUS_MODEL_ID= NEBIUS_PATCH_MODEL_ID= \
  .venv/bin/python scripts/prepare_graph_demo.py --private-output .private/graph-my-demo
```

The tool creates a new private local fixture, refuses overwrite, and prints its
database path. It accepts only the repository's exact known trusted fixture for
local execution. Seven real external-oracle cases pass, but this is **not** a model
repair or isolated execution of untrusted code. It leaves `awaiting_review`, the
original failed patch selected, no human decision, `not_deployed`, and counter ten.

To serve that private copy, use its printed absolute SQLite path:

```bash
OWNSTACK_AI_MODE=off OWNSTACK_MAX_LIVE_CALLS=0 OWNSTACK_REQUIRE_BACKGROUND=false \
OWNSTACK_PUBLIC_ORIGIN=http://127.0.0.1:8082 OWNSTACK_OFFLINE_PORT=8082 \
OWNSTACK_DATABASE_URL=sqlite:////ABSOLUTE/PATH/TO/.private/graph-my-demo/demo.db \
NEBIUS_API_KEY= NEBIUS_MODEL_ID= NEBIUS_PATCH_MODEL_ID= \
  .venv/bin/python scripts/serve_offline_build.py
```

Build React first with `pnpm --dir web build`. Sign in locally as `atlas-engineer`
with the documented synthetic password, choose Code review and the offline item,
then expand Saved workflow evidence. October 18 browser verification read the real
saved phase and both reviewer passes, refreshed without inference and left the
candidate unadopted. Screenshot: `evidence/langgraph-2026-10-18/saved-workflow.jpg`.
An initial Playwright label locator did not resolve; native accessibility controls
completed login and verification. This is agent-run QA, not an independent study.

## Learn it without copying a framework-shaped black box

Prediction first: if generation succeeds but the process exits after saving the
candidate, should the next worker invoke the model? Answer from the test, not the
diagram. Follow `claim_work -> save_candidate -> claim_work -> finish_checks` in
`repair.py` before studying graph syntax.

After the core Python/SQL slices in the ninety-day plan, reconstruct these three
narrow changes in the learner repository, only after their prerequisites exist:

1. Typed state and scope routing. Add the invalid-scope negative test before the
   graph. Suggested commit: `feat: route bounded repair through typed evidence graph`.
2. Parallel oracle/snapshot join. Reproduce `Barrier(2)` overlap and a stale witness
   rejection. Suggested commit: `test: fence parallel repair evidence to one candidate`.
3. Sequential comparator and one real process-exit experiment. Preserve raw results
   and explain overhead. Suggested commit: `experiment: compare repair schedulers offline`.

Only commit your actual changed files after tests pass. Do not mark days completed
from this reference, fabricate daily activity or claim its new code as independently
reconstructed. Add a learning journal entry naming which authority rejects a stale
candidate after the parallel snapshot check has already passed.

Official reading, in order:

1. [Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents):
   distinguish fixed evidence workflows from open-ended agency.
2. [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts): predict replay
   before running the teaching control.
3. [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence): distinguish
   graph checkpoints from OwnStack's domain ledger; study failure semantics before
   proposing a second durable store.
4. [Installed package/version](https://pypi.org/project/langgraph/): compare the lock with
   your actual environment rather than assuming latest examples match.

Next research gate: have an independent engineer review the authored cases, then
predeclare a broader workload and compare maintenance effort and failure recovery
against the simple controller. Any live model-quality comparison needs renewed
budget approval. No salary, hiring, prize, research novelty or layoff guarantee
follows from adding LangGraph.
