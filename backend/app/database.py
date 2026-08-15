"""SQLAlchemy engine, session factory and the declarative base.

This is the only module that knows how to open a database connection. Routers
receive a ready-made `Session` through the `get_db` dependency and never build
one themselves, which is what guarantees every request's session is closed even
when the handler raises.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# The engine holds a pool of connections and is created exactly once per
# process. Creating one per request would open a TCP connection per request.
if settings.is_sqlite:
    # SQLite's default threading check rejects a connection used by a thread
    # other than the one that created it. FastAPI runs sync endpoints in a
    # thread pool, so that check has to be relaxed for the demo fallback.
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        echo=False,
    )
else:
    engine = create_engine(
        settings.database_url,
        # MySQL closes idle connections after `wait_timeout` (8 hours by
        # default). Without pre-ping, the first request after a long idle
        # period fails with "MySQL server has gone away". Pre-ping costs one
        # cheap round-trip and removes that entire class of bug.
        pool_pre_ping=True,
        # Recycle below MySQL's timeout for the same reason.
        pool_recycle=3600,
        pool_size=5,
        max_overflow=10,
        echo=False,
    )

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class every ORM model inherits from.

    SQLAlchemy collects table definitions on `Base.metadata`, which is what
    `create_all` and Alembic-style tooling read.
    """


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped database session.

    The `finally` block is the important part: it runs whether the endpoint
    returned normally or raised, so a failing request can never leak a
    connection out of the pool.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create any missing tables.

    `database/schema.sql` is the authoritative, human-readable schema and is
    what you run in MySQL Workbench. This function exists so that a fresh
    checkout — or the SQLite fallback, where nobody runs schema.sql — still
    comes up with working tables. `create_all` only creates what is missing; it
    never drops or alters an existing table.
    """
    # Importing the models module registers every table on Base.metadata.
    # Without this import the metadata is empty and create_all does nothing.
    from app import models  # noqa: F401  (imported for its side effects)

    Base.metadata.create_all(bind=engine)
