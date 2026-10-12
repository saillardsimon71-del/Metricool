import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderPlus, FolderSync, Layers, Wand2 } from 'lucide-react'
import { useState } from 'react'
import { PageHeader } from '../components/AppShell'
import { Button, Card, EmptyState, Field, Input, Select, Spinner } from '../components/ui'
import { api } from '../lib/api'
import { formatRelative } from '../lib/format'
import { useToasts } from '../hooks/useToasts'
import type { Account, Media, Template, WatchedFolder } from '../lib/types'

export default function Automations() {
  const queryClient = useQueryClient()
  const { notify } = useToasts()

  const templates = useQuery({ queryKey: ['templates'], queryFn: () => api.get<Template[]>('/api/posts/templates') })
  const folders = useQuery({ queryKey: ['watchers'], queryFn: () => api.get<WatchedFolder[]>('/api/watchers') })
  const media = useQuery({ queryKey: ['media'], queryFn: () => api.get<{ items: Media[] }>('/api/media?limit=200') })
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api.get<Account[]>('/api/accounts') })

  const [selectedMedia, setSelectedMedia] = useState<string[]>([])
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>([])
  const [days, setDays] = useState(5)
  const [times, setTimes] = useState('12:30, 18:30')
  const [templateId, setTemplateId] = useState('')
  const [folderPath, setFolderPath] = useState('')
  const [tags, setTags] = useState('')

  const invalidate = () => { queryClient.invalidateQueries(); }

  const createFolder = useMutation({
    mutationFn: () => api.post<WatchedFolder>('/api/watchers', { path: folderPath, tags: tags.split(',').map((tag) => tag.trim()).filter(Boolean), create_draft: true, enabled: true, recursive: false }),
    onSuccess: () => { notify('Dossier surveillé ajouté', 'success'); setFolderPath(''); setTags(''); invalidate() },
    onError: (error) => notify(error.message, 'error'),
  })

  const scan = useMutation({
    mutationFn: (id?: string) => (id ? api.post(`/api/watchers/${id}/scan`) : api.post('/api/watchers/scan-all')),
    onSuccess: (result) => { notify(`Analyse terminée : ${JSON.stringify(result).slice(0, 180)}`, 'success'); invalidate() },
    onError: (error) => notify(error.message, 'error'),
  })

  const batch = useMutation({
    mutationFn: () =>
      api.post<{ scheduled: unknown[] }>('/api/posts/batch-schedule', {
        media_ids: selectedMedia,
        account_ids: selectedAccounts,
        days: nextDays(days),
        times: times.split(',').map((value) => value.trim()).filter(Boolean),
        template_id: templateId || null,
      }),
    onSuccess: (result) => { notify(`${result.scheduled.length} publication(s) répartie(s) sur le calendrier`, 'success'); invalidate() },
    onError: (error) => notify(error.message, 'error'),
  })

  return (
    <div>
      <PageHeader title="Automatisations" description="Modèles réutilisables, dossiers surveillés Studio IA et programmation par lot — sans service externe ni LLM payant." />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Programmation par lot" actions={<Wand2 size={16} className="text-ink-faint" />}>
          <p className="mb-3 text-xs text-ink-muted">Répartit N vidéos sur les prochains jours et horaires, une publication par compte sélectionné.</p>
          {media.isLoading || accounts.isLoading ? <Spinner /> : (
            <div className="space-y-3">
              <Field label={`Vidéos (${selectedMedia.length} sélectionnée(s))`}>
                <div className="max-h-40 overflow-y-auto rounded-lg border border-line p-2">
                  {(media.data?.items ?? []).map((item) => (
                    <label key={item.id} className="flex items-center gap-2 px-1 py-0.5 text-sm hover:bg-surface-subtle">
                      <input type="checkbox" className="h-4 w-4 accent-brand-500" checked={selectedMedia.includes(item.id)}
                        onChange={(event) => setSelectedMedia((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} />
                      <span className="truncate">{item.display_name}</span>
                    </label>
                  ))}
                  {(media.data?.items ?? []).length === 0 && <p className="p-2 text-xs text-ink-faint">Aucune vidéo importée.</p>}
                </div>
              </Field>
              <Field label="Comptes">
                <div className="flex flex-wrap gap-2">
                  {(accounts.data ?? []).map((account) => (
                    <button key={account.id}
                      className={`rounded-lg border px-2 py-1 text-xs ${selectedAccounts.includes(account.id) ? 'border-brand-500 bg-brand-500/10' : 'border-line'}`}
                      onClick={() => setSelectedAccounts((current) => current.includes(account.id) ? current.filter((id) => id !== account.id) : [...current, account.id])}>
                      {account.display_name}
                    </button>
                  ))}
                </div>
              </Field>
              <div className="grid grid-cols-3 gap-3">
                <Field label="Jours"><Input type="number" min={1} max={60} value={days} onChange={(event) => setDays(Number(event.target.value))} /></Field>
                <Field label="Horaires (UTC)"><Input value={times} onChange={(event) => setTimes(event.target.value)} /></Field>
                <Field label="Modèle">
                  <Select value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
                    <option value="">Aucun</option>
                    {(templates.data ?? []).map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}
                  </Select>
                </Field>
              </div>
              <Button variant="primary" loading={batch.isPending} disabled={!selectedMedia.length || !selectedAccounts.length} onClick={() => batch.mutate()}>
                Programmer le lot
              </Button>
            </div>
          )}
        </Card>

        <Card title="Dossiers surveillés (Studio IA)" actions={<Button onClick={() => scan.mutate()} loading={scan.isPending}><FolderSync size={14} /> Tout analyser</Button>}>
          <div className="mb-3 space-y-2">
            <Field label="Chemin du dossier d’exports"><Input value={folderPath} onChange={(event) => setFolderPath(event.target.value)} placeholder="C:\Users\moi\StudioIA\exports" /></Field>
            <Field label="Tags appliqués à l’import"><Input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="studio-ia, vertical" /></Field>
            <Button onClick={() => createFolder.mutate()} loading={createFolder.isPending} disabled={!folderPath}><FolderPlus size={14} /> Surveiller ce dossier</Button>
          </div>
          {folders.isLoading && <Spinner />}
          {folders.data && folders.data.length === 0 && <EmptyState title="Aucun dossier surveillé" description="Les fichiers déposés dans ce dossier seront importés automatiquement, une fois l’écriture terminée." />}
          <ul className="space-y-2">
            {(folders.data ?? []).map((folder) => (
              <li key={folder.id} className="rounded-lg border border-line p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate font-medium">{folder.path}</p>
                  <Button onClick={() => scan.mutate(folder.id)} loading={scan.isPending}>Analyser</Button>
                </div>
                <p className="text-xs text-ink-muted">
                  {folder.enabled ? 'Actif' : 'Suspendu'} · brouillon auto : {folder.create_draft ? 'oui' : 'non'} · dernière analyse : {formatRelative(folder.last_scan_at)}
                </p>
                {folder.last_error && <p className="text-xs text-red-300">{folder.last_error}</p>}
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card title="Modèles de publication" className="mt-4" actions={<Layers size={16} className="text-ink-faint" />}>
        {templates.data && templates.data.length === 0 ? (
          <EmptyState title="Aucun modèle" description="Enregistrez la configuration d’une publication (hashtags, descriptions, comptes) pour la réappliquer en un clic depuis le compositeur." />
        ) : (
          <ul className="divide-y divide-line">
            {(templates.data ?? []).map((template) => (
              <li key={template.id} className="flex items-center justify-between py-2 text-sm">
                <div>
                  <p className="font-medium">{template.name}</p>
                  <p className="text-xs text-ink-muted">{(template.payload.hashtags as string[] | undefined)?.join(' ') || 'sans hashtag'} · {Object.keys((template.payload.per_platform as Record<string, unknown>) ?? {}).join(', ') || 'toutes plateformes'}</p>
                </div>
                <Button variant="danger" onClick={() => api.del(`/api/posts/templates/${template.id}`).then(invalidate)}>Supprimer</Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}

const nextDays = (count: number): string[] => {
  const out: string[] = []
  const today = new Date()
  for (let index = 0; index < Math.max(1, count); index += 1) {
    const day = new Date(today)
    day.setDate(today.getDate() + index)
    out.push(day.toISOString().slice(0, 10))
  }
  return out
}
