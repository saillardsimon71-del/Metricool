"""Surveillance de dossiers : import automatique, stabilité, deduplication."""

from __future__ import annotations

import os
import time
from pathlib import Path

from socialdock.config import Settings
from socialdock.models import WatchedFolder
from socialdock.services.watcher import scan_all, scan_folder
from sqlalchemy.orm import Session


def test_import_depuis_dossier_surveille(session: Session, settings: Settings, sample_video: Path):
    watched = settings.data_dir / "entree"
    watched.mkdir()
    cible = watched / "nouveau.mp4"
    cible.write_bytes(sample_video.read_bytes())
    # Fichier considéré comme stable (modification ancienne)
    old = time.time() - 3600
    os.utime(cible, (old, old))
    folder = WatchedFolder(path=str(watched), recursive=False, tags=["studio-ai"], enabled=True)
    session.add(folder)
    session.commit()
    result = scan_folder(session, folder, settings=settings)
    assert [item["file"] for item in result["imported"]] == ["nouveau.mp4"]
    assert result["unstable"] == []
    # Deuxième analyse : rien de nouveau (déduplication par empreinte)
    result2 = scan_folder(session, folder, settings=settings)
    assert result2["imported"] == []
    assert result2["skipped"]


def test_fichier_instable_non_importe(session: Session, settings: Settings, sample_video: Path):
    watched = settings.data_dir / "en-cours"
    watched.mkdir()
    cible = watched / "partiel.mp4"
    cible.write_bytes(sample_video.read_bytes())  # mtime = maintenant
    folder = WatchedFolder(path=str(watched), recursive=False, enabled=True)
    session.add(folder)
    session.commit()
    result = scan_folder(session, folder, settings=settings)
    assert result["imported"] == []
    assert result["unstable"] == ["partiel.mp4"]


def test_extension_non_supportee_ignorer(session: Session, settings: Settings):
    watched = settings.data_dir / "divers"
    watched.mkdir()
    (watched / "notes.txt").write_text("rien à voir")
    folder = WatchedFolder(path=str(watched), recursive=False, enabled=True)
    session.add(folder)
    session.commit()
    result = scan_folder(session, folder, settings=settings)
    assert result["imported"] == [] and result["skipped"] == []


def test_dossier_introuvable_signalé(session: Session, settings: Settings):
    folder = WatchedFolder(path=str(settings.data_dir / "absent"), recursive=False, enabled=True)
    session.add(folder)
    session.commit()
    result = scan_folder(session, folder, settings=settings)
    assert result["errors"]
    assert folder.last_error is not None


def test_scan_all_n_analyse_que_les_dossiers_actifs(session: Session, settings: Settings, sample_video: Path):
    actif = settings.data_dir / "actif"
    inactif = settings.data_dir / "inactif"
    actif.mkdir()
    inactif.mkdir()
    for folder in (actif, inactif):
        (folder / "clip.mp4").write_bytes(sample_video.read_bytes() + folder.name.encode())
        os.utime(folder / "clip.mp4", (time.time() - 3600,) * 2)
    session.add(WatchedFolder(path=str(actif), recursive=False, enabled=True))
    session.add(WatchedFolder(path=str(inactif), recursive=False, enabled=False))
    session.commit()
    results = scan_all(session, settings=settings)
    assert len(results) == 1, "seul le dossier actif doit être analysé"
    assert len(results[0]["imported"]) == 1


def test_dernier_scan_horodaté(session: Session, settings: Settings):
    watched = settings.data_dir / "vide"
    watched.mkdir()
    folder = WatchedFolder(path=str(watched), recursive=False, enabled=True)
    session.add(folder)
    session.commit()
    scan_folder(session, folder, settings=settings)
    assert folder.last_scan_at is not None
