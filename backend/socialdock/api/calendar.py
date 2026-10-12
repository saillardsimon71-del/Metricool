"""API calendrier éditorial (vues mois/semaine/jour/liste + glisser-déposer)."""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..models import PostTarget
from ..schemas import ScheduleRequest
from ..services import posts as post_service
from ..services.posts import PostError
from ..services.states import describe_status
from .deps import db_session

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

DEFAULT_TZ = "Europe/Paris"


@router.get("")
def calendar_range(
    start: date,
    end: date,
    account_id: list[str] | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    if (end - start).days > 400:
        raise HTTPException(status_code=400, detail="Plage trop large (400 jours maximum).")
    start_dt = datetime.combine(start, dtime.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end, dtime.max, tzinfo=timezone.utc)
    targets, total = post_service.list_targets(
        session, start=start_dt, end=end_dt, account_ids=account_id, status=status, limit=2000
    )
    by_day: dict[str, list[dict[str, Any]]] = {}
    items: list[dict[str, Any]] = []
    for target in targets:
        if target.scheduled_at is None:
            continue
        entry = _entry(target)
        items.append(entry)
        by_day.setdefault(target.scheduled_at.date().isoformat(), []).append(entry)
    return {
        "timezone": DEFAULT_TZ,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "items": items,
        "by_day": by_day,
        "total": total,
    }


@router.get("/queue")
def queue(limit: int = Query(default=50, ge=1, le=500), session: Session = Depends(db_session)) -> dict[str, Any]:
    targets, _ = post_service.list_targets(session, status=["scheduled", "ready", "waiting_for_user"], limit=limit)
    return {"items": [_entry(t) for t in targets]}


@router.post("/targets/{target_id}/move", response_model=dict[str, Any])
def move_target(target_id: str, payload: ScheduleRequest, session: Session = Depends(db_session)) -> dict[str, Any]:
    """Déplacement depuis le calendrier : les données de la publication sont préservées."""
    target = session.get(PostTarget, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Cible introuvable.")
    try:
        post_service.schedule_target(session, target, payload.scheduled_at)
    except PostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    return {"post_target_id": target.id, "scheduled_at": target.scheduled_at.isoformat(), "status": target.status}


def _entry(target: PostTarget) -> dict[str, Any]:
    post = target.post
    account = target.account
    thumbnail = None
    if post and post.thumbnail is not None:
        thumbnail = f"/api/media/{post.thumbnail.id}/thumbnail"
    elif post and post.media is not None and post.media.thumbnail_path:
        thumbnail = f"/api/media/{post.media.id}/thumbnail"
    return {
        "post_target_id": target.id,
        "post_id": target.post_id,
        "title": post.title if post else None,
        "account_id": target.account_id,
        "account_name": account.display_name if account else None,
        "platform": account.platform if account else None,
        "mode": account.mode if account else None,
        "status": target.status,
        "status_label": describe_status(target.status),
        "scheduled_at": target.scheduled_at.isoformat() if target.scheduled_at else None,
        "published_at": target.published_at.isoformat() if target.published_at else None,
        "thumbnail": thumbnail,
        "remote_url": target.remote_url,
        "requires_user_action": target.requires_user_action,
        "error_message": target.error_message,
    }
