"""Concurrency harness guards only; real PostgreSQL schedules are separate."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


spec=importlib.util.spec_from_file_location('release_pg_controls',Path(__file__).resolve().parents[1]/'scripts/run_release_concurrency.py')
controls=importlib.util.module_from_spec(spec);spec.loader.exec_module(controls)


@pytest.fixture
def safe_environment(monkeypatch,tmp_path):
    monkeypatch.setattr(controls,'ROOT',tmp_path)
    for key,value in {'OWNSTACK_AI_MODE':'off','OWNSTACK_MAX_LIVE_CALLS':'0',
                      'NEBIUS_API_KEY':'','NEBIUS_MODEL_ID':'','NEBIUS_PATCH_MODEL_ID':'','DOCKER_HOST':''}.items():
        monkeypatch.setenv(key,value)
    return tmp_path/'.private/release-assurance-20261027/pg-controls/new'


@pytest.mark.parametrize('key,value',[
    ('OWNSTACK_AI_MODE','fixture'),('OWNSTACK_AI_MODE','nebius'),
    ('OWNSTACK_MAX_LIVE_CALLS','1'),('NEBIUS_API_KEY','synthetic'),
    ('NEBIUS_MODEL_ID','synthetic'),('NEBIUS_PATCH_MODEL_ID','synthetic'),
    ('DOCKER_HOST','tcp://remote:2375')])
def test_pg_harness_refuses_live_or_remote_before_tools(safe_environment,monkeypatch,key,value):
    monkeypatch.setenv(key,value)
    monkeypatch.setattr(controls,'run',lambda *a,**kw:pytest.fail('No Docker tool should run'))
    with pytest.raises(ValueError):controls.Campaign(safe_environment)
    assert not safe_environment.exists()


def test_pg_harness_refuses_outside_private_task_directory(safe_environment,monkeypatch,tmp_path):
    monkeypatch.setattr(controls,'run',lambda *a,**kw:pytest.fail('No Docker tool should run'))
    with pytest.raises(ValueError):controls.Campaign(tmp_path/'elsewhere')


def test_pg_harness_rejects_remote_context_without_image_or_resource_commands(safe_environment,monkeypatch):
    calls=[]
    def run(args,**kw):
        calls.append(args)
        return SimpleNamespace(stdout=b'"tcp://remote:2375"')
    monkeypatch.setattr(controls,'run',run)
    with pytest.raises(ValueError):controls.Campaign(safe_environment)
    assert len(calls)==1 and calls[0][:3]==['docker','context','inspect']
    assert not safe_environment.exists()


def test_pg_harness_does_not_overwrite_prior_run(safe_environment,monkeypatch):
    safe_environment.mkdir(parents=True);marker=safe_environment/'saved';marker.write_text('retain')
    calls=[]
    def run(args,**kw):
        calls.append(args)
        return SimpleNamespace(stdout=b'"unix:///local.sock"')
    monkeypatch.setattr(controls,'run',run)
    with pytest.raises(FileExistsError):controls.Campaign(safe_environment)
    assert marker.read_text()=='retain'
    assert all('run' not in args and 'volume' not in args for args in calls)
