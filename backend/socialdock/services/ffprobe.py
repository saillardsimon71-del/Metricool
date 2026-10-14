"""Accès à FFmpeg / FFprobe.

FFmpeg est une dépendance *optionnelle* : s'il est absent, SocialDock fonctionne
toujours (import, bibliothèque, compositeur, calendrier, scheduler) mais les
métadonnées techniques sont marquées ``probe_status="unavailable"`` — jamais
inventées.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_WINDOWS_CANDIDATES = [
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
]


def _find(binary: str) -> str | None:
    override = os.environ.get(f"SOCIALDOCK_{binary.upper()}")
    if override and Path(override).exists():
        return override
    found = shutil.which(binary)
    if found:
        return found
    if os.name == "nt":
        for candidate in _WINDOWS_CANDIDATES:
            if Path(candidate).exists():
                return candidate.replace("ffmpeg.exe", f"{binary}.exe")
    return None


def ffmpeg_path() -> str | None:
    return _find("ffmpeg")


def ffprobe_path() -> str | None:
    return _find("ffprobe")


def ffmpeg_available() -> bool:
    """Vrai si au moins un des deux binaires est utilisable.

    ``probe_file`` sait travailler avec ``ffmpeg`` seul (analyse de la bannière),
    donc l'absence de ``ffprobe`` ne désactive pas l'analyse technique.
    """
    return ffprobe_path() is not None or ffmpeg_path() is not None


@dataclass(slots=True)
class ProbeResult:
    """Métadonnées extraites d'un fichier. Les champs absents restent ``None``."""

    probe_status: str = "unavailable"  # ok | unavailable | failed
    probe_error: str | None = None
    kind: str = "video"
    mime_type: str | None = None
    container: str | None = None
    size_bytes: int = 0
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    has_audio: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "probe_status": self.probe_status,
            "probe_error": self.probe_error,
            "kind": self.kind,
            "mime_type": self.mime_type,
            "container": self.container,
            "size_bytes": self.size_bytes,
            "duration_seconds": self.duration_seconds,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "has_audio": self.has_audio,
            **self.extra,
        }


class FFmpegError(RuntimeError):
    """Échec d'une opération FFmpeg (conversion, miniature…)."""


def _parse_fps(stream: dict[str, Any]) -> float | None:
    for key in ("avg_frame_rate", "r_frame_rate"):
        raw = stream.get(key)
        if not raw or raw in {"0/0", "N/A"}:
            continue
        try:
            num, den = raw.split("/")
            if float(den) == 0:
                continue
            value = float(num) / float(den)
            if value > 0:
                return round(value, 3)
        except (ValueError, ZeroDivisionError):
            continue
    return None


def probe_file(path: str | Path, timeout: int = 60) -> ProbeResult:
    """Analyse un fichier média avec ffprobe. N'échoue jamais brutalement."""
    path = Path(path)
    result = ProbeResult()
    try:
        result.size_bytes = path.stat().st_size
    except OSError as exc:
        result.probe_status = "failed"
        result.probe_error = f"Fichier inaccessible : {exc}"
        return result

    binary = ffprobe_path()
    if binary is None:
        # ffprobe absent mais ffmpeg présent : on analyse la sortie de `ffmpeg -i`.
        fallback = ffmpeg_path()
        if fallback is None:
            result.probe_status = "unavailable"
            result.probe_error = (
                "FFmpeg/ffprobe introuvables : installez FFmpeg pour activer l'analyse technique."
            )
            return result
        return _probe_with_ffmpeg(fallback, path, result, timeout)

    cmd = [
        binary,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        result.probe_status = "failed"
        result.probe_error = f"Analyse interrompue après {timeout} s."
        return result
    except OSError as exc:
        result.probe_status = "failed"
        result.probe_error = f"Impossible d'exécuter ffprobe : {exc}"
        return result

    if completed.returncode != 0:
        result.probe_status = "failed"
        result.probe_error = (completed.stderr or "ffprobe a renvoyé une erreur").strip()[:500]
        return result

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        result.probe_status = "failed"
        result.probe_error = f"Sortie ffprobe illisible : {exc}"
        return result

    fmt = payload.get("format") or {}
    streams = payload.get("streams") or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    result.probe_status = "ok"
    result.container = (fmt.get("format_name") or "").split(",")[0] or None
    result.mime_type = _guess_mime(path.suffix.lower(), result.container)
    result.kind = "image" if (video_stream and not audio_stream and _is_image_container(result.container, video_stream)) else "video"
    if fmt.get("duration"):
        with contextlib.suppress(TypeError, ValueError):
            result.duration_seconds = round(float(fmt["duration"]), 3)
    if video_stream:
        result.width = video_stream.get("width")
        result.height = video_stream.get("height")
        result.video_codec = video_stream.get("codec_name")
        result.fps = _parse_fps(video_stream)
    if audio_stream:
        result.audio_codec = audio_stream.get("codec_name")
        result.has_audio = True
    return result


def _is_image_container(container: str | None, video_stream: dict[str, Any]) -> bool:
    if container in {"png_pipe", "image2", "jpeg", "mjpeg"}:
        return True
    return video_stream.get("codec_name") in {"png", "mjpeg", "jpeg", "webp", "bmp"}


def _guess_mime(suffix: str, container: str | None) -> str:
    table = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    return table.get(suffix) or (f"video/{container}" if container else "application/octet-stream")


def make_thumbnail(source: str | Path, destination: str | Path, at_seconds: float = 1.0, width: int = 480, timeout: int = 120) -> bool:
    """Génère une miniature JPEG. Retourne ``False`` si FFmpeg est indisponible."""
    binary = ffmpeg_path()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if binary is None:
        log.warning("FFmpeg indisponible : miniature non générée pour %s", source)
        return False
    cmd = [
        binary,
        "-y",
        "-ss",
        str(max(0.0, at_seconds)),
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:-2",
        "-q:v",
        "4",
        str(destination),
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("Échec miniature %s : %s", source, exc)
        return False
    if completed.returncode != 0 or not destination.exists():
        log.warning("Échec miniature %s : %s", source, (completed.stderr or "")[-300:])
        return False
    return True


def extract_frame(source: str | Path, destination: str | Path, at_seconds: float, width: int = 1080, timeout: int = 120) -> bool:
    """Extrait une image pleine résolution (couverture YouTube / miniature TikTok)."""
    binary = ffmpeg_path()
    if binary is None:
        return False
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cmd = [binary, "-y", "-ss", str(at_seconds), "-i", str(source), "-frames:v", "1", "-vf", f"scale={width}:-2", str(destination)]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return completed.returncode == 0 and destination.exists()


def convert_to_h264(source: str | Path, destination: str | Path, *, crf: int = 21, preset: str = "medium", timeout: int = 3600) -> bool:
    """Réencode en H.264/AAC (+ faststart pour Instagram). Opération explicite."""
    binary = ffmpeg_path()
    if binary is None:
        return False
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        binary,
        "-y",
        "-i",
        str(source),
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return completed.returncode == 0 and destination.exists()


def fit_vertical_916(source: str | Path, destination: str | Path, width: int = 1080, height: int = 1920, timeout: int = 3600) -> bool:
    """Recadre/complete en 9:16 (recadrage central puis fond flouté, sans déformation)."""
    binary = ffmpeg_path()
    if binary is None:
        return False
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"split[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=20[blurred];"
        f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[scaled];"
        f"[blurred][scaled]overlay=(W-w)/2:(H-h)/2"
    )
    cmd = [
        binary, "-y", "-i", str(source),
        "-filter_complex", vf,
        "-c:v", "libx264", "-crf", "21", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(destination),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return completed.returncode == 0 and destination.exists()


def normalize_audio(source: str | Path, destination: str | Path, target_lufs: float = -16.0, timeout: int = 3600) -> bool:
    """Normalise le son en deux passes (loudnorm) sans toucher à la vidéo."""
    binary = ffmpeg_path()
    if binary is None:
        return False
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        binary, "-y", "-i", str(source),
        "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        str(destination),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return completed.returncode == 0 and destination.exists()


def trim_video(source: str | Path, destination: str | Path, start: float, duration: float, timeout: int = 3600) -> bool:
    """Découpe sans réencodage (copie de flux) lorsque c'est possible."""
    binary = ffmpeg_path()
    if binary is None:
        return False
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cmd = [binary, "-y", "-ss", str(start), "-i", str(source), "-t", str(duration), "-c", "copy", "-movflags", "+faststart", str(destination)]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return completed.returncode == 0 and destination.exists()


def version_info() -> dict[str, Any]:
    """Informations FFmpeg pour la page Diagnostics."""
    info: dict[str, Any] = {
        "available": ffmpeg_available(),
        "ffmpeg_path": ffmpeg_path(),
        "ffprobe_path": ffprobe_path(),
        "probe_backend": "ffprobe" if ffprobe_path() else ("ffmpeg" if ffmpeg_path() else None),
    }
    binary = ffmpeg_path()
    if not binary:
        info["version"] = None
        return info
    try:
        completed = subprocess.run([binary, "-version"], capture_output=True, text=True, timeout=15)
        first = (completed.stdout or "").splitlines()
        info["version"] = first[0] if first else None
    except (subprocess.TimeoutExpired, OSError):
        info["version"] = None
    return info


# ---------------------------------------------------------------------------
# Analyse de secours via `ffmpeg -i` (utilisée quand ffprobe n'est pas installé)
# ---------------------------------------------------------------------------
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO_RE = re.compile(
    r"Video:\s*(?P<codec>[a-z0-9_]+).*?(?P<width>\d{2,5})x(?P<height>\d{2,5})", re.IGNORECASE
)
_FPS_RE = re.compile(r"(?P<fps>\d+(?:\.\d+)?)\s+fps")
_AUDIO_RE = re.compile(r"Audio:\s*(?P<codec>[a-z0-9_]+)", re.IGNORECASE)
_CONTAINER_RE = re.compile(r"Input #\d+,\s*([^,]+),\s*from")


def _probe_with_ffmpeg(binary: str, path: Path, result: ProbeResult, timeout: int) -> ProbeResult:
    """Extrait durée/codecs/résolution depuis la bannière d'erreur d'ffmpeg."""
    try:
        completed = subprocess.run(
            [binary, "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        result.probe_status = "failed"
        result.probe_error = f"Analyse ffmpeg impossible : {exc}"
        return result

    output = (completed.stderr or "") + (completed.stdout or "")
    if "Invalid data found" in output or "does not contain any stream" in output:
        result.probe_status = "failed"
        result.probe_error = "Fichier illisible ou corrompu (aucun flux média détecté)."
        return result

    duration = _DURATION_RE.search(output)
    if duration:
        hours, minutes, seconds = duration.groups()
        result.duration_seconds = round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 3)

    container = _CONTAINER_RE.search(output)
    if container:
        result.container = container.group(1).strip().split("/")[0]
    result.mime_type = _guess_mime(path.suffix.lower(), result.container)

    video = _VIDEO_RE.search(output)
    if video:
        result.video_codec = video.group("codec").lower()
        result.width = int(video.group("width"))
        result.height = int(video.group("height"))
    fps = _FPS_RE.search(output)
    if fps:
        result.fps = round(float(fps.group("fps")), 3)
    audio = _AUDIO_RE.search(output)
    if audio:
        result.audio_codec = audio.group("codec").lower()
        result.has_audio = True

    if not video and not audio:
        result.probe_status = "failed"
        result.probe_error = "Aucun flux vidéo ou audio détecté par ffmpeg."
        return result

    result.kind = "image" if (video and not audio and _is_image_container(result.container, {"codec_name": result.video_codec})) else "video"
    result.probe_status = "ok"
    result.extra["probe_backend"] = "ffmpeg"
    return result
