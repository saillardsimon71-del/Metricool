import { describe, expect, it } from 'vitest'
import { formatBytes, formatDateTime, formatDuration, formatTime, fromLocalInput, toLocalInput } from '../format'

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
  it.each([
    ['2027-01-15T08:30:00.000Z', '2027-01-15T09:30'],
    ['2027-07-15T07:30:00.000Z', '2027-07-15T09:30'],
    ['2027-03-28T01:30:00.000Z', '2027-03-28T03:30'],
  ])('convertit %s dans le fuseau Europe/Paris', (iso, local) => {
    expect(toLocalInput(iso)).toBe(local)
    expect(fromLocalInput(local)).toBe(iso)
  })

  it('affiche les horaires à Paris quel que soit le fuseau du navigateur', () => {
    expect(formatTime('2027-07-15T07:30:00Z')).toBe('09:30')
    expect(formatDateTime('2027-07-15T07:30:00Z')).toContain('09:30')
  })

  it('refuse une heure inexistante au passage à l\'heure d\'été', () => {
    expect(() => fromLocalInput('2027-03-28T02:30')).toThrow()
  })

  it('choisit la première occurrence lors du passage à l\'heure d\'hiver', () => {
    expect(fromLocalInput('2027-10-31T02:30')).toBe('2027-10-31T00:30:00.000Z')
  })

  it('préserve la seconde occurrence si l\'horaire existant est inchangé', () => {
    expect(fromLocalInput('2027-10-31T02:30', '2027-10-31T01:30:00Z')).toBe('2027-10-31T01:30:00.000Z')
  })

  it('préserve l’instant lors de l’aller-retour', () => {
    const iso = '2026-03-29T01:30:00.000Z' // nuit du changement d’heure en Europe/Paris
    const local = toLocalInput(iso)
    expect(fromLocalInput(local)).toBe(iso)
  })
})
