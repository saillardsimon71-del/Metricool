import { describe, expect, it } from 'vitest'
import { formatBytes, formatDuration, fromLocalInput, toLocalInput } from '../format'

describe('formatBytes', () => {
  it('utilise les unités françaises', () => {
    expect(formatBytes(0)).toBe('0 o')
    expect(formatBytes(950)).toBe('950 o')
    expect(formatBytes(1_500_000)).toBe('1.5 Mo')
    expect(formatBytes(2_500_000_000)).toBe('2.5 Go')
  })
})

describe('formatDuration', () => {
  it('affiche minutes:secondes', () => {
    expect(formatDuration(65)).toBe('1:05')
    expect(formatDuration(null)).toBe('—')
  })
})

describe('conversion des horaires', () => {
  it('préserve l’instant lors de l’aller-retour', () => {
    const iso = '2026-03-29T01:30:00.000Z' // nuit du changement d’heure en Europe/Paris
    const local = toLocalInput(iso)
    expect(fromLocalInput(local)).toBe(iso)
  })
})
