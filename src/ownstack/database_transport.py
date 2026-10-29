"""Bound silent PostgreSQL I/O without guessing an uncertain COMMIT outcome.

Server statement timeouts cannot deliver a reply across a broken connection.
Each synchronous psycopg wait therefore has a wall-clock deadline. On an
operational failure discard the connection, including its pending response;
callers must reload durable state using a fresh transaction. Closing locally
does not prove the server canceled a query or rolled back a COMMIT.
"""
import math
import os

import psycopg


def io_timeout():
    seconds = float(os.getenv('OWNSTACK_DB_IO_TIMEOUT_SECONDS', '15'))
    if not math.isfinite(seconds) or not 1 <= seconds <= 120:
        raise ValueError('Database I/O timeout must be between one and 120 seconds')
    return seconds


def connection_class(seconds):
    """One engine owns its deadline; no global monkeypatch of the driver."""
    class DeadlineConnection(psycopg.Connection):
        def wait(self, gen, interval=.1, timeout=None):
            bound = seconds if timeout is None else min(seconds, timeout)
            try:
                return super().wait(gen, interval=interval, timeout=bound)
            except psycopg.OperationalError:
                # Never cancel-and-reuse an unknown transaction. In particular,
                # COMMIT may have succeeded before its acknowledgement vanished.
                self.close()
                raise

    return DeadlineConnection


def install_deadline(engine):
    from sqlalchemy import event

    bounded = connection_class(io_timeout())

    @event.listens_for(engine, 'do_connect')
    def connect(dialect, record, args, params):
        # Preserve TLS, identity and other URL options. A URL may choose a
        # shorter connect deadline but cannot silently restore an infinite wait.
        given = int(params.get('connect_timeout', 5))
        params = {**params, 'connect_timeout': min(given, 5) if given > 0 else 5}
        return bounded.connect(*args, **params)
