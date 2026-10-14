"""Contrat commun des connecteurs sociaux.

Un connecteur ne ment jamais : il retourne un :class:`PublishResult` dont
l'``outcome`` reflète ce qui a réellement été observé. En cas de doute
(timeout après envoi, réponse illisible) il renvoie ``uncertain`` et laisse le
scheduler refuser toute republication automatique.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ..models import Account, Post, PostTarget


class ConnectorError(RuntimeError):
    """Erreur réseau/protocolaire non récupérable."""

    def __init__(self, message: str, *, code: str | None = None, http_status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class RetriableError(ConnectorError):
    """Erreur transitoire : le scheduler peut réessayer avec backoff."""


class PermanentError(ConnectorError):
    """Erreur définitive (permission, quota, refus de contenu) : ne pas réessayer."""


class AmbiguousError(ConnectorError):
    """Issue inconnue : la publication a peut-être abouti. Statut ``uncertain``."""


@dataclass(slots=True)
class Capabilities:
    """Ce que la plateforme autorise réellement pour un compte donné."""

    platform: str
    label: str
    auth_available: bool = True
    publish_video: bool = True
    publish_public: bool = False
    scheduling: bool = False
    upload: bool = True
    analytics: bool = False
    assisted_mode: bool = True
    requires_review: bool = False
    restrictions: list[str] = field(default_factory=list)
    permissions_required: list[str] = field(default_factory=list)
    permissions_missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "label": self.label,
            "auth_available": self.auth_available,
            "publish_video": self.publish_video,
            "publish_public": self.publish_public,
            "scheduling": self.scheduling,
            "upload": self.upload,
            "analytics": self.analytics,
            "assisted_mode": self.assisted_mode,
            "requires_review": self.requires_review,
            "restrictions": list(self.restrictions),
            "permissions_required": list(self.permissions_required),
            "permissions_missing": list(self.permissions_missing),
        }


@dataclass(slots=True)
class AuthStart:
    authorization_url: str
    state: str
    scopes: list[str]
    redirect_uri: str
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PublishResult:
    outcome: str  # success | failure | timeout | uncertain
    status: str  # PostStatus
    remote_id: str | None = None
    remote_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    http_status: int | None = None
    operation_id: str | None = None
    requires_user_action: bool = False
    user_action_hint: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StatusResult:
    status: str  # PostStatus
    remote_url: str | None = None
    remote_id: str | None = None
    detail: str | None = None


@dataclass(slots=True)
class PublishContext:
    """Tout ce dont un connecteur a besoin pour publier une cible."""

    target: PostTarget
    post: Post
    account: Account
    credential: dict[str, Any]
    media_path: Path | None = None
    thumbnail_path: Path | None = None
    progress: Callable[[int, str], None] | None = None
    timeout: int = 120

    def report(self, percent: int, message: str) -> None:
        if self.progress is not None:
            self.progress(percent, message)


class SocialConnector(abc.ABC):
    """Interface modulaire — chaque plateforme l'implémente à sa façon."""

    platform: str = "unknown"
    label: str = "Inconnu"

    def __init__(self, client: httpx.Client | None = None, *, timeout: float = 60.0) -> None:
        self._client = client
        self._timeout = timeout

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout, follow_redirects=False)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # -- capacités ---------------------------------------------------------
    @abc.abstractmethod
    def get_capabilities(self, account: Account | None = None) -> Capabilities: ...

    # -- authentification --------------------------------------------------
    def begin_auth(self, *, state: str, redirect_uri: str, account: Account | None = None) -> AuthStart:
        raise PermanentError(f"{self.label} : authentification non configurée.")

    def handle_auth_callback(self, *, code: str, state: str, redirect_uri: str, code_verifier: str | None = None) -> dict[str, Any]:
        raise PermanentError(f"{self.label} : callback non supporté.")

    def refresh_auth(self, credential: dict[str, Any]) -> dict[str, Any]:
        raise PermanentError(f"{self.label} : rafraîchissement non supporté.")

    def revoke_auth(self, credential: dict[str, Any]) -> None:
        return None

    def get_account_info(self, credential: dict[str, Any]) -> dict[str, Any]:
        raise PermanentError(f"{self.label} : informations de compte indisponibles.")

    # -- validation --------------------------------------------------------
    def validate_media(self, probe: dict[str, Any]) -> dict[str, Any]:
        from .platform_rules import get_spec

        return get_spec(self.platform).validate(probe)

    def validate_post(self, payload: dict[str, Any]) -> list[str]:
        """Erreurs bloquantes sur la charge utile (titres trop longs, etc.)."""
        from .platform_rules import get_spec

        spec = get_spec(self.platform)
        errors: list[str] = []
        title = payload.get("title")
        if spec.title_limit and title and len(title) > spec.title_limit:
            errors.append(f"Titre trop long : {len(title)}/{spec.title_limit} caractères.")
        caption = payload.get("caption") or payload.get("description") or ""
        if caption and len(caption) > spec.caption_limit:
            errors.append(f"Description trop longue : {len(caption)}/{spec.caption_limit} caractères.")
        return errors

    # -- publication -------------------------------------------------------
    def upload_media(self, context: PublishContext) -> dict[str, Any]:
        raise PermanentError(f"{self.label} : upload non supporté.")

    @abc.abstractmethod
    def publish(self, context: PublishContext) -> PublishResult: ...

    def get_publish_status(self, context: PublishContext) -> StatusResult:
        raise PermanentError(f"{self.label} : statut distant indisponible.")

    def get_post_url(self, context: PublishContext) -> str | None:
        return context.target.remote_url

    def get_analytics(self, context: PublishContext) -> dict[str, Any]:
        raise PermanentError(f"{self.label} : statistiques indisponibles pour ce connecteur.")

    def disconnect(self, credential: dict[str, Any]) -> None:
        self.revoke_auth(credential)

    # -- utilitaires -------------------------------------------------------
    def assisted_hint(self, context: PublishContext) -> str:
        """Message d'assistance quand l'automatisation n'est pas autorisée."""
        return (
            f"Publication assistée {self.label} : ouvrez la plateforme, importez le média "
            f"« {context.post.title} », collez la description préparée puis renseignez le lien publié."
        )
