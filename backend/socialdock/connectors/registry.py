"""Registre des connecteurs : instanciation selon la configuration et le compte."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings, get_settings
from ..models import Account
from .base import SocialConnector
from .demo import DemoConnector
from .instagram import InstagramConnector
from .tiktok import TikTokConnector
from .youtube import YouTubeConnector

PLATFORM_LABELS = {
    "youtube": "YouTube",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "demo": "Démonstration locale",
}


def build_connector(platform: str, settings: Settings | None = None, *, client: httpx.Client | None = None) -> SocialConnector:
    """Fabrique le connecteur d'une plateforme selon la configuration locale."""
    settings = settings or get_settings()
    base = settings.oauth_redirect_base.rstrip("/")
    if platform == "youtube":
        return YouTubeConnector(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=f"{base}/api/oauth/youtube/callback",
            client=client,
        )
    if platform == "instagram":
        return InstagramConnector(
            app_id=settings.meta_app_id,
            app_secret=settings.meta_app_secret,
            redirect_uri=f"{base}/api/oauth/instagram/callback",
            api_version=settings.meta_api_version,
            client=client,
        )
    if platform == "tiktok":
        return TikTokConnector(
            client_key=settings.tiktok_client_key,
            client_secret=settings.tiktok_client_secret,
            redirect_uri=f"{base}/api/oauth/tiktok/callback",
            client=client,
        )
    return DemoConnector(client=client)


def connector_for_account(account: Account, settings: Settings | None = None, *, client: httpx.Client | None = None) -> SocialConnector:
    """Un compte ``demo`` utilise toujours le connecteur local, même si des
    identifiants API sont configurés — aucune ambiguïté possible."""
    if account.mode == "demo":
        return DemoConnector(client=client)
    return build_connector(account.platform, settings, client=client)


def platform_labels() -> dict[str, str]:
    return dict(PLATFORM_LABELS)


def capabilities_for(account: Account, settings: Settings | None = None) -> dict[str, Any]:
    connector = connector_for_account(account, settings)
    try:
        return connector.get_capabilities(account).as_dict()
    finally:
        connector.close()
