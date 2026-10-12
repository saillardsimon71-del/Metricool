"""Dépendances partagées : base, configuration, scheduler, sécurité locale."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..security import constant_time_equals, local_api_token

if TYPE_CHECKING:  # pragma: no cover
    from ..services.scheduler import SchedulerEngine


def get_current_settings() -> Settings:
    return get_settings()


def db_session() -> Session:  # pragma: no cover - alias FastAPI
    yield from get_db()


def get_scheduler(request: Request) -> SchedulerEngine | None:
    return getattr(request.app.state, "scheduler", None)


def require_ingest_token(
    x_socialdock_token: str | None = Header(default=None, alias="X-SocialDock-Token"),
    settings: Settings = Depends(get_current_settings),
) -> str:
    """Protège l'API d'ingestion locale (Studio IA) par token.

    Sans ce contrôle, un processus local malveillant pourrait faire lire à
    SocialDock n'importe quel fichier du disque.
    """
    expected = local_api_token(settings)
    if not x_socialdock_token or not constant_time_equals(x_socialdock_token, expected):
        raise HTTPException(status_code=401, detail="Token d'ingestion invalide ou absent.")
    return x_socialdock_token
