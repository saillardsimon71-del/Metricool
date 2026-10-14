import { useQuery } from '@tanstack/react-query'
import {
  Activity, BarChart3, CalendarDays, Cog, FolderSync, Gauge, Images, ListVideo, Moon, Plus, Sun, Users,
} from 'lucide-react'
import { useEffect } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { useTheme } from '../hooks/useTheme'
import type { SchedulerStatus } from '../lib/types'

const links = [
  { to: '/dashboard', label: 'Tableau de bord', Icon: Gauge, shortcut: '1' },
  { to: '/calendar', label: 'Calendrier', Icon: CalendarDays, shortcut: '2' },
  { to: '/posts', label: 'Publications', Icon: ListVideo, shortcut: '3' },
  { to: '/library', label: 'Bibliothèque', Icon: Images, shortcut: '4' },
  { to: '/accounts', label: 'Comptes', Icon: Users, shortcut: '5' },
  { to: '/analytics', label: 'Statistiques', Icon: BarChart3, shortcut: '6' },
  { to: '/automations', label: 'Automatisations', Icon: FolderSync, shortcut: '7' },
  { to: '/settings', label: 'Paramètres', Icon: Cog, shortcut: '8' },
  { to: '/diagnostics', label: 'Diagnostics', Icon: Activity, shortcut: '9' },
]

export default function AppShell() {
  const { theme, toggle } = useTheme()
  const navigate = useNavigate()
  const { data: scheduler } = useQuery({
    queryKey: ['scheduler-status'],
    queryFn: () => api.get<SchedulerStatus>('/api/scheduler/status'),
    refetchInterval: 10_000,
  })

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
      if (event.altKey) {
        const link = links.find((item) => item.shortcut === event.key)
        if (link) {
          event.preventDefault()
          navigate(link.to)
        }
      }
      if (event.key.toLowerCase() === 'n' && !event.metaKey && !event.ctrlKey) {
        event.preventDefault()
        navigate('/posts/new')
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [navigate])

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-line bg-surface-elevated">
        <div className="flex items-center gap-2 px-4 py-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white">S</div>
          <div>
            <p className="text-sm font-semibold leading-tight">SocialDock</p>
            <p className="text-[11px] text-ink-faint">Local · hors SaaS</p>
          </div>
        </div>
        <nav className="flex-1 space-y-1 px-2">
          {links.map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
                  isActive ? 'bg-brand-600/15 text-brand-200' : 'text-ink-muted hover:bg-surface-subtle hover:text-ink'
                }`
              }
            >
              <Icon size={16} />
              <span className="flex-1">{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="space-y-2 border-t border-line p-3">
          <SchedulerPill status={scheduler} />
          <button className="btn-ghost w-full justify-center" onClick={toggle} aria-label="Basculer le thème">
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            {theme === 'dark' ? 'Mode clair' : 'Mode sombre'}
          </button>
          <p className="text-center text-[11px] text-ink-faint">Alt+1…9 · N = nouvelle publication</p>
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-6">
        <Outlet />
      </main>
    </div>
  )
}

function SchedulerPill({ status }: { status?: SchedulerStatus }) {
  const running = status?.running ?? false
  return (
    <div className="rounded-lg border border-line px-3 py-2 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-ink-muted">Moteur de programmation</span>
        <span className={`h-2 w-2 rounded-full ${running ? 'bg-emerald-400' : 'bg-red-400'}`} aria-hidden />
      </div>
      <p className="mt-1 text-ink-faint">
        {running
          ? `${status?.scheduled_count ?? 0} programmée(s) · ${status?.waiting_user_count ?? 0} action(s) requise(s)`
          : 'Arrêté — les publications ne partiront pas'}
      </p>
    </div>
  )
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-ink-muted">{description}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">{actions}</div>
    </header>
  )
}

export { Plus }
