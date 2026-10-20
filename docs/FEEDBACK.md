# Feedback and buyer validation

No independent customer interview, pilot or usability feedback has been collected in this repository. Do not invent quotations, willingness to pay or endorsements. Technical defects found during local implementation are developer findings, not customer feedback.

The hackathon also asks for provider/tool feedback. [TOOL_FEEDBACK](TOOL_FEEDBACK.md)
contains first-hand observations from the real Token Factory/Nemotron runs,
including failed/truncated patches and billing limits. It is a prepared draft,
not feedback already sent. Independent customer validation remains a separate
product evidence goal, not a fabricated quotation or a substitute for tool feedback.

Observed developer findings on October 7: container source-root assumptions broke the verifier; queued check identity collided with the API route name; replaced API IPs required dynamic Nginx DNS; dropped capabilities revealed a shared-volume ownership bug. Each was repaired and the HTTP journey rerun. Session hardening replaced browser token storage with revocable cookies. See `JOURNAL.md` and `VALIDATION.md`.

## Run the first independent observation

Ask a B2B engineer about the last actual customer-specific request, then watch them complete Atlas access and PDF handoff without coaching. Obtain permission for notes; redact customer details. Ask what they do today, who approves, how long it takes, how they rollback, how many variants remain and what would prevent adoption. Avoid leading questions such as whether this is impressive.

Record date, participant role, consent, actual request, current baseline, time to outcome, engineer touches, mistakes, confusing UI text, requested correction, action taken, and retest result. Separate observations from interpretation. Test the buyer hypothesis with a concrete follow-up pilot invitation, not compliments about the demo.

Falsification: if teams rarely have legitimate narrow requests, cannot safely integrate a host contract, or their simpler feature-flag/manual process is faster at comparable risk, narrow or stop the product. Do not infer demand from a judge's job title.
