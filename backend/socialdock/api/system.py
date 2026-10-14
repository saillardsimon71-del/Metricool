"""API système : santé, tableau de bord, capacité des plateformes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import __product__, __version__
from ..connectors.platform_rules import SPECS
from ..services.posts import dashboard_summary
from ..services.scheduler import SchedulerEngine, scheduler_status_dict
from .deps import db_session, get_current_settings, get_scheduler

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "product": __product__, "version": __version__}


@router.get("/api/dashboard")
def dashboard(session: Session = Depends(db_session), engine: SchedulerEngine | None = Depends(get_scheduler)) -> dict[str, Any]:
    summary = dashboard_summary(session)
    summary["scheduler"] = scheduler_status_dict(engine)
    return summary


@router.get("/api/platforms")
def platforms(session: Session = Depends(db_session), settings=Depends(get_current_settings)) -> dict[str, Any]:
    """Capacités réelles par plateforme (source de vérité de l'interface)."""
    from ..connectors.registry import build_connector

    out: dict[str, Any] = {}
    for platform_name, spec in SPECS.items():
        connector = build_connector(platform_name, settings)
        try:
            capabilities = connector.get_capabilities().as_dict()
        finally:
            connector.close()
        out[platform_name] = {
            "label": spec.label,
            "capabilities": capabilities,
            "media_rules": spec.notes,
            "caption_limit": spec.caption_limit,
            "title_limit": spec.title_limit,
        }
    return {"platforms": out}
