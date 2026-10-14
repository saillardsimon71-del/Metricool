import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CalendarDays, CheckCircle2, Clock, Images, Plus, RefreshCw, Upload, Users } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { Card, EmptyState, ErrorState, Spinner, Button } from '../components/ui'
import { PageHeader } from '../components/AppShell'
import PlatformIcon from '../components/PlatformIcon'
import StatusBadge from '../components/StatusBadge'
import { api } from '../lib/api'
import { formatRelative } from '../lib/format'
import { useToasts } from '../hooks/useToasts'
import type { Account, Dashboard as DashboardData, PostStatus } from '../lib/types'

const tiles: { key: keyof DashboardData; label: string; Icon: typeof Clock; tone?: string }[] = [
  { key: 'accounts_connected', label: 'Comptes connectés', Icon: Users },
  { key: 'scheduled', label: 'Programmées', Icon: Clock },
  { key: 'posts_today', label: 'Aujourd’hui', Icon: CalendarDays },
  { key: 'published', label: 'Publiées', Icon: CheckCircle2, tone: 'text-emerald-400' },
  { key: 'failed', label: 'Échecs', Icon: AlertTriangle, tone: 'text-red-400' },
  { key: 'waiting_for_user', label: 'Action humaine', Icon: AlertTriangle, tone: 'text-amber-400' },
  { key: 'drafts', label: 'Brouillons', Icon: Images },
  { key: 'media_count', label: 'Médias en bibliothèque', Icon: Images },
]

export default function Dashboard() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { notify } = useToasts()
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: () => api.get<DashboardData>('/api/dashboard') })
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api.get<Account[]>('/api/accounts') })

  const seedDemo = useMutation({
    mutationFn: () => api.post<Account[]>('/api/accounts/demo/seed'),
    onSuccess: (created) => {
      notify(`${created.length} comptes de démonstration prêts`, 'success')
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: (error) => notify(error.message, 'error'),
  })

  const tick = useMutation({
    mutationFn: () => api.post<{ executed: number; due: number }>('/api/scheduler/tick'),
    onSuccess: (result) => {
      notify(`Cycle exécuté : ${result.executed}/${result.due} publication(s) traitée(s)`, 'success')
      queryClient.invalidateQueries()
    },
    onError: (error) => notify(error.message, 'error'),
  })

  if (dashboard.isLoading) return <Spinner label="Chargement du tableau de bord…" />
  if (dashboard.error) return <ErrorState error={dashboard.error} onRetry={() => dashboard.refetch()} />
  const data = dashboard.data!

  return (
    <div>
      <PageHeader
        title="Tableau de bord"
        description="Vue d’ensemble de vos comptes, publications et du moteur de programmation local."
        actions={
          <>
            <Button variant="primary" onClick={() => navigate('/posts/new')}><Plus size={16} /> Nouvelle publication</Button>
            <Button onClick={() => navigate('/library')}><Upload size={16} /> Importer une vidéo</Button>
            <Button onClick={() => navigate('/calendar')}><CalendarDays size={16} /> Calendrier</Button>
            <Button loading={seedDemo.isPending} onClick={() => seedDemo.mutate()}><Users size={16} /> Comptes démo</Button>
            <Button loading={tick.isPending} onClick={() => tick.mutate()}><RefreshCw size={16} /> Lancer un cycle</Button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {tiles.map(({ key, label, Icon, tone }) => (
          <div key={String(key)} className="card p-4">
            <div className="flex items-center justify-between">
              <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
              <Icon size={16} className={tone ?? 'text-ink-faint'} />
            </div>
            <p className={`mt-2 text-2xl font-semibold ${tone ?? ''}`}>{String(data[key] ?? 0)}</p>
          </div>
        ))}
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        <Card title="Prochaines publications" className="lg:col-span-2">
          {data.upcoming.length === 0 ? (
            <EmptyState
              title="Rien de programmé"
              description="Préparez une vidéo puis choisissez vos comptes : les six publications apparaîtront ici."
              action={<Button variant="primary" onClick={() => navigate('/posts/new')}>Créer une publication</Button>}
            />
          ) : (
            <ul className="divide-y divide-line">
              {data.upcoming.map((item) => (
                <li key={item.post_target_id} className="flex items-center gap-3 py-2">
                  <PlatformIcon platform={item.platform} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{item.title ?? 'Sans titre'}</p>
                    <p className="text-xs text-ink-muted">{item.account} · {formatRelative(item.scheduled_at)}</p>
                  </div>
                  <StatusBadge status={item.status as PostStatus} />
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Comptes" actions={<Link className="text-xs text-brand-400 hover:underline" to="/accounts">Gérer</Link>}>
          {(accounts.data ?? []).length === 0 ? (
            <EmptyState title="Aucun compte" description="Connectez vos comptes réels ou créez six comptes de démonstration." />
          ) : (
            <ul className="space-y-2">
              {(accounts.data ?? []).map((account) => (
                <li key={account.id} className="flex items-center gap-3 rounded-lg border border-line px-3 py-2">
                  <PlatformIcon platform={account.platform} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{account.display_name}</p>
                    <p className="text-xs text-ink-muted">{account.mode === 'demo' ? 'Démonstration locale' : account.status}</p>
                  </div>
                  {account.capabilities?.publish_public === false && (
                    <span className="chip" title={(account.capabilities?.restrictions ?? []).join(' · ')}>Public : non</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {data.uncertain > 0 && (
        <div className="mt-4 rounded-xl border border-orange-500/40 bg-orange-500/10 p-4 text-sm text-orange-200">
          <strong>{data.uncertain} publication(s) au statut incertain.</strong> SocialDock ne relance jamais automatiquement une
          publication ambiguë : vérifiez la plateforme, puis tranchez dans la page Publications.
        </div>
      )}
    </div>
  )
}
