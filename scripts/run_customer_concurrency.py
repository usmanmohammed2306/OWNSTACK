"""Disposable PostgreSQL customer-authority schedules, with executor doubles.

Requires the existing local postgres image and explicit AI off/cap zero. Never
connects to an existing product database or runs candidate/model code. Retains a
private dump before cleaning up only its newly labeled container and volume.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
import argparse
import json
import time
from uuid import uuid4


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    from run_release_concurrency import Campaign, private, result_double
    root=Path(__file__).resolve().parents[1]
    campaign=Campaign(args.output)
    report={'passed':False,'provider_calls':0,'actual_candidate_execution':False,'executor_double':True}
    try:
        campaign.boot(json.loads((root/'.private/release-assurance-20261027/requirement.json').read_text()))
        from sqlalchemy import select,func,text
        from ownstack.customer_models import CustomerIdentity,CustomerSubmission,CustomerRequestLink
        from ownstack.customers import NewCustomer,LinkProject,Toggle,new_customer,link_project,customer_status,adopt
        from ownstack.release_assurance import (NewRequirement,Approve,create_requirement,approve_requirement,
            current_requirements,NewCheck,create_check,claim_next,finish_check,context_valid,
            lock_project,decide_check_in_transaction,Decide)
        from ownstack.change_agent_contracts import VisibilityPolicy,counterexample_requirements
        from ownstack.models import Project,ReleaseCheck
        from ownstack.service import utcnow
        def prepare(factory):
            with factory() as db:a=new_customer(NewCustomer(name='Synthetic customer',key='synthetic-customer'),campaign.owner,db)
            with factory() as db:link_project(a['id'],LinkProject(project_id='atlas-project',expected_revision=1,enabled=True),campaign.owner,db)
            policy=VisibilityPolicy(roles=['engineer'],requires_assignment=True,temporary_grants=False,visible_fields=['id'],denial_status=403)
            for spec in counterexample_requirements(policy,session_id='pg-customer',customer=a['id'],owner='atlas-engineer',source_ref='local://explicit-pg-control'):
                with factory() as db:r=create_requirement(NewRequirement(project_id='atlas-project',spec=spec,customer_account_id=a['id']),campaign.engineer,db)
                with factory() as db:approve_requirement(r['id'],Approve(expected_hash=r['requirement_hash']),campaign.owner,db)
            return a
        def queue(factory):
            with factory() as db:
                requirements=current_requirements(db,db.get(Project,'atlas-project'),utcnow())
                return create_check(NewCheck(project_id='atlas-project',baseline_sha256='a'*64,candidate_sha256='b'*64,
                    requirement_ids=[r[0] for r in requirements],idempotency_key=uuid4().hex),campaign.engineer,db)
        def disable(factory,a):
            with factory() as db:return customer_status(a['id'],Toggle(expected_revision=1,enabled=False),campaign.owner,db)
        for phase in ('queued','running'):
            factory=campaign.factory();a=prepare(factory);item=queue(factory)
            claim=claim_next(factory,only_id=item['id']) if phase=='running' else None
            disable(factory,a)
            if claim:assert finish_check(factory,item['id'],claim['claim_token'],result_double(claim))
            else:assert claim_next(factory,only_id=item['id']) is None
            saved=campaign.saved(factory,item['id']);assert saved['state']=='blocked' and saved['decision'] is None
            campaign.note('customer_revoked_'+phase,passed=True,state=saved['state'],executor_double=True)
        factory=campaign.factory();a=prepare(factory);item=queue(factory);claim=claim_next(factory,only_id=item['id'])
        assert finish_check(factory,item['id'],claim['claim_token'],result_double(claim))
        saved=campaign.saved(factory,item['id']);started=Event()
        with factory() as review:
            project=lock_project(review,campaign.engineer,'atlas-project')
            current_requirements(review,project,utcnow())  # Holds shared customer authority locks.
            def revoke_waiter():
                with factory() as db:
                    db.execute(text("SET application_name='ownstack-customer-revoke'"));started.set()
                    return customer_status(a['id'],Toggle(expected_revision=1,enabled=False),campaign.owner,db)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(revoke_waiter);assert started.wait(5)
                for _ in range(100):
                    waiting=campaign.sql("SELECT count(*) FROM pg_stat_activity WHERE application_name='ownstack-customer-revoke' AND wait_event_type='Lock'")[0][0]
                    if waiting:break
                    time.sleep(.02)
                else:raise AssertionError('Expected real PostgreSQL customer row-lock wait')
                decide_check_in_transaction(item['id'],Decide(expected_revision=saved['revision'],evidence_hash=saved['evidence_hash'],decision='accept_for_manual_release'),campaign.engineer,review)
                review.commit();assert future.result(timeout=15)['enabled'] is False
        with factory() as db:
            try:context_valid(db,db.get(ReleaseCheck,item['id']))
            except ValueError:pass
            else:raise AssertionError('Later revocation must invalidate reuse of accepted history')
        campaign.note('review_before_revoke_serialized',passed=True,observed_pg_lock_wait=True,accepted_history_retained=True,subsequent_reuse_refused=True,executor_double=True)
        factory=campaign.factory();a=prepare(factory)
        with factory() as db:
            person=CustomerIdentity(id=str(uuid4()),tenant_id='atlas',customer_id=a['id'],username='pg-contact',name='Synthetic contact',password_hash='disabled-fixture-no-usable-password')
            db.add(person);db.flush()
            submission=CustomerSubmission(id=str(uuid4()),tenant_id='atlas',customer_id=a['id'],identity_id=person.id,
                project_id='atlas-project',text='Preserve private customer documents after this refactor.',idempotency_key='one-submission')
            db.add(submission);db.commit();submission_id=submission.id
        def adopt_once(_):
            with factory() as db:return adopt(submission_id,campaign.engineer,db)
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(adopt_once,range(4)))
        assert len({r['request_id'] for r in results})==1
        with factory() as db:assert db.scalar(select(func.count()).select_from(CustomerRequestLink))==1
        campaign.note('four_concurrent_adoptions',passed=True,one_internal_request=True,executor_double=False,actual_candidate_execution=False)
        report.update(passed=True,schedules=4,limitation='Finite real PostgreSQL control schedules; repository execution is explicitly doubled.')
    finally:
        campaign.cleanup();private(campaign.output/'report.json',report)
    print(json.dumps(report))


if __name__=='__main__':main()
