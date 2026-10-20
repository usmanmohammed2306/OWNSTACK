# Judge test build: five-minute inspection, no inference spend

This is a working local Python/React/PostgreSQL reference with synthetic tenants.
The saved October 7 Nebius calls are genuine historical evidence. This walkthrough
runs AI-off; it does not pretend to replay those calls. Public build/repository
links are pending owner publication. No paid account, API key, local Python or
Node install is needed for the container path. Docker Compose is required.

## Start from the published source or extracted test-build ZIP

In the directory containing `compose.full.yaml`:

```bash
OWNSTACK_AI_MODE=off OWNSTACK_MAX_LIVE_CALLS=0 docker compose -f compose.full.yaml up -d --build
curl --fail http://127.0.0.1:8080/health/ready
```

Expected readiness: `{"status":"ready","ai_mode":"off"}`. First build downloads
dependencies and container images. Open `http://127.0.0.1:8080`. Local synthetic
password: `demo-only-pass`. Never expose these default credentials publicly.
The supplied original workspace retains its exhausted 10/10 counter. A new
judge installation must stay AI-off with cap zero; it is not a renewed allowance.

## Inspect historical live proof first

Sign in as `atlas-admin`; **Overview & proof** opens first. Inspect the dated
Nano access outcome, rejected Super patch, distinct manual correction hash,
tiny model comparison and original file hashes. Expand the check outputs.
These are public synthetic source artifacts, not current tenant data. A file
digest is not authentication or signed attestation. Inspect the running request
records separately in Change journey and Evidence ledger.

## Exercise the actual host boundary without AI

1. As `atlas-engineer`, save a Temporary access request for `atlas-contractor`
   on `atlas-project`, expiring within seven days. In the selected request,
   choose **Continue without AI as engineer**. Expected: ready configure proposal.
2. Switch to `atlas-admin`. Select that request, **Run host preview**. Expected:
   denied before, allowed after, 24 comparisons and zero unexpected deltas.
   Choose **Review & approve**, inspect the exact scope and hash, acknowledge it,
   then **Approve exact proposal**. The server rejects changed or stale previews.
3. Switch to `atlas-contractor`, **Test protected read**. Expected: Atlas document
   titles. The actual host API, not React state, makes this decision.
4. As `nova-contractor`, the same protected-read button checks Nova and remains
   denied. A direct cross-tenant Atlas ID is 404; this negative is exercised by
   the HTTP smoke and API tests, not by pretending the Nova button targets Atlas.
5. As `atlas-admin`, revoke the active variation. Switch to `atlas-contractor`
   and read again: expected 403. Refresh does not restore revoked permission.
6. As `atlas-admin`, Evidence ledger, select this request and export its proof.
   Offline verification with Python: `python scripts/verify_proof.py <download.json>`.
   Expected digest verifies; it does not certify security or origin.

## Exercise the engineering boundary

As `atlas-engineer`, select **New code feature**, save a PDF-export request, then
**Continue without AI as engineer**. Open its Engineer cockpit work item. Choose
**Write patch without AI**. Copy the complete reference from
`docs/evidence/pdf-agent-manual-correction.py` into the replacement-source editor,
save and **Run isolated checks**. Expected: checks pass, with exact patch/source/
check hashes. This is an explicitly AI-assisted reference correction, not a new
Nemotron generation. An untouched placeholder fails checks.

Inspect the diff and limitations. You may reject or take over. Acceptance is only
a manual-release handoff, not deployment. The verifier has no network and a fixed
command, but is not a certified sandbox for arbitrary hostile repositories.

As `platform-owner`, open Convergence. Repeated needs and grant-attributed API
reads are synthetic counts. Write your rationale and record keep separate,
promote or retire. No code or global policy is automatically promoted.

## Repeatable checks

With the Python dependencies from README installed:

```bash
.venv/bin/pytest --tb=short
.venv/bin/python scripts/smoke_full_stack.py
.venv/bin/python scripts/submission_preflight.py
```

The smoke changes synthetic records, grants then revokes access, checks a fixture
patch and makes zero inference calls. Preflight is read-only and offline.
`--strict` intentionally exits 2 until the external publication gates are filled
and owner-checked. Fixture/mocked tests are not live provider-outage evidence.

Stop services with `docker compose -f compose.full.yaml down`. This preserves
named volumes. Do not use `down -v`, reset the inference ledger, or spend more
credits to make a rehearsal look live. Read `UNPROVEN.md` for release limits.
