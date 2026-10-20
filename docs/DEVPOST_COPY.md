# OwnStack: copy-ready submission draft

Not submitted. Adapt to the actual form after owner eligibility/terms review.
Do not insert nonexistent URLs. Use `submission_manifest.json` for real links.

## Name and short pitch

OwnStack

Customer-specific software changes without permanent forks: Nemotron proposes,
the host enforces, humans approve, and independent evidence stays inspectable.

## Inspiration

One customer's legitimate exception can become every engineer's permanent burden.
Our hypothesis is that B2B teams need a middle ground between rejecting requests,
maintaining forks and giving AI unrestricted control. OwnStack makes the boundary
explicit: narrow, temporary variations are governed by a versioned contract;
new behavior requires engineering. Buyer demand is still unvalidated.

## What it does

An admin asks for contractor read-only access to Project Atlas until Friday.
Nemotron interprets intent through a server-side Nebius Token Factory call.
The host computes a preview using its own authorization policy. An authenticated
admin approves the exact proposal; protected reads enforce tenant, project,
expiry and revoke. Nova remains separate. Saved attempts, version fences and
idempotency prevent repeated clicks or late model responses from silently
overwriting the accepted result.

PDF export is engineering, not disguised configuration. The Engineer Cockpit
shows the real request, exact bounded diff, independently executed checks,
failed history and AI-off takeover. Humans retain release authority. The
Convergence Queue records repeated needs and actual variation-attributed host
reads so a product owner can promote, keep separate or retire a variation.
It never automatically changes the shared product. Tenant-private proof exports
make decisions/check history inspectable offline.

## How we built it / built with

Python, FastAPI, React, TypeScript, PostgreSQL, SQLAlchemy, Alembic, Docker Compose,
Nginx, pytest, NVIDIA Nemotron and Nebius Token Factory. The model cannot execute
arbitrary shell commands or grant access. The host owns policy, preview and
approval. A separate no-network verifier executes a fixed check command against
the owned single-file sample. This is defense in depth, not certified hostile-code
isolation. No silent merge or deployment is implemented.

## NVIDIA and Nebius contribution

On October 7, `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` made two accepted runtime
interpretations: the access path took 1,357 ms; PDF routing took 1,251 ms. The
access proposal led to an actual approved host grant, Atlas read, Nova denial
and revoke. `nvidia/nemotron-3-super-120b-a12b` produced a real PDF patch that
failed independent syntax checks. A separate coding-assistant-authored manual
correction passed four fixture checks. We preserve both outcomes and do not
claim model-only patch success.

A predeclared two-case-per-model comparison matched 2/2 routes for Nano and
2/2 for Super versus 1/2 for a kind-only baseline. Mean latencies were 1,179 ms
and 1,857.5 ms respectively. This tiny synthetic comparison cannot establish
general superiority. Ten reservations, including failures, exhausted the
approved allowance. Current demo is AI-off; dated live evidence remains visible.
No Nebius AI Cloud/Serverless deployment is claimed. See NVIDIA_NEBIUS_USAGE.

## Challenges and what we learned

Confident output is not verified behavior. Nano produced no usable PDF draft
in three attempts; two were explicitly truncated. Super's longer patch still
failed syntax checks. The failure revealed that an AI-off manual correction
must be a first-class path, preserve the rejected patch, and bind new checks
to the new hash. Container path, volume ownership and service DNS failures
were repaired and retested. Production safety is not inferred from local tests.

## Accomplishments

One real runtime interpretation led to a bounded end-to-end host outcome.
Direct cross-tenant negatives, exact approval, expiry/revoke, saved refresh,
duplicate/retry fences, failed-patch recovery and PostgreSQL restart evidence
are reproducible locally. Proof exports distinguish predicted effects from
actual host observations. The build remains useful with inference disabled.
See CAREER_EVIDENCE for dated commands, denominators and limits.

## What's next

Observe B2B engineers doing the task against their existing manual/feature-flag
process. Measure time, touches, errors and recurring variations. Harden identity
provisioning, per-job isolation, backup recovery and deployment controls before
real customer data. Stop or narrow the product if a simpler baseline wins.

## Significant work and ownership disclosure

The owned Python/React product was implemented and tested during October 2026.
It is distinct from the earlier deterministic Studio in the separate Relief
workspace. Do not claim every file was personally coded or independently
reconstructed: the reference implementation and manual correction were
AI-assisted/agent-authored. Usman supplied the product thesis, constraints and
learning charter, approved bounded runtime use and configured credentials.
Verify exact dates/commit SHA after owner publication. No fabricated daily Git
history, customer adoption, endorsements, employment promises or win is claimed.

## Links to fill in the actual form

Public MIT repository; downloadable test build or hosted working app; public
YouTube video strictly under three minutes; tool feedback from TOOL_FEEDBACK;
usage/evidence links. Keep access free through December 15 judging close.

Track: **Best Apps and Agents**. The working bounded application and honest
failure recovery are stronger evidence than a general autonomous coding-agent
claim. The four equal criteria reward technical implementation, coherent design,
specific impact and useful novelty. Do not predict individual judges' votes or
infer hiring needs from titles. LinkedIn profiles/jobs were not audited here.

Official sources rechecked October 9: [rules](https://nebiusglobalaihackathon.devpost.com/rules),
[resources](https://nebiusglobalaihackathon.devpost.com/resources),
[Token Factory quickstart](https://docs.tokenfactory.nebius.com/quickstart).
