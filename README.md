# OwnStack

**Build it. Understand it. Know what happens when it breaks.**

You press Run. The screen keeps spinning. An AI response arrives late, a retry begins, and the answer on screen is suddenly the wrong one.

What happened?

Most tools are eager to write another piece of code for you. OwnStack starts with a different idea: the moment something goes wrong is the moment you can learn how your system actually works. It lets you follow a request through the browser, server, worker, and model; see where reality diverges from expectation; make a change; and check whether that change holds when the timing changes again.

The goal is not just to help you ship an app. It is to help you become the person who understands, changes, and operates that app.

> **Project status:** OwnStack currently has a working, local interactive studio for one simulated failure. The cloud-backed apprenticeship product described below is the direction we are building toward, not a feature we claim to have shipped.

## The problem

AI has made it easier than ever to get a working first version. Understanding that version is another matter.

When a request hangs, a background worker retries, a model returns late, or a cloud bill surprises you, generated code is no substitute for knowing which component owns the decision. A tutorial can explain a concept in isolation. A coding agent can fix a bug for you. Neither automatically proves you can recognize the same failure in *your* project next week.

OwnStack is being built for AI and cloud builders who want both outcomes: useful software today and more capability tomorrow.

## How OwnStack is meant to work

The full product is designed around a short loop:

1. **Build something useful.** Start with a supported app or a clearly bounded part of your own project.
2. **See the system.** Follow real requests, state changes, and failures, with observed facts kept separate from guesses.
3. **Understand one decision.** Get an explanation when a concept is unfamiliar, then inspect the relevant code and evidence.
4. **Make the change.** Edit or approve the critical behavior yourself. Ask for more help when you want it.
5. **Verify it independently.** Tests check what the software did, including a variation that was not part of the walkthrough.
6. **Leave with a truthful record.** Know what passed, what help you used, and what remains unproven.

The first supported case is deliberately specific: an asynchronous AI request times out, gets retried, and receives an old answer after the new attempt has taken ownership. It is a small story that reveals a large class of real engineering problems: background work, persistent state, duplicate delivery, cancellation, concurrency, and the difference between a result existing and a result being safe to show.

The long-term ambition is a project-native apprenticeship for software builders. The first prototype is not a universal tutor, arbitrary-repository coding agent, or claim that someone can master every cloud service through one lesson.

## Try the studio that exists today

The current app is a local, interactive simulation. It uses a real state model and deterministic checks, but it does **not** call an AI provider, deploy to AWS, or edit repository code.

From the repository root:

```sh
pnpm install
pnpm dev:studio
```

Open **http://127.0.0.1:5180/**. You need Node.js 22+ and pnpm. No API key or cloud account is required. The development server binds to your local machine.

Then try this:

1. Select **Begin walkthrough** and follow request 482 across the system view.
2. Jump to **Late arrival**. Notice which attempt produced the visible summary.
3. Select **Only accept the current attempt**.
4. Select **Run both checks**. One fixture lets the retry succeed; the other lets it fail. In neither case should the superseded answer become the user's answer.
5. Open **The code** and **Your evidence**. The code is an illustrative contract. The receipt describes a simulated exercise, not a production guarantee or a mastery score.

You can pause and scrub the replay, inspect components, switch between 3D and 2D, use captions, or ask the scripted guide a small set of supported voice or text commands. Microphone access is off unless you choose to enable it. The lesson works without speech or WebGL.

For every current control and limitation, see the [studio guide](apps/studio/README.md).

## What is implemented, and what is not

| Area | Status today |
| --- | --- |
| Interactive request-flow scene and original 3D guide | Implemented locally with React, TypeScript, and Three.js |
| Retry and late-result behavior | Calculated by a deterministic simulation with success and failure fixtures |
| Voice and text interaction | Browser speech when available, captions, and bounded scripted commands |
| Evidence receipt | Local simulation receipt that states its limits |
| Real learner code change and independent verifier | Not implemented in OwnStack yet |
| Live NVIDIA Nemotron through Nebius Token Factory | Not implemented in OwnStack yet |
| AWS deployment and operations | Not implemented in OwnStack yet |
| OwnStack MCP server or native Alexa+ integration | Not implemented yet |
| Learning improvement or commercial demand | Not established; these require real users and comparison |

There is no hidden general-purpose AI behind the guide. Mira's explanations are scripted. Her face reacts to speaking state; it is not phoneme-accurate lip sync or NVIDIA Audio2Face. The current scene illustrates a system, not the internal topology of any cloud provider.

These boundaries matter. A persuasive interface should make the underlying work easier to inspect, not make a simulation look like a deployed system.

## The design principle: evidence before confidence

OwnStack separates three statements that are often blurred together:

- **The software did something.** A test, trace, or actual request can support that claim.
- **A person explained or changed it.** The record should show what they did and what help they received.
- **They can do it again independently.** That requires a different task or later check; a single guided success does not prove it.

The same care applies to system status. “Our server stopped waiting” does not mean “the model stopped working.” “Cancellation requested” does not mean “cancellation confirmed.” “The worker last contacted us ten seconds ago” is an observation, not a progress percentage.

That is why the first lesson focuses on an old AI response arriving after a retry. It gives us a concrete way to test whether the app tells the truth when several systems disagree about what is happening.

## Where the code lives

| Path | Purpose |
| --- | --- |
| [`apps/studio/src/model.ts`](apps/studio/src/model.ts) | Pure replay state, acceptance policies, and fixture checks |
| [`apps/studio/src/model.test.ts`](apps/studio/src/model.test.ts) | Deterministic behavior tests |
| [`apps/studio/src/Scene.tsx`](apps/studio/src/Scene.tsx) | 3D system scene and procedural guide |
| [`apps/studio/src/voice.ts`](apps/studio/src/voice.ts) | Browser speech, interruption, and recognition handling |
| [`apps/studio/src/main.tsx`](apps/studio/src/main.tsx) | Studio experience and evidence receipt |
| [`tests/ownstack-studio.test.mjs`](tests/ownstack-studio.test.mjs) | Browser-level checks |
| [`docs/OWNSTACK_BUILD_IT_YOURSELF.md`](docs/OWNSTACK_BUILD_IT_YOURSELF.md) | Step-by-step build and learning manual |

This workspace also preserves an older, separate Relief prototype in [`legacy/relief`](legacy/relief/package.json). OwnStack Studio does not use it. Its [historical guide](legacy/relief/docs/README.md), package manifest, lockfile, source, and tests remain together; run its commands from that directory. The root workspace and default commands contain only OwnStack. Before publishing an OwnStack-only repository, exclude the legacy directory and unrelated historical documents.

## Tests

The studio has deterministic model tests and browser checks. Run:

```sh
pnpm test:studio
pnpm build:studio
```

For browser checks, keep the studio development server running in another terminal, then run:

```sh
pnpm test:studio:browser
```

The browser test uses Playwright. If Playwright's Chromium is not installed, install it according to [Playwright's browser setup guide](https://playwright.dev/docs/browsers), or set `CHROME_PATH` to a locally installed Chrome or Chromium binary. The tests use simulated model behavior and mocked speech adapters. They do not establish real-model quality, cloud reliability, acoustic quality, or learning outcomes.

## What comes next

The next work is not a longer feature list. It is to make the central learning loop real:

1. Build a small local API that saves a request once and returns its already-generated result when the browser asks again.
2. Add a worker and an atomic ownership rule so an old attempt cannot publish after a retry.
3. Replace one fixture with a bounded, server-side NVIDIA Nemotron call through Nebius Token Factory.
4. Let a learner change a real, safe starter and run a verifier outside the editable exercise files.
5. Deploy the smallest useful AWS slice with scoped access, observable failures, cost limits, and a recovery path.
6. Expose a useful OwnStack workflow through a self-hosted MCP server and a clearly labeled Alexa+-style experience.
7. Test whether builders actually finish useful work and understand it better than they would with an ordinary, capable AI assistant.

The [build-it-yourself guide](docs/OWNSTACK_BUILD_IT_YOURSELF.md) breaks this into paced missions with analogies, specific reading links, coding tasks, tests, and submission checks. The [product decision](docs/OWNSTACK_DECISION.md), [learner experience design](docs/OWNSTACK_LEARNER_EXPERIENCE.md), and [AWS/NVIDIA learning program](docs/AWS_NVIDIA_LEARNING_PLAN.md) explain the reasoning and the open questions. They are plans, not claims of completed integrations. The current stack decision is React and TypeScript for the browser, Python for the planned API, worker, model adapter, MCP server, and AWS infrastructure code.

## Hackathon direction

OwnStack is being developed with two tracks in mind:

- [Amazon Alexa+](https://amazonappdev2026.devpost.com/rules): a useful agent workflow exposed through a compliant self-hosted MCP server, with a clearly labeled simulated Alexa+ web experience where appropriate. A documented AWS integration may also support the AWS Builder mini-challenge.
- [Nebius x NVIDIA Best Apps and Agents](https://nebiusglobalaihackathon.devpost.com/rules): a working builder application powered at runtime by an NVIDIA model through Nebius Token Factory.

The current local studio alone does **not** satisfy either intended final integration. This README will be updated with actual endpoints, model IDs, deployment instructions, demo video, and measured results only when those things exist. Nothing here claims organizer approval, a prize, or a completed submission.

## Privacy and safety

The current studio uses local, synthetic scenarios. It does not require a cloud account or send a prompt to an AI model. Replay position and selected view/policy preferences are stored in the browser's local storage. Microphone use requires an explicit action and browser permission; browser speech recognition may send audio to the browser's provider. The app does not record or persist microphone audio. On-device speech synthesis is used only when a suitable local voice is available, and captions remain available without it.

Do not put API keys, private repositories, personal data, or real customer content into screenshots or public issues. Future code-running exercises must use isolated, bounded environments. We will not treat a learner's repository as permission to execute arbitrary commands or expose its contents.

## Contributing and feedback

OwnStack is early. The most helpful feedback is concrete: where an explanation stopped matching what you saw, which step felt confusing, whether the visual model helped you reason about the failure, and what you could or could not do afterward without the guide.

If you report an issue, include the browser and operating system, the steps to reproduce it, what you expected, and what happened. Please do not include credentials or private project data. Contributions should keep simulation, observed behavior, and unverified claims clearly separated.

## License

Apache License 2.0. See [LICENSE](LICENSE). Check the licenses and permissions for any new assets, example repositories, models, and external services before publishing or redistributing them.

---

*OwnStack is a working name. The vision is ambitious; the current implementation is intentionally labeled. The next milestone is not to make the demo look more certain. It is to make more of its promises true.*
