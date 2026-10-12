"""Schémas Pydantic v2 de l'API locale."""

from __future__ import annotations

from datetime import date, datetime, time as dtime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# Comptes
# --------------------------------------------------------------------------
class AccountOut(ORMModel):
    id: str
    platform: str
    display_name: str
    external_id: str | None = None
    username: str | None = None
    avatar_url: str | None = None
    mode: str
    status: str
    scopes: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    permissions_missing: list[str] = Field(default_factory=list)
    default_privacy: str | None = None
    default_category_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    is_favorite: bool = False
    group_id: str | None = None
    last_verified_at: datetime | None = None
    credentials_expire_at: datetime | None = None
    last_error: str | None = None


class AccountCreate(BaseModel):
    platform: Literal["youtube", "instagram", "tiktok", "demo"]
    display_name: str = Field(min_length=1, max_length=160)
    mode: Literal["real", "demo"] = "real"


class DemoAccountSeed(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    platform: Literal["youtube", "instagram", "tiktok"]
    index: int = Field(default=1, ge=1, le=99)


class AccountPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    is_favorite: bool | None = None
    group_id: str | None = None
    default_privacy: str | None = None
    default_category_id: str | None = None
    audit_passed: bool | None = None
    demo_scenario: str | None = None


class VerifyReport(BaseModel):
    ok: bool
    message: str | None = None
    mode: str | None = None
    checked_at: str | None = None
    token_refreshed: bool | None = None
    info: dict[str, Any] | None = None


# --------------------------------------------------------------------------
# Médias
# --------------------------------------------------------------------------
class MediaOut(ORMModel):
    id: str
    stored_path: str
    original_name: str
    display_name: str
    kind: str
    mime_type: str | None = None
    size_bytes: int
    sha256: str
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    has_audio: bool
    probe_status: str
    probe_error: str | None = None
    thumbnail_path: str | None = None
    tags: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)
    imported_from: str | None = None
    notes: str | None = None
    created_at: datetime


class MediaPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=300)
    notes: str | None = None
    tags: list[str] | None = None
    collections: list[str] | None = None


class MediaValidation(BaseModel):
    platform: str
    platform_label: str
    ok: bool
    issues: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[dict[str, str]] = Field(default_factory=list)
    info: list[dict[str, str]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    caption_limit: int
    ratio: str | None = None
    probe_status: str


class MediaTransformRequest(BaseModel):
    operation: Literal["h264", "vertical", "audio", "trim", "frame"]
    at_seconds: float | None = None
    duration_seconds: float | None = None
    width: int | None = None


# --------------------------------------------------------------------------
# Publications
# --------------------------------------------------------------------------
class PostTargetOut(ORMModel):
    id: str
    post_id: str
    account_id: str
    status: str
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    remote_id: str | None = None
    remote_url: str | None = None
    attempts_count: int = 0
    next_retry_at: datetime | None = None
    error_message: str | None = None
    error_code: str | None = None
    requires_user_action: bool = False
    user_action_hint: str | None = None
    last_status_check_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PostOut(ORMModel):
    id: str
    title: str
    description: str
    hashtags: list[str] = Field(default_factory=list)
    media_asset_id: str | None = None
    thumbnail_media_id: str | None = None
    series_id: str | None = None
    episode_number: int | None = None
    language: str
    internal_notes: str | None = None
    template_id: str | None = None
    created_at: datetime
    updated_at: datetime
    targets: list[PostTargetOut] = Field(default_factory=list)


class PostCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    media_asset_id: str | None = None
    thumbnail_media_id: str | None = None
    series_id: str | None = None
    episode_number: int | None = None
    language: str = "fr"
    internal_notes: str | None = None
    account_ids: list[str] = Field(default_factory=list)
    per_platform: dict[str, dict[str, Any]] = Field(default_factory=dict)


class PostPatch(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    description: str | None = None
    hashtags: list[str] | None = None
    media_asset_id: str | None = None
    thumbnail_media_id: str | None = None
    series_id: str | None = None
    episode_number: int | None = None
    language: str | None = None
    internal_notes: str | None = None
    account_ids: list[str] | None = None
    per_platform: dict[str, dict[str, Any]] | None = None
    propagate_metadata: bool = False


class ScheduleRequest(BaseModel):
    scheduled_at: datetime

    @field_validator("scheduled_at")
    @classmethod
    def _tz_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("scheduled_at doit inclure un fuseau horaire (UTC recommandé).")
        return value


class BatchScheduleRequest(BaseModel):
    media_ids: list[str] = Field(min_length=1)
    account_ids: list[str] = Field(min_length=1)
    days: list[date] = Field(min_length=1)
    times: list[dtime] = Field(min_length=1)
    template_id: str | None = None
    per_platform: dict[str, dict[str, Any]] = Field(default_factory=dict)
    title_prefix: str = ""
    stagger_minutes: int = Field(default=0, ge=0, le=240)


class ResolveUncertainRequest(BaseModel):
    resolution: Literal["published", "failed", "retry"]
    remote_url: str | None = None


class AssistedCompletionRequest(BaseModel):
    remote_url: str = Field(min_length=3, max_length=600)
    status: Literal["published", "published_private"] = "published"
    published_at: datetime | None = None


class TemplateOut(ORMModel):
    id: str
    name: str
    description: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    from_post_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Automatisations / paramètres
# --------------------------------------------------------------------------
class WatchedFolderOut(ORMModel):
    id: str
    path: str
    enabled: bool
    create_draft: bool
    template_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    recursive: bool
    last_scan_at: datetime | None = None
    last_error: str | None = None


class WatchedFolderCreate(BaseModel):
    path: str = Field(min_length=1, max_length=600)
    enabled: bool = True
    create_draft: bool = True
    template_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    recursive: bool = False


class IngestRequest(BaseModel):
    """API locale pour Studio IA : chemin du fichier + métadonnées."""

    path: str | None = None
    filename: str | None = None
    title: str | None = Field(default=None, max_length=300)
    description: str | None = None
    language: str = "fr"
    series: str | None = None
    episode: int | None = None
    tags: list[str] = Field(default_factory=list)
    create_draft: bool = True


class SettingsOut(BaseModel):
    config: dict[str, Any]
    integrations: dict[str, Any]
    preferences: dict[str, Any]


class SchedulerStatusOut(BaseModel):
    running: bool
    worker_id: str
    started_at: str | None = None
    tick_seconds: int
    scheduled_count: int
    waiting_user_count: int
    uncertain_count: int
    late_count: int
    next_run_at: str | None = None
    last_error: str | None = None
    last_tick: dict[str, Any] | None = None
