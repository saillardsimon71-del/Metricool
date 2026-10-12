"""Configuration et emplacements de données persistants de SocialDock.

Règles :
* les données utilisateur ne vivent JAMAIS dans le dépôt Git (Windows :
  ``%LOCALAPPDATA%\\SocialDock``) ;
* le serveur écoute sur 127.0.0.1 par défaut et ne s'expose sur le réseau
  local que sur configuration explicite ;
* les secrets (tokens OAuth) sont chiffrés avant d'atteindre SQLite.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "SocialDock"


def _default_data_dir() -> Path:
    """Répertoire utilisateur persistant, indépendant du dépôt Git."""
    override = os.environ.get("SOCIALDOCK_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":  # Windows
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME.lower()


class Settings(BaseSettings):
    """Paramètres runtime (variables d'environnement préfixées ``SOCIALDOCK_``)."""

    model_config = SettingsConfigDict(env_prefix="SOCIALDOCK_", env_file=".env", extra="ignore")

    # Réseau
    host: str = "127.0.0.1"
    port: int = 8000
    # Données
    data_dir: Path = Field(default_factory=_default_data_dir)
    database_url: str | None = None
    # Sécurité
    secret_key: str | None = None
    api_token: str | None = None
    require_local_origin: bool = True
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"])
    # Publication
    demo_mode: bool = True
    scheduler_tick_seconds: int = 5
    publish_timeout_seconds: int = 120
    max_publish_attempts: int = 3
    # Identifiants des applications développeur (fournis par l'utilisateur)
    google_client_id: str | None = None
    google_client_secret: str | None = None
    meta_app_id: str | None = None
    meta_app_secret: str | None = None
    tiktok_client_key: str | None = None
    tiktok_client_secret: str | None = None
    oauth_redirect_base: str = "http://127.0.0.1:8000"

    # ---- Chemins dérivés -------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.data_dir / "socialdock.db"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def thumbnails_dir(self) -> Path:
        return self.data_dir / "thumbnails"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def secrets_dir(self) -> Path:
        return self.data_dir / "secrets"

    @property
    def key_file(self) -> Path:
        return self.secrets_dir / "socialdock.key"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.media_dir, self.thumbnails_dir, self.logs_dir, self.secrets_dir):
            path.mkdir(parents=True, exist_ok=True)

    def safe_media_path(self, relative: str) -> Path:
        """Résout un chemin média en refusant toute évasion hors du dossier média."""
        candidate = (self.media_dir / relative).resolve()
        root = self.media_dir.resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError(f"Chemin média invalide (path traversal refusé) : {relative!r}")
        return candidate

    def public_dict(self) -> dict[str, Any]:
        """Version sans secret, utilisable dans la page Diagnostics."""
        return {
            "version": "0.1.0",
            "data_dir": str(self.data_dir),
            "database": str(self.db_path),
            "media_dir": str(self.media_dir),
            "host": self.host,
            "port": self.port,
            "demo_mode": self.demo_mode,
            "scheduler_tick_seconds": self.scheduler_tick_seconds,
            "google_configured": bool(self.google_client_id and self.google_client_secret),
            "meta_configured": bool(self.meta_app_id and self.meta_app_secret),
            "tiktok_configured": bool(self.tiktok_client_key and self.tiktok_client_secret),
        }


@dataclass(slots=True)
class _SettingsHolder:
    current: Settings | None = None


_holder = _SettingsHolder()


def get_settings() -> Settings:
    """Singleton de configuration (créé au premier appel)."""
    if _holder.current is None:
        _holder.current = Settings()
        _holder.current.ensure_dirs()
    return _holder.current


def set_settings(settings: Settings) -> Settings:
    """Remplace la configuration globale — utilisé par les tests."""
    _holder.current = settings
    settings.ensure_dirs()
    return settings


def reset_settings() -> None:
    _holder.current = None


def generate_api_token() -> str:
    return secrets.token_urlsafe(32)
