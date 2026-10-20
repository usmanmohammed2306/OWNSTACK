# Still unproven

Latest October 18: mandatory kernel restrictions, restricted runtime DB role,
production ingress/session/default-account guards and finite hostile-code controls
are implemented and locally exercised. See SECURITY_HARDENING for 416 Python
tests, both current matrices and full AI-off HTTP/restart evidence. This narrows
the gap; it does not close general hostile-code safety. Shared kernel/reused
supervisor, x86 execution, VM-grade per-job isolation, supply-chain review,
independent penetration testing, real TLS path, SSO/MFA/reset, production capacity,
machine-loss recovery and owner-reviewed public delivery remain unverified. The
runtime role has application DML, not row-level tenant security. No live inference
or model-only repair was added. Known seed-password detection is not a general
password-strength audit or automatic rotation.

Later October 18: local PostgreSQL logical restore now matches 24 tables/743 rows
and counter ten from a frozen snapshot. Full AI-off HTTP access, expiry/revoke,
manual PDF recovery and four-service restart pass on a separately restored app.
Proof export includes complete repair history. See OFFLINE_HANDOFF. Public
delivery, customer validation, live repair quality, arbitrary-code containment,
production identity, PostgreSQL graph-specific contention, machine-loss recovery
and capacity/alerting remain unproven. Earlier dated tool-unavailability and
not-yet-rehearsed backup findings below are historical, not current blockers.

October 18: LangGraph repair orchestration is implemented and tested offline.
Its 96 executions repeat sixteen authored cases; parity with a shared-operations
sequential controller does not prove independent safety, better model quality,
production concurrency, arbitrary-code containment or research novelty. The graph
adds measured local overhead. No new live inference, native checkpoint recovery,
independent engineer study or public CI run is claimed. Seven actual demo oracle
checks execute only the exact trusted fixture, not an untrusted model patch.
See LANGGRAPH for source-bound evidence and limitations. October 14 runtime/tool
availability statements below are historical, not rechecked October 18 claims.

October 14 update: outbox dispatch/receipt deduplication, tenant account offboarding,
identity audit and private recovery tooling are implemented and locally tested.
Existing SQLite restore passed; actual PostgreSQL logical restore remains open
because its tools/runtime are unavailable today. HTTP delivery was exercised only
against a local synthetic receiver. Operating signals stay local; no external
receiver/alert service, identity provider, MFA, password reset, public build or
customer study has been validated. See OPERATIONS_HANDOFF for the scoped results.

- General hostile-code safety. October 12 to 13's [VERIFIER_LAB](VERIFIER_LAB.md)
  reproduces and fixes the early-exit false pass using an external PDF oracle.
  Thirteen disposable-container and fifteen sidecar expectations pass, including
  one detached-descendant cleanup. This finite matrix does not certify containment,
  arbitrary PDF correctness, supply-chain safety or sidecar reuse. Historical
  four-check passes are retained, not accepted as current external-oracle proof.

- Live bounded-repair quality. Durable two-attempt repair and offline process/check
  experiments are implemented, but their deliberately failing-then-correct fixture
  is not a successful Nemotron repair. The 60-case proposal benchmark is authored
  synthetic data, with independent review pending. The parser's 32/40 held-out
  successes and eight saved failures do not establish live model superiority.
  No further inference is authorized under the exhausted ten-call allowance.

- General variation portability. The compatibility lab exercises two owned host
  schemas through one upgrade each, not arbitrary SaaS integration. Its competent
  feature-flag baseline matches all twenty measured effects and ties the one-adapter
  maintenance edit count. Real customer time savings and willingness to pay remain
  unmeasured. Redaction is an offline lab contract, not a live host feature.

- Independent comprehension of the product-aligned variation map: can a new user
  explain why preview is not permission, Nova stays unchanged, and PDF requires
  engineering? Its eight display states are tested, not customer-validated.

- Physical 3D rendering across real low-end/mobile GPUs, measured frame time and
  battery cost, browser context-loss injection and actual system reduced-motion
  toggling. October 12's local browser checks and pure motion tests are useful
  but not independent accessibility or device certification. The scene is an
  architecture illustration, never evidence of a live request or authorization.

- Exhaustive process-failure safety and production recovery. October 10's
  RELIABILITY_LAB now passes a finite real PostgreSQL/HTTP/SIGKILL matrix and
  detects five specified defects, but uses a synthetic provider, shortened lab
  deadlines and explicit retry. Not live outages, automatic failover, machine
  loss, backup/restore, production identity or full-service capacity. Schema
  namespacing/socket hooks are harness guards, not sandbox certification.
  Latest source bundle must be distinguished from earlier ZIP/video snapshots.

- Production performance, concurrent full-HTTP capacity and cloud cost savings.
  October 10 local query benchmark reduces history materialization and paired
  p95, but excludes auth, observation commit, network and inference. One-grant
  workload is slightly slower; index-write/storage costs are unmeasured. See
  PERFORMANCE, not a requests-per-second or customer-scale claim. Earlier source
  ZIP/video artifacts do not include this performance pass.

- Independent usability/accessibility review of the Orbital UI. Agent checks
  cover keyboard dialogs, exact-scope approval, responsive layouts and real local
  grant/read/revoke/403, not user comprehension or certification. Earlier video/
  source submission bundles do not include the redesigned UI. No hackathon prize
  or individual judge reaction can be guaranteed.

- Robust live model quality, tail latency and production reliability. Nano runtime inference is now observed on two synthetic requests: access 1,357 ms with 114 input/167 output tokens; PDF interpretation 1,251 ms with 108/156 tokens. These are individual measurements, not a benchmark. The first PDF drafts failed; see the preserved artifacts.
- Actual billing reconciliation and failed-call usage. The official console showed $25 balance, Nano $0.06/$0.24 and Super $0.30/$0.90 per million input/output tokens on October 7. Prices are approximate. The durable 10-call cap limits reservations, not dollars. The approved key is saved privately, ignored and owner-readable only.
- Hosted judge-testable build, production secrets management, dollar-cost caps and alert delivery. Local full-stack HTTP, health pulses and October 9 full service/database restart passed. October 10 additionally kills a worker before transaction commit and verifies rollback/retry in the separate lab. These remain local tests, not backup/restore or public hosting.
- Production identity provider, MFA, password reset/provisioning, tenant administration and independent security review. Revocable opaque HttpOnly/Secure production cookies, CSRF/origin checks, shared login rate windows, disabled accounts and logout are implemented and locally tested. The UI no longer stores bearer tokens.
- Strong isolation for arbitrary model-authored code and a general escape audit. Finite escape-related controls now run and the disposable backend resolves an immutable local image ID per job. The reused sidecar and image supply chain still require stronger review.
- Model patch quality: Nano produced 0/3 usable drafts; the one Super candidate failed syntax checks. An agent-authored manual correction passed four checks, not a model-only success. Two held-out synthetic route cases per model scored 2/2, but larger independent evaluation is still required.
- A real merge/release pipeline. The current human decision explicitly returns `not_deployed`.
- External receiver integration, production alerts and exhaustive multi-worker failure drills. The October 14 dispatcher now supports explicit HTTP delivery, exact acknowledgements, leases, five claims and dead-letter state; its local receipt/HTTP tests pass. No real external receiver is configured or contacted. PostgreSQL delivery load and loss of a host remain open. Prior finite process/event/outbox drills retain their original limits.
- Customer interviews, willingness to pay, a real-team baseline comparison and independent adoption. Offline parser/feature-flag comparisons are implemented, not commercial validation.
- Fresh-clone test by another person, public licensed repository, public test-build/host URL, public YouTube upload and final submission. A 162-second local narrated edited actual-screen draft and captions are now prepared. Actual Devpost fields were inspected read-only October 9; owner ratings, personal declarations, full video/audio review and terms confirmation remain pending.
- GitHub Actions workflow execution on a public runner. The workflow is checked in but has not run remotely.
- Observation retention/partitioning, load impact of fail-closed read logging, unique-user analysis and customer outcome measurement. Granted API counts now work, but include retries and do not establish adoption. Export digests are not signed attestations; an independent verifier can recompute/tamper with them.

Do not say these are shipped. Complete the submission checks against the current [rules](https://nebiusglobalaihackathon.devpost.com/rules) and [resources](https://nebiusglobalaihackathon.devpost.com/resources). The stated deadline is October 30, 2026 at 10 a.m. PDT, but recheck the official page before scheduling a release.
