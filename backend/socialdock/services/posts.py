"""Service publications : composition, programmation, lots, calendrier."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..logging_setup import log_event
from ..models import (
    Account,
    MediaAsset,
    Post,
    PostStatus,
    PostTarget,
    PublishAttempt,
    utcnow,
)
from .states import can_transition, describe_status, set_status
from .templates import build_payload_for, create_targets_for_accounts, default_payload

log = logging.getLogger(__name__)


class PostError(RuntimeError):
    pass


def ensure_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise PostError("Un horaire sans fuseau horaire est refusé : fournissez un instant UTC ou offset.")
    return value.astimezone(UTC)


def create_post(
    session: Session,
    *,
    title: str,
    description: str = "",
    hashtags: Sequence[str] | None = None,
    media_asset_id: str | None = None,
    thumbnail_media_id: str | None = None,
    series_id: str | None = None,
    episode_number: int | None = None,
    language: str = "fr",
    internal_notes: str | None = None,
    account_ids: Sequence[str] | None = None,
    per_platform: dict[str, dict[str, Any]] | None = None,
    scheduled_at: Sequence[tuple[str, datetime | str | None]] | None = None,
) -> Post:
    post = Post(
        title=title.strip() or "Sans titre",
        description=description,
        hashtags=[h.strip().lstrip("#") for h in (hashtags or []) if h.strip()],
        media_asset_id=media_asset_id,
        thumbnail_media_id=thumbnail_media_id,
        series_id=series_id,
        episode_number=episode_number,
        language=language or "fr",
        internal_notes=internal_notes,
    )
    session.add(post)
    session.flush()
    if account_ids:
        create_targets_for_accounts(session, post, list(account_ids))
    if per_platform:
        for target in post.targets:
            platform = target.account.platform if target.account else "demo"
            target.payload = build_payload_for(platform, post, per_platform.get(platform))
    if scheduled_at:
        for target_id, when in scheduled_at:
            target = next((t for t in post.targets if t.id == target_id), None)
            if target is not None and when is not None:
                schedule_target(session, target, when)
    session.flush()
    return post


def update_post(
    session: Session,
    post_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    hashtags: Sequence[str] | None = None,
    media_asset_id: str | None = None,
    thumbnail_media_id: str | None = None,
    series_id: str | None = None,
    episode_number: int | None = None,
    language: str | None = None,
    internal_notes: str | None = None,
    account_ids: Sequence[str] | None = None,
    per_platform: dict[str, dict[str, Any]] | None = None,
    propagate_metadata: bool = False,
) -> Post:
    post = session.get(Post, post_id)
    if post is None:
        raise PostError(f"Publication introuvable : {post_id}")
    if title is not None:
        post.title = title.strip() or post.title
    if description is not None:
        post.description = description
    if hashtags is not None:
        post.hashtags = [h.strip().lstrip("#") for h in hashtags if h.strip()]
    if media_asset_id is not None:
        post.media_asset_id = media_asset_id or None
    if thumbnail_media_id is not None:
        post.thumbnail_media_id = thumbnail_media_id or None
    if series_id is not None:
        post.series_id = series_id or None
    if episode_number is not None:
        post.episode_number = episode_number
    if language is not None:
        post.language = language
    if internal_notes is not None:
        post.internal_notes = internal_notes
    session.flush()

    if account_ids is not None:
        wanted = set(account_ids)
        for target in list(post.targets):
            if target.account_id not in wanted:
                if target.status in {PostStatus.PUBLISHED.value, PostStatus.PUBLISHED_PRIVATE.value}:
                    raise PostError(
                        f"Impossible de retirer {target.account.display_name} : la publication est déjà effective."
                    )
                session.delete(target)
        session.flush()
        create_targets_for_accounts(session, post, sorted(wanted - {t.account_id for t in post.targets}))

    if per_platform:
        for target in post.targets:
            platform = target.account.platform if target.account else "demo"
            overrides = per_platform.get(platform)
            if overrides is None:
                continue
            target.payload = {**(target.payload or {}), **{k: v for k, v in overrides.items() if v is not None}}
    elif propagate_metadata:
        for target in post.targets:
            platform = target.account.platform if target.account else "demo"
            target.payload = default_payload(platform, post)
    session.flush()
    return post


def delete_post(session: Session, post_id: str, *, confirm: bool) -> None:
    if not confirm:
        raise PostError("Suppression refusée : confirmation explicite requise.")
    post = session.get(Post, post_id)
    if post is None:
        raise PostError(f"Publication introuvable : {post_id}")
    published = [t for t in post.targets if t.status in {PostStatus.PUBLISHED.value, PostStatus.PUBLISHED_PRIVATE.value}]
    session.delete(post)
    session.flush()
    log_event(
        session,
        source="posts",
        message=f"Publication supprimée : {post.title} ({len(published)} déjà publiée(s) — contenus distants non affectés)",
        level="warning" if published else "info",
    )


def duplicate_post(session: Session, post_id: str, *, account_ids: Sequence[str] | None = None) -> Post:
    source = session.get(Post, post_id)
    if source is None:
        raise PostError(f"Publication introuvable : {post_id}")
    copy = create_post(
        session,
        title=f"{source.title} (copie)",
        description=source.description,
        hashtags=list(source.hashtags or []),
        media_asset_id=source.media_asset_id,
        thumbnail_media_id=source.thumbnail_media_id,
        series_id=source.series_id,
        episode_number=source.episode_number,
        language=source.language,
        internal_notes=source.internal_notes,
        account_ids=account_ids or [t.account_id for t in source.targets],
    )
    per_platform = {
        (t.account.platform if t.account else "demo"): dict(t.payload or {}) for t in source.targets
    }
    for target in copy.targets:
        platform = target.account.platform if target.account else "demo"
        if platform in per_platform:
            target.payload = per_platform[platform]
    session.flush()
    return copy


def schedule_target(session: Session, target: PostTarget, when: datetime | str) -> PostTarget:
    moment = ensure_utc(when)
    if moment is None:
        raise PostError("Horaire manquant.")
    if target.status in {PostStatus.PUBLISHED.value, PostStatus.PUBLISHED_PRIVATE.value, PostStatus.CANCELLED.value}:
        raise PostError(f"Une publication « {describe_status(target.status)} » ne peut pas être reprogrammée.")
    target.scheduled_at = moment
    if target.status in {PostStatus.DRAFT.value, PostStatus.READY.value, PostStatus.FAILED.value, PostStatus.WAITING_FOR_USER.value, PostStatus.UNCERTAIN.value}:
        set_status(target, PostStatus.SCHEDULED.value)
    target.requires_user_action = False
    target.next_retry_at = None
    session.flush()
    return target


def unschedule_target(session: Session, target: PostTarget) -> PostTarget:
    if can_transition(target.status, PostStatus.READY.value):
        set_status(target, PostStatus.READY.value)
    elif target.status == PostStatus.DRAFT.value:
        pass
    else:
        raise PostError(f"Impossible de déprogrammer une publication « {describe_status(target.status)} ».")
    target.scheduled_at = None
    session.flush()
    return target


def publish_now(session: Session, target: PostTarget) -> PostTarget:
    """Force une publication immédiate (le scheduler l'exécutera au prochain tick)."""
    target.scheduled_at = utcnow()
    if can_transition(target.status, PostStatus.SCHEDULED.value):
        set_status(target, PostStatus.SCHEDULED.value)
    elif target.status not in {PostStatus.SCHEDULED.value}:
        raise PostError(f"Publication impossible depuis l'état « {describe_status(target.status)} ».")
    target.next_retry_at = None
    session.flush()
    log_event(session, source="posts", message=f"Publication immédiate demandée : {target.id}")
    return target


def cancel_target(session: Session, target: PostTarget) -> PostTarget:
    if can_transition(target.status, PostStatus.CANCELLED.value):
        set_status(target, PostStatus.CANCELLED.value)
        target.requires_user_action = False
        session.flush()
        return target
    raise PostError(f"Annulation impossible depuis l'état « {describe_status(target.status)} ».")


def update_target_payload(session: Session, target: PostTarget, payload: dict[str, Any]) -> PostTarget:
    if target.status in {PostStatus.PUBLISHED.value, PostStatus.PUBLISHED_PRIVATE.value}:
        raise PostError("Les métadonnées d'une publication effective ne sont plus modifiables ici.")
    merged = {**(target.payload or {}), **{k: v for k, v in payload.items() if v is not None}}
    target.payload = merged
    session.flush()
    return target


def list_targets(
    session: Session,
    *,
    status: Iterable[str] | None = None,
    account_ids: Iterable[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    query: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> tuple[list[PostTarget], int]:
    stmt = select(PostTarget)
    if status:
        stmt = stmt.where(PostTarget.status.in_(list(status)))
    if account_ids:
        stmt = stmt.where(PostTarget.account_id.in_(list(account_ids)))
    if start:
        stmt = stmt.where(PostTarget.scheduled_at >= start)
    if end:
        stmt = stmt.where(PostTarget.scheduled_at <= end)
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where(PostTarget.post.has(Post.title.ilike(like)))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.order_by(PostTarget.scheduled_at.asc().nullslast(), PostTarget.created_at.desc()).limit(limit).offset(offset)).all()
    return list(rows), int(total)


def dashboard_summary(session: Session) -> dict[str, Any]:
    now = utcnow()
    today_start = datetime.combine(now.date(), dtime.min, tzinfo=UTC)
    today_end = today_start + timedelta(days=1)

    def count_targets(**filters: Any) -> int:
        stmt = select(func.count()).select_from(PostTarget)
        for key, value in filters.items():
            column = getattr(PostTarget, key)
            if isinstance(value, (list, tuple, set)):
                stmt = stmt.where(column.in_(list(value)))
            else:
                stmt = stmt.where(column == value)
        return int(session.scalar(stmt) or 0)

    accounts_total = int(session.scalar(select(func.count()).select_from(Account)) or 0)
    accounts_connected = int(
        session.scalar(select(func.count()).select_from(Account).where(Account.status.in_(["connected", "demo"]))) or 0
    )
    upcoming = session.scalars(
        select(PostTarget)
        .where(PostTarget.status == PostStatus.SCHEDULED.value, PostTarget.scheduled_at >= now)
        .order_by(PostTarget.scheduled_at.asc())
        .limit(10)
    ).all()
    return {
        "generated_at": now.isoformat(),
        "accounts_total": accounts_total,
        "accounts_connected": accounts_connected,
        "accounts_needing_attention": int(
            session.scalar(
                select(func.count()).select_from(Account).where(Account.status.in_(["expired", "error", "not_configured"]))
            )
            or 0
        ),
        "posts_today": int(
            session.scalar(
                select(func.count())
                .select_from(PostTarget)
                .where(PostTarget.scheduled_at >= today_start, PostTarget.scheduled_at < today_end)
            )
            or 0
        ),
        "scheduled": count_targets(status=PostStatus.SCHEDULED.value),
        "drafts": count_targets(status=PostStatus.DRAFT.value),
        "ready": count_targets(status=PostStatus.READY.value),
        "published": count_targets(status=[PostStatus.PUBLISHED.value, PostStatus.PUBLISHED_PRIVATE.value]),
        "failed": count_targets(status=PostStatus.FAILED.value),
        "waiting_for_user": count_targets(status=PostStatus.WAITING_FOR_USER.value),
        "uncertain": count_targets(status=PostStatus.UNCERTAIN.value),
        "late": int(
            session.scalar(
                select(func.count())
                .select_from(PostTarget)
                .where(
                    PostTarget.status == PostStatus.SCHEDULED.value,
                    PostTarget.scheduled_at < now - timedelta(minutes=1),
                )
            )
            or 0
        ),
        "media_count": int(session.scalar(select(func.count()).select_from(MediaAsset)) or 0),
        "attempts_total": int(session.scalar(select(func.count()).select_from(PublishAttempt)) or 0),
        "upcoming": [
            {
                "post_target_id": t.id,
                "title": t.post.title if t.post else None,
                "account": t.account.display_name if t.account else None,
                "platform": t.account.platform if t.account else None,
                "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
                "status": t.status,
            }
            for t in upcoming
        ],
    }


def batch_schedule(
    session: Session,
    *,
    media_ids: Sequence[str],
    account_ids: Sequence[str],
    days: Sequence[date],
    times: Sequence[dtime],
    template_id: str | None = None,
    per_platform: dict[str, dict[str, Any]] | None = None,
    title_prefix: str = "",
    stagger_minutes: int = 0,
) -> dict[str, Any]:
    """Répartit plusieurs vidéos sur plusieurs jours/horaires, sans LLM.

    Ordre déterministe : pour chaque média (dans l'ordre fourni), on affecte le
    créneau suivant de la grille jours × heures, puis on crée une publication
    avec une cible par compte sélectionné.
    """
    if not media_ids or not account_ids or not days or not times:
        raise PostError("Sélection incomplète : médias, comptes, jours et horaires sont requis.")
    slots: list[datetime] = []
    for day in days:
        for hour in times:
            slots.append(datetime.combine(day, hour, tzinfo=UTC))
    if stagger_minutes:
        adjusted: list[datetime] = []
        for index, slot in enumerate(slots):
            adjusted.append(slot + timedelta(minutes=stagger_minutes * index))
        slots = adjusted

    created: list[dict[str, Any]] = []
    for index, media_id in enumerate(media_ids):
        asset = session.get(MediaAsset, media_id)
        if asset is None:
            raise PostError(f"Média introuvable : {media_id}")
        when = slots[index % len(slots)]
        post = create_post(
            session,
            title=f"{title_prefix}{asset.display_name}".strip(),
            description="",
            media_asset_id=asset.id,
            account_ids=list(account_ids),
            per_platform=per_platform,
        )
        if template_id:
            from .templates import apply_template

            apply_template(session, post, template_id)
        for offset, target in enumerate(post.targets):
            schedule_target(session, target, when + timedelta(minutes=stagger_minutes * offset))
        created.append(
            {
                "post_id": post.id,
                "media_id": asset.id,
                "title": post.title,
                "scheduled_at": when.isoformat(),
                "targets": len(post.targets),
            }
        )
    session.flush()
    log_event(session, source="posts", message=f"Programmation par lot : {len(created)} publication(s) sur {len(slots)} créneau(x)")
    return {"scheduled": created, "slots_used": [s.isoformat() for s in slots[: len(media_ids)]]}
