"""Database engine, session factory, and helpers.

SQLAlchemy is configured here once; all other modules import `get_db` for
FastAPI dependency injection or `SessionLocal` for background tasks.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from backend.config import settings

# check_same_thread=False is required for SQLite when used with FastAPI's
# multi-threaded request handling (multiple threads share the same connection).
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
    echo=False,  # set True to log every SQL statement (useful for debugging)
)

# Session factory — each call to SessionLocal() opens a new DB session.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


def get_db():
    """FastAPI dependency that yields a DB session and closes it on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables defined in ORM models (safe to call on every startup)."""
    from backend import models  # noqa: F401 — import triggers model registration
    Base.metadata.create_all(bind=engine)
