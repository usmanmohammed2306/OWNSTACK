"""Bounded backup faults in an explicitly labelled networkless PostgreSQL fixture.

Only trusted owned archives are accepted. No API/worker/inference is started.
All destinations are new generated databases; failures and private bytes remain.
The caller creates/removes the disposable fixture and retains the pinned receipt.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import uuid4

from ownstack.backup_artifacts import publish_backup, verified_backup


def execute(args, output):
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    output.chmod(0o700)
    records = []
    def save(name, data):
        fd = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data if isinstance(data, bytes) else json.dumps(data, indent=2).encode())
    def record(name, **details):
        row = {'case': name, **details};records.append(row)
        with (output / 'results.jsonl').open('a') as stream:
            stream.write(json.dumps(row) + '\n')
        return row
    def run(command, *, check=True, timeout=45, **kwargs):
        return subprocess.run(command, capture_output=True, check=check, timeout=timeout, **kwargs)
    if os.environ.get('DOCKER_HOST') and not os.environ['DOCKER_HOST'].startswith('unix://'):
        raise ValueError('Remote Docker hosts are not permitted')
    endpoint = json.loads(run(['docker', 'context', 'inspect', '--format', '{{json .Endpoints.docker.Host}}']).stdout)
    if not endpoint.startswith('unix://'):
        raise ValueError('Local Docker endpoint required')
    info = json.loads(run(['docker', 'inspect', args.fixture_container]).stdout)[0]
    if (info['Config'].get('Labels', {}).get('ownstack.test') != 'backup-integrity-20261027'
            or info['HostConfig']['NetworkMode'] != 'none' or info['NetworkSettings']['Ports']):
        raise ValueError('Explicit networkless disposable backup fixture required')
    if any(os.environ.get(k) for k in ('NEBIUS_API_KEY', 'NEBIUS_MODEL_ID', 'NEBIUS_PATCH_MODEL_ID')):
        raise ValueError('Empty provider credentials required')
    if os.environ.get('OWNSTACK_AI_MODE') != 'off' or os.environ.get('OWNSTACK_MAX_LIVE_CALLS') != '0':
        raise ValueError('Explicit AI off and cap zero required')
    prefix = ['docker', 'exec', '-i', args.fixture_container]
    def sql(db, query):
        return run(prefix + ['psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-U', 'ownstack', '-d', db, '-c', query]).stdout
    def fresh():
        name = 'ownstack_fault_' + uuid4().hex
        sql('ownstack', 'CREATE DATABASE ' + name + ' TEMPLATE template0')
        return name
    def tables(db):
        return int(sql(db, "SELECT count(*) FROM pg_tables WHERE schemaname='public'"))
    if int(sql('ownstack', "SELECT count(*) FROM pg_database WHERE datname LIKE 'ownstack_fault_%'")):
        raise ValueError('Fresh disposable fixture required; retain previous results rather than accumulating databases')
    def restore(stream, db, *, check=True):
        return run(prefix + ['pg_restore', '--single-transaction', '--exit-on-error', '--no-owner', '--no-privileges',
                            '-U', 'ownstack', '-d', db], stdin=stream, check=check)
    def validate(stream):
        run(prefix + ['pg_restore', '--list'], stdin=stream)
    raw = args.source_archive.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.source_sha256:
        raise ValueError('Owned source archive does not match retained receipt')
    receipt = publish_backup(output / 'known-good', lambda stream: stream.write(raw), validate=validate)
    baseline = fresh()
    with verified_backup(output / 'known-good', receipt['manifest_sha256']) as (stream, _):
        restore(stream, baseline)
    def fingerprint(db):
        # Return one consistent read-only statement's public rows, privately hash
        # them on the operator host. No row contents are printed or published.
        query = """BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
        SELECT format('SELECT %L AS name, coalesce(jsonb_agg(to_jsonb(t)), ''[]''::jsonb) AS rows FROM public.%I t', tablename, tablename)
        FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"""
        # One psql session runs generated SELECTs inside the same transaction.
        command = prefix + ['psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-U', 'ownstack', '-d', db]
        query = query[:-1] + '\n\\gexec\nROLLBACK;\n'
        values = run(command, input=query.encode()).stdout.splitlines()
        state = {}
        for line in values:
            name, rows = line.decode().split('|', 1)
            data = json.loads(rows)
            hashes = sorted(hashlib.sha256(json.dumps(r, sort_keys=True, separators=(',', ':')).encode()).hexdigest() for r in data)
            state[name] = {'rows': len(hashes), 'hashes': hashes}
        return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest(), {k:v['rows'] for k,v in state.items()}
    expected, counts = fingerprint(baseline)
    assert len(counts) == 35 and sql(baseline, "SELECT reserved_calls FROM inference_budget WHERE id='global'").strip() == b'0'
    record('trusted_source_restore', passed=True, tables=len(counts), rows=sum(counts.values()), fingerprint=expected)

    # Kill an actual backup writer before archive publication and at the window
    # after archive publication but before the completion marker. Own child only.
    child_code = '''import os,signal,sys
from pathlib import Path
import ownstack.backup_artifacts as a
dest=Path(sys.argv[1]); mode=sys.argv[2]
real=a._sync_directory
def pause():
    (dest/'paused').write_text('owned process waiting');signal.pause()
def sync(path):
    if mode=='after_archive' and (dest/'backup.dump').exists() and not (dest/'manifest.json').exists():pause()
    real(path)
a._sync_directory=sync
def write(stream):
    stream.write(b'PGDMP'+b'x'*8192);stream.flush();os.fsync(stream.fileno())
    if mode=='during_write':pause()
a.publish_backup(dest,write)
'''
    for phase in ('during_write', 'after_archive'):
        generation = output / ('killed-' + phase)
        child = subprocess.Popen([sys.executable, '-c', child_code, str(generation), phase], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 10
            while not (generation / 'paused').exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            assert (generation / 'paused').exists()
            child.kill();stdout, stderr = child.communicate(timeout=5)
            assert child.returncode == -signal.SIGKILL
        finally:
            if child.poll() is None:
                child.kill();child.communicate(timeout=5)
        save('killed-' + phase + '.stderr', stderr)
        assert not (generation / 'manifest.json').exists()
        try:
            with verified_backup(generation, '0' * 64):
                raise AssertionError('Interrupted generation accepted')
        except FileNotFoundError:
            pass
        record('SIGKILL_' + phase, passed=True, marker_absent=True, private_partial_retained=True)

    # Timeout expires only this producer process. Its partial is not committed.
    def slow_writer(stream):
        subprocess.run([sys.executable, '-c', 'import sys,time;sys.stdout.buffer.write(b"partial");sys.stdout.flush();time.sleep(30)'],
                       stdout=stream, stderr=subprocess.PIPE, check=True, timeout=.3)
    try:
        publish_backup(output / 'timed-out', slow_writer)
        raise AssertionError('Timed out producer committed')
    except subprocess.TimeoutExpired:
        assert not (output / 'timed-out/manifest.json').exists()
    record('backup_producer_timeout', passed=True, marker_absent=True)

    # Real pg_dump is killed after emitting bytes. An
    # uncompressed 4 MiB scratch table keeps stdout backpressure deterministic.
    dump_db = fresh()
    sql(dump_db, "CREATE TABLE payload AS SELECT i, repeat(md5(i::text),32) AS value FROM generate_series(1,4096) i")
    def interrupted_dump(stream):
        pidfile='/tmp/ownstack-dump-'+uuid4().hex+'.pid'
        process = subprocess.Popen(prefix+['sh','-c','echo $$ > '+pidfile+'; exec pg_dump -Fc --compress=0 -U ownstack -d '+dump_db],
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            chunk = process.stdout.read(16384);assert len(chunk) == 16384;stream.write(chunk)
            pid=int(run(prefix+['cat',pidfile]).stdout)
            assert run(prefix+['cat','/proc/'+str(pid)+'/comm']).stdout.strip()==b'pg_dump'
            run(prefix+['kill','-KILL',str(pid)])
            tail, stderr = process.communicate(timeout=10);stream.write(tail)
            save('interrupted-pg-dump.stderr', stderr)
            assert process.returncode != 0
            raise subprocess.CalledProcessError(process.returncode, ['pg_dump'], stderr=stderr)
        finally:
            if process.poll() is None:
                process.kill();process.communicate(timeout=5)
    try:
        publish_backup(output / 'interrupted-pg-dump', interrupted_dump)
        raise AssertionError('Interrupted pg_dump committed')
    except subprocess.CalledProcessError:
        assert not (output / 'interrupted-pg-dump/manifest.json').exists()
    record('actual_pg_dump_process_killed', passed=True, marker_absent=True)

    # Corruption detected before creating any target database.
    mutations = {'empty': b'', 'truncated_header': raw[:4], 'truncated_middle': raw[:len(raw)//2],
                 'truncated_tail': raw[:-1], 'header_bitflip': bytes([raw[0]^1])+raw[1:],
                 'body_bitflip': raw[:len(raw)//2]+bytes([raw[len(raw)//2]^1])+raw[len(raw)//2+1:],
                 'appended_bytes': raw+b'extra', 'same_size_replacement': b'x'*len(raw)}
    databases_before = sql('ownstack', 'SELECT count(*) FROM pg_database')
    for name, corrupted in mutations.items():
        folder = output / name
        saved = publish_backup(folder, lambda stream: stream.write(raw))
        (folder / 'backup.dump').write_bytes(corrupted)
        try:
            with verified_backup(folder, saved['manifest_sha256']):
                raise AssertionError('Corruption reached restore')
        except ValueError:
            pass
        record('preflight_' + name, passed=True, database_created=False)
    assert sql('ownstack', 'SELECT count(*) FROM pg_database') == databases_before

    # A valid checksum/TOC does not establish valid data. Seal an intentionally
    # truncated owned archive with its correct new checksum to reach the parser.
    malformed = publish_backup(output / 'sealed-late-corruption', lambda stream: stream.write(raw[:-1]), validate=validate)
    target = fresh()
    with verified_backup(output / 'sealed-late-corruption', malformed['manifest_sha256']) as (stream, _):
        result = restore(stream, target, check=False)
    save('transactional-corrupt-restore.stderr', result.stderr)
    assert result.returncode and tables(target) == 0
    record('late_corruption_transaction_rollback', passed=True, exit_code=result.returncode, public_tables_after=0,
           toc_listing_passed=True, checksum_passed=True)

    # Interrupt restores after the first table was created inside the transaction.
    # The preinstalled DDL gate belongs only to each scratch target, not the app.
    for action in ('cancel', 'terminate'):
        target = fresh();tag = 'ownstack_fault_restore_' + action
        sql(target, """CREATE FUNCTION public.restore_gate() RETURNS event_trigger LANGUAGE plpgsql AS $$
        BEGIN IF TG_TAG='CREATE TABLE' AND to_regclass('public.alembic_version') IS NOT NULL THEN
        PERFORM pg_sleep(20); END IF; END $$;
        CREATE EVENT TRIGGER restore_gate ON ddl_command_start EXECUTE FUNCTION public.restore_gate();""")
        with verified_backup(output / 'known-good', receipt['manifest_sha256']) as (stream, _):
            process = subprocess.Popen(['docker','exec','-i','-e','PGAPPNAME='+tag,args.fixture_container,
                'pg_restore','--single-transaction','--exit-on-error','--no-owner','--no-privileges','-U','ownstack','-d',target],
                stdin=stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+10;pid=None
                while time.monotonic()<deadline:
                    active=sql('ownstack', "SELECT pid FROM pg_stat_activity WHERE application_name='"+tag+"' AND wait_event='PgSleep'").strip()
                    if active:pid=int(active);break
                    if process.poll() is not None:break
                    time.sleep(.05)
                assert pid is not None,'Restore did not reach its deterministic DDL gate'
                operation='pg_cancel_backend' if action=='cancel' else 'pg_terminate_backend'
                assert sql('ownstack', 'SELECT '+operation+'('+str(pid)+')').strip()==b't'
                stdout,stderr=process.communicate(timeout=10)
            finally:
                if process.poll() is None:
                    process.kill();process.communicate(timeout=5)
        save('restore-'+action+'.stderr',stderr)
        assert process.returncode and tables(target)==0
        record('restore_'+action+'_rollback',passed=True,public_tables_after=0,preinstalled_DDL_gate=True)

    # A clean retry is a new generation/target, never reuse a partial destination.
    def dump(stream):
        subprocess.run(prefix+['pg_dump','-Fc','--no-owner','--no-privileges','-U','ownstack','-d',baseline],
                       stdout=stream,stderr=subprocess.PIPE,check=True,timeout=45)
    retry = publish_backup(output / 'successful-retry',dump,validate=validate,
                           metadata={'fingerprint':expected,'counts':counts,'reserved_calls':0})
    target=fresh()
    with verified_backup(output/'successful-retry',retry['manifest_sha256']) as (stream,_):
        restore(stream,target)
    actual,after_counts=fingerprint(target)
    assert actual==expected and counts==after_counts
    assert sql(target,"SELECT reserved_calls FROM inference_budget WHERE id='global'").strip()==b'0'
    assert sql(target,'SELECT count(*) FROM events').strip()==sql(target,'SELECT count(*) FROM outbox').strip()
    record('successful_new_generation_retry',passed=True,tables=len(counts),rows=sum(counts.values()),fingerprint=actual)
    # A valid archive from a different snapshot must fail the expected-state gate.
    wrong=fresh();sql(wrong,'CREATE TABLE unrelated(value text); INSERT INTO unrelated VALUES (\'other snapshot\')')
    def wrong_dump(stream):
        subprocess.run(prefix+['pg_dump','-Fc','--no-owner','--no-privileges','-U','ownstack','-d',wrong],
                       stdout=stream,stderr=subprocess.PIPE,check=True,timeout=45)
    wrong_receipt=publish_backup(output/'wrong-snapshot',wrong_dump,validate=validate,
        metadata={'fingerprint':expected,'counts':counts,'reserved_calls':0})
    wrong_target=fresh()
    with verified_backup(output/'wrong-snapshot',wrong_receipt['manifest_sha256']) as (stream,_):
        restore(stream,wrong_target)
    wrong_state,_=fingerprint(wrong_target)
    assert wrong_state!=expected
    record('semantic_snapshot_mismatch',passed=True,valid_archive_actually_restored=True,accepted_as_expected_restore=False)
    assert fingerprint(baseline)==(expected,counts)
    assert hashlib.sha256(args.source_archive.read_bytes()).hexdigest()==args.source_sha256
    result={'passed':True,'cases':len(records),'all_cases_passed':all(r['passed'] for r in records),
            'source_unchanged':True,'source_archive_sha256':args.source_sha256,'successful_retry':retry,
            'provider_calls':0,'new_inference_calls':0,'fixture_network':'none','no_app_started':True,
            'limits':'Owned synthetic logical backups on one host; no power-loss, hostile SQL or cluster-role recovery guarantee.'}
    save('report.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture-container',required=True)
    parser.add_argument('--source-archive',type=Path,required=True)
    parser.add_argument('--source-sha256',required=True)
    parser.add_argument('--private-output',type=Path,required=True)
    args=parser.parse_args()
    try:
        result=execute(args,args.private_output)
    except Exception as error:
        result={'passed':False,'error_type':type(error).__name__,'new_inference_calls':0}
        if args.private_output.is_dir():
            path=args.private_output/'failure.json'
            if not path.exists():
                path.touch(mode=0o600);path.write_text(json.dumps(result,indent=2))
        print(json.dumps(result));raise
    print(json.dumps({k:v for k,v in result.items() if k!='successful_retry'}))


if __name__=='__main__':
    main()
