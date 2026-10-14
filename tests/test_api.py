"""Tests d'intégration de l'API FastAPI (base SQLite + routes)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from socialdock.models import utcnow
from socialdock.services.media_service import import_path


@pytest.fixture()
def media_id(client: TestClient, sample_video, settings) -> str:
    from socialdock.database import get_session_factory

    session = get_session_factory()()
    try:
        result = import_path(session, sample_video, settings=settings)
        session.commit()
        return result.asset.id
    finally:
        session.close()


def test_health(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["product"] == "SocialDock"


def test_seed_comptes_demo(client: TestClient):
    accounts = client.post("/api/accounts/demo/seed").json()
    assert len(accounts) == 6
    assert {account["platform"] for account in accounts} == {"tiktok", "instagram", "youtube"}
    assert all(account["mode"] == "demo" for account in accounts)


def test_capacites_du_compte_demo(client: TestClient):
    accounts = client.post("/api/accounts/demo/seed").json()
    capabilities = client.get(f"/api/accounts/{accounts[0]['id']}/capabilities").json()
    assert capabilities["platform"] == accounts[0]["platform"]


def test_import_media_et_validation(client: TestClient, sample_video):
    response = client.post("/api/media/import-path", json={"path": str(sample_video)})
    assert response.status_code == 201
    media = response.json()["media"]
    assert media["probe_status"] == "ok"
    validation = client.get(f"/api/media/{media['id']}/validate/tiktok").json()
    assert validation["ok"] is True


def test_import_refuse_un_chemin_hors_autorisation(client: TestClient):
    response = client.post("/api/media/import-path", json={"path": "/etc/passwd"})
    assert response.status_code == 400


def test_composition_multicomptes_et_programmation(client: TestClient, media_id):
    accounts = client.post("/api/accounts/demo/seed").json()
    when = (utcnow() + timedelta(hours=2)).isoformat()
    post = client.post(
        "/api/posts",
        json={
            "title": "Épisode 12",
            "description": "Description commune",
            "hashtags": ["shorts"],
            "media_asset_id": media_id,
            "account_ids": [account["id"] for account in accounts],
        },
    ).json()
    assert len(post["targets"]) == 6
    payloads = {target["payload"].get("privacy") for target in post["targets"] if "privacy" in target["payload"]}
    assert "public" not in payloads, "aucune publication publique par défaut"

    for target in post["targets"]:
        response = client.post(f"/api/posts/targets/{target['id']}/schedule", json={"scheduled_at": when})
        assert response.status_code == 200
        assert response.json()["status"] == "scheduled"

    calendrier = client.get(
        "/api/calendar",
        params={"start": date.today().isoformat(), "end": (date.today() + timedelta(days=2)).isoformat()},
    ).json()
    assert len(calendrier["items"]) == 6


def test_programmation_refuse_un_horaire_sans_fuseau(client: TestClient, media_id):
    accounts = client.post("/api/accounts/demo/seed").json()
    post = client.post("/api/posts", json={"title": "x", "account_ids": [accounts[0]["id"]]}).json()
    response = client.post(f"/api/posts/targets/{post['targets'][0]['id']}/schedule", json={"scheduled_at": "2026-05-01T10:00:00"})
    assert response.status_code == 422


def test_deplacement_calendrier_conserve_les_donnees(client: TestClient, media_id):
    accounts = client.post("/api/accounts/demo/seed").json()
    post = client.post(
        "/api/posts",
        json={"title": "À déplacer", "description": "texte", "hashtags": ["a"], "media_asset_id": media_id, "account_ids": [accounts[0]["id"]]},
    ).json()
    target = post["targets"][0]
    nouvelle_date = (utcnow() + timedelta(days=3)).replace(microsecond=0).isoformat()
    moved = client.post(f"/api/calendar/targets/{target['id']}/move", json={"scheduled_at": nouvelle_date}).json()
    assert moved["status"] == "scheduled"
    refreshed = client.get(f"/api/posts/{post['id']}").json()
    assert refreshed["targets"][0]["payload"]["caption"] or refreshed["targets"][0]["payload"]["title"]
    assert refreshed["description"] == "texte"


def test_suppression_exige_confirmation(client: TestClient, media_id):
    accounts = client.post("/api/accounts/demo/seed").json()
    post = client.post("/api/posts", json={"title": "x", "account_ids": [accounts[0]["id"]]}).json()
    assert client.delete(f"/api/posts/{post['id']}").status_code == 400
    assert client.delete(f"/api/posts/{post['id']}?confirm=true").status_code == 204


def test_mode_assiste_puis_finalisation(client: TestClient, media_id):
    accounts = client.post("/api/accounts/demo/seed").json()
    post = client.post("/api/posts", json={"title": "assisté", "account_ids": [accounts[0]["id"]]}).json()
    target = post["targets"][0]
    assert client.post(f"/api/posts/targets/{target['id']}/assisted").json()["status"] == "waiting_for_user"
    completed = client.post(
        f"/api/posts/targets/{target['id']}/assisted/complete",
        json={"remote_url": "https://www.tiktok.com/@moi/video/1", "status": "published"},
    ).json()
    assert completed["status"] == "published"
    assert completed["remote_url"].endswith("/1")


def test_statut_scheduler_expose(client: TestClient):
    status = client.get("/api/scheduler/status").json()
    assert "running" in status and "tick_seconds" in status


def test_diagnostiques_et_resume(client: TestClient):
    report = client.get("/api/diagnostics").json()
    assert report["database"]["ok"] is True
    assert report["database"]["journal_mode"] == "wal"
    assert {connector["platform"] for connector in report["connectors"]} == {"youtube", "instagram", "tiktok"}
    assert any("youtube" in line.lower() for line in client.get("/api/diagnostics/summary").text.splitlines())


def test_parametres_et_token_d_ingestion(client: TestClient):
    payload = client.get("/api/settings").json()
    assert payload["preferences"]["timezone"] == "Europe/Paris"
    assert len(payload["integrations"]["ingest_token"]) >= 32
    updated = client.patch("/api/settings/preferences", json={"theme": "light", "favorite_times": ["08:00"]}).json()
    assert updated["preferences"]["theme"] == "light"


def test_plateformes_exposent_leurs_regles(client: TestClient):
    platforms = client.get("/api/platforms").json()["platforms"]
    assert platforms["youtube"]["capabilities"]["publish_public"] is False
    assert platforms["instagram"]["capabilities"]["publish_public"] is True
    assert platforms["tiktok"]["capabilities"]["requires_review"] is True


def test_middleware_refuse_les_origines_non_autorisees(client: TestClient):
    response = client.post("/api/posts", json={"title": "x"}, headers={"Origin": "https://malveillant.example"})
    assert response.status_code == 403


def test_batch_schedule(client: TestClient, sample_video, settings):
    from socialdock.database import get_session_factory

    session = get_session_factory()()
    media_ids = []
    for index in range(3):
        copie = settings.data_dir / f"clip-{index}.mp4"
        copie.write_bytes(sample_video.read_bytes() + bytes([index]))
        media_ids.append(import_path(session, copie, settings=settings).asset.id)
    session.commit()
    session.close()
    accounts = client.post("/api/accounts/demo/seed").json()
    result = client.post(
        "/api/posts/batch-schedule",
        json={
            "media_ids": media_ids,
            "account_ids": [account["id"] for account in accounts[:2]],
            "days": [(date.today() + timedelta(days=day)).isoformat() for day in range(3)],
            "times": ["09:00", "18:00"],
        },
    ).json()
    assert len(result["scheduled"]) == 3
    assert all(item["targets"] == 2 for item in result["scheduled"])


def test_404_sur_route_api_inconnue(client: TestClient):
    assert client.get("/api/inexistant").status_code == 404
