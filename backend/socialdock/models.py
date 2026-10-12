"""Modèles SQLAlchemy de SocialDock.

Conventions :
* tous les instants sont stockés en UTC (``DateTime(timezone=True)``) ;
* le fuseau d'affichage (Europe/Paris par défaut) est géré côté client ;
* aucune donnée sensible n'est stockée en clair : les blobs OAuth passent par
  ``socialdock.security.encrypt_secret``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


# --------------------------------------------------------------------------
# Énumérations métier
# --------------------------------------------------------------------------
class Platform(StrEnum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    DEMO = "demo"


class AccountStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CONNECTED = "connected"
    EXPIRED = "expired"
    ERROR = "error"
    DEMO = "demo"


class PostStatus(StrEnum):
    """État d'une publication *cible* (un compte = une cible)."""

    DRAFT = "draft"
    READY = "ready"
    SCHEDULED = "scheduled"
    WAITING_FOR_USER = "waiting_for_user"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    PUBLISHED_PRIVATE = "published_private"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    CANCELLED = "cancelled"


#: Transitions autorisées. Toute autre transition est refusée par
#: :func:`socialdock.services.states.assert_transition`.
ALLOWED_TRANSITIONS: dict[PostStatus, set[PostStatus]] = {
    PostStatus.DRAFT: {PostStatus.READY, PostStatus.SCHEDULED, PostStatus.WAITING_FOR_USER, PostStatus.CANCELLED},
    PostStatus.READY: {PostStatus.SCHEDULED, PostStatus.PUBLISHING, PostStatus.WAITING_FOR_USER, PostStatus.CANCELLED, PostStatus.DRAFT},
    PostStatus.SCHEDULED: {
        PostStatus.UPLOADING,
        PostStatus.WAITING_FOR_USER,
        PostStatus.FAILED,
        PostStatus.UNCERTAIN,
        PostStatus.CANCELLED,
        PostStatus.READY,
        PostStatus.DRAFT,
    },
    PostStatus.WAITING_FOR_USER: {PostStatus.PUBLISHED, PostStatus.PUBLISHED_PRIVATE, PostStatus.FAILED, PostStatus.CANCELLED, PostStatus.READY},
    PostStatus.UPLOADING: {PostStatus.PROCESSING, PostStatus.PUBLISHING, PostStatus.FAILED, PostStatus.UNCERTAIN, PostStatus.CANCELLED},
    PostStatus.PROCESSING: {PostStatus.PUBLISHING, PostStatus.FAILED, PostStatus.UNCERTAIN, PostStatus.CANCELLED},
    PostStatus.PUBLISHING: {
        PostStatus.PUBLISHED,
        PostStatus.PUBLISHED_PRIVATE,
        PostStatus.FAILED,
        PostStatus.UNCERTAIN,
        PostStatus.CANCELLED,
    },
    PostStatus.PUBLISHED: {PostStatus.PUBLISHED_PRIVATE, PostStatus.FAILED},
    PostStatus.PUBLISHED_PRIVATE: {PostStatus.PUBLISHED, PostStatus.FAILED},
    PostStatus.FAILED: {PostStatus.READY, PostStatus.SCHEDULED, PostStatus.UNCERTAIN, PostStatus.CANCELLED},
    PostStatus.UNCERTAIN: {PostStatus.PUBLISHED, PostStatus.PUBLISHED_PRIVATE, PostStatus.FAILED, PostStatus.READY, PostStatus.CANCELLED},
    PostStatus.CANCELLED: {PostStatus.DRAFT, PostStatus.READY},
}

TERMINAL_STATUSES = {PostStatus.PUBLISHED, PostStatus.PUBLISHED_PRIVATE, PostStatus.CANCELLED}


class AttemptOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    UNCERTAIN = "uncertain"
    SKIPPED = "skipped"


class AttemptPhase(StrEnum):
    UPLOAD = "upload"
    PROCESS = "process"
    PUBLISH = "publish"
    STATUS = "status"
    ANALYTICS = "analytics"


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------
class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    platform: Mapped[str] = mapped_column(String(16), index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    external_id: Mapped[str | None] = mapped_column(String(190), nullable=True)
    username: Mapped[str | None] = mapped_column(String(190), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    #: ``real`` = connecteur API officiel, ``demo`` = compte simulé local
    mode: Mapped[str] = mapped_column(String(8), default="real")
    status: Mapped[str] = mapped_column(String(24), default=AccountStatus.NOT_CONFIGURED.value)
    #: blob OAuth chiffré (access/refresh token, scopes, expiration)
    credential_blob: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    permissions_missing: Mapped[list[Any]] = mapped_column(JSON, default=list)
    default_privacy: Mapped[str | None] = mapped_column(String(24), nullable=True)
    default_category_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    group_id: Mapped[str | None] = mapped_column(ForeignKey("account_groups.id", ondelete="SET NULL"), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    credentials_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    group: Mapped["AccountGroup | None"] = relationship(back_populates="accounts")
    targets: Mapped[list["PostTarget"]] = relationship(back_populates="account", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_account_platform_external"),)


class AccountGroup(Base):
    __tablename__ = "account_groups"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    accounts: Mapped[list[Account]] = relationship(back_populates="group")


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    #: chemin relatif au dossier média (jamais de chemin absolu en base)
    stored_path: Mapped[str] = mapped_column(String(512))
    original_name: Mapped[str] = mapped_column(String(300))
    display_name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(16), default="video", index=True)  # video | image
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    #: ``ok`` = ffprobe a parlé, ``unavailable`` = FFmpeg absent, ``failed`` = fichier illisible
    probe_status: Mapped[str] = mapped_column(String(16), default="unavailable")
    probe_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    collections: Mapped[list[Any]] = mapped_column(JSON, default=list)
    imported_from: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    __table_args__ = (Index("ix_media_sha_kind", "sha256", "kind"),)


class PostTemplate(Base):
    __tablename__ = "post_templates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: {hashtags, per_platform: {youtube: {...}, instagram: {...}, tiktok: {...}}, account_ids, schedule}
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Series(Base):
    __tablename__ = "series"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    default_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    hashtags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    #: identifiants de comptes par défaut pour la série
    account_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    next_episode: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Post(Base):
    """Composition : un média + un jeu de métadonnées communs + N cibles."""

    __tablename__ = "posts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    media_asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    thumbnail_media_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True)
    series_id: Mapped[str | None] = mapped_column(ForeignKey("series.id", ondelete="SET NULL"), nullable=True)
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="fr")
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_id: Mapped[str | None] = mapped_column(ForeignKey("post_templates.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    media: Mapped["MediaAsset | None"] = relationship(foreign_keys=[media_asset_id])
    thumbnail: Mapped["MediaAsset | None"] = relationship(foreign_keys=[thumbnail_media_id])
    series: Mapped["Series | None"] = relationship()
    targets: Mapped[list["PostTarget"]] = relationship(
        back_populates="post", cascade="all, delete-orphan", order_by="PostTarget.created_at"
    )


class PostTarget(Base):
    """Une publication vers un compte donné : la vraie unité de travail du scheduler."""

    __tablename__ = "post_targets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24), default=PostStatus.DRAFT.value, index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: charge utile spécifique à la plateforme (titre, légende, catégorie, confidentialité…)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: clé d'idempotence : empêche toute double publication de la même cible
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: new_id())
    #: identifiant renvoyé par la plateforme (videoId / media_id / publish_id…)
    remote_id: Mapped[str | None] = mapped_column(String(190), nullable=True)
    remote_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    #: identifiant d'opération distante en cours (permet de lever un doute)
    pending_operation_id: Mapped[str | None] = mapped_column(String(190), nullable=True)
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: verrou propriétaire du worker (prévient l'exécution concurrente)
    locked_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requires_user_action: Mapped[bool] = mapped_column(Boolean, default=False)
    user_action_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_status_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    post: Mapped[Post] = relationship(back_populates="targets")
    account: Mapped[Account] = relationship(back_populates="targets")
    attempts: Mapped[list["PublishAttempt"]] = relationship(
        back_populates="target", cascade="all, delete-orphan", order_by="PublishAttempt.attempt_no"
    )

    __table_args__ = (UniqueConstraint("post_id", "account_id", name="uq_post_target_post_account"),)


class PublishAttempt(Base):
    """Journal d'exécution : la preuve de ce qui a réellement été tenté."""

    __tablename__ = "publish_attempts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    post_target_id: Mapped[str] = mapped_column(ForeignKey("post_targets.id", ondelete="CASCADE"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    phase: Mapped[str] = mapped_column(String(16), default=AttemptPhase.PUBLISH.value)
    outcome: Mapped[str] = mapped_column(String(16), default=AttemptOutcome.FAILURE.value)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: message expurgé de tout secret (voir socialdock.security.redact)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_operation_id: Mapped[str | None] = mapped_column(String(190), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    target: Mapped[PostTarget] = relationship(back_populates="attempts")


class AnalyticsSample(Base):
    """Métriques réellement renvoyées par les API. Aucune valeur n'est inventée :
    une métrique absente n'est tout simplement pas présente dans ``metrics``."""

    __tablename__ = "analytics_samples"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    post_target_id: Mapped[str | None] = mapped_column(ForeignKey("post_targets.id", ondelete="SET NULL"), nullable=True, index=True)
    metric_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (UTC)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("account_id", "post_target_id", "metric_date", name="uq_analytics_scope_date"),)


class OAuthState(Base):
    """État anti-CSRF + PKCE des parcours OAuth (durée de vie courte)."""

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(16))
    code_verifier: Mapped[str | None] = mapped_column(String(200), nullable=True)
    redirect_uri: Mapped[str] = mapped_column(String(400))
    account_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scopes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class WatchedFolder(Base):
    __tablename__ = "watched_folders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    path: Mapped[str] = mapped_column(String(600))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    create_draft: Mapped[bool] = mapped_column(Boolean, default=True)
    template_id: Mapped[str | None] = mapped_column(ForeignKey("post_templates.id", ondelete="SET NULL"), nullable=True)
    tags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    recursive: Mapped[bool] = mapped_column(Boolean, default=False)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: empreintes déjà traitées (évite les doublons entre deux scans)
    seen_hashes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventLog(Base):
    """Journal applicatif persistant, affiché dans la page Diagnostics."""

    __tablename__ = "event_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    level: Mapped[str] = mapped_column(String(12), default=LogLevel.INFO.value, index=True)
    source: Mapped[str] = mapped_column(String(48), index=True)
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AppSetting(Base):
    """Préférences applicatives (clé/valeur JSON) — hors données sensibles."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
