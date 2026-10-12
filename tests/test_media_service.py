"""Bibliothèque médias : import, déduplication, validation, suppression sûre."""

from __future__ import annotations

from pathlib import Path

import pytest
from socialdock.config import Settings
from socialdock.models import MediaAsset
from socialdock.services import media_service
from socialdock.services.media_service import MediaError
from sqlalchemy.orm import Session


@pytest.mark.ffmpeg
def test_import_extrait_les_metadonnees_et_la_miniature(session: Session, imported_media: MediaAsset, settings: Settings):
    assert imported_media.probe_status == "ok"
    assert (imported_media.width, imported_media.height) == (1080, 1920)
    assert imported_media.has_audio is True
    assert len(imported_media.sha256) == 64
    assert imported_media.thumbnail_path is not None
    miniature = settings.thumbnails_dir / imported_media.thumbnail_path
    assert miniature.exists() and miniature.stat().st_size > 0
    assert (settings.media_dir / imported_media.stored_path).exists()


@pytest.mark.ffmpeg
def test_deduplication_par_sha256(session: Session, sample_video: Path, settings: Settings):
    first = media_service.import_path(session, sample_video, settings=settings)
    second = media_service.import_path(session, sample_video, settings=settings)
    assert first.created is True
    assert second.created is False
    assert second.duplicate_of == first.asset.id
    assert media_service.find_duplicates(session) == []


@pytest.mark.ffmpeg
def test_import_refuse_les_formats_inconnus(session: Session, tmp_path: Path):
    fichier = tmp_path / "archive.zip"
    fichier.write_bytes(b"PK\x03\x04")
    with pytest.raises(MediaError, match="Format non supporté"):
        media_service.import_path(session, fichier)


def test_import_refuse_un_fichier_vide(session: Session, tmp_path: Path):
    fichier = tmp_path / "vide.mp4"
    fichier.write_bytes(b"")
    with pytest.raises(MediaError, match="vide"):
        media_service.import_path(session, fichier)


@pytest.mark.ffmpeg
def test_le_fichier_original_nest_pas_deplace_par_defaut(session: Session, sample_video: Path, settings: Settings):
    media_service.import_path(session, sample_video, settings=settings)
    assert sample_video.exists()


@pytest.mark.ffmpeg
def test_suppression_exige_une_confirmation(session: Session, imported_media: MediaAsset, settings: Settings):
    with pytest.raises(MediaError, match="confirmation"):
        media_service.delete_asset(session, imported_media.id, confirm=False, settings=settings)
    assert session.get(MediaAsset, imported_media.id) is not None


@pytest.mark.ffmpeg
def test_suppression_confirmee_retire_le_fichier_stocke(session: Session, imported_media: MediaAsset, settings: Settings):
    stocke = settings.media_dir / imported_media.stored_path
    assert stocke.exists()
    media_service.delete_asset(session, imported_media.id, confirm=True, settings=settings)
    session.commit()
    assert not stocke.exists()
    assert session.get(MediaAsset, imported_media.id) is None


def test_path_traversal_refuse(settings: Settings):
    with pytest.raises(ValueError, match="path traversal"):
        settings.safe_media_path("../../etc/passwd")


@pytest.mark.ffmpeg
def test_validation_par_plateforme(session: Session, imported_media: MediaAsset):
    instagram = media_service.validate_for_platform(session, imported_media, "instagram")
    assert instagram["ok"] is True
    assert instagram["ratio"] == "9:16"
    assert instagram["caption_limit"] == 2200

    # Un fichier illisible doit produire un blocage explicite
    broken = MediaAsset(
        stored_path="broken.mp4", original_name="broken.mp4", display_name="broken", kind="video",
        size_bytes=10, sha256="0" * 64, probe_status="failed", probe_error="illisible",
    )
    session.add(broken)
    session.flush()
    result = media_service.validate_for_platform(session, broken, "tiktok")
    assert result["ok"] is False
    assert any("corrompu" in issue["message"] or "illisible" in issue["message"] for issue in result["issues"])


@pytest.mark.ffmpeg
def test_recherche_filtres_et_tri(session: Session, imported_media: MediaAsset):
    media_service.update_asset(session, imported_media.id, display_name="Épisode 12", tags=["vertical", "ia"])
    session.commit()
    items, total = media_service.list_assets(session, query="pisode")
    assert total == 1 and items[0].id == imported_media.id
    items, total = media_service.list_assets(session, tags=["ia"])
    assert total == 1
    items, total = media_service.list_assets(session, tags=["inexistant"])
    assert total == 0
    items, total = media_service.list_assets(session, kind="image")
    assert total == 0


@pytest.mark.ffmpeg
def test_import_par_octets(session: Session, sample_video: Path, settings: Settings):
    data = sample_video.read_bytes()
    result = media_service.import_bytes(session, data, "clip.mp4", settings=settings)
    assert result.created is True
    assert result.asset.original_name == "clip.mp4"
