import { format, formatDistanceToNow, parseISO } from 'date-fns'
import { fr } from 'date-fns/locale'

export const formatDateTime = (iso: string | null, tz = 'Europe/Paris'): string => {
  if (!iso) return '—'
  const date = parseISO(iso)
  return `${format(date, 'dd MMM yyyy HH:mm', { locale: fr })} (${tzShort(tz)})`
}

export const formatTime = (iso: string | null): string => (iso ? format(parseISO(iso), 'HH:mm') : '—')

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
  const date = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export const fromLocalInput = (value: string): string => new Date(value).toISOString()
