# Architecture and invariants

OwnStack's difficult problem is not writing a clever prompt. It is letting one tenant change its effective app behavior without forking code or granting the model authority to deploy.

## Local component path

October 18: repair execution uses a real LangGraph `StateGraph`; see [LANGGRAPH](LANGGRAPH.md).
Its typed phase routing and parallel artifact/snapshot checks sit inside the
existing SQL claim/acceptance boundary. SQL is the sole durable continuation;
there is no native graph checkpointer or application `interrupt()`. The human gate
remains authenticated exact adoption and a separate release decision. Source/version
fencing prevents resuming old work under a silently changed workflow. Graph state
omits private prompts/source and external LangSmith tracing is disabled. This
does not make the runner a certified sandbox or authorize additional inference.

`React Studio -> FastAPI control routes -> PostgreSQL records -> fixture or Nebius worker -> proposal -> host-derived preview -> exact admin approval -> host authorization on each read`

The unsupported route continues as `engineering item -> bounded AI or manual patch draft -> disposable verifier -> evidence -> engineer decision`. When inference fails or is off, an engineer can create a proposal without AI. Access still uses the same host preview and requires a tenant-admin approval; a feature request opens the cockpit for a manual patch. Convergence is a separate aggregate, human-only product decision. There is no release automation.

Key files:

| Concern | File | Invariant to inspect |
| --- | --- | --- |
| Capability Contract and host policy | `src/ownstack/policy.py` | Only one project, contractor, read-only, maximum seven days |
| Host and control routes | `src/ownstack/api.py` | Tenant scope and roles are enforced on the server |
| Read-time grant candidates | `src/ownstack/host_access.py` | Exact policy predicates, stable first valid grant, at most one returned candidate; no authorization cache |
| Transactions and proposal fencing | `src/ownstack/service.py` | Approval binds to the exact contract, proposal and fresh preview hashes |
| Durable records | `src/ownstack/models.py`, `migrations/versions/` | Attempts, proposals, approvals, variations, evidence, events, idempotency and outbox persist |
| Inference | `src/ownstack/ai.py`, `src/ownstack/worker.py` | Model returns a proposal, never an authorization decision |
| Counterfactual replay | `src/ownstack/replay.py` | Finite matrix compares before and after, including Nova and post-expiry |
| Code proposal and checks | `src/ownstack/patch_agent.py`, `src/ownstack/runner.py`, `src/ownstack/verifier_service.py` | One allowed file, fixed verifier command, exact patch hash; local Compose uses a separate no-network sidecar |
| Evidence graph | `src/ownstack/repair_graph.py`, `src/ownstack/repair_execution.py` | Explicit routes and two tool witnesses; SQL rechecks at save/adoption, never graph majority vote |
| Owned host fixture | `sample_app/`, `checks/` | PDF code is proposed into a disposable copy, not deployed |
| User interface | `web/src/` | A preview is labeled preview and failures remain inspectable |

## Access journey and trust boundaries

1. Browser authentication creates an opaque cookie session stored only as a hash, with eight-hour expiry, server revocation and enabled-user checks. Mutations require the matching CSRF header/cookie/session hash and permitted Origin. Production sets Secure cookies, requires HTTPS and disables the local teaching bearer-token path. Demo identities are not production identity infrastructure.
2. The admin posts an access request with explicit structured project, contractor, and expiry. A request key makes repeats return the saved result.
3. The worker claims a queued attempt. The fixture or Nebius adapter suggests `configure`, `engineering`, or `refuse`. Server policy can narrow or refuse it. For this single contract, the host preview also requires an explicit read-only access request naming the selected project and rejects known conflicting terms such as export, write, permanent or bypass. This lexical check is defense in depth, not a general semantic proof.
4. The host preview calls `can_read`, which delegates to the same pure `read_decision` used by document reads. It records before/after, visible document identifiers, project revision, document body hashes, and a 24-check finite replay. This is a counterfactual snapshot, not an observed future.
5. The admin approves an exact proposal hash. Approval recomputes the preview and checks contract version/hash and request revision. If data changed, it returns a conflict. A successful transaction writes approval, active variation, event, outbox and idempotency result together.
6. The host API checks every read against current tenant, project, role, variation state, start and expiry. A browser flag cannot grant access. Revocation changes the variation state; expiry is enforced without waiting for a cleanup job. Nova's identifiers return not found to an Atlas principal.

Only server-side host authorization is authoritative. The AI output, React UI, preview, and test result are not.

Actual host reads now persist `HostObservation`: actor/project/document IDs,
authorization time, allowed/denied basis and the exact variation ID if it granted
access. No document body is copied. Missing/cross-tenant objects return 404 without
creating a record in the other tenant. Observation-storage failure prevents data
return. The timestamp denotes authorization, not response completion; revoke can
race an already authorized in-flight read. Preview has no observation side effect.
Convergence counts granted checks separately from repeated requests, excluding
role-based reads and denies. Retries count separately, not as unique users or demand.

The tenant-admin/engineer proof endpoint exports one request's saved records under
a PostgreSQL repeatable-read snapshot (explicit read transaction on SQLite), plus
current source/check hashes. Its envelope digest detects content changes but is
not signed and does not prove authenticity. Current source inventory must not be
confused with historical execution identity. Credentials and document bodies are
excluded; tenant request text and proposed code are private export content.

## Reliability state machine

October 18 proof completeness: the additive private v1 export now includes repair
runs, originals, every candidate/check, bounded feedback and frozen workflow
identities in the same tenant/request snapshot. Configuration fields are allowlisted.
Shared restart fingerprints include these records and contracts, excluding export
time/current source inventory. Older envelopes still verify; fingerprints from
the previous field set require a new baseline. Private code is not public evidence.
The guarded Docker-tool recovery keeps one read-only exported snapshot open for
fingerprint/dump and restores only into a new retained target. A dedicated network,
queue and web port separate the rehearsal from the old app. See OFFLINE_HANDOFF;
logical fixture recovery is not machine-loss failover or stronger code isolation.

Attempts move through `queued -> running -> accepted`, `queued/running -> timed_out`, or `running -> failed/superseded`. `current_attempt_id` and request revision fence late results. A second attempt can start after the first deadline; if the first remote call later returns, its answer is recorded as discarded and is not shown as accepted. A local timeout does not assert that Nebius stopped inference. GET routes read saved state and do not call AI. Repeating an interpret POST while a non-expired attempt is queued or running returns that same attempt.

The worker and API are separate processes, so restart does not erase queued records. Worker polls persist local deadlines and recover interrupted engineering operations. Acceptance locks the request and checks current attempt, revision, state and deadline. Engineering drafts/checks also fence exact operation ID and patch hash. Local cancellation never proves remote inference stopped. Worker and verifier heartbeats participate in readiness; worker errors trigger bounded backoff. Production still needs operational alerts and an external outbox dispatcher.

A claimed attempt must match the worker's current configured model; AI-off rejects
it without dispatch. The same settings snapshot is passed to the adapter and a
different returned model ID is rejected. A restart must not transform a queued
fixture attempt into an unreserved live call. Fixture attempts are labeled fixture
even if an unused live model ID exists in the developer's environment.

An already accepted attempt's duplicate delivery now records a discarded
duplicate without relabeling its accepted terminal state. The standalone
[real-process fault lab](RELIABILITY_LAB.md) exercises actual worker death before
and after commit, API restart, duplicate/running replay, reaping and late-result
fencing against PostgreSQL. It creates a retained lab schema with the exhausted
counter copied and live cap zero; five explicit defective functions exist only
inside child memory. This is trusted synthetic instrumentation, not a production
service, live model evaluation or security sandbox. No API image imports the lab.

## Engineering boundary and threat model

October 18 adds a mandatory kernel bootstrap before candidate compilation/exec:
deny-all Landlock filesystem rights, no-new-privileges and a default-deny seccomp
allowlist, including non-executable-only memory mappings. Missing support fails
closed, verified by a separate child startup preflight and matching policy pulse.
Bounded selector pipes stop output growth; queue files reject links/FIFOs and use
atomic group-readable writes. Exact policy source is included in the evidence
hash, so old checks are stale. See SECURITY_HARDENING for measured denials and
limits. A Python interpreter is not itself the isolation boundary; the shared
kernel and reused trusted supervisor remain unproven against general escapes.

PDF export cannot be smuggled into the access contract. The engineering route creates a work item. Nemotron mode can draft a complete source replacement for `sample_app/report.py`; fixture mode uses a known synthetic patch. The API validates the path, anchor and size. In the full local Compose stack, API/worker submit a hash-bound job to a separate no-network verifier container, without Docker socket access. A fixed unprivileged driver returns candidate PDF bytes. The trusted parent independently checks seven cases through `pdf_oracle.py`; it never trusts a candidate's printed verdict or exit code alone. Evidence binds patch, source, checks, oracle, driver, execution-policy hash and build revision. The deliberately narrow PDF format and reproduced legacy false pass are detailed in [VERIFIER_LAB](VERIFIER_LAB.md). The model never supplies shell commands. An engineer may accept the exact checked hash for manual release, reject it, or take over. Nothing merges or deploys.

The sidecar has read-only root, bounded temporary storage, no network and SETUID/SETGID/KILL capabilities for child identity and cleanup. CPU, memory, descriptors, output, file size and local deadlines are bounded. A Linux subreaper and PID/start-time checks clean up the tested detached descendant. Remaining threats: the sidecar container is reused, cleanup races and hostile kernel behavior are not generally solved, and Docker is not a certified hostile-code boundary. The development backend instead uses a fresh no-network container, resolving an installed image to an immutable ID per job. Images still need supply-chain review. Use stronger per-job isolation before inviting arbitrary repositories. A test pass is neither a security guarantee nor a release.

The additive [bounded repair workflow](BOUNDED_REPAIR.md) stores the original failed patch, at most two repair attempts, bounded feedback and each candidate's checks. Generation and verification are separate durable claims. The existing budget is reserved before any live dispatch. Request, item, attempt, deadline, generator configuration and verifier provenance fence acceptance. A passing candidate stops for explicit adoption, then the separate existing manual-release decision. Saved evidence and manual paths work with AI off. No successful live model repair has been demonstrated.

[SAFE_CHANGE_BENCHMARK](SAFE_CHANGE_BENCHMARK.md) and [COMPATIBILITY_LAB](COMPATIBILITY_LAB.md) are executable offline experiments, not new production authorization capabilities. The latter uses two owned adapters with v1/v2 schemas, temporary reads and restrict-only redaction. It does not silently add redaction or arbitrary integrations to the live host API.

## Database and deployment choices

Production API/worker now require a non-owner PostgreSQL runtime role without
DDL/TEMP/TRUNCATE/migration-metadata writes or privileged membership. The migrator
uses separate credentials. Only the restored 8082 rehearsal was provisioned and
tested; the original source role and app were not silently changed. Production
also rejects enabled known default-password accounts, uses Secure `__Host-`
cookies, validates canonical HTTPS origin/Host, bounds request streams and trusts
only pinned proxy IPs. The overlay no longer trusts forwarded headers from every
peer. These are tested guards and config, not a live TLS/SSO deployment.

Current schema head is `a14d09c7f602`, adding outbox leases, receipts, token versions
and identity audit after `e8c1a7b4d209`'s repair runs/attempts. Earlier
`d74f109a32be` adds the exact read-candidate index and `c62e84a910f3` observations.
Upgrade preserves the inference reservation history; no historical preview is
backfilled as observed usage. Protected reads capture one authorization instant,
select at most the first current matching grant and invoke shared policy. Role
decisions still check tenant first, and observations fail closed. See
[PERFORMANCE](PERFORMANCE.md) for bounded local measurements. API/worker run as
UID10001 with read-only root. `compose.production.yaml` adds TLS configuration,
but public hosting has not been performed. See [DEPLOYMENT](DEPLOYMENT.md).

October 14 adds an explicit tenant-selected outbox dispatcher. It commits a lease
before sending, fences destination/late acknowledgement, caps attempts and uses
consumer deduplication. Default receipts are local; configured HTTP receivers must
implement durable matching acknowledgements. Delivery is at least once, never
exactly-once remote effects. Account offboarding removes sessions, advances token
version and records a tenant-local identity event. Re-enabling cannot revive old
sessions, but does not revoke otherwise valid grant records. The operations API
reports local signals without sending alerts. See [release scope](SOURCE_RELEASE.md)
for implemented recovery tools, observed SQLite restore and pending PostgreSQL execution.

Alembic revision `bd01c3fe60ce` creates the core schema, and `f4a2d9b71c30` adds a durable global inference reservation counter. Run `alembic upgrade head` before seeding or starting an environment. PostgreSQL is the intended durable store; SQLite is a local learning convenience and has different concurrency behavior. The code does not auto-create tables at API startup. The app and worker must point to the same database and use the same configured model mode. Live mode reserves one counter slot before each inference or patch-draft call and refuses work after `OWNSTACK_MAX_LIVE_CALLS`; this is a conservative call limit, not a dollar budget or a provider bill.

The product is best submitted to Best Apps and Agents unless the coding-agent journey is demonstrably stronger under live inference and independent checks. Category choice must follow running evidence, not judge prestige.

## Historical demonstration boundary

`GET /v1/demo-evidence` requires an authenticated session but presents only
allowlisted public synthetic artifacts included in source, identically for all
roles. It never queries cross-tenant database rows or invokes inference. The
historical timestamp, failed model patch, explicitly assisted manual correction,
small denominators and artifact hashes stay visible. Missing/malformed files
return 503. This endpoint is not the current host state, a replay, tenant-private
proof export or signed attestation. Only the five explicit JSON files enter the
API image; environment files and private runtime records remain excluded.

Submission preflight is an offline file/narrative inventory. External URLs and
confirmations are owner assertions, not network-verified availability or legal
eligibility. The media renderer uses actual screenshots and local system speech,
rejects durations at/over 180 seconds, and never uploads. The submission bundler
verifies the source inventory and includes only the source ZIP, final MP4/VTT,
publication checklist and bundle hashes. None of these paths reserves inference.
