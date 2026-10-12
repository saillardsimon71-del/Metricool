import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Play, RotateCcw, Square } from 'lucide-react'
import { useState } from 'react'
import { PageHeader } from '../components/AppShell'
import { Button, Card, ErrorState, Field, Input, Spinner } from '../components/ui'
import { api } from '../lib/api'
import { useTheme } from '../hooks/useTheme'
import { useToasts } from '../hooks/useToasts'
import type { Preferences, SettingsPayload } from '../lib/types'

export default function Settings() {
  const queryClient = useQueryClient()
  const { notify } = useToasts()
  const { theme, setTheme } = useTheme()
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api.get<SettingsPayload>('/api/settings') })
  const [prefs, setPrefs] = useState<Preferences | null>(null)

  const save = useMutation({
    mutationFn: (body: Partial<Preferences>) => api.patch<{ preferences: Preferences }>('/api/settings/preferences', body),
    onSuccess: () => { notify('Préférences enregistrées', 'success'); queryClient.invalidateQueries({ queryKey: ['settings'] }) },
    onError: (error) => notify(error.message, 'error'),
  })

  const rotate = useMutation({
    mutationFn: () => api.post<{ ingest_token: string }>('/api/settings/integrations/token/rotate'),
    onSuccess: () => { notify('Token d’ingestion régénéré : mettez Studio IA à jour', 'warning'); queryClient.invalidateQueries({ queryKey: ['settings'] }) },
    onError: (error) => notify(error.message, 'error'),
  })

  const schedulerAction = useMutation({
    mutationFn: (action: 'start' | 'stop') => api.post(`/api/scheduler/${action}`),
    onSuccess: () => { notify('Moteur de programmation mis à jour', 'success'); queryClient.invalidateQueries({ queryKey: ['scheduler-status'] }) },
    onError: (error) => notify(error.message, 'error'),
  })

  if (settings.isLoading) return <Spinner label="Chargement des paramètres…" />
  if (settings.error) return <ErrorState error={settings.error} onRetry={() => settings.refetch()} />
  const current = prefs ?? settings.data!.preferences
  const patch = (key: keyof Preferences, value: unknown) => setPrefs({ ...current, [key]: value } as Preferences)

  return (
    <div>
      <PageHeader title="Paramètres" description="Préférences locales, intégration Studio IA et contrôle du moteur de programmation." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Préférences">
          <div className="space-y-3">
            <Field label="Thème">
              <div className="flex gap-2">
                <Button variant={theme === 'dark' ? 'primary' : 'ghost'} onClick={() => { setTheme('dark'); patch('theme', 'dark') }}>Sombre</Button>
                <Button variant={theme === 'light' ? 'primary' : 'ghost'} onClick={() => { setTheme('light'); patch('theme', 'light') }}>Clair</Button>
              </div>
            </Field>
            <Field label="Fuseau horaire d’affichage" hint="Les instants sont toujours stockés en UTC.">
              <Input value={current.timezone} onChange={(event) => patch('timezone', event.target.value)} />
            </Field>
            <Field label="Horaires favoris (séparés par des virgules, UTC)">
              <Input value={current.favorite_times.join(', ')} onChange={(event) => patch('favorite_times', event.target.value.split(',').map((value) => value.trim()).filter(Boolean))} />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="h-4 w-4 accent-brand-500" checked={current.notifications_enabled} onChange={(event) => patch('notifications_enabled', event.target.checked)} />
              Notifications Windows (publication échouée, action requise, compte expiré)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="h-4 w-4 accent-brand-500" checked={current.demo_mode} onChange={(event) => patch('demo_mode', event.target.checked)} />
              Mode démonstration (comptes simulés uniquement)
            </label>
            <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(current)}>Enregistrer</Button>
          </div>
        </Card>

        <Card title="Intégration Studio IA">
          <p className="mb-2 text-xs text-ink-muted">API locale protégée par token. Le serveur n’écoute que sur 127.0.0.1 et refuse les chemins hors des dossiers autorisés.</p>
          <div className="space-y-2 rounded-lg border border-line p-3 text-xs">
            <p>Endpoint : <code className="text-brand-300">POST /api/ingest/video</code></p>
            <p>En-tête : <code className="text-brand-300">X-SocialDock-Token</code></p>
            <div className="flex items-center gap-2">
              <code data-testid="ingest-token" className="flex-1 truncate rounded bg-surface-subtle px-2 py-1">{settings.data!.integrations.ingest_token}</code>
              <Button onClick={() => navigator.clipboard.writeText(settings.data!.integrations.ingest_token).then(() => notify('Token copié', 'success'))}><Copy size={14} /></Button>
              <Button onClick={() => rotate.mutate()} loading={rotate.isPending}><RotateCcw size={14} /></Button>
            </div>
          </div>
          <pre className="mt-3 overflow-x-auto rounded-lg bg-surface-subtle p-3 text-[11px] text-ink-muted">{`curl -X POST http://127.0.0.1:8000/api/ingest/video \\
  -H "X-SocialDock-Token: ${settings.data!.integrations.ingest_token}" \\
  -H "Content-Type: application/json" \\
  -d '{"path":"C:\\\\StudioIA\\\\exports\\\\clip.mp4","title":"Épisode 12","series":"Ma série","episode":12,"tags":["vertical"]}'`}</pre>
        </Card>

        <Card title="Moteur de programmation">
          <p className="mb-3 text-xs text-ink-muted">
            Le moteur tourne avec le serveur, indépendamment du navigateur. S’il est arrêté, les publications programmées ne partiront pas.
          </p>
          <div className="flex gap-2">
            <Button onClick={() => schedulerAction.mutate('start')} loading={schedulerAction.isPending}><Play size={14} /> Démarrer</Button>
            <Button onClick={() => schedulerAction.mutate('stop')} loading={schedulerAction.isPending}><Square size={14} /> Arrêter</Button>
          </div>
        </Card>

        <Card title="Emplacements">
          <ul className="space-y-1 text-xs text-ink-muted">
            {Object.entries(settings.data!.config).map(([key, value]) => (
              <li key={key} className="flex justify-between gap-3 border-b border-line py-1">
                <span>{key}</span><span className="truncate text-right text-ink">{String(value)}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}
