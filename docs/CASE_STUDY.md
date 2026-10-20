# Technical case study, local evidence edition

## Problem and ownership

OwnStack explores safe variation without a permanent code fork. A model may understand a customer request, but it cannot authorize access or release its own patch. The owned synthetic host makes this boundary testable without claiming integration with arbitrary SaaS. Buyer demand remains a separate hypothesis.

## Implemented outcome

The local Atlas journey saves a durable request, derives a bounded proposal, computes preview through host authorization, requires exact admin approval, permits an actual contractor read, denies Nova and denies the read after revoke. Expiry is enforced at read time. Unsupported PDF export opens a single-file engineering work item, exact diff, independent no-network checks and a human manual-release handoff. It never deploys code.

## Hard engineering decisions

PostgreSQL owns persistent status, attempts, idempotency and evidence. Row locks serialize attempt transitions and approval; operation IDs and deadlines fence late drafts/checks. A repeated active request shares work; a page refresh reads the saved proposal. Locally canceled/time-expired inference is not reported as remotely stopped. AI-off handoff remains available without surrendering the host's policy boundary.

The browser uses hashed, revocable cookie sessions and CSRF/origin checks. Production startup guards reject local credentials and fixture mode. Full-stack API/worker run without root or writable root filesystems. The verifier receives bounded source only, no network or application secrets, and executes a fixed test command as an unprivileged child. Its reused sidecar remains experimental, not sufficient isolation for arbitrary hostile repositories.

Acceptance binds to patch hash plus current source/test/build provenance. Model interpretation evidence records raw proposed route separately from policy-accepted route. A host override is not counted as model accuracy. Convergence exposes counts rather than customer request content, and promotion is record-only human judgment.

## Evidence and failures

See `VALIDATION.md` for exact commands and current counts. The PostgreSQL HTTP smoke and four-way concurrent duplicate drill passed locally. The offline fixture is only 5/10 on its ten development cases, versus 4/10 for a kind-only baseline. In a separate tiny live holdout, Nano and Super each matched 2/2 routes versus baseline 1/2. Nano mean latency was 1,179 ms and Super 1,857.5 ms. This is not a robust model benchmark or commercial baseline.

Container tests exposed source-path assumptions, route/function collision, stale upstream DNS and a dropped-capability volume initialization failure. Repairs were verified through the real HTTP stack rather than declared from unit tests alone. The prior failing observations remain in the learning journal.

Live patch experiments were negative: Nano 0/3 usable drafts, Super 0/1 passing patches. Super's syntax error triggered independent failure, exposing a missing manual-correction state transition. The repaired path preserves the original model proposal and checks. An explicitly coding-assistant-authored manual correction passes four independent checks without further inference, not a model-only success. The 49 regressions and web build pass; review/release remain pending.

October 9 extended the reference to 61 passing tests. The host now records real
authorization observations separately from previews, attributed to the saved
variation. A failed observation write prevents protected data return. Convergence
shows those counts without leaking tenant details and requires an owner rationale
in Studio. Tenant-private evidence exports use a consistent PostgreSQL read
snapshot and a verifiable content digest, without claiming a signature. A queued
fixture cannot become a paid live call after worker configuration changes.
The full AI-off HTTP journey passed and a full service/database restart preserved
the same saved workflow fingerprint. The existing ten-call counter stayed at ten.

## Limits and next experiment

Real NVIDIA runtime proof exists for the synthetic Atlas access and feature interpretations, with actual access/revoke observations. A zero-inference HTTP drill also observed an eight-second grant expire before revoke and the call cap refuse dispatch. Model patches failed; manual recovery is checked but not released. No public hosting, customer pilot, independent security review or final submission exists yet. A technical check is not production certification. Next: use an approved hosting target, rehearse with an independent user, then compare the same actual request with that team's manual workflow. Publish only measured claims. The user's future commits should distinguish the provided reference from their independently reconstructed work.
