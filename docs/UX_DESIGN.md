# OwnStack workbench: design and review behavior

## October 12: product-aligned variation map, third revision

The current design replaces the abstract hardware chamber with the actual product
idea: one shared application, distinct Atlas and Nova workspaces, a contract and
human gate, and a separate engineering route. Midnight navy is the stable shared
core; ice cyan marks the Atlas scope; amber marks the human boundary and engineering.
The same palette carries through navigation, intake, request review and dialogs.
The task action comes first, above a full-width optional physical 3D map.

Two explicit examples explain different boundaries. Temporary access has Contract,
Preview, Atlas only and Rollback steps. PDF export has Boundary, Diff, Checks and
Handoff steps. The latter never lights an access grant or claims a passing test.
The shared app is never duplicated, Nova is always unchanged, and no stage claims
deployment. The map says "ILLUSTRATIVE EXAMPLE · NOT LIVE" and "This example changes
no permissions and deploys no code." Loaded tenant counts remain separate below.

`variationModel.ts` defines and tests the eight example states. Both the renderer
and HTML explanation use that model. It has no host API authority. The physical
scene uses local geometry, optical materials, constrained mouse orbit and scoped
signal paths. Native step buttons support arrows, Home and End. Pause, Simple view,
reduced-motion and offscreen behavior remain available; touch policy allows page
scroll and pinch zoom. Real-device gestures still need independent verification.
The Sites local-preview workflow informed this task-centered structure and browser
checks. Nothing was registered or published through Sites.

Do not retain dead tests as a bigger number: the obsolete layer-height and
perspective-fit helpers and their two tests were removed. Five new tests cover the
map invariants and labels. The current frontend suite has 14 tests. Exact build,
browser evidence and limitations: `evidence/ui-cinematic-2026-10-12-r3/report.json`.
Older screenshots, failures and prior design notes are preserved below.

Learning checkpoint, three real reconstruction slices:

1. Predict: can PDF's Checks step ever turn Atlas access on? Rebuild
   `variationFrame` and its tests without opening the reference. Run
   `pnpm --dir web test`, expecting all 14 current tests to pass. Commit your actual
   work as `test: model scoped variation examples` only after explaining each
   invariant. These are display rules, not tenant security tests.
2. Build one shared-app mesh and two customer meshes. Add a route whose material
   changes only from the tested frame. Verify the path is not hidden behind opaque
   geometry. Commit: `feat: visualize one app with scoped customer variations`.
3. Connect native buttons, plain-language explanations and the diagram fallback.
   Check one canvas in 3D, zero in Simple view, Escape from intake and 390px layout.
   Commit: `feat: add accessible variation-map controls`. Compare what a new user
   thinks the map changes with what the host actually changes.

Use the official Three.js material, renderer and React cleanup readings in the
second-revision section below. Next practice: context-loss testing, actual mobile
GPU frame-time measurement and uncoached user comprehension. An attractive map is
not evidence of customer demand, personal mastery or production safety.

## October 12: physical 3D chamber, second revision

Historical implementation, superseded by the variation map above.

Replaced the CSS-only object with a lazily imported Three.js WebGL2 scene:
machined gunmetal, transmissive glass with apertures, a faceted cyan core,
procedural studio reflections, shadows and selected-layer lighting. Drag rotates;
Assemble/Separate layers changes the explanatory model. The short two-line intro
and primary action sit beside the scene at desktop widths; counts are below it.
On mobile, the request action precedes the scene. The Sites local-preview workflow
informed task-first layout and actual browser verification, not publication.

The model has no API access. It cannot approve, grant or release anything. Its
caption explicitly says architecture illustration. Simple view disposes WebGL
and shows a static diagram with the same text and native stage buttons. Import or
context failure falls back to that diagram. Paused and reduced-motion changes
render on demand; hidden/offscreen canvas suspends the animation loop. DPR is
capped at 1.5. Geometry, materials, textures, observers, context and listeners are
disposed on unmount. No downloaded HDR, external font or model call is required.

Tradeoff: the separate 3D chunk is approximately 575.83 kB minified / 147.54 kB
gzip. Vite retains its large-chunk warning. Lazy loading keeps that dependency
out of the initial task bundle, but it still downloads when the scene mounts.
No FPS, battery, low-end-device or measured loading-speed claim is made.

Source map: `ScopeScene.tsx` owns lifecycle and accessible controls;
`CapabilityRenderer.ts` owns scene/resources; `sceneMotion.ts` holds the tested
motion gate, layer order and camera-fit math. `WorkspaceHome.tsx` and the existing
styles keep task content separate from the illustration. The superseded CSS
scene rules were removed; prior screenshots and evidence remain below/in their
original directories. Current results: `evidence/ui-cinematic-2026-10-12-r2/`.

Learning checkpoint, three honest reconstruction commits:

1. Predict which of visible/paused/reduced-motion states should request another
   frame. Rebuild `sceneMotion.ts` and its three tests. Run `pnpm --dir web test`.
   Suggested commit after doing it: `test: rebuild scene motion and camera bounds`.
2. Build one lit mesh, then add the floor, environment and glass. Explain why a
   bright environment can wash out transparent material. Add disposal before
   adding animation. Commit: `feat: build optional physical capability model`.
3. Rebuild the native controls and diagram fallback. Navigate away and back;
   verify one canvas, then zero in Simple view. Test keyboard selection, Escape
   from New request and 390px layout. Commit: `feat: connect accessible scene controls`.

Official reading: [Three.js physical materials](https://threejs.org/docs/pages/MeshPhysicalMaterial.html),
[WebGL renderer](https://threejs.org/docs/pages/WebGLRenderer.html),
[RoomEnvironment](https://threejs.org/docs/pages/RoomEnvironment.html), and
[React effect cleanup](https://react.dev/reference/react/useEffect).
Future practice: measure frame time on a real low-end device; add a context-loss
browser test; observe whether a new user mistakes the model for runtime state.
Do not turn visual polish or AI-assisted source into a claim of unaided mastery.

## Earlier October 12: CSS cinematic workspace revision

The earlier direction was a dark, quiet workspace with mint lighting and an
interactive exploded capability core. The October 9 design notes below remain
as history. This revision is AI-assisted reference work, not a claim of unaided
human authorship, independent usability validation or production readiness.

The home has one primary action, New request. A native dialog handles intake;
Requests holds saved work, previews and decisions. Code review, Product signals
and Activity use plain navigation labels. Historical demo evidence is optional
and dated. Hashes, attempts and detailed evidence remain inspectable without
occupying the default reading path. Current counts derive from loaded records.

`WorkspaceHome.tsx` composes the landing view. `RequestComposer.tsx` owns the
native intake dialog. `experience.css` follows the earlier presentation layers;
it replaces their colors and responsive treatment without deleting the earlier
implementation. `ScopeScene.tsx` and `scope-scene.css` implement the scene using
CSS perspective, preserve-3d planes and SVG circuit detail. No new 3D engine,
remote image/font, model call or asset download is required.

The scene is explicitly an architecture illustration, never live authorization
or telemetry. Three buttons select Propose, Approve and Enforce. Mouse movement
tilts the object; keyboard selection and touch buttons offer the same explanation.
Pause, reset, reduced-motion, offscreen and hidden-document behavior bound motion.
The protected host API remains the enforcement point.

Learning slice: predict whether a late preview for request A may ever enable
approval for request B. Rebuild the response identity helper and tests first.
Then build a two-plane CSS illustration with native buttons and reduced-motion
support. Finally rebuild the intake dialog and verify Escape, focus restoration,
server errors and narrow-screen scrolling. Commit only your actual reconstruction,
for example `feat: bind preview display to exact proposal identity`, followed by
`feat: add accessible capability explorer`. A visual resemblance is not proof of
understanding or independent authorship.

Official reference reading:
[CSS 3D transforms](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/transform-style),
[reduced motion](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-reduced-motion),
[visibility observation](https://developer.mozilla.org/en-US/docs/Web/API/Intersection_Observer_API),
and the React/dialog resources below. Read the preserve-3d flattening conditions
before adding filters or opacity to an ancestor of the plane assembly.

Verification results belong in the dated evidence handoff, not this design intent.
Earlier ZIPs and the edited video keep their original UI and were not overwritten.

## October 9: Orbital reference and earlier verification

October 9, 2026. Implemented in the existing React app with AI assistance. This
is a design direction, not a claim of unaided human authorship, independent user
validation, production readiness or a guaranteed hackathon result.

## Design intent

An instrument-like graphite shell and architecture illustration surround a
readable paper-colored work surface. Lime marks human gates and selected state;
warm rust marks rejected evidence. Status always has text, not just color. System
fonts, Lucide icons and repo-native SVG avoid external asset/font requests. The
diagram explicitly says architecture illustration, not live telemetry.

The Sites skill informed task-centered layout, responsive checks and local-only
preview. No Sites registration, repository migration or publication was performed.

## What is implemented

- Overview & proof is the entry view. Historical model measurements, finite
  preview counts and the failed patch remain dated and separate from runtime mode.
- Role-filtered quick navigation opens with Command/Ctrl K. A native dialog gives
  focus containment, Escape and focus restoration. Search uses only already-loaded
  tenant requests. It invokes no inference and performs no mutation.
- Request search matches all query words across intent, ID, kind and saved status.
  Filters include awaiting approval in needs attention. Selecting via quick
  navigation clears old list filters so the requested item is not hidden.
- The boundary inspector joins this request's activation event to its exact
  variation, project and contractor before counting granted reads. No approval or
  preview is inferred to be a read. It shows evidence presence, not authorization.
  The observation window is the latest 500 tenant checks, not lifetime analytics.
- Review & approve requires a host preview and an admin. Its dialog exposes the
  exact project, viewer, read-only effect, expiry, document names and proposal hash.
  Acknowledgement resets on close; changing proposal/preview identity remounts the
  dialog. The server still rechecks authorization and snapshot. The checkbox is a
  usability guard, not a security boundary or a replacement for backend fencing.
- Active variation display derives expiry from loaded state and device time.
  Revoked/expired records move into collapsible history. Host time is authoritative.
- The cockpit offers a line-numbered exact-source diff and complete-source view.
  A bounded longest-common-subsequence computation falls back to full replacement
  above 250,000 line comparisons. Tests reconstruct both exact inputs. Display
  line counts do not replace the server patch hash. Historical checks do not cover
  another candidate; conflicting results for one hash show mixed, not a guessed
  latest result from an unordered response.
- AI-off handoff guidance, saved-state sync timestamps and refresh failure labels
  replace ambiguous disabled controls. No decorative activity/health counters.
- Skip link, visible focus, semantic headings, text statuses, reduced-motion CSS,
  mobile horizontal work-item lists and scrollable code regions are present.

## Source and checks

`web/src/workbench.css` is the Orbital presentation layer over the existing base
layout. Components: `BoundaryMap.tsx`, `BoundaryInspector.tsx`, `ApprovalReview.tsx`,
`CommandMenu.tsx`, `PatchDiff.tsx` and `DemoEvidence.tsx`. Pure derivations live in
`web/src/review.ts`; Node's built-in test runner exercises them without new packages.

```bash
pnpm --dir web test
pnpm --dir web build
.venv/bin/pytest --tb=short
```

Expected: six frontend derivation tests, a TypeScript/Vite build and the Python
regression suite pass. Current observed results and exact browser journey IDs are
in `evidence/ui-redesign-2026-10-09.json` and VALIDATION.

Browser QA is agent-run, not an accessibility audit or an independent usability
study. Keyboard dialog behavior, role controls, request search, exact read
attribution, approval acknowledgement/reset, actual grant/read/revoke/403 and
390-pixel layouts were checked against the running PostgreSQL app with AI off.
Initial mobile heading spacing and oversized vertical work lists were corrected;
the initial screenshot remains as evidence, not a final design capture.

## Learn by rebuilding one slice

Predict first: should a passing check for hash A make hash B look checked? Should
an admin read or another variation's read count as this request's contractor use?
Implement `currentPatchCheck` and `attributedReads` without opening the reference,
then run `pnpm --dir web test`. Explain why these functions must never grant access.

Next, rebuild the approval dialog and test cancel, reopen, keyboard-only navigation
and a stale server preview. Commit your actual work as
`feat: add exact-scope approval review`, only when you can explain it. Do not copy
this agent's run into a personal ownership claim or manufacture daily history.

Useful official reading: [React state](https://react.dev/learn/managing-state),
[native dialog](https://developer.mozilla.org/en-US/docs/Web/HTML/Element/dialog),
[Node test runner](https://nodejs.org/api/test.html), and
[WAI dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/).

Existing r3 video and earlier submission ZIPs retain the pre-redesign UI. They
are historical snapshots and were not silently overwritten. Re-capture/update
the edited video and build package before representing this UI as their contents.
