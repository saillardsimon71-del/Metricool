import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Library from '../Library'
import { mockApi } from '../../test/mockApi'
import { ToastProvider } from '../../hooks/useToasts'

const mediaItem = {
  id: 'media-1', stored_path: 'a.mp4', original_name: 'a.mp4', display_name: 'Clip vertical 9:16', kind: 'video',
  mime_type: 'video/mp4', size_bytes: 2_500_000, sha256: 'deadbeef', duration_seconds: 45.2, width: 1080, height: 1920,
  fps: 30, video_codec: 'h264', audio_codec: 'aac', has_audio: true, probe_status: 'ok', probe_error: null,
  thumbnail_path: 'deadbeef.jpg', tags: ['vertical'], collections: [], imported_from: 'local:a.mp4', notes: null,
  created_at: '2026-02-01T09:00:00Z',
}

const renderLibrary = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider><Library /></ToastProvider>
    </QueryClientProvider>,
  )
}

describe('Library', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('affiche les métadonnées extraites et les tags', async () => {
    mockApi({ '/api/media': { items: [mediaItem], total: 1 } })
    renderLibrary()
    expect(await screen.findByText('Clip vertical 9:16')).toBeInTheDocument()
    expect(screen.getByText(/1080×1920/)).toBeInTheDocument()
    expect(screen.getByText('#vertical')).toBeInTheDocument()
  })

  it('signale explicitement quand FFmpeg est absent', async () => {
    mockApi({ '/api/media': { items: [{ ...mediaItem, probe_status: 'unavailable', width: null, height: null }], total: 1 } })
    renderLibrary()
    expect(await screen.findByText('analyse indisponible')).toBeInTheDocument()
  })

  it('affiche un état vide explicite', async () => {
    mockApi({ '/api/media': { items: [], total: 0 } })
    renderLibrary()
    expect(await screen.findByText('Bibliothèque vide')).toBeInTheDocument()
  })

  it('ouvre le détail avec la conformité Instagram', async () => {
    const { calls } = mockApi({
      '/api/media': { items: [mediaItem], total: 1 },
      '/api/media/media-1/validate/instagram': {
        platform: 'instagram', platform_label: 'Instagram (Reels)', ok: false,
        issues: [{ key: 'size', label: 'Taille', message: 'Fichier trop volumineux : 400 Mo (maximum 300 Mo).' }],
        warnings: [], info: [], notes: ['Compte Professionnel requis'], caption_limit: 2200, ratio: '9:16', probe_status: 'ok',
      },
      '/api/media/media-1/refresh': mediaItem,
    })
    const user = userEvent.setup()
    renderLibrary()
    await user.click(await screen.findByText('Clip vertical 9:16'))
    expect(await screen.findByText(/Fichier trop volumineux/)).toBeInTheDocument()
    await waitFor(() => expect(calls.some((call) => call.path.includes('/validate/instagram'))).toBe(true))
  })

  it('propose une zone de dépôt pour l’import', async () => {
    mockApi({ '/api/media': { items: [], total: 0 } })
    renderLibrary()
    expect(await screen.findByText(/Déposez vos fichiers ici/)).toBeInTheDocument()
  })
})
