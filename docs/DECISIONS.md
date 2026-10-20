# Architecture decisions

## ADR 029: Untrusted computation gets kernel rights, not Python promises

October 18. The owned PDF transform needs memory and pipes, not files, sockets,
new processes or executable mappings. Establish no-new-privileges, deny-all
Landlock and a seccomp allowlist before candidate execution; unsupported Linux
ABIs/libraries fail closed. Keep the external oracle outside that interpreter.
Hash the policy and queue implementation into current evidence, preflight in a
separate child and reject stale profiles. Use bounded pipes rather than growing
temporary output files. Tradeoff: intentionally incompatible with arbitrary
imports/packages; reused supervisor/shared kernel remain, not certified isolation.
Fifteen caught-denial probes per backend pass with a valid PDF; independent
review and stronger per-job boundaries remain release gates. SECURITY_HARDENING.

## ADR 030: Production must refuse inherited development authority

October 18. Separate migration-owner and DML runtime credentials; fail startup on
administrative DB rights and enabled known seed-password accounts. Changing config
does not rotate stored identities. Trust exact pinned proxies, canonical Host and
ASGI HTTPS, never a browser's forwarded header. Bound body streams before routes;
use host-only Secure cookies in production. Verify grants only on the restored
local fixture, with rollback-only privilege negatives and lifecycle controls.
Tradeoff: operator identity/role provisioning and real TLS testing are still
required; the local fixture remains convenient, not safe for public exposure.

## ADR 027: Proof snapshots must retain unsuccessful repair branches

October 18: add full run/attempt history to the tenant-private v1 proof, not only
events and the selected patch. Query through the tenant/request-scoped parent in
one snapshot. Allowlist configuration fields; include repairs in the shared restart
fingerprint. Cost: larger private exports with untrusted code/feedback and a changed
comparison field set. Old envelopes verify, but old fingerprints need a new baseline.
Digests do not establish authenticity; no model result becomes a claimed human result.

## ADR 028: Recovery uses a new target, never a renewed allowance

October 18: use official tools in the owned local PostgreSQL container, hold one
read-only snapshot for fingerprint/dump, restore only into a new generated target
and compare all public rows/columns and the exhausted ledger. Require AI off,
cap zero, empty credentials and a local Docker endpoint. Separate network/queue/
web port avoid app collisions. Preserve failed dumps/targets; never clean, drop or
overwrite. Cost: retained private storage and a shared local database process,
not production failover or complete cluster recovery. Source workflows are not migrated.

## ADR 026: Graph execution must not become a second recovery authority

October 18: use LangGraph for bounded repair phase routing, parallel artifact and
snapshot checks, and explicit evidence joins. Keep committed SQL claims/results
as the sole durable continuation; no native application checkpoint or interrupt.
The human gate remains an authenticated API decision. This avoids checkpoint
replay silently duplicating uncertain paid side effects. The native interrupt
teaching control reproduces the documented repeated-side-effect behavior and its
separate-node correction. Freeze graph source/version per run and disable hosted
tracing. Cost: additional dependencies, source-upgrade handoff, and measured local
orchestration overhead. The shared-operations sequential baseline matches all
authored outcomes, so neither safety superiority nor model-quality improvement
is claimed. See LANGGRAPH for controls, actual results and unproven boundaries.

## ADR 023: Outbox replay belongs to a deduplicating consumer

October 14: commit a lease before delivery, freeze the operator destination, limit
claims and fence late acknowledgements. A consumer acknowledges the exact event
and envelope hash only after storing its unique receipt. A lost sender acknowledgement
can still cause replay; delivery is at least once. Default receipts are local.
External endpoints are operator configuration, never model/request data, and have
not been contacted. Cost: retries/dead letters need operational review and a
receiver must implement its own idempotency. No exactly-once remote effect claim.

## ADR 024: Re-enabling an account must not revive a login

October 14: offboarding removes opaque sessions and advances a durable token
version, including local teaching bearer tokens. Re-enable also advances the
version and requires fresh login. Tenant admins cannot use this narrow route for
administrator/platform changes. Identity audit commits with the action; timestamps
carry UTC. Existing grants remain a separate lifecycle: permanent access removal
also requires grant revocation. Cost: no identity-provider, provisioning, MFA or
password-reset integration is implied. PostgreSQL login/offboarding race is designed
with row locks but not separately exercised today.

## ADR 025: Learning cadence does not delay a complete submission

October 19 follow-up: the user explicitly restarted Day 1 today. Shift the active
calendar and existing reminder to October 19 through January 16, retain the unused
October 14 plan in history, and leave the learner stub and completion ledger alone.
An elapsed date is never evidence of an implemented feature. Publication remains
independent of the reconstruction schedule.

October 14: keep the finished local reference separate from the user-selected
ninety-day rebuild. Generate one short daily lesson from a validated calendar,
read progress without marking work complete and leave commit/push to the user.
Retain earlier calendars and AI-assisted provenance. Prepare complete publication
before the hackathon deadline, independent of learner pacing. Cost: two clearly
named workspaces and genuine per-day implementation/review, not cosmetic graph edits.

## ADR 001: Own the host app

Use an owned Python project-workspace fixture rather than claiming safe adaptation of arbitrary external SaaS. This makes server-side enforcement and negative tests inspectable. Cost: it is not proof of general integration.

## ADR 002: Model proposes, policy decides

Nemotron classifies and drafts, but fixed server rules determine allowed effect. This prevents a prompt from broadening a read-only contract. Cost: limited capability surface.

## ADR 003: Bind approval to evidence

Version the contract, hash proposals and previews, recheck before approval, and bind patch checks to the exact patch hash. This exposes stale data rather than silently applying a changed effect. Cost: conflicts require a new attempt.

## ADR 004: Durable attempts, honest timeout

Persist attempts and fence late results with request revision and current attempt ID. A timeout is a local deadline, not a claim that the provider stopped computing. Cost: remote work can continue and be billed.

## ADR 005: No model-authored commands or automatic release

The verifier runs one fixed command against one allowlisted file. An engineer records a human choice, but no merge or deployment occurs. Cost: this is less automated than a general coding agent, but its evidence boundary is clear.

## ADR 006: Product decisions stay human

The Convergence Queue exposes an aggregate repeated need to a product owner and records a decision. It never promotes a customer-specific variation automatically. Cost: product judgment remains manual and demand is unvalidated.

## ADR 007: Revocable cookie sessions

Browser identity uses opaque HttpOnly session cookies with hashed server records, expiry, enabled-account checks and explicit logout. Mutations require CSRF and permitted Origin. Production requires HTTPS/Secure and disables local bearer tokens. Cost: real provisioning/MFA/identity-provider integration still needs work.

## ADR 008: Fence interrupted engineering operations

Draft/check claims commit an operation ID and deadline before external work. Only that still-current operation may save its exact result. A watchdog recovers interrupted work; takeover clears the claim. Cost: remote execution/inference cancellation remains unknown.

## ADR 009: Release handoff needs current provenance

Passing checks bind source, test suite, patch and configured build revision. Human acceptance and artifact download reject mismatched provenance. Cost: a new build or check definition requires a new check; an uncommitted build is explicitly labeled and cannot be claimed as commit-bound evidence.

## ADR 010: Host owns patch anchors, failures remain evidence

The live model returns a replacement string only. The host owns the allowlisted path and source snapshot. Do not repair invalid output silently. A failed check can be corrected through the manual engineer path, retaining the superseded proposal and its hash/evidence. The live Super syntax failure remains a failed model result even after an agent-authored correction passes. Cost: fewer autonomous successes, more explicit review, and no claim that a larger model is inherently safer. Interpretation and coding model IDs may differ only through explicit configuration.

## ADR 011: Measure the boundary, not the preview

October 9: record the pure host decision immediately before returning protected
data. Attribute contractor grants to the saved variation, not to a model claim or
approval. Fail closed on observation persistence failure. Keep role reads, denied
checks and previews out of granted-use counts. Cross-tenant IDs disclose neither
objects nor observations. Cost: protected reads now require a database write;
retention/partitioning and load budgets need production design. Counts include
retries and cannot establish demand or completed delivery.

## ADR 012: Export reproducible evidence without attestation claims

October 9: export tenant-scoped immutable history and current workflow state from
a consistent database read snapshot. Include source hashes at export and a
canonical content digest, with an offline verifier. Do not include authentication
records or document bodies. Cost: sensitive request text/code still requires
review before sharing, digest authenticity is not established, and current hashes
cannot retroactively bind earlier executions to a Git commit.

## ADR 013: Fence provider configuration at worker dispatch

October 9: compare the claimed attempt's model with one captured runtime settings
snapshot before calling the adapter. Off or mismatched configuration fails the
attempt while preserving its evidence and budget. Reject a mismatched returned
model ID. Cost: changing models requires a fresh explicit attempt instead of
silently rerouting queued work. Reservations are not refunded automatically.

## ADR 014: A judge demo must distinguish historical proof from current state

October 9: show saved public synthetic live artifacts through a read-only,
authenticated, allowlisted endpoint. Never replay a model response as new live
inference, query another tenant's private records, or hide the rejected patch.
Bundle a disclosed edited actual-screen video and manual AI-off test build while
the ten-call allowance remains exhausted. Cost: live interaction with a provider
cannot be demonstrated afresh without new approval. Offline submission checks
must continue failing external readiness until real URLs and owner confirmations
exist. A source ZIP or local MP4 is useful preparation, not public submission.

## ADR 015: Make evidence inspectable without inventing authority

October 9: add an exact-scope approval review, native keyboard navigation,
request-attributed evidence stages, expiry-aware history and line-by-line patch
review. Pure presentation derivations have independent frontend tests. Check
results only summarize the matching patch hash; conflicting records remain mixed.
Do not guess latest from unordered evidence. The approval acknowledgement is a UX
guard only; all existing server-side role/hash/version/snapshot fences remain.
Architecture illustration is not live telemetry, device expiry is not host time,
and loaded observations are a bounded window. Cost: another human review step and
explicit limits rather than an apparently autonomous control room. No new model,
backend schema, paid resource or release authority is introduced.

## ADR 016: Reduce history loading, not authorization freshness

October 10: push exact tenant/project/viewer/state/time predicates into SQL and
return the first valid grant under stable ID ordering. Skip grant lookup for role
paths, but keep the shared policy's tenant-first decision. Add an equality-first,
expiry-range composite index. Use one authorization instant for selection, policy
and observation; no TTL permission cache, model call or async evidence shortcut.
Cost: SQL predicates duplicate part of the pure policy and require differential
tests whenever contracts change. The index adds unmeasured write/storage cost,
and synchronous creation is not proven zero-downtime. Small one-grant reads can
be slightly slower. Return cardinality is bounded, not all database work.
Local paired PostgreSQL results and retained noisy runs are in PERFORMANCE.
No production throughput, memory RSS, certified isolation or security guarantee.

## ADR 017: Test process death and test the oracles

October 10: use a standalone PostgreSQL-schema lab with real HTTP/API/worker
processes and SIGKILL checkpoints around actual transactions. Substitute only a
clearly synthetic provider, checkpoint instrumentation and explicit in-memory
defective baselines. Assert saved state and event/outbox parity; prove the checks
detect five specific removed guards. Keep failed runs, traces and lab schemas.
Preserve accepted terminal history on duplicate result delivery, a real defect
found during the audit. Copy the exhausted main reservation counter, live cap
zero, empty credentials, no alternate allowance or remote cancellation claim.
Cost: local schema growth, test startup time and a finite declared failure matrix.
The socket hook/schema namespace are not security isolation, shortened-deadline
recovery is not an SLA, and metadata setup is not a migration/backup rehearsal.
No source mutation, public deployment or model inference occurs in this lab.

## ADR 018: Optional physical illustration, never runtime authority

October 12: use a lazy-loaded Three.js WebGL2 renderer for the requested cinematic
architecture explorer. Physical lighting and geometry replace CSS-only planes;
task controls remain ordinary React/HTML. The scene receives only local display
options, never API records or credentials. No decorative state may claim a grant,
observation or release. A native-button diagram remains on graphics failure or
explicit Simple view. Pause/reduced-motion/visibility bound rendering, and unmount
disposes resources. Cost: another 147.54 kB gzip chunk plus unmeasured GPU/battery
work. Preserve the build warning; do not hide this behind a speed claim. Browser
checks and pure math tests are not device/accessibility certification. No new
inference, backend permission, hosting resource or publication is introduced.

## ADR 019: Cinematic geometry must explain scoped variation

October 12: replace abstract layers with one shared application, separate Atlas
and Nova modules, an explicit human gate and an engineering branch. Use a pure
eight-state example model shared by HTML and WebGL. Access preview is not an
active path; only the illustrated access step opens Atlas. PDF always routes to
engineering, never to permission changes or deployment. Nova and the shared-app
count remain invariant. Keep example labels distinct from loaded runtime counts.
Cost: the renderer still adds a substantial optional bundle and unmeasured GPU
work. Small engraved 3D labels are secondary to readable HTML, not a replacement.
Local browser QA and display tests do not prove host policy or user comprehension.
No backend behavior, model budget, release authority or public state changes.

## ADR 020: Candidate output is evidence input, not a verdict

October 13: replace exit-code-only PDF checks with a trusted parent oracle.
The legacy early-exit control reproduced a false pass. The candidate interpreter
now emits bytes, while a separate authority checks the narrow PDF subset and
complete seven-case evidence. Bind the execution-policy source along with the
patch/oracle/driver/build. Preserve old evidence but require re-verification for
new acceptance. Sidecar subreaper cleanup and CAP_KILL address the tested detached
child; container reuse is still experimental. Prefer rejecting a valid unsupported
PDF to accepting output we cannot independently inspect. No general PDF or sandbox
certification follows from these finite tests.

## ADR 021: Bounded repair keeps the failed original until adoption

October 13: allow at most two durable repair attempts, using the existing budget
reservation path and separate generation/verification claims. Freeze generator
source and decoding configuration as well as verifier provenance. A post-claim
crash can consume a reservation without a dispatch; never re-send that claim.
Exact current-attempt/deadline/request/item checks discard late results. A passed
candidate waits for explicit human adoption and then a separate release decision.
No silent deployment. Interpretation and repair both receive a worker cycle so
one queue cannot short-circuit the other. Main runtime remains AI-off.

## ADR 022: Experimental breadth must not impersonate production features

October 13: keep the frozen proposal benchmark and two-host compatibility lab
separate from live authorization. The benchmark preserves raw model versus
host-corrected results and currently evaluates only synthetic baselines. The
compatibility lab tests native schemas, redaction and version fencing, but does
not enable redaction in the live host API. Its shared-feature-flag comparator ties
OwnStack on selected effects and adapter edits. Preserve that negative commercial
finding, eight parser errors and every earlier experiment instead of tuning away
the evidence. Independent case review, users and renewed live-call approval are
the next gates, not more unvalidated features.
