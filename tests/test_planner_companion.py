"""Exercise service admission without loading weights or allocating a GPU."""
import importlib.util
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

spec=importlib.util.spec_from_file_location('planner_companion_tests',Path(__file__).resolve().parents[1]/'training/serve_planner.py')
service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service)

def test_missing_identity_or_wrong_identity_never_starts_generation(monkeypatch):
    calls=[];monkeypatch.setattr(service,'generate_plan',lambda c:calls.append(c))
    monkeypatch.delenv('OWNSTACK_PLANNER_SERVICE_TOKEN',raising=False)
    with TestClient(service.app) as client:
        assert client.post('/plan',json={'text':'use violet'}).status_code==503
        monkeypatch.setenv('OWNSTACK_PLANNER_SERVICE_TOKEN','x'*48)
        assert client.post('/plan',json={'text':'use violet'}).status_code==401
        assert client.post('/plan',json={'text':'use violet'},headers={'X-OwnStack-Planner-Key':'wrong'}).status_code==401
        assert client.post('/plan',json={'text':'use violet'},headers={b'X-OwnStack-Planner-Key':b'\xff'}).status_code==401
    assert calls==[]

def test_busy_worker_rejects_without_queueing_or_generating(monkeypatch):
    monkeypatch.setenv('OWNSTACK_PLANNER_SERVICE_TOKEN','x'*48)
    monkeypatch.setattr(service,'runtime',('synthetic-unit-only',)*6)
    assert service.lock.acquire(False)
    try:
        with TestClient(service.app) as client:
            result=client.post('/plan',json={'text':'use violet'},headers={'X-OwnStack-Planner-Key':'x'*48})
            assert result.status_code==429
    finally:service.lock.release()

def test_service_bounds_input_before_dispatch(monkeypatch):
    monkeypatch.setenv('OWNSTACK_PLANNER_SERVICE_TOKEN','x'*48)
    with TestClient(service.app) as client:
        for body in [{'text':'x'*1001},{'text':'ok','tenant_id':'nova'},{'text':True}]:
            assert client.post('/plan',json=body,headers={'X-OwnStack-Planner-Key':'x'*48}).status_code==422
