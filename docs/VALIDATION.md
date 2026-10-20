# Validation ledger

Latest October 18 security pass: 416 Python tests, no skips, 27.269 seconds in
`evidence/security-2026-10-18-tests-r6.xml`; 26 frontend tests and build pass.
Mandatory Landlock/seccomp on actual aarch64/ABI 8: 15/15 caught-denial probes on
each backend, plus 13/13 Docker and 15/15 sidecar adversarial expectations. Every
caught-denial candidate also passes the seven-case PDF oracle. Three base-container
capabilities are calibrated; other denials may overlap Docker's existing policy.
Six real restricted-role DB negatives plus rollback-only ownership/membership
controls pass. Six actual Nginx trusted/untrusted peer/path controls pass.
No-server production startup rejects
stored seed passwords; rollback-only positive startup restores exact identity flags.
Full restricted-role queue/HTTP demo: 33 checks/80 requests; after four-service
restart: 12 checks/18 requests, three identical histories. Browser shows current
checks, historical failure and Not deployed. Original schema/counts/ledger remain
unchanged; both ledgers ten. Permission-blocked Docker and loopback runs remain
retained, not counted as policy passes. SECURITY_HARDENING and its dated report
identify final hashes and limitations: no independent escape audit, x86 execution,
live TLS, production identity, arbitrary repository, public deployment or inference.

Later October 18: final r2 has 373 Python tests pass in 30.67 seconds; 26 frontend tests,
TypeScript/Vite and six local image builds pass. Full restored-stack journey:
33 named checks/80 HTTP requests, exact-hash/role denials, duplicates, Atlas/Nova,
revocation, actual expiry, rejected then corrected manual PDF with seven sidecar
oracle cases, exact artifact and record-only Convergence. Four-service restart
preserves three histories: 12 checks/18 requests. PostgreSQL recovery matches
24 tables/743 rows and ledger ten; target-only write absent from source. First
public-schema restore conflict is retained and independently reproduced. Browser
observes saved revoked access, current/historical patch distinction and real 403.
Source remains schema e8c1a7b4d209, 31 requests, 213 events, ten reservations;
only the new target was migrated. AI off/cap zero/empty keys, no inference/release.
See OFFLINE_HANDOFF and `evidence/offline-gaps-2026-10-18/` for scope and failures.

October 18 LangGraph pass: 348 Python tests pass in 26.02 seconds, JUnit
`evidence/langgraph-2026-10-18-tests-r1.xml`; 26 frontend tests and web build pass.
Primary `evidence/langgraph-2026-10-18-r3/report.json` records 96/96 offline
scheduler-case executions, 48 paired matching outcomes, two actual process-exit
recoveries and the native interrupt replay control. Synthetic callbacks, zero
inference; not 96 unique scenarios or production fault coverage. Sequential versus
graph p95 worker-phase time: 7.566 versus 8.661 ms, 135 samples each, local SQLite.
Earlier timing r1/r2 overlapped other checks and remains retained, not primary.
Private demo's exact trusted fixture passes seven actual external-oracle cases;
browser reads saved nodes/reviewers and refreshes, with no adoption/release.
No new disposable-container experiment, model quality, public CI or customer proof.
LangGraph dependency resolution initially conflicted with websockets 17.1; tested
16.1.1 resolves it. `pip check` passes. Optional 3D large-chunk warning remains.
Details and reproduction in LANGGRAPH; prior failed evidence remains unchanged.

October 13 engineering-depth pass: 273 Python tests pass in 16.76 seconds, one
existing dependency warning. Recorded JUnit:
`evidence/implementation-2026-10-13-pytest-final.xml`. External-oracle Docker
expectations 13/13 and sidecar 15/15 pass; the legacy false pass is reproduced.
See VERIFIER_LAB for why earlier network/write controls were superseded.
Bounded repair passes 17 assertions in the process/Docker lab and 17 in the real
PostgreSQL race/crash lab, with all children reaped and main counts/budget unchanged.
These are synthetic checks, not new live model results. The migrated local HTTP
journey passes seven PDF cases, Atlas grant/revoke, Nova denial and proof digests.
Original reservations remain 10; runtime is off, cap 0, credential absent.

The safe-change benchmark freezes 20 development/40 held-out authored cases.
Held-out parser 32/40 exact/route successes; kind-only 15/40 route successes;
eight parser failures preserved. Compatibility exercises two owned hosts and one
upgrade each: ten invariants pass, six named mutants detected, twenty effects match
manual flags. The baseline ties OwnStack on one-adapter maintenance edits.
Source, commands, limits and raw reports are in SAFE_CHANGE_BENCHMARK and
COMPATIBILITY_LAB. Independent reviewers, real customers and new approved live
comparisons remain pending. Frontend/browser/package results are in
COMPLETION_HANDOFF; earlier visual counts below remain dated checkpoints.

October 12 product-aligned variation map, third pass: 143 Python tests pass in
13.86 seconds with one existing dependency warning; 14 frontend tests and
TypeScript/Vite/web-container builds pass. Five new tests cover all eight example
states, Nova invariance, one shared app, no deployment, stage bounds and PDF route
separation. Two obsolete layer/camera tests were removed with their unused helpers.
Actual browser checks cover Atlas-only and rollback readouts, PDF engineering,
keyboard arrows/Home/End, pause/simple-view disposal/remount and intake Escape
restoring New request focus. Sampled widths 320/390/961/1024/1440 have no page-level
horizontal overflow. Initial silver facades, hidden routes, offscreen blank canvas
and cropped mobile board were corrected; earlier captures remain. Latest browser
console query returned no warnings/errors. AI off, cap zero, no runtime credential,
durable counter ten. No request, grant, inference or release created in this pass.
The 559.85 kB minified / 142.61 kB gzip optional renderer retains its size warning.
See [third visual report](evidence/ui-cinematic-2026-10-12-r3/report.json).
No new real-host authorization rehearsal, real-device pinch/GPU test, context-loss
fault injection, system reduced-motion toggle or independent usability is claimed.

October 12 physical 3D revision: 143 Python/11 frontend tests and TypeScript/Vite
build pass. Actual local WebGL, mouse rotation, assembly, stage keyboard control,
simple-view disposal/remount and dialog focus restoration checked in browser.
Home overflow checks cover 320/390/961/1024/1440 widths; screenshots retain the
initial overbright lighting and corrected views. Runtime remains AI off, cap zero,
credential absent, durable counter ten. No new grant or inference in this pass.
The separate 3D chunk retains Vite's size warning. Context-loss fault injection,
system-preference toggling, FPS and real mobile GPU testing remain unexecuted.
See [second visual report](evidence/ui-cinematic-2026-10-12-r2/report.json).

October 12 cinematic UI pass: 143 Python tests, eight frontend tests and
TypeScript/Vite build pass. Two new pure tests cover exact display identity and
unconfirmed-create key reuse. Browser checked 390/1024/1440 layouts, scene layer
selection/keyboard/pause, dialog focus/Escape, exact approval acknowledgement and
the AI-off engineer/admin/contractor journey. Actual grant/read/revoke/403 passed;
rehearsal request `c67e3d50-2a1f-4ca6-ba93-7f244b0028c4` ends revoked. Original
inference counter remains ten, runtime off, cap zero, credential absent. Only
the local web container changed. Screenshots, corrections and limits are in the
[dated report](evidence/ui-cinematic-2026-10-12/report.json). No independent
usability/accessibility, browser network-delay injection, FPS/load benchmark,
new inference or public deployment is claimed. Reduced-motion behavior is
implemented and source-reviewed, not tested by changing the system preference.
Earlier video and archives retain their original UI.

Later October 10 reliability pass: 143 Python tests, six frontend tests and build
pass; Python statement coverage 1,343/1,673 (80.27%), one dependency warning.
[Real-process fault lab](RELIABILITY_LAB.md) primary
[r3](evidence/reliability-2026-10-10-r3/report.json) passes 36/36 executions of 12
scenarios across three repetitions, including 12 deliberate SIGKILLs. Five/five
specified defective baselines are detected once each; 85/85 children are reaped;
39 positive-control requests have zero queued/running attempts. Eight cold same-key
creates, queued repeats and running repeats are barrier-aligned. PostgreSQL rolls
back the killed precommit acceptance; saved result survives worker/API deaths.
The provider is synthetic throughout. Main table counts and budget 10 match
before/after; the lab copies the exhausted count with cap zero. r1/r2 retained.
Rebuilt local API/worker are off, cap zero, no live credentials; installed service
hash matches source. Manual full-stack smoke again passes Atlas/Nova/revoke,
independent fixture patch checks and proof digests, budget 10 unchanged. Exact
handoff: [reliability-handoff](evidence/reliability-handoff-2026-10-10.json).
Not live outage, full-service capacity, backup recovery, signed attestation or
production security. CI is configured, not observed on a public runner.

October 10 latest: 127 Python tests, six frontend tests and build pass; Python
statement coverage 1,340/1,670 (80.24%). Exact grant selector agrees with exhaustive
policy across 500 seeded comparisons; migration upgrade/downgrade/re-upgrade keeps
the synthetic exhausted ledger. Existing PostgreSQL upgraded to `d74f109a32be`,
index verified, AI-off HTTP grant/read/Nova denial/revoke/check/proof smoke passes,
counter 10 before/after. Local paired p95 59.065 to 1.893 ms at 10,000 historical
grants, 200 samples each, same index. Not full request latency or production load.
See [methodology](PERFORMANCE.md) and [dated evidence](evidence/performance-handoff-2026-10-10.json).

Latest Orbital UI pass, October 9: 69/69 Python tests, 6/6 frontend derivation
tests and web build pass. Actual AI-off HTTP smoke and browser grant/read/revoke/
403 pass with count 10 unchanged. Keyboard quick-navigation Escape restores focus;
approval acknowledgement resets on reopen; 390/1024 checked views have no
page-level horizontal overflow. See [UI evidence](evidence/ui-redesign-2026-10-09.json)
and [UX design](UX_DESIGN.md). Agent QA is not independent accessibility/usability
certification. Earlier video and bundles retain pre-redesign UI.

This file separates repeatable local evidence from claims that still require an external test. Re-run the commands, do not copy a past result into a submission without checking it.

| Check | Observed locally through 2026-10-09 | What it proves | What it does not prove |
| --- | --- | --- | --- |
| Latest submission preparation | 68/68 tests and web build pass October 9; AI-off smoke preserves count 10; local MP4 162 seconds; actual form inspected read-only | Demo endpoint/packaging regressions, real saved UI and offline materials exist | Public access, owner declarations, continuous live capture, final submission or production certification |
| `.venv/bin/pytest` | 61 tests passed on 2026-10-09 | Previous 49 checks plus host-observation attribution/exclusion/isolation/fail-closed behavior, proof digest/access controls, upgrade preserving exhausted budget and worker configuration fences | Production security or hosted behavior |
| Browser cookie login and refresh after session hardening | Passed on 2026-10-07 | Saved identity and accepted fixture proposal reappear, preview shows finite 24-check counterfactual | Live inference or independent usability study |
| `.venv/bin/python -m ownstack.evaluate` | 10 offline cases; simple baseline 4 correct, synthetic fixture 5 correct | The fixed fixture has route-quality weaknesses that are visible | Live Nemotron quality or production safety |
| `pnpm --dir web build` | Passed at last check | TypeScript and Vite build | Browser accessibility or user success |
| Alembic upgrade on empty SQLite | Passed | Revision applies on SQLite | PostgreSQL behavior |
| Alembic upgrade and synthetic seed on separate local PostgreSQL 16 | Passed | Revision and seed work on PostgreSQL | Crash/restart load test |
| Inference budget migration on local PostgreSQL 16 | Passed on 2026-10-07 | New revision applies transactionally after the first | Actual Token Factory billing or credits |
| Docker verifier on fixture patch | Three independent PDF checks passed | Known patch passes fixed local checks in no-network container | Live model quality, sandbox certification or release |
| `scripts/smoke_full_stack.py` against Compose | Passed on 2026-10-07 with PostgreSQL, Nginx, API, verifier sidecar | Actual HTTP path enforces Atlas access then revoke, denies Nova, checks manual patch, records human decision without deployment or AI calls | Public hosting, live model output, hostile-code sandbox certification |
| Browser Atlas admin to contractor journey | Created request, got fixture proposal, previewed, approved, read Atlas documents | Synthetic local end-to-end host effect | Live Nebius or customer outcome |
| Browser PDF engineering journey | Fixture proposal created a bounded patch; Docker ran three independent checks and reported pass | Synthetic local code-review and check path | Live model patch quality or deployment |
| Direct Nova and contractor denial tests | Passed in API tests | Specific tested isolation cases | Exhaustive tenant security |
| Cookie-authenticated full-stack smoke after session migration | Passed on 2026-10-07 | PostgreSQL migration, cookie/CSRF flow, no-network checks, exact accepted artifact and server logout work through Nginx | Production identity lifecycle or public TLS |
| `scripts/drill_concurrency.py` | Passed on 2026-10-07 | Four simultaneous duplicate POSTs create one request; four interpretation POSTs share one attempt on PostgreSQL | Load capacity or exhaustive concurrency proof |
| Official account/model inspection | $25 credit balance observed; Nano and Super IDs/prices read; Nano playground offers JSON object/schema | Account credit and catalog facts at inspection time | Successful inference or billing guarantee |
| `scripts/prove_live_workflow.py` | Two live Nano interpretations accepted; Atlas read, Nova denial and revoke passed; PDF draft failed; three calls reserved | Real runtime model affects the synthetic user workflow; failed patch is not accepted | Live patch quality, production security or total provider billing |
| First explicit `scripts/retry_live_patch.py` | One call reserved, rejected `MODEL_OUTPUT_TRUNCATED`, failed work item remains inspectable | Truncated answer is not persisted as a valid patch; original evidence preserved | Remote inference cancellation or successful patch generation |
| Further explicit patch experiments | Nano reasoning-sampling retry also truncated; Super returned patch in 20,649 ms, syntax checks failed | Genuine model-proposed code can fail independently and cannot become a release | Any successful autonomous coding outcome |
| `scripts/capture_live_comparison.py` | Four calls on two frozen newly worded cases: Nano 2/2, Super 2/2, baseline 1/2 | Small raw route comparison with a negative case, actual latency/tokens and partial cost estimates | Robust generalization, full billing or model superiority |
| `scripts/prove_manual_recovery.py` | Agent-authored manual-path correction passed 4/4 independent checks, zero new calls; no human decision or deployment | Engineer can recover after failed checks without losing original proposal/evidence | User unaided implementation or successful model-only patch |
| `scripts/prove_expiry_and_cap.py` | Eight-second manual grant allowed a read then denied it after expiry, before revoke; exhausted live interpretation returned 429 with no saved attempt and zero extra reservations | Actual HTTP read-time expiry and pre-dispatch call cap | Live inference, remote cancellation or exhaustive isolation |
| Corrected source archive installed into separate local Compose project | Passed on 2026-10-07, including fresh PostgreSQL migrations, HTTP smoke and concurrency drill on port 8081 | Public source permissions, clean database setup, dependency install, web build and documented synthetic journey | Independent tester, remote CI, public availability or live AI |
| Production Compose overlay syntax | `config --quiet` passed with example placeholders | Overlay parses and removes direct web publication | Actual TLS provisioning, operational security or deployment |
| October 9 AI-off HTTP smoke | Passed; one actual grant-attributed read, tenant-safe observation ledger, both proof envelopes verified, fixed fixture patch checked, counter 10 before/after | New observation/proof path runs through Nginx, PostgreSQL and no-network sidecar | No new live call, successful model patch, demand or deployment |
| October 9 full service/database restart | `check_saved_state.py` matched fingerprint `28b2f4ef0eaf8a281aa0c22526ba0149b817a6dbed7c33452ec7fed4bedb54c7` before/after | Same saved manual request, attempts, exact approval, variation, observation, checks/events survive restart; AI-off/counter 10 | Backup/restore, concurrent crash during commit, live provider recovery or load capacity |
| October 9 browser inspection | Admin session restored after reload; PDF/access Convergence cards distinguish granted API reads from requests; filtered evidence ledger shows saved history | Local browser renders saved state and actual use separately | Independent usability/accessibility study |
| October 9 source handoff | Archive `ownstack-test-build-2026-10-09.zip`, 121 public files, SHA-256 `34e98c6e8490859c97cacfd19669cb0515ddd184986ea638b320c7f65c389791`; extracted source passes 61 tests | Packaged runtime/test source works with reused installed dependencies, explicit empty credentials and zero live cap; configured credential found in zero public files | Not current fresh dependency install, new PostgreSQL install, independent clone, public URL or runtime attestation; post-package evidence-table notes are outside that archive |

## Minimum reproducible checks

Later October 9 submission pass: 68/68 regressions and web build pass. The rebuilt
AI-off HTTP smoke again enforced/revoked Atlas access, denied Nova, ran fixture
checks in the sidecar and verified proofs, with reservations 10 before/after.
Historical-evidence endpoint authentication/missing-artifact/zero-call tests and
submission packaging/inventory regressions are included. See
`evidence/submission-preparation-2026-10-09.json` for exact request IDs and failures.
The local video is 162 seconds with one audio/video track; three decoded frames
were visually inspected. Owner audio/full-playback review and public upload are
pending. Actual Devpost fields were inspected read-only. Offline strict preflight
returns 2 for missing external URLs/confirmations; that is not a regression pass
or final submission readiness. No new inference was used.

```bash
.venv/bin/pytest --tb=short
pnpm --dir web build
.venv/bin/alembic current
curl -sS http://127.0.0.1:8800/health/ready
OWNSTACK_AI_MODE=off docker compose -f compose.full.yaml up -d --build
.venv/bin/python scripts/smoke_full_stack.py
```

The older `drill_concurrency.py` requires fixture interpretation; it is not part of
the current AI-off rehearsal. Never switch the main runtime to live merely to run
it. For the verifier, use the manual engineer handoff and manual patch with Docker
running. Do not run generated code directly on your host. No new inference is
authorized by these instructions. The original allowance is exhausted.

## Evaluation plan

The ten cases in `evals/interpretation_cases.json` are a reproducible **offline development** set, not a held-out benchmark. The synthetic fixture scores 5/10 and a simple kind-only baseline scores 4/10. This is useful precisely because it exposes weak interpretation; fixed host policy remains the authority. Before submission, freeze a separate held-out set with valid Atlas grant, expiry, over-seven-day grant, Nova cross-tenant identifiers, write permission disguised as access, unsupported PDF export, prompt injection, duplicate request, model 429/timeout/invalid JSON, worker restart, and late attempt 1 after attempt 2. Compare a current fast Nemotron and stronger Nemotron on route correctness, policy overrides, latency, token usage and price per accepted result. Keep raw cases and redacted outputs. A fake fixture result must never be reported as live inference.

For buyer validation, interview B2B SaaS engineers about a recent real customer-specific request. Measure manual baseline lead time, engineer touches, rollback time, incident rate and number of maintained forks. Do not infer demand from a hackathon demo or judge reaction.

The [unproven list](UNPROVEN.md) is the release and submission gate.
