import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Plus, RefreshCw, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '../components/AppShell'
import PlatformIcon from '../components/PlatformIcon'
import StatusBadge from '../components/StatusBadge'
import { Button, Card, EmptyState, ErrorState, Field, Input, Modal, Select, Spinner } from '../components/ui'
import { api, params } from '../lib/api'
import { formatDateTime } from '../lib/format'
import { useToasts } from '../hooks/useToasts'
import type { PostStatus, PostTarget } from '../lib/types'

interface Row { target: PostTarget; post: { id: string; title: string } | null; account: { id: string; display_name: string; platform: string; mode: string } | null; status_label: string }

const filters: { value: string; label: string }[] = [
  { value: '', label: 'Tous les statuts' },
  { value: 'scheduled', label: 'Programmées' },
  { value: 'draft', label: 'Brouillons' },
  { value: 'published', label: 'Publiées' },
  { value: 'published_private', label: 'Publiées (privées)' },
  { value: 'waiting_for_user', label: 'Action humaine' },
  { value: 'uncertain', label: 'Statut incertain' },
  { value: 'failed', label: 'Échecs' },
]

export default function Posts() {
  const [status, setStatus] = useState('')
  const [query, setQuery] = useState('')
  const [resolving, setResolving] = useState<Row | null>(null)
  const [resolution, setResolution] = useState<'published' | 'failed' | 'retry'>('published')
  const [remoteUrl, setRemoteUrl] = useState('')
  const queryClient = useQueryClient()
  const { notify } = useToasts()

  const list = useQuery({
    queryKey: ['posts', status, query],
    queryFn: () => api.get<{ items: Row[]; total: number }>(`/api/posts${params({ status: status || undefined, q: query || undefined })}`),
  })

  const act = useMutation({
    mutationFn: ({ id, action, body }: { id: string; action: string; body?: unknown }) => api.post(`/api/posts/targets/${id}/${action}`, body),
    onSuccess: () => {
      notify('Action enregistrée', 'success')
      queryClient.invalidateQueries()
    },
    onError: (error) => notify(error.message, 'error'),
  })

  if (list.isLoading) return <Spinner label="Chargement des publications…" />
  if (list.error) return <ErrorState error={list.error} onRetry={() => list.refetch()} />

  return (
    <div>
      <PageHeader
        title="Publications"
        description="Une ligne par compte : chaque publication suit son propre cycle de vie, avec son journal de tentatives."
        actions={<Link className="btn-primary" to="/posts/new"><Plus size={16} /> Nouvelle publication</Link>}
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Recherche"><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Titre…" /></Field>
        <Field label="Statut">
          <Select value={status} onChange={(event) => setStatus(event.target.value)}>
            {filters.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </Select>
        </Field>
        <span className="chip">{list.data!.total} publication(s)</span>
      </div>

      {list.data!.items.length === 0 ? (
        <EmptyState title="Aucune publication" description="Créez une publication pour préparer une vidéo sur plusieurs comptes." />
      ) : (
        <Card>
          <ul className="divide-y divide-line">
            {list.data!.items.map((row) => (
              <li key={row.target.id} className="flex flex-wrap items-center gap-3 py-3">
                <PlatformIcon platform={row.account?.platform} />
                <div className="min-w-[200px] flex-1">
                  <Link className="text-sm font-medium hover:underline" to={`/posts/${row.post?.id}`}>{row.post?.title ?? 'Sans titre'}</Link>
                  <p className="text-xs text-ink-muted">
                    {row.account?.display_name} · {formatDateTime(row.target.scheduled_at)} · {row.target.attempts_count} tentative(s)
                  </p>
                  {row.target.error_message && <p className="mt-1 text-xs text-red-300">{row.target.error_message}</p>}
                  {row.target.user_action_hint && <p className="mt-1 text-xs text-amber-300">{row.target.user_action_hint}</p>}
                </div>
                <StatusBadge status={row.target.status as PostStatus} label={row.status_label} />
                <div className="flex flex-wrap gap-1">
                  {row.target.remote_url && (
                    <a className="btn-ghost" href={row.target.remote_url} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Voir</a>
                  )}
                  {(row.target.status === 'draft' || row.target.status === 'ready' || row.target.status === 'failed') && (
                    <Button loading={act.isPending} onClick={() => act.mutate({ id: row.target.id, action: 'publish-now' })}>Publier maintenant</Button>
                  )}
                  {row.target.status === 'failed' && (
                    <Button onClick={() => act.mutate({ id: row.target.id, action: 'schedule', body: { scheduled_at: new Date().toISOString() } })}>
                      <RotateCcw size={14} /> Reprogrammer
                    </Button>
                  )}
                  {row.target.status === 'uncertain' && (
                    <Button onClick={() => { setResolving(row); setResolution('published'); setRemoteUrl(row.target.remote_url ?? '') }}>Résoudre</Button>
                  )}
                  {row.target.status !== 'waiting_for_user' && row.target.status !== 'published' && row.target.status !== 'published_private' && (
                    <Button onClick={() => act.mutate({ id: row.target.id, action: 'assisted' })}>Mode assisté</Button>
                  )}
                  {row.target.status === 'waiting_for_user' && (
                    <Button onClick={() => act.mutate({ id: row.target.id, action: 'assisted/complete', body: { remote_url: row.target.remote_url ?? 'https://exemple.local', status: 'published' } })}>
                      Marquer publiée
                    </Button>
                  )}
                  <Button onClick={() => act.mutate({ id: row.target.id, action: 'refresh-status' })}><RefreshCw size={14} /> Statut</Button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Modal
        open={resolving !== null}
        title="Résoudre un statut incertain"
        onClose={() => setResolving(null)}
        footer={
          <>
            <Button onClick={() => setResolving(null)}>Annuler</Button>
            <Button
              variant="primary"
              onClick={() => {
                if (!resolving) return
                act.mutate({ id: resolving.target.id, action: 'resolve', body: { resolution, remote_url: remoteUrl || null } })
                setResolving(null)
              }}
            >
              Valider
            </Button>
          </>
        }
      >
        <p className="mb-3 text-sm text-ink-muted">
          SocialDock ne republie jamais automatiquement une cible ambiguë. Vérifiez d’abord la plateforme, puis choisissez l’issue réelle.
        </p>
        <div className="space-y-3">
          <Field label="Issue constatée">
            <Select value={resolution} onChange={(event) => setResolution(event.target.value as typeof resolution)}>
              <option value="published">La publication est bien en ligne</option>
              <option value="failed">La publication a échoué</option>
              <option value="retry">Rien n’a été publié : relancer</option>
            </Select>
          </Field>
          {resolution === 'published' && (
            <Field label="Lien publié"><Input value={remoteUrl} onChange={(event) => setRemoteUrl(event.target.value)} placeholder="https://…" /></Field>
          )}
        </div>
      </Modal>
    </div>
  )
}
