"""Explicit filesystem-failure controls, never real issue-resolution evidence."""
import errno
import json

import pytest

from ownstack.models import Evidence
from ownstack.patch_agent import fixture_patch
from ownstack.runner import patch_hash
from ownstack.verifier_service import run_once
from test_repository_cockpit import item,local_repo,fake_executor,work  # noqa: F401
from test_repository_recovery import controlled_host_identity  # noqa: F401


@pytest.mark.parametrize('code',[errno.ENOSPC,errno.EROFS,errno.EACCES])
def test_failed_verifier_result_write_preserves_incoming_job(tmp_path,monkeypatch,code):
    incoming=tmp_path/'incoming';incoming.mkdir();ident='a'*32;patch=fixture_patch()
    path=incoming/(ident+'.json');path.write_text(json.dumps({'id':ident,'patch':patch,'patch_hash':patch_hash(patch)}))
    monkeypatch.setattr('ownstack.verifier_service.check',lambda patch:{'passed':True,'patch_hash':patch_hash(patch)})
    def fail(*args,**kwargs):raise OSError(code,'controlled storage fault')
    monkeypatch.setattr('ownstack.verifier_service.write_json',fail)
    with pytest.raises(OSError):run_once(tmp_path)
    assert path.is_file(),'Unacknowledged job was deleted after failed result persistence'
    assert not list((tmp_path/'outgoing').glob('*.json'))


@pytest.mark.parametrize('where',['job.json','operator-report.json'])
def test_artifact_failure_saves_honest_blocked_state(client,fixture_db,local_repo,monkeypatch,where):
    import ownstack.repository_worker as worker
    iid,_,headers,_=item(client);ident=client.post(f'/v1/engineering/{iid}/verify',headers=headers).json()['id']
    real=worker.private_json;fake_executor(monkeypatch)
    def fail(path,value):
        if path.name in {where,'operator-failure.json'}:raise OSError(errno.ENOSPC,'controlled storage fault')
        return real(path,value)
    monkeypatch.setattr(worker,'private_json',fail)
    assert work(fixture_db,local_repo)
    detail=client.get(f'/v1/engineering/{iid}',headers=headers).json()
    assert detail['status']=='checks_failed' and not detail['current_checks_usable']
    with fixture_db() as db:
        data=db.get(Evidence,ident).result
        assert data['state']=='blocked' and data['lease_closed'] and data['error_code']


def test_private_publication_failure_leaves_no_partial_target(tmp_path,monkeypatch):
    from ownstack.repository_executor import private_json
    import ownstack.repository_executor as executor
    def fail(*args):raise OSError(errno.ENOSPC,'controlled link publication failure')
    with monkeypatch.context() as patch:
        patch.setattr(executor.os,'link',fail)
        with pytest.raises(OSError):private_json(tmp_path/'claim.json',{'id':'complete'})
    assert list(tmp_path.iterdir())==[]
    private_json(tmp_path/'claim.json',{'id':'complete'})
    with pytest.raises(FileExistsError):private_json(tmp_path/'claim.json',{'id':'replacement'})
    assert json.loads((tmp_path/'claim.json').read_text())=={'id':'complete'}


def test_recovery_receipt_failure_blocks_requeue(client,fixture_db,local_repo,monkeypatch):
    from test_repository_recovery import crashed
    import ownstack.repository_recovery as recovery
    iid,old,headers,_=crashed(client,fixture_db,local_repo,monkeypatch)
    monkeypatch.setattr(recovery,'process_dead',lambda pid:True)
    monkeypatch.setattr(recovery,'cleanup',lambda *args:{'cleanup_verified':True})
    def fail(*args):raise OSError(errno.EROFS,'controlled evidence volume read-only')
    monkeypatch.setattr('ownstack.repository_executor.private_json',fail)
    assert recovery.recover_once(fixture_db,local_repo)
    detail=client.get(f'/v1/engineering/{iid}',headers=headers).json()
    assert not detail['current_checks_usable'] and len(detail['repository']['checks'])==1
    with fixture_db() as db:
        data=db.get(Evidence,old).result
        assert data['state']=='recovery_blocked' and not data['cleanup_verified']
        assert data['recovery_evidence_saved'] is False and not data.get('replacement_check_id')
