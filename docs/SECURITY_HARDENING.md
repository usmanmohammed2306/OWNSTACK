# Kernel-restricted verification and production guards

October 18, 2026, Phoenix. Implemented and exercised locally with AI off. This is
a stronger defense-in-depth boundary, not a production security certificate.
The original 8080 app was not replaced. The hardened rehearsal is on loopback
8082, against the separately restored PostgreSQL fixture.

## What changed

Think of the candidate as a visitor who can pass a paper through a slot, not a
guest with a key to the building. Its job is only to turn supplied text into PDF
bytes. It does not need files, network access, child processes or new programs.

| Boundary | Implementation | Important tradeoff |
| --- | --- | --- |
| Candidate kernel rights | `candidate_sandbox.py` establishes no-new-privileges, a deny-all Landlock filesystem ruleset and a default-deny seccomp syscall allowlist before candidate compilation/execution | Linux x86_64/aarch64 only, Landlock ABI >= 3 and libseccomp required. Unsupported runtime fails closed. Only aarch64/ABI 8 was executed here. |
| Native escape primitives | New file opens, sockets, fork/clone, exec, ptrace, process-memory writes, namespace/policy changes, memfd and executable mmap/mprotect are not allowed | Not Python import filtering. ctypes is still available, but its syscalls remain kernel-restricted. Existing executable mappings and the shared kernel remain. |
| Resource bounds | Unprivileged child, no-network/read-only container, CPU/memory/process/descriptor limits, local deadline and bounded pipe capture | Output no longer grows temporary files; disposable candidate Docker logging is disabled. Shared-supervisor and kernel vulnerabilities are not solved. |
| Startup and readiness | Separate child preflight plus bounded policy heartbeat with matching execution-policy hash; every candidate independently locks down | Missing/stale/malformed policy cannot become ready or passing evidence. A heartbeat is not attestation against a compromised supervisor. |
| Queue | No-follow, single-link regular-file reads; bounded JSON; atomic 0640 outputs in the shared directory group | Prevents tested symlink/hardlink/FIFO and oversized-message cases, not a multi-host authenticated queue. |
| Production ingress | Exact Host and HTTPS scheme, explicit proxy IP trust, bounded streamed bodies/deadlines, no public API schema/docs, security headers | Proxy trust is enforced by Uvicorn/Nginx configuration, not a client-controlled forwarded header. Live TLS was not deployed. |
| Production sessions | Secure, host-only `__Host-` cookies, existing HttpOnly session/CSRF/origin checks, no Domain attribute | Local synthetic cookies retain their old names. Does not add SSO, MFA or password reset. |
| Database blast radius | Separate migrator and DML-only runtime credentials; API/worker startup refuses administrative/schema-create/TEMP/TRUNCATE/migration-write privileges and privileged memberships | Runtime still has application-table DML. This is not PostgreSQL row-level tenant isolation or protection against stolen API credentials. |
| Stored demo accounts | Production startup checks enabled stored hashes for the known `demo-only-pass` seed password | Changing an environment password never rotates existing accounts. This detects the known seed, not every weak password. Real identity provisioning remains a release gate. |

`candidate_payload()` never accepts the trusted host-execution flag. The separate
developer helper permits only exact equality with the repository's known fixture
and labels its result **not sandboxed**. API and bounded-repair acceptance require
the kernel policy ID plus complete current oracle/provenance checks. Existing
checks made under an older execution-policy hash must be rerun, not relabelled.
No candidate supplies a shell command, merges code or deploys a release.

## Actual results

The [final sanitized report](evidence/security-2026-10-18/report-final.json) records source
inventory, private-report digests, exact proof fingerprints and limitations.

- Final regression: **416/416 Python tests**, 27.269 seconds, no skips. JUnit:
  `evidence/security-2026-10-18-tests-r6.xml`. **26/26 frontend tests**, TypeScript,
  Vite, four local images, generated Nginx and production Compose configuration pass.
  The existing optional 559.85 kB / 142.60 kB gzip 3D chunk warning remains.
- **15/15 caught-denial probes on each backend.** Each must assert the expected
  denial and still pass the seven-case PDF oracle. Final reports are
  `security-2026-10-18-docker-r4.json` and `security-2026-10-18-sidecar-r2.json`.
  An unfiltered container control proves file read, Unix socket creation and fork
  were actually possible. Some other denials overlap Docker's existing policy;
  these are not fifteen newly discovered escapes. Unsupported architecture stops
  before candidate execution.
- **13/13 disposable-container and 15/15 sidecar adversarial expectations** match.
  Reports: `security-2026-10-18-verifier-docker-r3.json` and
  `security-2026-10-18-verifier-sidecar-r1.json`. A valid PDF passes; forged output,
  early exit, invalid PDFs, flood, CPU loop and forbidden access fail. Fork is now
  denied before a detached descendant can be created. Earlier cleanup controls
  remain historical evidence, not silently replaced.
- **Six real runtime-role negatives:** DDL, TEMP, TRUNCATE of the restored-only
  recovery probe, migration-metadata update, admin role switch and source-table
  read are denied. Negative statements use rollback-only transactions. Only the
  restored target's grants and a new generated role were changed. The secret is
  in a private 0600 file, not this report or the repository.
- Production no-server lifecycle control rejects stored default-password accounts.
  A rollback-only all-accounts-disabled positive control passes startup under the
  restricted role, then restores exact identity flags. No password was changed,
  no server bound and no production identity system was validated.
- Rollback-only DB controls reject table ownership even after ordinary
  CREATE/TRUNCATE rights are revoked, and reject predefined server-file role
  membership. Temporary role/table disappear on rollback; the actual runtime
  role still passes. See `runtime-role-controls.json`.
- Actual generated Nginx passes six peer/path controls in a network-none namespace.
  Only the pinned original socket peer may assert HTTPS. Spoofed HTTPS from the
  other peer remains HTTP, including after real-IP rewriting. All three API
  locations are checked. `proxy-r1.json` is not a TLS/Caddy/public-network test.
- **Full HTTP demo: 33 checks / 80 requests.** Exact approval and role negatives,
  Atlas/Nova, actual expiry/revoke, rejected then corrected handwritten PDF, actual
  queue exchange and seven PDF cases, exact release artifact, private proofs and
  record-only Convergence pass under the restricted role. AI-off calls return
  unavailable without starting an attempt. No grant remains active.
- **After restarting API, worker, verifier and web: 12 checks / 18 requests** pass;
  all three histories match exactly. Shared PostgreSQL was not restarted. Browser
  inspection shows current checks versus the historical failure and Not deployed.

The source database remains at schema `e8c1a7b4d209`, 31 requests, 213 events and
ten reserved calls. The restored ledger is also ten. Runtime is off/cap zero with
provider credentials empty. Zero new inference, no reset, commit, push or public
deployment. Dates in raw reports use UTC and may show October 19; the rehearsal
occurred October 18 in America/Phoenix.

## Reproduce the current private rehearsal

Run from the reference project root. Do not print resolved Compose configuration,
container environments or the runtime env file. It contains a generated password.
Do not reuse the source database as the rehearsal target.

```bash
.venv/bin/pytest -q
pnpm --dir web test
pnpm --dir web build
.venv/bin/python scripts/run_security_lab.py --output docs/evidence/my-new-security-docker.json
.venv/bin/python scripts/run_verifier_lab.py --output docs/evidence/my-new-verifier-docker.json
```

Docker controls require local Docker permission and the installed `python:3.12-slim`
image. They never run candidate code on the host and do not pull an image. Choose
new evidence paths; tools refuse to overwrite an earlier run. For the current
sidecar, append these arguments to either lab command:

```bash
--backend sidecar --compose-project ownstack-offline-20261018 \
--compose-env-file .private/offline-e2e-2026-10-18.env \
--compose-env-file .private/security-role-2026-10-18-r1/runtime.env \
--compose-overlay compose.rehearsal.yaml
```

The full HTTP harness needs a new private directory and creates synthetic
workflows. It does not request inference:

```bash
OWNSTACK_AI_MODE=off OWNSTACK_MAX_LIVE_CALLS=0 NEBIUS_API_KEY= NEBIUS_MODEL_ID= NEBIUS_PATCH_MODEL_ID= \
  .venv/bin/python scripts/run_offline_demo.py --url http://127.0.0.1:8082 \
  --output .private/my-security-http
```

Restart only the current rehearsal, never the original project:

```bash
docker compose --env-file .private/offline-e2e-2026-10-18.env --env-file .private/security-role-2026-10-18-r1/runtime.env -p ownstack-offline-20261018 -f compose.full.yaml -f compose.rehearsal.yaml restart api worker verifier web
.venv/bin/python scripts/run_offline_demo.py --url http://127.0.0.1:8082 --output .private/my-security-restart --resume .private/my-security-http/report.json
```

Wait for readiness before resume. To stop only these services, use the same
Compose prefix with `stop web api worker verifier`. No database/volume is deleted.
Use engineer login supplied in the local README, Code review, request `faca7f63`.
Current patch `1a58d725bb364063` passes, historical `9ace5b922c1cc69b` fails;
acceptance remains Not deployed. Do not expose these fixture identities publicly.

The restored-role helper intentionally refuses main/remote/live targets. It is
not a general production provisioning tool. Production operators must separately
create a non-owner runtime role, revoke PUBLIC database CREATE/TEMP and schema
CREATE, grant only CONNECT/schema USAGE/application DML/sequence access, exclude
migration metadata writes, and set future-owner default privileges. Verify posture
as the runtime role. Never rotate a shared source database implicitly. The
production overlay requires its separate runtime password and pinned private proxy
addresses; a config-only check is not a deployed or TLS-tested service.

## Preserved failures

The first full pass had 407 tests before the final capture/startup checks. Intermediate
`tests-r2` has 412 passes and a loopback bind PermissionError from the host tool
sandbox. `tests-r3` reruns all 413 with local permission and passes. Additional
proxy, pacing and ownership regressions bring final `tests-r6` to 416 passes.
`docker-r3` and `verifier-docker-r2` similarly record unavailable Docker access,
not successful containment; the explicit current reports above rerun with local
Docker access. Earlier passing policy snapshots remain saved, but predate final
source hashes. One required restored-URL guard regression was caught and fixed.
A queue group-ownership mismatch was corrected before the passing HTTP run:
atomic 0640 files must inherit the shared directory GID, not root's primary group.
An initial container build was also blocked from updating Docker's local builder
metadata; the approved local build then completed. Failures are not erased.

The unpaced final-web HTTP run r2 hit the existing Nginx rate limit during its
second access journey (50 records including failed logout cleanup). That failure
is retained. The functional harness now spaces starts by at least 70 ms, rather
than weakening the limit or retrying mutations. Later r3 and final r4 pass all
80 requests. Earlier `report.json` and HTTP r1 are intermediate snapshots; final
evidence uses the ownership guard and proxy changes described above.

## What still blocks hostile public workloads

Independent threat review and penetration testing; image/SBOM/dependency review;
separate per-job VM or equivalent stronger boundary; realistic parser/kernel
attacks and sustained abuse; clean production identity/secrets/retention; actual
TLS/proxy-path testing; RLS if required; rate/capacity budgets and machine-loss
recovery. The reused supervisor holds trusted files and a shared Linux kernel.
The candidate protocol is deliberately narrow and in-memory: ordinary imports
that open files, native libraries loaded after lockdown, subprocesses and network
features can fail. Do not silently relax the policy to make an arbitrary package
work. This pass does not enable arbitrary repositories or automatic releases.

## Learn one boundary yourself

Prediction: if hostile code catches `PermissionError` from `open('/etc/passwd')`
and then returns a correct PDF, should the check pass? Explain why passing the
PDF oracle alone would not prove the open was denied.

Read `candidate_sandbox.py`, `candidate_driver.py`, `bounded_process.py`,
`verifier_service.py` and `tests/test_security_boundary.py`. Rebuild just a bounded
pipe-capture helper in the separate learning repository, then test normal output,
flood and deadline. Do not execute model-authored code on your host. Next explain
why a Python monkeypatch cannot undo an installed kernel filter, while a kernel
exploit remains outside this claim. No learning day or Git commit is marked done.

Official reading: [Landlock semantics and ABI compatibility](https://cdn.kernel.org/doc/html/latest/userspace-api/landlock.html),
[no-new-privileges](https://cdn.kernel.org/doc/html/latest/userspace-api/no_new_privs.html),
[libseccomp argument comparisons](https://man7.org/linux/man-pages/man3/seccomp_rule_add.3.html),
[PostgreSQL privileges](https://www.postgresql.org/docs/16/ddl-priv.html),
and [Starlette ASGI middleware](https://www.starlette.io/middleware/).
These explain mechanisms, not certification of OwnStack.
