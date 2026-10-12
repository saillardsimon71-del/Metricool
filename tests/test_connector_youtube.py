"""Connecteur YouTube Data API v3 — testé contre des réponses API simulées."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from socialdock.connectors.base import AmbiguousError, PermanentError, PublishContext, RetriableError
from socialdock.connectors.youtube import YouTubeConnector
from socialdock.models import Account, Post, PostTarget


def context(tmp_path: Path, *, privacy: str = "public", audited: bool = False, publish_at: str | None = None) -> PublishContext:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"0" * 1024)
    account = Account(id="acc", platform="youtube", display_name="Chaîne", mode="real", extra={"audit_passed": audited})
    post = Post(id="post", title="Mon titre", description="Ma description", hashtags=["shorts", "ia"], language="fr")
    target = PostTarget(id="t1", post_id=post.id, account_id=account.id, idempotency_key="idem-1", payload={"privacy": privacy, "publish_at": publish_at})
    return PublishContext(target=target, post=post, account=account, credential={"access_token": "ya29.test"}, media_path=media)


def build(handler) -> YouTubeConnector:
    transport = httpx.MockTransport(handler)
    return YouTubeConnector(client_id="id", client_secret="secret", client=httpx.Client(transport=transport))


def test_capacites_sans_audit_interdisent_le_public():
    connector = build(lambda request: httpx.Response(200, json={}))
    capabilities = connector.get_capabilities(Account(platform="youtube", display_name="x", extra={}))
    assert capabilities.publish_public is False
    assert any("non audité" in line for line in capabilities.restrictions)


def test_capacites_apres_audit_autorisent_le_public():
    connector = build(lambda request: httpx.Response(200, json={}))
    capabilities = connector.get_capabilities(Account(platform="youtube", display_name="x", extra={"audit_passed": True}))
    assert capabilities.publish_public is True


def test_upload_resumable_avec_reprise_308(tmp_path: Path):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/upload/youtube/v3/videos":
            return httpx.Response(200, headers={"Location": "https://upload.session/abc"})
        if request.url.host == "upload.session":
            if len([r for r in seen if r.url.host == "upload.session"]) == 1:
                return httpx.Response(308, headers={"Range": "bytes=0-511"})
            return httpx.Response(200, json={"id": "VIDEO123", "status": {"uploadStatus": "processed", "privacyStatus": "private"}})
        if request.url.path == "/youtube/v3/videos":
            return httpx.Response(200, json={"items": [{"id": "VIDEO123", "status": {"privacyStatus": "private", "uploadStatus": "processed"}}]})
        if request.url.path == "/upload/youtube/v3/thumbnails/set":
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"error": {"message": "inattendu"}})

    connector = build(handler)
    result = connector.publish(context(tmp_path, privacy="public"))
    assert result.outcome == "success"
    assert result.remote_id == "VIDEO123"
    assert result.remote_url == "https://www.youtube.com/watch?v=VIDEO123"
    # Projet non audité : la vidéo reste privée et l'utilisateur est prévenu
    assert result.status == "published_private"
    assert result.requires_user_action is True


def test_metadata_force_privacy_private_sans_audit(tmp_path: Path):
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/upload/youtube/v3/videos":
            captured["metadata"] = json.loads(request.content)
            return httpx.Response(200, headers={"Location": "https://upload.session/abc"})
        if request.url.host == "upload.session":
            return httpx.Response(200, json={"id": "V1", "status": {"privacyStatus": "private"}})
        return httpx.Response(200, json={"items": [{"status": {"privacyStatus": "private"}}]})

    connector = build(handler)
    connector.publish(context(tmp_path, privacy="public", audited=False))
    metadata = captured["metadata"]
    assert metadata["status"]["privacyStatus"] == "private"
    assert metadata["snippet"]["title"] == "Mon titre"
    assert metadata["snippet"]["tags"] == ["shorts", "ia"]


def test_public_autorise_apres_audit(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/upload/youtube/v3/videos":
            return httpx.Response(200, headers={"Location": "https://upload.session/abc"})
        if request.url.host == "upload.session":
            return httpx.Response(200, json={"id": "V2", "status": {"privacyStatus": "public"}})
        return httpx.Response(200, json={"items": [{"status": {"privacyStatus": "public"}}]})

    connector = build(handler)
    result = connector.publish(context(tmp_path, privacy="public", audited=True))
    assert result.status == "published"
    assert result.requires_user_action is False


def test_programmation_native_avec_publishat(tmp_path: Path):
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/upload/youtube/v3/videos":
            captured["metadata"] = json.loads(request.content)
            return httpx.Response(200, headers={"Location": "https://upload.session/abc"})
        if request.url.host == "upload.session":
            return httpx.Response(200, json={"id": "V3", "status": {"privacyStatus": "private"}})
        return httpx.Response(200, json={"items": [{"status": {"privacyStatus": "private"}}]})

    connector = build(handler)
    connector.publish(context(tmp_path, privacy="private", audited=True, publish_at="2026-05-01T10:00:00+00:00"))
    assert captured["metadata"]["status"]["publishAt"] == "2026-05-01T10:00:00+00:00"


def test_video_refusee_par_youtube(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/upload/youtube/v3/videos":
            return httpx.Response(200, headers={"Location": "https://upload.session/abc"})
        if request.url.host == "upload.session":
            return httpx.Response(200, json={"id": "V4"})
        return httpx.Response(200, json={"items": [{"status": {"privacyStatus": "private", "rejectionReason": "termsOfUse"}}]})

    connector = build(handler)
    result = connector.publish(context(tmp_path))
    assert result.outcome == "failure"
    assert result.status == "failed"
    assert "termsOfUse" in result.error_message


def test_quota_depasse_est_reessayable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"code": 403, "message": "quota dépassé", "errors": [{"reason": "quotaExceeded"}]}})

    connector = build(handler)
    with pytest.raises(RetriableError) as info:
        connector.list_channels({"access_token": "ya29.x"})
    assert info.value.code == "quotaExceeded"


def test_erreur_authentification_est_definitive():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"code": 401, "message": "jeton invalide", "errors": [{"reason": "authError"}]}})

    connector = build(handler)
    with pytest.raises(PermanentError):
        connector.list_channels({"access_token": "ya29.x"})


def test_session_sans_location_produit_un_statut_ambigu(tmp_path: Path):
    connector = build(lambda request: httpx.Response(200, json={}))
    result = connector.publish(context(tmp_path))
    assert result.outcome == "uncertain"
    assert result.requires_user_action is True


def test_echange_de_code_oauth_et_renouvellement():
    def handler(request: httpx.Request) -> httpx.Response:
        body = dict(httpx.QueryParams(request.content.decode()))
        if body.get("grant_type") == "authorization_code":
            return httpx.Response(200, json={"access_token": "ya29.new", "refresh_token": "1//refresh", "expires_in": 3600, "scope": "a b"})
        return httpx.Response(200, json={"access_token": "ya29.renewed", "expires_in": 3600})

    connector = build(handler)
    credential = connector.handle_auth_callback(code="code", state="s", redirect_uri="http://127.0.0.1:8000/api/oauth/youtube/callback")
    assert credential["access_token"] == "ya29.new"
    renewed = connector.refresh_auth(credential)
    assert renewed["access_token"] == "ya29.renewed"
    assert renewed["refresh_token"] == "1//refresh", "le refresh_token doit être conservé"


def test_liste_des_chaines_et_statistiques(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/youtube/v3/channels":
            return httpx.Response(200, json={"items": [{"id": "UC1", "snippet": {"title": "Ma chaîne"}, "statistics": {"subscriberCount": "1200"}}]})
        return httpx.Response(200, json={"items": [{"statistics": {"viewCount": "4200", "likeCount": "300", "commentCount": "21"}}]})

    connector = build(handler)
    channels = connector.list_channels({"access_token": "ya29.x"})
    assert channels[0]["title"] == "Ma chaîne"
    ctx = context(tmp_path)
    ctx.target.remote_id = "VIDEO123"
    analytics = connector.get_analytics(ctx)
    assert analytics["metrics"] == {"views": 4200, "likes": 300, "comments": 21}


def test_aucune_chaine_associee_message_explicite():
    connector = build(lambda request: httpx.Response(200, json={"items": []}))
    with pytest.raises(PermanentError, match="youtubeSignupRequired|chaîne"):
        connector.get_account_info({"access_token": "ya29.x"})
