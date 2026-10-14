import { formatDistanceToNow, parseISO } from 'date-fns'
import { fr } from 'date-fns/locale'

export const formatDateTime = (iso: string | null, tz = 'Europe/Paris'): string => {
  if (!iso) return '—'
  const date = parseISO(iso)
  return `${new Intl.DateTimeFormat('fr-FR', {
    timeZone: tz, day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(date)} (${tzShort(tz)})`
}

export const formatTime = (iso: string | null): string => (iso ? new Intl.DateTimeFormat('fr-FR', {
  timeZone: 'Europe/Paris', hour: '2-digit', minute: '2-digit',
}).format(parseISO(iso)) : '—')

export const formatRelative = (iso: string | null): string =>
  iso ? formatDistanceToNow(parseISO(iso), { addSuffix: true, locale: fr }) : '—'

export const formatBytes = (bytes: number): string => {
  if (!bytes) return '0 o'
  const units = ['o', 'Ko', 'Mo', 'Go', 'To']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1000)), units.length - 1)
  return `${(bytes / 1000 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

export const formatDuration = (seconds: number | null): string => {
  if (seconds === null || seconds === undefined) return '—'
  const total = Math.round(seconds)
  const minutes = Math.floor(total / 60)
  return `${minutes}:${String(total % 60).padStart(2, '0')}`
}

const tzShort = (tz: string): string => (tz === 'Europe/Paris' ? 'Paris' : tz.split('/')[1] ?? tz)

export const toLocalInput = (iso: string | null): string => {
  if (!iso) return ''
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Paris', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(iso))
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]))
  return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}`
}

export const fromLocalInput = (value: string, originalIso?: string | null): string => {
  if (originalIso && toLocalInput(originalIso) === value) return new Date(originalIso).toISOString()
  const wallTime = Date.parse(`${value}:00.000Z`)
  const candidates = new Set<number>()
  for (const days of [-1, 0, 1]) {
    const sample = wallTime + days * 86_400_000
    const offset = Date.parse(`${toLocalInput(new Date(sample).toISOString())}:00.000Z`) - sample
    const candidate = wallTime - offset
    if (toLocalInput(new Date(candidate).toISOString()) === value) candidates.add(candidate)
  }
  if (!candidates.size) throw new Error('Cette heure n\'existe pas dans le fuseau Europe/Paris.')
  return new Date(Math.min(...candidates)).toISOString()
}
