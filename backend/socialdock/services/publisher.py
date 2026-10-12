"""Pipeline de publication : idempotence, verrouillage, journal des tentatives.

Règles de sûreté appliquées ici (et non dans l'interface) :

1. une cible déjà dotée d'un ``remote_id`` n'est **jamais** republiée : on
   vérifie son statut distant ;
2. un échec ambigu (timeout, réponse illisible) place la cible en
   ``uncertain`` avec ``requires_user_action`` — aucune relance automatique ;
3. chaque tentative est journalisée dans ``publish_attempts`` avec un message
   expurgé de tout secret ;
4. une cible dont le connecteur ne sait pas publier passe en
   ``waiting_for_user`` avec une consigne explicite (mode assisté).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..connectors.base import PublishContext, PublishResult, SocialConnector
from ..connectors.registry import connector_for_account
from ..logging_setup import log_event
from ..models import (
    Account,
    AttemptOutcome,
    AttemptPhase,
    MediaAsset,
    Post,
    PostStatus,
    PostTarget,
    PublishAttempt,
    utcnow,
)
from ..security import SecretVault, redact
from .states import can_transition, describe_status, set_status

log = logging.getLogger(__name__)

LOCK_MINUTES = 15


class PublicationError(RuntimeError):
    pass


def credential_for(account: Account, settings: Settings | None = None) -> dict[str, Any]:
    if account.mode == "demo":
        return {"demo": True}
    vault = SecretVault(settings)
    return vault.decrypt(account.credential_blob)


def store_credential(account: Account, credential: dict[str, Any], settings: Settings | None = None) -> None:
    vault = SecretVault(settings)
    account.credential_blob = vault.encrypt(credential)
    expires = credential.get("expires_at")
    if expires:
        try:
            account.credentials_expire_at = datetime.fromisoformat(expires)
        except ValueError:
            account.credentials_expire_at = None


def _needs_refresh(credential: dict[str, Any]) -> bool:
    expires = credential.get("expires_at")
    if not expires:
        return False
    try:
        expiry = datetime.fromisoformat(expires)
    except ValueError:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry <= datetime.now(timezone.utc) + timedelta(minutes=2)


def acquire_lock(session: Session, target: PostTarget, owner: str, *, minutes: int = LOCK_MINUTES) -> bool:
    """Verrou conditionnel : échoue si un autre worker tient déjà la cible."""
    now = utcnow()
    if target.locked_by and target.lock_expires_at and target.lock_expires_at > now:
        return False
    target.locked_by = owner
    target.locked_at = now
    target.lock_expires_at = now + timedelta(minutes=minutes)
    session.commit()
    return True


def release_lock(session: Session, target: PostTarget) -> None:
    target.locked_by = None
    target.locked_at = None
    target.lock_expires_at = None
    session.commit()


def record_attempt(
    session: Session,
    target: PostTarget,
    *,
    phase: str = AttemptPhase.PUBLISH.value,
    outcome: str,
    detail: str | None = None,
    http_status: int | None = None,
    remote_operation_id: str | None = None,
    started_at: datetime | None = None,
) -> PublishAttempt:
    attempt = PublishAttempt(
        post_target_id=target.id,
        attempt_no=(target.attempts_count or 0) + 1,
        phase=phase,
        outcome=outcome,
        http_status=http_status,
        detail=redact(detail)[:2000] if detail else None,
        remote_operation_id=remote_operation_id,
        started_at=started_at or utcnow(),
        finished_at=utcnow(),
    )
    session.add(attempt)
    target.attempts_count = (target.attempts_count or 0) + 1
    session.commit()
    return attempt


def _media_path(settings: Settings, post: Post) -> tuple[Any, Any]:
    media = post.media
    thumb = post.thumbnail
    media_path = settings.safe_media_path(media.stored_path) if media else None
    thumb_path = settings.safe_media_path(thumb.stored_path) if thumb else None
    if thumb_path is None and media is not None and media.thumbnail_path:
        candidate = settings.thumbnails_dir / media.thumbnail_path
        thumb_path = candidate if candidate.exists() else None
    return media_path, thumb_path


def publish_target(
    session: Session,
    target: PostTarget,
    *,
    settings: Settings | None = None,
    connector: SocialConnector | None = None,
    owner: str = "worker",
    progress: Callable[[str, int, str], None] | None = None,
) -> PostTarget:
    """Exécute (ou refuse d'exécuter) la publication d'une cible."""
    settings = settings or get_settings()
    started = utcnow()
    post = target.post
    account = target.account
    if post is None or account is None:
        raise PublicationError("Cible orpheline : publication ou compte manquant.")

    if target.remote_id:
        # Règle 1 : idempotence — on vérifie, on ne republie pas.
        log.info("Cible %s déjà publiée (remote_id=%s) : vérification du statut", target.id, target.remote_id)
        return refresh_remote_status(session, target, settings=settings, connector=connector)

    connector = connector or connector_for_account(account, settings)
    capabilities = connector.get_capabilities(account)

    # Un compte de démonstration ne requiert aucune authentification : seule sa
    # capacité de publication compte.
    needs_auth = account.mode != "demo" and not capabilities.auth_available
    if not capabilities.publish_video or needs_auth:
        _to_waiting_for_user(
            session,
            target,
            hint=(
                f"{capabilities.label} : publication automatique indisponible "
                f"({'; '.join(capabilities.restrictions) or 'connecteur non configuré'}). "
                "Utilisez le mode assisté."
            ),
        )
        record_attempt(session, target, outcome=AttemptOutcome.SKIPPED.value, detail="Publication automatique indisponible pour ce compte.")
        log_event(session, source="publisher", message=f"{target.id} : mode assisté requis ({account.display_name})", level="warning")
        return target

    credential = credential_for(account, settings)
    if _needs_refresh(credential) and account.mode != "demo":
        try:
            credential = connector.refresh_auth(credential)
            store_credential(account, credential, settings)
            session.commit()
        except Exception as exc:  # noqa: BLE001 — toute erreur d'auth est rapportée à l'utilisateur
            account.status = "expired"
            account.last_error = redact(str(exc))
            session.commit()
            _fail(session, target, "auth_expired", f"Jeton expiré et renouvellement impossible : {exc}")
            return target

    media_path, thumb_path = _media_path(settings, post)
    errors = connector.validate_post(target.payload or {})
    if errors:
        _fail(session, target, "invalid_payload", " ; ".join(errors))
        return target

    context = PublishContext(
        target=target,
        post=post,
        account=account,
        credential=credential,
        media_path=media_path,
        thumbnail_path=thumb_path,
        progress=(lambda percent, message: progress(target.id, percent, message)) if progress else None,
        timeout=settings.publish_timeout_seconds,
    )

    _transition(session, target, PostStatus.UPLOADING.value)
    log.info("Publication de la cible %s vers %s", target.id, account.display_name)
    try:
        result: PublishResult = connector.publish(context)
    except Exception as exc:  # noqa: BLE001 — filet de sécurité du worker
        log.exception("Erreur inattendue pendant la publication de %s", target.id)
        record_attempt(session, target, outcome=AttemptOutcome.UNCERTAIN.value, detail=str(exc), started_at=started)
        _set(session, target, PostStatus.UNCERTAIN.value, force=True)
        target.requires_user_action = True
        target.user_action_hint = "Erreur inattendue pendant la publication : vérifiez la plateforme avant de relancer."
        target.error_message = redact(str(exc))
        target.error_code = "unexpected_error"
        session.commit()
        return target

    outcome_map = {
        "success": AttemptOutcome.SUCCESS.value,
        "failure": AttemptOutcome.FAILURE.value,
        "timeout": AttemptOutcome.TIMEOUT.value,
        "uncertain": AttemptOutcome.UNCERTAIN.value,
    }
    record_attempt(
        session,
        target,
        outcome=outcome_map.get(result.outcome, AttemptOutcome.FAILURE.value),
        detail=result.error_message,
        http_status=result.http_status,
        remote_operation_id=result.operation_id,
        started_at=started,
    )
    target.remote_id = result.remote_id or target.remote_id
    target.remote_url = result.remote_url or target.remote_url
    target.pending_operation_id = result.operation_id or target.pending_operation_id
    target.error_message = redact(result.error_message)
    target.error_code = result.error_code
    target.requires_user_action = bool(result.requires_user_action)
    target.user_action_hint = result.user_action_hint
    if result.outcome == "success":
        target.published_at = utcnow()
        target.last_error_at = None
        account.last_verified_at = utcnow()
    else:
        target.last_error_at = utcnow()

    _set(session, target, result.status, force=True)
    if result.outcome in {"timeout", "failure"}:
        target.next_retry_at = utcnow() + timedelta(minutes=2 ** min(target.attempts_count, 4))
    log_event(
        session,
        source="publisher",
        message=f"{account.display_name} : {describe_status(target.status)}",
        level="info" if result.outcome == "success" else "error",
        data={"post_target_id": target.id, "outcome": result.outcome, "error_code": result.error_code},
    )
    session.commit()
    return target


def refresh_remote_status(
    session: Session,
    target: PostTarget,
    *,
    settings: Settings | None = None,
    connector: SocialConnector | None = None,
) -> PostTarget:
    """Relit le statut distant (aucune écriture côté plateforme)."""
    settings = settings or get_settings()
    account = target.account
    connector = connector or connector_for_account(account, settings)
    credential = credential_for(account, settings)
    context = PublishContext(target=target, post=target.post, account=account, credential=credential)
    try:
        status = connector.get_publish_status(context)
    except Exception as exc:  # noqa: BLE001
        target.last_status_check_at = utcnow()
        target.error_message = redact(str(exc))
        session.commit()
        return target
    target.last_status_check_at = utcnow()
    if status.remote_url:
        target.remote_url = status.remote_url
    if status.remote_id:
        target.remote_id = status.remote_id
    if can_transition(target.status, status.status):
        set_status(target, status.status)
    session.commit()
    return target


def resolve_uncertain(session: Session, target: PostTarget, resolution: str, *, remote_url: str | None = None) -> PostTarget:
    """Décision humaine sur un statut incertain : ``published`` | ``failed`` | ``retry``."""
    resolution = resolution.lower()
    if resolution == "published":
        target.status = PostStatus.PUBLISHED.value
        target.published_at = utcnow()
        target.requires_user_action = False
        target.user_action_hint = None
        if remote_url:
            target.remote_url = remote_url
    elif resolution == "failed":
        target.status = PostStatus.FAILED.value
        target.requires_user_action = False
        target.error_message = "Marqué comme échec par l'utilisateur après statut incertain."
    elif resolution == "retry":
        target.status = PostStatus.READY.value
        target.remote_id = None
        target.pending_operation_id = None
        target.requires_user_action = False
    else:
        raise PublicationError(f"Résolution inconnue : {resolution}")
    log_event(session, source="publisher", message=f"{target.id} : statut incertain résolu ({resolution})", level="warning")
    session.commit()
    return target


def _transition(session: Session, target: PostTarget, status: str) -> None:
    if can_transition(target.status, status):
        set_status(target, status)
        session.commit()


def _set(session: Session, target: PostTarget, status: str, *, force: bool = False) -> None:
    """Applique un statut renvoyé par un connecteur (chemin de confiance)."""
    if can_transition(target.status, status):
        set_status(target, status)
    elif force:
        # Statut renvoyé par la plateforme : on l'accepte même hors transitions
        # classiques (ex. published_private → failed), en journalisant l'écart.
        log.warning("Transition hors matrice pour %s : %s → %s (acceptée)", target.id, target.status, status)
        target.status = status
    session.commit()


def _fail(session: Session, target: PostTarget, code: str, message: str) -> None:
    target.error_code = code
    target.error_message = redact(message)
    target.last_error_at = utcnow()
    _set(session, target, PostStatus.FAILED.value, force=True)
    record_attempt(session, target, outcome=AttemptOutcome.FAILURE.value, detail=message)
    log_event(session, source="publisher", message=f"{target.id} : échec ({code})", level="error")


def _to_waiting_for_user(session: Session, target: PostTarget, hint: str) -> None:
    target.requires_user_action = True
    target.user_action_hint = hint
    _set(session, target, PostStatus.WAITING_FOR_USER.value, force=True)
