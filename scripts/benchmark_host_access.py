"""Paired local synthetic query benchmark. No API, model, or persistent writes.

Uses a connection-local TEMP variations table that shadows the real table only
on this connection. Rolls back on exit. Never creates/reset an inference ledger.
Set OWNSTACK_PERF_DATABASE_URL for loopback PostgreSQL; default is memory SQLite.
"""
import argparse
from datetime import datetime, timedelta, timezone
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import platform
from statistics import median
import time
import tracemalloc
from sqlalchemy import Column, Index, MetaData, Table, create_engine, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
import sqlalchemy
from ownstack.host_access import host_read_decision, candidate_query
from ownstack.models import Variation
from ownstack.policy import Principal, read_decision

ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
PRINCIPAL = Principal("contractor", "atlas", "contractor")


def baseline(db, principal=PRINCIPAL):
    # Exact pre-optimization lookup and pure policy, retained for reproducibility.
    rows = db.scalars(select(Variation).where(Variation.tenant_id == principal.tenant_id,
        Variation.project_id == "atlas-project").order_by(Variation.id)).all()
    return read_decision(principal, "atlas", "atlas-project", rows, AT)


def optimized(db, principal=PRINCIPAL):
    return host_read_decision(db, principal, "atlas", "atlas-project", AT)


def summarize(samples):
    ordered = sorted(samples)
    return {"samples": len(samples), "p50_ms": median(samples) / 1e6,
            "p95_ms": ordered[math.ceil(len(samples) * .95) - 1] / 1e6,
            "min_ms": ordered[0] / 1e6, "max_ms": ordered[-1] / 1e6,
            "raw_ns": samples}


def run(connection, function):
    with Session(bind=connection, expire_on_commit=False) as db:
        return function(db)


def paired(connection, rounds):
    samples = {"baseline": [], "optimized": []}
    functions = {"baseline": baseline, "optimized": optimized}
    for _ in range(5):
        for function in functions.values():
            assert run(connection, function).variation_id == "zz-active"
    for iteration in range(rounds):
        # Alternate order to reduce systematic warm-cache/order bias.
        for name in (["baseline", "optimized"] if iteration % 2 == 0 else ["optimized", "baseline"]):
            started = time.perf_counter_ns()
            decision = run(connection, functions[name])
            samples[name].append(time.perf_counter_ns() - started)
            assert decision.variation_id == "zz-active"
    return {key: summarize(value) for key, value in samples.items()}


def memory_peak(connection, function):
    peaks = []
    for _ in range(3):
        gc.collect()
        tracemalloc.start()
        try:
            run(connection, function)
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
    return {"median_peak_python_bytes": median(peaks), "raw_peaks": peaks}


def budget(connection):
    if connection.dialect.name != "postgresql":
        return None
    # Read only. Temporary fixture has no inference table.
    return connection.execute(text("SELECT reserved_calls FROM public.inference_budget WHERE id='global'")).scalar_one()


def benchmark(rounds, sizes):
    url = make_url(os.getenv("OWNSTACK_PERF_DATABASE_URL", "sqlite://"))
    if url.drivername != "sqlite" and not (url.drivername.startswith("postgresql") and url.host in {"127.0.0.1", "localhost", "db"}):
        raise ValueError("Only memory SQLite or local development PostgreSQL is allowed")
    if url.drivername == "sqlite" and url.database not in {None, "", ":memory:"}:
        raise ValueError("SQLite benchmark must be in memory")
    engine = create_engine(url)
    report = {"captured_at": datetime.now(timezone.utc).isoformat(), "workload": "synthetic host grant lookup plus pure policy, not HTTP",
        "rounds_per_variant_per_size": rounds, "warmups_per_variant": 5,
        "machine": {"system": platform.system(), "release": platform.release(), "architecture": platform.machine(),
                    "python": platform.python_version(), "sqlalchemy": sqlalchemy.__version__, "logical_cpus": os.cpu_count()},
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in
            [ROOT / "src/ownstack/host_access.py", ROOT / "src/ownstack/policy.py", ROOT / "scripts/benchmark_host_access.py"]},
        "ai_calls": 0, "persistent_fixture_writes": 0, "results": []}
    try:
        with engine.connect() as connection:
            report["database"] = connection.dialect.name
            report["database_version"] = list(connection.dialect.server_version_info)
            report["budget_before"] = budget(connection)
            fixture = Table("variations", MetaData(), *[Column(c.name, c.type, primary_key=c.primary_key,
                nullable=c.nullable) for c in Variation.__table__.columns], prefixes=["TEMPORARY"], postgresql_on_commit="DROP")
            fixture.create(connection)
            if connection.dialect.name == "postgresql":
                assert connection.execute(text("SELECT to_regclass('pg_temp.variations') IS NOT NULL")).scalar_one()
            Index("perf_tenant", fixture.c.tenant_id).create(connection)
            Index("perf_project", fixture.c.project_id).create(connection)
            for historical in sizes:
                connection.execute(fixture.delete())
                rows = [dict(id=f"old-{i:08d}", tenant_id="atlas", project_id="atlas-project", viewer_id="contractor",
                    proposal_id=f"proposal-{i}", state="revoked" if i % 2 else "active", starts_at=AT - timedelta(days=2),
                    expires_at=AT - timedelta(days=1), revision=1) for i in range(historical)]
                rows.append(dict(id="zz-active", tenant_id="atlas", project_id="atlas-project", viewer_id="contractor",
                    proposal_id="proposal-active", state="active", starts_at=AT - timedelta(hours=1),
                    expires_at=AT + timedelta(hours=1), revision=1))
                connection.execute(insert(fixture), rows)
                if connection.dialect.name == "postgresql":
                    connection.execute(text("ANALYZE pg_temp.variations"))
                result = {"historical_rows": historical, "total_rows": historical + 1,
                    "materialized_rows": {"baseline": historical + 1, "optimized": 1},
                    "without_candidate_index": paired(connection, rounds)}
                index = Index("perf_read_candidate", fixture.c.tenant_id, fixture.c.project_id, fixture.c.viewer_id,
                    fixture.c.state, fixture.c.expires_at)
                index.create(connection)
                result["with_candidate_index"] = paired(connection, rounds)
                result["python_memory"] = {name: memory_peak(connection, fn) for name, fn in [("baseline", baseline), ("optimized", optimized)]}
                statement = candidate_query(PRINCIPAL, "atlas-project", AT).compile(connection,
                    compile_kwargs={"literal_binds": True})
                explain = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " if connection.dialect.name == "postgresql" else "EXPLAIN QUERY PLAN "
                result["optimized_query_plan"] = [list(row) for row in connection.exec_driver_sql(explain + str(statement)).all()]
                index.drop(connection)
                report["results"].append(result)
            report["budget_after"] = budget(connection)
            assert report["budget_before"] == report["budget_after"]
            connection.rollback()
    finally:
        engine.dispose()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=40)
    parser.add_argument("--sizes", type=int, nargs="+", default=[0, 100, 10000])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 5 <= args.rounds <= 200 or any(not 0 <= n <= 100000 for n in args.sizes):
        parser.error("Use 5..200 rounds and 0..100000 historical rows")
    report = benchmark(args.rounds, args.sizes)
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        with args.output.open("x") as destination:
            destination.write(encoded)
    print(encoded)
