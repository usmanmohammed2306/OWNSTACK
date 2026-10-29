"""Separate local operator for durable repository check jobs. Never call a model."""
from copy import deepcopy
from datetime import timedelta
import difflib
import json
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update

from ownstack.config import Settings
from ownstack.models import EngineeringItem, Evidence, User
from ownstack.policy import Principal, aware, digest
from ownstack.team_scope import require_request
from ownstack.repository_cockpit import (
    binding, candidate, context_hash, current_context, expire_check, require_enabled,
)
from ownstack.repository_executor import ROOT, RepositoryCase, execute, private_directory, private_json
from ownstack.service import record, utcnow
from ownstack.repository_recovery import Heartbeat, claim_metadata, lease_current, now, recover_once


def authorized(db, actor_id, tenant_id, request_id):
    actor = db.get(User, actor_id)
    if not (actor and actor.enabled and actor.tenant_id == tenant_id and actor.role == 'engineer'):
        return False
    try:
        require_request(db,Principal(actor.id,tenant_id,actor.role),request_id,write=True)
    except HTTPException:
        return False
    return True


def discard(db,item,row,*,event_type,report=None,code=None,owner=None):
    """Retire only this lease, even if the ORM objects predate a peer retry."""
    db.scalar(select(EngineeringItem).where(EngineeringItem.id==item.id).with_for_update()
        .execution_options(populate_existing=True))
    # The item lock precedes the evidence lock everywhere, including recovery.
    current=db.scalar(select(Evidence).where(Evidence.id==row.id,Evidence.tenant_id==row.tenant_id)
        .with_for_update().execution_options(populate_existing=True))
    data=deepcopy(current.result)
    db.execute(update(EngineeringItem).where(EngineeringItem.id==item.id,
        EngineeringItem.tenant_id==item.tenant_id,EngineeringItem.operation_id==row.id,
        select(Evidence.id).where(Evidence.id==row.id,
            Evidence.result['state'].as_string().in_(['queued','running'])).exists(),
        EngineeringItem.status=='checking').values(status='checks_failed',operation_id=None,
            operation_deadline=None).execution_options(synchronize_session=False))
    # API cancel/retry also writes item before evidence. Read the current terminal
    # state under its row lock; a stale snapshot must not undo cancellation.
    if data['state'] not in {'passed','failed','blocked'}:
        current.result={**data,'state':data['state'] if data['state'] in
            {'canceled','timed_out','superseded','recovering','recovered','recovery_blocked'} else 'superseded',
            'late_result_saved':bool(data.get('late_result_saved') or report is not None),
            'accepted':False,'finished_at':utcnow().isoformat(),
            **({'lease_closed':True} if owner and data.get('lease_owner')==owner and data['state']
               not in {'recovering','recovered','recovery_blocked'} else {}),
            **({'error_code':code} if code and data['state'] in {'queued','running'} else {})}
    record(db,row.tenant_id,row.request_id,event_type,{'check_id':row.id})


def work_once(factory, directory: Path, evaluator: Path, cache: Path) -> bool:
    require_enabled()
    settings = Settings()
    if settings.ai_mode != 'off' or settings.max_live_calls != 0 or settings.nebius_key:
        raise RuntimeError('Repository operator requires AI off, cap zero and no provider key')
    directory = private_directory(directory)
    if not evaluator.resolve().is_relative_to((ROOT / '.private').resolve()):
        raise ValueError('Evaluator answers must remain in the private operator directory')
    if recover_once(factory, directory):
        return True
    with factory() as db:
        # Deadlines survive operator restarts. Never silently turn an abandoned
        # running attempt into pass or dispatch it twice.
        for item in db.scalars(select(EngineeringItem).where(EngineeringItem.status == 'checking')):
            if isinstance(item.patch, dict) and '_repository' in item.patch:
                expire_check(db, item)
        db.commit()
        rows = db.scalars(select(Evidence).where(Evidence.kind == 'repository_checks',
            Evidence.result['state'].as_string() == 'queued').order_by(Evidence.created_at, Evidence.id)).all()
        for row in rows:
            data = deepcopy(row.result)
            item = db.get(EngineeringItem, data['item_id'])
            if not item or item.tenant_id != row.tenant_id or item.request_id != row.request_id:
                continue
            try:
                if not authorized(db, data['actor_id'], row.tenant_id, row.request_id):
                    raise HTTPException(409, 'Stale repository actor')
                # Claim in the same identity -> item -> evidence order as API
                # cancellation and recovery. Reload after waiting for the item.
                item = db.scalar(select(EngineeringItem).where(EngineeringItem.id == item.id)
                    .with_for_update().execution_options(populate_existing=True))
                b = current_context(db, item)
                if (item.operation_id != row.id or item.status != 'checking'
                        or item.patch_hash != row.subject_hash or context_hash(item) != data['context_hash']):
                    raise HTTPException(409, 'Stale repository job')
            except HTTPException:
                discard(db,item,row,event_type='repository.check_superseded',code='CONTEXT_CHANGED')
                db.commit(); return True
            started = claim_metadata(db, directory, {**data, 'state': 'running', 'started_at': utcnow().isoformat(),
                       'deadline': (utcnow() + timedelta(seconds=300)).isoformat()})
            claim = db.execute(update(Evidence).where(Evidence.id == row.id,
                Evidence.kind == 'repository_checks', Evidence.result['state'].as_string() == 'queued')
                .values(result=started).execution_options(synchronize_session=False))
            if claim.rowcount != 1:
                db.rollback(); continue
            item.operation_deadline = utcnow() + timedelta(seconds=300)
            payload = deepcopy(candidate(item)); origin = item.patch['_candidate_origin']
            case_id = b['case_id']; checksum = item.patch_hash; check_id = row.id
            tenant_id = row.tenant_id; request_id = row.request_id; item_id = item.id
            expected_context = data['context_hash']; actor_id = data['actor_id']
            from ownstack.repository_release import bound
            customer_gate=deepcopy(bound(item))
            owner = started['lease_owner']
            record(db, tenant_id, request_id, 'repository.check_started', {'check_id': check_id})
            db.commit(); break
        else:
            return False

    UUID(check_id)  # Only server UUIDs become private artifact path components.
    job_root = None
    report = None; error_code = None
    try:
        job_root = private_directory(directory / check_id)
        private_json(job_root / 'job.json', {'check_id': check_id, 'item_id': item_id,
            'tenant_id': tenant_id, 'request_id': request_id, 'patch_hash': checksum,
            'context_hash': expected_context, 'origin': origin})
        with Heartbeat(factory, check_id, owner):
            case = RepositoryCase.load(ROOT / 'evals/real_issues_v1/cases.jsonl', evaluator, case_id)
            report = execute(case, payload, job_root / 'execution', cache, origin=origin)
            if 'saved_replay' in report:
                raise ValueError('A new job must not adopt another attempt directory')
            if customer_gate is not None:
                from ownstack.repository_release import run,validate
                source=json.loads((job_root/'execution/source.json').read_text())
                report={**report,**{k:source[k] for k in ('baseline_tree_sha256','candidate_tree_sha256')}}
                downstream=run(job_root/'execution/baseline-source',job_root/'execution/candidate-source',
                    customer_gate,job_root/'customer-release',image=report['image_id'],
                    expected_baseline=source['baseline_tree_sha256'],expected_candidate=source['candidate_tree_sha256'])
                verdict=validate(downstream,customer_gate,report)
                report={**report,'upstream_passed':report['passed'],'customer_release':downstream,
                        'passed':report['passed'] and verdict['passed']}
                if not verdict['baseline_valid']:
                    error_code='CUSTOMER_BASELINE_INVALID'
                elif verdict['status']=='blocked':
                    error_code='CUSTOMER_CHECK_BLOCKED'
            differences = []
            for path in sorted({edit['path'] for edit in payload['edits']}):
                old = (job_root / 'execution/baseline-source' / path).read_text()
                new = (job_root / 'execution/candidate-source' / path).read_text()
                differences.extend(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                                       fromfile='a/' + path, tofile='b/' + path))
            report = {**report, 'diff': ''.join(differences), 'diff_hash': digest(''.join(differences)),
                      'patch_hash': checksum, 'runner': 'local-repository-operator', 'stdout': '', 'stderr': ''}
            private_json(job_root / 'operator-report.json', report)
    except Exception as error:
        # Detailed errors remain operator-private. Do not expose local paths,
        # credentials or arbitrary exception text through the web response.
        error_code = 'EXECUTOR_UNAVAILABLE' if report is None else 'INVALID_EXECUTOR_RESULT'
        if isinstance(error, OSError):
            error_code = 'ARTIFACT_STORAGE_UNAVAILABLE'
            report = None
        if job_root is not None:
            try:
                private_json(job_root / 'operator-failure.json', {'error_type': type(error).__name__,
                    'detail': str(error)[:2000], 'provider_calls': 0})
            except OSError:
                pass  # Storage failure cannot prevent the durable DB outcome.

    with factory() as db:
        actor_ok = authorized(db, actor_id, tenant_id, request_id)
        item = db.scalar(select(EngineeringItem).where(EngineeringItem.id==item_id)
            .with_for_update().execution_options(populate_existing=True))
        row = db.scalar(select(Evidence).where(Evidence.id==check_id)
            .with_for_update().execution_options(populate_existing=True))
        data = deepcopy(row.result)
        try:
            current_context(db, item)
            eligible = (item.status == 'checking' and item.operation_id == check_id and item.patch_hash == checksum
                and context_hash(item) == expected_context and data['state'] == 'running'
                and aware(item.operation_deadline) > utcnow() and actor_ok
                and data.get('lease_owner') == owner and lease_current(data, now(db)))
        except HTTPException:
            eligible = False
        if not eligible:
            # A canceled/older answer stays historical. It cannot change the
            # current candidate, newer operation or the user's review controls.
            discard(db,item,row,event_type='repository.late_result_discarded',report=report,owner=owner,code='CONTEXT_CHANGED')
        else:
            if report and report.get('baseline_failed') is not True and not error_code:
                # A broken environment or nonreproducing oracle cannot establish
                # a failed candidate. Keep it blocked and available for takeover.
                error_code = 'BASELINE_NOT_REPRODUCED'
            passed = bool(report and report.get('passed') is True and not error_code)
            state = 'passed' if passed else 'blocked' if error_code else 'failed'
            changed = db.execute(update(EngineeringItem).where(EngineeringItem.id == item_id,
                EngineeringItem.tenant_id == tenant_id, EngineeringItem.operation_id == check_id,
                EngineeringItem.status == 'checking', EngineeringItem.patch_hash == checksum,
                EngineeringItem.operation_deadline > utcnow()).values(status='checks_passed' if passed else 'checks_failed',
                operation_id=None, operation_deadline=None).execution_options(synchronize_session=False))
            if changed.rowcount != 1:
                discard(db,item,row,event_type='repository.late_result_discarded',report=report,owner=owner)
                db.commit();return True
            row.result = {**data, 'state': state, 'report': report, 'receipt_hash': digest(report) if report else None,
                          'error_code': error_code, 'accepted': True, 'lease_closed':True,
                          'finished_at': utcnow().isoformat()}
            record(db, tenant_id, request_id, 'repository.check_finished',
                   {'check_id': check_id, 'state': state, 'patch_hash': checksum})
        db.commit()
    return True
