# Cross-host variation compatibility lab

This is an executable **offline experiment**, separate from production
authorization. Two owned synthetic applications use the same narrow policy model
and different native schemas. No database, live inference, deployment, customer
interview or independent human approval is performed by this lab.

The question is deliberately bounded: can a host schema change preserve a
customer-specific, temporary effect, reject a declared semantic mismatch, and
selectively remove one variation without removing another?

## What is implemented

| Boundary | Working implementation | Deliberate limitation |
| --- | --- | --- |
| Host 1 | Project-document records become nested document envelopes in v2 | Owned synthetic records, not an external SaaS integration |
| Host 2 | Integer work-order keys, company-owned boards and nested technician/requester data become public/restricted tuples in v2 | Different data model, still an agent-authored fixture |
| Shared read contract | Exact tenant, host, workspace and subject; contractor read; maximum seven days | No writes, exports, wildcard scopes or general policies |
| Second contract | Remove declared sensitive fields from an otherwise authorized response | Synthetic confidentiality need, not a discovered customer requirement; cannot grant access |
| Overlap | Redactions compose by union; overlapping grants in the same scope are rejected | Explicitly chooses safety and review over maximum flexibility |
| Approval | Immutable state and exact contract/proposal/state digests | Fixture principals, not identity infrastructure or cryptographic signatures |
| Upgrade | Manifest compatibility, normalized-data parity, impact matrix and exact approved plan with five-minute validity | Trusted semantic declarations and finite records, not arbitrary code-equivalence proof |
| Rollback | Revoke one variation ID, retaining the others and all history | In-memory lab state, not a production migration or durable audit service |

Implementation: `src/ownstack/compatibility.py`,
`sample_apps_compat/adapters.py`, `sample_apps_compat/baselines.py`,
`scripts/run_compatibility_lab.py`, and `tests/test_compatibility.py`.
Production `policy.py`, host authorization routes and database schema are not
replaced or extended by this experiment.

## Observed checkpoint: October 12, 2026

The final targeted run passed **42 tests** in 0.18 seconds, with the existing
Starlette/httpx deprecation warning. The executable
[r2 report](evidence/compatibility-2026-10-12-r2/report.json) passes ten positive
invariants, detects all six specified defects, and records twenty matching
manual-feature-flag effects. Both native-schema upgrades preserve the protected
Atlas and Nova outputs. No inference or database operation occurred.

Report file SHA-256:
`7256815c7abc9518f7b4a82f325d6ebfd13813e776abec9d31762a0cc95cc982`.
The earlier r1 report remains unchanged. r2 adds source-bound report reproduction,
overwrite refusal, role restrictions, idempotent rollback, target-contract and
adapter-revision regressions to the original 36-test checkpoint. These are finite
agent-authored synthetic checks, not independently observed customer outcomes.

## Reproduce

From the repository root, using the existing Python environment:

```bash
env OWNSTACK_AI_MODE=off OWNSTACK_MAX_LIVE_CALLS=0 NEBIUS_API_KEY= \
  NEBIUS_MODEL_ID= NEBIUS_PATCH_MODEL_ID= \
  .venv/bin/pytest tests/test_compatibility.py --tb=short

env OWNSTACK_AI_MODE=off OWNSTACK_MAX_LIVE_CALLS=0 NEBIUS_API_KEY= \
  NEBIUS_MODEL_ID= NEBIUS_PATCH_MODEL_ID= \
  .venv/bin/python scripts/run_compatibility_lab.py \
  --output docs/evidence/compatibility-your-own-new-run
```

The output directory must not exist. A repeated command fails rather than
overwrite evidence. The report contains exact source hashes, normalized protected
outputs before and after each upgrade, plan hashes, rejected migrations, every
declared defect result, and limitations. `report.sha256` binds the file bytes;
`content_digest` binds the canonical report excluding that digest itself. Neither
is a signature or external attestation. Every run uses a fixed synthetic policy
clock and separately records its real UTC execution timestamp.

Expected: all positive controls and all six defect detections pass, both hosts
preserve their effective Atlas response, Nova retains its own unchanged response,
expiry and grant rollback deny access, and the old adapter is refused after the
upgrade. A semantic mismatch for `internal_notes` produces a blocked impact and
cannot be approved. Preview is a counterfactual and never mutates state.

## Methodology and baselines

The reproducible finite matrix contains ten positive invariants and six deliberate
defective implementations: removed tenant check, ignored expiry, lost redaction,
overbroad rollback, removed host-version fence and removed upgrade-approval fences.
These mutants exist only in the experiment. The same invariant definitions are
run against the correct functions and each mutant. Detecting these six specified
defects is not exhaustive security evidence or a mutation score over the codebase.

Twenty comparisons cover both applications, an Atlas contractor and a Nova member,
target/non-target resources, and pre/post-expiry times. A competent manual feature
flag baseline has tenant/scope/subject checks, expiry and explicit redactions. It
uses the same normalization and produces the same allowed/denied protected
outputs on these cases. OwnStack does not claim an advantage on this simple task.
The additional lab mechanism is explicit version/semantic impact review and exact
approval history. A real flag system could implement those mechanisms too.

The branch comparison compiles and executes two tiny owned customer-branch source
fixtures. Both fail against the new schema before editing and succeed after the
same one-line mapping change. That requires two branch source-unit edits versus
one shared adapter unit for **both** OwnStack and the shared feature-flag baseline.
This is a transparent fixture count, not measured engineering time, saved money,
proof that all flags prevent forks, or proof that all customer branches are bad.

## Learning path: build your own evidence

1. Predict the output of `read` for Nova using an Atlas object key. Rebuild that
   tenant-first check without reading the implementation, then write a negative
   test. Checkpoint: the returned fields are empty for denied reads.
2. Implement the expiry interval as `starts <= now < expires`. Test both boundary
   instants. Explain why a cleanup job is not needed for expiration enforcement.
3. Rebuild redaction as a union of field sets after authorization. Test redaction
   alone, two overlapping restrictions and selective rollback. Explain why a
   last-write-wins policy would re-expose a field.
4. Create your own second native schema and adapter. First intentionally map one
   private field incorrectly. Write an independent expected-output test that
   fails, then correct the mapping. A self-declared manifest is not enough.
5. Rebuild immutable plan hashing. Mutate a variation, target revision and data
   snapshot separately after preview. Each stale approval must fail. Explain why
   a digest is not an authenticated signature.
6. Add one genuinely new mutant and predict which independent oracle should
   detect it. Preserve the failing result before fixing your reconstruction.

Commit your own meaningful slices only after you understand and verify them.
Suggested real commits: `test: define tenant-safe projection boundaries`,
`feat: compose restrict-only variations`, `feat: normalize second host schema`,
`feat: fence compatibility plans`, `test: add upgrade defect control`. These are
suggested learning units, not fabricated day-by-day history or a claim that you
personally authored this reference implementation.

## Unproven and next gate

The contract requirements and adapters are trusted agent-authored code. A dishonest
adapter can leak data despite its manifest, which is why independent output tests
matter. Only finite fixtures are checked. There is no durable cross-service
transaction, concurrent migration, arbitrary repository integration, automatic
rollout, authenticated human approval, customer validation or production guarantee
here. Changing data as part of the upgrade is intentionally rejected and needs a
separate migration design.

The next product gate is independent review of an actual customer's variation
and a real second application's integration cost, compared fairly with its
existing feature-flag/manual process. Outreach and private customer data need
separate permission. Do not add a third fixture and call that market evidence.
