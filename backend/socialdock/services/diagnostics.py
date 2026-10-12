"""Diagnostics : état réel du système, sans jargon ni secret."""

from __future__ import annotations

import logging
import platform as pyplatform
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import __product__, __version__
from ..config import Settings, get_settings
from ..connectors.registry import connector_for_account
from ..models import Account, AnalyticsSample, EventLog, MediaAsset, PostTarget, PublishAttempt, WatchedFolder, utcnow
from ..security import redact
from .ffprobe import version_info
from .scheduler import SchedulerEngine, scheduler_status_dict

log = logging.getLogger(__name__)


def _disk_usage(path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
        return {
            "total_gb": round(usage.total / 1e9, 2),
            "free_gb": round(usage.free / 1e9, 2),
            "used_percent": round(100 * usage.used / usage.total, 1) if usage.total else None,
        }
    except OSError as exc:
        return {"error": str(exc)}


def check_database(session: Session) -> dict[str, Any]:
    info: dict[str, Any] = {"ok": True}
    try:
        info["journal_mode"] = session.execute(text("PRAGMA journal_mode")).scalar()
        info["foreign_keys"] = session.execute(text("PRAGMA foreign_keys")).scalar()
        info["tables"] = len(session.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).all())
        info["integrity"] = session.execute(text("PRAGMA integrity_check")).scalar()
        info["ok"] = info["integrity"] == "ok"
    except Exception as exc:  # noqa: BLE001
        info.update({"ok": False, "error": str(exc)})
    return info


def check_connectors(session: Session, settings: Settings) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for platform_name in ("youtube", "instagram", "tiktok"):
        connector = connector_for_account(Account(platform=platform_name, display_name=platform_name, mode="real"), settings)
        try:
            caps = connector.get_capabilities().as_dict()
        finally:
            connector.close()
        accounts = session.scalars(select(Account).where(Account.platform == platform_name)).all()
        out.append(
            {
                "platform": platform_name,
                "configured": caps["auth_available"],
                "publish_public_available": caps["publish_public"],
                "requires_review": caps["requires_review"],
                "missing_configuration": caps["permissions_missing"],
                "restrictions": caps["restrictions"],
                "accounts": [
                    {
                        "id": a.id,
                        "name": a.display_name,
                        "status": a.status,
                        "mode": a.mode,
                        "last_error": redact(a.last_error),
                        "credentials_expire_at": a.credentials_expire_at.isoformat() if a.credentials_expire_at else None,
                    }
                    for a in accounts
                ],
                "real_validation": "non testé en production (aucun identifiant API fourni)"
                if not caps["auth_available"]
                else "prêt à être testé avec vos identifiants",
            }
        )
    return out


def recent_attempts(session: Session, limit: int = 15) -> list[dict[str, Any]]:
    rows = session.scalars(select(PublishAttempt).order_by(PublishAttempt.started_at.desc()).limit(limit)).all()
    return [
        {
            "attempt_no": a.attempt_no,
            "phase": a.phase,
            "outcome": a.outcome,
            "http_status": a.http_status,
            "detail": redact(a.detail),
            "started_at": a.started_at.isoformat() if a.started_at else None,
            "post_target_id": a.post_target_id,
        }
        for a in rows
    ]


def last_errors(session: Session, limit: int = 10) -> list[dict[str, Any]]:
    rows = session.scalars(select(EventLog).where(EventLog.level == "error").order_by(EventLog.created_at.desc()).limit(limit)).all()
    return [{"message": redact(e.message), "source": e.source, "created_at": e.created_at.isoformat()} for e in rows]


def build_report(session: Session, settings: Settings | None = None, engine: SchedulerEngine | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    db = check_database(session)
    ffmpeg = version_info()
    disk = _disk_usage(settings.data_dir)
    expiring = session.scalars(
        select(Account).where(Account.credentials_expire_at.is_not(None), Account.credentials_expire_at < utcnow() + timedelta(hours=24))
    ).all()
    return {
        "product": __product__,
        "version": __version__,
        "generated_at": utcnow().isoformat(),
        "python": {
            "version": pyplatform.python_version(),
            "executable": sys.executable,
            "platform": pyplatform.platform(),
        },
        "config": settings.public_dict(),
        "database": db,
        "ffmpeg": ffmpeg,
        "scheduler": scheduler_status_dict(engine),
        "disk": disk,
        "connectors": check_connectors(session, settings),
        "counts": {
            "accounts": session.scalar(select(__import__("sqlalchemy").func.count()).select_from(Account)) or 0,
            "media": session.scalar(select(__import__("sqlalchemy").func.count()).select_from(MediaAsset)) or 0,
            "post_targets": session.scalar(select(__import__("sqlalchemy").func.count()).select_from(PostTarget)) or 0,
            "analytics_samples": session.scalar(select(__import__("sqlalchemy").func.count()).select_from(AnalyticsSample)) or 0,
            "watched_folders": session.scalar(select(__import__("sqlalchemy").func.count()).select_from(WatchedFolder)) or 0,
        },
        "credentials_expiring_soon": [
            {"id": a.id, "name": a.display_name, "expires_at": a.credentials_expire_at.isoformat()} for a in expiring
        ],
        "recent_attempts": recent_attempts(session),
        "last_errors": last_errors(session),
        "sqlite_library": sqlite3.sqlite_version,
    }


def human_summary(report: dict[str, Any]) -> str:
    """Version lisible pour l'utilisateur (aucune connaissance technique requise)."""
    lines = [
        f"{report['product']} {report['version']} — rapport du {report['generated_at']}",
        f"Python {report['python']['version']} sur {report['python']['platform']}",
        f"Base de données : {'OK' if report['database'].get('ok') else 'ERREUR'} ({report['database'].get('integrity')}, journal {report['database'].get('journal_mode')})",
        f"FFmpeg : {'disponible' if report['ffmpeg'].get('available') else 'absent (analyse des vidéos désactivée)'}"
        f" ({report['ffmpeg'].get('probe_backend') or 'aucun binaire'})",
        f"Scheduler : {'actif' if report['scheduler'].get('running') else 'arrêté'} — "
        f"{report['scheduler'].get('scheduled_count', 0)} publication(s) programmée(s), "
        f"{report['scheduler'].get('waiting_user_count', 0)} en attente d'action",
        f"Espace disque : {report['disk'].get('free_gb')} Go libres sur {report['disk'].get('total_gb')} Go",
    ]
    for connector in report["connectors"]:
        state = "configuré" if connector["configured"] else "non configuré"
        lines.append(f"{connector['platform']} : {state} — publication publique : {'oui' if connector['publish_public_available'] else 'non'}")
        for missing in connector["missing_configuration"]:
            lines.append(f"   • variable manquante : {missing}")
    if report["last_errors"]:
        lines.append("Dernières erreurs :")
        lines.extend(f"   • {error['message']}" for error in report["last_errors"][:5])
    return "\n".join(lines)


def export_text_report(session: Session, settings: Settings | None = None, engine: SchedulerEngine | None = None) -> str:
    return human_summary(build_report(session, settings, engine))
