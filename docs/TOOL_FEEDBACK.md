# First-hand Nebius / NVIDIA tool feedback draft

Prepared October 9 for owner review and the submission's tool-feedback field.
These are developer observations from saved October 7 artifacts, not customer
interviews, vendor endorsements, support reports or feedback already sent.

## What worked

Token Factory's server-side chat-completions path integrated with a small Python
adapter. Returned model/usage fields let us bind interpretations to durable
attempts and estimate returned-usage cost. Nano's accepted access interpretation
took 1,357 ms and the PDF route 1,251 ms in our synthetic app. The resulting access
proposal led to real host authorization, not just generated prose.

## Where the boundary mattered

Three Nano PDF draft attempts produced no usable patch. Two were explicitly
rejected as `MODEL_OUTPUT_TRUNCATED`; the first preserved only a ValueError, so
we cannot diagnose it more precisely. Super generated a real patch in 20,649 ms,
but the separate verifier caught an unterminated triple-quoted string. We cannot
infer that this is a provider bug, universal model behavior or a benchmark result.
See `evidence/live-patch-super.json` for the exact failed output and check hashes.

## Improvements we would value

- More task-oriented examples for bounded code generation: output schema,
  finish reason, truncation detection and a no-execution-by-model default.
- Clear guidance for timeouts and client cancellation: local cancellation does
  not establish that remote inference stopped or was not billed.
- Usage/billing reconciliation for unsuccessful or truncated calls. Our
  $0.00402432 known returned-usage estimate excludes three failed Nano drafts;
  it is not the account's total bill.
- A concise model-selection guide emphasizing measured task outcomes rather
  than always selecting the largest model. Our two-case comparison was useful
  as a smoke test, not robust evidence of superiority.

## How we responded in OwnStack

We cap and atomically reserve live calls before dispatch, keep failure evidence,
reject stale/late attempts, display honest status and support manual recovery.
The exhausted ten-call allowance is preserved. Reading saved evidence or using
the manual path spends no inference credits. We use neither Tavily nor Nebius
AI Cloud in this build, so we provide no invented first-hand feedback on them.

Independent customer validation remains separate and uncollected. See FEEDBACK.
