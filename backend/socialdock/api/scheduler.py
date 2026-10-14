"""API scheduler : état, déclenchement manuel, tâches manquées."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..services.scheduler import SchedulerEngine
from .deps import db_session, get_scheduler

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/status")
def status(engine: SchedulerEngine | None = Depends(get_scheduler), session: Session = Depends(db_session)) -> dict[str, Any]:
    from ..services.scheduler import scheduler_status_dict

    payload = scheduler_status_dict(engine)
    if engine is not None:
        engine.refresh_counts(session)
        payload = scheduler_status_dict(engine)
    return payload


@router.post("/start")
async def start(engine: SchedulerEngine | None = Depends(get_scheduler)) -> dict[str, Any]:
    if engine is None:
        return {"running": False, "message": "Scheduler non initialisé dans ce processus."}
    await engine.start()
    return {"running": engine.status.running, "worker_id": engine.worker_id}


@router.post("/stop")
async def stop(engine: SchedulerEngine | None = Depends(get_scheduler)) -> dict[str, Any]:
    if engine is None:
        return {"running": False, "message": "Scheduler non initialisé dans ce processus."}
    await engine.stop()
    return {"running": engine.status.running}


@router.post("/tick")
def tick(engine: SchedulerEngine | None = Depends(get_scheduler)) -> dict[str, Any]:
    """Exécute un cycle immédiatement (utile pour tester sans attendre)."""
    if engine is None:
        return {"executed": 0, "message": "Scheduler non initialisé dans ce processus."}
    return engine.run_tick().as_dict()


@router.get("/missed")
def missed(engine: SchedulerEngine | None = Depends(get_scheduler), session: Session = Depends(db_session)) -> dict[str, Any]:
    if engine is None:
        return {"missed": []}
    return {"missed": engine.detect_missed(session)}
