import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { addDays, addMonths, eachDayOfInterval, endOfMonth, endOfWeek, format, isSameDay, isSameMonth, parseISO, startOfMonth, startOfWeek } from 'date-fns'
import { fr } from 'date-fns/locale'
import { ChevronLeft, ChevronRight, LayoutList } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '../components/AppShell'
import PlatformIcon from '../components/PlatformIcon'
import StatusBadge from '../components/StatusBadge'
import { Button, Card, EmptyState, ErrorState, Spinner } from '../components/ui'
import { api, params } from '../lib/api'
import { formatDateTime, formatTime } from '../lib/format'
import { useToasts } from '../hooks/useToasts'
import type { CalendarEntry } from '../lib/types'

type View = 'month' | 'week' | 'day' | 'list'

interface CalendarResponse { items: CalendarEntry[]; by_day: Record<string, CalendarEntry[]>; timezone: string }

export default function Calendar() {
  const [view, setView] = useState<View>('month')
  const [cursor, setCursor] = useState(() => new Date())
  const [dragging, setDragging] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const { notify } = useToasts()

  const range = useMemo(() => {
    if (view === 'month') return { start: startOfMonth(cursor), end: endOfMonth(cursor) }
    if (view === 'week') return { start: startOfWeek(cursor, { weekStartsOn: 1 }), end: endOfWeek(cursor, { weekStartsOn: 1 }) }
    return { start: cursor, end: cursor }
  }, [cursor, view])

  const query = useQuery({
    queryKey: ['calendar', format(range.start, 'yyyy-MM-dd'), format(range.end, 'yyyy-MM-dd')],
    queryFn: () =>
      api.get<CalendarResponse>(
        `/api/calendar${params({ start: format(range.start, 'yyyy-MM-dd'), end: format(range.end, 'yyyy-MM-dd') })}`,
      ),
  })

  const move = useMutation({
    mutationFn: ({ id, iso }: { id: string; iso: string }) => api.post(`/api/calendar/targets/${id}/move`, { scheduled_at: iso }),
    onSuccess: () => {
      notify('Publication déplacée (données conservées)', 'success')
      queryClient.invalidateQueries({ queryKey: ['calendar'] })
      queryClient.invalidateQueries({ queryKey: ['posts'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: (error) => notify(error.message, 'error'),
  })

  const days = useMemo(() => {
    if (view === 'list') return []
    const gridStart = startOfWeek(range.start, { weekStartsOn: 1 })
    const gridEnd = endOfWeek(range.end, { weekStartsOn: 1 })
    return eachDayOfInterval({ start: gridStart, end: gridEnd })
  }, [range, view])

  const shift = (direction: number) => {
    if (view === 'month') setCursor((current) => addMonths(current, direction))
    else setCursor((current) => addDays(current, direction * (view === 'week' ? 7 : 1)))
  }

  const dropOn = (day: Date) => {
    if (!dragging) return
    const entry = query.data?.items.find((item) => item.post_target_id === dragging)
    if (!entry?.scheduled_at) return
    const original = parseISO(entry.scheduled_at)
    const next = new Date(day)
    next.setHours(original.getHours(), original.getMinutes(), 0, 0)
    move.mutate({ id: dragging, iso: next.toISOString() })
    setDragging(null)
  }

  if (query.isLoading) return <Spinner label="Chargement du calendrier…" />
  if (query.error) return <ErrorState error={query.error} onRetry={() => query.refetch()} />

  return (
    <div>
      <PageHeader
        title="Calendrier éditorial"
        description="Glissez-déposez une publication pour changer son horaire. Les instants sont stockés en UTC, affichés en Europe/Paris."
        actions={
          <>
            <div className="flex items-center gap-1">
              <Button onClick={() => shift(-1)} aria-label="Période précédente"><ChevronLeft size={16} /></Button>
              <span className="min-w-[160px] text-center text-sm font-medium capitalize">{format(cursor, 'MMMM yyyy', { locale: fr })}</span>
              <Button onClick={() => shift(1)} aria-label="Période suivante"><ChevronRight size={16} /></Button>
            </div>
            <Button onClick={() => setCursor(new Date())}>Aujourd’hui</Button>
            <div className="flex rounded-lg border border-line">
              {(['month', 'week', 'day', 'list'] as View[]).map((item) => (
                <button
                  key={item}
                  className={`px-3 py-2 text-sm ${view === item ? 'bg-brand-600/20 text-brand-200' : 'text-ink-muted hover:text-ink'}`}
                  onClick={() => setView(item)}
                >
                  {item === 'month' ? 'Mois' : item === 'week' ? 'Semaine' : item === 'day' ? 'Jour' : 'Liste'}
                </button>
              ))}
            </div>
          </>
        }
      />

      {query.data!.items.length === 0 && (
        <EmptyState
          title="Aucune publication sur cette période"
          description="Programmez une publication depuis le compositeur : elle apparaîtra immédiatement ici."
          action={<Link className="btn-primary" to="/posts/new"><LayoutList size={16} /> Ouvrir le compositeur</Link>}
        />
      )}

      {view !== 'list' && query.data!.items.length > 0 && (
        <div className="card grid grid-cols-7 overflow-hidden">
          {['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'].map((label) => (
            <div key={label} className="border-b border-line bg-surface-subtle px-2 py-2 text-center text-xs font-medium text-ink-muted">{label}</div>
          ))}
          {days.map((day) => {
            const entries = (query.data!.items ?? []).filter((item) => item.scheduled_at && isSameDay(parseISO(item.scheduled_at), day))
            const outside = !isSameMonth(day, range.start)
            return (
              <div
                key={day.toISOString()}
                onDragOver={(event) => event.preventDefault()}
                onDrop={() => dropOn(day)}
                className={`min-h-[120px] border-b border-r border-line p-2 ${outside ? 'opacity-40' : ''}`}
              >
                <p className="mb-1 text-xs text-ink-faint">{format(day, 'd', { locale: fr })}</p>
                <div className="space-y-1">
                  {entries.map((entry) => (
                    <article
                      key={entry.post_target_id}
                      draggable
                      onDragStart={() => setDragging(entry.post_target_id)}
                      onDragEnd={() => setDragging(null)}
                      className={`cursor-grab rounded-lg border border-line bg-surface px-2 py-1 text-xs hover:border-brand-500 ${dragging === entry.post_target_id ? 'opacity-50' : ''}`}
                    >
                      <div className="flex items-center gap-1">
                        <PlatformIcon platform={entry.platform} size={12} />
                        <span className="font-medium">{formatTime(entry.scheduled_at)}</span>
                        {entry.requires_user_action && <span className="ml-auto text-amber-400">!</span>}
                      </div>
                      <p className="truncate text-ink-muted">{entry.account_name}</p>
                      <StatusBadge status={entry.status} />
                    </article>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {view === 'list' && (
        <Card title="File d’attente et publications">
          <ul className="divide-y divide-line">
            {query.data!.items.map((entry) => (
              <li key={entry.post_target_id} className="flex items-center gap-3 py-2">
                {entry.thumbnail ? <img src={entry.thumbnail} alt="" className="h-10 w-10 rounded object-cover" /> : <PlatformIcon platform={entry.platform} />}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{entry.title}</p>
                  <p className="text-xs text-ink-muted">{entry.account_name} · {formatDateTime(entry.scheduled_at)}</p>
                </div>
                <StatusBadge status={entry.status} />
                <Link className="btn-ghost" to={`/posts/${entry.post_id}`}>Ouvrir</Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
