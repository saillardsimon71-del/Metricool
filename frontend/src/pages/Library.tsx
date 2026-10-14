import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Film, Image as ImageIcon, Search, Upload, Wand2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { PageHeader } from '../components/AppShell'
import { Button, Card, EmptyState, ErrorState, Field, Input, Modal, Select, Spinner, Textarea } from '../components/ui'
import { api, params } from '../lib/api'
import { formatBytes, formatDuration, formatRelative } from '../lib/format'
import { useToasts } from '../hooks/useToasts'
import type { Media, MediaValidation } from '../lib/types'

export default function Library() {
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('')
  const [detail, setDetail] = useState<Media | null>(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()
  const { notify } = useToasts()

  const list = useQuery({
    queryKey: ['media', query, kind],
    queryFn: () => api.get<{ items: Media[]; total: number }>(`/api/media${params({ q: query || undefined, kind: kind || undefined, limit: 120 })}`),
  })

  const upload = useMutation({
    mutationFn: async (files: FileList | File[]) => {
      const results: string[] = []
      for (const file of Array.from(files)) {
        const form = new FormData()
        form.append('file', file)
        const response = await api.upload<{ created: boolean; duplicate_of: string | null; media: Media }>('/api/media/upload', form)
        results.push(response.created ? `${file.name} importé` : `${file.name} : doublon ignoré`)
      }
      return results
    },
    onSuccess: (messages) => {
      messages.forEach((message) => notify(message, message.includes('doublon') ? 'warning' : 'success'))
      queryClient.invalidateQueries({ queryKey: ['media'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: (error) => notify(error.message, 'error'),
  })

  const transform = useMutation({
    mutationFn: ({ id, operation }: { id: string; operation: string }) => api.post<Media>(`/api/media/${id}/transform`, { operation }),
    onSuccess: (asset) => {
      notify(`Traitement terminé : ${asset.display_name}`, 'success')
      queryClient.invalidateQueries({ queryKey: ['media'] })
    },
    onError: (error) => notify(error.message, 'error'),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/media/${id}?confirm=true`),
    onSuccess: () => {
      notify('Média supprimé de la bibliothèque', 'success')
      setDetail(null)
      queryClient.invalidateQueries()
    },
    onError: (error) => notify(error.message, 'error'),
  })

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api.patch<Media>(`/api/media/${id}`, body),
    onSuccess: (asset) => {
      setDetail(asset)
      queryClient.invalidateQueries({ queryKey: ['media'] })
    },
    onError: (error) => notify(error.message, 'error'),
  })

  return (
    <div>
      <PageHeader
        title="Bibliothèque médias"
        description="Importez vos vidéos verticales : SocialDock calcule l’empreinte SHA-256, évite les doublons et extrait les métadonnées via FFmpeg."
        actions={
          <>
            <input ref={inputRef} type="file" multiple accept=".mp4,.mov,.webm,.jpg,.jpeg,.png" className="hidden" onChange={(event) => event.target.files && upload.mutate(event.target.files)} />
            <Button variant="primary" loading={upload.isPending} onClick={() => inputRef.current?.click()}><Upload size={16} /> Importer</Button>
          </>
        }
      />

      <div
        onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          if (event.dataTransfer.files.length) upload.mutate(event.dataTransfer.files)
        }}
        className={`mb-4 rounded-xl border-2 border-dashed p-6 text-center text-sm transition ${dragging ? 'border-brand-500 bg-brand-500/10' : 'border-line text-ink-muted'}`}
      >
        Déposez vos fichiers ici (MP4, MOV, WebM, JPEG, PNG) — le fichier original reste à sa place.
      </div>

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Recherche"><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Nom, note…" /></Field>
        <Field label="Type">
          <Select value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="">Tous</option>
            <option value="video">Vidéos</option>
            <option value="image">Images</option>
          </Select>
        </Field>
        <span className="chip"><Search size={12} /> {list.data?.total ?? 0}</span>
      </div>

      {list.isLoading && <Spinner label="Chargement de la bibliothèque…" />}
      {list.error && <ErrorState error={list.error} onRetry={() => list.refetch()} />}
      {list.data && list.data.items.length === 0 && (
        <EmptyState title="Bibliothèque vide" description="Importez une vidéo pour commencer, ou configurez un dossier surveillé Studio IA." />
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(list.data?.items ?? []).map((item) => (
          <button key={item.id} onClick={() => setDetail(item)} className="card overflow-hidden text-left transition hover:border-brand-500">
            <div className="relative aspect-video bg-black">
              {item.thumbnail_path ? (
                <img src={`/api/media/${item.id}/thumbnail`} alt="" className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full items-center justify-center text-ink-faint">{item.kind === 'video' ? <Film size={24} /> : <ImageIcon size={24} />}</div>
              )}
              {item.probe_status !== 'ok' && <span className="absolute left-2 top-2 rounded bg-amber-500/90 px-1.5 py-0.5 text-[10px] text-black">analyse indisponible</span>}
              <span className="absolute bottom-2 right-2 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-white">{formatDuration(item.duration_seconds)}</span>
            </div>
            <div className="space-y-1 p-3">
              <p className="truncate text-sm font-medium">{item.display_name}</p>
              <p className="text-xs text-ink-muted">{item.width ?? '?'}×{item.height ?? '?'} · {formatBytes(item.size_bytes)} · {formatRelative(item.created_at)}</p>
              <div className="flex flex-wrap gap-1">{item.tags.map((tag) => <span key={tag} className="chip">#{tag}</span>)}</div>
            </div>
          </button>
        ))}
      </div>

      <Modal open={detail !== null} title={detail?.display_name ?? ''} onClose={() => setDetail(null)}>
        {detail && (
          <div className="grid gap-4 md:grid-cols-[260px_1fr]">
            <div>
              {detail.thumbnail_path ? <img src={`/api/media/${detail.id}/thumbnail`} alt="" className="w-full rounded-lg" /> : <div className="aspect-video rounded-lg bg-surface-subtle" />}
              <video src={`/api/media/${detail.id}/file`} controls className="mt-2 w-full rounded-lg" />
            </div>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2 text-xs text-ink-muted">
                <p>Durée : {formatDuration(detail.duration_seconds)}</p>
                <p>Résolution : {detail.width}×{detail.height}</p>
                <p>Images/s : {detail.fps ?? '—'}</p>
                <p>Taille : {formatBytes(detail.size_bytes)}</p>
                <p>Codec vidéo : {detail.video_codec ?? '—'}</p>
                <p>Codec audio : {detail.audio_codec ?? (detail.has_audio ? 'inconnu' : 'absent')}</p>
                <p className="col-span-2 break-all">SHA-256 : {detail.sha256}</p>
              </div>
              <Field label="Nom affiché">
                <Input defaultValue={detail.display_name} onBlur={(event) => patch.mutate({ id: detail.id, body: { display_name: event.target.value } })} />
              </Field>
              <Field label="Tags (séparés par des virgules)">
                <Input defaultValue={detail.tags.join(', ')} onBlur={(event) => patch.mutate({ id: detail.id, body: { tags: event.target.value.split(',').map((tag) => tag.trim()).filter(Boolean) } })} />
              </Field>
              <Field label="Notes"><Textarea defaultValue={detail.notes ?? ''} onBlur={(event) => patch.mutate({ id: detail.id, body: { notes: event.target.value } })} /></Field>
              <div className="flex flex-wrap gap-2">
                <Button loading={transform.isPending} onClick={() => transform.mutate({ id: detail.id, operation: 'vertical' })}><Wand2 size={14} /> Adapter en 9:16</Button>
                <Button loading={transform.isPending} onClick={() => transform.mutate({ id: detail.id, operation: 'h264' })}>Convertir H.264/AAC</Button>
                <Button loading={transform.isPending} onClick={() => transform.mutate({ id: detail.id, operation: 'audio' })}>Normaliser le son</Button>
                <Button onClick={() => api.post<Media>(`/api/media/${detail.id}/refresh`).then((asset) => { setDetail(asset); notify('Métadonnées réanalysées', 'success') })}>Réanalyser</Button>
                <Button variant="danger" onClick={() => { if (window.confirm('Supprimer ce média de la bibliothèque ? Le fichier sera effacé du dossier SocialDock.')) remove.mutate(detail.id) }}>Supprimer</Button>
              </div>
              <ValidationPanel mediaId={detail.id} probeStatus={detail.probe_status} />
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

function ValidationPanel({ mediaId, probeStatus }: { mediaId: string; probeStatus: string }) {
  const [platform, setPlatform] = useState('instagram')
  const query = useQuery({
    queryKey: ['media-validation', mediaId, platform],
    queryFn: () => api.get<MediaValidation>(`/api/media/${mediaId}/validate/${platform}`),
  })
  return (
    <div className="rounded-lg border border-line p-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">Conformité plateforme</p>
        <Select value={platform} onChange={(event) => setPlatform(event.target.value)} className="w-40">
          <option value="instagram">Instagram</option>
          <option value="tiktok">TikTok</option>
          <option value="youtube">YouTube</option>
        </Select>
      </div>
      {query.isLoading && <Spinner label="Analyse…" />}
      {query.data && (
        <div className="space-y-1 text-xs">
          {probeStatus !== 'ok' && (
            <p className="flex items-center gap-1 text-amber-300"><AlertTriangle size={12} /> FFmpeg absent : la conformité n’a pas pu être vérifiée localement.</p>
          )}
          {query.data.issues.map((issue) => <p key={issue.key} className="text-red-300">• {issue.message}</p>)}
          {query.data.warnings.map((warning) => <p key={warning.key} className="text-amber-300">• {warning.message}</p>)}
          {query.data.info.map((info) => <p key={info.key} className="text-ink-muted">• {info.message}</p>)}
          {query.data.issues.length === 0 && query.data.warnings.length === 0 && probeStatus === 'ok' && <p className="text-emerald-300">Conforme aux exigences {query.data.platform_label}.</p>}
          <ul className="mt-2 space-y-0.5 text-ink-faint">{query.data.notes.map((note) => <li key={note}>– {note}</li>)}</ul>
        </div>
      )}
    </div>
  )
}

export { Card }
