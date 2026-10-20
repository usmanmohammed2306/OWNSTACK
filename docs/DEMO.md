# Local demonstration script

October 18: the [release scope](SOURCE_RELEASE.md) describes the retained AI-off HTTP journey
and restored-stack restart procedure. The verified private build runs on loopback
8082, separate from the old app. It demonstrates manual correction and actual
checks, not new live model success. The ten-call allowance remains exhausted.

Run API, worker, web and the migrated/seeded database from the README. Use only synthetic data.

Current safe route: [JUDGE_QUICKSTART](JUDGE_QUICKSTART.md) runs entirely AI-off
and points to the dated live evidence. The older fixture/live outline below is
not authority for a new inference call. All ten approved reservations are
exhausted; use engineer manual handoff for a new request, or inspect saved state.

1. Sign in as `atlas-contractor`. Test the protected Project Atlas read. It is denied before a grant. Sign out.
2. Sign in as `atlas-admin`. Create a temporary read-only request for `atlas-contractor` on `atlas-project` with an expiry within seven days. Use a new idempotency key. Interpret. In fixture mode, label the result synthetic.
3. Refresh while the request is queued or ready. The saved state should remain; GET does not re-run AI. Preview the proposal. Inspect before/after, visible documents, finite replay count and limitations. Approve the exact hash.
4. Sign in as `atlas-contractor`. Test a protected read. Atlas document names appear. A Nova project identifier still does not resolve for this tenant. Sign out.
5. As `atlas-admin`, revoke the variation. The contractor read becomes denied. Expiry is also enforced by the host policy even if no cleanup worker runs.
6. As `atlas-engineer`, request PDF export. Interpret: this must route to engineering, not an access contract. Draft a patch, inspect the complete diff, run independent checks in Docker, and record an exact-hash human decision. Show `not_deployed`.
7. As `nova-admin`, make a separate PDF request. As `platform-owner`, inspect the cross-tenant aggregate count and record `keep_separate`, `promote`, or `retire`. No tenant request text is shown across tenants.

Failure drill: set `OWNSTACK_AI_MODE=off`, restart API/worker, and show that a fresh interpret call fails clearly while existing evidence remains readable. As `atlas-engineer`, use **Continue without AI as engineer** on a new or failed request. An access request still needs host preview and `atlas-admin` approval. For a feature request, open the cockpit, choose **Write patch without AI**, edit the complete source, save the bounded patch, run checks, and record a decision. Use tests for the late-answer race, since a synthetic fixture cannot reproduce a real provider timeout. Never narrate the fixture as a live Nebius result.
