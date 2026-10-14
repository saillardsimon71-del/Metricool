"""Couche d'accès SQLite (SQLAlchemy 2.x, mode WAL, sessions thread-safe)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings, get_settings
from .models import Base

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _configure_sqlite(engine: Engine) -> None:
    """Active WAL + contraintes FK : fiabilité après crash / coupure Windows."""

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record) -> None:  # pragma: no cover - callback SQLAlchemy
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()


def init_engine(settings: Settings | None = None, *, echo: bool = False) -> Engine:
    """Crée (ou recrée) le moteur global pour la configuration donnée."""
    global _engine, _SessionFactory
    settings = settings or get_settings()
    settings.ensure_dirs()
    engine = create_engine(
        settings.resolved_database_url,
        echo=echo,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30} if settings.resolved_database_url.startswith("sqlite") else {},
    )
    _configure_sqlite(engine)
    _engine = engine
    _SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    return engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _SessionFactory is None:
        init_engine()
    assert _SessionFactory is not None
    return _SessionFactory


def create_all() -> None:
    """Crée le schéma sans migration (première installation / tests)."""
    Base.metadata.create_all(bind=get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session transactionnelle : commit automatique, rollback sur exception."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """Dépendance FastAPI."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
