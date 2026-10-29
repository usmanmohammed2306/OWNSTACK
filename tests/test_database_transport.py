"""Driver deadline controls; real wire faults run in the separate local drill."""
import psycopg
import pytest

from ownstack.db import make_engine
from ownstack.database_transport import connection_class, io_timeout


def test_postgres_engine_installs_bounded_driver():
    engine = make_engine('postgresql+psycopg://test:test@127.0.0.1/test')
    try:
        assert list(engine.dialect.dispatch.do_connect), 'No bound on established-connection I/O'
    finally:
        engine.dispose()


@pytest.mark.parametrize('configured', ['0', '-1', '121', 'nan', 'inf', 'garbage'])
def test_invalid_deadlines_fail_at_engine_creation(monkeypatch, configured):
    monkeypatch.setenv('OWNSTACK_DB_IO_TIMEOUT_SECONDS', configured)
    with pytest.raises(ValueError):
        make_engine('postgresql+psycopg://test:test@127.0.0.1/test')


def test_default_is_finite_and_sqlite_is_unchanged(monkeypatch):
    monkeypatch.delenv('OWNSTACK_DB_IO_TIMEOUT_SECONDS', raising=False)
    assert io_timeout() == 15
    engine = make_engine('sqlite:///:memory:')
    try:
        assert not list(engine.dialect.dispatch.do_connect)
    finally:
        engine.dispose()


@pytest.mark.parametrize('requested,expected', [(None, 15), (2, 2), (90, 15), (0, 0)])
def test_wait_preserves_shorter_deadline(monkeypatch, requested, expected):
    calls = []
    def wait(self, generator, **kwargs):
        calls.append(kwargs)
        return 'completed'
    monkeypatch.setattr(psycopg.Connection, 'wait', wait)
    bounded = connection_class(15)
    connection = object.__new__(bounded)
    assert connection.wait(iter(()), timeout=requested) == 'completed'
    assert calls == [{'interval': .1, 'timeout': expected}]


def test_operational_failure_closes_without_retry_or_remote_cancel(monkeypatch):
    closed = []
    error = psycopg.OperationalError('uncertain transaction')
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(psycopg.Connection, 'wait', fail)
    bounded = connection_class(15)
    connection = object.__new__(bounded)
    connection.close = lambda: closed.append(True)
    with pytest.raises(psycopg.OperationalError) as caught:
        connection.wait(iter(()))
    assert caught.value is error and closed == [True]


@pytest.mark.parametrize('given,expected', [('0', 5), ('40', 5), ('2', 2), (None, 5)])
def test_connection_options_preserve_tls_and_bound_connect(monkeypatch, given, expected):
    calls = []
    def connect(cls, *args, **kwargs):
        calls.append(kwargs)
        return 'driver'
    monkeypatch.setattr(psycopg.Connection, 'connect', classmethod(connect))
    engine = make_engine('postgresql+psycopg://test:test@127.0.0.1/test')
    try:
        params = {'sslmode': 'verify-full', 'application_name': 'ownstack'}
        if given is not None:
            params['connect_timeout'] = given
        hook = list(engine.dialect.dispatch.do_connect)[0]
        assert hook(engine.dialect, None, [], params) == 'driver'
        assert calls == [{**params, 'connect_timeout': expected}]
    finally:
        engine.dispose()
