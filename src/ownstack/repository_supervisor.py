"""Local AI-off repository operator with safe process replacement on DB failure.

The supervisor never claims work. Durable ownership belongs to its child, which
exits on database errors so another process can positively prove owner death.
There is no same-PID lease stealing or inference redispatch. Commands are fixed
by the operator CLI, never accepted from an API, repository or model.
"""
import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from sqlalchemy.exc import DBAPIError, SQLAlchemyError, OperationalError, InterfaceError, TimeoutError as PoolTimeoutError

from ownstack.config import Settings
from ownstack.repository_executor import ROOT, private_directory

DATABASE_RETRY = 75
OPERATOR_ERROR = 70


def require_offline():
    settings = Settings()
    if settings.environment != 'local' or settings.ai_mode != 'off' or settings.max_live_calls != 0 or settings.nebius_key:
        raise RuntimeError('Repository supervision requires local AI off, cap zero and no provider key')


def emit(event, **fields):
    print(json.dumps({'event': event, **fields, 'provider_calls': 0}), flush=True)


def worker_loop(factory, directory, evaluator, cache, *, once=False):
    from ownstack.repository_worker import work_once
    require_offline()
    try:
        while True:
            worked = work_once(factory, directory, evaluator, cache)
            if once:
                emit('operator_finished', progressed=worked)
                return 0
            if not worked:
                time.sleep(.5)
    except SQLAlchemyError as error:
        # The outcome may be unknown after COMMIT. The next child reloads durable
        # state; it must not rerun a remembered command or reset an attempt ID.
        transient = (isinstance(error, (OperationalError, InterfaceError, PoolTimeoutError)) or
            isinstance(error, DBAPIError) and (error.connection_invalidated or
                getattr(error.orig, 'sqlstate', None) in {'40001', '40P01'}))
        emit('database_unavailable' if transient else 'operator_attention_required',
             error_type=type(error).__name__, outcome='unknown_reload_saved_state')
        return DATABASE_RETRY if transient else OPERATOR_ERROR
    except Exception as error:
        emit('operator_attention_required', error_type=type(error).__name__)
        return OPERATOR_ERROR


def supervise(command, *, stop=None, initial_delay=1., max_delay=15.):
    """One child at a time; bounded restart rate and explicit stop cleanup.

    A trusted local harness may supply its own observation wrapper as command.
    No shell expansion or remote/user-authored command selection is supported.
    """
    require_offline()
    if not command or any(not isinstance(part, str) for part in command) or not 0 < initial_delay <= max_delay:
        raise ValueError('Use an operator-owned argument vector and positive bounded backoff')
    install_handlers = stop is None
    stop = stop or threading.Event()
    previous = {}
    if install_handlers:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, lambda *_: stop.set())
    delay = initial_delay
    try:
        while not stop.is_set():
            started = time.monotonic()
            child = subprocess.Popen(command)
            emit('operator_child_started', pid=child.pid)
            try:
                while child.poll() is None and not stop.wait(.1):
                    pass
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill(); child.wait(timeout=5)
            code = child.returncode
            emit('operator_child_exited', pid=child.pid, exit_code=code)
            if stop.is_set():
                return 0
            # Logical/configuration errors require inspection instead of a hot
            # crash loop. DB uncertainty and real process death are retried.
            if code != DATABASE_RETRY and code >= 0:
                return code
            if time.monotonic() - started >= 30:
                delay = initial_delay
            emit('operator_retry_wait', delay_seconds=delay)
            if stop.wait(delay):
                return 0
            delay = min(max_delay, delay * 2)
        return 0
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--evaluator', type=Path, default=ROOT / '.private/real-issues-20261025/evaluator/evaluator-only.jsonl')
    parser.add_argument('--cache', type=Path, default=ROOT / '.private/repository-executor-20261025/source-cache')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    require_offline()
    directory = private_directory(args.directory)
    if args.watch and not args.worker:
        command = [sys.executable, '-m', 'ownstack.repository_supervisor', '--worker', '--watch',
                   '--directory', str(directory), '--evaluator', str(args.evaluator), '--cache', str(args.cache)]
        return supervise(command)
    from ownstack.db import SessionLocal
    return worker_loop(SessionLocal, directory, args.evaluator, args.cache, once=not args.watch)


if __name__ == '__main__':
    raise SystemExit(main())
