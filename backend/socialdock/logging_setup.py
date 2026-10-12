"""Journalisation : fichier + table ``event_log`` consultable dans Diagnostics."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import EventLog, LogLevel
from .security import redact

_configured = False


def configure_logging(settings: Settings | None = None, level: int = logging.INFO) -> None:
    """Configure le logger racine (console + fichier rotatif)."""
    global _configured
    settings = settings or get_settings()
    settings.ensure_dirs()
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(settings.logs_dir / "socialdock.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    _configured = True


def is_configured() -> bool:
    return _configured


def log_event(
    session: Session,
    *,
    source: str,
    message: str,
    level: str = LogLevel.INFO.value,
    data: dict | None = None,
    commit: bool = True,
) -> EventLog:
    """Écrit un événement métier en base (message expurgé de tout secret)."""
    entry = EventLog(
        level=level,
        source=source,
        message=redact(message) or message,
        data={k: (redact(str(v)) if isinstance(v, str) else v) for k, v in (data or {}).items()},
    )
    session.add(entry)
    if commit:
        session.commit()
    return entry
