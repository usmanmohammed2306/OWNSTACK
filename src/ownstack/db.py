from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from ownstack.config import Settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    postgres = url.startswith(('postgresql+psycopg://', 'postgresql://'))
    engine = create_engine(url, pool_pre_ping=True,
        **({'pool_timeout': 5} if postgres else {}),
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if postgres:
        from ownstack.database_transport import install_deadline
        if engine.dialect.driver == 'psycopg':
            install_deadline(engine)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine


engine = make_engine(Settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def transaction(factory=SessionLocal):
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(bind=engine):
    from ownstack import models  # noqa: F401
    from ownstack import repair_models  # noqa: F401
    from ownstack import workspace_models  # noqa: F401
    from ownstack import customer_models  # noqa: F401
    Base.metadata.create_all(bind)
