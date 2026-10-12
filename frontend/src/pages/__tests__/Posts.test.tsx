import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Posts from '../Posts'
import { mockApi } from '../../test/mockApi'
import { ToastProvider } from '../../hooks/useToasts'

const row = (id: string, status: string, extra: Record<string, unknown> = {}) => ({
  target: {
    id, post_id: 'post-1', account_id: 'acc-1', status, scheduled_at: '2026-04-01T09:00:00Z', published_at: null,
    payload: {}, idempotency_key: `key-${id}`, remote_id: null, remote_url: null, attempts_count: 1, next_retry_at: null,
    error_message: null, error_code: null, requires_user_action: status === 'waiting_for_user', user_action_hint: null,
    last_status_check_at: null, created_at: '2026-04-01T08:00:00Z', updated_at: '2026-04-01T08:00:00Z', ...extra,
  },
  post: { id: 'post-1', title: 'Épisode 12' },
  account: { id: 'acc-1', display_name: 'TikTok Démo 1', platform: 'tiktok', mode: 'demo' },
  status_label: status,
})

const renderPosts = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider><MemoryRouter><Posts /></MemoryRouter></ToastProvider>
    </QueryClientProvider>,
  )
}

describe('Posts', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('liste les publications avec leur compte et leur statut', async () => {
    mockApi({ '/api/posts': { items: [row('t1', 'scheduled'), row('t2', 'failed', { error_message: 'Quota dépassé' })], total: 2 } })
    renderPosts()
    expect(await screen.findAllByText('Épisode 12')).toHaveLength(2)
    expect(screen.getByText('Quota dépassé')).toBeInTheDocument()
    expect(screen.getByText('2 publication(s)')).toBeInTheDocument()
  })

  it('filtre par statut en interrogeant l’API', async () => {
    const { calls } = mockApi({ '/api/posts': { items: [], total: 0 } })
    const user = userEvent.setup()
    renderPosts()
    await screen.findByText('Aucune publication')
    await user.selectOptions(screen.getByLabelText('Statut'), 'uncertain')
    await waitFor(() => expect(calls.some((call) => call.path.includes('status=uncertain'))).toBe(true))
  })

  it('ouvre la résolution d’un statut incertain et envoie la décision', async () => {
    const { calls } = mockApi({
      '/api/posts': { items: [row('t1', 'uncertain')], total: 1 },
      '/api/posts/targets/t1/resolve': { ok: true },
    })
    const user = userEvent.setup()
    renderPosts()
    await user.click(await screen.findByRole('button', { name: 'Résoudre' }))
    expect(await screen.findByText(/ne republie jamais automatiquement/)).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Issue constatée'), 'published')
    await user.click(screen.getByRole('button', { name: 'Valider' }))
    await waitFor(() => {
      const call = calls.find((item) => item.path.includes('/resolve'))
      expect(call?.body).toMatchObject({ resolution: 'published' })
    })
  })

  it('propose le mode assisté pour une publication non automatisable', async () => {
    const { calls } = mockApi({ '/api/posts': { items: [row('t1', 'draft')], total: 1 }, '/api/posts/targets/t1/assisted': {} })
    const user = userEvent.setup()
    renderPosts()
    await user.click(await screen.findByRole('button', { name: 'Mode assisté' }))
    await waitFor(() => expect(calls.some((call) => call.path.endsWith('/assisted'))).toBe(true))
  })

  it('affiche un état vide', async () => {
    mockApi({ '/api/posts': { items: [], total: 0 } })
    renderPosts()
    expect(await screen.findByText('Aucune publication')).toBeInTheDocument()
  })
})
