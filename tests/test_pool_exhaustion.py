"""Real bounded QueuePool controls; executor results are explicit doubles."""
import pytest
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import sessionmaker

from ownstack.api import app
from ownstack.auth import db_session
from ownstack.models import Evidence,Event
from ownstack.repository_supervisor import worker_loop
from ownstack.repository_worker import ROOT
from conftest import login
from test_repository_cockpit import item,local_repo,fake_executor,work  # noqa: F401


@pytest.fixture
def single_pool(fixture_db):
    # Same actual fixture database, one connection and a short explicit control
    # deadline. PostgreSQL's normal five-second bound is exercised separately.
    engine=create_engine(fixture_db.kw['bind'].url,pool_size=1,max_overflow=0,
                         pool_timeout=.05,connect_args={'check_same_thread':False})
    factory=sessionmaker(bind=engine,expire_on_commit=False)
    yield factory
    engine.dispose()


def test_exhausted_api_pool_returns_private_retryable_status_then_saved_work(client,fixture_db,single_pool):
    headers=login(client,'atlas-engineer')
    def override():
        with single_pool() as db:yield db
    original=app.dependency_overrides[db_session];app.dependency_overrides[db_session]=override
    try:
        before=client.get('/v1/engineering',headers=headers)
        with single_pool.kw['bind'].connect():
            blocked=client.get('/v1/engineering',headers=headers)
            assert blocked.status_code==503 and blocked.headers['Retry-After']=='2'
            assert blocked.json()=={'detail':'Database temporarily unavailable. Retry to check saved progress.'}
        assert client.get('/v1/engineering',headers=headers).json()==before.json()
        assert single_pool.kw['bind'].pool.checkedout()==0
    finally:app.dependency_overrides[db_session]=original


def test_exhausted_worker_pool_cannot_claim_or_duplicate_queued_work(client,fixture_db,single_pool,local_repo,monkeypatch,capsys):
    iid,_,headers,_=item(client)
    queued=client.post(f'/v1/engineering/{iid}/verify',headers=headers).json()
    monkeypatch.setenv('OWNSTACK_AI_MODE','off')
    with single_pool.kw['bind'].connect():
        assert worker_loop(single_pool,local_repo,ROOT/'.private/evaluator-unit-placeholder.jsonl',local_repo/'cache',once=True)==75
    assert 'database_unavailable' in capsys.readouterr().out
    with fixture_db() as db:
        assert db.get(Evidence,queued['id']).result['state']=='queued'
        assert db.scalar(select(func.count()).select_from(Event).where(Event.event_type=='repository.check_started'))==0
    fake_executor(monkeypatch)
    assert work(single_pool,local_repo)
    assert client.get(f'/v1/engineering/{iid}',headers=headers).json()['current_checks_usable']
    with fixture_db() as db:
        assert db.scalar(select(func.count()).select_from(Event).where(Event.event_type=='repository.check_started'))==1
    assert single_pool.kw['bind'].pool.checkedout()==0
