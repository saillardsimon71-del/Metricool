"""API diagnostics : état du système, journaux, rapport exportable."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EventLog
from ..security import redact
from ..services.diagnostics import build_report, export_text_report, human_summary
from ..services.scheduler import SchedulerEngine
from .deps import db_session, get_current_settings, get_scheduler

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("")
def report(
    session: Session = Depends(db_session),
    settings=Depends(get_current_settings),
    engine: SchedulerEngine | None = Depends(get_scheduler),
) -> dict[str, Any]:
    return build_report(session, settings, engine)


@router.get("/summary", response_class=PlainTextResponse)
def summary(
    session: Session = Depends(db_session),
    settings=Depends(get_current_settings),
    engine: SchedulerEngine | None = Depends(get_scheduler),
) -> PlainTextResponse:
    return PlainTextResponse(export_text_report(session, settings, engine))


@router.get("/logs")
def logs(limit: int = Query(default=100, ge=1, le=1000), level: str | None = None, session: Session = Depends(db_session)) -> dict[str, Any]:
    stmt = select(EventLog).order_by(EventLog.created_at.desc()).limit(limit)
    if level:
        stmt = stmt.where(EventLog.level == level)
    rows = session.scalars(stmt).all()
    return {
        "items": [
            {
                "id": row.id,
                "level": row.level,
                "source": row.source,
                "message": redact(row.message),
                "data": row.data,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.get("/report.txt", response_class=PlainTextResponse)
def report_text(
    session: Session = Depends(db_session),
    settings=Depends(get_current_settings),
    engine: SchedulerEngine | None = Depends(get_scheduler),
) -> PlainTextResponse:
    return PlainTextResponse(export_text_report(session, settings, engine), media_type="text/plain; charset=utf-8")
