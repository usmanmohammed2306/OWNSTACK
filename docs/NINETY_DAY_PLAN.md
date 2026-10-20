# OwnStack: 90 days of meaningful feature commits

Start: October 19, 2026. Day 90: January 16, 2027. Dates use America/Phoenix.
Usman explicitly restarted Day 1 on October 19. The unused October 14 calendar is
preserved in `history/NINETY_DAY_PLAN_2026-10-14.md`; no work is marked complete.
This replaces the active learning calendar; the earlier 30-day map stays as history.
No day is marked completed by a calendar, a reminder, an existing reference file or
an agent test. Your existing end-to-end contribution confirmation stays intact.

## Publication and learning

Keep the complete tested app available for the October 30 hackathon. Its deadline
is October 30, 2026 at 10 a.m. Phoenix time, Day 12, as rechecked against the
[official rules](https://nebiusglobalaihackathon.devpost.com/rules) on October 14.
A 90-day rebuild is a separate learning history. Do not hold back required code
until January or claim a partially uploaded repository runs the whole demo.

Recommended: publish the reference as one disclosed baseline when you review it,
then use an independent OwnStack rebuild repository for these daily slices.
Alternative: publish a complete baseline in one repository, then make real
improvements daily. Do not split already-written code solely to imply it was
implemented on ninety later days. A day's contribution can be a feature you
personally reconstruct, a real bug fix or a reproducible experiment. Never backdate,
make empty commits, or push files you cannot explain just to change the graph.

The current source repository has no commits at this audit. Do not stage all its
untracked files accidentally. GitHub counts qualifying commits associated with your
account on the default branch or gh-pages; forks and email association have further
conditions. Read [GitHub's actual criteria](https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference).
A daily push does not itself establish a contribution for that date or a hiring outcome.

## A 30 to 60 minute daily loop

Optional October 18 reference extension: [LANGGRAPH](LANGGRAPH.md) adds a three-slice
reconstruction path after the durable repair prerequisites. It does not replace
the ninety dated slices, mark any lesson complete or justify pushing prewritten
code as ninety newly authored features. Learn the SQL fences before the framework.

1. Predict the proof in the day's row before reading the reference.
2. Read the named file and the matching resource below.
3. Close the reference and implement one small behavior in your learning repository.
4. Write the negative regression, run it, then run the feature check.
5. Explain the decision owner in two sentences and record actual output in your journal.
6. Review, commit specific changed files and push yourself after tests pass.

The reference check column is runnable here, not automatically runnable in an
incomplete rebuild. Add the corresponding test in your own repository and run only
that test until its dependencies exist. Browser behaviors require a browser
exercise in addition to helper tests. Process/container labs require their documented
prerequisites. These are target behaviors, not ninety promised green test reports.

Use `python scripts/daily_slice.py --day 1` in this reference for the short lesson.
Without a day it uses today's Phoenix date. `--next` chooses the first incomplete
slice from a private progress file. Existing code is reference material.
All lessons are offline. The ten-call allowance is exhausted. Price/model study can
use saved results; new inference requires renewed approval.

After implementation in your own repository:

```bash
git status --short
git diff --check
# Run the day's actual relevant test here.
git add -- path/to/feature.py path/to/test_feature.py
git diff --cached --stat
git diff --cached
git commit -m "feat: implement the day's tested behavior"
git push
```

Replace the example file names with the actual two or three files you changed.
Confirm the remote points to your intended repository before the first push.
Keep your verified account email private if desired by using GitHub's noreply address.
A missed day moves the unfinished slice forward; do not fabricate a result.

## Calendar and exact feature slices

Each row is planned reconstruction or improvement, not completion. Commit messages
are suggestions for work actually performed. Days 88 to 90 include a small tool or
experiment implementation alongside the write-up, not a cosmetic README change.

| Day | Phoenix date | Feature | Reference | Proof to produce | Reference check | Suggested commit |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | 2026-10-19 | Read decision | `src/ownstack/policy.py` | Allow an admin in Atlas; deny a contractor without a grant. | `.venv/bin/pytest tests/test_policy.py -q` | `feat: implement read decision` |
| 02 | 2026-10-20 | Tenant boundary | `src/ownstack/policy.py` | An Atlas principal cannot read Nova even with an admin role. | `.venv/bin/pytest tests/test_policy.py -q` | `feat: implement tenant boundary` |
| 03 | 2026-10-21 | Exact expiry | `src/ownstack/policy.py` | At the expiry instant the grant is denied. | `.venv/bin/pytest tests/test_policy.py -q` | `feat: implement exact expiry` |
| 04 | 2026-10-22 | Project and viewer scope | `src/ownstack/policy.py` | Changing either project or viewer denies the grant. | `.venv/bin/pytest tests/test_policy.py -q` | `feat: implement project and viewer scope` |
| 05 | 2026-10-23 | Revocation state | `src/ownstack/policy.py` | A revoked grant denies the next read. | `.venv/bin/pytest tests/test_policy.py -q` | `feat: implement revocation state` |
| 06 | 2026-10-24 | Capability duration | `src/ownstack/policy.py` | Zero, past and over-seven-day durations are rejected. | `.venv/bin/pytest tests/test_policy.py -q` | `feat: implement capability duration` |
| 07 | 2026-10-25 | Host preview | `src/ownstack/service.py` | Preview calls the shared policy and creates no observation. | `.venv/bin/pytest tests/test_observations.py -q` | `feat: implement host preview` |
| 08 | 2026-10-26 | Canonical proposal digest | `src/ownstack/policy.py` | Key ordering is stable; a changed parameter changes the digest. | `.venv/bin/pytest tests/test_policy.py -q` | `feat: implement canonical proposal digest` |
| 09 | 2026-10-27 | Two-tenant host API | `src/ownstack/api.py` | Unauthenticated document reads return 401. | `.venv/bin/pytest tests/test_api.py -q` | `feat: implement two-tenant host api` |
| 10 | 2026-10-28 | Object lookup isolation | `src/ownstack/api.py` | Foreign document IDs return 404 without leaking a body. | `.venv/bin/pytest tests/test_api.py -q` | `feat: implement object lookup isolation` |
| 11 | 2026-10-29 | Password verification | `src/ownstack/auth.py` | Wrong passwords fail without identifying unknown users. | `.venv/bin/pytest tests/test_sessions.py -q` | `feat: implement password verification` |
| 12 | 2026-10-30 | Opaque cookie sessions | `src/ownstack/auth.py` | Login restores identity; logout invalidates the saved cookie. | `.venv/bin/pytest tests/test_sessions.py -q` | `feat: implement opaque cookie sessions` |
| 13 | 2026-10-31 | CSRF and origin checks | `src/ownstack/auth.py` | Missing CSRF or an unapproved Origin denies mutation. | `.venv/bin/pytest tests/test_sessions.py -q` | `feat: implement csrf and origin checks` |
| 14 | 2026-11-01 | Account offboarding | `src/ownstack/members.py` | Disable and re-enable cannot revive an old cookie or token. | `.venv/bin/pytest tests/test_members.py -q` | `feat: implement account offboarding` |
| 15 | 2026-11-02 | Request idempotency | `src/ownstack/service.py` | One key shares one request; changed bodies conflict. | `.venv/bin/pytest tests/test_api.py -q` | `feat: implement request idempotency` |
| 16 | 2026-11-03 | Durable outbox delivery | `src/ownstack/outbox.py` | A consumer receipt survives sender death and deduplicates replay. | `.venv/bin/pytest tests/test_outbox.py -q` | `feat: implement durable outbox delivery` |
| 17 | 2026-11-04 | Exact approval | `src/ownstack/service.py` | A changed proposal hash cannot authorize a grant. | `.venv/bin/pytest tests/test_api.py -q` | `feat: implement exact approval` |
| 18 | 2026-11-05 | Preview revision fence | `src/ownstack/service.py` | Changing a document after preview makes approval conflict. | `.venv/bin/pytest tests/test_api.py -q` | `feat: implement preview revision fence` |
| 19 | 2026-11-06 | Atomic activation | `src/ownstack/service.py` | Approval, variation, event and outbox commit together. | `.venv/bin/pytest tests/test_api.py -q` | `feat: implement atomic activation` |
| 20 | 2026-11-07 | Additive migrations | `migrations/versions/a14d09c7f602_operations.py` | Upgrade and downgrade retain the exhausted reservation ledger. | `.venv/bin/pytest tests/test_migration.py -q` | `feat: implement additive migrations` |
| 21 | 2026-11-08 | Durable credit guard | `src/ownstack/service.py` | An exhausted counter rejects a call before dispatch. | `.venv/bin/pytest tests/test_budget.py -q` | `feat: implement durable credit guard` |
| 22 | 2026-11-09 | Saved attempt states | `src/ownstack/models.py` | GET saved state never dispatches inference. | `.venv/bin/pytest tests/test_api.py -q` | `feat: implement saved attempt states` |
| 23 | 2026-11-10 | Worker claim | `src/ownstack/worker.py` | Two competing workers cannot claim the same pending attempt. | `.venv/bin/pytest tests/test_worker.py -q` | `feat: implement worker claim` |
| 24 | 2026-11-11 | Late-result fence | `src/ownstack/service.py` | Attempt 1 cannot overwrite accepted attempt 2. | `.venv/bin/pytest tests/test_api.py -q` | `feat: implement late-result fence` |
| 25 | 2026-11-12 | Local deadline | `src/ownstack/worker.py` | Timeout retains an honest failure and permits manual continuation. | `.venv/bin/pytest tests/test_worker.py -q` | `feat: implement local deadline` |
| 26 | 2026-11-13 | Local cancellation | `src/ownstack/api.py` | Cancel invalidates acceptance without promising remote cancellation. | `.venv/bin/pytest tests/test_operations.py -q` | `feat: implement local cancellation` |
| 27 | 2026-11-14 | Process recovery | `ops/reliability/child.py` | Kill a synthetic worker and inspect rollback versus committed state. | `.venv/bin/pytest tests/test_reliability_lab.py -q` | `feat: implement process recovery` |
| 28 | 2026-11-15 | Accepted redelivery guard | `src/ownstack/service.py` | A duplicate accepted result cannot relabel the original accepted state. | `.venv/bin/pytest tests/test_api.py -q` | `feat: implement accepted redelivery guard` |
| 29 | 2026-11-16 | Saved result refresh | `web/src/responseIdentity.ts` | A refresh shows saved data and does not create another attempt. | `node --experimental-strip-types --test web/tests/responseIdentity.test.mjs` | `feat: implement saved result refresh` |
| 30 | 2026-11-17 | Honest waiting states | `web/src/responseDeadline.ts` | A transport ignoring AbortSignal still times out locally. | `node --experimental-strip-types --test web/tests/responseDeadline.test.mjs` | `feat: implement honest waiting states` |
| 31 | 2026-11-18 | Unsupported feature route | `src/ownstack/ai.py` | PDF export cannot be approved as a temporary read grant. | `.venv/bin/pytest tests/test_ai.py -q` | `feat: implement unsupported feature route` |
| 32 | 2026-11-19 | AI-off engineer handoff | `src/ownstack/service.py` | An engineer continues without a provider call. | `.venv/bin/pytest tests/test_manual.py -q` | `feat: implement ai-off engineer handoff` |
| 33 | 2026-11-20 | Allowlisted patch surface | `src/ownstack/runner.py` | Traversal, extra files and invalid anchors are rejected. | `.venv/bin/pytest tests/test_runner.py -q` | `feat: implement allowlisted patch surface` |
| 34 | 2026-11-21 | Exact source diff | `web/src/review.ts` | Empty lines and trailing newlines remain inspectable. | `node --experimental-strip-types --test web/tests/review.test.mjs` | `feat: implement exact source diff` |
| 35 | 2026-11-22 | Patch digest | `src/ownstack/runner.py` | Changing one source byte invalidates earlier evidence. | `.venv/bin/pytest tests/test_runner.py -q` | `feat: implement patch digest` |
| 36 | 2026-11-23 | Fixed candidate command | `src/ownstack/candidate_driver.py` | Candidate output cannot choose shell commands. | `.venv/bin/pytest tests/test_runner.py -q` | `feat: implement fixed candidate command` |
| 37 | 2026-11-24 | Empty-output oracle | `src/ownstack/pdf_oracle.py` | Exit zero without a PDF is rejected. | `.venv/bin/pytest tests/test_pdf_oracle.py -q` | `feat: implement empty-output oracle` |
| 38 | 2026-11-25 | PDF structure checks | `src/ownstack/pdf_oracle.py` | Wrong offsets or inconsistent xref entries are rejected. | `.venv/bin/pytest tests/test_pdf_oracle.py -q` | `feat: implement pdf structure checks` |
| 39 | 2026-11-26 | Forged verdict rejection | `src/ownstack/pdf_oracle.py` | A printed success verdict cannot replace actual PDF bytes. | `.venv/bin/pytest tests/test_pdf_oracle.py -q` | `feat: implement forged verdict rejection` |
| 40 | 2026-11-27 | Negative PDF corpus | `scripts/run_verifier_lab.py` | Keep every failed control and its authored expectation. | `.venv/bin/pytest tests/test_pdf_oracle.py -q` | `feat: implement negative pdf corpus` |
| 41 | 2026-11-28 | Detached child cleanup | `src/ownstack/process_supervisor.py` | Inspect bounded descendant cleanup and preserve its limits. | `.venv/bin/pytest tests/test_runner.py -q` | `feat: implement detached child cleanup` |
| 42 | 2026-11-29 | Bounded execution | `src/ownstack/bounded_process.py` | Overlong output or local deadline cannot become a pass. | `.venv/bin/pytest tests/test_runner.py -q` | `feat: implement bounded execution` |
| 43 | 2026-11-30 | Verifier provenance | `src/ownstack/runner.py` | Changed oracle or supervisor requires fresh verification. | `.venv/bin/pytest tests/test_runner.py -q` | `feat: implement verifier provenance` |
| 44 | 2026-12-01 | Manual correction history | `src/ownstack/api.py` | A correction retains the failed model proposal. | `.venv/bin/pytest tests/test_manual.py -q` | `feat: implement manual correction history` |
| 45 | 2026-12-02 | Human release handoff | `src/ownstack/api.py` | Passing checks enable a human decision; release remains explicit. | `.venv/bin/pytest tests/test_operations.py -q` | `feat: implement human release handoff` |
| 46 | 2026-12-03 | Durable repair runs | `src/ownstack/repair.py` | A run keeps the original failed patch and at most two attempts. | `.venv/bin/pytest tests/test_repair.py -q` | `feat: implement durable repair runs` |
| 47 | 2026-12-04 | Generator provenance | `src/ownstack/repair.py` | Changed configuration cannot silently reroute saved work. | `.venv/bin/pytest tests/test_repair.py -q` | `feat: implement generator provenance` |
| 48 | 2026-12-05 | Separate verification claim | `src/ownstack/repair.py` | Generation and independent checks use distinct durable claims. | `.venv/bin/pytest tests/test_repair.py -q` | `feat: implement separate verification claim` |
| 49 | 2026-12-06 | Candidate adoption | `src/ownstack/repair.py` | A passing candidate waits for exact human adoption. | `.venv/bin/pytest tests/test_repair.py -q` | `feat: implement candidate adoption` |
| 50 | 2026-12-07 | Manual takeover | `src/ownstack/repair.py` | Takeover fences a late repair answer and preserves evidence. | `.venv/bin/pytest tests/test_repair.py -q` | `feat: implement manual takeover` |
| 51 | 2026-12-08 | Cockpit saved history | `web/src/repairView.ts` | Another tenant or login cannot display the old run. | `node --experimental-strip-types --test web/tests/repairView.test.mjs` | `feat: implement cockpit saved history` |
| 52 | 2026-12-09 | Queue fairness | `src/ownstack/worker.py` | Interpretation and repair both receive a worker cycle. | `.venv/bin/pytest tests/test_worker.py -q` | `feat: implement queue fairness` |
| 53 | 2026-12-10 | At-least-once lease | `src/ownstack/outbox.py` | Expired leases can retry while old acknowledgements are rejected. | `.venv/bin/pytest tests/test_outbox.py -q` | `feat: implement at-least-once lease` |
| 54 | 2026-12-11 | Receiver acknowledgement | `src/ownstack/outbox.py` | Redirects, large replies and wrong digest acknowledgements fail. | `.venv/bin/pytest tests/test_outbox.py -q` | `feat: implement receiver acknowledgement` |
| 55 | 2026-12-12 | Delivery backoff | `src/ownstack/outbox.py` | Failures wait and the fifth failure enters a dead-letter state. | `.venv/bin/pytest tests/test_outbox.py -q` | `feat: implement delivery backoff` |
| 56 | 2026-12-13 | Tenant operating signals | `src/ownstack/operations.py` | Atlas cannot see Nova queue counts or identity events. | `.venv/bin/pytest tests/test_outbox.py -q` | `feat: implement tenant operating signals` |
| 57 | 2026-12-14 | Session revocation audit | `src/ownstack/members.py` | Session revocation stores an identity event without secrets. | `.venv/bin/pytest tests/test_members.py -q` | `feat: implement session revocation audit` |
| 58 | 2026-12-15 | Private backup | `src/ownstack/recovery.py` | Backup files are private and never enter the source package. | `.venv/bin/pytest tests/test_recovery.py -q` | `feat: implement private backup` |
| 59 | 2026-12-16 | Independent restore write | `src/ownstack/recovery.py` | Restored records match the snapshot; a target write leaves source alone. | `.venv/bin/pytest tests/test_recovery.py -q` | `feat: implement independent restore write` |
| 60 | 2026-12-17 | Migration budget preservation | `tests/test_migration.py` | Upgrading an existing ledger retains ten reservations. | `.venv/bin/pytest tests/test_migration.py -q` | `feat: implement migration budget preservation` |
| 61 | 2026-12-18 | Observed grant attribution | `src/ownstack/host_access.py` | Only actual granted host checks count as variation use. | `.venv/bin/pytest tests/test_observations.py -q` | `feat: implement observed grant attribution` |
| 62 | 2026-12-19 | Consistent proof export | `src/ownstack/proof.py` | Export reads one tenant snapshot and omits credentials and bodies. | `.venv/bin/pytest tests/test_proof.py -q` | `feat: implement consistent proof export` |
| 63 | 2026-12-20 | Offline proof verifier | `scripts/verify_proof.py` | Tampering fails the digest; recomputing it is still not authenticity. | `.venv/bin/pytest tests/test_proof.py -q` | `feat: implement offline proof verifier` |
| 64 | 2026-12-21 | Human convergence decision | `src/ownstack/api.py` | An owner supplies rationale; promotion does not release code. | `.venv/bin/pytest tests/test_api.py -q` | `feat: implement human convergence decision` |
| 65 | 2026-12-22 | Frozen evaluation split | `src/ownstack/change_benchmark.py` | Development and held-out cases remain separate. | `.venv/bin/pytest tests/test_change_benchmark.py -q` | `feat: implement frozen evaluation split` |
| 66 | 2026-12-23 | Raw versus enforced score | `src/ownstack/change_benchmark.py` | Policy correction cannot hide raw proposal errors. | `.venv/bin/pytest tests/test_change_benchmark.py -q` | `feat: implement raw versus enforced score` |
| 67 | 2026-12-24 | Negative route cases | `evals/safe_change_v1/held_out.json` | Preserve the eight parser errors and explain each boundary. | `.venv/bin/pytest tests/test_change_benchmark.py -q` | `feat: implement negative route cases` |
| 68 | 2026-12-25 | Result import provenance | `src/ownstack/change_benchmark.py` | Wrong case hashes or provenance are rejected. | `.venv/bin/pytest tests/test_change_benchmark.py -q` | `feat: implement result import provenance` |
| 69 | 2026-12-26 | Model failure adapter | `src/ownstack/ai.py` | Invalid output, 429 and timeout retain a manual path using fakes. | `.venv/bin/pytest tests/test_ai.py -q` | `feat: implement model failure adapter` |
| 70 | 2026-12-27 | Provider configuration fence | `src/ownstack/worker.py` | Queued fixture work cannot become an unreserved live call. | `.venv/bin/pytest tests/test_worker.py -q` | `feat: implement provider configuration fence` |
| 71 | 2026-12-28 | Native host adapter | `src/ownstack/compatibility.py` | Two owned schemas expose the same narrow contract effect. | `.venv/bin/pytest tests/test_compatibility.py -q` | `feat: implement native host adapter` |
| 72 | 2026-12-29 | Upgrade version fence | `src/ownstack/compatibility.py` | An unsafe host-schema upgrade refuses stale approval. | `.venv/bin/pytest tests/test_compatibility.py -q` | `feat: implement upgrade version fence` |
| 73 | 2026-12-30 | Restrict-only variation | `src/ownstack/compatibility.py` | Offline redaction cannot expand read permission. | `.venv/bin/pytest tests/test_compatibility.py -q` | `feat: implement restrict-only variation` |
| 74 | 2026-12-31 | Selective rollback | `src/ownstack/compatibility.py` | Revoke one variation without changing Nova or unrelated variation. | `.venv/bin/pytest tests/test_compatibility.py -q` | `feat: implement selective rollback` |
| 75 | 2027-01-01 | Manual flag comparison | `scripts/run_compatibility_lab.py` | Reproduce the comparator tie and retain the negative result. | `.venv/bin/pytest tests/test_compatibility.py -q` | `feat: implement manual flag comparison` |
| 76 | 2027-01-02 | Bounded grant SQL | `src/ownstack/host_access.py` | Return one exact candidate while preserving policy freshness. | `.venv/bin/pytest tests/test_host_access.py -q` | `feat: implement bounded grant sql` |
| 77 | 2027-01-03 | Policy differential tests | `tests/test_host_access.py` | Seeded cases agree with the simpler materializing policy. | `.venv/bin/pytest tests/test_host_access.py -q` | `feat: implement policy differential tests` |
| 78 | 2027-01-04 | Measured query harness | `scripts/benchmark_host_access.py` | Report workload, denominator and small-history regression honestly. | `.venv/bin/pytest tests/test_host_access.py -q` | `feat: implement measured query harness` |
| 79 | 2027-01-05 | Accessible review identity | `web/src/ApprovalReview.tsx` | A stale preview cannot remain bound to a new proposal. | `node --experimental-strip-types --test web/tests/responseIdentity.test.mjs` | `feat: implement accessible review identity` |
| 80 | 2027-01-06 | Keyboard navigation | `web/src/CommandMenu.tsx` | Escape returns focus and navigation remains usable without 3D. | `node --experimental-strip-types --test web/tests/review.test.mjs` | `feat: implement keyboard navigation` |
| 81 | 2027-01-07 | Accessible saved progress | `web/src/BoundedRepair.tsx` | Saved work announces progress and exposes honest retry errors. | `node --experimental-strip-types --test web/tests/repairView.test.mjs` | `feat: implement accessible saved progress` |
| 82 | 2027-01-08 | Optional motion gate | `web/src/sceneMotion.ts` | Reduced motion, offscreen state and pause stop continuous animation. | `node --experimental-strip-types --test web/tests/sceneMotion.test.mjs` | `feat: implement optional motion gate` |
| 83 | 2027-01-09 | Scoped variation illustration | `web/src/variationModel.ts` | All eight display states preserve Nova and one shared app. | `node --experimental-strip-types --test web/tests/variationModel.test.mjs` | `feat: implement scoped variation illustration` |
| 84 | 2027-01-10 | Historical demo boundary | `src/ownstack/demo.py` | Saved live evidence is dated and failed patches stay visible. | `.venv/bin/pytest tests/test_demo.py -q` | `feat: implement historical demo boundary` |
| 85 | 2027-01-11 | Source package inventory | `scripts/package_test_build.py` | The ZIP omits private backups, keys, databases and dependencies. | `.venv/bin/pytest tests/test_package.py -q` | `feat: implement source package inventory` |
| 86 | 2027-01-12 | Submission readiness gate | `scripts/submission_preflight.py` | Local files pass inventory while missing public URLs fail strict mode. | `.venv/bin/pytest tests/test_submission.py -q` | `feat: implement submission readiness gate` |
| 87 | 2027-01-13 | Continuous integration checks | `docs/examples/ci.yml` | Review the inactive example before explicitly enabling CI; inspect a real runner result, not a local badge. | `.venv/bin/pytest tests/test_submission.py -q` | `feat: implement continuous integration checks` |
| 88 | 2027-01-14 | User-task measurement protocol | `docs/FEEDBACK.md` | Implement a small timer and touches log for an approved real task; record no invented participant. | `.venv/bin/pytest tests/test_observations.py -q` | `feat: implement user-task measurement protocol` |
| 89 | 2027-01-15 | Evidence-backed case study | `docs/CASE_STUDY.md` | Add one reproducible experiment artifact with result and limitation. | `.venv/bin/pytest tests/test_proof.py -q` | `feat: implement evidence-backed case study` |
| 90 | 2027-01-16 | Release checkpoint | `docs/UNPROVEN.md` | Build a gate summary from saved checks; leave external unknowns open. | `.venv/bin/pytest tests/test_submission.py -q` | `feat: implement release checkpoint` |

## Resources and practice

- Days 1 to 8: [Python tutorial](https://docs.python.org/3/tutorial/), dataclasses,
  datetime and unittest. Practice a pure read decision with a table of negative cases.
- Days 9 to 17: [FastAPI tutorial](https://fastapi.tiangolo.com/tutorial/),
  [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
  and [Pro Git](https://git-scm.com/book/en/v2). Practice direct requests without React.
- Days 18 to 30: [SQLAlchemy transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html),
  [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html),
  [PostgreSQL locking](https://www.postgresql.org/docs/current/explicit-locking.html).
  Draw the state transition, then remove one fence in a disposable exercise and
  show that your negative test catches the defect.
- Days 31 to 50: [Python subprocess](https://docs.python.org/3/library/subprocess.html),
  [Docker security](https://docs.docker.com/engine/security/) and
  VERIFIER_LAB/BOUNDED_REPAIR. Practice judging output independently of exit status.
- Days 51 to 64: [PostgreSQL backup](https://www.postgresql.org/docs/current/backup.html),
  [sqlite3 backup](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup)
  and operations/recovery reference code. Practice a lost acknowledgement and a
  restored target that retains the same reservation count.
- Days 65 to 78: SAFE_CHANGE_BENCHMARK, COMPATIBILITY_LAB and PERFORMANCE.
  Read [Token Factory structured output](https://docs.tokenfactory.nebius.com/ai-models-inference/json)
  and saved model traces. Keep the held-out set frozen, report errors, and compare
  against the competent feature-flag baseline before making improvement claims.
- Days 79 to 90: [React Learn](https://react.dev/learn),
  [MDN accessibility](https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Accessibility),
  GitHub workflow documentation and FEEDBACK. Practice keyboard completion, an
  independently observed task and a reproducible source archive.

After Day 90, prioritize external evidence over extra scope: an approved identity
provider integration, a real PostgreSQL recovery drill, independent runner review
and an actual B2B team comparison. Choose the next feature from a measured failure.
Do not promise a salary, a job, a prize or permanent employment from this schedule.

## Today's checkpoint

Day 1 is only the pure read decision. In a new learner repository create
`ownstack/policy.py`, `ownstack/__init__.py`, `tests/test_policy.py` and a minimal
`pyproject.toml` with pytest as a test dependency. Avoid the reference's global
API fixture until you have implemented the API.

Predict: can an Atlas contractor with no active grant read an Atlas project?
Use the prepared learner's `can_read(principal: Principal, project_tenant: str)`
function in `../../ownstack-rebuild/ownstack/policy.py`. Today prove only same-tenant
admin allowed and contractor-without-grant denied. Keep the test scaffold and
implement the stub yourself. Run `python3 -m unittest discover -s tests -v` from
`../../ownstack-rebuild`; no third-party test install is needed for this starter.
Tomorrow add the direct cross-tenant denial. Commit your actual implementation as
`feat: implement read decision`. Suggested journal entry: what you predicted,
which test failed first, the result you observed and why the host owns this decision.

## Optional private progress

Use this curriculum in a separate local rebuild. Reading the reference or reaching
a calendar date does not complete a feature. This document does not schedule jobs,
commit code, push changes or authorize inference.

Optional private progress format in `.private/learning-progress.json`:
`{"completed_days": [1], "evidence": {"1": {"commit": "YOUR_REAL_SHA", "check": "YOUR_ACTUAL_RESULT"}}}`.
Do not fill this until you performed the work. It is a user-maintained checklist,
not an independently verified activity log. The lesson command only reads it.
