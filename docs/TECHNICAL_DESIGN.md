# Technical design entry point

The maintained design is [ARCHITECTURE.md](ARCHITECTURE.md), with decisions in [DECISIONS.md](DECISIONS.md), operational commands in [DEPLOYMENT.md](DEPLOYMENT.md), and measured claims in [VALIDATION.md](VALIDATION.md). These are linked rather than duplicated so code changes do not create competing specifications.

Read in order: `policy.py` for host authority, `models.py` for durable records, `auth.py` for sessions, `service.py` for transactions/fences, `api.py` for scoped routes, `worker.py` for recovery, `runner.py`/`verifier_service.py` for independent checks, then `web/src/main.tsx` for the presentation. The UI and model never own authorization or deployment.
