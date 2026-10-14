import { useQuery } from '@tanstack/react-query'
import { Activity, Download, FileText } from 'lucide-react'
import { PageHeader } from '../components/AppShell'
import { Button, Card, ErrorState, Spinner } from '../components/ui'
import { api } from '../lib/api'
import { formatRelative } from '../lib/format'
import type { Diagnostics as DiagnosticsData } from '../lib/types'

const indicator = (ok: boolean) => (
  <span className={`inline-block h-2 w-2 rounded-full ${ok ? 'bg-emerald-400' : 'bg-red-400'}`} aria-hidden />
)

export default function Diagnostics() {
  const report = useQuery({ queryKey: ['diagnostics'], queryFn: () => api.get<DiagnosticsData>('/api/diagnostics'), refetchInterval: 15_000 })
  const logs = useQuery({ queryKey: ['diagnostics-logs'], queryFn: () => api.get<{ items: { id: string; level: string; source: string; message: string; created_at: string }[] }>('/api/diagnostics/logs?limit=40') })

  if (report.isLoading) return <Spinner label="Collecte des diagnostics…" />
  if (report.error) return <ErrorState error={report.error} onRetry={() => report.refetch()} />
  const data = report.data!

  return (
    <div>
      <PageHeader
        title="Diagnostics"
        description="Tout ce qu’il faut pour comprendre un problème sans lire de code. Les secrets ne sont jamais affichés."
        actions={<a className="btn-ghost" href="/api/diagnostics/report.txt" download><FileText size={16} /> Exporter le rapport</a>}
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Système">
          <ul className="space-y-1 text-sm">
            <li className="flex justify-between"><span className="text-ink-muted">Version</span><span>{data.product} {data.version}</span></li>
            <li className="flex justify-between"><span className="text-ink-muted">Python</span><span>{data.python.version}</span></li>
            <li className="flex justify-between"><span className="text-ink-muted">Système</span><span className="truncate">{data.python.platform}</span></li>
            <li className="flex justify-between"><span className="text-ink-muted">SQLite</span><span>{data.database.integrity} · journal {data.database.journal_mode}</span></li>
            <li className="flex justify-between"><span className="text-ink-muted">FFmpeg</span><span>{data.ffmpeg.available ? `disponible (${data.ffmpeg.probe_backend})` : 'absent'}</span></li>
            <li className="flex justify-between"><span className="text-ink-muted">Disque libre</span><span>{data.disk.free_gb} Go / {data.disk.total_gb} Go</span></li>
          </ul>
        </Card>

        <Card title="Moteur de programmation">
          <ul className="space-y-1 text-sm">
            <li className="flex items-center justify-between"><span className="text-ink-muted">État</span><span className="flex items-center gap-2">{indicator(data.scheduler.running)} {data.scheduler.running ? 'actif' : 'arrêté'}</span></li>
            <li className="flex justify-between"><span className="text-ink-muted">Worker</span><span>{data.scheduler.worker_id}</span></li>
            <li className="flex justify-between"><span className="text-ink-muted">Programmées</span><span>{data.scheduler.scheduled_count}</span></li>
            <li className="flex justify-between"><span className="text-ink-muted">En retard</span><span>{data.scheduler.late_count}</span></li>
            <li className="flex justify-between"><span className="text-ink-muted">Actions requises</span><span>{data.scheduler.waiting_user_count}</span></li>
            <li className="flex justify-between"><span className="text-ink-muted">Statuts incertains</span><span>{data.scheduler.uncertain_count}</span></li>
            <li className="flex justify-between"><span className="text-ink-muted">Intervalle</span><span>{data.scheduler.tick_seconds} s</span></li>
          </ul>
          {data.scheduler.last_error && <p className="mt-2 text-xs text-red-300">{data.scheduler.last_error}</p>}
        </Card>

        <Card title="Comptes et jetons">
          <ul className="space-y-2 text-sm">
            {data.connectors.map((connector) => (
              <li key={connector.platform} className="rounded-lg border border-line p-2">
                <div className="flex items-center justify-between">
                  <span className="capitalize font-medium">{connector.platform}</span>
                  <span className="flex items-center gap-2 text-xs">{indicator(connector.configured)} {connector.configured ? 'configuré' : 'non configuré'}</span>
                </div>
                <p className="text-xs text-ink-muted">Publication publique : {connector.publish_public_available ? 'autorisée' : 'non autorisée'} · {connector.real_validation}</p>
                {connector.accounts.map((account) => (
                  <p key={account.id} className="mt-1 text-xs text-ink-faint">
                    {account.name} — {account.status}{account.credentials_expire_at ? ` · expire ${formatRelative(account.credentials_expire_at)}` : ''}
                    {account.last_error ? ` · ${account.last_error}` : ''}
                  </p>
                ))}
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Dernières tentatives de publication">
          {data.recent_attempts.length === 0 ? <p className="text-sm text-ink-muted">Aucune tentative pour le moment.</p> : (
            <ul className="divide-y divide-line text-sm">
              {data.recent_attempts.map((attempt, index) => (
                <li key={`${attempt.post_target_id}-${index}`} className="flex items-center justify-between gap-2 py-2">
                  <span className="text-xs text-ink-muted">{formatRelative(attempt.started_at)} · {attempt.phase} · n°{attempt.attempt_no}</span>
                  <span className={`text-xs font-medium ${attempt.outcome === 'success' ? 'text-emerald-300' : attempt.outcome === 'uncertain' ? 'text-orange-300' : 'text-red-300'}`}>
                    {attempt.outcome}{attempt.http_status ? ` (${attempt.http_status})` : ''}
                  </span>
                  <span className="max-w-[45%] truncate text-xs text-ink-faint">{attempt.detail ?? ''}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Journal applicatif" actions={<Button onClick={() => logs.refetch()}><Download size={14} /> Actualiser</Button>}>
          <ul className="max-h-80 space-y-1 overflow-y-auto text-xs">
            {(logs.data?.items ?? []).map((entry) => (
              <li key={entry.id} className="flex gap-2">
                <span className={`w-16 shrink-0 ${entry.level === 'error' ? 'text-red-300' : entry.level === 'warning' ? 'text-amber-300' : 'text-ink-faint'}`}>{entry.level}</span>
                <span className="w-20 shrink-0 text-ink-faint">{entry.source}</span>
                <span className="flex-1">{entry.message}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}

export { Activity }
