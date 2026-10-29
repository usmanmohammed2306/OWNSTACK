"""Source onboarding/CI boundaries. Real container campaigns stay separate."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest
from conftest import login
from ownstack.release_repository import initialize,load,relative,validate_snapshot,MANIFEST
from ownstack.release_executor import snapshot_repository,repository_command
from test_release_journeys import approved_requirement,release_enabled

script=importlib.util.spec_from_file_location('customer_release_cli',Path(__file__).resolve().parents[1]/'scripts/customer_release.py')
cli=importlib.util.module_from_spec(script);script.loader.exec_module(cli)


def repo(tmp_path):
    root=tmp_path/'repo';root.mkdir();(root/'policy.py').write_text('def read(): return 403\n')
    (root/'serve.py').write_text('import policy\n')
    snapshot=initialize(root,name='Customer workspace',entrypoint='serve.py',include=['serve.py','policy.py'])
    return root,snapshot


def test_complete_inventory_is_bound_and_extra_files_are_not_mounted(tmp_path):
    root,snapshot=repo(tmp_path)
    (root/'not-selected.txt').write_text('not mounted')
    assert snapshot_repository(root)==snapshot
    assert set(load(root)[1])=={'policy.py','serve.py'}
    assert validate_snapshot(snapshot).entrypoint=='serve.py'
    command=repository_command(snapshot)('ownstack-release-'+'a'*32,'sha256:'+'b'*64,root)
    assert command[-3:]==['-I','-B','/repo/serve.py']
    assert '--read-only' in command and command[command.index('--network')+1]=='none'
    (root/'policy.py').write_text('def read(): return 200\n')
    assert snapshot_repository(root)['sha256']!=snapshot['sha256']


@pytest.mark.parametrize('path',['../source.py','/etc/passwd','a/../b','a\\b','.env','.env.example','.private/x','src/.git/config',
    '.venv/file.py','secret.pem','keys.key','state.sqlite','a//b','a/./b','ownstack.release.json','a\nx'])
def test_unsafe_inventory_paths_are_refused(path):
    with pytest.raises(ValueError):relative(path)


@pytest.mark.parametrize('mutation',['sha','entrypoint','filehash','extra','missing'])
def test_snapshot_metadata_cannot_substitute_for_source_identity(tmp_path,mutation):
    root,snapshot=repo(tmp_path);bad=deepcopy(snapshot)
    if mutation=='sha':bad['sha256']='f'*64
    elif mutation=='entrypoint':bad['config']['entrypoint']='other.py'
    elif mutation=='filehash':bad['files']['policy.py']='f'*64
    elif mutation=='extra':bad['shell']='echo approved'
    else:bad['files'].pop('policy.py')
    with pytest.raises(ValueError):validate_snapshot(bad)


def test_symlinks_and_overwrite_are_refused_without_execution(tmp_path):
    root,snapshot=repo(tmp_path)
    with pytest.raises(FileExistsError):initialize(root,name='Again',entrypoint='serve.py',include=['serve.py'])
    (root/'policy.py').unlink();(root/'policy.py').symlink_to(root/'serve.py')
    with pytest.raises(ValueError):load(root)


def test_duplicate_manifest_keys_rejected(tmp_path):
    root,_=repo(tmp_path);raw=(root/MANIFEST).read_text()
    (root/MANIFEST).write_text(raw.replace('"version": 1','"version": 1, "version": 1'))
    with pytest.raises(ValueError):load(root)


def test_source_registration_scoped_and_idempotent(client,release_enabled,tmp_path):
    root,snapshot=repo(tmp_path);engineer=login(client,'atlas-engineer')
    body={'project_id':'atlas-project','label':'main','snapshot':snapshot}
    first=client.post('/v1/release/sources',headers=engineer,json=body)
    assert first.status_code==201,first.text
    assert client.post('/v1/release/sources',headers=engineer,json=body).json()==first.json()
    catalog=client.get('/v1/release/sources',headers=engineer).json()
    assert len(catalog)==1 and catalog[0]['file_count']==2
    assert 'files' not in catalog[0] and 'config' not in catalog[0]
    nova=login(client,'nova-admin')
    assert client.get('/v1/release/sources',headers=nova).json()==[]
    assert client.post('/v1/release/sources',headers=nova,json=body).status_code==404
    bad=deepcopy(body);bad['snapshot']['sha256']='0'*64
    assert client.post('/v1/release/sources',headers=engineer,json=bad).status_code==422


def test_sqlite_simultaneous_source_registration_saves_one_record(client, fixture_db, release_enabled, tmp_path):
    """SQLite has no SELECT FOR UPDATE; the local lab still needs deduplication."""
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from ownstack.api import app
    from ownstack.models import ReleaseAudit
    import threading
    _,snapshot=repo(tmp_path);engineer=login(client,'atlas-engineer');barrier=threading.Barrier(8)
    def register(index):
        with TestClient(app) as peer:
            barrier.wait(10)
            response=peer.post('/v1/release/sources',headers=engineer,json={
                'project_id':'atlas-project','label':'peer-'+str(index),'snapshot':snapshot})
            assert response.status_code==201,response.text
            return response.json()
    with ThreadPoolExecutor(max_workers=8) as pool:values=list(pool.map(register,range(8)))
    assert all(value==values[0] for value in values)
    with fixture_db() as db:assert db.query(ReleaseAudit).filter_by(action='source.registered').count()==1


def test_export_receipt_requires_current_approval_and_expires(client,fixture_db,release_enabled):
    req,engineer,_=approved_requirement(client)
    result=client.get('/v1/release/requirements-receipt',params={'project_id':'atlas-project'},headers=engineer)
    assert result.status_code==200,result.text
    raw=json.dumps(result.json()).encode();sha=hashlib.sha256(raw).hexdigest()
    value,specs=cli.receipt(raw,sha)
    assert value['requirement_ids']==[req['id']] and len(specs)==1
    with pytest.raises(ValueError):cli.receipt(raw,'0'*64)
    from ownstack.models import User
    with fixture_db() as db:db.get(User,'atlas-admin').token_version+=1;db.commit()
    assert client.get('/v1/release/requirements-receipt',params={'project_id':'atlas-project'},headers=engineer).status_code==409
    from ownstack.policy import digest
    value['exported_at']=(datetime.now(timezone.utc)-timedelta(minutes=20)).isoformat()
    value['expires_at']=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
    value['receipt_sha256']=digest({k:v for k,v in value.items() if k!='receipt_sha256'})
    stale=json.dumps(value).encode()
    with pytest.raises(ValueError):cli.receipt(stale,hashlib.sha256(stale).hexdigest())
