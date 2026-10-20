# Local stack and deployment gate

October 18 security update: read [SECURITY_HARDENING](SECURITY_HARDENING.md) first.
Kernel lockdown is mandatory. Production requires separate least-privileged
runtime DB credentials, stored default-password rejection and pinned private
proxy trust. Only the restored local rehearsal on 8082 was upgraded and tested;
live TLS, production identity and public deployment were not exercised. AI stays
off, cap zero, provider fields empty. The ten-call allowance is exhausted.

The checked-in Compose file is a **local rehearsal**, not a public deployment recipe. It starts PostgreSQL, a migration/seed job, API, attempt worker, Nginx web UI, and a separate verifier sidecar. The verifier has no network, receives only a bounded patch via a shared job volume, executes a fixed test command as UID 65534 with resource limits, and returns a patch-hash-bound result. The API has no Docker socket. This is useful defense in depth, not certified isolation for arbitrary hostile code.

## Reproduce the local journey

From the repository root with Docker Desktop running:

```bash
OWNSTACK_AI_MODE=off docker compose -f compose.full.yaml up -d --build
curl -sS http://127.0.0.1:8080/health/ready
.venv/bin/python scripts/smoke_full_stack.py
docker compose -f compose.full.yaml ps
```

Expected readiness for this safe rehearsal: `{"status":"ready","ai_mode":"off"}`. Expected smoke output includes `enforced_then_revoked`, `isolated`, `checked_not_deployed`, `no-network-verifier-sidecar`, verified proof digests, and `ai_calls: 0`. The script creates synthetic requests and ledger rows, so it is not a read-only check. It uses a new idempotency key on each run. The default web port is loopback only. `docker compose -f compose.full.yaml down` stops the containers but retains the named PostgreSQL and job volumes.

If readiness returns 502 after replacing the API container, rebuild the web image containing the dynamic Docker DNS resolver. If an API request returns 503, check the migration job and `alembic_version`. If patch checks time out, inspect verifier status and logs. A timeout is an unknown execution state, not a test pass. Do not delete volumes just to hide a migration failure.

## Before any shared test build

1. Verify the Token Factory account balance, redemption status, current model ID, JSON-mode support, and price in the signed-in official console. A promo code in an email is not confirmed account credit. Keep the key out of chat, Git, screenshots, and browser code. The local call cap counts reservations, not dollars. Do not enable any top-up or paid resource without specific approval.
2. Set `OWNSTACK_ENV=production`, PostgreSQL, a new 32+ character signing secret, a separate 16+ character identity-provisioning password, `OWNSTACK_AI_MODE=off`, `OWNSTACK_MAX_LIVE_CALLS=0` and empty provider fields. Provision a separate non-owner runtime DB role before API/worker startup. Use a canonical HTTPS origin and explicit trusted proxy IPs. Existing enabled demo accounts must be separately disabled or safely reprovisioned; a new environment password does not rotate their stored hashes. These guards do not make the demo production secure.
3. Cookie sessions, CSRF/origin checks, login rate windows, strict Host/HTTPS/proxy boundaries, HTTPS overlay and nonroot services are implemented. Mandatory kernel candidate isolation and local logical restore now have finite measured controls. Still replace demo identities for real customers, independently review security, strengthen per-job isolation and enforce egress policy. Public testing must contain synthetic data only.
4. Re-run the full test suite, evaluation, fresh-clone setup, container smoke test, browser accessibility walk, cross-tenant negatives, restart and late-result drills. Bind evidence to the exact commit. Do not claim a patch was released merely because checks passed.
5. For hackathon submission, provide a working judge-testable URL, public licensed repository, setup instructions, public video under three minutes, truthful NVIDIA/Nebius usage evidence, feedback, and an explanation of hackathon-period work. Recheck the official [rules](https://nebiusglobalaihackathon.devpost.com/rules) and [resources](https://nebiusglobalaihackathon.devpost.com/resources) before filling the form.

No public cloud deployment, paid resource, model call, or promo-code redemption was performed by the local rehearsal.

The source-only archive has also been extracted and installed against a fresh local PostgreSQL database, followed by the HTTP smoke and concurrency drill. Its first packaging failure and repair are recorded in `JOURNAL.md`. To reproduce a source-only handoff, run `scripts/package_test_build.py --output <new-zip-path>`; it excludes credentials/caches and includes a SHA-256 source inventory. Extract, follow the README, and retain the inventory with your test results. This is not a public download URL or another person's fresh-clone verification.

## TLS deployment bundle, not deployed

Use an approved existing Linux host with Docker Compose, an owned DNS name pointing to it, ports 80/443 open, and sufficient memory for the service images. Token Factory credits are not authorization or funding for a compute host. Do not buy one automatically.

Create an ignored `.env.production` from `.env.production.example` through your secret manager. Generate independent signing secret, migration-owner database password, runtime-role password and identity-provisioning password. Use URL-safe database-password characters because they are embedded in SQLAlchemy DSNs. Never publish passwords or API keys. Set the actual HTTPS Origin/domain, an unused private service subnet and pinned web/edge addresses. Keep AI off, cap zero and provider fields empty: the existing ten-call authorization is exhausted. Do not reset or replace its reservation ledger.

Before API/worker startup, initialize/migrate only the approved target using the
owner credential, then provision a non-owner runtime role through approved database
administration. Revoke PUBLIC database CREATE/TEMP and schema CREATE; grant
runtime CONNECT, schema USAGE, application DML and sequence access, not TRUNCATE
or migration-metadata writes. Configure owner default grants for future tables
and check `runtime_role_safe` as runtime. The restored-fixture helper deliberately
refuses production/main targets. Never rotate a shared source database implicitly.
An absent/unsafe role or stored seed password must fail startup, not cause fallback
to admin credentials. Real identity integration and TLS-path tests remain gates.

After approving the host and cost, the deployment command is:

```bash
docker compose --env-file .env.production -p ownstack-prod -f compose.full.yaml -f compose.production.yaml config --quiet
docker compose --env-file .env.production -p ownstack-prod -f compose.full.yaml -f compose.production.yaml up -d --build
```

Use the separate project name so production does not reuse a local database volume with old credentials. **Do not use a new database to regain the exhausted ten-call allowance.** The current authorization is exhausted everywhere, not per database. Keep any new environment AI-off with cap zero until new explicit authority exists; preserve/transfer the reservation ledger when moving an existing runtime. The examples above describe infrastructure only, not renewed inference permission. Compose's `!reset` requires a recent Compose version. Caddy provisions TLS for the configured domain; the API/database/verifier are not published. Back up PostgreSQL before migrations. Do not run `down -v` on a database you intend to preserve.

Run readiness, the cookie-based smoke and browser journey against the HTTPS domain using `OWNSTACK_SMOKE_URL`, and provide the new demo password through the environment, not argv or public logs. The smoke uses manual proposals, zero model calls, and changes only synthetic data. Then run `scripts/prove_live_workflow.py` only after approved credits, price and key configuration. It reserves at most three calls, stops on failure, stores redacted evidence, revokes its access grant, and does not accept or deploy the proposed code. A laptop or temporary tunnel is not a reliable judging-period deployment.

## Recovery and operating checks

- `/health/live` checks process liveness. `/health/ready` checks schema head plus worker/verifier pulses in the full stack. Readiness does not make a paid inference health call.
- Restart API/worker and verify the same request and accepted proposal remain readable. A queued attempt survives process restart; an expired operation becomes retryable through the worker reaper.
- Observe `X-Request-ID` for unexpected failures. Logs contain exception type rather than secrets or model prompts. Do not expose raw container environment or resolved Compose config.
- Inference outages preserve evidence and permit the engineer's AI-off handoff. Timeout/cancel is local only; retry cannot accept the previous attempt's late result.
- Monitor disk, database backup success, pulse age, 429/502 errors and remaining reservations. The explicit tenant dispatcher and `/v1/operations` local signals are implemented; external receiver/alert configuration and operation remain pending. See OPERATIONS_HANDOFF for fixed acknowledgement, destination/lease fencing and private recovery commands.
- October 9: API/worker/verifier/web/database restart preserved the exact saved request fingerprint, including attempts, approvals, variation, observations, evidence and events, with AI off and counter 10 unchanged. This is restart recovery, not backup/restore or live outage proof. Reproduce with `scripts/check_saved_state.py <smoke-access-request-id>` before restart and `--expected-digest <printed-sha256>` afterward. No interpretation is requested by this script.
- Restore into a separate AI-off test database before claiming backup recoverability. Independent backup/restore and hostile-runner drills remain release gates.

October 14 recovery checkpoint: the actual old SQLite file passed consistent
backup, restored row fingerprint, integrity/foreign-key and independent-write checks.
The private restored copy was migrated to `a14d09c7f602` and serves the loopback
teaching UI with AI off/cap zero. Docker/PostgreSQL tools are absent today, so this
does not replace the intended PostgreSQL stack or establish PostgreSQL restore.
The guarded `scripts/rehearse_postgres_backup.py` requires the existing exhausted
source ledger, official pg_dump/pg_restore and a new private output directory.
It retains a uniquely named restored database and never overwrites/drops one.
