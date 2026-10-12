"""Contraintes techniques par plateforme et règles de validation des médias.

Les valeurs ci-dessous proviennent des documentations officielles consultées le
2026-10-12 (voir ``docs/PLATFORM_FEASIBILITY.md`` pour les sources exactes) :

* YouTube  : ``videos.insert`` — projets API non audités créés après le
  28/07/2020 → vidéos verrouillées en privé ; 100 ``videos.insert``/jour ;
  256 Go / 12 h par fichier.
* Instagram (API avec Instagram Login, ``graph.instagram.com``) : conteneur
  ``media_type=REELS`` puis ``media_publish`` ; 3 s → 15 min ; 300 Mo ;
  MP4/MOV, H.264/HEVC, AAC, 23–60 fps, largeur ≤ 1920 px, 9:16 recommandé ;
  légende 2200 caractères ; quota ``content_publishing_limit``.
* TikTok (Content Posting API, ``open.tiktokapis.com``) : 4 Go ;
  360–4096 px ; 23–60 fps ; durée limitée par ``max_video_post_duration_sec``
  (3 min pour la plupart des créateurs, plafond API 10 min) ; légende 2200.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


@dataclass(slots=True)
class MediaRule:
    """Règle de validation : un écart produit un message actionnable."""

    key: str
    label: str
    severity: str
    applies_to: str  # video | image | both

    def check(self, probe: dict[str, Any]) -> tuple[bool, str | None]:
        raise NotImplementedError


@dataclass(slots=True)
class _Duration(MediaRule):
    min_seconds: float = 0.0
    max_seconds: float | None = None
    reels_note: str | None = None

    def check(self, probe: dict[str, Any]) -> tuple[bool, str | None]:
        duration = probe.get("duration_seconds")
        if duration is None:
            return True, None
        if duration < self.min_seconds:
            return False, f"Vidéo trop courte : {duration:.1f} s (minimum {self.min_seconds:.0f} s)."
        if self.max_seconds is not None and duration > self.max_seconds:
            return False, (
                f"Vidéo trop longue : {duration:.1f} s (maximum {self.max_seconds:.0f} s)."
            )
        if self.reels_note and duration > 90:
            return True, self.reels_note
        return True, None


@dataclass(slots=True)
class _FileSize(MediaRule):
    max_bytes: int = 0

    def check(self, probe: dict[str, Any]) -> tuple[bool, str | None]:
        size = probe.get("size_bytes") or 0
        if self.max_bytes and size > self.max_bytes:
            return False, (
                f"Fichier trop volumineux : {size / 1_000_000:.1f} Mo "
                f"(maximum {self.max_bytes / 1_000_000:.0f} Mo)."
            )
        return True, None


@dataclass(slots=True)
class _Aspect(MediaRule):
    target: float = 9 / 16
    tolerance: float = 0.05

    def check(self, probe: dict[str, Any]) -> tuple[bool, str | None]:
        width, height = probe.get("width"), probe.get("height")
        if not width or not height:
            return True, None
        ratio = width / height
        if abs(ratio - self.target) > self.tolerance:
            return False, (
                f"Ratio {width}x{height} ({ratio:.2f}) différent du vertical 9:16 attendu : "
                "recadrage recommandé (Outils → Adapter au format vertical)."
            )
        return True, None


@dataclass(slots=True)
class _VideoCodec(MediaRule):
    allowed: tuple[str, ...] = ("h264",)

    def check(self, probe: dict[str, Any]) -> tuple[bool, str | None]:
        codec = (probe.get("video_codec") or "").lower()
        if not codec:
            return True, None
        if codec not in {c.lower() for c in self.allowed}:
            return False, (
                f"Codec vidéo « {codec} » non conforme — "
                f"attendu : {', '.join(self.allowed)}. Conversion nécessaire."
            )
        return True, None


@dataclass(slots=True)
class _AudioCodec(MediaRule):
    allowed: tuple[str, ...] = ("aac",)
    required: bool = True

    def check(self, probe: dict[str, Any]) -> tuple[bool, str | None]:
        codec = (probe.get("audio_codec") or "").lower()
        if not codec:
            if self.required:
                return False, "Aucune piste audio détectée : ajout d'une piste AAC recommandé."
            return True, None
        if codec not in {c.lower() for c in self.allowed}:
            return False, f"Codec audio « {codec} » non conforme — attendu : {', '.join(self.allowed)}."
        return True, None


@dataclass(slots=True)
class _Container(MediaRule):
    allowed: tuple[str, ...] = ("mp4", "mov")

    def check(self, probe: dict[str, Any]) -> tuple[bool, str | None]:
        name = (probe.get("container") or probe.get("mime_type") or "").lower()
        if not name:
            return True, None
        if any(token in name for token in self.allowed):
            return True, None
        return False, (
            f"Conteneur « {name} » non supporté — attendu : {', '.join(self.allowed)}."
        )


@dataclass(slots=True)
class _FrameRate(MediaRule):
    min_fps: float = 23.0
    max_fps: float = 60.0

    def check(self, probe: dict[str, Any]) -> tuple[bool, str | None]:
        fps = probe.get("fps")
        if not fps:
            return True, None
        if fps < self.min_fps or fps > self.max_fps:
            return False, f"Fréquence d'images {fps:.2f} fps hors plage {self.min_fps:.0f}–{self.max_fps:.0f} fps."
        return True, None


@dataclass(slots=True)
class _MinSide(MediaRule):
    min_px: int = 360

    def check(self, probe: dict[str, Any]) -> tuple[bool, str | None]:
        width, height = probe.get("width"), probe.get("height")
        if not width or not height:
            return True, None
        if min(width, height) < self.min_px:
            return False, f"Résolution trop faible ({width}x{height}) — minimum {self.min_px} px sur le petit côté."
        return True, None


@dataclass(slots=True)
class _Corrupt(MediaRule):
    def check(self, probe: dict[str, Any]) -> tuple[bool, str | None]:
        if probe.get("probe_status") == "failed":
            return False, f"Fichier illisible ou corrompu : {probe.get('probe_error') or 'ffprobe a échoué'}."
        return True, None


@dataclass(slots=True)
class _MaxWidth(MediaRule):
    max_px: int = 1920

    def check(self, probe: dict[str, Any]) -> tuple[bool, str | None]:
        width = probe.get("width")
        if width and width > self.max_px:
            return True, (
                f"Largeur {width} px supérieure à {self.max_px} px : la plateforme redimensionnera le fichier."
            )
        return True, None


@dataclass(slots=True)
class PlatformSpec:
    platform: str
    label: str
    caption_limit: int
    title_limit: int | None
    rules: list[MediaRule] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def validate(self, probe: dict[str, Any]) -> dict[str, Any]:
        """Retourne ``{ok, issues, warnings, info}`` pour un média donné."""
        issues: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        infos: list[dict[str, str]] = []
        for rule in self.rules:
            if rule.applies_to != "both" and probe.get("kind", "video") != rule.applies_to:
                continue
            ok, message = rule.check(probe)
            if message is None:
                continue
            bucket = issues if not ok and rule.severity == SEVERITY_ERROR else (warnings if rule.severity == SEVERITY_WARNING else infos)
            if ok and rule.severity == SEVERITY_ERROR:
                bucket = infos
            bucket.append({"key": rule.key, "label": rule.label, "message": message})
        return {"ok": not issues, "issues": issues, "warnings": warnings, "info": infos}


MB = 1_000_000
GB = 1_000_000_000

YOUTUBE_SPEC = PlatformSpec(
    platform="youtube",
    label="YouTube",
    caption_limit=5000,  # description, en octets côté API
    title_limit=100,
    rules=[
        _Corrupt("corrupt", "Intégrité du fichier", SEVERITY_ERROR, "video"),
        _FileSize("size", "Taille du fichier", SEVERITY_ERROR, "both", max_bytes=256 * GB),
        _Aspect("aspect", "Format vertical 9:16 (Shorts)", SEVERITY_WARNING, "video"),
        _Duration("duration", "Durée", SEVERITY_WARNING, "video", max_seconds=12 * 3600,
                  reels_note="Au-delà de 3 minutes, la vidéo n'est plus classée comme Short."),
        _FrameRate("fps", "Fréquence d'images", SEVERITY_WARNING, "video"),
        _VideoCodec("vcodec", "Codec vidéo", SEVERITY_WARNING, "video", allowed=("h264", "hevc", "vp9", "av1")),
        _AudioCodec("acodec", "Codec audio", SEVERITY_WARNING, "video", allowed=("aac", "opus", "mp3"), required=False),
    ],
    notes=[
        "Shorts : vertical, 3 minutes maximum pour être classé comme Short.",
        "Projets API non audités (créés après le 28/07/2020) : les uploads sont verrouillés en privé.",
        "100 appels videos.insert par projet et par jour (quota par défaut).",
    ],
)

INSTAGRAM_SPEC = PlatformSpec(
    platform="instagram",
    label="Instagram (Reels)",
    caption_limit=2200,
    title_limit=None,
    rules=[
        _Corrupt("corrupt", "Intégrité du fichier", SEVERITY_ERROR, "video"),
        _Container("container", "Conteneur", SEVERITY_ERROR, "video", allowed=("mp4", "mov", "quicktime")),
        _VideoCodec("vcodec", "Codec vidéo", SEVERITY_ERROR, "video", allowed=("h264", "hevc")),
        _AudioCodec("acodec", "Codec audio", SEVERITY_ERROR, "video", allowed=("aac",), required=True),
        _Duration("duration", "Durée", SEVERITY_ERROR, "video", min_seconds=3, max_seconds=15 * 60,
                  reels_note="Au-delà de 90 s, la publication peut perdre son éligibilité à l'onglet Reels."),
        _FileSize("size", "Taille du fichier", SEVERITY_ERROR, "video", max_bytes=300 * MB),
        _MaxWidth("maxwidth", "Largeur", SEVERITY_INFO, "video", max_px=1920),
        _Aspect("aspect", "Format 9:16", SEVERITY_WARNING, "video"),
        _FrameRate("fps", "Fréquence d'images", SEVERITY_ERROR, "video"),
    ],
    notes=[
        "La vidéo doit être accessible par les serveurs Meta : URL publique HTTPS ou upload résumable rupload.",
        "Compte Professionnel (Business ou Creator) obligatoire.",
        "Quota de publication vérifiable via content_publishing_limit.",
    ],
)

TIKTOK_SPEC = PlatformSpec(
    platform="tiktok",
    label="TikTok",
    caption_limit=2200,
    title_limit=None,
    rules=[
        _Corrupt("corrupt", "Intégrité du fichier", SEVERITY_ERROR, "video"),
        _Container("container", "Conteneur", SEVERITY_ERROR, "video", allowed=("mp4", "mov", "quicktime", "webm")),
        _FileSize("size", "Taille du fichier", SEVERITY_ERROR, "video", max_bytes=4 * GB),
        _Duration("duration", "Durée", SEVERITY_ERROR, "video", min_seconds=3, max_seconds=10 * 60,
                  reels_note="La limite réelle dépend de max_video_post_duration_sec du créateur (3 min pour la plupart)."),
        _FrameRate("fps", "Fréquence d'images", SEVERITY_WARNING, "video"),
        _MinSide("minside", "Résolution minimale", SEVERITY_ERROR, "video", min_px=360),
        _Aspect("aspect", "Format 9:16", SEVERITY_WARNING, "video"),
        _VideoCodec("vcodec", "Codec vidéo", SEVERITY_WARNING, "video", allowed=("h264", "hevc", "vp8", "vp9")),
    ],
    notes=[
        "Application non auditée : publication limitée à SELF_ONLY et 5 utilisateurs par 24 h.",
        "6 requêtes/minute maximum sur l'endpoint d'initialisation de publication.",
    ],
)

DEMO_SPEC = PlatformSpec(
    platform="demo",
    label="Compte de démonstration",
    caption_limit=4000,
    title_limit=200,
    rules=[_Corrupt("corrupt", "Intégrité du fichier", SEVERITY_ERROR, "video")],
    notes=["Plateforme simulée, locale : aucune donnée ne quitte votre ordinateur."],
)

SPECS: dict[str, PlatformSpec] = {
    "youtube": YOUTUBE_SPEC,
    "instagram": INSTAGRAM_SPEC,
    "tiktok": TIKTOK_SPEC,
    "demo": DEMO_SPEC,
}


def get_spec(platform: str) -> PlatformSpec:
    return SPECS.get(platform, DEMO_SPEC)
