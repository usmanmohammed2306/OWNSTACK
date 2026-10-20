# External PDF verification and adversarial experiments

October 18 follow-up: [SECURITY_HARDENING](SECURITY_HARDENING.md) adds mandatory
kernel lockdown and bounded pipes/queue IO. Current denial and adversarial matrix
reports are listed there. Fork is now denied before a detached child starts;
the cleanup experiment below remains dated historical evidence. A pass under the
older policy hash is not current verification and must be rerun. No new inference.

October 12 to 13, 2026. OwnStack now judges a candidate's exported bytes outside
the candidate interpreter. This fixes a reproduced false pass in the former
exit-code-only check. It does not make Docker a certified hostile-code sandbox.

## What changed

The old command imported the candidate and ran unittest in the same interpreter.
A candidate containing `os._exit(0)` ended that process before the tests completed.
The supervisor recorded success from its exit code. The preserved legacy control
reproduces this behavior inside a disposable container, never on the developer host.

The fixed driver now asks the candidate for PDF bytes for seven inputs. The trusted
parent checks the actual object graph, cross-reference offsets, stream lengths,
escaping and exact decoded text. An empty output, printed success claim, partial
result, corrupt PDF, process error or deadline cannot establish success. Each
successful case has a document digest. Approval requires complete external evidence
bound to the exact patch, source, oracle, driver, supervisor policy and build revision.
Old functional check records remain readable but cannot authorize a new acceptance.

This is a deliberately narrow format: one PDF-1.4 page, five objects, uncompressed
text, Helvetica with explicit WinAnsi encoding and cp1252 replacement for unsupported
characters. The generator prompt states the same format. Other valid PDFs may be
rejected. This oracle is not a general PDF parser, rendering certification or proof
that arbitrary candidate code has no unrelated behavior.

## Measured results

| Experiment | Result | Artifact |
| --- | --- | --- |
| Disposable Docker runner | 13/13 authored expectations match, including known-good export and twelve rejection cases | `evidence/verifier-2026-10-12-r3/report.json` |
| Actual no-network sidecar | 15/15 expectations match, including queue-volume denial and successful cleanup of a detached double-fork descendant | `evidence/verifier-sidecar-2026-10-12-r2/report.json` |
| Vulnerable legacy control | Exit code zero incorrectly implies pass with no export implementation | `legacy_control` in each report |

Cases cover early exit, forged verdict text, test-framework manipulation, wrong
scope, wrong xref, missing rows, unescaped text, output flood, CPU loop, prohibited
write and outbound connection. The prohibited-operation controls run the known-good
export only if the prohibited action succeeds, so an unexpectedly allowed action
would produce a detected test failure. Runner unavailability cannot count as a
detected defect. These are finite authored controls, not penetration-test coverage.

The first verifier report is preserved. Its filesystem/network cases were weak
because they lacked an export function and would fail even if the prohibited action
succeeded. Later reports correct that design and bind a fuller source inventory.
Do not use that first report as containment evidence.

## Isolation boundaries

The development Docker backend resolves an already installed image to its immutable
ID for each job, never pulls implicitly, creates a fresh container, has no mounts
or credentials, and disables networking. Memory, CPU, process count, file size,
descriptor count, output and local deadlines are bounded. The host runs only the
known repository fixture through `trusted_local_verification`; other source is refused.

The full stack does not give the API or worker a Docker socket. It uses a separate
reused no-network sidecar, a fresh UID65534 candidate process and a protected queue
volume. The trusted supervisor retains only SETUID, SETGID and KILL capabilities.
KILL is necessary to clean up a child after dropping its identity. Linux subreaper
mode adopts orphaned descendants; PID/start-time checks and bounded kill/reap retries
handle the tested detached child. Unexplained remaining children block further work.
This does not eliminate kernel vulnerabilities, all process races, denial of service
or the risks of reusing a container. Per-job stronger isolation and an independent
security review remain prerequisites for arbitrary untrusted repositories.

The kernel's [subreaper documentation](https://man7.org/linux/man-pages/man2/PR_SET_CHILD_SUBREAPER.2const.html)
explains orphan adoption. [Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints/)
explain CPU/memory limits and why they must be configured, not assumed.

## Reproduce and learn

From the repository root, with the local stack running and `python:3.12-slim`
already installed. Choose new output paths; earlier reports are never overwritten.

```bash
.venv/bin/pytest tests/test_pdf_oracle.py tests/test_runner.py tests/test_verifier_queue.py -q
.venv/bin/python scripts/run_verifier_lab.py --output docs/evidence/verifier-my-run/report.json
.venv/bin/python scripts/run_verifier_lab.py --backend sidecar --output docs/evidence/sidecar-my-run/report.json
```

Prediction first: why can an untrusted function that prints `passed=true` never
be the authority on whether it passed? Rebuild `judge` without executing candidate
code. Write negative tests for empty, deeply nested, extra and incomplete output.
Then inspect `candidate_driver.py`, `bounded_process.py`, `runner.py`,
`verifier_service.py` and `process_supervisor.py`. Draw the process boundary and
identify which side can author the verdict. Suggested personal commit after your
own tests: `test: separate candidate output from trusted verdict`.
