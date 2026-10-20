# Hackathon submission draft and gates

Status: local reference build, not submitted. Recheck the [official rules](https://nebiusglobalaihackathon.devpost.com/rules), [resources](https://nebiusglobalaihackathon.devpost.com/resources), and actual Devpost form before publication. Deadline rechecked October 9: October 30, 2026, 10 a.m. PDT. Target Best Apps and Agents. Switch to Coding and Agentic Engineering only if live patch generation and independently checked engineering outcomes become the stronger demonstrated journey.

## Copy-ready description, subject to evidence updates

October 9 packaging update: [copy-ready story](DEVPOST_COPY.md),
[actual form audit and field answers](DEVPOST_FIELDS.md),
[first-hand tool feedback](TOOL_FEEDBACK.md), and
[zero-inference judge walkthrough](JUDGE_QUICKSTART.md) are prepared locally.
The signed-in Devpost draft was inspected read-only; nothing was saved or
submitted. Subjective ratings, eligibility, learning/career self-assessment,
publication and final terms remain owner actions. The generic video widget is
less strict than the event rules: use public YouTube, not Vimeo/unlisted.

Keep judge access available through December 15, 2026, noon Pacific, the official
judging close. A downloadable public test build is an allowed route, not just a
hosted app. A ZIP on this laptop is not a public test-build URL. Run
`python scripts/submission_preflight.py --strict` against
`submission_manifest.json`. Exit 2 is expected until external gates are filled;
the checker is offline and does not independently verify URLs or eligibility.

**OwnStack: customer-specific changes without permanent forks.**

B2B software teams receive requests that are too narrow to justify a fork but too important to ignore. OwnStack separates a bounded customer variation from a real engineering change. An admin requests temporary contractor access to Project Atlas. NVIDIA Nemotron, called server-side through Nebius Token Factory when live mode is configured, proposes an interpretation. The host app retains authority: its versioned Capability Contract limits the effect to read-only access for one contractor, one project and a bounded duration. The host computes an exact preview; an authenticated admin approves its hash. Actual document reads enforce tenant scope, expiry and revoke. Nova remains separate.

A PDF-export request cannot become a configuration permission. It opens an Engineer Cockpit for an exact, single-file patch against the owned sample app, a diff and independent no-network checks. A human can reject, take over or accept the checked artifact for manual release. Nothing silently deploys. Repeated PDF/access needs and actual grant-attributed host checks enter a tenant-safe Convergence Queue where a product owner records a rationale and decision, not an automatic promotion. Previews are never reported as observed use. A tenant-private proof export preserves exact proposals, approvals, failed/superseded checks and current source hashes for offline inspection; its digest is not a signed attestation.

The local build includes durable request/attempt records, repeated-click deduplication, late-result fencing, cancellation with honest remote-state limits, AI-off handoff, revocable cookie sessions and a reproducible Python/React/PostgreSQL stack. Its buyer hypothesis and production safety are not yet independently validated.

The original live artifact now contains two accepted Nano interpretations and actual Atlas/Nova/revoke observations. It also records a failed PDF draft. Describe the engineering outcome only according to the subsequent preserved retry/check artifacts. Configuration alone is not submission proof.

## Why the technical story is distinctive

The differentiator is the boundary from intent to **observed host behavior**, not a chat interface or extra models. Demonstrate one authorized delta, direct negative API checks, parity between preview and enforcement, expiry/revoke, repeat/restart recovery and a real independently checked patch. Explain the limitations voluntarily. A ten-case synthetic classification score is not evidence of model superiority or customer demand.

## Required completion checklist

| Gate | Current evidence | Required external outcome |
| --- | --- | --- |
| Runtime Nebius + NVIDIA model | Two accepted live Nano interpretations; Atlas grant/read, Nova denial and revoke observed | Core local runtime gate observed; public judge workflow still needed |
| Working build | Local Compose and HTTP smoke pass | Judge-accessible hosted demo or test build link, available throughout judging |
| Repository | MIT license, setup and source present locally | Public repository URL after owner reviews and pushes |
| Video | [Actual-screen scene source](demo_scenes.json), renderer and [script](VIDEO_SCRIPT.md) | Review local render, then public YouTube URL strictly under three minutes |
| Usage documentation | [Usage ledger](NVIDIA_NEBIUS_USAGE.md) | Exact live model ID, runtime path, metrics and limitations |
| Feedback | [First-hand tool feedback](TOOL_FEEDBACK.md); separate [buyer protocol](FEEDBACK.md) | Include honest provider feedback. Customer interviews remain an unvalidated product goal, not invented eligibility evidence |
| Work period | Owned implementation/evidence built and tested October 7-9 locally | Truthful timeline, prior-art disclosure and significant hackathon work explanation |
| Form and eligibility | Rules and actual draft fields inspected October 9, no edits | Owner supplies personal declarations/ratings and reviews terms at submission |

No final submission, repository publication, video upload or paid deployment has been performed. The user intends to commit and push later. Do not invent a receipt or public URL.

## Judge relevance, not a prediction about individuals

NVIDIA engineering roles make model integration, independent checks and system boundaries relevant topics. Nebius product/serverless roles make reproducibility, observable runtime usage, latency/cost tradeoffs and recovery relevant topics. Developer-relations roles make fresh setup, clear demos and learnable architecture relevant topics. Forward-deployed roles make an actual customer workflow and baseline comparison relevant topics. These are role-based inferences, not verified personal preferences, job requirements or a claim that any named judge will hire the builder. Their LinkedIn profiles and teams' current vacancies have not been audited in this build. Do not advertise that they have.

Serverless Endpoints/Jobs are encouraged for the target track, not mandatory. Do not add unrelated infrastructure just to target a judge. Demonstrated reliability and a narrow real outcome are stronger than an unverified feature pile.
