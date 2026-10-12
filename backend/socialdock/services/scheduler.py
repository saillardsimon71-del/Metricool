"""Moteur de programmation persistant.

Aucune file en mémoire : l'état vit dans SQLite (``post_targets`` +
``publish_attempts``), ce qui garantit la reprise après redémarrage ou crash.

* **Verrouillage** : ``locked_by`` + ``lock_expires_at`` empêchent toute
  exécution concurrente d'une même cible.
* **Reprise** : au démarrage, les verrous périmés sont libérés et les
  publications interrompues passent en ``uncertain`` (jamais relancées
  aveuglément).
* **Retards** : les tâches dont l'heure est passée sont exécutées au prochain
  tick et journalisées.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_session_factory
from ..logging_setup import log_event
from ..models import EventLog, LogLevel, PostStatus, PostTarget, utcnow
from .publisher import acquire_lock, publish_target, release_lock
from .states import can_transition, set_status

log = logging.getLogger(__name__)

#: Délai au-delà duquel une cible bloquée en cours d'envoi est considérée ambiguë
STALE_LOCK_MINUTES = 20
LATE_GRACE_SECONDS = 60


@dataclass(slots=True)
class TickReport:
    started_at: datetime
    finished_at: datetime | None = None
    due: int = 0
    executed: int = 0
    skipped: int = 0
    errors: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "due": self.due,
            "executed": self.executed,
            "skipped": self.skipped,
            "errors": self.errors,
            "details": self.details,
        }


@dataclass(slots=True)
class SchedulerStatus:
    running: bool = False
    worker_id: str = ""
    started_at: datetime | None = None
    tick_seconds: int = 5
    last_tick: TickReport | None = None
    last_error: str | None = None
    scheduled_count: int = 0
    waiting_user_count: int = 0
    uncertain_count: int = 0
    late_count: int = 0
    next_run_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "worker_id": self.worker_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "tick_seconds": self.tick_seconds,
            "last_tick": self.last_tick.as_dict() if self.last_tick else None,
            "last_error": self.last_error,
            "scheduled_count": self.scheduled_count,
            "waiting_user_count": self.waiting_user_count,
            "uncertain_count": self.uncertain_count,
            "late_count": self.late_count,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "pid": None,
        }


class SchedulerEngine:
    """Boucle de publication : indépendante du navigateur, persistante."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        tick_seconds: int | None = None,
        worker_id: str | None = None,
        notifier: Callable[[str, str, str], None] | None = None,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.tick_seconds = tick_seconds or self.settings.scheduler_tick_seconds
        self.worker_id = worker_id or f"{socket.gethostname()}-main"
        self._task: asyncio.Task | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status = SchedulerStatus(worker_id=self.worker_id, tick_seconds=self.tick_seconds)
        self.notifier = notifier
        self._session_factory = session_factory

    # -- état --------------------------------------------------------------
    @property
    def status(self) -> SchedulerStatus:
        return self._status

    def _session(self) -> Session:
        if self._session_factory is not None:
            return self._session_factory()
        return get_session_factory()()

    # -- cycle de vie ------------------------------------------------------
    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._status.running = True
        self._status.started_at = utcnow()
        self.recover_interrupted()
        self._task = asyncio.create_task(self._loop())
        log.info("Scheduler démarré (worker %s, tick %ss)", self.worker_id, self.tick_seconds)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        self._status.running = False
        self._status.next_run_at = None
        log.info("Scheduler arrêté proprement")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.run_tick)
            except Exception as exc:  # noqa: BLE001 — la boucle ne doit jamais mourir
                self._status.last_error = str(exc)
                log.exception("Échec du tick scheduler")
            self._status.next_run_at = utcnow() + timedelta(seconds=self.tick_seconds)
            try:
                await asyncio.wait_for(self._stop_async(), timeout=self.tick_seconds)
            except asyncio.TimeoutError:
                continue

    async def _stop_async(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(0.1)

    # -- reprise après crash ----------------------------------------------
    def recover_interrupted(self) -> dict[str, int]:
        """Libère les verrous périmés ; les envois interrompus deviennent incertains."""
        session = self._session()
        now = utcnow()
        released = ambiguous = 0
        try:
            stale = session.scalars(
                select(PostTarget).where(
                    PostTarget.locked_by.is_not(None),
                    or_(PostTarget.lock_expires_at.is_(None), PostTarget.lock_expires_at < now),
                )
            ).all()
            for target in stale:
                if target.status in {PostStatus.UPLOADING.value, PostStatus.PROCESSING.value, PostStatus.PUBLISHING.value}:
                    if can_transition(target.status, PostStatus.UNCERTAIN.value):
                        set_status(target, PostStatus.UNCERTAIN.value)
                    else:
                        target.status = PostStatus.UNCERTAIN.value
                    target.requires_user_action = True
                    target.user_action_hint = (
                        "Publication interrompue (arrêt ou crash de SocialDock). "
                        "Vérifiez la plateforme avant de relancer."
                    )
                    ambiguous += 1
                release_lock(session, target)
                released += 1
            if released:
                log_event(
                    session,
                    source="scheduler",
                    message=f"Reprise : {released} verrou(x) libéré(s), {ambiguous} statut(s) incertain(s)",
                    level=LogLevel.WARNING.value,
                )
            self.refresh_counts(session)
            return {"released": released, "ambiguous": ambiguous}
        finally:
            session.close()

    # -- tick --------------------------------------------------------------
    def due_targets(self, session: Session, *, now: datetime | None = None, limit: int = 20) -> list[PostTarget]:
        now = now or utcnow()
        return list(
            session.scalars(
                select(PostTarget)
                .where(
                    PostTarget.status == PostStatus.SCHEDULED.value,
                    PostTarget.scheduled_at.is_not(None),
                    PostTarget.scheduled_at <= now,
                    or_(PostTarget.next_retry_at.is_(None), PostTarget.next_retry_at <= now),
                )
                .order_by(PostTarget.scheduled_at.asc())
                .limit(limit)
            ).all()
        )

    def run_tick(self, *, now: datetime | None = None) -> TickReport:
        report = TickReport(started_at=utcnow())
        with self._lock:
            session = self._session()
            try:
                targets = self.due_targets(session, now=now)
                report.due = len(targets)
                for target in targets:
                    target_id = target.id
                    if not acquire_lock(session, target, self.worker_id):
                        report.skipped += 1
                        report.details.append({"post_target_id": target_id, "result": "verrou tenu par un autre worker"})
                        continue
                    try:
                        session.refresh(target)
                        publish_target(session, target, settings=self.settings, owner=self.worker_id)
                        report.executed += 1
                        report.details.append({"post_target_id": target_id, "result": target.status})
                        self._notify_for(target)
                    except Exception as exc:  # noqa: BLE001
                        report.errors += 1
                        report.details.append({"post_target_id": target_id, "result": "error", "error": str(exc)})
                        log.exception("Échec de publication de %s", target_id)
                    finally:
                        try:
                            release_lock(session, target)
                        except Exception:  # noqa: BLE001
                            session.rollback()
                self.refresh_counts(session)
            finally:
                report.finished_at = utcnow()
                self._status.last_tick = report
                session.close()
        return report

    def _notify_for(self, target: PostTarget) -> None:
        if self.notifier is None:
            return
        if target.status == PostStatus.WAITING_FOR_USER.value:
            self.notifier("Action requise", f"{target.account.display_name} : {target.user_action_hint or 'intervention manuelle nécessaire'}", "warning")
        elif target.status == PostStatus.UNCERTAIN.value:
            self.notifier("Statut incertain", f"{target.account.display_name} : vérifiez la plateforme avant de relancer.", "warning")
        elif target.status == PostStatus.FAILED.value:
            self.notifier("Publication échouée", f"{target.account.display_name} : {target.error_message or 'erreur inconnue'}", "error")
        elif target.status == PostStatus.PUBLISHED.value:
            self.notifier("Publication réussie", f"{target.account.display_name}", "info")

    # -- compteurs ---------------------------------------------------------
    def refresh_counts(self, session: Session) -> None:
        from sqlalchemy import func

        def count(status: str) -> int:
            return int(session.scalar(select(func.count()).select_from(PostTarget).where(PostTarget.status == status)) or 0)

        self._status.scheduled_count = count(PostStatus.SCHEDULED.value)
        self._status.waiting_user_count = count(PostStatus.WAITING_FOR_USER.value)
        self._status.uncertain_count = count(PostStatus.UNCERTAIN.value)
        now = utcnow()
        self._status.late_count = int(
            session.scalar(
                select(func.count())
                .select_from(PostTarget)
                .where(
                    PostTarget.status == PostStatus.SCHEDULED.value,
                    PostTarget.scheduled_at.is_not(None),
                    PostTarget.scheduled_at < now - timedelta(seconds=LATE_GRACE_SECONDS),
                )
            )
            or 0
        )

    # -- détection des tâches manquées ------------------------------------
    def detect_missed(self, session: Session) -> list[dict[str, Any]]:
        now = utcnow()
        rows = session.scalars(
            select(PostTarget).where(
                PostTarget.status == PostStatus.SCHEDULED.value,
                PostTarget.scheduled_at.is_not(None),
                PostTarget.scheduled_at < now - timedelta(seconds=LATE_GRACE_SECONDS),
            )
        ).all()
        return [
            {
                "post_target_id": t.id,
                "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
                "late_seconds": int((now - t.scheduled_at).total_seconds()) if t.scheduled_at else None,
                "account": t.account.display_name if t.account else None,
            }
            for t in rows
        ]


def scheduler_status_dict(engine: SchedulerEngine | None) -> dict[str, Any]:
    if engine is None:
        return SchedulerStatus().as_dict()
    return engine.status.as_dict()


def recent_events(session: Session, limit: int = 50, level: str | None = None) -> list[EventLog]:
    stmt = select(EventLog).order_by(EventLog.created_at.desc()).limit(limit)
    if level:
        stmt = stmt.where(EventLog.level == level)
    return list(session.scalars(stmt).all())


def _tz() -> timezone:
    return timezone.utc
