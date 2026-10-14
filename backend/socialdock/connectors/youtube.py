"""Connecteur YouTube Data API v3.

Points de conformité majeurs (documentation officielle, consultée le 2026-10-12) :

* **Projets non audités** : « All videos uploaded via the videos.insert endpoint
  from unverified API projects created after 28 July 2020 will be restricted to
  private viewing mode. » — tant que l'utilisateur n'a pas déclaré avoir passé
  l'audit, ``publish_public`` reste ``False`` et toute publication est marquée
  ``published_private`` après vérification du statut distant.
* **Programmation native** : ``status.publishAt`` n'est accepté que si
  ``status.privacyStatus = private`` et que la vidéo n'a jamais été publiée.
* **Upload résumable** : ``uploadType=resumable``, morceaux multiples de 256 Kio.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from ..models import Account
from .base import (
    AmbiguousError,
    AuthStart,
    Capabilities,
    ConnectorError,
    PermanentError,
    PublishContext,
    PublishResult,
    RetriableError,
    SocialConnector,
    StatusResult,
)
from .oauth2 import bearer_headers, build_authorization_url, exchange_code, refresh_token, revoke

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

CHUNK_SIZE = 8 * 1024 * 1024  # multiple de 256 Kio, conforme au protocole résumable
CHUNK_ALIGNMENT = 256 * 1024

UNAUDITED_NOTICE = (
    "Projet API non audité : Google verrouille les uploads en privé "
    "(règle du 28/07/2020). Déclarez l'audit réussi dans les paramètres du compte "
    "pour activer la publication publique."
)


class YouTubeConnector(SocialConnector):
    platform = "youtube"
    label = "YouTube"

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str = "http://127.0.0.1:8000/api/oauth/youtube/callback",
        client: httpx.Client | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(client, timeout=timeout)
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    # -- capacités ---------------------------------------------------------
    def get_capabilities(self, account: Account | None = None) -> Capabilities:
        audited = bool(account and (account.extra or {}).get("audit_passed"))
        restrictions = [] if audited else [UNAUDITED_NOTICE]
        restrictions.append("100 appels videos.insert par projet et par jour (quota par défaut).")
        restrictions.append("Programmation native disponible uniquement avec privacyStatus=private.")
        missing: list[str] = []
        if not self.client_id or not self.client_secret:
            missing = ["SOCIALDOCK_GOOGLE_CLIENT_ID", "SOCIALDOCK_GOOGLE_CLIENT_SECRET"]
        return Capabilities(
            platform=self.platform,
            label=self.label,
            auth_available=bool(self.client_id and self.client_secret),
            publish_video=True,
            publish_public=audited,
            scheduling=True,
            upload=True,
            analytics=True,
            requires_review=not audited,
            restrictions=restrictions,
            permissions_required=SCOPES,
            permissions_missing=missing,
        )

    # -- OAuth -------------------------------------------------------------
    def begin_auth(self, *, state: str, redirect_uri: str, account: Account | None = None) -> AuthStart:
        if not self.client_id:
            raise PermanentError("Identifiant client Google absent (SOCIALDOCK_GOOGLE_CLIENT_ID).")
        from ..security import pkce_pair

        verifier, challenge = pkce_pair()
        url = build_authorization_url(
            AUTHORIZE_URL,
            client_id=self.client_id,
            redirect_uri=redirect_uri,
            scopes=SCOPES,
            state=state,
            extra={
                "access_type": "offline",
                "prompt": "consent",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "include_granted_scopes": "true",
            },
        )
        return AuthStart(authorization_url=url, state=state, scopes=SCOPES, redirect_uri=redirect_uri, notes=[verifier])

    def handle_auth_callback(self, *, code: str, state: str, redirect_uri: str, code_verifier: str | None = None) -> dict[str, Any]:
        if not self.client_id or not self.client_secret:
            raise PermanentError("Identifiants Google incomplets.")
        data = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        payload = exchange_code(self.client, TOKEN_URL, data=data)
        return self._normalize_token(payload)

    def refresh_auth(self, credential: dict[str, Any]) -> dict[str, Any]:
        refresh = credential.get("refresh_token")
        if not refresh:
            raise PermanentError("Aucun refresh_token YouTube : reconnectez le compte.")
        payload = refresh_token(
            self.client,
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
        merged = self._normalize_token(payload)
        merged["refresh_token"] = refresh  # Google ne renvoie pas le refresh_token au refresh
        merged.setdefault("scope", credential.get("scope"))
        return merged

    def revoke_auth(self, credential: dict[str, Any]) -> None:
        token = credential.get("access_token")
        if token:
            revoke(self.client, REVOKE_URL, data={"token": token})

    def _normalize_token(self, payload: dict[str, Any]) -> dict[str, Any]:
        expires_in = int(payload.get("expires_in") or 3600)
        return {
            "access_token": payload.get("access_token"),
            "refresh_token": payload.get("refresh_token"),
            "scope": payload.get("scope"),
            "token_type": payload.get("token_type", "Bearer"),
            "obtained_at": datetime.now(UTC).isoformat(),
            "expires_at": datetime.fromtimestamp(time.time() + expires_in, tz=UTC).isoformat(),
        }

    # -- comptes -----------------------------------------------------------
    def list_channels(self, credential: dict[str, Any]) -> list[dict[str, Any]]:
        response = self.client.get(
            CHANNELS_URL,
            params={"part": "snippet,statistics,contentDetails", "mine": "true", "maxResults": 50},
            headers=bearer_headers(credential["access_token"]),
        )
        self._raise_for_error(response)
        channels: list[dict[str, Any]] = []
        for item in response.json().get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            channels.append(
                {
                    "id": item.get("id"),
                    "title": snippet.get("title"),
                    "description": snippet.get("description"),
                    "avatar_url": (snippet.get("thumbnails", {}).get("default") or {}).get("url"),
                    "subscriber_count": stats.get("subscriberCount"),
                    "video_count": stats.get("videoCount"),
                    "view_count": stats.get("viewCount"),
                }
            )
        return channels

    def get_account_info(self, credential: dict[str, Any]) -> dict[str, Any]:
        channels = self.list_channels(credential)
        if not channels:
            raise PermanentError(
                "Aucune chaîne YouTube associée à ce compte Google "
                "(erreur YouTube : youtubeSignupRequired). Créez une chaîne puis réautorisez.",
                code="youtubeSignupRequired",
            )
        return channels[0]

    # -- upload ------------------------------------------------------------
    def _start_resumable(self, credential: dict[str, Any], metadata: dict[str, Any]) -> str:
        response = self.client.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status,contentDetails", "notifySubscribers": "false"},
            headers={**bearer_headers(credential["access_token"]), "Content-Type": "application/json; charset=UTF-8"},
            content=json.dumps(metadata),
        )
        self._raise_for_error(response)
        location = response.headers.get("Location") or response.headers.get("location")
        if not location:
            raise AmbiguousError("Session d'upload résumable sans en-tête Location.", http_status=response.status_code)
        return location

    def _send_chunks(self, session_uri: str, credential: dict[str, Any], path, size: int, progress) -> httpx.Response:
        """Envoie le fichier par morceaux de 8 Mio (alignés sur 256 Kio)."""
        chunk = (CHUNK_SIZE // CHUNK_ALIGNMENT) * CHUNK_ALIGNMENT
        sent = 0
        last: httpx.Response | None = None
        with open(path, "rb") as handle:
            while sent < size:
                length = min(chunk, size - sent)
                handle.seek(sent)
                payload = handle.read(length)
                headers = {
                    **bearer_headers(credential["access_token"]),
                    "Content-Length": str(len(payload)),
                    "Content-Range": f"bytes {sent}-{sent + len(payload) - 1}/{size}",
                    "Content-Type": "video/mp4",
                }
                response = self.client.put(session_uri, headers=headers, content=payload)
                if response.status_code in (200, 201):
                    if progress:
                        progress(100, "Upload terminé")
                    return response
                if response.status_code == 308:  # reprise : le serveur indique l'octet attendu
                    range_header = response.headers.get("Range", "")
                    if range_header.startswith("bytes="):
                        try:
                            sent = int(range_header.split("-")[1]) + 1
                        except (IndexError, ValueError):
                            sent += len(payload)
                    else:
                        sent += len(payload)
                    last = response
                    if progress:
                        progress(int(sent * 100 / max(size, 1)), f"{sent // 1_000_000} Mo envoyés")
                    continue
                self._raise_for_error(response)
        if last is None:
            raise AmbiguousError("Upload terminé sans réponse de confirmation.")
        return last

    # -- publication -------------------------------------------------------
    def _build_metadata(self, context: PublishContext) -> dict[str, Any]:
        payload = context.target.payload or {}
        post = context.post
        privacy = str(payload.get("privacy") or "private").lower()
        capabilities = self.get_capabilities(context.account)
        if privacy == "public" and not capabilities.publish_public:
            # Règle J : on ne promet jamais une publication publique impossible.
            privacy = "private"
        snippet: dict[str, Any] = {
            "title": (payload.get("title") or post.title)[:100],
            "description": payload.get("description") or post.description or "",
            "defaultLanguage": payload.get("language") or post.language or "fr",
        }
        tags = payload.get("tags")
        if not tags:
            tags = [tag.lstrip("#") for tag in (post.hashtags or [])]
        if tags:
            snippet["tags"] = [str(t)[:40] for t in tags][:30]
        if payload.get("category_id"):
            snippet["categoryId"] = str(payload["category_id"])
        status: dict[str, Any] = {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": bool(payload.get("made_for_kids", False)),
            "embeddable": bool(payload.get("embeddable", True)),
            "publicStatsViewable": bool(payload.get("public_stats_viewable", True)),
        }
        if "contains_synthetic_media" in payload:
            status["containsSyntheticMedia"] = bool(payload["contains_synthetic_media"])
        scheduled_for = payload.get("publish_at")
        if scheduled_for and privacy == "private":
            status["publishAt"] = _iso8601(scheduled_for)
        content_details: dict[str, Any] = {}
        if payload.get("caption_language"):
            content_details["defaultAudioLanguage"] = payload["caption_language"]
        return {"snippet": snippet, "status": status, "contentDetails": content_details or {}}

    def upload_media(self, context: PublishContext) -> dict[str, Any]:
        if context.media_path is None or not context.media_path.exists():
            raise PermanentError("Fichier média introuvable pour l'upload YouTube.")
        metadata = self._build_metadata(context)
        context.report(2, "Ouverture de la session d'upload…")
        session_uri = self._start_resumable(context.credential, metadata)
        size = context.media_path.stat().st_size
        context.report(5, f"Envoi de {size // 1_000_000} Mo…")
        response = self._send_chunks(session_uri, context.credential, context.media_path, size, context.progress)
        try:
            resource = response.json()
        except ValueError as exc:
            raise AmbiguousError(f"Réponse d'upload illisible : {exc}") from exc
        video_id = resource.get("id")
        if not video_id:
            raise AmbiguousError("Upload accepté mais aucun identifiant de vidéo renvoyé.")
        return {"video_id": video_id, "resource": resource}

    def set_thumbnail(self, credential: dict[str, Any], video_id: str, image_path) -> bool:
        try:
            with open(image_path, "rb") as handle:
                image = handle.read()
        except OSError as exc:
            raise PermanentError(f"Miniature illisible : {exc}") from exc
        response = self.client.post(
            THUMBNAIL_URL,
            params={"videoId": video_id, "uploadType": "media"},
            headers={**bearer_headers(credential["access_token"]), "Content-Type": "image/jpeg"},
            content=image,
        )
        return response.status_code < 400

    def publish(self, context: PublishContext) -> PublishResult:
        try:
            uploaded = self.upload_media(context)
        except AmbiguousError as exc:
            return PublishResult(
                outcome="uncertain",
                status="uncertain",
                error_code=exc.code or "youtube_ambiguous",
                error_message=str(exc),
                http_status=exc.http_status,
                requires_user_action=True,
                user_action_hint=(
                    "YouTube a peut-être reçu la vidéo. Vérifiez YouTube Studio avant toute "
                    "nouvelle tentative : ne relancez pas la publication sans vérification."
                ),
            )
        except PermanentError as exc:
            return PublishResult(
                outcome="failure",
                status="failed",
                error_code=exc.code,
                error_message=str(exc),
                http_status=exc.http_status,
            )
        except RetriableError as exc:
            return PublishResult(outcome="timeout", status="failed", error_code=exc.code, error_message=str(exc), http_status=exc.http_status)
        except httpx.TimeoutException as exc:
            return PublishResult(
                outcome="uncertain",
                status="uncertain",
                error_code="youtube_timeout",
                error_message=f"Timeout pendant l'envoi : {exc}",
                requires_user_action=True,
                user_action_hint="Vérifiez YouTube Studio : la vidéo a peut-être été reçue.",
            )

        video_id = uploaded["video_id"]
        remote_url = f"https://www.youtube.com/watch?v={video_id}"
        if context.thumbnail_path is not None and context.thumbnail_path.exists():
            context.report(90, "Envoi de la miniature…")
            self.set_thumbnail(context.credential, video_id, context.thumbnail_path)

        context.report(95, "Vérification du statut distant…")
        remote = self._fetch_video(context.credential, video_id)
        privacy = ((remote.get("status") or {}).get("privacyStatus") or "").lower()
        upload_status = ((remote.get("status") or {}).get("uploadStatus") or "").lower()
        rejection = (remote.get("status") or {}).get("rejectionReason")
        if rejection:
            return PublishResult(
                outcome="failure",
                status="failed",
                remote_id=video_id,
                remote_url=remote_url,
                error_code="youtube_rejected",
                error_message=f"Vidéo refusée par YouTube : {rejection}",
            )
        if privacy == "public":
            status = "published"
        elif privacy in {"unlisted", "private"}:
            status = "published_private"
        else:
            status = "published_private"
        return PublishResult(
            outcome="success",
            status=status,
            remote_id=video_id,
            remote_url=remote_url,
            data={
                "privacy": privacy,
                "upload_status": upload_status,
                "locked_private": upload_status == "rejected" or privacy == "private",
            },
            requires_user_action=status == "published_private" and (context.target.payload or {}).get("privacy") == "public",
            user_action_hint=(
                "La vidéo est privée : projet API non audité. Passez l'audit YouTube "
                "ou publiez manuellement depuis YouTube Studio."
            )
            if status == "published_private" and (context.target.payload or {}).get("privacy") == "public"
            else None,
        )

    def _fetch_video(self, credential: dict[str, Any], video_id: str) -> dict[str, Any]:
        response = self.client.get(
            VIDEOS_URL,
            params={"part": "snippet,status,statistics", "id": video_id},
            headers=bearer_headers(credential["access_token"]),
        )
        self._raise_for_error(response)
        items = response.json().get("items") or []
        return items[0] if items else {}

    def get_publish_status(self, context: PublishContext) -> StatusResult:
        if not context.target.remote_id:
            raise PermanentError("Aucun identifiant distant YouTube pour cette cible.")
        video = self._fetch_video(context.credential, context.target.remote_id)
        status = (video.get("status") or {})
        privacy = (status.get("privacyStatus") or "").lower()
        if privacy == "public":
            state = "published"
        elif privacy in {"private", "unlisted"}:
            state = "published_private"
        else:
            state = "processing"
        return StatusResult(
            status=state,
            remote_url=f"https://www.youtube.com/watch?v={context.target.remote_id}",
            remote_id=context.target.remote_id,
            detail=f"uploadStatus={status.get('uploadStatus')} privacy={privacy}",
        )

    def get_analytics(self, context: PublishContext) -> dict[str, Any]:
        if not context.target.remote_id:
            return {}
        video = self._fetch_video(context.credential, context.target.remote_id)
        stats = video.get("statistics") or {}
        mapping = {
            "viewCount": "views",
            "likeCount": "likes",
            "commentCount": "comments",
        }
        metrics: dict[str, Any] = {}
        for source, target in mapping.items():
            if stats.get(source) is not None:
                try:
                    metrics[target] = int(stats[source])
                except (TypeError, ValueError):
                    continue
        return {"metrics": metrics, "source": "youtube.videos.statistics", "fetched_at": datetime.now(UTC).isoformat()}

    # -- erreurs -----------------------------------------------------------
    def _raise_for_error(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        code = None
        message = response.text[:400]
        try:
            errors = response.json().get("error", {})
            code = errors.get("errors", [{}])[0].get("reason") or errors.get("code")
            message = errors.get("message") or message
        except ValueError:
            pass
        if response.status_code in {429, 500, 502, 503, 504} or code in {"quotaExceeded", "rateLimitExceeded", "backendError"}:
            raise RetriableError(message, code=str(code), http_status=response.status_code)
        if code in {"authError", "invalidCredentials", "invalid_token"} or response.status_code in {401, 403}:
            raise PermanentError(message, code=str(code), http_status=response.status_code)
        raise ConnectorError(message, code=str(code), http_status=response.status_code)


def _iso8601(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()
