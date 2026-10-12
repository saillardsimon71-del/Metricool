"""API d'ingestion sécurisée (Studio IA) : jeton, périmètre de chemins, brouillon."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from socialdock.config import Settings
from socialdock.models import WatchedFolder


@pytest.fixture()
def token(settings: Settings) -> str:
    from socialdock.security import local_api_token

    return local_api_token(settings)


def auth(token: str) -> dict[str, str]:
    return {"X-SocialDock-Token": token}


def test_ping_sans_jeton_refuse(client: TestClient):
    assert client.get("/api/ingest/ping").status_code == 401


def test_ping_avec_jeton_invalide_refuse(client: TestClient, token: str):
    assert client.get("/api/ingest/ping", headers=auth("mauvais-jeton")).status_code == 401
    # un en-tête d'autorisation classique ne remplace pas l'en-tête attendu
    assert client.get("/api/ingest/ping", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_ping_avec_jeton_valide(client: TestClient, token: str):
    assert client.get("/api/ingest/ping", headers=auth(token)).json()["status"] == "ok"


def test_ingestion_par_chemin_dans_un_dossier_surveille(client: TestClient, token: str, settings: Settings, sample_video):
    watched = settings.data_dir / "studio"
    watched.mkdir(exist_ok=True)
    source = watched / "rendu.mp4"
    source.write_bytes(sample_video.read_bytes())
    session_client = client.get("/api/health")  # la base est initialisée par le client
    from socialdock.database import get_session_factory

    session = get_session_factory()()
    session.add(WatchedFolder(path=str(watched), recursive=False, enabled=True))
    session.commit()
    session.close()

    response = client.post(
        "/api/ingest/video",
        headers=auth(token),
        json={"path": str(source), "title": "Rendu Studio IA", "tags": ["studio-ai"], "create_draft": True},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["draft_post_id"]
    draft = client.get(f"/api/posts/{body['draft_post_id']}").json()
    assert draft["title"] == "Rendu Studio IA"
    assert draft["media_asset_id"] == body["media_id"]
    # Un brouillon n'a pas encore de cible : le statut vit sur les cibles
    assert draft["targets"] == []


def test_ingestion_hors_des_dossiers_autorises_refusee(client: TestClient, token: str, settings: Settings):
    hors = Path(settings.data_dir).parent / "hors-perimetre.mp4"
    hors.write_bytes(b"0" * 1024)
    response = client.post("/api/ingest/video", headers=auth(token), json={"path": str(hors)})
    assert response.status_code == 403
    assert "autorisés" in response.json()["detail"]


def test_ingestion_refuse_une_traversee_de_chemin(client: TestClient, token: str, settings: Settings):
    watched = settings.data_dir / "studio"
    watched.mkdir(exist_ok=True)
    from socialdock.database import get_session_factory

    session = get_session_factory()()
    session.add(WatchedFolder(path=str(watched), recursive=False, enabled=True))
    session.commit()
    session.close()
    response = client.post("/api/ingest/video", headers=auth(token), json={"path": f"{watched}/../../etc/passwd"})
    # /etc/passwd n'est ni dans le périmètre ni un format média supporté
    assert response.status_code in (400, 403, 404)
    assert response.status_code != 201


def test_ingestion_par_televersement(client: TestClient, token: str, sample_video):
    response = client.post(
        "/api/ingest/upload",
        headers=auth(token),
        files={"file": ("rendu.mp4", sample_video.read_bytes(), "video/mp4")},
        data={"title": "Depuis Studio IA", "tags": "ia,studio"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    media = client.get(f"/api/media/{body['media_id']}").json()
    assert media["original_name"] == "rendu.mp4"
    assert media["imported_from"].startswith("studio-ai-upload:")


def test_doublon_detecte_et_dedupliqué(client: TestClient, token: str, sample_video):
    premier = client.post(
        "/api/ingest/upload",
        headers=auth(token),
        files={"file": ("meme.mp4", sample_video.read_bytes(), "video/mp4")},
    ).json()
    second = client.post(
        "/api/ingest/upload",
        headers=auth(token),
        files={"file": ("copie.mp4", sample_video.read_bytes(), "video/mp4")},
    ).json()
    assert second["created"] is False
    assert second["duplicate_of"] == premier["media_id"]
    assert second["media_id"] == premier["media_id"]
