"""Restore a frozen public-schema dump into a new retained local rehearsal database.

Requires installed pg_dump/pg_restore, AI off, cap zero and an exhausted source
ledger. Never overwrites/drops a database, starts app services or calls a provider.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from ownstack.backup_artifacts import publish_backup, verified_backup
from ownstack.config import Settings
from ownstack.policy import digest


def local_connection(settings):
    url = make_url(settings.database_url)
    if (settings.ai_mode != "off" or settings.max_live_calls != 0
            or url.get_backend_name() != "postgresql"
            or url.host not in {"127.0.0.1", "localhost", "::1", "db"}
            or not url.database or url.query):
        raise ValueError("Explicit local PostgreSQL, AI off, cap zero and no URL query required")
    return {"host": url.host, "port": url.port or 5432, "dbname": url.database,
            "user": url.username, "password": url.password, "connect_timeout": 5,
            "options": "-c timezone=UTC -c statement_timeout=30000"}


def fingerprint(db):
    tables = db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
    state, counts = {}, {}
    for (table,) in tables:
        rows = db.execute(sql.SQL("SELECT * FROM public.{}").format(sql.Identifier(table)))
        columns = [column.name for column in rows.description]
        hashes = sorted(digest(list(row)) for row in rows)
        state[table] = {"columns": columns, "rows": hashes}
        counts[table] = len(hashes)
    return digest(state), counts


def rehearse(settings, directory):
    connection = local_connection(settings)
    dump_tool, restore_tool = shutil.which("pg_dump"), shutil.which("pg_restore")
    if not dump_tool or not restore_tool:
        raise RuntimeError("Install the official PostgreSQL client tools before this rehearsal")
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    directory.chmod(0o700)
    target_name = "ownstack_restore_" + uuid4().hex
    target_note = directory / "target.json"
    target_note.touch(mode=0o600, exist_ok=False)
    target_note.write_text(json.dumps({"target_database": target_name, "purpose": "retained AI-off recovery rehearsal"}))
    env = {"PATH": os.environ.get("PATH", ""), "PGHOST": connection["host"],
           "PGPORT": str(connection["port"]), "PGUSER": connection["user"] or "",
           "PGPASSWORD": connection["password"] or "", "PGCONNECT_TIMEOUT": "5",
           "PGOPTIONS": "-c timezone=UTC -c statement_timeout=30000"}
    with psycopg.connect(**connection) as source:
        source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        budget = source.execute("SELECT reserved_calls FROM public.inference_budget WHERE id='global'").fetchone()[0]
        if budget != 10:
            raise ValueError("This workspace requires its exhausted ten-call source ledger")
        before, counts = fingerprint(source)
        snapshot = source.execute("SELECT pg_export_snapshot()").fetchone()[0]
        def dump(stream):
            subprocess.run([dump_tool, "--format=custom", "--schema=public", "--no-owner", "--no-privileges",
                            "--snapshot=" + snapshot, "--dbname=" + connection["dbname"]],
                           env=env, stdout=stream, stderr=subprocess.PIPE, check=True, timeout=120)
        def validate_archive(stream):
            subprocess.run([restore_tool, '--list'], env=env, stdin=stream,
                           capture_output=True, check=True, timeout=40)
        receipt = publish_backup(directory / 'archive', dump, validate=validate_archive,
            metadata={'snapshot_sha256': before, 'tables': counts, 'reserved_calls': budget})
    with verified_backup(directory / 'archive', receipt['manifest_sha256']) as (stream, _):
        with psycopg.connect(**connection, autocommit=True) as operator:
            operator.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_name)))
        # Generated target, held verified descriptor, and rollback on any restore error.
        subprocess.run([restore_tool, "--schema=public", "--single-transaction", "--exit-on-error", "--no-owner", "--no-privileges",
                        "--dbname=" + target_name],
                       env=env, stdin=stream, capture_output=True, check=True, timeout=120)
    with psycopg.connect(**{**connection, "dbname": target_name}) as target:
        target.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        after, restored_counts = fingerprint(target)
        restored_budget = target.execute("SELECT reserved_calls FROM public.inference_budget WHERE id='global'").fetchone()[0]
        if before != after or counts != restored_counts or restored_budget != budget:
            raise ValueError("Restored snapshot or inference ledger differs")
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "database": "postgresql",
              "target_database": target_name, "snapshot_sha256": before, "restored_sha256": after,
              "tables": len(counts), "rows": sum(counts.values()), "reserved_calls": restored_budget,
              "backup_sha256": receipt['sha256'], "backup_manifest_sha256": receipt['manifest_sha256'],
              "backup_generation": "archive", "transactional_restore": True, "model_calls": 0,
              "target_retained": True, "limit": "Local logical restore, not machine-loss failover or RPO/RTO"}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = rehearse(Settings(), args.private_output)
    except Exception as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__, "model_calls": 0}))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
