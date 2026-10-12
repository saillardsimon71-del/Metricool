"""Analyse FFmpeg : chemin nominal, fichier corrompu, FFmpeg absent."""

from __future__ import annotations

from pathlib import Path

import pytest
from socialdock.services import ffprobe


@pytest.mark.ffmpeg
def test_probe_reelle_d_une_video_verticale(sample_video: Path):
    result = ffprobe.probe_file(sample_video)
    assert result.probe_status == "ok"
    assert result.kind == "video"
    assert (result.width, result.height) == (1080, 1920)
    assert result.video_codec == "h264"
    assert result.audio_codec == "aac"
    assert result.has_audio is True
    assert 3.5 <= result.duration_seconds <= 4.5
    assert 29 <= result.fps <= 31


@pytest.mark.ffmpeg
def test_miniature_generee(sample_video: Path, tmp_path: Path):
    destination = tmp_path / "thumb.jpg"
    assert ffprobe.make_thumbnail(sample_video, destination, at_seconds=1.0) is True
    assert destination.exists() and destination.stat().st_size > 1000


@pytest.mark.ffmpeg
@pytest.mark.ffmpeg
def test_fichier_corrompu_detecte(tmp_path: Path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"ceci n'est pas une video")
    result = ffprobe.probe_file(broken)
    assert result.probe_status == "failed"
    assert result.probe_error


def test_fichier_inexistant(tmp_path: Path):
    result = ffprobe.probe_file(tmp_path / "absent.mp4")
    assert result.probe_status == "failed"
    assert "inaccessible" in result.probe_error


def test_probe_sans_ffmpeg_signale_l_indisponibilite(monkeypatch, tmp_path: Path):
    """Sans FFmpeg, aucune métadonnée n'est inventée."""
    monkeypatch.setenv("SOCIALDOCK_FFMPEG", str(tmp_path / "inexistant"))
    monkeypatch.setenv("SOCIALDOCK_FFPROBE", str(tmp_path / "inexistant"))
    monkeypatch.setattr(ffprobe.shutil, "which", lambda _: None)
    monkeypatch.setattr(ffprobe, "_WINDOWS_CANDIDATES", [])
    fichier = tmp_path / "clip.mp4"
    fichier.write_bytes(b"x" * 100)
    result = ffprobe.probe_file(fichier)
    assert result.probe_status == "unavailable"
    assert result.duration_seconds is None
    assert result.width is None
    assert "FFmpeg" in result.probe_error


def test_version_info_reflete_la_disponibilite(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SOCIALDOCK_FFMPEG", str(tmp_path / "inexistant"))
    monkeypatch.setenv("SOCIALDOCK_FFPROBE", str(tmp_path / "inexistant"))
    monkeypatch.setattr(ffprobe.shutil, "which", lambda _: None)
    monkeypatch.setattr(ffprobe, "_WINDOWS_CANDIDATES", [])
    info = ffprobe.version_info()
    assert info["available"] is False
    assert info["probe_backend"] is None
