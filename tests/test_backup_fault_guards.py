"""Operator fault harness must never fall back to a remote or reused fixture."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec=importlib.util.spec_from_file_location('backup_faults',Path(__file__).resolve().parents[1]/'scripts/rehearse_backup_faults.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def args(tmp_path):
    return SimpleNamespace(fixture_container='disposable',source_archive=tmp_path/'never-read',source_sha256='0'*64)


def test_remote_docker_rejected_before_tool_launch(tmp_path,monkeypatch):
    monkeypatch.setenv('DOCKER_HOST','tcp://remote:2375')
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**kw:pytest.fail('No remote tool allowed'))
    with pytest.raises(ValueError,match='Remote Docker'):
        module.execute(args(tmp_path),tmp_path/'private')


@pytest.mark.parametrize('network,label,ports',[('bridge','backup-integrity-20261027',{}),('none','other',{}),('none','backup-integrity-20261027',{'5432/tcp':[{}]})])
def test_nonisolated_fixture_rejected_before_database_commands(tmp_path,monkeypatch,network,label,ports):
    monkeypatch.delenv('DOCKER_HOST',raising=False)
    def run(command,**kw):
        if 'context' in command:return SimpleNamespace(stdout=b'"unix:///local.sock"')
        assert 'inspect' in command,'Must not execute DB commands'
        data=[{'Config':{'Labels':{'ownstack.test':label}},'HostConfig':{'NetworkMode':network},'NetworkSettings':{'Ports':ports}}]
        return SimpleNamespace(stdout=json.dumps(data).encode())
    monkeypatch.setattr(module.subprocess,'run',run)
    with pytest.raises(ValueError,match='networkless'):
        module.execute(args(tmp_path),tmp_path/'private')


def test_reused_fixture_is_refused_before_creating_another_database(tmp_path,monkeypatch):
    monkeypatch.delenv('DOCKER_HOST',raising=False)
    monkeypatch.setenv('OWNSTACK_AI_MODE','off');monkeypatch.setenv('OWNSTACK_MAX_LIVE_CALLS','0')
    def run(command,**kw):
        if 'context' in command:return SimpleNamespace(stdout=b'"unix:///local.sock"')
        if 'inspect' in command:
            return SimpleNamespace(stdout=json.dumps([{'Config':{'Labels':{'ownstack.test':'backup-integrity-20261027'}},'HostConfig':{'NetworkMode':'none'},'NetworkSettings':{'Ports':{}}}]).encode())
        assert command[-1].startswith('SELECT count(*) FROM pg_database'), 'Only read-only freshness query permitted'
        return SimpleNamespace(stdout=b'1\n')
    monkeypatch.setattr(module.subprocess,'run',run)
    with pytest.raises(ValueError,match='Fresh disposable'):
        module.execute(args(tmp_path),tmp_path/'private')
