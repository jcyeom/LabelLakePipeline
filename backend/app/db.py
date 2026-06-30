"""Database engine / session / Base (design: db_design_prd, backend 절차 1).

MVP uses SQLAlchemy with a generic ``JSON`` column type so the same models run on
SQLite (tests/dev) and PostgreSQL 15 (production). Postgres-only concerns from
db_design_prd.md (RANGE partitioning, append-only triggers, JSONB, arrays) are
documented there and enforced at the *application* layer here (see repositories).
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()

# check_same_thread=False so the FastAPI TestClient (threaded) can share a connection.
_is_sqlite = _settings.database_url.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}
# Pool tuning applies to server DBs (PostgreSQL); SQLite uses its default pool.
_pool_kwargs = (
    {}
    if _is_sqlite
    else {
        "pool_size": _settings.db_pool_size,
        "max_overflow": _settings.db_max_overflow,
        "pool_pre_ping": True,
        "pool_recycle": _settings.db_pool_recycle,
        # Fail fast instead of blocking on an exhausted pool (avoids request stalls).
        "pool_timeout": _settings.db_pool_timeout,
    }
)
engine = create_engine(_settings.database_url, connect_args=_connect_args, future=True, **_pool_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

# Dedicated engine/pool for background batch jobs (fusion/drift/republish). Isolating it
# from the request pool prevents a burst of long-running jobs from starving the API path.
_bg_pool_kwargs = (
    {}
    if _is_sqlite
    else {
        "pool_size": _settings.bg_pool_size,
        "max_overflow": _settings.bg_max_overflow,
        "pool_pre_ping": True,
        "pool_recycle": _settings.db_pool_recycle,
        "pool_timeout": _settings.db_pool_timeout,
    }
)
background_engine = create_engine(
    _settings.database_url, connect_args=_connect_args, future=True, **_bg_pool_kwargs
)
BackgroundSessionLocal = sessionmaker(
    bind=background_engine, autoflush=False, expire_on_commit=False, future=True
)


def init_db() -> None:
    """Create all tables. Production uses Alembic (db_design_prd 절차 11) instead."""
    # Import models so they are registered on Base.metadata before create_all.
    from app.models import orm  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_factory():
    """Dependency returning the background sessionmaker for jobs that open their own
    session after the request completes. Bound to a dedicated pool so batch jobs don't
    starve the request pool. Tests override this to bind to the test engine."""
    return BackgroundSessionLocal
