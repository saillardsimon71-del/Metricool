"""API locale d'ingestion pour Studio IA (protégée par token).

Sécurité :
* token obligatoire (``X-SocialDock-Token``) ;
* le chemin demandé doit se trouver dans un dossier autorisé (dossiers
  surveillés ou répertoire utilisateur) — pas de lecture arbitraire du disque ;
* seuls les formats médias acceptés par la bibliothèque sont importés.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Post, Series, WatchedFolder
from ..schemas import IngestRequest
from ..services.media_service import MediaError, import_bytes, import_path, is_supported
from .deps import db_session, get_current_settings, require_ingest_token

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


def _allowed_roots(session: Session, settings: Settings) -> list[Path]:
    roots = [settings.data_dir.resolve(), Path.home().resolve()]
    for folder in session.scalars(select(WatchedFolder)).all():
        try:
            roots.append(Path(folder.path).expanduser().resolve())
        except OSError:
            continue
    return roots


def _check_path(session: Session, settings: Settings, candidate: Path) -> Path:
    resolved = candidate.expanduser().resolve()
    if not any(resolved == root or root in resolved.parents for root in _allowed_roots(session, settings)):
        raise HTTPException(status_code=403, detail="Chemin hors des dossiers autorisés.")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"Fichier introuvable : {candidate}")
    if not is_supported(resolved):
        raise HTTPException(status_code=400, detail=f"Format non supporté : {resolved.suffix}")
    return resolved


@router.get("/ping")
def ping(_: str = Depends(require_ingest_token)) -> dict[str, str]:
    return {"status": "ok", "service": "SocialDock ingest"}


@router.post("/video", status_code=201)
def ingest_video(
    payload: IngestRequest,
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_current_settings),
    _: str = Depends(require_ingest_token),
) -> dict[str, Any]:
    """Studio IA transmet un chemin local ; SocialDock importe et prépare un brouillon."""
    if not payload.path:
        raise HTTPException(status_code=400, detail="Chemin de fichier manquant.")
    source = _check_path(session, settings, Path(payload.path))
    try:
        result = import_path(session, source, display_name=payload.title, tags=payload.tags, imported_from=f"studio-ai:{source.name}", settings=settings)
    except MediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    draft_id = None
    if payload.create_draft:
        draft_id = _create_draft(session, result.asset, payload)
    session.commit()
    return {
        "media_id": result.asset.id,
        "created": result.created,
        "duplicate_of": result.duplicate_of,
        "draft_post_id": draft_id,
    }


@router.post("/upload", status_code=201)
async def ingest_upload(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    description: str | None = Form(default=None),
    language: str = Form(default="fr"),
    tags: str = Form(default=""),
    _: str = Depends(require_ingest_token),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_current_settings),
) -> dict[str, Any]:
    """Variante téléversement : aucun chemin disque n'est exposé."""
    data = await file.read(2 * 1024 * 1024 * 1024)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        result = import_bytes(session, data, file.filename or "studio-ai.mp4", display_name=title, tags=tag_list, imported_from=f"studio-ai-upload:{file.filename}", settings=settings)
    except MediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    draft_id = None
    draft = Post(title=title or result.asset.display_name, description=description or "", hashtags=tag_list, media_asset_id=result.asset.id, language=language)
    session.add(draft)
    session.flush()
    draft_id = draft.id
    session.commit()
    return {"media_id": result.asset.id, "created": result.created, "duplicate_of": result.duplicate_of, "draft_post_id": draft_id}


def _create_draft(session: Session, asset, payload: IngestRequest) -> str:
    series_id = None
    if payload.series:
        series = session.scalar(select(Series).where(Series.name == payload.series))
        if series is None:
            series = Series(name=payload.series)
            session.add(series)
            session.flush()
        series_id = series.id
        if payload.episode is None:
            payload.episode = series.next_episode
            series.next_episode = (series.next_episode or 1) + 1
    post = Post(
        title=payload.title or asset.display_name,
        description=payload.description or "",
        hashtags=payload.tags or [],
        media_asset_id=asset.id,
        language=payload.language or "fr",
        series_id=series_id,
        episode_number=payload.episode,
    )
    session.add(post)
    session.flush()
    return post.id
