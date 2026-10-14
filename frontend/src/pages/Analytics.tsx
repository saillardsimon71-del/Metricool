import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid, Legend } from 'recharts'
import { PageHeader } from '../components/AppShell'
import { Button, Card, EmptyState, ErrorState, Field, Select, Spinner } from '../components/ui'
import { api, params } from '../lib/api'
import { useToasts } from '../hooks/useToasts'
import type { Account } from '../lib/types'

interface Point { date: string; account_id: string; metric: string; value: number }
interface RankItem { account: string | null; platform: string | null; title: string | null; date: string; value: number; demo: boolean }

export default function Analytics() {
  const [metric, setMetric] = useState('views')
  const [accountFilter, setAccountFilter] = useState('')
  const queryClient = useQueryClient()
  const { notify } = useToasts()

  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api.get<Account[]>('/api/accounts') })
  const definitions = useQuery({ queryKey: ['metric-definitions'], queryFn: () => api.get<{ by_platform: Record<string, { key: string; label: string; definition: string }[]> }>('/api/stats/metrics') })
  const series = useQuery({
    queryKey: ['stats-series', metric, accountFilter],
    queryFn: () => api.get<{ points: Point[] }>(`/api/stats/series${params({ metric, account_id: accountFilter || undefined })}`),
  })
  const ranking = useQuery({
    queryKey: ['stats-ranking', metric, accountFilter],
    queryFn: () => api.get<{ items: RankItem[] }>(`/api/stats/ranking${params({ metric, account_id: accountFilter || undefined, limit: 25 })}`),
  })

  const collect = useMutation({
    mutationFn: () => api.post<{ targets: number; samples_stored: number }>('/api/stats/collect'),
    onSuccess: (result) => {
      notify(`${result.samples_stored} relevé(s) enregistré(s) sur ${result.targets} publication(s)`, 'success')
      queryClient.invalidateQueries({ queryKey: ['stats-series'] })
      queryClient.invalidateQueries({ queryKey: ['stats-ranking'] })
    },
    onError: (error) => notify(error.message, 'error'),
  })

  const chartData = (series.data?.points ?? []).map((point) => {
    const account = accounts.data?.find((item) => item.id === point.account_id)
    return { date: point.date, compte: account?.display_name ?? point.account_id.slice(0, 6), value: point.value }
  })

  return (
    <div>
      <PageHeader
        title="Statistiques"
        description="Uniquement les métriques réellement renvoyées par les API. Une case vide signifie « donnée non fournie », jamais une estimation."
        actions={
          <>
            <Button onClick={() => collect.mutate()} loading={collect.isPending}><RefreshCw size={16} /> Rapatrier</Button>
            <a className="btn-ghost" href="/api/stats/export.csv"><Download size={16} /> CSV</a>
            <a className="btn-ghost" href="/api/stats/export.json"><Download size={16} /> JSON</a>
          </>
        }
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Métrique">
          <Select value={metric} onChange={(event) => setMetric(event.target.value)}>
            <option value="views">Vues</option>
            <option value="likes">Mentions J’aime</option>
            <option value="comments">Commentaires</option>
            <option value="shares">Partages</option>
            <option value="reach">Portée</option>
            <option value="saved">Enregistrements</option>
          </Select>
        </Field>
        <Field label="Compte">
          <Select value={accountFilter} onChange={(event) => setAccountFilter(event.target.value)}>
            <option value="">Tous les comptes</option>
            {(accounts.data ?? []).map((account) => <option key={account.id} value={account.id}>{account.display_name}</option>)}
          </Select>
        </Field>
      </div>

      {series.isLoading && <Spinner label="Chargement des statistiques…" />}
      {series.error && <ErrorState error={series.error} onRetry={() => series.refetch()} />}

      {series.data && series.data.points.length === 0 ? (
        <EmptyState
          title="Aucune donnée disponible"
          description="Les métriques apparaissent après publication et rapatriement. TikTok ne fournit pas de statistiques via la Content Posting API : cette colonne restera vide, c’est attendu."
        />
      ) : (
        <Card title={`Évolution — ${metric}`}>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.15} />
                <XAxis dataKey="date" stroke="currentColor" fontSize={11} />
                <YAxis stroke="currentColor" fontSize={11} />
                <Tooltip contentStyle={{ background: '#111a2e', border: '1px solid #1f2b45', borderRadius: 8 }} />
                <Legend />
                <Line type="monotone" dataKey="value" stroke="#3383fb" strokeWidth={2} dot={false} name={metric} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      <Card title="Classement" className="mt-4">
        {(ranking.data?.items ?? []).length === 0 ? (
          <p className="text-sm text-ink-muted">Aucun relevé pour cette métrique.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-ink-muted">
                <th className="py-2">Publication</th><th>Compte</th><th>Plateforme</th><th>Date</th><th className="text-right">{metric}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(ranking.data?.items ?? []).map((item, index) => (
                <tr key={`${item.title}-${item.date}-${index}`}>
                  <td className="py-2">{item.title ?? '—'}</td>
                  <td>{item.account}</td>
                  <td>{item.platform}{item.demo && <span className="chip ml-1">démo</span>}</td>
                  <td>{item.date}</td>
                  <td className="text-right font-medium">{item.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="Définitions par plateforme" className="mt-4">
        <div className="grid gap-3 md:grid-cols-2">
          {Object.entries(definitions.data?.by_platform ?? {}).map(([platform, metrics]) => (
            <div key={platform}>
              <p className="mb-1 text-sm font-medium capitalize">{platform}</p>
              <ul className="space-y-0.5 text-xs text-ink-muted">
                {metrics.map((item) => <li key={item.key}><strong>{item.label}</strong> — {item.definition}</li>)}
                {metrics.length === 0 && <li className="text-ink-faint">Aucune métrique exposée par cette API.</li>}
              </ul>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
