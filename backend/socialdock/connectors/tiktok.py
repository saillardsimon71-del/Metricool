"""Connecteur TikTok — Content Posting API (officielle).

Contraintes majeures (documentation TikTok for Developers, consultée le 2026-10-12) :

* Deux modes : **Direct Post** (scope ``video.publish``) et **Upload vers la
  boîte de réception** (scope ``video.upload``, le créateur termine la publication
  dans l'application TikTok).
* **Application non auditée** : la publication est limitée à ``SELF_ONLY`` et à
  5 utilisateurs par 24 h (erreur ``unaudited_client_can_only_post_to_private_accounts``).
* ``creator_info`` doit être interrogé avant publication : il fournit
  ``privacy_level_options``, ``max_video_post_duration_sec``, l'identifiant et
  l'avatar du créateur.
* Transfert : ``FILE_UPLOAD`` par morceaux (5–64 Mo, dernier ≤ 128 Mo, ≤ 1000
  morceaux) ou ``PULL_FROM_URL`` (domaine vérifié dans le portail développeur).
* 6 requêtes/minute maximum sur l'endpoint d'initialisation.

Aucun endpoint privé, cookie de session ou technique de contournement n'est
utilisé : si la publication publique n'est pas autorisée, SocialDock bascule sur
le mode assisté.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ..models import Account
from ..security import pkce_pair
from .base import (
    AuthStart,
    Capabilities,
    PermanentError,
    PublishContext,
    PublishResult,
    RetriableError,
    SocialConnector,
    StatusResult,
)
from .oauth2 import bearer_headers, build_authorization_url

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
DIRECT_POST_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
INBOX_POST_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
VIDEO_QUERY_URL = "https://open.tiktokapis.com/v2/video/query/"

SCOPES = ["user.info.basic", "user.info.profile", "video.publish", "video.upload"]
MIN_CHUNK = 5 * 1024 * 1024
MAX_CHUNK = 64 * 1024 * 1024
MAX_CHUNKS = 1000
POLL_INTERVAL_SECONDS = 10
POLL_MAX_ATTEMPTS = 90  # 15 minutes


class TikTokConnector(SocialConnector):
    platform = "tiktok"
    label = "TikTok"

    def __init__(
        self,
        *,
        client_key: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str = "http://127.0.0.1:8000/api/oauth/tiktok/callback",
        client: httpx.Client | None = None,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(client, timeout=timeout)
        self.client_key = client_key
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    # -- capacités ---------------------------------------------------------
    def get_capabilities(self, account: Account | None = None) -> Capabilities:
        audited = bool(account and (account.extra or {}).get("audit_passed"))
        restrictions = []
        if not audited:
            restrictions.append(
                "Application non auditée : publication limitée à SELF_ONLY "
                "(privée) et 5 utilisateurs par 24 h."
            )
        restrictions.append("Le niveau de confidentialité doit appartenir à privacy_level_options du créateur.")
        restrictions.append("6 requêtes/minute maximum sur l'initialisation de publication.")
        restrictions.append("La durée maximale dépend de max_video_post_duration_sec (3 min pour la plupart des créateurs).")
        missing: list[str] = []
        if not self.client_key or not self.client_secret:
            missing = ["SOCIALDOCK_TIKTOK_CLIENT_KEY", "SOCIALDOCK_TIKTOK_CLIENT_SECRET"]
        return Capabilities(
            platform=self.platform,
            label=self.label,
            auth_available=bool(self.client_key and self.client_secret),
            publish_video=True,
            publish_public=audited,
            scheduling=False,  # pas de programmation native : SocialDock déclenche, ou mode assisté
            upload=True,
            analytics=False,  # Content Posting API ne fournit pas de métriques détaillées
            requires_review=not audited,
            restrictions=restrictions,
            permissions_required=SCOPES,
            permissions_missing=missing,
        )

    # -- OAuth (Login Kit + PKCE) ------------------------------------------
    def begin_auth(self, *, state: str, redirect_uri: str, account: Account | None = None) -> AuthStart:
        if not self.client_key:
            raise PermanentError("Client key TikTok absent (SOCIALDOCK_TIKTOK_CLIENT_KEY).")
        verifier, challenge = pkce_pair()
        url = build_authorization_url(
            AUTHORIZE_URL,
            client_id=self.client_key,
            redirect_uri=redirect_uri,
            scopes=SCOPES,
            state=state,
            scope_separator=",",
            extra={"code_challenge": challenge, "code_challenge_method": "S256"},
        )
        return AuthStart(
            authorization_url=url,
            state=state,
            scopes=SCOPES,
            redirect_uri=redirect_uri,
            notes=[verifier, "Le redirect_uri doit être déclaré à l'identique dans le portail TikTok."],
        )

    def handle_auth_callback(self, *, code: str, state: str, redirect_uri: str, code_verifier: str | None = None) -> dict[str, Any]:
        if not self.client_key or not self.client_secret:
            raise PermanentError("Identifiants TikTok incomplets.")
        body: dict[str, Any] = {
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            body["code_verifier"] = code_verifier
        response = self.client.post(TOKEN_URL, json=body, headers={"Content-Type": "application/json; charset=UTF-8"})
        self._raise_for_error(response)
        payload = response.json()
        if payload.get("error") not in (None, "", "ok"):
            raise PermanentError(f"Échange du code refusé : {payload.get('error_description') or payload.get('error')}")
        return self._normalize(payload)

    def refresh_auth(self, credential: dict[str, Any]) -> dict[str, Any]:
        refresh = credential.get("refresh_token")
        if not refresh:
            raise PermanentError("Aucun refresh_token TikTok : reconnectez le compte.")
        response = self.client.post(
            TOKEN_URL,
            json={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
            headers={"Content-Type": "application/json; charset=UTF-8"},
        )
        self._raise_for_error(response)
        payload = response.json()
        normalized = self._normalize(payload)
        normalized["refresh_token"] = payload.get("refresh_token") or refresh
        return normalized

    def _normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        expires_in = int(payload.get("expires_in") or 86400)
        refresh_expires = payload.get("refresh_expires_in")
        return {
            "access_token": payload.get("access_token"),
            "refresh_token": payload.get("refresh_token"),
            "scope": payload.get("scope"),
            "open_id": payload.get("open_id"),
            "token_type": payload.get("token_type", "Bearer"),
            "obtained_at": datetime.now(UTC).isoformat(),
            "expires_at": datetime.fromtimestamp(time.time() + expires_in, tz=UTC).isoformat(),
            "refresh_expires_at": (
                datetime.fromtimestamp(time.time() + int(refresh_expires), tz=UTC).isoformat() if refresh_expires else None
            ),
        }

    def get_account_info(self, credential: dict[str, Any]) -> dict[str, Any]:
        info = self.creator_info(credential)
        creator = info.get("creator_info") or {}
        return {
            "id": creator.get("creator_user_id") or credential.get("open_id"),
            "title": creator.get("creator_nickname") or creator.get("creator_username"),
            "username": creator.get("creator_username"),
            "avatar_url": creator.get("creator_avatar_url"),
            "privacy_level_options": info.get("privacy_level_options") or [],
            "max_video_post_duration_sec": info.get("max_video_post_duration_sec"),
            "comment_disabled": info.get("comment_disabled"),
            "duet_disabled": info.get("duet_disabled"),
            "stitch_disabled": info.get("stitch_disabled"),
        }

    def creator_info(self, credential: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(CREATOR_INFO_URL, headers=bearer_headers(credential["access_token"]), json={})
        self._raise_for_error(response)
        payload = response.json()
        self._raise_for_api_error(payload)
        return payload.get("data") or {}

    # -- publication -------------------------------------------------------
    def _resolve_privacy(self, context: PublishContext, options: list[str]) -> tuple[str, bool]:
        """Choisit le niveau de confidentialité autorisé — jamais au-dessus des droits réels."""
        requested = str((context.target.payload or {}).get("privacy") or "SELF_ONLY").upper()
        capabilities = self.get_capabilities(context.account)
        if requested == "PUBLIC_TO_EVERYONE" and not capabilities.publish_public:
            requested = "SELF_ONLY"
        if options and requested not in options:
            fallback = "SELF_ONLY" if "SELF_ONLY" in options else options[0]
            log.warning("Niveau de confidentialité %s indisponible, repli sur %s", requested, fallback)
            return fallback, True
        return requested, False

    def _build_body(self, context: PublishContext, privacy: str, size: int) -> dict[str, Any]:
        payload = context.target.payload or {}
        post = context.post
        caption = (payload.get("caption") or post.description or "").strip()
        hashtags = " ".join(tag if tag.startswith("#") else f"#{tag}" for tag in (post.hashtags or []))
        title = f"{caption} {hashtags}".strip()[:2200]
        post_info: dict[str, Any] = {
            "title": title,
            "privacy_level": privacy,
            "disable_comment": bool(payload.get("disable_comment", False)),
            "disable_duet": bool(payload.get("disable_duet", False)),
            "disable_stitch": bool(payload.get("disable_stitch", False)),
        }
        if payload.get("video_cover_timestamp_ms") is not None:
            post_info["video_cover_timestamp_ms"] = int(payload["video_cover_timestamp_ms"])
        for flag in ("brand_content_toggle", "brand_organic_toggle", "is_aigc"):
            if flag in payload:
                post_info[flag] = bool(payload[flag])
        video_url = payload.get("video_url")
        if video_url:
            source_info: dict[str, Any] = {"source": "PULL_FROM_URL", "video_url": video_url}
        else:
            chunk = self._chunk_plan(size)
            source_info = {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk,
                "total_chunk_count": max(1, (size + chunk - 1) // chunk),
            }
        return {"post_info": post_info, "source_info": source_info}

    @staticmethod
    def _chunk_plan(size: int) -> int:
        """Taille de morceau conforme (5–64 Mo, ≤ 1000 morceaux, fichier < 5 Mo en un bloc).

        Au-delà de 1000 morceaux de 64 Mo (~64 Go), le protocole FILE_UPLOAD ne
        peut plus respecter les règles TikTok : on refuse explicitement plutôt
        que d'envoyer un plan invalide.
        """
        if size <= MIN_CHUNK:
            return size
        if size > MAX_CHUNK * MAX_CHUNKS:
            raise PermanentError(
                f"Fichier de {size / 1_000_000_000:.1f} Go trop volumineux pour FILE_UPLOAD "
                f"(maximum {MAX_CHUNK * MAX_CHUNKS / 1_000_000_000:.0f} Go en {MAX_CHUNKS} morceaux de 64 Mo).",
                code="tiktok_file_too_large",
            )
        return MAX_CHUNK

    def _init_post(self, context: PublishContext, body: dict[str, Any], inbox: bool) -> dict[str, Any]:
        url = INBOX_POST_URL if inbox else DIRECT_POST_URL
        response = self.client.post(url, headers=bearer_headers(context.credential["access_token"]), json=body)
        self._raise_for_error(response)
        payload = response.json()
        self._raise_for_api_error(payload)
        data = payload.get("data") or {}
        if not data.get("publish_id"):
            raise PermanentError("TikTok n'a pas renvoyé de publish_id.")
        return data

    def _upload_chunks(self, context: PublishContext, upload_url: str, path: Path, size: int, chunk_size: int) -> None:
        sent = 0
        with open(path, "rb") as handle:
            while sent < size:
                length = min(chunk_size, size - sent)
                handle.seek(sent)
                payload = handle.read(length)
                headers = {
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(payload)),
                    "Content-Range": f"bytes {sent}-{sent + len(payload) - 1}/{size}",
                }
                response = self.client.put(upload_url, headers=headers, content=payload)
                if response.status_code not in (200, 201, 206):
                    self._raise_for_error(response)
                sent += len(payload)
                context.report(10 + int(70 * sent / max(size, 1)), f"{sent // 1_000_000} Mo envoyés")

    def _poll_status(self, context: PublishContext, publish_id: str) -> dict[str, Any]:
        for attempt in range(POLL_MAX_ATTEMPTS):
            response = self.client.post(
                STATUS_URL,
                headers=bearer_headers(context.credential["access_token"]),
                json={"publish_id": publish_id},
            )
            self._raise_for_error(response)
            payload = response.json()
            self._raise_for_api_error(payload)
            data = payload.get("data") or {}
            status = (data.get("status") or "").upper()
            context.report(80 + min(15, attempt), f"TikTok : {status or 'en attente'}")
            if status == "PUBLISH_COMPLETE":
                return data
            if status == "FAILED":
                raise PermanentError(
                    f"Publication TikTok refusée : {data.get('fail_reason') or 'raison inconnue'}",
                    code=str(data.get("fail_reason") or "tiktok_failed"),
                )
            if status == "DOWNLOAD_COMPLETE" or status == "PROCESSING_UPLOAD":
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            time.sleep(POLL_INTERVAL_SECONDS)
        raise RetriableError("Statut TikTok non résolu après 15 minutes.", code="tiktok_status_timeout")

    def publish(self, context: PublishContext) -> PublishResult:
        inbox_mode = bool((context.target.payload or {}).get("mode") == "inbox")
        try:
            info = self.creator_info(context.credential)
            options = [str(o).upper() for o in (info.get("privacy_level_options") or [])]
            privacy, downgraded = self._resolve_privacy(context, options)
            max_duration = info.get("max_video_post_duration_sec")
            video_url = (context.target.payload or {}).get("video_url")
            size = 0
            if video_url:
                body = self._build_body(context, privacy, 0)
            else:
                if context.media_path is None or not context.media_path.exists():
                    raise PermanentError("Fichier média introuvable pour l'upload TikTok.")
                size = context.media_path.stat().st_size
                body = self._build_body(context, privacy, size)
            context.report(3, "Initialisation de la publication…")
            data = self._init_post(context, body, inbox=inbox_mode)
            publish_id = str(data["publish_id"])
            context.target.pending_operation_id = publish_id
            if not video_url and data.get("upload_url"):
                chunk_size = int(body["source_info"].get("chunk_size") or size)
                self._upload_chunks(context, data["upload_url"], context.media_path, size, chunk_size)
            self._poll_status(context, publish_id)
            remote_url = None
            username = ((info.get("creator_info") or {}).get("creator_username"))
            if username:
                remote_url = f"https://www.tiktok.com/@{username}"
            status = "published"
            if inbox_mode:
                status = "waiting_for_user"
            elif privacy == "SELF_ONLY":
                status = "published_private"
            return PublishResult(
                outcome="success" if status != "waiting_for_user" else "success",
                status=status,
                remote_id=publish_id,
                remote_url=remote_url,
                operation_id=publish_id,
                data={"privacy_level": privacy, "downgraded_privacy": downgraded, "max_video_post_duration_sec": max_duration},
                requires_user_action=status in {"waiting_for_user", "published_private"},
                user_action_hint=(
                    "Vidéo envoyée dans la boîte de réception TikTok : terminez la publication dans l'application."
                    if status == "waiting_for_user"
                    else (
                        "Publié en privé (SELF_ONLY) : application non auditée ou niveau non autorisé. "
                        "Validez le passage en public depuis TikTok."
                        if status == "published_private"
                        else None
                    )
                ),
            )
        except PermanentError as exc:
            return PublishResult(outcome="failure", status="failed", error_code=exc.code, error_message=str(exc), http_status=exc.http_status)
        except RetriableError as exc:
            return PublishResult(outcome="timeout", status="failed", error_code=exc.code, error_message=str(exc), http_status=exc.http_status)
        except httpx.TimeoutException as exc:
            return PublishResult(
                outcome="uncertain",
                status="uncertain",
                error_code="tiktok_timeout",
                error_message=f"Timeout TikTok : {exc}",
                operation_id=context.target.pending_operation_id,
                requires_user_action=True,
                user_action_hint="Vérifiez le profil TikTok : la vidéo a peut-être été publiée.",
            )

    def get_publish_status(self, context: PublishContext) -> StatusResult:
        publish_id = context.target.pending_operation_id or context.target.remote_id
        if not publish_id:
            raise PermanentError("Aucun publish_id TikTok pour cette cible.")
        response = self.client.post(
            STATUS_URL,
            headers=bearer_headers(context.credential["access_token"]),
            json={"publish_id": publish_id},
        )
        self._raise_for_error(response)
        data = (response.json() or {}).get("data") or {}
        status = (data.get("status") or "").upper()
        mapping = {
            "PUBLISH_COMPLETE": "published",
            "PROCESSING_DOWNLOAD": "processing",
            "PROCESSING_UPLOAD": "processing",
            "DOWNLOAD_COMPLETE": "processing",
            "SENDING_TO_USER": "waiting_for_user",
            "FAILED": "failed",
        }
        return StatusResult(
            status=mapping.get(status, "processing"),
            remote_id=publish_id,
            detail=f"{status} {data.get('fail_reason') or ''}".strip(),
        )

    def get_analytics(self, context: PublishContext) -> dict[str, Any]:
        """La Content Posting API n'expose pas de métriques détaillées."""
        return {"metrics": {}, "error": "La Content Posting API TikTok ne fournit pas de statistiques de publication."}

    # -- erreurs -----------------------------------------------------------
    def _raise_for_error(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        code = None
        message = response.text[:400]
        try:
            error = response.json().get("error", {})
            code = error.get("code")
            message = error.get("message") or message
        except ValueError:
            pass
        detail = f"{message} (code {code})"
        if response.status_code == 429 or code in {"rate_limit_exceeded", "internal"}:
            raise RetriableError(detail, code=str(code), http_status=response.status_code)
        raise PermanentError(detail, code=str(code), http_status=response.status_code)

    @staticmethod
    def _raise_for_api_error(payload: dict[str, Any]) -> None:
        error = (payload or {}).get("error") or {}
        code = error.get("code")
        if code in (None, "", "ok"):
            return
        message = f"{error.get('message') or 'Erreur TikTok'} (code {code})"
        if code == "rate_limit_exceeded":
            raise RetriableError(message, code=str(code), http_status=429)
        raise PermanentError(message, code=str(code))
