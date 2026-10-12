"""API paramètres : préférences, intégrations, token local."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import AppSetting, utcnow
from ..security import local_api_token
from .deps import db_session, get_current_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULT_PREFERENCES: dict[str, Any] = {
    "theme": "dark",
    "language": "fr",
    "timezone": "Europe/Paris",
    "favorite_times": ["09:00", "12:30", "18:00", "20:30"],
    "default_privacy": {"youtube": "private", "tiktok": "SELF_ONLY", "instagram": "public"},
    "demo_mode": True,
    "notifications_enabled": True,
}


def _prefs(session: Session) -> dict[str, Any]:
    row = session.get(AppSetting, "preferences")
    return {**DEFAULT_PREFERENCES, **(row.value if row else {})}


@router.get("")
def get_settings_payload(session: Session = Depends(db_session), settings: Settings = Depends(get_current_settings)) -> dict[str, Any]:
    return {
        "config": settings.public_dict(),
        "preferences": _prefs(session),
        "integrations": {
            "ingest_endpoint": "/api/ingest/video",
            "ingest_token": local_api_token(settings),
            "studio_ai_docs": "/docs/STUDIO_AI_INTEGRATION",
            "note": "Token à transmettre dans l'en-tête X-SocialDock-Token. Ne le partagez jamais.",
        },
    }


@router.patch("/preferences")
def patch_preferences(payload: dict[str, Any], session: Session = Depends(db_session)) -> dict[str, Any]:
    row = session.get(AppSetting, "preferences")
    if row is None:
        row = AppSetting(key="preferences", value={})
        session.add(row)
    merged = {**_prefs(session), **{k: v for k, v in payload.items() if k in DEFAULT_PREFERENCES}}
    row.value = merged
    row.updated_at = utcnow()
    session.commit()
    return {"preferences": merged}


@router.post("/integrations/token/rotate")
def rotate_token(session: Session = Depends(db_session), settings: Settings = Depends(get_current_settings)) -> dict[str, Any]:
    """Régénère le token de l'API locale (révoque l'ancien)."""
    from ..security import _restrict_file  # noqa: PLC2701 — usage interne assumé

    token_file = settings.secrets_dir / "ingest.token"
    import secrets as _secrets

    token = _secrets.token_urlsafe(32)
    settings.ensure_dirs()
    token_file.write_text(token, encoding="utf-8")
    _restrict_file(token_file)
    settings.api_token = token
    return {"ingest_token": token}
