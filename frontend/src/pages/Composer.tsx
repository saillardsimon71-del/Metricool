import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, Save, Send, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { PageHeader } from '../components/AppShell'
import PlatformIcon, { platformLabel } from '../components/PlatformIcon'
import { Button, Card, EmptyState, Field, Input, Modal, Select, Textarea } from '../components/ui'
import { api } from '../lib/api'
import { buildVariant, groupVariantsByPlatform, parseTags, toggleAll } from '../lib/compose'
import { formatBytes, formatDuration, fromLocalInput, toLocalInput } from '../lib/format'
import { useToasts } from '../hooks/useToasts'
import type { Account, Media, Post } from '../lib/types'

interface Payload { [key: string]: unknown }

export default function Composer() {
  const { postId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { notify } = useToasts()

  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api.get<Account[]>('/api/accounts') })
  const media = useQuery({ queryKey: ['media'], queryFn: () => api.get<{ items: Media[] }>('/api/media?limit=200') })
  const existing = useQuery({ queryKey: ['post', postId], enabled: Boolean(postId), queryFn: () => api.get<Post>(`/api/posts/${postId}`) })

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [hashtags, setHashtags] = useState('')
  const [language, setLanguage] = useState('fr')
  const [series, setSeries] = useState('')
  const [episode, setEpisode] = useState('')
  const [notes, setNotes] = useState('')
  const [mediaId, setMediaId] = useState('')
  const [thumbnailId, setThumbnailId] = useState('')
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [variants, setVariants] = useState<Record<string, Payload>>({})
  const [activeTab, setActiveTab] = useState<string>('')
  const [when, setWhen] = useState('')
  const [preview, setPreview] = useState(false)
  const [loadedPostId, setLoadedPostId] = useState<string | null>(null)

  const selectedAccounts = useMemo(() => (accounts.data ?? []).filter((account) => selected[account.id]), [accounts.data, selected])
  const platforms = useMemo(() => Array.from(new Set(selectedAccounts.map((account) => account.platform))), [selectedAccounts])
  const currentTab = selectedAccounts.some((account) => account.id === activeTab) ? activeTab : selectedAccounts[0]?.id

  useEffect(() => {
    if (!existing.data) return
    const post = existing.data
    setTitle(post.title)
    setDescription(post.description)
    setHashtags(post.hashtags.join(' '))
    setLanguage(post.language)
    setSeries(post.series_id ?? '')
    setEpisode(post.episode_number ? String(post.episode_number) : '')
    setNotes(post.internal_notes ?? '')
    setMediaId(post.media_asset_id ?? '')
    setThumbnailId(post.thumbnail_media_id ?? '')
    setSelected(Object.fromEntries(post.targets.map((target) => [target.account_id, true])))
    setVariants(Object.fromEntries(post.targets.map((target) => [target.account_id, target.payload])))
    setActiveTab(post.targets[0]?.account_id ?? '')
    const first = post.targets.find((target) => target.scheduled_at)?.scheduled_at
    setWhen(toLocalInput(first ?? null))
    setLoadedPostId(post.id)
  }, [existing.data])

  useEffect(() => {
    if (!accounts.data || (postId && loadedPostId !== postId)) return
    const common = { title, description, hashtags: parseTags(hashtags), language }
    setVariants((current) => {
      const next = { ...current }
      for (const account of selectedAccounts) if (!next[account.id]) next[account.id] = buildVariant(account.platform, common)
      for (const key of Object.keys(next)) if (!selectedAccounts.some((account) => account.id === key)) delete next[key]
      return next
    })
  }, [accounts.data, postId, loadedPostId, selectedAccounts, title, description, hashtags, language])

  const regenerate = () => {
    const common = { title, description, hashtags: parseTags(hashtags), language }
    setVariants(Object.fromEntries(selectedAccounts.map((account) => [account.id, buildVariant(account.platform, common)])))
    notify('Variantes régénérées depuis les métadonnées communes', 'info')
  }

  const save = useMutation({
    mutationFn: async (mode: 'draft' | 'schedule' | 'now') => {
      const accountIds = selectedAccounts.map((account) => account.id)
      const payload = {
        title: title || 'Sans titre',
        description,
        hashtags: parseTags(hashtags),
        media_asset_id: mediaId || null,
        thumbnail_media_id: thumbnailId || null,
        language,
        internal_notes: notes || null,
        episode_number: episode ? Number(episode) : null,
        account_ids: accountIds,
        per_platform: groupVariantsByPlatform(selectedAccounts, variants),
      }
      const post = postId ? await api.patch<Post>(`/api/posts/${postId}`, { ...payload, propagate_metadata: false }) : await api.post<Post>('/api/posts', payload)
      if (mode !== 'draft') {
        if (!when) throw new Error('Choisissez une date et une heure de publication.')
        for (const target of post.targets) {
          const iso = fromLocalInput(when, target.scheduled_at)
          await api.post(`/api/posts/targets/${target.id}/schedule`, { scheduled_at: iso })
        }
        if (mode === 'now') {
          const immediate = new Date().toISOString()
          for (const target of post.targets) await api.post(`/api/posts/targets/${target.id}/schedule`, { scheduled_at: immediate })
        }
      }
      return { mode }
    },
    onSuccess: ({ mode }) => {
      notify(mode === 'draft' ? 'Brouillon enregistré' : mode === 'schedule' ? 'Publications programmées' : 'Publication immédiate demandée', 'success')
      queryClient.invalidateQueries()
      navigate('/posts')
    },
    onError: (error) => notify(error.message, 'error'),
  })

  const remove = useMutation({
    mutationFn: () => api.del(`/api/posts/${postId}?confirm=true`),
    onSuccess: () => {
      notify('Publication supprimée', 'success')
      queryClient.invalidateQueries()
      navigate('/posts')
    },
    onError: (error) => notify(error.message, 'error'),
  })

  const chosenMedia = (media.data?.items ?? []).find((item) => item.id === mediaId)

  return (
    <div>
      <PageHeader
        title={postId ? 'Modifier la publication' : 'Nouvelle publication'}
        description="Une vidéo, plusieurs comptes : préparez une description commune puis ajustez chaque plateforme."
        actions={
          <>
            {postId && <Button variant="danger" onClick={() => remove.mutate()}><Trash2 size={16} /> Supprimer</Button>}
            <Button onClick={() => setPreview(true)}><Eye size={16} /> Prévisualiser</Button>
            <Button loading={save.isPending} onClick={() => save.mutate('draft')}><Save size={16} /> Brouillon</Button>
            <Button loading={save.isPending} onClick={() => save.mutate('schedule')} variant="primary"><Send size={16} /> Programmer</Button>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <div className="space-y-4">
          <Card title="Média">
            <Field label="Vidéo">
              <Select value={mediaId} onChange={(event) => setMediaId(event.target.value)}>
                <option value="">— Sélectionner —</option>
                {(media.data?.items ?? []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.display_name} · {formatDuration(item.duration_seconds)} · {item.width}×{item.height}
                  </option>
                ))}
              </Select>
            </Field>
            {chosenMedia && (
              <div className="mt-3 space-y-1 text-xs text-ink-muted">
                <p>{formatBytes(chosenMedia.size_bytes)} · {chosenMedia.video_codec ?? 'codec inconnu'} · {chosenMedia.audio_codec ?? 'sans audio'}</p>
                {chosenMedia.probe_status !== 'ok' && <p className="text-amber-300">Analyse technique indisponible : {chosenMedia.probe_error}</p>}
              </div>
            )}
            <div className="mt-3">
              <Field label="Miniature / couverture">
                <Select value={thumbnailId} onChange={(event) => setThumbnailId(event.target.value)}>
                  <option value="">— Première frame —</option>
                  {(media.data?.items ?? []).filter((item) => item.kind === 'image').map((item) => (
                    <option key={item.id} value={item.id}>{item.display_name}</option>
                  ))}
                </Select>
              </Field>
            </div>
          </Card>

          <Card title="Comptes" actions={<Button onClick={() => setSelected(toggleAll(accounts.data ?? [], selected))}>Tout</Button>}>
            {(accounts.data ?? []).length === 0 ? (
              <EmptyState title="Aucun compte" description="Ajoutez des comptes de démonstration ou connectez un compte réel." action={<Button onClick={() => navigate('/accounts')}>Ouvrir Comptes</Button>} />
            ) : (
              <ul className="space-y-1">
                {(accounts.data ?? []).map((account) => (
                  <li key={account.id}>
                    <label className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-surface-subtle">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-brand-500"
                        checked={Boolean(selected[account.id])}
                        onChange={(event) => setSelected((current) => ({ ...current, [account.id]: event.target.checked }))}
                      />
                      <PlatformIcon platform={account.platform} />
                      <span className="flex-1 truncate text-sm">{account.display_name}</span>
                      {account.mode === 'demo' && <span className="chip">démo</span>}
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card title="Métadonnées communes">
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Titre interne"><Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Ma vidéo 9:16" /></Field>
              <div className="grid grid-cols-3 gap-3">
                <Field label="Langue"><Input value={language} onChange={(event) => setLanguage(event.target.value)} maxLength={5} /></Field>
                <Field label="Série"><Input value={series} onChange={(event) => setSeries(event.target.value)} /></Field>
                <Field label="Épisode"><Input value={episode} onChange={(event) => setEpisode(event.target.value)} inputMode="numeric" /></Field>
              </div>
              <Field label="Description commune"><Textarea value={description} onChange={(event) => setDescription(event.target.value)} /></Field>
              <Field label="Hashtags" hint="Séparés par des espaces, sans # obligatoire">
                <Input value={hashtags} onChange={(event) => setHashtags(event.target.value)} placeholder="shorts vertical ia" />
              </Field>
              <Field label="Date et heure (Europe/Paris)">
                <Input type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} />
              </Field>
              <Field label="Notes internes"><Textarea value={notes} onChange={(event) => setNotes(event.target.value)} /></Field>
            </div>
          </Card>

          <Card
            title={`Variantes par plateforme (${selectedAccounts.length})`}
            actions={<Button onClick={regenerate}><Sparkles size={14} /> Régénérer depuis le commun</Button>}
          >
            {selectedAccounts.length === 0 ? (
              <EmptyState title="Sélectionnez au moins un compte" description="Chaque compte recevra sa propre variante de description." />
            ) : (
              <>
                <div className="mb-3 flex flex-wrap gap-1 border-b border-line pb-2">
                  {selectedAccounts.map((account) => (
                    <button
                      key={account.id}
                      onClick={() => setActiveTab(account.id)}
                      className={`flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm ${currentTab === account.id ? 'bg-brand-600/20 text-brand-200' : 'text-ink-muted hover:text-ink'}`}
                    >
                      <PlatformIcon platform={account.platform} size={14} /> {account.display_name}
                    </button>
                  ))}
                </div>
                {selectedAccounts.map((account) => {
                  const isActive = currentTab === account.id
                  if (!isActive) return null
                  const payload = variants[account.id] ?? {}
                  const patch = (key: string, value: unknown) => setVariants((current) => ({ ...current, [account.id]: { ...(current[account.id] ?? {}), [key]: value } }))
                  return (
                    <div key={account.id} className="space-y-3">
                      <p className="text-xs text-ink-muted">
                        {platformLabel(account.platform)} — seuls les champs réellement acceptés par l’API sont proposés.
                        {account.capabilities?.publish_public === false && ' Publication publique indisponible pour ce compte (audit requis).'}
                      </p>
                      {'title' in payload && <Field label="Titre (100 caractères max)"><Input value={String(payload.title ?? '')} onChange={(event) => patch('title', event.target.value)} /></Field>}
                      {'description' in payload && <Field label="Description YouTube (5000 octets max)"><Textarea value={String(payload.description ?? '')} onChange={(event) => patch('description', event.target.value)} /></Field>}
                      {'caption' in payload && <Field label="Légende (2200 caractères max)"><Textarea value={String(payload.caption ?? '')} onChange={(event) => patch('caption', event.target.value)} /></Field>}
                      {Array.isArray(payload.tags) && <Field label="Tags YouTube (30 max)"><Input value={(payload.tags as string[]).join(', ')} onChange={(event) => patch('tags', event.target.value.split(',').map((tag) => tag.trim()).filter(Boolean).slice(0, 30))} /></Field>}
                      {'privacy' in payload && (
                        <Field label="Confidentialité">
                          <Select value={String(payload.privacy)} onChange={(event) => patch('privacy', event.target.value)}>
                            {account.platform === 'youtube' ? (
                              <>
                                <option value="private">Privée</option>
                                <option value="unlisted">Non répertoriée</option>
                                <option value="public" disabled={account.capabilities?.publish_public === false}>Publique (audit requis)</option>
                              </>
                            ) : (
                              <>
                                <option value="SELF_ONLY">Privée (SELF_ONLY)</option>
                                <option value="PUBLIC_TO_EVERYONE" disabled={account.capabilities?.publish_public === false}>Publique (audit requis)</option>
                              </>
                            )}
                          </Select>
                        </Field>
                      )}
                      {'category_id' in payload && <Field label="Catégorie YouTube (ID)"><Input value={String(payload.category_id ?? '')} onChange={(event) => patch('category_id', event.target.value)} /></Field>}
                      {'made_for_kids' in payload && (
                        <label className="flex items-center gap-2 text-sm">
                          <input type="checkbox" className="h-4 w-4 accent-brand-500" checked={Boolean(payload.made_for_kids)} onChange={(event) => patch('made_for_kids', event.target.checked)} />
                          Contenu destiné aux enfants
                        </label>
                      )}
                      {'contains_synthetic_media' in payload && (
                        <label className="flex items-center gap-2 text-sm">
                          <input type="checkbox" className="h-4 w-4 accent-brand-500" checked={Boolean(payload.contains_synthetic_media)} onChange={(event) => patch('contains_synthetic_media', event.target.checked)} />
                          Contenu synthétique ou modifié (IA)
                        </label>
                      )}
                      {'is_aigc' in payload && (
                        <label className="flex items-center gap-2 text-sm">
                          <input type="checkbox" className="h-4 w-4 accent-brand-500" checked={Boolean(payload.is_aigc)} onChange={(event) => patch('is_aigc', event.target.checked)} />
                          Marquer comme généré par IA (TikTok)
                        </label>
                      )}
                      {'disable_comment' in payload && (
                        <div className="flex flex-wrap gap-4 text-sm">
                          <label className="flex items-center gap-2"><input type="checkbox" className="h-4 w-4 accent-brand-500" checked={Boolean(payload.disable_comment)} onChange={(event) => patch('disable_comment', event.target.checked)} /> Commentaires désactivés</label>
                          <label className="flex items-center gap-2"><input type="checkbox" className="h-4 w-4 accent-brand-500" checked={Boolean(payload.disable_duet)} onChange={(event) => patch('disable_duet', event.target.checked)} /> Duets désactivés</label>
                          <label className="flex items-center gap-2"><input type="checkbox" className="h-4 w-4 accent-brand-500" checked={Boolean(payload.disable_stitch)} onChange={(event) => patch('disable_stitch', event.target.checked)} /> Stitch désactivé</label>
                        </div>
                      )}
                      {'share_to_feed' in payload && (
                        <label className="flex items-center gap-2 text-sm">
                          <input type="checkbox" className="h-4 w-4 accent-brand-500" checked={Boolean(payload.share_to_feed)} onChange={(event) => patch('share_to_feed', event.target.checked)} />
                          Partager aussi dans le feed Instagram
                        </label>
                      )}
                    </div>
                  )
                })}
              </>
            )}
          </Card>
        </div>
      </div>

      <Modal open={preview} title="Prévisualisation (simulation visuelle)" onClose={() => setPreview(false)}>
        <div className="grid gap-4 sm:grid-cols-3">
          {platforms.map((platform) => (
            <PreviewCard key={platform} platform={platform} media={chosenMedia} accounts={selectedAccounts.filter((account) => account.platform === platform)} payload={variants[selectedAccounts.find((account) => account.platform === platform)?.id ?? ''] ?? {}} />
          ))}
          {platforms.length === 0 && <p className="text-sm text-ink-muted">Sélectionnez des comptes pour afficher la simulation.</p>}
        </div>
      </Modal>
    </div>
  )
}

function PreviewCard({ platform, media, accounts, payload }: { platform: string; media?: Media; accounts: Account[]; payload: Payload }) {
  const caption = String(payload.caption ?? payload.description ?? '')
  const title = String(payload.title ?? '')
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-black text-white">
      <div className="relative aspect-[9/16] bg-gradient-to-br from-zinc-800 to-black">
        {media?.thumbnail_path ? <img src={`/api/media/${media.id}/thumbnail`} alt="" className="h-full w-full object-cover opacity-80" /> : <div className="flex h-full items-center justify-center text-xs text-zinc-500">Aucun aperçu</div>}
        <div className="absolute bottom-0 left-0 right-0 space-y-1 bg-gradient-to-t from-black/90 to-transparent p-3 text-left">
          {title && <p className="text-sm font-semibold">{title}</p>}
          <p className="line-clamp-3 text-xs text-zinc-200">{caption}</p>
          <div className="flex flex-wrap gap-1 pt-1">
            {accounts.map((account) => (
              <span key={account.id} className="flex items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 text-[10px]">
                <PlatformIcon platform={account.platform} size={10} /> {account.display_name}
              </span>
            ))}
          </div>
        </div>
        <span className="absolute right-2 top-2 rounded bg-black/60 px-1.5 py-0.5 text-[10px] uppercase">{platformLabel(platform)}</span>
      </div>
    </div>
  )
}


