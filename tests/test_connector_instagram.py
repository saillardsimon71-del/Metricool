"""Connecteur Instagram (API avec Instagram Login) — réponses API simulées."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from socialdock.connectors.base import PermanentError, PublishContext
from socialdock.connectors.instagram import InstagramConnector
from socialdock.models import Account, Post, PostTarget


def context(tmp_path: Path, *, video_url: str | None = None, caption: str | None = None) -> PublishContext:
    media = tmp_path / "reel.mp4"
    media.write_bytes(b"0" * 2048)
    account = Account(id="acc", platform="instagram", display_name="IG", mode="real", external_id="1784", extra={})
    post = Post(id="post", title="Reel", description=caption or "Légende commune", hashtags=["reels", "ia"], language="fr")
    payload = {"share_to_feed": True, "thumb_offset_ms": 1500}
    if video_url:
        payload["video_url"] = video_url
    target = PostTarget(id="t1", post_id=post.id, account_id=account.id, idempotency_key="idem", payload=payload)
    return PublishContext(
        target=target, post=post, account=account,
        credential={"access_token": "IGQtoken", "user_id": "1784"}, media_path=media,
    )


def build(handler) -> InstagramConnector:
    return InstagramConnector(app_id="app", app_secret="secret", client=httpx.Client(transport=httpx.MockTransport(handler)), api_version="v23.0")


def test_publication_complete_conteneur_rupload_publish(tmp_path: Path):
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, f"{request.url.host}{request.url.path}"))
        if request.url.host == "rupload.facebook.com":
            assert request.headers["offset"] == "0"
            assert request.headers["file_size"] == "2048"
            assert request.headers["Authorization"].startswith("OAuth ")
            return httpx.Response(200, json={"id": "media-upload"})
        if request.url.path.endswith("/media"):
            body = dict(httpx.QueryParams(request.content.decode()))
            assert body["media_type"] == "REELS"
            assert body["upload_type"] == "resumable", "sans URL publique, l'upload résumable est obligatoire"
            assert "#reels" in body["caption"]
            assert body["thumb_offset"] == "1500"
            return httpx.Response(200, json={"id": "CONTAINER1"})
        if request.url.path.endswith("/CONTAINER1"):
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if request.url.path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "MEDIA9"})
        if request.url.path.endswith("/MEDIA9"):
            return httpx.Response(200, json={"permalink": "https://www.instagram.com/reel/ABC/"})
        return httpx.Response(404, json={"error": {"message": "inattendu", "code": 100}})

    connector = build(handler)
    result = connector.publish(context(tmp_path))
    assert result.outcome == "success"
    assert result.status == "published"
    assert result.remote_id == "MEDIA9"
    assert result.remote_url == "https://www.instagram.com/reel/ABC/"
    assert ("POST", "rupload.facebook.com/ig-api-upload/v23.0/CONTAINER1") in calls


def test_mode_url_publique_ignore_l_upload_resumable(tmp_path: Path):
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.path.endswith("/media"):
            body = dict(httpx.QueryParams(request.content.decode()))
            assert body["video_url"] == "https://cdn.exemple.com/reel.mp4"
            assert "upload_type" not in body
            return httpx.Response(200, json={"id": "C2"})
        if request.url.path.endswith("/C2"):
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if request.url.path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "M2"})
        return httpx.Response(200, json={"permalink": "https://www.instagram.com/reel/M2/"})

    connector = build(handler)
    result = connector.publish(context(tmp_path, video_url="https://cdn.exemple.com/reel.mp4"))
    assert result.outcome == "success"
    assert "rupload.facebook.com" not in hosts


def test_conteneur_en_erreur_echec_explicite(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("socialdock.connectors.instagram.POLL_INTERVAL_SECONDS", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "C3"})
        if request.url.host == "rupload.facebook.com":
            return httpx.Response(200, json={})
        if request.url.path.endswith("/C3"):
            return httpx.Response(200, json={"status_code": "ERROR", "status": "codec non supporté"})
        return httpx.Response(404)

    connector = build(handler)
    result = connector.publish(context(tmp_path))
    assert result.outcome == "failure"
    assert result.error_code == "instagram_container_error"


def test_compte_personnel_refuse():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"user_id": "1784", "username": "moi", "account_type": "PERSONAL"})

    connector = build(handler)
    with pytest.raises(PermanentError, match="Professionnel"):
        connector.get_account_info({"access_token": "IGQ"})


def test_compte_professionnel_accepte():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"user_id": "1784", "username": "moi", "name": "Mon compte", "account_type": "CREATOR", "media_count": 12})

    connector = build(handler)
    info = connector.get_account_info({"access_token": "IGQ"})
    assert info["account_type"] == "CREATOR"
    assert info["id"] == "1784"


def test_echange_de_code_puis_jeton_longue_duree():
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = dict(httpx.QueryParams(request.content.decode()))
        seen.append(body)
        if body.get("grant_type") == "authorization_code":
            return httpx.Response(200, json={"access_token": "court", "user_id": "1784"})
        if body.get("grant_type") == "ig_exchange_token":
            return httpx.Response(200, json={"access_token": "longue-duree", "expires_in": 5184000, "user_id": "1784"})
        return httpx.Response(200, json={"access_token": "renouvele", "expires_in": 5184000})

    connector = build(handler)
    credential = connector.handle_auth_callback(code="code", state="s", redirect_uri="http://127.0.0.1:8000/api/oauth/instagram/callback")
    assert credential["access_token"] == "longue-duree"
    assert seen[1]["grant_type"] == "ig_exchange_token"
    renewed = connector.refresh_auth(credential)
    assert renewed["access_token"] == "renouvele"


def test_quota_de_publication_lu():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"config": {"quota_total": 100, "quota_duration": 86400}, "quota_usage": 7}]})

    connector = build(handler)
    quota = connector.get_publishing_quota({"access_token": "IGQ"}, "1784")
    assert quota == {"quota_total": 100, "quota_usage": 7, "quota_duration": 86400}


def test_statistiques_media_mappees():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [
            {"name": "views", "values": [{"value": 3200}]},
            {"name": "likes", "values": [{"value": 180}]},
            {"name": "reach", "values": [{"value": 2900}]},
        ]})

    connector = build(handler)
    ctx = context(Path("/tmp"))
    ctx.target.remote_id = "MEDIA9"
    analytics = connector.get_analytics(ctx)
    assert analytics["metrics"] == {"views": 3200, "likes": 180, "reach": 2900}


def test_capacites_refletent_les_contraintes_reelles():
    connector = build(lambda request: httpx.Response(200, json={}))
    capabilities = connector.get_capabilities(Account(platform="instagram", display_name="x"))
    assert capabilities.publish_public is True
    assert capabilities.scheduling is False, "Instagram n'a pas de programmation native"
    assert any("Professionnel" in line for line in capabilities.restrictions)


def test_erreur_de_quota_est_reessayable(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "limite atteinte", "code": "4"}})

    connector = build(handler)
    result = connector.publish(context(tmp_path))
    assert result.outcome == "timeout"  # erreur transitoire : le scheduler réessaiera
    assert result.status == "failed"
