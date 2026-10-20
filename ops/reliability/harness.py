"""Real OS processes + real PostgreSQL + real HTTP, synthetic provider only.

Creates one uniquely named lab schema in an explicitly supplied local database.
Does not change the existing runtime schema, renew credit allowance or run code
from a model. Lab records and every failed run remain available for inspection.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import socket
import statistics
import subprocess
import sys
from threading import Barrier
import time
from uuid import uuid4
import httpx
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_COUNTS = ("change_requests", "attempts", "proposals", "approvals", "variations", "events", "outbox")
SCENARIOS = ("duplicate_fanout", "kill_after_claim", "kill_before_commit", "kill_after_commit",
             "late_attempt", "cancel_late", "invalid_output", "provider_429", "provider_timeout",
             "stale_approval", "grant_revoke_expiry", "accepted_redelivery")


class CheckFailed(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailed(message)


def local_url(value):
    url = make_url(value)
    if url.drivername != "postgresql+psycopg" or url.host not in {"db", "127.0.0.1", "localhost"} or url.query:
        raise ValueError("Explicit local PostgreSQL URL without query options required")
    return url


def child_environment(url, schema, secret):
    # Do not inherit .env, API keys, proxy settings, cloud credentials or user secrets.
    return {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "PYTHONPATH": str(ROOT / "src") + os.pathsep + str(ROOT), "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "OWNSTACK_RELIABILITY_LAB": "1", "OWNSTACK_LAB_SCHEMA": schema,
        "OWNSTACK_DATABASE_URL": url.render_as_string(hide_password=False),
        "OWNSTACK_AI_MODE": "fixture", "OWNSTACK_MAX_LIVE_CALLS": "0", "OWNSTACK_AI_TIMEOUT_SECONDS": "10",
        "NEBIUS_API_KEY": "", "NEBIUS_MODEL_ID": "", "NEBIUS_PATCH_MODEL_ID": "",
        "OWNSTACK_ENV": "local", "OWNSTACK_REQUIRE_BACKGROUND": "false",
        "OWNSTACK_SIGNING_SECRET": secret, "OWNSTACK_PUBLIC_ORIGIN": "http://127.0.0.1",
        "OWNSTACK_DEMO_PASSWORD": "synthetic-lab-only-password"}


def percentiles(samples):
    if not samples:
        return {"samples": 0, "raw_ms": []}
    values = sorted(samples)
    return {"samples": len(samples), "p50_ms": statistics.median(values),
            "p95_ms": values[math.ceil(len(values)*.95)-1], "max_ms": values[-1], "raw_ms": samples}


def source_hashes():
    paths = [ROOT / "src/ownstack" / name for name in
             ["service.py", "worker.py", "api.py", "policy.py", "models.py", "db.py", "host_access.py"]]
    paths += list((ROOT / "ops/reliability").glob("*.py")) + [ROOT / "scripts/run_reliability_lab.py"]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


class Lab:
    def __init__(self, url, directory, repeats):
        from ownstack.db import Base
        from ownstack.models import Contract, Document, InferenceBudget, Project, Tenant, User
        from ownstack.auth import password_hash
        from ownstack.policy import CONTRACT, digest
        self.directory, self.repeats = directory, repeats
        directory.mkdir(parents=True, exist_ok=False)
        self.schema = "ownstack_lab_" + uuid4().hex
        self.public = create_engine(local_url(url))
        self.processes, self.http_samples, self.recoveries = [], [], []
        self.checks, self.mutants, self.kills, self.dispatches = [], [], [], []
        self.control_requests = []
        self.client = httpx.Client(timeout=8, trust_env=False)
        self.api_process = None
        self.report = {"format_version": 1, "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "running", "schema": self.schema, "schema_retained": True,
            "provider": "instrumented synthetic fixture; no live inference", "live_calls": 0,
            "repeats": repeats, "scenario_manifest": list(SCENARIOS), "source_sha256": source_hashes(),
            "machine": {"system": platform.system(), "architecture": platform.machine(),
                        "python": platform.python_version(), "logical_cpus": os.cpu_count()},
            "checks": self.checks, "mutants": self.mutants, "intentional_process_kills": self.kills}
        with self.public.begin() as db:
            self.report["public_before"] = self.public_snapshot(db)
            db.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        scoped_url = local_url(url).update_query_dict({"options":
            f"-csearch_path={self.schema},pg_catalog -cstatement_timeout=5000 -clock_timeout=2000"})
        self.engine = create_engine(scoped_url)
        self.env = child_environment(scoped_url, self.schema, uuid4().hex + uuid4().hex)
        # Metadata fixture, explicitly not a migration rehearsal. Never inserts a zero
        # allowance as a substitute for the existing counter; live cap is always zero.
        with self.engine.begin() as db:
            require(db.scalar(text("SELECT current_schema()")) == self.schema, "Schema isolation failed")
            Base.metadata.create_all(db)
        with Session(self.engine) as db:
            db.add_all([Tenant(id="atlas", name="Atlas lab"), Tenant(id="nova", name="Nova lab")])
            db.flush()
            encoded = password_hash("synthetic-lab-only-password")
            db.add_all([User(id=f"{tenant}-{role}", tenant_id=tenant, role=role, password_hash=encoded)
                        for tenant in ("atlas", "nova") for role in ("admin", "engineer", "contractor")])
            db.add_all([Project(id=f"{tenant}-project", tenant_id=tenant, name=f"Project {tenant.title()}", revision=1)
                        for tenant in ("atlas", "nova")])
            db.flush()
            db.add_all([Document(id=f"{tenant}-doc", tenant_id=tenant, project_id=f"{tenant}-project",
                                title=f"{tenant} lab document", body=f"{tenant} synthetic private content") for tenant in ("atlas", "nova")])
            db.add(Contract(id=CONTRACT["id"], version=1, manifest=CONTRACT, manifest_hash=digest(CONTRACT)))
            db.add(InferenceBudget(id="global", reserved_calls=self.report["public_before"]["reserved_calls"]))
            db.commit()
        self.port = self.unused_port()
        self.base = f"http://127.0.0.1:{self.port}"

    @staticmethod
    def unused_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    @staticmethod
    def public_snapshot(db):
        return {"reserved_calls": db.scalar(text("SELECT reserved_calls FROM public.inference_budget WHERE id='global'")),
                "counts": {name: db.scalar(text(f'SELECT COUNT(*) FROM public."{name}"')) for name in PUBLIC_COUNTS}}

    def spawn(self, action="worker", **options):
        directory = self.directory / f"child-{len(self.processes):04d}-{action}"
        directory.mkdir()
        command = [sys.executable, "-m", "ops.reliability.child", action, "--directory", str(directory)]
        for key, value in options.items():
            command.extend(["--" + key.replace("_", "-"), str(value)])
        output = (directory / "process.log").open("wb")
        process = subprocess.Popen(command, env=self.env, cwd=directory, stdout=output, stderr=subprocess.STDOUT)
        output.close()
        handle = {"process": process, "directory": directory, "action": action}
        self.processes.append(handle)
        return handle

    def traces(self, handle):
        path = handle["directory"] / "trace.jsonl"
        if not path.exists():
            return []
        lines = path.read_text().splitlines()
        rows = []
        for line in lines:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # Writer may currently be finishing a line; next poll rereads it.
        return rows

    def wait_trace(self, handle, event, timeout=12):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            rows = [row for row in self.traces(handle) if row["event"] == event]
            if rows:
                return rows[-1]
            require(handle["process"].poll() is None, f"Child exited before {event}; inspect {handle['directory'].name}")
            time.sleep(.01)
        raise CheckFailed(f"Checkpoint timed out: {event}")

    def finish(self, handle, timeout=15):
        code = handle["process"].wait(timeout=timeout)
        require(code == 0, f"Child exit {code}; inspect {handle['directory'].name}")
        return self.traces(handle)

    def kill(self, handle, point):
        require(handle["process"].poll() is None, "Target process already exited")
        started = time.monotonic_ns()
        handle["process"].kill()
        code = handle["process"].wait(timeout=5)
        require(code == -9, f"Expected SIGKILL, got {code}")
        self.kills.append({"action": handle["action"], "pid": handle["process"].pid,
                           "point": point, "exit_code": code})
        return started

    def release(self, handle):
        (handle["directory"] / "release").touch(exist_ok=False)

    def start_api(self, mutant="none"):
        self.api_process = self.spawn("api", port=self.port, mutant=mutant)
        end = time.monotonic() + 12
        while time.monotonic() < end:
            require(self.api_process["process"].poll() is None, "Lab API exited at startup")
            try:
                if self.client.get(self.base + "/health/live").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(.03)
        raise CheckFailed("Lab API startup timed out")

    def stop_api(self):
        if self.api_process and self.api_process["process"].poll() is None:
            self.api_process["process"].terminate()
            self.api_process["process"].wait(timeout=8)

    def http(self, method, path, user="admin", body=None, expected=200, key=None):
        headers = {"Authorization": "Bearer " + self.tokens[user]} if hasattr(self, "tokens") and user else {}
        if key:
            headers["Idempotency-Key"] = key
        started = time.monotonic_ns()
        response = self.client.request(method, self.base + path, json=body, headers=headers)
        elapsed = (time.monotonic_ns() - started) / 1e6
        self.http_samples.append({"method": method, "path": path, "status": response.status_code, "ms": elapsed})
        require(response.status_code == expected, f"{method} {path}: expected {expected}, got {response.status_code}")
        return response.json()

    def login(self):
        self.tokens = {}
        for alias, username in {"admin": "atlas-admin", "engineer": "atlas-engineer",
                                "contractor": "atlas-contractor", "nova": "nova-admin"}.items():
            self.tokens[alias] = self.http("POST", "/v1/session", user=None,
                body={"username": username, "password": "synthetic-lab-only-password"})["token"]

    @staticmethod
    def request_body(expiry=None):
        return {"text": "Give contractor read-only access to Project Atlas until the selected expiry.",
                "kind": "access", "project_id": "atlas-project", "viewer_id": "atlas-contractor",
                "expires_at": (expiry or (datetime.now(timezone.utc) + timedelta(minutes=30))).isoformat()}

    def request(self, expiry=None, key=None):
        body = self.request_body(expiry)
        result = self.http("POST", "/v1/requests", body=body, key=key or uuid4().hex, expected=201)
        return result["id"], body

    @staticmethod
    def fanout(function, count=8):
        barrier = Barrier(count)
        def aligned(_):
            barrier.wait(timeout=5)
            return function()
        with ThreadPoolExecutor(max_workers=count) as pool:
            return list(pool.map(aligned, range(count)))

    def interpret(self, request_id):
        return self.http("POST", f"/v1/requests/{request_id}/interpret", expected=202)["attempt_id"]

    def snapshot(self, request_id):
        from ownstack.models import Approval, Attempt, ChangeRequest, Event, Outbox, Proposal, Variation
        with Session(self.engine) as db:
            req = db.get(ChangeRequest, request_id)
            proposals = db.scalars(select(Proposal).where(Proposal.request_id == request_id)).all()
            ids = [row.id for row in proposals]
            events = db.scalars(select(Event).where(Event.request_id == request_id)).all()
            outbox_ids = set(db.scalars(select(Outbox.event_id).where(Outbox.event_id.in_([row.id for row in events]))))
            return {"request_id": request_id, "status": req.status, "current_attempt_id": req.current_attempt_id,
                "accepted_proposal_id": req.accepted_proposal_id,
                "attempts": [{"id": row.id, "state": row.state, "error_code": row.error_code}
                    for row in db.scalars(select(Attempt).where(Attempt.request_id == request_id).order_by(Attempt.number))],
                "proposals": [{"id": row.id, "attempt_id": row.attempt_id, "reason": row.reason} for row in proposals],
                "approvals": db.scalar(select(func.count(Approval.id)).where(Approval.proposal_id.in_(ids))),
                "variations": db.scalar(select(func.count(Variation.id)).where(Variation.proposal_id.in_(ids))),
                "events": len(events), "missing_outbox": sum(row.id not in outbox_ids for row in events)}

    def accept_one(self, request_id, **options):
        attempt_id = self.interpret(request_id)
        child = self.spawn(**options)
        self.finish(child)
        state = self.snapshot(request_id)
        require(state["accepted_proposal_id"] and len(state["proposals"]) == 1, "Expected one saved proposal")
        return attempt_id, state

    def expire_and_reap(self, attempt_id):
        from ownstack.models import Attempt
        # Deliberate deadline injection, with real elapsed time, not a fake clock.
        deadline = datetime.now(timezone.utc) + timedelta(milliseconds=120)
        with Session(self.engine) as db:
            db.get(Attempt, attempt_id).deadline_at = deadline
            db.commit()
        while datetime.now(timezone.utc) <= deadline:
            time.sleep(.01)
        reaper = self.spawn("reap")
        self.finish(reaper)

    def check_saved(self, request_id, expected_proposals=1):
        state = self.snapshot(request_id)
        require(len(state["proposals"]) == expected_proposals and state["missing_outbox"] == 0,
                "Proposal/outbox invariant failed")
        require(not any(row["state"] in {"queued", "running"} for row in state["attempts"]), "Orphaned work")
        return state

    def scenario(self, name):
        if name != "duplicate_fanout":
            request_id, _ = self.request()
            self.control_requests.append(request_id)
        extra = {}
        if name == "duplicate_fanout":
            body, request_key = self.request_body(), uuid4().hex
            creates = self.fanout(lambda: self.http("POST", "/v1/requests", body=body, key=request_key, expected=201))
            require(len({row["id"] for row in creates}) == 1, "Duplicate request effects")
            request_id = creates[0]["id"]
            self.control_requests.append(request_id)
            attempts = self.fanout(lambda: self.interpret(request_id))
            require(len(set(attempts)) == 1, "Duplicate attempts")
            children = [self.spawn(gate="provider") for _ in range(4)]
            end = time.monotonic() + 12
            while time.monotonic() < end and not any(any(row["event"] == "provider.entered" for row in self.traces(c)) for c in children):
                time.sleep(.01)
            entered = [c for c in children if any(row["event"] == "provider.entered" for row in self.traces(c))]
            require(len(entered) == 1, "Expected one provider dispatch at checkpoint")
            running_replays = self.fanout(lambda: self.interpret(request_id))
            require(set(running_replays) == set(attempts), "Running replay launched duplicate work")
            require(self.http("GET", f"/v1/requests/{request_id}")["status"] == "interpreting", "Saved progress missing")
            self.release(entered[0])
            for child in children:
                self.finish(child)
            dispatches = sum(sum(row["event"] == "provider.entered" for row in self.traces(c)) for c in children)
            require(dispatches == 1, "Duplicate synthetic provider dispatch")
            extra = {"concurrent_cold_creates": 8, "concurrent_queued_interpretations": 8,
                     "concurrent_running_replays": 8, "worker_processes": 4, "provider_dispatches": dispatches}
        elif name in {"kill_after_claim", "kill_before_commit", "kill_after_commit"}:
            attempt_id = self.interpret(request_id)
            gate = {"kill_after_claim": "provider", "kill_before_commit": "precommit", "kill_after_commit": "postcommit"}[name]
            child = self.spawn(gate=gate)
            self.wait_trace(child, {"provider": "provider.entered", "precommit": "precommit.reached", "postcommit": "postcommit.reached"}[gate])
            began = self.kill(child, name)
            state = self.snapshot(request_id)
            if gate == "postcommit":
                require(len(state["proposals"]) == 1, "Committed result lost")
                self.kill(self.api_process, "api_restart_after_saved_result")
                self.start_api()
                saved = self.http("GET", f"/v1/requests/{request_id}")
                require(saved["accepted_proposal_id"] == state["accepted_proposal_id"], "Restart changed saved result")
                require(self.interpret(request_id) == attempt_id, "Refresh/redelivery launched duplicate work")
            else:
                require(len(state["proposals"]) == 0 and state["missing_outbox"] == 0, "Uncommitted result leaked")
                self.expire_and_reap(attempt_id)
                retry, _ = self.accept_one(request_id)
                require(retry != attempt_id, "Explicit retry did not create a new attempt")
            recovery = (time.monotonic_ns() - began) / 1e6
            self.recoveries.append(recovery)
            extra = {"kill_to_verified_saved_outcome_ms": recovery, "retry": "explicit HTTP retry after reaper" if gate != "postcommit" else "saved result; no retry dispatch"}
        elif name in {"late_attempt", "cancel_late"}:
            first = self.interpret(request_id)
            child = self.spawn(gate="provider", outcome="refuse")
            self.wait_trace(child, "provider.entered")
            if name == "cancel_late":
                canceled = self.http("POST", f"/v1/requests/{request_id}/cancel")
                require(canceled["remote_cancellation_verified"] is False, "False remote cancellation claim")
            else:
                self.expire_and_reap(first)
            second, accepted = self.accept_one(request_id)
            self.release(child)
            self.finish(child)
            state = self.snapshot(request_id)
            require(state["accepted_proposal_id"] == accepted["accepted_proposal_id"], "Late result overwrote current proposal")
            require(len(state["proposals"]) == 1 and state["proposals"][0]["attempt_id"] == second, "Late result accepted")
            extra = {"first_attempt": first, "second_attempt": second, "late_result_accepted": False}
        elif name in {"invalid_output", "provider_429", "provider_timeout"}:
            attempt_id = self.interpret(request_id)
            outcome = {"invalid_output": "invalid", "provider_429": "429", "provider_timeout": "timeout"}[name]
            self.finish(self.spawn(outcome=outcome))
            failed = self.snapshot(request_id)
            require(failed["status"] == "failed" and not failed["proposals"], "Failed provider fabricated success")
            handed = self.http("POST", f"/v1/requests/{request_id}/manual-handoff", user="engineer", key=uuid4().hex)
            require(handed["ai_call"] is False, "Manual fallback claimed inference")
            extra = {"failed_attempt": attempt_id, "error_code": failed["attempts"][0]["error_code"], "manual_recovery": True}
        elif name == "stale_approval":
            _, state = self.accept_one(request_id)
            proposal = self.http("GET", f"/v1/proposals/{state['accepted_proposal_id']}")
            from ownstack.models import Document
            with Session(self.engine) as db:
                db.get(Document, "atlas-doc").body = "Changed after proposal snapshot"
                db.commit()
            self.http("POST", f"/v1/proposals/{proposal['id']}/approve", body={"proposal_hash": proposal["proposal_hash"]}, key=uuid4().hex, expected=409)
            require(self.snapshot(request_id)["variations"] == 0, "Stale approval created effect")
            with Session(self.engine) as db:
                db.get(Document, "atlas-doc").body = "atlas synthetic private content"
                db.commit()
            extra = {"stale_approval_http": 409, "effects": 0}
        elif name == "grant_revoke_expiry":
            _, state = self.accept_one(request_id)
            proposal = self.http("GET", f"/v1/proposals/{state['accepted_proposal_id']}")
            key = uuid4().hex
            approvals = self.fanout(lambda: self.http("POST", f"/v1/proposals/{proposal['id']}/approve",
                    body={"proposal_hash": proposal["proposal_hash"]}, key=key))
            require(len({row["variation_id"] for row in approvals}) == 1, "Duplicate committed grants")
            state = self.snapshot(request_id)
            require(state["approvals"] == state["variations"] == 1, "Approval/effect cardinality failed")
            path = "/v1/host/projects/atlas-project/documents/atlas-doc"
            self.http("GET", path, user="contractor")
            self.http("GET", path, user="nova", expected=404)
            self.http("GET", f"/v1/requests/{request_id}", user="nova", expected=404)
            self.http("POST", f"/v1/variations/{approvals[0]['variation_id']}/revoke", key=uuid4().hex)
            self.http("GET", path, user="contractor", expected=403)
            expires = datetime.now(timezone.utc) + timedelta(seconds=4)
            expiring, _ = self.request(expiry=expires)
            self.control_requests.append(expiring)
            handoff = self.http("POST", f"/v1/requests/{expiring}/manual-handoff", user="engineer", key=uuid4().hex)
            p = self.http("GET", f"/v1/proposals/{handoff['proposal_id']}")
            self.http("POST", f"/v1/proposals/{p['id']}/approve", body={"proposal_hash": p["proposal_hash"]}, key=uuid4().hex)
            self.http("GET", path, user="contractor")
            while datetime.now(timezone.utc) <= expires:
                time.sleep(.01)
            self.http("GET", path, user="contractor", expected=403)
            self.check_saved(expiring)
            extra = {"concurrent_approvals": 8, "committed_variations": 1,
                     "nova_http": 404, "revoke_http": 403, "natural_four_second_expiry_http": 403}
        elif name == "accepted_redelivery":
            attempt_id, state = self.accept_one(request_id)
            self.finish(self.spawn("redeliver", attempt_id=attempt_id))
            again = self.snapshot(request_id)
            require(again["attempts"][0]["state"] == "accepted" and again["accepted_proposal_id"] == state["accepted_proposal_id"], "Redelivery rewrote terminal history")
        else:
            raise ValueError("Unknown scenario")
        return {"name": name, "passed": True, "saved": self.check_saved(request_id), **extra}

    def mutation_checks(self):
        # Actual defective executions must violate the same saved-state/HTTP invariants.
        for kind in ("late_fence", "accepted_redelivery", "outbox", "snapshot_fence", "tenant_scope"):
            request_id, _ = self.request()
            if kind == "late_fence":
                first = self.interpret(request_id)
                child = self.spawn(gate="provider", outcome="refuse", mutant=kind)
                self.wait_trace(child, "provider.entered")
                self.expire_and_reap(first)
                _, state = self.accept_one(request_id)
                self.release(child)
                self.finish(child)
                after = self.snapshot(request_id)
                detected = after["accepted_proposal_id"] != state["accepted_proposal_id"] or len(after["proposals"]) != 1
                observed = {"proposals": len(after["proposals"]), "saved_result_changed": after["accepted_proposal_id"] != state["accepted_proposal_id"]}
            elif kind == "accepted_redelivery":
                attempt, _ = self.accept_one(request_id)
                child = self.spawn("redeliver", attempt_id=attempt, mutant=kind)
                self.finish(child)
                after = self.snapshot(request_id)
                detected = after["attempts"][0]["state"] != "accepted"
                observed = {"attempt_state": after["attempts"][0]["state"]}
            elif kind == "outbox":
                self.interpret(request_id)
                child = self.spawn(mutant=kind)
                self.finish(child)
                after = self.snapshot(request_id)
                detected = after["missing_outbox"] != 0
                observed = {"events_without_outbox": after["missing_outbox"]}
            else:
                _, state = self.accept_one(request_id)
                proposal = self.http("GET", f"/v1/proposals/{state['accepted_proposal_id']}")
                self.stop_api()
                self.start_api(mutant=kind)
                child = self.api_process
                if kind == "tenant_scope":
                    leaked = self.http("GET", f"/v1/requests/{request_id}", user="nova", expected=200)
                    detected = leaked["tenant_id"] == "atlas"
                    observed = {"cross_tenant_http": 200, "returned_tenant": leaked["tenant_id"]}
                else:
                    from ownstack.models import Document
                    with Session(self.engine) as db:
                        db.get(Document, "atlas-doc").body = "Mutant changed source snapshot"
                        db.commit()
                    self.http("POST", f"/v1/proposals/{proposal['id']}/approve",
                        body={"proposal_hash": proposal["proposal_hash"]}, key=uuid4().hex)
                    after = self.snapshot(request_id)
                    detected = after["variations"] != 0
                    observed = {"stale_approval_http": 200, "variations": after["variations"]}
                    # Mutant's effect is retained as revoked lab history, not deleted.
                    from ownstack.models import Variation
                    with Session(self.engine) as db:
                        for row in db.scalars(select(Variation).where(Variation.proposal_id == proposal["id"])):
                            row.state = "revoked"
                        db.get(Document, "atlas-doc").body = "atlas synthetic private content"
                        db.commit()
                self.stop_api()
                self.start_api()
            installed = [row for row in self.traces(child) if row["event"] == "mutant.installed"]
            require(len(installed) == 1 and detected, f"Oracle failed to detect mutant {kind}")
            self.mutants.append({"kind": kind, "detected": detected, "request_id": request_id,
                                 "ast_sha256": installed[0]["ast_sha256"], "observed_violation": observed})

    def execute(self):
        try:
            self.start_api()
            self.login()
            for repeat in range(self.repeats):
                for name in SCENARIOS:
                    started = time.monotonic_ns()
                    try:
                        row = self.scenario(name)
                    except Exception as error:
                        self.checks.append({"name": name, "repeat": repeat + 1, "passed": False, "error_type": type(error).__name__})
                        raise
                    row.update(repeat=repeat + 1, elapsed_ms=(time.monotonic_ns() - started) / 1e6)
                    self.checks.append(row)
                    print(f"lab {repeat+1}/{self.repeats}: {name} PASS", file=sys.stderr, flush=True)
            self.mutation_checks()
            states = [self.snapshot(identifier) for identifier in self.control_requests]
            require(all(row["missing_outbox"] == 0 for row in states), "Control event/outbox mismatch")
            orphans = sum(sum(a["state"] in {"queued", "running"} for a in row["attempts"]) for row in states)
            require(orphans == 0, "Unresolved control attempts remain")
            require(source_hashes() == self.report["source_sha256"], "Source changed during run")
            self.report.update(status="passed", control_request_count=len(set(self.control_requests)),
                               orphaned_control_attempts=orphans, detected_mutants=len(self.mutants))
        except Exception as error:
            self.report.update(status="failed", error_type=type(error).__name__)
            if isinstance(error, CheckFailed):
                self.report["failure"] = str(error)
        finally:
            finalization_errors = []
            for handle in self.processes:
                try:
                    if handle["process"].poll() is None:
                        handle["process"].kill()
                        handle["process"].wait(timeout=5)
                except Exception as error:
                    finalization_errors.append({"stage": "child_cleanup", "directory": handle["directory"].name,
                                                "error_type": type(error).__name__})
            self.report["process_exit_codes"] = [{"directory": h["directory"].name, "action": h["action"],
                "exit_code": h["process"].returncode} for h in self.processes]
            self.report["all_child_processes_reaped"] = all(h["process"].poll() is not None for h in self.processes)
            try:
                with self.public.connect() as db:
                    self.report["public_after"] = self.public_snapshot(db)
                with Session(self.engine) as db:
                    self.report["lab_reserved_calls_after"] = db.scalar(text("SELECT reserved_calls FROM inference_budget WHERE id='global'"))
                if self.report["public_after"] != self.report["public_before"]:
                    self.report.update(status="failed", failure="Existing runtime changed during lab; investigate concurrent activity")
                if self.report["lab_reserved_calls_after"] != self.report["public_before"]["reserved_calls"]:
                    self.report.update(status="failed", failure="Lab reservation counter changed")
            except Exception as error:
                finalization_errors.append({"stage": "database_verification", "error_type": type(error).__name__})
            if finalization_errors or not self.report["all_child_processes_reaped"]:
                self.report.update(status="failed", finalization_errors=finalization_errors)
            self.report["http"] = {"timings": percentiles([row["ms"] for row in self.http_samples]), "requests": self.http_samples}
            self.report["recovery"] = percentiles(self.recoveries)
            self.report["limitations"] = ["Synthetic provider failures, not live Nebius outages or model quality.",
                "Small local fault matrix, not a production SLA, throughput benchmark or exhaustive security proof.",
                "Recovery uses a shortened lab deadline and explicit client retry, not automatic retry or remote cancellation.",
                "Mutation baselines run only in child memory; lab schema includes intentional defective history.",
                "Metadata-created fixture, not migration/backup/restore or certified sandbox evidence."]
            self.report["finished_at"] = datetime.now(timezone.utc).isoformat()
            with (self.directory / "report.json").open("x") as stream:
                json.dump(self.report, stream, indent=2)
                stream.write("\n")
            self.client.close()
            self.engine.dispose()
            self.public.dispose()
        return self.report
