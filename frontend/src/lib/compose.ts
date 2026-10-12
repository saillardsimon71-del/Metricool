/** Logique de composition multiplateforme — partagée et testable. */

import type { Account } from './types'

export interface CommonMetadata { title: string; description: string; hashtags: string[]; language: string }

export const LIMITS = {
  youtubeTitle: 100,
  youtubeDescription: 5000,
  instagramCaption: 2200,
  tiktokCaption: 2200,
  youtubeTags: 30,
} as const

export const parseTags = (value: string): string[] =>
  value.split(/[\s,]+/).map((tag) => tag.replace(/^#/, '').trim()).filter(Boolean)

const tagLine = (hashtags: string[]): string => hashtags.map((tag) => (tag.startsWith('#') ? tag : `#${tag}`)).join(' ')

/** Génère la variante d'une plateforme à partir des métadonnées communes.
 * Seuls les champs réellement acceptés par l'API sont produits. */
export const buildVariant = (platform: string, common: CommonMetadata): Record<string, unknown> => {
  const tags = tagLine(common.hashtags)
  if (platform === 'youtube') {
    return {
      title: common.title.slice(0, LIMITS.youtubeTitle),
      description: `${common.description}\n\n${tags}`.trim().slice(0, LIMITS.youtubeDescription),
      tags: common.hashtags.map((tag) => tag.replace('#', '')).slice(0, LIMITS.youtubeTags),
      privacy: 'private',
      category_id: '',
      language: common.language,
      made_for_kids: false,
      embeddable: true,
      contains_synthetic_media: false,
    }
  }
  if (platform === 'instagram') {
    return { caption: `${common.description}\n\n${tags}`.trim().slice(0, LIMITS.instagramCaption), share_to_feed: true, thumb_offset_ms: 1000 }
  }
  if (platform === 'tiktok') {
    return {
      caption: `${common.description} ${tags}`.trim().slice(0, LIMITS.tiktokCaption),
      privacy: 'SELF_ONLY',
      disable_comment: false,
      disable_duet: false,
      disable_stitch: false,
      is_aigc: false,
      video_cover_timestamp_ms: 1000,
      mode: 'direct',
    }
  }
  return { caption: `${common.description} ${tags}`.trim().slice(0, 4000) }
}

export const groupVariantsByPlatform = (accounts: Account[], variants: Record<string, Record<string, unknown>>): Record<string, Record<string, unknown>> => {
  const grouped: Record<string, Record<string, unknown>> = {}
  for (const account of accounts) grouped[account.platform] = variants[account.id] ?? {}
  return grouped
}

export const toggleAll = (accounts: Account[], current: Record<string, boolean>): Record<string, boolean> => {
  const allSelected = accounts.length > 0 && accounts.every((account) => current[account.id])
  return Object.fromEntries(accounts.map((account) => [account.id, !allSelected]))
}

export const variantLabel = (platform: string): string =>
  ({ youtube: 'YouTube', instagram: 'Instagram Reels', tiktok: 'TikTok', demo: 'Démonstration' })[platform] ?? platform
