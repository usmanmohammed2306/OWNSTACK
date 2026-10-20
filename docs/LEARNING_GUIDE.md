# Rebuild OwnStack yourself in 30 daily commits

Historical calendar retained. On October 14, Usman chose the new
[90-day feature plan](NINETY_DAY_PLAN.md) and separate `../ownstack-rebuild`
workspace. Use that active plan for today's lesson and reminder. Dates below
remain the original planned schedule, not completed personal work.

This repository is the completed **local reference implementation**, not a command to upload code you do not understand. Read a slice, close the reference, write your own version in a separate `ownstack-rebuild` repository, run its tests, then compare. Make one meaningful commit each day. Keep this reference intact so you can inspect it when stuck. Do not copy a whole module and call that learning.

Start date for this reconstruction: **October 7, 2026**. October 30 at 10 a.m. PDT is day 24, so days 25 to 30 are post-deadline hardening. This 30-day learning track cannot all precede submission. Prioritize a truthful, working journey by day 24, then continue the deeper product work. Recheck the [official rules](https://nebiusglobalaihackathon.devpost.com/rules) before final submission.

## How to work each day

October 13 is Day 7 on the original reconstruction calendar. Later reference
features are ready to inspect, not evidence that you completed their learning days.
Keep the dates honest if exams delay the rebuild. Do not backdate commits.

The engineering-depth additions have four small reconstruction checkpoints:

| Planned day | Rebuild from the reference | Your proof and suggested commit |
| --- | --- | --- |
| 15, Oct 21 | `repair.py`: exact current-attempt/deadline/configuration checks and durable `candidate_ready` | Predict a post-claim crash, reproduce a late discard; `feat: fence bounded repair attempts` |
| 18 to 20, Oct 24 to 26 | `pdf_oracle.py` before the driver/supervisor; read VERIFIER_LAB | Reject exit-zero/forged verdicts and bind exact output evidence; `test: judge exports outside candidate execution` |
| 26, Nov 1 | `change_benchmark.py` and the frozen split in SAFE_CHANGE_BENCHMARK | Reproduce 32/40, inspect eight errors without tuning the holdout; `eval: reproduce raw proposal baseline` |
| 27, Nov 2 | `compatibility.py`, both adapters and COMPATIBILITY_LAB | Reject an unsafe schema upgrade and explain the feature-flag tie; `test: fence variation compatibility across hosts` |

The reference contains a real PostgreSQL repair claim/crash lab as well as a
SQLite process experiment. Start with one transition, not the whole harness.
The lab's seventeen assertions are not seventeen unique failure scenarios.
Official next readings: [Python subprocess](https://docs.python.org/3.12/library/subprocess.html),
[PostgreSQL explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html),
and [Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints/).
After rebuilding these slices, study property-based state-machine testing and
distributed-system failure models, then design an independent customer comparison.
Practice first with local fixtures; none of these exercises needs new inference.

1. Predict the behavior before reading the implementation. Write one test you expect to fail.
2. Read only the day's reference files and one official resource. Explain the trust boundary in your own words.
3. Implement the slice in your rebuild repo. Run the exact check. Save a screenshot or command output when useful, but never call a fixture result live.
4. Commit only your own work with the suggested message. In `docs/JOURNAL.md`, record prediction, failure, fix, evidence, next question, and what remains unproven.

Use `git status --short`, `git diff --check`, relevant tests, then `git add <specific files>` and `git commit -m "..."`. Do not stage secrets, `.env`, databases, `.venv`, `node_modules`, build output, or another project's files. Push your rebuild repository after the daily commit if you want a public history. A commit is evidence of your process, not proof of product demand. The finished reference can be committed once as a clearly labeled reference snapshot in a separate repository or branch, but do not disguise its creation as 30 days of your work.

## Daily reconstruction map

Each line gives the date, your implementation target, the proof you should produce, and a suggested commit message. The daily work can be smaller than the reference if necessary, but never falsify the proof column.

| Day | Date | Your implementation and practice | Proof of work | Suggested commit |
| --- | --- | --- | --- | --- |
| 01 | Oct 7 | Audit this README, contract, API, worker, tests and dirty worktree. Draw the trust boundaries. Create your rebuild repo and journal. | Run reference tests and write an implemented/planned table. | `docs: record OwnStack baseline and risks` |
| 02 | Oct 8 | Trace Atlas contractor read before and after approval through `api.py`, `service.py`, `policy.py`. Predict whether Nova can read Atlas. | A one-page request-to-host trace plus one failing isolation test in your repo. | `test: capture host authorization boundary` |
| 03 | Oct 9 | Interview two B2B engineers about their last actual customer-specific change. Record current manual path, delay, forks and rollback. | Redacted interview notes; separate facts from guesses. | `docs: log customer change interviews` |
| 04 | Oct 10 | Write buyer/user hypothesis and a simple baseline. Define five acceptance tests before coding. | Hypothesis with falsification criteria and test names. | `docs: define buyer hypothesis and acceptance tests` |
| 05 | Oct 11 | Build FastAPI host routes with synthetic Atlas/Nova projects and documents. | `pytest` proves unauthenticated read denied. | `feat: add owned two-tenant host fixture` |
| 06 | Oct 12 | Implement identities and server-side role/tenant checks. Never trust a browser tenant parameter. | Direct API tests: Atlas cannot address Nova; contractor cannot access control records. | `feat: enforce tenant-scoped host reads` |
| 07 | Oct 13 | Encode Contract v1 as data and pure functions: one project, contractor, read-only, max seven days. | Table-driven valid and invalid contract cases. | `feat: define bounded capability contract` |
| 08 | Oct 14 | Call `can_read` on every protected document request. Include expiry and revoke state. | Tests for before grant, after grant, after expiry, after revoke. | `feat: enforce contract in host API` |
| 09 | Oct 15 | Build preview from the same policy function. Hash project revision and document state. | Mutate a document after preview; approval must conflict. | `feat: derive preview from host policy` |
| 10 | Oct 16 | Add SQLAlchemy records and Alembic migration for requests, attempts, proposals, evidence, events, idempotency and outbox. | Fresh empty PostgreSQL upgrade and seed. | `feat: persist change-control ledger` |
| 11 | Oct 17 | Implement exact proposal-hash approval with request revision, contract version and preview fencing. | Same key returns same response; changed body conflicts. | `feat: fence exact admin approval` |
| 12 | Oct 18 | Activate only Atlas variation. Add host revoke and clock-based expiry. | Nova unchanged; contractor loses access immediately after revoke. | `feat: activate reversible tenant variation` |
| 13 | Oct 19 | Add queued/running/accepted/failed attempts and a separate worker. GET must be read-only. | Refresh saved result without another AI call; duplicate interpret shares attempt. | `feat: add durable inference attempts` |
| 14 | Oct 20 | Read current Token Factory docs, confirm redeemed credits/prices/model ID, then make one server-side live Nemotron call only within the approved credit cap. | Redacted trace with model ID, status, tokens and latency, or an honest blocked note. | `feat: connect approved Nemotron runtime` |
| 15 | Oct 21 | Simulate invalid JSON, 429, outage, timeout and late result. Implement AI-off manual path. | Attempt 1 late answer is discarded after attempt 2 succeeds. | `test: exercise model failure recovery` |
| 16 | Oct 22 | Compare a current fast and strong Nemotron on fixed cases only if credits and usage permit. Record price and quality. | Raw redacted results, latency and estimated cost per accepted result, or pending note. | `eval: compare bounded model choices` |
| 17 | Oct 23 | Route PDF export to engineer, never contract configuration. Build work item and exact request display. | PDF request cannot reach access approval endpoint. | `feat: route unsupported feature to cockpit` |
| 18 | Oct 24 | Threat-model model-authored code. Implement one allowed file, size/anchor checks and fixed runner command. | Reject traversal, extra file, oversized patch and command injection examples. | `security: bound engineering patch surface` |
| 19 | Oct 25 | Generate or hand-author a real PDF-export patch against the owned fixture. Review the diff line by line. | Patched fixture produces a readable `%PDF` header. | `feat: produce reviewable PDF export patch` |
| 20 | Oct 26 | Run independent tests in the no-network verifier sidecar; bind results to patch hash. | Change one byte after check and show acceptance fails. | `feat: bind independent checks to patch` |
| 21 | Oct 27 | Add accept-for-manual-release, reject and take-over. Make release state explicit. | Accept fails without passing checks; no deployment occurs. | `feat: require human engineering decision` |
| 22 | Oct 28 | Polish accessible React journey and run negative-case, restart, and runner drills. Freeze claims. | Keyboard walkthrough and security/reliability log. | `test: rehearse judge journey and limits` |
| 23 | Oct 29 | If approved, prepare a judge-testable build with live model, cost cap, health and logs. Run fresh-clone and independent user rehearsal. Record a public video under three minutes. | Tester reaches hosted outcome and video URL, or blockers recorded honestly. | `ops: prepare reproducible judge build` |
| 24 | Oct 30 | Before 10 a.m. PDT, verify current form fields, public license/repo, setup, live NVIDIA/Nebius use, feedback and video. Submit truthful claims only. | Submission receipt and URL; technical limitations documented. | `docs: freeze truthful hackathon submission` |
| 25 | Oct 31 | Count repeated PDF/access needs and actual variation-attributed host checks without leaking tenant text; product owner supplies rationale and records a decision only. | Preview adds zero observations; contractor read adds one; Nova sees no Atlas evidence. | `feat: add observed usage and human convergence` |
| 26 | Nov 1 | Expand held-out cases and compare to a simpler manual/rules baseline. | Versioned case set, confusion matrix and error analysis. | `eval: deepen held-out boundary cases` |
| 27 | Nov 2 | Drill cross-tenant identifiers, replay, restart, late model and runner escape attempts. | Security/reliability log with pass, fail, limitation. | `test: deepen tenant and recovery drills` |
| 28 | Nov 3 | Interview a user watching the journey and compare it with their existing process. | Observed confusion and one measurable correction. | `research: record pilot usability findings` |
| 29 | Nov 4 | Harden auth, sandbox and worker recovery design from the evidence log. | New regression tests for highest-risk gap. | `security: harden highest-risk boundary` |
| 30 | Nov 5 | Write a technical case study and next pilot plan. Make a resume claim only from evidence. | Reproducible result, limitations, baseline comparison and next experiment. | `docs: publish technical case study` |

The user-visible daily checkpoint is always one tested behavior plus one sentence explaining why the server, database, model or human owns that decision. If a day slips, compress interface polish before cutting tenant isolation or honest evidence.

## Start today: exact Day 1 exercise

Read `src/ownstack/policy.py`, `src/ownstack/api.py`, `src/ownstack/service.py`, `src/ownstack/worker.py`, and `tests/test_api.py` in that order. Before reading `can_read`, predict: **If the Atlas contractor has an active Atlas grant, what happens when they request a Nova document ID, and which line of defense decides?** Write your prediction first. Then run:

```bash
.venv/bin/pytest --tb=short
pnpm --dir web build
rg -n 'can_read|host_preview|approve|current_attempt_id|late_discarded' src tests
```

Expected in the reference: the tests pass, the web build succeeds, and the search reveals preview's `can_read` and protected host reads both delegate to the same pure `read_decision`. A Nova ID must not resolve for an Atlas principal. If tests fail at import, confirm the virtual environment and `pip install -e '.[dev]'`. If readiness fails, apply `alembic upgrade head` to the same database URL used by the API. If the UI spins, check the separate worker and `/v1/requests/<id>/attempts`, not the browser console alone.

## October 9 reference additions to reconstruct

Later submission slice: rebuild `src/ownstack/demo.py` and
`scripts/submission_preflight.py` only after predicting what they should do when
evidence is missing, when a failed patch has a later passing correction, and when
all local files exist but public URLs do not. Run `pytest tests/test_demo.py
tests/test_submission.py tests/test_submission_bundle.py -q`. Explain why a
historical success, content digest, local video and owner checkbox are four
different kinds of evidence. Suggested narrow commit:
`test: separate local evidence from public submission gates`. No need to copy
the optional Swift media renderer to learn the core Python boundary.

These are agent-authored reference slices, not claims about your daily commits.
The ledger is the lab notebook; a preview is a prediction, an observation records
the authorization check, and a proof export is a photocopy whose digest catches
changes but cannot certify who wrote it.

| Slice | Exact reference | Prediction and practice | Check and suggested commit |
| --- | --- | --- | --- |
| Actual variation use | `policy.py:read_decision`, `api.py:observe_read`, `models.py:HostObservation`, migration `c62e84a910f3`, `tests/test_observations.py` | Predict the count after two previews, one admin read, one granted contractor read and one Nova ID. Then implement the pure decision and transaction yourself. | `.venv/bin/pytest tests/test_observations.py -q`; `feat: distinguish host observations from previews` |
| Restart configuration fence | `worker.py:run_one`, `tests/test_worker.py` | A fixture job is queued, then the worker restarts in live mode. Explain why it must not dispatch even if a key exists. Add a spy that fails if called. | `.venv/bin/pytest tests/test_worker.py -q`; `fix: fence queued inference against configuration changes` |
| Evidence export | `proof.py`, `scripts/verify_proof.py`, `tests/test_proof.py` | Export a request, change an approval hash, verify failure, then recompute the digest. Why is the recomputed digest not authenticity? | `.venv/bin/pytest tests/test_proof.py -q`; `feat: export tenant-scoped reproducible evidence` |

Read [PostgreSQL transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
for consistent snapshots and [Python hashlib](https://docs.python.org/3/library/hashlib.html)
for digests. Practice on synthetic data only. The reference's actual full-stack
restart fingerprint is in `docs/evidence/local-completion-2026-10-09.json`.
The ten-call allowance remains exhausted; learning and reconstruction do not
authorize further inference or an alternate database budget.

Your Day 1 journal entry should have a truth table with rows for local fixture, PostgreSQL, live Nebius, isolated patch check, hosted demo, and real users. Mark only observed facts as implemented. The local HTTP smoke test is `scripts/smoke_full_stack.py`; run it if Docker is available, but never label it live AI. Commit the audit and one negative test. Tomorrow, trace the Atlas/Nova route without looking at the UI.

## Official reading and deliberate practice

Read only what supports the day's slice. A useful progression:

- Python: [Python tutorial](https://docs.python.org/3/tutorial/), especially modules, exceptions, classes, and virtual environments. Practice by writing a pure `can_read` function and 10 table-driven cases.
- HTTP/API: [FastAPI tutorial](https://fastapi.tiangolo.com/tutorial/) and [testing](https://fastapi.tiangolo.com/tutorial/testing/). Practice with direct API calls that bypass React.
- SQL: [PostgreSQL transactions](https://www.postgresql.org/docs/current/tutorial-transactions.html), [SQLAlchemy Session transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html), and [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html). Practice by intentionally conflicting two approvals and inspecting the committed rows.
- Frontend: [React Learn](https://react.dev/learn), [TypeScript Handbook](https://www.typescriptlang.org/docs/handbook/intro.html), and [MDN accessibility](https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Accessibility). Practice by making failed attempts and saved evidence visible after refresh.
- AI integration: [Token Factory quickstart](https://docs.tokenfactory.nebius.com/quickstart) and [JSON output](https://docs.tokenfactory.nebius.com/ai-models-inference/json). Practice first with an injected fake and error cases, then one credit-backed call only after balance, price and model support are confirmed. Inspect current available Nemotron IDs instead of copying a guessed name.
- Security: [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/) and [Docker security](https://docs.docker.com/engine/security/). Practice by trying cross-tenant IDs and forbidden patch paths against your own local fixture.
- Testing/Git: [pytest documentation](https://docs.pytest.org/en/stable/) and [Pro Git](https://git-scm.com/book/en/v2). Practice by making one test fail before each feature and writing narrow commits.

## After the 30 days

October 10 advanced recovery reference: use [RELIABILITY_LAB](RELIABILITY_LAB.md)
for Days 15/27 after implementing durable attempts. Reconstruct duplicate accepted
delivery, then one real precommit process death, then prove a deliberately removed
late-result fence is caught. It includes three suggested narrow commits, exact
checks, official readings and limitations. Reference results do not become your
personal test results or historical commits. No additional inference is authorized.

Weeks 5 to 8: replace demo auth with a real identity provider, isolate the code runner on a separate service, add queue leases/watchdog and outbox dispatch, and run a fresh-clone/hosted failure drill. Read the latest official docs for each dependency before selecting it. Weeks 9 to 12: pilot with two independent SaaS teams, compare against their manual process, collect usage and rollback data, then decide whether the product should expand beyond temporary access. Do not add more models or cloud services merely to look advanced.

Strong portfolio proof is a real user outcome plus a measured baseline, verified Nebius runtime, tenant-negative tests, actual patch and independent checks, failure recovery, reproducible setup and honest limitations. A hackathon result is not evidence of hiring demand.
