"""Connecteur TikTok Content Posting API — réponses API simulées."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from socialdock.connectors.base import PermanentError, PublishContext, RetriableError
from socialdock.connectors.tiktok import MAX_CHUNK, MIN_CHUNK, TikTokConnector
from socialdock.models import Account, Post, PostTarget


def context(tmp_path: Path, *, privacy: str = "PUBLIC_TO_EVERYONE", mode: str = "direct", audited: bool = False, size: int = 2048) -> PublishContext:
    media = tmp_path / "tiktok.mp4"
    media.write_bytes(b"0" * size)
    account = Account(id="acc", platform="tiktok", display_name="TikTok", mode="real", extra={"audit_passed": audited})
    post = Post(id="post", title="Clip", description="Légende commune", hashtags=["fyp", "ia"], language="fr")
    target = PostTarget(
        id="t1", post_id=post.id, account_id=account.id, idempotency_key="idem",
        payload={"privacy": privacy, "mode": mode, "is_aigc": True},
    )
    return PublishContext(target=target, post=post, account=account, credential={"access_token": "tt.token"}, media_path=media)


def build(handler) -> TikTokConnector:
    return TikTokConnector(client_key="key", client_secret="secret", client=httpx.Client(transport=httpx.MockTransport(handler)))


def creator_response(options=None, duration=180) -> dict:
    return {
        "data": {
            "privacy_level_options": options or ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
            "max_video_post_duration_sec": duration,
            "creator_info": {"creator_username": "moi", "creator_avatar_url": "https://x/y.png"},
        }
    }


def test_plan_de_morceaux_conforme_aux_regles_tiktok():
    assert TikTokConnector._chunk_plan(1024) == 1024, "un fichier < 5 Mo part en un seul morceau"
    assert TikTokConnector._chunk_plan(MIN_CHUNK) == MIN_CHUNK
    assert TikTokConnector._chunk_plan(200 * 1024 * 1024) == MAX_CHUNK
    # Au-delà de 1000 morceaux de 64 Mo, FILE_UPLOAD ne peut pas respecter les
    # règles TikTok : le connecteur doit refuser explicitement.

    with pytest.raises(PermanentError, match="FILE_UPLOAD"):
        TikTokConnector._chunk_plan(90 * 1024 * 1024 * 1024)


def test_publication_directe_apres_audit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("socialdock.connectors.tiktok.POLL_INTERVAL_SECONDS", 0)
    init_body: dict = {}
    upload_headers: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/creator_info/query/"):
            return httpx.Response(200, json=creator_response())
        if request.url.path.endswith("/video/init/"):
            init_body.update(json.loads(request.content))
            return httpx.Response(200, json={"data": {"publish_id": "PUB1", "upload_url": "https://upload.tiktok/put"}})
        if request.url.host == "upload.tiktok":
            upload_headers.append(dict(request.headers))
            return httpx.Response(201)
        if request.url.path.endswith("/status/fetch/"):
            return httpx.Response(200, json={"data": {"status": "PUBLISH_COMPLETE"}})
        return httpx.Response(404, json={"error": {"code": "not_found", "message": "?"}})

    connector = build(handler)
    result = connector.publish(context(tmp_path, audited=True))
    assert result.outcome == "success"
    assert result.status == "published"
    assert init_body["post_info"]["privacy_level"] == "PUBLIC_TO_EVERYONE"
    assert init_body["post_info"]["is_aigc"] is True
    assert init_body["source_info"]["source"] == "FILE_UPLOAD"
    assert init_body["source_info"]["video_size"] == 2048
    assert "#fyp" in init_body["post_info"]["title"]
    assert upload_headers[0]["content-range"] == "bytes 0-2047/2048"
    assert result.remote_url == "https://www.tiktok.com/@moi"


def test_sans_audit_publication_forcee_en_self_only(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("socialdock.connectors.tiktok.POLL_INTERVAL_SECONDS", 0)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/creator_info/query/"):
            return httpx.Response(200, json=creator_response())
        if request.url.path.endswith("/video/init/"):
            captured.update(json.loads(request.content))
            return httpx.Response(200, json={"data": {"publish_id": "PUB2", "upload_url": "https://upload.tiktok/put"}})
        if request.url.host == "upload.tiktok":
            return httpx.Response(201)
        return httpx.Response(200, json={"data": {"status": "PUBLISH_COMPLETE"}})

    connector = build(handler)
    result = connector.publish(context(tmp_path, privacy="PUBLIC_TO_EVERYONE", audited=False))
    assert captured["post_info"]["privacy_level"] == "SELF_ONLY"
    assert result.status == "published_private"
    assert result.requires_user_action is True


def test_niveau_de_confidentialite_indisponible_replie(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("socialdock.connectors.tiktok.POLL_INTERVAL_SECONDS", 0)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/creator_info/query/"):
            return httpx.Response(200, json=creator_response(options=["SELF_ONLY"], duration=180))
        if request.url.path.endswith("/video/init/"):
            captured.update(json.loads(request.content))
            return httpx.Response(200, json={"data": {"publish_id": "PUB3", "upload_url": "https://upload.tiktok/put"}})
        if request.url.host == "upload.tiktok":
            return httpx.Response(201)
        return httpx.Response(200, json={"data": {"status": "PUBLISH_COMPLETE"}})

    connector = build(handler)
    connector.publish(context(tmp_path, audited=True))
    assert captured["post_info"]["privacy_level"] == "SELF_ONLY"


def test_mode_inbox_demande_une_action_humaine(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("socialdock.connectors.tiktok.POLL_INTERVAL_SECONDS", 0)
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/creator_info/query/"):
            return httpx.Response(200, json=creator_response())
        if request.url.path.endswith("/inbox/video/init/"):
            return httpx.Response(200, json={"data": {"publish_id": "PUB4", "upload_url": "https://upload.tiktok/put"}})
        if request.url.host == "upload.tiktok":
            return httpx.Response(201)
        return httpx.Response(200, json={"data": {"status": "PUBLISH_COMPLETE"}})

    connector = build(handler)
    result = connector.publish(context(tmp_path, mode="inbox", audited=True))
    assert result.status == "waiting_for_user"
    assert result.requires_user_action is True
    assert any("/inbox/video/init/" in path for path in paths)


def test_echec_de_publication_avec_raison(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("socialdock.connectors.tiktok.POLL_INTERVAL_SECONDS", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/creator_info/query/"):
            return httpx.Response(200, json=creator_response())
        if request.url.path.endswith("/video/init/"):
            return httpx.Response(200, json={"data": {"publish_id": "PUB5", "upload_url": "https://upload.tiktok/put"}})
        if request.url.host == "upload.tiktok":
            return httpx.Response(201)
        return httpx.Response(200, json={"data": {"status": "FAILED", "fail_reason": "file_format_check_failed"}})

    connector = build(handler)
    result = connector.publish(context(tmp_path, audited=True))
    assert result.outcome == "failure"
    assert "file_format_check_failed" in result.error_message


def test_application_non_auditee_erreur_explicite(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/creator_info/query/"):
            return httpx.Response(200, json=creator_response())
        return httpx.Response(
            403,
            json={"error": {"code": "unaudited_client_can_only_post_to_private_accounts", "message": "audit requis"}},
        )

    connector = build(handler)
    result = connector.publish(context(tmp_path, audited=True))
    assert result.outcome == "failure"
    assert "unaudited_client_can_only_post_to_private_accounts" in (result.error_code or "")


def test_limite_de_debit_reessayable(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": "6 req/min"}})

    connector = build(handler)
    with pytest.raises(RetriableError):
        connector.creator_info({"access_token": "tt"})


def test_echange_oauth_avec_pkce():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"access_token": "tt.new", "refresh_token": "tt.refresh", "expires_in": 86400, "scope": "video.publish"})

    connector = build(handler)
    credential = connector.handle_auth_callback(code="c", state="s", redirect_uri="http://127.0.0.1:8000/api/oauth/tiktok/callback", code_verifier="verif")
    assert credential["access_token"] == "tt.new"
    assert captured["code_verifier"] == "verif"
    assert captured["grant_type"] == "authorization_code"


def test_url_d_autorisation_contient_pkce_et_scopes():
    connector = build(lambda request: httpx.Response(200, json={}))
    start = connector.begin_auth(state="etat", redirect_uri="http://127.0.0.1:8000/api/oauth/tiktok/callback")
    assert "code_challenge_method=S256" in start.authorization_url
    assert "video.publish" in start.authorization_url
    assert start.notes[0], "le code_verifier doit être conservé pour l'échange"


def test_capacites_sans_audit():
    connector = build(lambda request: httpx.Response(200, json={}))
    capabilities = connector.get_capabilities(Account(platform="tiktok", display_name="x"))
    assert capabilities.publish_public is False
    assert capabilities.analytics is False
    assert any("SELF_ONLY" in line for line in capabilities.restrictions)


def test_informations_createur():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=creator_response(duration=600))

    connector = build(handler)
    info = connector.get_account_info({"access_token": "tt"})
    assert info["username"] == "moi"
    assert info["max_video_post_duration_sec"] == 600
