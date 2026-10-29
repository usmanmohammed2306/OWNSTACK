"""Same-host, bounded crash recovery for local repository checks.

Evidence JSON is the durable lease. Expiry alone never permits takeover: the
original process must be absent on this boot and its exact owned resources must
be cleaned up. This deliberately fails closed across hosts, ambiguous process
identities and Docker outages. It is not distributed exactly-once execution.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import threading
import time
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import DateTime, cast, func, select, update

from ownstack.models import EngineeringItem, Evidence
from ownstack.policy import Principal, aware
from ownstack.service import record

ACTIVE = {'queued', 'running', 'recovering', 'recovery_blocked'}
MAX_RECOVERIES = 2
MAX_CLEANUP_ATTEMPTS = 3


def public_result(row):
    """Tenant exports retain results, never operator ownership/cleanup tokens."""
    if row.kind != 'repository_checks':
        return row.result
    hidden = {'lease_owner', 'lease_pid', 'lease_host', 'recovery_token', 'recovery_pid'}
    return {key: value for key, value in row.result.items() if key not in hidden}


def now(db):
    """Database time avoids clock disagreement between API and operator processes."""
    value = db.scalar(select(func.clock_timestamp() if db.bind.dialect.name == 'postgresql'
                             else func.current_timestamp()))
    return aware(value)


def stamp(value):
    return aware(value).isoformat(timespec='microseconds')


def lease_seconds():
    seconds = int(os.getenv('OWNSTACK_REPOSITORY_LEASE_SECONDS', '30'))
    if not 5 <= seconds <= 60:
        raise ValueError('Repository lease must be between five and sixty seconds')
    return seconds


def recovery_seconds():
    seconds = int(os.getenv('OWNSTACK_REPOSITORY_RECOVERY_SECONDS', '60'))
    if not 5 <= seconds <= 120:
        raise ValueError('Recovery lease must be between five and 120 seconds')
    return seconds


@lru_cache(maxsize=32)
def host_identity(directory):
    """A copied fixture or a different boot must never kill an unrelated PID."""
    try:
        if platform.system() == 'Linux':
            boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        elif platform.system() == 'Darwin':
            boot = subprocess.check_output(['/usr/sbin/sysctl', '-n', 'kern.boottime'], timeout=5,
                                           stderr=subprocess.PIPE).decode().strip()
        else:
            return None
    except (OSError, subprocess.SubprocessError):
        return None  # Checks still work; recovery requires positive ownership proof.
    return hashlib.sha256(f'{platform.node()}|{boot}|{directory.resolve()}'.encode()).hexdigest()


def process_dead(pid):
    if type(pid) is not int or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        state = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, timeout=5)
        return state.returncode == 0 and state.stdout.decode().strip().startswith('Z')
    except ProcessLookupError:
        return True
    except (PermissionError, OSError, subprocess.SubprocessError):
        return False


def claim_metadata(db, directory, data):
    instant = now(db)
    return {**data, 'lease_owner': str(uuid4()), 'lease_pid': os.getpid(),
            'lease_host': host_identity(directory), 'lease_until': stamp(instant + timedelta(seconds=lease_seconds())),
            'heartbeat_at': stamp(instant), 'lease_closed': False,
            'recovery_count': data.get('recovery_count', 0), 'root_check_id': data.get('root_check_id', data['id'])}


def lease_current(data, instant):
    return (data.get('state') == 'running' and not data.get('lease_closed')
            and isinstance(data.get('lease_until'), str)
            and datetime.fromisoformat(data['lease_until']) > aware(instant))


def renew(factory, check_id, owner):
    with factory() as db:
        row = db.scalar(select(Evidence).where(Evidence.id == check_id).with_for_update())
        if not row or row.result.get('lease_owner') != owner or not lease_current(row.result, now(db)):
            return False
        data = deepcopy(row.result)
        instant = now(db)
        if not lease_current(data, instant):
            return False
        # Recheck at the actual SQL write, including time spent waiting for a
        # database lock. A successful old read cannot revive an expired lease.
        unexpired = (cast(Evidence.result['lease_until'].as_string(), DateTime(timezone=True)) > func.clock_timestamp()
                     if db.bind.dialect.name == 'postgresql' else
                     Evidence.result['lease_until'].as_string() > func.strftime('%Y-%m-%dT%H:%M:%f000+00:00', 'now'))
        result = db.execute(update(Evidence).where(Evidence.id == check_id,
            Evidence.result['state'].as_string() == 'running',
            Evidence.result['lease_owner'].as_string() == owner,
            unexpired,
            Evidence.result['lease_until'].as_string() == data['lease_until'])
            .values(result={**data, 'heartbeat_at': stamp(instant),
                            'lease_until': stamp(instant + timedelta(seconds=lease_seconds()))})
            .execution_options(synchronize_session=False))
        db.commit()
        return result.rowcount == 1


class Heartbeat:
    """No inference and no result writes. A lost lease can never be revived."""
    def __init__(self, factory, check_id, owner):
        self.factory, self.check_id, self.owner = factory, check_id, owner
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name='repository-lease')

    def run(self):
        while not self.stop.wait(lease_seconds() / 5):
            try:
                if not renew(self.factory, self.check_id, self.owner):
                    return
            except Exception:
                # A database outage consumes the lease. Never assume renewal.
                continue

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=2)


def _private_read(path, root):
    if (path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
            or any(parent.is_symlink() for parent in path.parents if parent != root and parent.is_relative_to(root))):
        raise ValueError('Unsafe recovery artifact path')
    info = path.stat()
    if not path.is_file() or info.st_mode & 0o077 or info.st_size > 128000:
        raise ValueError('Recovery metadata must be a bounded private file')
    return json.loads(path.read_text())


def _inspect(name):
    result = subprocess.run(['docker', 'inspect', name], capture_output=True, timeout=15)
    if result.returncode == 0:
        return json.loads(result.stdout)[0]
    if b'no such object:' in result.stderr.lower() or b'no such container:' in result.stderr.lower():
        return None
    raise RuntimeError('Docker absence could not be verified')


def cleanup(directory, check_id):
    """Remove only invocation-owned resources after positively proving owner death.

    A missing child record after an invocation is intentionally ambiguous. It
    requires operator inspection instead of an unsafe automatic replay.
    """
    UUID(check_id)
    root = directory.resolve() / check_id
    if root.is_symlink() or not root.resolve().is_relative_to(directory.resolve()):
        raise ValueError('Unsafe recovery job root')
    cleaned = []
    for stage in ('baseline', 'candidate'):
        target = root / 'execution' / stage
        invocation = target / 'invocation.json'
        if not invocation.exists():
            continue  # No execution intent was written, so this stage never spawned.
        data = _private_read(invocation, directory)
        name = data['container']; command = data['argv']
        if (not re.fullmatch(r'ownstack-repo-[a-f0-9]{32}', name)
                or command[:3] != ['docker', 'run', '--name'] or command[3] != name):
            raise ValueError('Unrecognized owned container invocation')
        image = next((part for part in command if re.fullmatch(r'sha256:[a-f0-9]{64}', part)), None)
        if not image:
            raise ValueError('Recovery needs an immutable image identity')
        child = _private_read(target / 'process.json', directory)
        pid = child['pid']
        if type(pid) is not int or pid <= 1 or child['pgid'] != pid or child['argv'] != command:
            raise ValueError('Child process identity does not match invocation')
        container = _inspect(name)
        if container:
            source = str((root / 'execution' / f'{stage}-source').resolve())
            if (container['Image'] != image or container['HostConfig']['NetworkMode'] != 'none'
                    or not container['HostConfig']['ReadonlyRootfs']
                    or not any(m['Source'] == source and m['Destination'] == '/repo' and not m['RW']
                               for m in container['Mounts'])):
                raise ValueError('Container ownership or isolation does not match invocation')
        if not process_dead(pid):
            result = subprocess.run(['ps', '-p', str(pid), '-o', 'args='], capture_output=True, timeout=5)
            # ps renders the embedded trusted Python driver without shell
            # quoting. Only the executable and exact unique name are needed.
            args = result.stdout.decode().strip().split()
            if (result.returncode or not args or Path(args[0]).name not in {'docker', 'com.docker.cli'}
                    or name not in args or 'run' not in args or os.getpgid(pid) != pid):
                raise ValueError('Refusing to kill an ambiguous or reused process identity')
            os.killpg(pid, signal.SIGKILL)
            deadline = time.monotonic() + 5
            while not process_dead(pid) and time.monotonic() < deadline:
                time.sleep(.05)
            if not process_dead(pid):
                raise RuntimeError('Owned Docker client did not stop')
        if container:
            result = subprocess.run(['docker', 'rm', '--force', container['Id']], capture_output=True, timeout=15)
            if result.returncode:
                raise RuntimeError('Owned container removal failed')
        if _inspect(name) is not None:
            raise RuntimeError('Owned container is still present')
        cleaned.append({'stage': stage, 'container': name, 'absent': True, 'client_stopped': True})
    return {'owned_resources': cleaned, 'cleanup_verified': True, 'provider_calls': 0}


def recover_once(factory, directory):
    """Claim cleanup once, verify it outside the transaction, then atomically requeue.

    Lock order is identity/membership (on final authorization), item, evidence.
    A reaper crash itself can be recovered, but only after its lease and death.
    """
    from ownstack.repository_cockpit import context_hash, current_context, enqueue
    from ownstack.repository_executor import private_json
    from ownstack.repository_worker import authorized

    host = host_identity(directory)
    if not host:
        return False
    token = str(uuid4())
    with factory() as db:
        rows = db.scalars(select(Evidence).where(Evidence.kind == 'repository_checks',
            Evidence.result['state'].as_string().in_(['running', 'timed_out', 'recovering', 'recovery_blocked', 'canceled']))
            .order_by(Evidence.created_at, Evidence.id)).all()
        for found in rows:
            data = found.result
            instant = now(db)
            if (not data.get('lease_owner') or data.get('lease_closed') or data.get('lease_host') != host
                    or datetime.fromisoformat(data['lease_until']) > instant or not process_dead(data.get('lease_pid'))):
                continue
            if data.get('recovery_pid') and (datetime.fromisoformat(data['recovery_until']) > instant
                                           or not process_dead(data['recovery_pid'])):
                continue
            if data.get('state') == 'recovery_blocked' and datetime.fromisoformat(data['recovery_until']) > instant:
                continue
            if data.get('recovery_exhausted'):
                continue
            iid, cid = data['item_id'], found.id
            item = db.scalar(select(EngineeringItem).where(EngineeringItem.id == iid)
                             .with_for_update().execution_options(populate_existing=True))
            row = db.scalar(select(Evidence).where(Evidence.id == cid)
                            .with_for_update().execution_options(populate_existing=True))
            # A concurrent operator may have changed the record while we waited.
            if row.result != data or not item:
                db.rollback(); continue
            if data.get('cleanup_attempts', 0) >= MAX_CLEANUP_ATTEMPTS:
                # A reaper can die on its last claim before saving its outcome.
                # Do not leave an immortal "recovering" spinner or silently
                # release the unresolved cleanup fence.
                row.result = {**data, 'state': 'canceled' if data['state'] == 'canceled' else 'recovery_blocked',
                    'recovery_pid': None, 'recovery_exhausted': True, 'accepted': False,
                    'error_code': 'RECOVERY_CLEANUP_LIMIT'}
                record(db, row.tenant_id, row.request_id, 'repository.recovery_exhausted', {'check_id': cid})
                db.commit(); return True
            prior = data['state']
            claimed = {**data, 'state': 'recovering', 'recovery_token': token, 'recovery_pid': os.getpid(),
                       'recovery_until': stamp(instant + timedelta(seconds=recovery_seconds())),
                       'recovery_retry': data.get('recovery_retry', True) and prior != 'canceled',
                       'cleanup_attempts': data.get('cleanup_attempts', 0) + 1,
                       'recovery_requested_at': stamp(instant), 'recovery_prior_state': prior}
            changed = db.execute(update(Evidence).where(Evidence.id == cid,
                Evidence.result['state'].as_string() == prior,
                Evidence.result['lease_owner'].as_string() == data['lease_owner'],
                Evidence.result['recovery_token'].as_string() == data.get('recovery_token'))
                .values(result=claimed).execution_options(synchronize_session=False))
            if changed.rowcount != 1:
                db.rollback(); continue
            record(db, row.tenant_id, row.request_id, 'repository.recovery_started', {'check_id': cid})
            tenant_id, request_id = row.tenant_id, row.request_id
            db.commit(); break
        else:
            return False

    proof = None
    try:
        proof = cleanup(directory, cid)
    except Exception as error:
        proof = {'cleanup_verified': False, 'error_type': type(error).__name__, 'detail': str(error)[:2000], 'provider_calls': 0}
    evidence_saved = True
    try:
        private_json(directory / f'recovery-{token}.json', {'check_id': cid, **proof})
    except OSError:
        # Resource cleanup may have completed, but its required receipt could
        # not be saved. Preserve the pending-cleanup fence and a retryable state.
        evidence_saved = False
        proof = {'cleanup_verified': False, 'error_type': 'RecoveryEvidenceUnavailable', 'provider_calls': 0}

    with factory() as db:
        # Use fresh original actor/team authority. A crash is not new permission.
        actor_ok = authorized(db, data['actor_id'], tenant_id, request_id)
        item = db.scalar(select(EngineeringItem).where(EngineeringItem.id == iid)
                         .with_for_update().execution_options(populate_existing=True))
        row = db.scalar(select(Evidence).where(Evidence.id == cid)
                        .with_for_update().execution_options(populate_existing=True))
        if row.result.get('recovery_token') != token:
            return True
        current = deepcopy(row.result)
        # Cancellation, takeover or a replacement during cleanup always wins.
        selected = (item.patch or {}).get('_verification_id') == cid
        exact = selected and not item.human_decision and item.patch_hash == row.subject_hash
        try:
            current_context(db, item)
            exact = exact and context_hash(item) == data['context_hash']
        except HTTPException:
            exact = False
        eligible = (exact and actor_ok and current['state'] == 'recovering'
                    and current['recovery_retry'] and (item.operation_id == cid
                        or item.status == 'checks_failed' and item.operation_id is None))
        base = {**current, 'recovery_pid': None, 'cleanup_verified': proof['cleanup_verified'],
                'recovery_evidence_saved': evidence_saved}
        if not proof['cleanup_verified']:
            exhausted = current['cleanup_attempts'] >= MAX_CLEANUP_ATTEMPTS
            row.result = {**base, 'state': 'canceled' if current['state'] == 'canceled' else 'recovery_blocked',
                          'error_code': 'RECOVERY_CLEANUP_LIMIT' if exhausted else 'RECOVERY_CLEANUP_UNVERIFIED',
                          'recovery_exhausted': exhausted,
                          'recovery_until': stamp(now(db) + timedelta(seconds=30))}
        else:
            if item.operation_id == cid and item.status == 'checking':
                item.status = 'checks_failed'; item.operation_id = None; item.operation_deadline = None
                db.flush()
            allowed = eligible and data.get('recovery_count', 0) < MAX_RECOVERIES
            row.result = {**base, 'state': 'recovered' if allowed else 'canceled' if
                          current['state'] == 'canceled' or not current['recovery_retry'] else 'blocked',
                          'lease_closed': True, 'accepted': False, 'finished_at': stamp(now(db)),
                          'error_code': 'WORKER_CRASH_RECOVERED' if allowed else
                              'RECOVERY_LIMIT' if eligible else 'RECOVERY_CONTEXT_CHANGED'}
            if allowed:
                db.flush(); db.refresh(item)
                result = enqueue(db, item, Principal(data['actor_id'], row.tenant_id, 'engineer'), retry=True, expected_id=cid)
                replacement = db.get(Evidence, result['id'])
                replacement.result = {**replacement.result, 'recovery_count': data.get('recovery_count', 0) + 1,
                    'root_check_id': data.get('root_check_id', cid), 'previous_check_id': cid}
                row.result = {**row.result, 'replacement_check_id': result['id']}
        record(db, row.tenant_id, row.request_id, 'repository.recovery_finished',
               {'check_id': cid, 'state': row.result['state'], 'replacement_check_id': row.result.get('replacement_check_id')})
        db.commit()
    return True
