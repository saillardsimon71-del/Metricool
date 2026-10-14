import { describe, expect, it } from 'vitest'
import { buildVariant, groupVariantsByPlatform, LIMITS, parseTags, toggleAll } from '../compose'
import type { Account } from '../types'

const common = { title: 'Ma vidéo', description: 'Une description commune', hashtags: ['shorts', 'ia'], language: 'fr' }

const account = (id: string, platform: string): Account =>
  ({ id, platform, display_name: id, mode: 'demo', status: 'demo', extra: {}, capabilities: {}, permissions_missing: [], scopes: [] } as unknown as Account)

describe('parseTags', () => {
  it('accepte espaces, virgules et dièses', () => {
    expect(parseTags('#shorts, ia  vertical')).toEqual(['shorts', 'ia', 'vertical'])
  })

  it('renvoie une liste vide pour une saisie vide', () => {
    expect(parseTags('   ')).toEqual([])
  })
})

describe('buildVariant', () => {
  it('produit une variante YouTube conforme aux limites API', () => {
    const variant = buildVariant('youtube', common)
    expect(variant.title).toBe('Ma vidéo')
    expect(String(variant.description)).toContain('#shorts #ia')
    expect(variant.tags).toEqual(['shorts', 'ia'])
    expect(variant.privacy).toBe('private') // jamais « public » par défaut : audit requis
    expect(String(variant.description).length).toBeLessThanOrEqual(LIMITS.youtubeDescription)
  })

  it('produit une légende Instagram dans la limite de 2200 caractères', () => {
    const variant = buildVariant('instagram', { ...common, description: 'x'.repeat(3000) })
    expect(String(variant.caption).length).toBeLessThanOrEqual(LIMITS.instagramCaption)
    expect(variant.share_to_feed).toBe(true)
  })

  it('produit une variante TikTok privée par défaut', () => {
    const variant = buildVariant('tiktok', common)
    expect(variant.privacy).toBe('SELF_ONLY')
    expect(String(variant.caption)).toContain('#shorts')
    expect(variant.mode).toBe('direct')
  })

  it('tronque un titre YouTube à 100 caractères', () => {
    const variant = buildVariant('youtube', { ...common, title: 't'.repeat(250) })
    expect(String(variant.title)).toHaveLength(LIMITS.youtubeTitle)
  })
})

describe('groupVariantsByPlatform', () => {
  it('regroupe par plateforme pour l’envoi à l\'API', () => {
    const accounts = [account('a1', 'tiktok'), account('a2', 'tiktok'), account('i1', 'instagram')]
    const variants = { a1: { caption: 'un' }, a2: { caption: 'deux' }, i1: { caption: 'ig' } }
    expect(groupVariantsByPlatform(accounts, variants)).toEqual({ tiktok: { a1: { caption: 'un' }, a2: { caption: 'deux' } }, instagram: { i1: { caption: 'ig' } } })
  })

  it('maintient les variantes indépendantes par compte m%C3%Aame plateforme', () => {
    const accounts = [account('tiktok-1', 'tiktok'), account('tiktok-2', 'tiktok')]
    const variants = { 'tiktok-1': { description: 'Description du compte 1' }, 'tiktok-2': { description: 'Description du compte 2' } }
    const result = groupVariantsByPlatform(accounts, variants)
    expect(result).toEqual({ tiktok: { 'tiktok-1': { description: 'Description du compte 1' }, 'tiktok-2': { description: 'Description du compte 2' } } })
  })
})

describe('toggleAll', () => {
  it('sélectionne tout puis désélectionne tout', () => {
    const accounts = [account('a1', 'tiktok'), account('a2', 'instagram')]
    const first = toggleAll(accounts, {})
    expect(first).toEqual({ a1: true, a2: true })
    expect(toggleAll(accounts, first)).toEqual({ a1: false, a2: false })
  })
})
