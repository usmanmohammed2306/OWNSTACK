"""Logical recovery of the existing local fixture through its PostgreSQL tools.

Keeps a read-only exported source snapshot open during pg_dump/fingerprinting.
Restores only to a new retained database. No source migration, overwrite, drop,
inference, external Docker host, credential output or application start.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from uuid import uuid4
from ownstack.policy import digest

ROOT = Path(__file__).resolve().parents[1]


def validate(container, directory):
    if (os.environ.get('OWNSTACK_AI_MODE') != 'off'
            or os.environ.get('OWNSTACK_MAX_LIVE_CALLS') != '0'
            or any(os.environ.get(k) for k in ('NEBIUS_API_KEY', 'NEBIUS_MODEL_ID', 'NEBIUS_PATCH_MODEL_ID'))):
        raise ValueError('Explicit AI-off, cap-zero and empty provider credentials required')
    if not re.fullmatch(r'ownstack[-a-zA-Z0-9_]*', container):
        raise ValueError('Explicit local OwnStack fixture container required')
    directory = directory.resolve()
    if not directory.is_relative_to(ROOT / '.private') or directory.exists():
        raise ValueError('Choose a new private directory')
    if os.environ.get('DOCKER_HOST') and not os.environ['DOCKER_HOST'].startswith('unix://'):
        raise ValueError('Remote Docker hosts are not permitted')
    return directory


class FixturePostgres:
    def __init__(self, container):
        endpoint = subprocess.run(['docker', 'context', 'inspect', '--format', '{{json .Endpoints.docker.Host}}'],
            capture_output=True, check=True, timeout=10).stdout
        if not json.loads(endpoint).startswith('unix://'):
            raise ValueError('Local Unix Docker context required')
        image = subprocess.run(['docker', 'inspect', container, '--format', '{{.Config.Image}}'],
            capture_output=True, check=True, timeout=10).stdout.decode().strip()
        if not re.fullmatch(r'postgres:(16|17)-alpine', image):
            raise ValueError('Expected the owned PostgreSQL fixture image')
        self.prefix = ['docker', 'exec', '-i', '-e', 'PGOPTIONS=-c timezone=UTC -c statement_timeout=30000',
                       container]

    def psql(self, database):
        return self.prefix + ['psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-U', 'ownstack', '-d', database]

    def query(self, database, query, snapshot=None):
        if snapshot:
            if not re.fullmatch(r'[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+', snapshot):
                raise ValueError('Invalid server snapshot identifier')
            query = "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET TRANSACTION SNAPSHOT '" + snapshot + "'; " + query
        result = subprocess.run(self.psql(database) + ['-c', query], capture_output=True, check=True, timeout=40)
        if len(result.stdout) > 32 * 1024 * 1024:
            raise ValueError('Fixture fingerprint output exceeds local rehearsal bound')
        return [json.loads(line) for line in result.stdout.splitlines() if line]

    def fingerprint(self, database, snapshot=None):
        tables = self.query(database,
            "SELECT to_json(tablename) FROM pg_tables WHERE schemaname='public' ORDER BY tablename", snapshot)
        state, counts = {}, {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            columns = self.query(database, "SELECT to_json(column_name) FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='" + table.replace("'", "''") + "' ORDER BY ordinal_position", snapshot)
            rows = self.query(database, 'SELECT to_jsonb(t) FROM public.' + quoted + ' t', snapshot)
            state[table] = {'columns': columns, 'rows': sorted(digest(row) for row in rows)}
            counts[table] = len(rows)
        return digest(state), counts


def rehearse(container, directory):
    directory = validate(container, directory)
    postgres = FixturePostgres(container)
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    directory.chmod(0o700)
    backup = directory / 'backup.dump'
    backup.touch(mode=0o600, exist_ok=False)
    target = 'ownstack_restore_' + uuid4().hex
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'passed': False,
        'target_database': target, 'database': 'postgresql', 'source_snapshot_read_only': True,
        'target_retained': False, 'new_inference_calls': 0,
        'limits': ['Local public-schema logical recovery, not machine-loss failover or an RPO/RTO.',
                   'Restored accounts and code are private; never publish the dump or target credentials.']}
    note = directory / 'report.json'
    note.touch(mode=0o600, exist_ok=False)
    keeper = None
    stage = 'source_snapshot'
    try:
        with tempfile.TemporaryFile() as stderr:
            keeper = subprocess.Popen(postgres.psql('ownstack'), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=stderr, text=True, bufsize=1)
            keeper.stdin.write('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot();\n')
            keeper.stdin.flush()
            snapshot = keeper.stdout.readline().strip()
            budget = postgres.query('ownstack', "SELECT reserved_calls FROM public.inference_budget WHERE id='global'", snapshot)
            if budget != [10]:
                raise ValueError('Existing exhausted source ledger required')
            before, counts = postgres.fingerprint('ownstack', snapshot)
            stage = 'dump'
            with backup.open('wb') as stream:
                subprocess.run(postgres.prefix + ['pg_dump', '-U', 'ownstack', '-d', 'ownstack',
                    '--format=custom', '--schema=public', '--no-owner', '--no-privileges', '--snapshot=' + snapshot],
                    stdout=stream, stderr=subprocess.PIPE, check=True, timeout=90)
            keeper.communicate('ROLLBACK;\n\\q\n', timeout=10)
            if keeper.returncode:
                raise RuntimeError('Source snapshot process failed')
        # Generated identifier only; no caller-selected target or overwrite flag.
        stage = 'create_target'
        postgres.query('ownstack', 'CREATE DATABASE "' + target + '"')
        report['target_retained'] = True
        stage = 'restore'
        with backup.open('rb') as stream:
            subprocess.run(postgres.prefix + ['pg_restore', '-U', 'ownstack', '-d', target,
                '--schema=public', '--exit-on-error', '--no-owner', '--no-privileges'],
                stdin=stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=90)
        stage = 'fingerprint'
        after, restored_counts = postgres.fingerprint(target)
        restored_budget = postgres.query(target, "SELECT reserved_calls FROM inference_budget WHERE id='global'")
        if before != after or counts != restored_counts or restored_budget != [10]:
            raise ValueError('Restored snapshot differs')
        postgres.query(target, "CREATE TABLE recovery_probe (value TEXT NOT NULL); INSERT INTO recovery_probe VALUES ('target-only')")
        if postgres.query('ownstack', "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename='recovery_probe'") != [0]:
            raise ValueError('Source unexpectedly contains the target probe')
        if postgres.query('ownstack', "SELECT reserved_calls FROM inference_budget WHERE id='global'") != [10]:
            raise ValueError('Source ledger changed')
        report.update(passed=True, tables=len(counts), rows=sum(counts.values()),
            snapshot_sha256=before, restored_sha256=after, table_counts=counts,
            reserved_calls=10, independent_target_write=True,
            backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest())
    except Exception as error:
        report['error_type'] = type(error).__name__
        report['failed_stage'] = stage
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            diagnostic = directory / 'private-tool-error.txt'
            diagnostic.touch(mode=0o600, exist_ok=False)
            diagnostic.write_bytes(error.stderr)
    finally:
        if keeper and keeper.poll() is None:
            keeper.kill()
            keeper.wait(timeout=5)
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        note.write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-container', required=True)
    parser.add_argument('--private-output', required=True, type=Path)
    args = parser.parse_args()
    try:
        report = rehearse(args.source_container, args.private_output)
    except Exception as error:
        report = {'passed': False, 'error_type': type(error).__name__, 'new_inference_calls': 0}
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
