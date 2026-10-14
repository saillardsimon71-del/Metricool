import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Composer from '../Composer'
import { mockApi } from '../../test/mockApi'
import { ToastProvider } from '../../hooks/useToasts'
import type { Account, Media, Post } from '../../lib/types'

const accounts = ['tiktok', 'instagram', 'youtube'].flatMap((platform, _index) =>
  [1, 2].map((n) => ({
    id: `${platform}-${n}`,
    platform,
    display_name: `${platform} ${n}`,
    mode: 'demo',
    status: 'demo',
    capabilities: { publish_public: platform === 'instagram', restrictions: [], scheduling: false, analytics: true, auth_available: false, publish_video: true, upload: true, assisted_mode: true, requires_review: false, permissions_required: [], permissions_missing: [] },
    permissions_missing: [],
    extra: {},
    scopes: [],
    username: null,
    avatar_url: null,
    external_id: null,
    default_privacy: null,
    default_category_id: null,
    group_id: null,
    is_favorite: false,
    last_verified_at: null,
    credentials_expire_at: null,
    last_error: null,
  } as unknown as Account)),
)

const media = [{
  id: 'media-1', stored_path: 'x.mp4', original_name: 'clip.mp4', display_name: 'clip vertical', kind: 'video',
  mime_type: 'video/mp4', size_bytes: 1_200_000, sha256: 'abc', duration_seconds: 42, width: 1080, height: 1920,
  fps: 30, video_codec: 'h264', audio_codec: 'aac', has_audio: true, probe_status: 'ok', probe_error: null,
  thumbnail_path: 'abc.jpg', tags: ['test'], collections: [], imported_from: null, notes: null, created_at: '2026-01-01T10:00:00Z',
}] as Media[]

const post: Post = {
  id: 'post-1', title: 'Ma vidéo', description: 'Description commune', hashtags: ['original'],
  media_asset_id: 'media-1', thumbnail_media_id: null, series_id: null, episode_number: null,
  language: 'fr', internal_notes: null, template_id: null,
  created_at: '2026-01-01T10:00:00Z', updated_at: '2026-01-01T10:00:00Z',
  targets: [1, 2].map((n) => ({
    id: `target-${n}`, post_id: 'post-1', account_id: `tiktok-${n}`, status: 'scheduled',
    scheduled_at: '2027-07-01T07:00:00Z', published_at: null,
    payload: { caption: `Original TikTok ${n}`, privacy: 'SELF_ONLY', disable_comment: n === 2 },
    idempotency_key: `key-${n}`, remote_id: null, remote_url: null, attempts_count: 0,
    next_retry_at: null, error_message: null, error_code: null, requires_user_action: false,
    user_action_hint: null, last_status_check_at: null,
    created_at: '2026-01-01T10:00:00Z', updated_at: '2026-01-01T10:00:00Z',
  })),
}

const renderComposer = (path = '/posts/new') => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/posts/new" element={<Composer />} />
            <Route path="/posts/:postId" element={<Composer />} />
            <Route path="/posts" element={<p>Liste des publications</p>} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('Composer', () => {
  beforeEach(() => {
    mockApi({
      '/api/accounts': accounts,
      '/api/media': { items: media, total: 1 },
      '/api/posts': { id: 'post-1', title: 'Ma vidéo', description: '', hashtags: [], media_asset_id: 'media-1', thumbnail_media_id: null, series_id: null, episode_number: null, language: 'fr', internal_notes: null, template_id: null, created_at: '2026-01-01T10:00:00Z', updated_at: '2026-01-01T10:00:00Z', targets: [] },
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('affiche les six comptes de démonstration', async () => {
    renderComposer()
    expect(await screen.findByText('tiktok 1')).toBeInTheDocument()
    expect(screen.getByText('youtube 2')).toBeInTheDocument()
  })

  it('génère une variante par compte sélectionné, avec les champs de la plateforme', async () => {
    const user = userEvent.setup()
    renderComposer()
    await screen.findByText('tiktok 1')
    await user.click(screen.getByLabelText(/tiktok 1/i))
    await user.click(screen.getByLabelText(/instagram 1/i))

    expect(await screen.findByText(/Variantes par plateforme \(2\)/)).toBeInTheDocument()
    // Onglet actif = première cible sélectionnée (TikTok) : légende, pas de titre YouTube
    expect(screen.getByLabelText(/Légende \(2200 caractères max\)/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/Titre \(100 caractères max\)/)).not.toBeInTheDocument()

    await user.click(screen.getByLabelText(/youtube 1/i))
    await screen.findByRole('button', { name: /youtube 1/ })
    await user.click(screen.getByRole('button', { name: /youtube 1/ }))
    await waitFor(() => expect(screen.getByLabelText(/Titre \(100 caractères max\)/)).toBeInTheDocument())
  })

  it('propage la description commune et les hashtags dans chaque variante', async () => {
    const user = userEvent.setup()
    renderComposer()
    await screen.findByText('tiktok 1')
    await user.type(screen.getByPlaceholderText('Ma vidéo 9:16'), 'Épisode 12')
    await user.type(screen.getByPlaceholderText('shorts vertical ia'), 'vertical')
    await user.click(screen.getByLabelText(/tiktok 1/i))
    const caption = await screen.findByLabelText(/Légende \(2200 caractères max\)/) as HTMLTextAreaElement
    await waitFor(() => expect(caption.value).toContain('#vertical'))
  })

  it('refuse de programmer sans date et affiche l’erreur', async () => {
    const user = userEvent.setup()
    renderComposer()
    await screen.findByText('tiktok 1')
    await user.click(screen.getByLabelText(/tiktok 1/i))
    fireEvent.click(screen.getByRole('button', { name: /Programmer/ }))
    expect(await screen.findByText(/Choisissez une date et une heure/)).toBeInTheDocument()
  })

  it('désactive l’option publique pour un compte non audité', async () => {
    const user = userEvent.setup()
    renderComposer()
    await screen.findByText('tiktok 1')
    await user.click(screen.getByLabelText(/tiktok 1/i))
    const option = await screen.findByRole('option', { name: /Publique \(audit requis\)/ }) as HTMLOptionElement
    expect(option.disabled).toBe(true)
  })
  it('charge la publication existante et ouvre la variante du premier compte', async () => {
    mockApi({
      '/api/accounts': accounts,
      '/api/media': { items: media, total: 1 },
      '/api/posts/post-1': post,
    })
    const user = userEvent.setup()
    renderComposer('/posts/post-1')
    expect(await screen.findByRole('heading', { name: 'Modifier la publication' })).toBeInTheDocument()
    expect(await screen.findByDisplayValue('Original TikTok 1')).toBeInTheDocument()
    expect(screen.getByLabelText(/tiktok 1/i)).toBeChecked()
    expect(screen.getByLabelText(/tiktok 2/i)).toBeChecked()
    await user.click(screen.getByRole('button', { name: /tiktok 2/i }))
    expect(screen.getByLabelText(/Légende/)).toHaveValue('Original TikTok 2')
  })

  it('modifie une publication multi-comptes existante en conservant les variantes par compte', async () => {
    const { calls } = mockApi({
      '/api/accounts': accounts,
      '/api/media': { items: media, total: 1 },
      '/api/posts/post-1': post,
      '/api/posts/targets/target-1/schedule': post.targets[0],
      '/api/posts/targets/target-2/schedule': post.targets[1],
    })
    const user = userEvent.setup()
    renderComposer('/posts/post-1')
    const caption = await screen.findByDisplayValue('Original TikTok 1')
    await user.clear(caption)
    await user.type(caption, 'TikTok 1 modifié')
    await user.click(screen.getByRole('button', { name: /tiktok 2/i }))
    expect(screen.getByLabelText(/Légende/)).toHaveValue('Original TikTok 2')
    await user.type(screen.getByLabelText('Description commune'), ' modifiée')
    expect(screen.getByLabelText(/Légende/)).toHaveValue('Original TikTok 2')
    const when = screen.getByLabelText(/Date et heure/)
    expect(when).toHaveValue('2027-07-01T09:00')
    fireEvent.change(when, { target: { value: '2027-07-02T09:30' } })
    await user.click(screen.getByRole('button', { name: /Programmer/ }))
    expect(await screen.findByText('Publications programmées')).toBeInTheDocument()
    expect(calls.filter((call) => call.method === 'PATCH')).toEqual([{
      path: '/api/posts/post-1', method: 'PATCH', body: expect.objectContaining({
        account_ids: ['tiktok-1', 'tiktok-2'], propagate_metadata: false,
        per_platform: { tiktok: {
          'tiktok-1': { caption: 'TikTok 1 modifié', privacy: 'SELF_ONLY', disable_comment: false },
          'tiktok-2': { caption: 'Original TikTok 2', privacy: 'SELF_ONLY', disable_comment: true },
        } },
      }),
    }])
    expect(calls.filter((call) => call.method === 'POST')).toEqual([
      { path: '/api/posts/targets/target-1/schedule', method: 'POST', body: { scheduled_at: '2027-07-02T07:30:00.000Z' } },
      { path: '/api/posts/targets/target-2/schedule', method: 'POST', body: { scheduled_at: '2027-07-02T07:30:00.000Z' } },
    ])
  })

  it('affiche une variante restante quand le compte actif est retiré', async () => {
    mockApi({
      '/api/accounts': accounts,
      '/api/media': { items: media, total: 1 },
      '/api/posts/post-1': post,
    })
    const user = userEvent.setup()
    renderComposer('/posts/post-1')
    await screen.findByDisplayValue('Original TikTok 1')
    await user.click(screen.getByRole('button', { name: /tiktok 2/i }))
    await user.click(screen.getByLabelText(/tiktok 2/i))
    expect(screen.getByLabelText(/Légende/)).toHaveValue('Original TikTok 1')
  })

  it('réenregistre sans décaler une publication au second 02:30 de Paris', async () => {
    const autumnPost = { ...post, targets: post.targets.map((target) => ({ ...target, scheduled_at: '2027-10-31T01:30:00Z' })) }
    const { calls } = mockApi({
      '/api/accounts': accounts, '/api/media': { items: media, total: 1 },
      '/api/posts/post-1': autumnPost,
      '/api/posts/targets/target-1/schedule': autumnPost.targets[0],
      '/api/posts/targets/target-2/schedule': autumnPost.targets[1],
    })
    const user = userEvent.setup()
    renderComposer('/posts/post-1')
    await screen.findByDisplayValue('Original TikTok 1')
    expect(screen.getByLabelText(/Date et heure/)).toHaveValue('2027-10-31T02:30')
    await user.click(screen.getByRole('button', { name: /Programmer/ }))
    await screen.findByText('Publications programmées')
    expect(calls.filter((call) => call.method === 'POST').map((call) => call.body)).toEqual([
      { scheduled_at: '2027-10-31T01:30:00.000Z' }, { scheduled_at: '2027-10-31T01:30:00.000Z' },
    ])
  })
})
