"""Fixtures partagées : configuration isolée, base temporaire, comptes démo, vidéo réelle."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def _ensure_ffmpeg() -> None:
    """Rend FFmpeg disponible pour les tests marqués ``ffmpeg``.

    Priorité au binaire système ; à défaut, le paquet optionnel ``imageio-ffmpeg``
    (PyPI) fournit un binaire statique multiplateforme. Ce n'est qu'une commodité
    de test : SocialDock n'en dépend pas à l'exécution.
    """
    if os.environ.get("SOCIALDOCK_FFMPEG"):
        return
    from shutil import which

    if which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg

        os.environ["SOCIALDOCK_FFMPEG"] = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 — FFmpeg reste optionnel
        return


_ensure_ffmpeg()

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from socialdock.config import Settings, set_settings  # noqa: E402
from socialdock.connectors.base import Capabilities, PublishContext, PublishResult, SocialConnector  # noqa: E402
from socialdock.database import create_all, get_session_factory, init_engine  # noqa: E402
from socialdock.models import Account, MediaAsset, Post, PostTarget  # noqa: E402
from socialdock.services import accounts as account_service  # noqa: E402
from socialdock.services.ffprobe import ffmpeg_path  # noqa: E402
from socialdock.services.scheduler import SchedulerEngine  # noqa: E402


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Configuration isolée dans un répertoire temporaire (aucune donnée réelle)."""
    config = Settings(
        data_dir=tmp_path / "socialdock",
        host="127.0.0.1",
        port=8123,
        demo_mode=True,
        require_local_origin=True,
        scheduler_tick_seconds=1,
        google_client_id="test-google-id",
        google_client_secret="test-google-secret",
        meta_app_id="test-meta-id",
        meta_app_secret="test-meta-secret",
        tiktok_client_key="test-tiktok-key",
        tiktok_client_secret="test-tiktok-secret",
    )
    set_settings(config)
    init_engine(config)
    create_all()
    return config


@pytest.fixture()
def session(settings: Settings) -> Iterator[Session]:
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def demo_accounts(session: Session) -> list[Account]:
    return account_service.seed_demo_accounts(session)


@dataclass(slots=True)
class FakeConnector(SocialConnector):
    """Connecteur de test au comportement programmable et journalisé."""

    platform: str = "demo"
    label: str = "Faux connecteur"
    outcomes: list[str] = field(default_factory=lambda: ["success"])
    publish_public: bool = True
    publish_video: bool = True
    auth_available: bool = True
    calls: list[str] = field(default_factory=list)
    remote_id: str = "remote-123"
    analytics: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        # SocialConnector.__init__ n'est pas appelé par @dataclass : on reproduit
        # l'état minimal pour que close() / client fonctionnent comme en réel.
        self._client = None
        self._timeout = 60.0

    def get_capabilities(self, account: Account | None = None) -> Capabilities:
        return Capabilities(
            platform=self.platform,
            label=self.label,
            auth_available=self.auth_available,
            publish_video=self.publish_video,
            publish_public=self.publish_public,
            scheduling=True,
            upload=True,
            analytics=True,
        )

    def publish(self, context: PublishContext) -> PublishResult:
        self.calls.append("publish")
        scenario = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if scenario == "success":
            return PublishResult(outcome="success", status="published", remote_id=self.remote_id, remote_url="https://demo.local/x")
        if scenario == "private":
            return PublishResult(
                outcome="success",
                status="published_private",
                remote_id=self.remote_id,
                remote_url="https://demo.local/private",
                requires_user_action=True,
                user_action_hint="Passer en public",
            )
        if scenario == "failure":
            return PublishResult(outcome="failure", status="failed", error_code="demo_rejected", error_message="Refus simulé", http_status=403)
        if scenario == "uncertain":
            return PublishResult(outcome="uncertain", status="uncertain", error_code="demo_timeout", error_message="Réponse perdue", requires_user_action=True)
        return PublishResult(outcome="success", status="waiting_for_user", requires_user_action=True, user_action_hint="Terminer manuellement")

    def get_publish_status(self, context: PublishContext):
        from socialdock.connectors.base import StatusResult

        self.calls.append("status")
        return StatusResult(status="published", remote_url="https://demo.local/x", remote_id=self.remote_id)

    def get_analytics(self, context: PublishContext) -> dict[str, Any]:
        self.calls.append("analytics")
        if self.analytics is None:
            return {"metrics": {"views": 1234, "likes": 42}, "source": "fake"}
        return dict(self.analytics)


@pytest.fixture()
def fake_connector() -> FakeConnector:
    return FakeConnector()


@pytest.fixture()
def engine(settings: Settings) -> SchedulerEngine:
    return SchedulerEngine(settings, tick_seconds=1)


@pytest.fixture()
def client(settings: Settings, engine: SchedulerEngine) -> Iterator[TestClient]:
    from socialdock.main import create_app

    app = create_app(settings, run_scheduler=False, engine=engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Vidéo 9:16 réelle générée par FFmpeg (test ignoré si FFmpeg absent)."""
    binary = ffmpeg_path()
    if binary is None:
        pytest.skip("FFmpeg indisponible dans cet environnement")
    destination = tmp_path_factory.mktemp("media") / "sample.mp4"
    subprocess.run(
        [
            binary, "-y", "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(destination),
        ],
        check=True,
        capture_output=True,
    )
    return destination


@pytest.fixture()
def imported_media(session: Session, sample_video: Path, settings: Settings) -> MediaAsset:
    from socialdock.services.media_service import import_path

    result = import_path(session, sample_video, tags=["test"], settings=settings)
    session.commit()
    return result.asset


def make_post(session: Session, media: MediaAsset | None, accounts: list[Account]) -> Post:
    from socialdock.services.posts import create_post

    post = create_post(
        session,
        title="Publication de test",
        description="Description commune",
        hashtags=["test", "vertical"],
        media_asset_id=media.id if media else None,
        account_ids=[account.id for account in accounts],
    )
    session.commit()
    return post


def make_target(session: Session, post: Post, account: Account, **overrides: Any) -> PostTarget:
    from socialdock.services.templates import default_payload

    target = PostTarget(post_id=post.id, account_id=account.id, payload=default_payload(account.platform, post), **overrides)
    session.add(target)
    session.commit()
    return target
