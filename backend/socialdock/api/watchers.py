"""API dossiers surveillés (intégration Studio IA)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import WatchedFolder
from ..schemas import WatchedFolderCreate, WatchedFolderOut
from ..services.watcher import scan_all, scan_folder
from .deps import db_session, get_current_settings

router = APIRouter(prefix="/api/watchers", tags=["watchers"])


@router.get("", response_model=list[WatchedFolderOut])
def list_watchers(session: Session = Depends(db_session)) -> list[WatchedFolder]:
    return list(session.scalars(select(WatchedFolder).order_by(WatchedFolder.created_at.asc())).all())


@router.post("", response_model=WatchedFolderOut, status_code=201)
def create_watcher(payload: WatchedFolderCreate, session: Session = Depends(db_session)) -> WatchedFolder:
    path = Path(payload.path).expanduser()
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"Dossier introuvable : {payload.path}")
    if not path.is_dir():
        raise HTTPException(status_code=400, detail="Le chemin fourni n'est pas un dossier.")
    folder = WatchedFolder(
        path=str(path),
        enabled=payload.enabled,
        create_draft=payload.create_draft,
        template_id=payload.template_id,
        tags=payload.tags,
        recursive=payload.recursive,
    )
    session.add(folder)
    session.commit()
    return folder


@router.patch("/{folder_id}", response_model=WatchedFolderOut)
def patch_watcher(folder_id: str, payload: WatchedFolderCreate, session: Session = Depends(db_session)) -> WatchedFolder:
    folder = session.get(WatchedFolder, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Dossier surveillé introuvable.")
    for key, value in payload.model_dump().items():
        setattr(folder, key, value)
    session.commit()
    return folder


@router.delete("/{folder_id}", status_code=204)
def delete_watcher(folder_id: str, session: Session = Depends(db_session)) -> None:
    folder = session.get(WatchedFolder, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Dossier surveillé introuvable.")
    session.delete(folder)


@router.post("/{folder_id}/scan")
def scan(folder_id: str, session: Session = Depends(db_session), settings=Depends(get_current_settings)) -> dict[str, Any]:
    folder = session.get(WatchedFolder, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Dossier surveillé introuvable.")
    return scan_folder(session, folder, settings=settings)


@router.post("/scan-all")
def scan_everything(session: Session = Depends(db_session), settings=Depends(get_current_settings)) -> dict[str, Any]:
    return {"folders": scan_all(session, settings=settings)}
