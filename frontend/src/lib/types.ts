/** Types partagés — reflètent les schémas Pydantic du backend. */

export type Platform = 'youtube' | 'instagram' | 'tiktok' | 'demo'

export type PostStatus =
  | 'draft' | 'ready' | 'scheduled' | 'waiting_for_user' | 'uploading'
  | 'processing' | 'publishing' | 'published' | 'published_private'
  | 'failed' | 'uncertain' | 'cancelled'

export interface Capabilities {
  platform: string
  label: string
  auth_available: boolean
  publish_video: boolean
  publish_public: boolean
  scheduling: boolean
  upload: boolean
  analytics: boolean
  assisted_mode: boolean
  requires_review: boolean
  restrictions: string[]
  permissions_required: string[]
  permissions_missing: string[]
}

export interface Account {
  id: string
  platform: Platform
  display_name: string
  external_id: string | null
  username: string | null
  avatar_url: string | null
  mode: 'real' | 'demo'
  status: string
  scopes: string[]
  capabilities: Capabilities | Record<string, never>
  permissions_missing: string[]
  default_privacy: string | null
  default_category_id: string | null
  extra: Record<string, unknown>
  is_favorite: boolean
  group_id: string | null
  last_verified_at: string | null
  credentials_expire_at: string | null
  last_error: string | null
}

export interface Media {
  id: string
  stored_path: string
  original_name: string
  display_name: string
  kind: 'video' | 'image'
  mime_type: string | null
  size_bytes: number
  sha256: string
  duration_seconds: number | null
  width: number | null
  height: number | null
  fps: number | null
  video_codec: string | null
  audio_codec: string | null
  has_audio: boolean
  probe_status: 'ok' | 'unavailable' | 'failed'
  probe_error: string | null
  thumbnail_path: string | null
  tags: string[]
  collections: string[]
  imported_from: string | null
  notes: string | null
  created_at: string
}

export interface MediaValidation {
  platform: string
  platform_label: string
  ok: boolean
  issues: { key: string; label: string; message: string }[]
  warnings: { key: string; label: string; message: string }[]
  info: { key: string; label: string; message: string }[]
  notes: string[]
  caption_limit: number
  ratio: string | null
  probe_status: string
}

export interface PostTarget {
  id: string
  post_id: string
  account_id: string
  status: PostStatus
  scheduled_at: string | null
  published_at: string | null
  payload: Record<string, unknown>
  idempotency_key: string
  remote_id: string | null
  remote_url: string | null
  attempts_count: number
  next_retry_at: string | null
  error_message: string | null
  error_code: string | null
  requires_user_action: boolean
  user_action_hint: string | null
  last_status_check_at: string | null
  created_at: string
  updated_at: string
}

export interface Post {
  id: string
  title: string
  description: string
  hashtags: string[]
  media_asset_id: string | null
  thumbnail_media_id: string | null
  series_id: string | null
  episode_number: number | null
  language: string
  internal_notes: string | null
  template_id: string | null
  created_at: string
  updated_at: string
  targets: PostTarget[]
}

export interface CalendarEntry {
  post_target_id: string
  post_id: string
  title: string | null
  account_id: string
  account_name: string | null
  platform: Platform | null
  mode: 'real' | 'demo' | null
  status: PostStatus
  status_label: string
  scheduled_at: string | null
  published_at: string | null
  thumbnail: string | null
  remote_url: string | null
  requires_user_action: boolean
  error_message: string | null
}

export interface Dashboard {
  generated_at: string
  accounts_total: number
  accounts_connected: number
  accounts_needing_attention: number
  posts_today: number
  scheduled: number
  drafts: number
  ready: number
  published: number
  failed: number
  waiting_for_user: number
  uncertain: number
  late: number
  media_count: number
  attempts_total: number
  upcoming: { post_target_id: string; title: string | null; account: string | null; platform: string | null; scheduled_at: string | null; status: string }[]
  scheduler: SchedulerStatus
}

export interface SchedulerStatus {
  running: boolean
  worker_id: string
  started_at: string | null
  tick_seconds: number
  scheduled_count: number
  waiting_user_count: number
  uncertain_count: number
  late_count: number
  next_run_at: string | null
  last_error: string | null
  last_tick: Record<string, unknown> | null
}

export interface Diagnostics {
  product: string
  version: string
  generated_at: string
  python: { version: string; executable: string; platform: string }
  config: Record<string, unknown>
  database: { ok: boolean; journal_mode?: string; integrity?: string; tables?: number; error?: string }
  ffmpeg: { available: boolean; ffmpeg_path: string | null; ffprobe_path: string | null; probe_backend: string | null; version?: string | null }
  scheduler: SchedulerStatus
  disk: { total_gb?: number; free_gb?: number; used_percent?: number; error?: string }
  connectors: {
    platform: string; configured: boolean; publish_public_available: boolean; requires_review: boolean
    missing_configuration: string[]; restrictions: string[]; real_validation: string
    accounts: { id: string; name: string; status: string; mode: string; last_error: string | null; credentials_expire_at: string | null }[]
  }[]
  counts: Record<string, number>
  credentials_expiring_soon: { id: string; name: string; expires_at: string }[]
  recent_attempts: { attempt_no: number; phase: string; outcome: string; http_status: number | null; detail: string | null; started_at: string | null; post_target_id: string }[]
  last_errors: { message: string | null; source: string; created_at: string }[]
}

export interface Template { id: string; name: string; description: string | null; payload: Record<string, unknown>; created_at: string; updated_at: string }
export interface WatchedFolder { id: string; path: string; enabled: boolean; create_draft: boolean; template_id: string | null; tags: string[]; recursive: boolean; last_scan_at: string | null; last_error: string | null }
export interface Preferences { theme: 'dark' | 'light'; language: string; timezone: string; favorite_times: string[]; default_privacy: Record<string, string>; demo_mode: boolean; notifications_enabled: boolean }
export interface SettingsPayload { config: Record<string, unknown>; preferences: Preferences; integrations: { ingest_endpoint: string; ingest_token: string; studio_ai_docs: string; note: string } }
