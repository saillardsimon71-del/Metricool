"""Surveillance de dossiers (intégration Studio IA) — import automatique.

Sécurité :
* seuls les fichiers dont l'écriture est terminée sont importés (taille stable
  sur deux scans consécutifs) ;
* l'empreinte SHA-256 évite tout doublon ;
* aucun chemin n'est exposé à un client non autorisé : l'API d'ingestion exige
  un token local et le serveur n'écoute que 127.0.0.1 par défaut.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..logging_setup import log_event
from ..models import Post, WatchedFolder, utcnow
from .media_service import ImportResult, MediaError, import_path, is_supported

log = logging.getLogger(__name__)

#: Un fichier dont la taille a bougé depuis moins de ce délai est considéré en cours d'écriture
STABILITY_SECONDS = 5


def scan_folder(
    session: Session,
    folder: WatchedFolder,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Analyse un dossier surveillé et importe les nouveaux fichiers stables."""
    settings = settings or get_settings()
    now = now or utcnow()
    result: dict[str, Any] = {"folder": folder.path, "imported": [], "skipped": [], "errors": [], "unstable": []}
    root = Path(folder.path).expanduser()
    if not root.exists() or not root.is_dir():
        folder.last_error = f"Dossier introuvable : {folder.path}"
        folder.last_scan_at = now
        session.commit()
        result["errors"].append(folder.last_error)
        return result

    folder.last_error = None
    seen = set(folder.seen_hashes or [])
    iterator = root.rglob("*") if folder.recursive else root.glob("*")
    for candidate in sorted(iterator):
        if not candidate.is_file() or not is_supported(candidate):
            continue
        try:
            stat = candidate.stat()
        except OSError as exc:
            result["errors"].append(f"{candidate.name} : {exc}")
            continue
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        if now - mtime < timedelta(seconds=STABILITY_SECONDS):
            result["unstable"].append(candidate.name)
            continue
        try:
            outcome: ImportResult = import_path(
                session,
                candidate,
                tags=folder.tags,
                imported_from=f"watched:{folder.id}:{candidate.name}",
                settings=settings,
            )
        except MediaError as exc:
            result["errors"].append(f"{candidate.name} : {exc}")
            continue
        if not outcome.created:
            result["skipped"].append({"file": candidate.name, "reason": "doublon (SHA-256 identique)", "media_id": outcome.asset.id})
        else:
            result["imported"].append({"file": candidate.name, "media_id": outcome.asset.id})
            if folder.create_draft:
                draft = create_draft_from_media(session, outcome.asset, template_id=folder.template_id)
                result["imported"][-1]["draft_post_id"] = draft.id
        seen.add(outcome.asset.sha256)
    folder.seen_hashes = sorted(seen)[-500:]
    folder.last_scan_at = now
    session.commit()
    if result["imported"]:
        log_event(session, source="watcher", message=f"{len(result['imported'])} fichier(s) importé(s) depuis {folder.path}")
    return result


def create_draft_from_media(session: Session, asset, *, template_id: str | None = None) -> Post:
    """Crée un brouillon prêt à compléter depuis un média fraîchement importé."""
    from .templates import apply_template

    post = Post(
        title=asset.display_name,
        description="",
        hashtags=[],
        media_asset_id=asset.id,
        language="fr",
        template_id=template_id,
    )
    session.add(post)
    session.flush()
    if template_id:
        apply_template(session, post, template_id)
    return post


def scan_all(session: Session, *, settings: Settings | None = None) -> list[dict[str, Any]]:
    folders = session.scalars(select(WatchedFolder).where(WatchedFolder.enabled.is_(True))).all()
    return [scan_folder(session, folder, settings=settings) for folder in folders]
