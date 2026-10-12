"""API bibliothèque médias : import, métadonnées, validation, outils FFmpeg."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import MediaAsset
from ..schemas import MediaOut, MediaPatch, MediaTransformRequest, MediaValidation
from ..services import media_service
from ..services.media_service import MediaError
from .deps import db_session, get_current_settings

router = APIRouter(prefix="/api/media", tags=["media"])

MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024


@router.get("", response_model=dict[str, Any])
def list_media(
    q: str | None = None,
    kind: str | None = None,
    tags: list[str] | None = Query(default=None),
    sort: str = "created_desc",
    limit: int = Query(default=60, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    items, total = media_service.list_assets(session, query=q, kind=kind, tags=tags, sort=sort, limit=limit, offset=offset)
    return {
        "items": [MediaOut.model_validate(item).model_dump(mode="json") for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/upload", response_model=dict[str, Any], status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    tags: str | None = Form(default=None),
    display_name: str | None = Form(default=None),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_current_settings),
) -> dict[str, Any]:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (limite 4 Go).")
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    try:
        result = await asyncio.to_thread(
            media_service.import_bytes,
            session,
            data,
            file.filename or "media.mp4",
            display_name=display_name,
            tags=tag_list,
            imported_from=f"upload:{file.filename}",
            settings=settings,
        )
    except MediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    return {"created": result.created, "duplicate_of": result.duplicate_of, "media": MediaOut.model_validate(result.asset).model_dump(mode="json")}


@router.post("/import-path", response_model=dict[str, Any], status_code=201)
async def import_from_path(
    payload: dict[str, Any],
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_current_settings),
) -> dict[str, Any]:
    """Import depuis un chemin local (utilisé par l'API d'ingestion et l'UI)."""
    path = payload.get("path")
    if not path:
        raise HTTPException(status_code=400, detail="Chemin manquant.")
    try:
        result = await asyncio.to_thread(
            media_service.import_path,
            session,
            Path(path),
            display_name=payload.get("display_name"),
            tags=payload.get("tags") or [],
            imported_from=f"local:{path}",
            settings=settings,
        )
    except MediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Import impossible : {exc}") from exc
    session.commit()
    return {"created": result.created, "duplicate_of": result.duplicate_of, "media": MediaOut.model_validate(result.asset).model_dump(mode="json")}


@router.get("/duplicates")
def duplicates(session: Session = Depends(db_session)) -> dict[str, Any]:
    return {"duplicates": media_service.find_duplicates(session)}


@router.get("/{media_id}", response_model=MediaOut)
def get_media(media_id: str, session: Session = Depends(db_session)) -> MediaAsset:
    asset = session.get(MediaAsset, media_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Média introuvable.")
    return asset


@router.patch("/{media_id}", response_model=MediaOut)
def patch_media(media_id: str, payload: MediaPatch, session: Session = Depends(db_session)) -> MediaAsset:
    try:
        return media_service.update_asset(session, media_id, **payload.model_dump(exclude_none=True))
    except MediaError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{media_id}", status_code=204)
def delete_media(
    media_id: str,
    confirm: bool = Query(default=False),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_current_settings),
) -> None:
    try:
        media_service.delete_asset(session, media_id, confirm=confirm, settings=settings)
    except MediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{media_id}/refresh", response_model=MediaOut)
def refresh_media(media_id: str, session: Session = Depends(db_session), settings: Settings = Depends(get_current_settings)) -> MediaAsset:
    asset = session.get(MediaAsset, media_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Média introuvable.")
    return media_service.refresh_metadata(session, asset, settings)


@router.get("/{media_id}/validate/{platform}", response_model=MediaValidation)
def validate_media(media_id: str, platform: str, session: Session = Depends(db_session)) -> dict[str, Any]:
    asset = session.get(MediaAsset, media_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Média introuvable.")
    return media_service.validate_for_platform(session, asset, platform)


@router.get("/{media_id}/history")
def media_history(media_id: str, session: Session = Depends(db_session)) -> dict[str, Any]:
    return {"history": media_service.publish_history(session, media_id)}


@router.post("/{media_id}/transform", response_model=MediaOut)
async def transform_media(
    media_id: str,
    payload: MediaTransformRequest,
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_current_settings),
) -> MediaAsset:
    """Traitements FFmpeg optionnels (jamais de réencodage automatique)."""
    from ..services.ffprobe import convert_to_h264, extract_frame, fit_vertical_916, normalize_audio, trim_video

    asset = session.get(MediaAsset, media_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Média introuvable.")
    source = settings.safe_media_path(asset.stored_path)
    suffix = source.suffix
    destination = settings.media_dir / f"{asset.sha256[:12]}_{payload.operation}{suffix}"
    if payload.operation == "frame":
        destination = settings.thumbnails_dir / f"{asset.sha256[:12]}_frame_{int(payload.at_seconds or 0)}.jpg"

    def run() -> bool:
        if payload.operation == "h264":
            return convert_to_h264(source, destination)
        if payload.operation == "vertical":
            return fit_vertical_916(source, destination)
        if payload.operation == "audio":
            return normalize_audio(source, destination)
        if payload.operation == "trim":
            return trim_video(source, destination, payload.at_seconds or 0.0, payload.duration_seconds or 30.0)
        return extract_frame(source, destination, payload.at_seconds or 0.0, width=payload.width or 1080)

    ok = await asyncio.to_thread(run)
    if not ok:
        raise HTTPException(status_code=409, detail="Traitement impossible : FFmpeg indisponible ou fichier incompatible.")
    result = media_service.import_path(session, destination, display_name=f"{asset.display_name} ({payload.operation})", imported_from=f"transform:{asset.id}")
    session.commit()
    return result.asset


@router.get("/{media_id}/file")
def media_file(media_id: str, session: Session = Depends(db_session), settings: Settings = Depends(get_current_settings)) -> FileResponse:
    asset = session.get(MediaAsset, media_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Média introuvable.")
    try:
        path = settings.safe_media_path(asset.stored_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier absent du disque.")
    return FileResponse(path, media_type=asset.mime_type or "application/octet-stream", filename=asset.original_name)


@router.get("/{media_id}/thumbnail")
def media_thumbnail(media_id: str, session: Session = Depends(db_session), settings: Settings = Depends(get_current_settings)) -> FileResponse:
    asset = session.get(MediaAsset, media_id)
    if asset is None or not asset.thumbnail_path:
        raise HTTPException(status_code=404, detail="Miniature indisponible (FFmpeg requis).")
    path = settings.thumbnails_dir / asset.thumbnail_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Miniature absente du disque.")
    return FileResponse(path, media_type="image/jpeg")
