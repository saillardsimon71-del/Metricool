"""Connecteur Instagram (API Instagram Platform).

Parcours retenu : **Instagram API avec Instagram Login** (``graph.instagram.com``)
— il n'exige pas de Page Facebook liée, ce qui correspond à une application
personnelle locale. Permissions : ``instagram_business_basic`` et
``instagram_business_content_publish`` (compte Professionnel requis).

Publication officielle en trois temps :
1. ``POST /{ig-user-id}/media`` → conteneur (``media_type=REELS``) ;
2. ``GET /{container}?fields=status_code`` jusqu'à ``FINISHED`` ;
3. ``POST /{ig-user-id}/media_publish`` avec ``creation_id``.

Le transfert du fichier utilise le protocole résumable officiel
``rupload.facebook.com/ig-api-upload`` : la vidéo n'a donc pas besoin d'être
hébergée publiquement. L'option ``video_url`` (hébergement temporaire) reste
disponible et désactivée par défaut.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from ..models import Account
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
from .oauth2 import bearer_headers, build_authorization_url, exchange_code

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://graph.instagram.com/access_token"
REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
ME_URL = "https://graph.instagram.com/me"
RUPLOAD_URL = "https://rupload.facebook.com/ig-api-upload"

SCOPES = ["instagram_business_basic", "instagram_business_content_publish"]
DEFAULT_API_VERSION = "v23.0"
POLL_INTERVAL_SECONDS = 10
POLL_MAX_ATTEMPTS = 60  # 10 minutes au maximum


class InstagramConnector(SocialConnector):
    platform = "instagram"
    label = "Instagram"

    def __init__(
        self,
        *,
        app_id: str | None = None,
        app_secret: str | None = None,
        redirect_uri: str = "http://127.0.0.1:8000/api/oauth/instagram/callback",
        api_version: str = DEFAULT_API_VERSION,
        client: httpx.Client | None = None,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(client, timeout=timeout)
        self.app_id = app_id
        self.app_secret = app_secret
        self.redirect_uri = redirect_uri
        self.api_version = api_version

    @property
    def graph(self) -> str:
        return f"https://graph.instagram.com/{self.api_version}"

    # -- capacités ---------------------------------------------------------
    def get_capabilities(self, account: Account | None = None) -> Capabilities:
        missing: list[str] = []
        if not self.app_id or not self.app_secret:
            missing = ["SOCIALDOCK_META_APP_ID", "SOCIALDOCK_META_APP_SECRET"]
        return Capabilities(
            platform=self.platform,
            label=self.label,
            auth_available=bool(self.app_id and self.app_secret),
            publish_video=True,
            publish_public=True,  # une publication API est publique par nature
            scheduling=False,     # aucune programmation native : c'est SocialDock qui déclenche
            upload=True,
            analytics=True,
            requires_review=False,  # Standard Access suffit pour ses propres comptes
            restrictions=[
                "Compte Professionnel (Business ou Creator) obligatoire.",
                "Accès Standard : seuls les rôles de l'application Meta peuvent publier (usage personnel).",
                "Quota de publication : 100 publications API par 24 h glissantes (content_publishing_limit).",
                "Reels : 3 s à 15 min, 300 Mo max, MP4/MOV, H.264/HEVC + AAC, 23–60 fps, 9:16 recommandé.",
                "Un conteneur non publié expire au bout de 24 h.",
            ],
            permissions_required=SCOPES,
            permissions_missing=missing,
        )

    # -- OAuth -------------------------------------------------------------
    def begin_auth(self, *, state: str, redirect_uri: str, account: Account | None = None) -> AuthStart:
        if not self.app_id:
            raise PermanentError("Identifiant d'application Meta absent (SOCIALDOCK_META_APP_ID).")
        url = build_authorization_url(
            AUTHORIZE_URL,
            client_id=self.app_id,
            redirect_uri=redirect_uri,
            scopes=SCOPES,
            state=state,
            scope_separator=",",
        )
        return AuthStart(
            authorization_url=url,
            state=state,
            scopes=SCOPES,
            redirect_uri=redirect_uri,
            notes=[
                "Meta n'accepte pas PKCE : la validation repose sur le paramètre state.",
                "Le redirect_uri doit être déclaré à l'identique dans le tableau de bord Meta.",
            ],
        )

    def handle_auth_callback(self, *, code: str, state: str, redirect_uri: str, code_verifier: str | None = None) -> dict[str, Any]:
        if not self.app_id or not self.app_secret:
            raise PermanentError("Identifiants Meta incomplets.")
        short = exchange_code(
            self.client,
            TOKEN_URL,
            data={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        short_token = short.get("access_token")
        if not short_token:
            raise PermanentError("Réponse Meta sans access_token.")
        long_lived = exchange_code(
            self.client,
            TOKEN_URL,
            data={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "grant_type": "ig_exchange_token",
                "access_token": short_token,
            },
        )
        return self._normalize(long_lived)

    def refresh_auth(self, credential: dict[str, Any]) -> dict[str, Any]:
        token = credential.get("access_token")
        if not token:
            raise PermanentError("Aucun access_token Instagram : reconnectez le compte.")
        response = self.client.get(REFRESH_URL, params={"grant_type": "ig_refresh_token", "access_token": token})
        self._raise_for_error(response)
        return self._normalize(response.json())

    def _normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        expires_in = int(payload.get("expires_in") or 60 * 24 * 3600)
        return {
            "access_token": payload.get("access_token"),
            "token_type": payload.get("token_type", "Bearer"),
            "user_id": str(payload.get("user_id") or ""),
            "expires_in": expires_in,
            "obtained_at": datetime.now(UTC).isoformat(),
            "expires_at": datetime.fromtimestamp(time.time() + expires_in, tz=UTC).isoformat(),
        }

    def get_account_info(self, credential: dict[str, Any]) -> dict[str, Any]:
        response = self.client.get(
            ME_URL,
            params={"fields": "user_id,username,account_type,media_count,name", "access_token": credential["access_token"]},
        )
        self._raise_for_error(response)
        data = response.json()
        account_type = data.get("account_type")
        if account_type and account_type.upper() == "PERSONAL":
            raise PermanentError(
                "Compte Instagram personnel détecté : l'API exige un compte Professionnel "
                "(Business ou Creator). Convertissez le compte puis reconnectez-le.",
                code="instagram_personal_account",
            )
        return {
            "id": str(data.get("user_id") or data.get("id") or ""),
            "title": data.get("name") or data.get("username"),
            "username": data.get("username"),
            "account_type": account_type,
            "media_count": data.get("media_count"),
        }

    # -- quota -------------------------------------------------------------
    def get_publishing_quota(self, credential: dict[str, Any], ig_user_id: str) -> dict[str, Any]:
        response = self.client.get(
            f"{self.graph}/{ig_user_id}/content_publishing_limit",
            params={"fields": "config,quota_usage", "access_token": credential["access_token"]},
        )
        self._raise_for_error(response)
        entries = (response.json() or {}).get("data") or []
        if not entries:
            return {}
        config = entries[0].get("config") or {}
        usage = entries[0].get("quota_usage")
        return {"quota_total": config.get("quota_total"), "quota_usage": usage, "quota_duration": config.get("quota_duration")}

    # -- publication -------------------------------------------------------
    def _ig_user_id(self, context: PublishContext) -> str:
        ig_id = context.credential.get("user_id") or context.account.external_id
        if not ig_id:
            raise PermanentError("Identifiant utilisateur Instagram inconnu : reconnectez le compte.")
        return str(ig_id)

    def _create_container(self, context: PublishContext, ig_user_id: str) -> str:
        payload = context.target.payload or {}
        post = context.post
        caption = (payload.get("caption") or post.description or "").strip()
        hashtags = " ".join(tag if tag.startswith("#") else f"#{tag}" for tag in (post.hashtags or []))
        full_caption = f"{caption}\n\n{hashtags}".strip() if hashtags else caption
        body: dict[str, Any] = {
            "media_type": "REELS",
            "caption": full_caption[:2200],
            "share_to_feed": str(bool(payload.get("share_to_feed", True))).lower(),
        }
        if payload.get("thumb_offset_ms"):
            body["thumb_offset"] = str(int(payload["thumb_offset_ms"]))
        video_url = payload.get("video_url")
        if video_url:
            body["video_url"] = video_url
        else:
            body["upload_type"] = "resumable"
        response = self.client.post(
            f"{self.graph}/{ig_user_id}/media",
            headers=bearer_headers(context.credential["access_token"]),
            data=body,
        )
        self._raise_for_error(response)
        container = response.json().get("id")
        if not container:
            raise PermanentError("Instagram n'a pas renvoyé d'identifiant de conteneur.")
        return str(container)

    def _upload_resumable(self, context: PublishContext, container_id: str) -> None:
        if context.media_path is None or not context.media_path.exists():
            raise PermanentError("Fichier média introuvable pour l'upload Instagram.")
        size = context.media_path.stat().st_size
        context.report(20, f"Envoi de {size // 1_000_000} Mo aux serveurs Meta…")
        with open(context.media_path, "rb") as handle:
            content = handle.read()
        response = self.client.post(
            f"{RUPLOAD_URL}/{self.api_version}/{container_id}",
            headers={
                "Authorization": f"OAuth {context.credential['access_token']}",
                "offset": "0",
                "file_size": str(size),
                "Content-Type": "application/octet-stream",
            },
            content=content,
        )
        self._raise_for_error(response)

    def _wait_for_container(self, context: PublishContext, container_id: str) -> str:
        for attempt in range(POLL_MAX_ATTEMPTS):
            response = self.client.get(
                f"{self.graph}/{container_id}",
                params={"fields": "status_code,status", "access_token": context.credential["access_token"]},
            )
            self._raise_for_error(response)
            data = response.json()
            code = (data.get("status_code") or "").upper()
            context.report(40 + min(40, attempt * 2), f"Traitement Meta : {code or 'en attente'}")
            if code == "FINISHED":
                return code
            if code in {"ERROR", "EXPIRED"}:
                raise PermanentError(
                    f"Conteneur Instagram {code} : {data.get('status')}",
                    code=f"instagram_container_{code.lower()}",
                )
            time.sleep(POLL_INTERVAL_SECONDS)
        raise RetriableError("Traitement Meta trop long (10 min) : nouvelle tentative possible.", code="instagram_processing_timeout")

    def _publish_container(self, context: PublishContext, ig_user_id: str, container_id: str) -> str:
        response = self.client.post(
            f"{self.graph}/{ig_user_id}/media_publish",
            headers=bearer_headers(context.credential["access_token"]),
            data={"creation_id": container_id},
        )
        self._raise_for_error(response)
        media_id = response.json().get("id")
        if not media_id:
            raise PermanentError("media_publish n'a pas renvoyé d'identifiant de média.")
        return str(media_id)

    def _get_permalink(self, context: PublishContext, media_id: str) -> str | None:
        response = self.client.get(
            f"{self.graph}/{media_id}",
            params={"fields": "permalink", "access_token": context.credential["access_token"]},
        )
        if response.status_code >= 400:
            return None
        return (response.json() or {}).get("permalink")

    def publish(self, context: PublishContext) -> PublishResult:
        try:
            ig_user_id = self._ig_user_id(context)
            context.report(5, "Création du conteneur Reels…")
            container_id = self._create_container(context, ig_user_id)
            context.target.pending_operation_id = container_id
            if not (context.target.payload or {}).get("video_url"):
                self._upload_resumable(context, container_id)
            self._wait_for_container(context, container_id)
            context.report(85, "Publication…")
            media_id = self._publish_container(context, ig_user_id, container_id)
            permalink = self._get_permalink(context, media_id)
            return PublishResult(
                outcome="success",
                status="published",
                remote_id=media_id,
                remote_url=permalink or f"https://www.instagram.com/reel/{media_id}/",
                operation_id=container_id,
                data={"container_id": container_id},
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
                error_code="instagram_timeout",
                error_message=f"Timeout Meta : {exc}",
                operation_id=context.target.pending_operation_id,
                requires_user_action=True,
                user_action_hint=(
                    "Le conteneur a peut-être été publié. Vérifiez le profil Instagram avant "
                    "de relancer (un conteneur ne peut être publié qu'une fois)."
                ),
            )

    def get_publish_status(self, context: PublishContext) -> StatusResult:
        if not context.target.remote_id:
            if not context.target.pending_operation_id:
                raise PermanentError("Aucun identifiant distant Instagram.")
            response = self.client.get(
                f"{self.graph}/{context.target.pending_operation_id}",
                params={"fields": "status_code", "access_token": context.credential["access_token"]},
            )
            self._raise_for_error(response)
            code = (response.json().get("status_code") or "").upper()
            mapping = {"FINISHED": "processing", "PUBLISHED": "published", "IN_PROGRESS": "processing", "ERROR": "failed", "EXPIRED": "failed"}
            return StatusResult(status=mapping.get(code, "processing"), detail=f"conteneur {code}")
        response = self.client.get(
            f"{self.graph}/{context.target.remote_id}",
            params={"fields": "permalink,media_type,timestamp", "access_token": context.credential["access_token"]},
        )
        self._raise_for_error(response)
        data = response.json()
        return StatusResult(status="published", remote_url=data.get("permalink"), remote_id=context.target.remote_id, detail=data.get("media_type"))

    def get_analytics(self, context: PublishContext) -> dict[str, Any]:
        if not context.target.remote_id:
            return {}
        response = self.client.get(
            f"{self.graph}/{context.target.remote_id}/insights",
            params={
                "metric": "views,likes,comments,shares,saved,total_interactions,reach",
                "access_token": context.credential["access_token"],
            },
        )
        if response.status_code >= 400:
            return {"metrics": {}, "error": f"insights indisponibles (HTTP {response.status_code})"}
        metrics: dict[str, Any] = {}
        for item in (response.json() or {}).get("data") or []:
            name = item.get("name")
            values = item.get("values") or []
            if name and values and values[0].get("value") is not None:
                metrics[name] = values[0]["value"]
        return {"metrics": metrics, "source": "instagram.media.insights", "fetched_at": datetime.now(UTC).isoformat()}

    def _raise_for_error(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        code = None
        message = response.text[:400]
        subcode = None
        try:
            error = response.json().get("error", {})
            code = str(error.get("code") or "")
            subcode = error.get("error_subcode")
            message = error.get("message") or message
        except ValueError:
            pass
        detail = f"{message} (code {code}" + (f", subcode {subcode}" if subcode else "") + ")"
        if response.status_code in {429, 500, 502, 503, 504} or code in {"4", "17", "32", "613"}:
            raise RetriableError(detail, code=code, http_status=response.status_code)
        if response.status_code in {401, 403} or code in {"190", "10", "200"}:
            raise PermanentError(detail, code=code, http_status=response.status_code)
        raise PermanentError(detail, code=code, http_status=response.status_code)
