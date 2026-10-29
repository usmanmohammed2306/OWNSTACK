"""Running-check lifecycle controls use explicit executor doubles, not real code."""
from copy import deepcopy
import json

import pytest

from conftest import login
from ownstack.models import InferenceBudget,TeamMembership,User
from ownstack import repository_release as gate,repository_worker as worker
from test_repository_cockpit import item,fake_executor,work,local_repo
from test_repository_release import approved,enabled,synthetic_report,SOURCE


@pytest.mark.parametrize('change',['approved_revision','draft_only','role','disable','membership','membership_restore','session_version'])
def test_change_during_running_check_fences_old_result(client,fixture_db,local_repo,enabled,monkeypatch,change):
    iid,_,headers,_=item(client);requirement=approved(client)
    base=f'/v1/engineering/{iid}'
    assert client.post(base+'/release-assurance',headers=headers,json={'requirement_ids':[requirement['id']]}).status_code==200
    queued=client.post(base+'/verify',headers=headers).json()
    fake_executor(monkeypatch)
    original=worker.execute
    def execute(case,patch,output,cache,origin):
        assert client.get(base,headers=headers).json()['repository']['checks'][-1]['state']=='running'
        if change=='approved_revision':approved(client,2)
        elif change=='draft_only':
            value={**requirement['spec'],'version':2}
            assert client.post('/v1/release/requirements',headers=headers,json={'project_id':'atlas-project','spec':value}).status_code==201
        else:
            with fixture_db() as db:
                person=db.get(User,'atlas-admin')
                if change=='role':person.role='engineer';person.token_version+=1
                if change=='disable':person.enabled=False;person.token_version+=1
                if change=='session_version':person.token_version+=1
                if change in {'membership','membership_restore'}:
                    member=db.query(TeamMembership).filter_by(user_id=person.id).one()
                    member.enabled=False;member.revision+=1
                db.commit()
            if change=='membership_restore':
                with fixture_db() as db:
                    member=db.query(TeamMembership).filter_by(user_id='atlas-admin').one()
                    member.enabled=True;member.revision+=1;db.commit()
        report=original(case,patch,output,cache,origin)
        (output/'source.json').write_text(json.dumps(SOURCE))
        return {**report,'image_id':SOURCE['image_id']}
    monkeypatch.setattr(worker,'execute',execute)
    monkeypatch.setattr(gate,'run',lambda b,c,coverage,o,**kw:synthetic_report(coverage,SOURCE))
    assert work(fixture_db,local_repo)
    detail=client.get(base,headers=headers).json();check=detail['repository']['checks'][-1]
    if change=='draft_only':
        assert detail['current_checks_usable'] and check['state']=='passed'
    else:
        assert check['state']=='superseded',check
        assert check.get('report') is None and not detail['current_checks_usable']
        exact={'decision':'accept_for_manual_release','patch_hash':detail['patch_hash'],
               'verification_id':queued['id'],'context_hash':detail['repository']['context_hash']}
        assert client.post(base+'/decide',headers=headers,json=exact).status_code==409
        assert client.get(base+'/artifact',headers=headers).status_code==409
    with fixture_db() as db:assert db.get(InferenceBudget,'global').reserved_calls==0
