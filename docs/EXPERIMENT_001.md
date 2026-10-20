# Experiment 001: safe Atlas variation

Hypothesis: one legitimate temporary access request can produce exactly one intended host-permission delta without altering Nova or creating a code fork. This is a technical hypothesis, not buyer validation.

Observed local experiment on October 7: cookie-authenticated PostgreSQL/Nginx/API smoke created a manual proposal, recomputed preview, approved its exact hash, read Atlas as contractor, denied Nova, revoked the grant and denied the next contractor read. It also submitted a reference PDF fixture patch to the separate no-network verifier, passed independent checks, exercised the synthetic manual-release decision and retrieved the exact artifact with `not_deployed`. Zero AI calls, not an independent human review.

Four-way simultaneous request and interpretation drill produced one request and one attempt. Unit tests cover expiry, stale preview/hash, replay, invalid model output, AI-off handoff, late attempt 1 after attempt 2, local cancel, sessions and operation recovery. See `VALIDATION.md` for repeatable commands.

The subsequent `scripts/prove_live_workflow.py` run made two accepted Nano interpretations through Token Factory. Access interpretation took 1,357 ms, feature interpretation 1,251 ms. The live access path recomputed preview, approved its exact hash, allowed the Atlas contractor read, denied Nova, revoked and denied the next read. The first PDF draft failed; a later explicit retry recorded `MODEL_OUTPUT_TRUNCATED`. [Original live evidence](evidence/live-workflow.json) and [retry evidence](evidence/live-patch-retry.json) preserve these failures. No generated code was released.

Limitations: synthetic tenants, finite replay, local deployment and no real customer baseline. A successful interpretation is not proof of patch quality, demand or production security.

Later actual Super code failed syntax checks. Agent-authored manual recovery preserved the failed diff and passed four checks, with no human release decision. The separate eight-second manual-grant HTTP drill observed denied access after expiry before revoke, and the exhausted budget rejected interpretation without creating an attempt or spending another reservation. See [recovery](evidence/manual-recovery.json) and [expiry/cap](evidence/expiry-and-cap.json).
