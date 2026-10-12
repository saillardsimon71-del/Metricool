"""Bibliothèque médias : import, déduplication, métadonnées, validation.

Principes :
* l'original n'est jamais supprimé par défaut (``delete_asset(confirm=True)``
  exigé et confirmé par l'interface) ;
* un même fichier n'est stocké qu'une fois (empreinte SHA-256) ;
* aucune métadonnée n'est inventée : si FFmpeg manque, ``probe_status``
  vaut ``unavailable``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import MediaAsset, PostTarget, utcnow
from ..connectors.platform_rules import get_spec
from .ffprobe import make_thumbnail, probe_file

log = logging.getLogger(__name__)

VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_SUFFIXES = VIDEO_SUFFIXES | IMAGE_SUFFIXES
MAX_IMPORT_BYTES = 8 * 1024 * 1024 * 1024  # garde-fou disque : 8 Go


class MediaError(RuntimeError):
    """Erreur métier de la bibliothèque médias."""


@dataclass(slots=True)
class ImportResult:
    asset: MediaAsset
    created: bool
    duplicate_of: str | None = None


def _safe_stem(name: str) -> str:
    cleaned = re.sub(r"[^\w\-. ]+", "_", Path(name).stem, flags=re.UNICODE).strip()
    return (cleaned or "media")[:120]


def compute_sha256(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_supported(path: str | Path) -> bool:
    return Path(path).suffix.lower() in ALLOWED_SUFFIXES


def _ratio_label(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    from math import gcd

    divisor = gcd(width, height) or 1
    return f"{width // divisor}:{height // divisor}"


def probe_dict(asset: MediaAsset) -> dict[str, Any]:
    """Projection d'un asset vers le dictionnaire attendu par les règles."""
    return {
        "kind": asset.kind,
        "probe_status": asset.probe_status,
        "probe_error": asset.probe_error,
        "mime_type": asset.mime_type,
        "container": None,
        "size_bytes": asset.size_bytes,
        "duration_seconds": asset.duration_seconds,
        "width": asset.width,
        "height": asset.height,
        "fps": asset.fps,
        "video_codec": asset.video_codec,
        "audio_codec": asset.audio_codec,
        "has_audio": asset.has_audio,
    }


def import_path(
    session: Session,
    source: str | Path,
    *,
    display_name: str | None = None,
    tags: Iterable[str] | None = None,
    collections: Iterable[str] | None = None,
    move: bool = False,
    imported_from: str | None = None,
    generate_thumbnail: bool = True,
    original_name: str | None = None,
    settings: Settings | None = None,
) -> ImportResult:
    """Importe un fichier local dans la bibliothèque (copie par défaut)."""
    settings = settings or get_settings()
    source_path = Path(source).expanduser()
    if not source_path.exists() or not source_path.is_file():
        raise MediaError(f"Fichier introuvable : {source_path}")
    if not is_supported(source_path):
        raise MediaError(
            f"Format non supporté : « {source_path.suffix} ». Formats acceptés : "
            f"{', '.join(sorted(ALLOWED_SUFFIXES))}."
        )
    size = source_path.stat().st_size
    if size == 0:
        raise MediaError("Le fichier est vide (0 octet).")
    if size > MAX_IMPORT_BYTES:
        raise MediaError(f"Fichier trop volumineux pour l'import local ({size / 1_000_000_000:.1f} Go > 8 Go).")

    sha = compute_sha256(source_path)
    existing = session.scalar(select(MediaAsset).where(MediaAsset.sha256 == sha))
    if existing is not None:
        log.info("Doublon détecté pour %s (asset %s)", source_path.name, existing.id)
        return ImportResult(asset=existing, created=False, duplicate_of=existing.id)

    settings.ensure_dirs()
    stored_name = f"{sha[:12]}_{_safe_stem(source_path.name)}{source_path.suffix.lower()}"
    destination = settings.media_dir / stored_name
    if move:
        shutil.move(str(source_path), destination)
    else:
        shutil.copy2(source_path, destination)

    probe = probe_file(destination)
    asset = MediaAsset(
        stored_path=stored_name,
        original_name=original_name or source_path.name,
        display_name=display_name or _safe_stem(source_path.name),
        kind=probe.kind,
        mime_type=probe.mime_type,
        size_bytes=size,
        sha256=sha,
        duration_seconds=probe.duration_seconds,
        width=probe.width,
        height=probe.height,
        fps=probe.fps,
        video_codec=probe.video_codec,
        audio_codec=probe.audio_codec,
        has_audio=probe.has_audio,
        probe_status=probe.probe_status,
        probe_error=probe.probe_error,
        tags=sorted({t.strip() for t in (tags or []) if t and t.strip()}),
        collections=sorted({c.strip() for c in (collections or []) if c and c.strip()}),
        imported_from=imported_from or str(source_path),
    )
    if probe.extra.get("container"):
        asset.collections = asset.collections  # conteneur conservé via mime_type
    if generate_thumbnail and probe.kind == "video":
        thumb_name = f"{asset.sha256[:12]}.jpg"
        if make_thumbnail(destination, settings.thumbnails_dir / thumb_name):
            asset.thumbnail_path = thumb_name
    session.add(asset)
    session.flush()
    log.info("Média importé : %s (%s, %s octets)", asset.display_name, asset.id, size)
    return ImportResult(asset=asset, created=True)


def import_bytes(
    session: Session,
    data: bytes,
    filename: str,
    *,
    display_name: str | None = None,
    tags: Iterable[str] | None = None,
    imported_from: str | None = None,
    settings: Settings | None = None,
) -> ImportResult:
    """Importe un flux (téléversement HTTP ou API d'ingestion locale)."""
    if not filename or not is_supported(filename):
        raise MediaError(f"Format non supporté : « {filename} ».")
    if len(data) == 0:
        raise MediaError("Contenu vide.")
    settings = settings or get_settings()
    settings.ensure_dirs()
    tmp = settings.data_dir / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    staging = tmp / f"upload_{Path(filename).name}"
    staging.write_bytes(data)
    try:
        return import_path(
            session,
            staging,
            display_name=display_name,
            tags=tags,
            imported_from=imported_from or f"upload:{filename}",
            original_name=filename,
            settings=settings,
        )
    finally:
        staging.unlink(missing_ok=True)


def refresh_metadata(session: Session, asset: MediaAsset, settings: Settings | None = None) -> MediaAsset:
    """Relance l'analyse technique (après installation de FFmpeg, par exemple)."""
    settings = settings or get_settings()
    path = settings.safe_media_path(asset.stored_path)
    probe = probe_file(path)
    asset.probe_status = probe.probe_status
    asset.probe_error = probe.probe_error
    asset.duration_seconds = probe.duration_seconds
    asset.width = probe.width
    asset.height = probe.height
    asset.fps = probe.fps
    asset.video_codec = probe.video_codec
    asset.audio_codec = probe.audio_codec
    asset.has_audio = probe.has_audio
    asset.mime_type = probe.mime_type or asset.mime_type
    if asset.thumbnail_path is None and probe.kind == "video":
        thumb_name = f"{asset.sha256[:12]}.jpg"
        if make_thumbnail(path, settings.thumbnails_dir / thumb_name):
            asset.thumbnail_path = thumb_name
    session.flush()
    return asset


def list_assets(
    session: Session,
    *,
    query: str | None = None,
    kind: str | None = None,
    tags: Iterable[str] | None = None,
    sort: str = "created_desc",
    limit: int = 60,
    offset: int = 0,
) -> tuple[list[MediaAsset], int]:
    stmt = select(MediaAsset)
    if kind:
        stmt = stmt.where(MediaAsset.kind == kind)
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where(or_(MediaAsset.display_name.ilike(like), MediaAsset.original_name.ilike(like), MediaAsset.notes.ilike(like)))
    if tags:
        # Filtre JSON appliqué en Python : portable SQLite/PostgreSQL et lisible.
        wanted = {t for t in tags if t}
        rows = [r for r in session.scalars(stmt).all() if wanted.issubset(set(r.tags or []))]
        return rows[offset : offset + limit], len(rows)

    order = {
        "created_desc": MediaAsset.created_at.desc(),
        "created_asc": MediaAsset.created_at.asc(),
        "name_asc": MediaAsset.display_name.asc(),
        "size_desc": MediaAsset.size_bytes.desc(),
        "duration_desc": MediaAsset.duration_seconds.desc(),
    }.get(sort, MediaAsset.created_at.desc())
    # Le total doit refléter les filtres appliqués, pas la table entière.
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.order_by(order).limit(limit).offset(offset)).all()
    return list(rows), int(total)


def update_asset(session: Session, asset_id: str, **fields: Any) -> MediaAsset:
    asset = session.get(MediaAsset, asset_id)
    if asset is None:
        raise MediaError(f"Média introuvable : {asset_id}")
    for key in ("display_name", "notes"):
        if key in fields and fields[key] is not None:
            setattr(asset, key, str(fields[key]))
    for key in ("tags", "collections"):
        if key in fields and fields[key] is not None:
            cleaned = sorted({str(v).strip() for v in fields[key] if str(v).strip()})
            setattr(asset, key, cleaned)
    session.flush()
    return asset


def delete_asset(session: Session, asset_id: str, *, confirm: bool, settings: Settings | None = None) -> None:
    """Supprime l'entrée de bibliothèque. ``confirm=True`` obligatoire."""
    if not confirm:
        raise MediaError("Suppression refusée : confirmation explicite requise.")
    settings = settings or get_settings()
    asset = session.get(MediaAsset, asset_id)
    if asset is None:
        raise MediaError(f"Média introuvable : {asset_id}")
    linked = session.scalar(select(func.count()).select_from(PostTarget).join(PostTarget.post).where(PostTarget.post.has(media_asset_id=asset_id)))
    stored = settings.media_dir / asset.stored_path
    try:
        stored.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("Suppression du fichier impossible : %s", exc)
    if asset.thumbnail_path:
        (settings.thumbnails_dir / asset.thumbnail_path).unlink(missing_ok=True)
    session.delete(asset)
    session.flush()
    log.info("Média supprimé : %s (publications liées : %s)", asset.display_name, linked)


def find_duplicates(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(MediaAsset.sha256, func.count(MediaAsset.id)).group_by(MediaAsset.sha256).having(func.count(MediaAsset.id) > 1)
    ).all()
    return [{"sha256": sha, "count": count} for sha, count in rows]


def validate_for_platform(session: Session, asset: MediaAsset, platform: str) -> dict[str, Any]:
    """Confronte un média aux contraintes réelles d'une plateforme."""
    spec = get_spec(platform)
    probe = probe_dict(asset)
    result = spec.validate(probe)
    result["platform"] = platform
    result["platform_label"] = spec.label
    result["caption_limit"] = spec.caption_limit
    result["ratio"] = _ratio_label(asset.width, asset.height)
    result["probe_status"] = asset.probe_status
    if asset.probe_status == "unavailable":
        result["info"].append(
            {
                "key": "probe_unavailable",
                "label": "Analyse indisponible",
                "message": "FFmpeg absent : la conformité du fichier n'a pas pu être vérifiée localement.",
            }
        )
    result["notes"] = spec.notes
    return result


def publish_history(session: Session, asset_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(PostTarget).join(PostTarget.post).where(PostTarget.post.has(id=asset_id)).order_by(PostTarget.created_at.desc())
    ).scalars().all()
    return [
        {
            "post_target_id": t.id,
            "status": t.status,
            "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
            "published_at": t.published_at.isoformat() if t.published_at else None,
            "remote_url": t.remote_url,
            "account_id": t.account_id,
        }
        for t in rows
    ]


def touched_at() -> str:
    return utcnow().isoformat()
