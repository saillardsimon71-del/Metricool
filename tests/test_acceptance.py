"""Parcours complet d'utilisation, exécuté via l'API réelle.

Ce test joue le scénario nominal : import → composition 6 destinations →
programmation → exécution du scheduler → résultats hétérogènes → statistiques.
Il vérifie aussi que l'état survit à un redémarrage du moteur.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from socialdock.config import Settings
from socialdock.database import get_session_factory
from socialdock.models import PostStatus, PostTarget, PublishAttempt, utcnow
from socialdock.services.media_service import import_path
from socialdock.services.scheduler import SchedulerEngine
from tests.conftest import FakeConnector


@pytest.fixture()
def media_id(settings: Settings, sample_video) -> str:
    session = get_session_factory()()
    try:
        asset = import_path(session, sample_video, settings=settings).asset
        session.commit()
        return asset.id
    finally:
        session.close()


def test_parcours_complet_de_publication(client: TestClient, media_id: str, settings: Settings, monkeypatch):
    # 1. Six destinations : 2 TikTok, 2 Instagram, 2 YouTube
    accounts = client.post("/api/accounts/demo/seed").json()
    assert len(accounts) == 6

    # 2. Une seule vidéo, six publications, aucune publication publique par défaut
    composer = client.post(
        "/api/posts",
        json={
            "title": "Épisode pilote",
            "description": "Description commune partagée",
            "hashtags": ["ia", "shorts"],
            "media_asset_id": media_id,
            "account_ids": [account["id"] for account in accounts],
        },
    ).json()
    assert len(composer["targets"]) == 6
    assert all(target["status"] == PostStatus.DRAFT.value for target in composer["targets"])

    # 3. Validation par plateforme avant publication
    platform_of = {account["id"]: account["platform"] for account in accounts}
    for target in composer["targets"]:
        platform = platform_of[target["account_id"]]
        validation = client.get(f"/api/media/{media_id}/validate/{platform}").json()
        assert validation["ok"] is True, f"{platform} : {validation.get('errors')}"

    # 4. Programmation à un instant déjà écoulé (le prochain tick les exécute)
    echeance = (utcnow() - timedelta(minutes=1)).isoformat()
    for target in composer["targets"]:
        assert client.post(f"/api/posts/targets/{target['id']}/schedule", json={"scheduled_at": echeance}).status_code == 200

    # 5. Statut du scheduler : 6 tâches en attente
    assert client.get("/api/scheduler/status").json()["scheduled_count"] == 6

    # 6. Exécution : résultats hétérogènes programmés explicitement
    outcomes = ["success", "private", "failure", "uncertain", "success", "waiting"]
    connectors: dict[str, FakeConnector] = {}

    def fake_for_account(account, settings=None, client=None):
        connector = FakeConnector(outcomes=[outcomes[len(connectors) % len(outcomes)]])
        connectors[account.id] = connector
        return connector

    monkeypatch.setattr("socialdock.services.publisher.connector_for_account", fake_for_account)
    engine = SchedulerEngine(settings=settings, session_factory=get_session_factory())
    report = engine.run_tick()
    assert report.due == 6
    assert report.errors == 0

    # 7. Vérification des états finaux : aucun faux succès
    session = get_session_factory()()
    try:
        statuses = {
            target.id: target.status
            for target in session.scalars(select(PostTarget).where(PostTarget.post_id == composer["id"]))
        }
        assert sorted(statuses.values()) == sorted(
            [
                PostStatus.PUBLISHED.value,
                PostStatus.PUBLISHED.value,
                PostStatus.PUBLISHED_PRIVATE.value,
                PostStatus.FAILED.value,
                PostStatus.UNCERTAIN.value,
                PostStatus.WAITING_FOR_USER.value,
            ]
        )
        # Chaque publication publiée porte une preuve : identifiant + URL
        for target in session.scalars(
            select(PostTarget).where(PostTarget.status.in_([PostStatus.PUBLISHED.value, PostStatus.PUBLISHED_PRIVATE.value]))
        ):
            assert target.remote_id and target.remote_url and target.published_at
        attempts = session.scalars(select(PublishAttempt)).all()
        assert len(attempts) == 6
    finally:
        session.close()

    # 8. Relance du scheduler : rien n'est republié (idempotence après redémarrage)
    engine2 = SchedulerEngine(settings=settings, session_factory=get_session_factory())
    report2 = engine2.run_tick()
    assert report2.due == 0
    assert all(connector.calls.count("publish") == 1 for connector in connectors.values())

    # 9. Statistiques uniquement à partir de données de connecteur
    stats = client.post("/api/stats/collect").json()
    assert stats["samples_stored"] >= 1
    ranking = client.get("/api/stats/ranking").json()
    assert ranking["items"]

    # 10. Diagnostics cohérents
    diagnostics = client.get("/api/diagnostics").json()
    assert diagnostics["database"]["ok"] is True
    assert diagnostics["scheduler"]["tick_seconds"] == settings.scheduler_tick_seconds


def test_mode_assiste_complet(client: TestClient, media_id: str):
    """Compte sans capacité de publication : préparer, copier, puis valider."""
    accounts = client.post("/api/accounts/demo/seed").json()
    tiktok = next(account for account in accounts if account["platform"] == "tiktok")
    post = client.post(
        "/api/posts",
        json={"title": "Assisté", "description": "Légende à copier", "hashtags": ["fyp"], "media_asset_id": media_id, "account_ids": [tiktok["id"]]},
    ).json()
    target = post["targets"][0]
    assisted = client.post(f"/api/posts/targets/{target['id']}/assisted").json()
    assert assisted["status"] == PostStatus.WAITING_FOR_USER.value
    assert assisted["user_action_hint"]
    completed = client.post(
        f"/api/posts/targets/{target['id']}/assisted/complete",
        json={"status": "published", "remote_url": "https://www.tiktok.com/@moi/video/777"},
    ).json()
    assert completed["status"] == PostStatus.PUBLISHED.value
    assert completed["remote_url"].endswith("/777")


def test_survie_d_un_redemarrage_apres_arret_brutal(client: TestClient, settings: Settings, monkeypatch):
    """Cibles verrouillées par un processus mort : incertaines, jamais republiées."""
    from socialdock.database import get_session_factory
    from socialdock.models import PostTarget

    accounts = client.post("/api/accounts/demo/seed").json()
    post = client.post("/api/posts", json={"title": "Interrompu", "account_ids": [accounts[0]["id"]]}).json()
    session = get_session_factory()()
    try:
        target = session.get(PostTarget, post["targets"][0]["id"])
        target.status = PostStatus.UPLOADING.value
        target.locked_by = "processus-mort"
        target.locked_at = utcnow() - timedelta(minutes=40)
        target.lock_expires_at = utcnow() - timedelta(minutes=25)
        session.commit()
    finally:
        session.close()

    connector = FakeConnector()
    monkeypatch.setattr("socialdock.services.publisher.connector_for_account", lambda account, settings=None, client=None: connector)
    engine = SchedulerEngine(settings=settings, session_factory=get_session_factory())
    result = engine.recover_interrupted()
    assert result["released"] == 1
    assert result["ambiguous"] == 1
    engine.run_tick()
    assert connector.calls == [], "une publication ambiguë ne doit jamais être relancée automatiquement"

    detail = client.get(f"/api/posts/{post['id']}").json()
    assert detail["targets"][0]["status"] == PostStatus.UNCERTAIN.value
    assert detail["targets"][0]["requires_user_action"] is True
