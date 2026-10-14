import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Calendar from '../Calendar'
import { mockApi } from '../../test/mockApi'
import { ToastProvider } from '../../hooks/useToasts'

const entry = {
  post_target_id: 't1', post_id: 'p1', title: 'Épisode 12', account_id: 'a1', account_name: 'TikTok Démo 1',
  platform: 'tiktok', mode: 'demo', status: 'scheduled' as const, status_label: 'Programmée',
  scheduled_at: '2026-04-15T09:00:00Z', published_at: null, thumbnail: null, remote_url: null,
  requires_user_action: false, error_message: null,
}

const renderCalendar = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider><MemoryRouter><Calendar /></MemoryRouter></ToastProvider>
    </QueryClientProvider>,
  )
}

describe('Calendar', () => {
  beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }); vi.setSystemTime(new Date('2026-04-10T12:00:00Z')) })
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

  it('affiche la publication programmée dans la grille mensuelle', async () => {
    mockApi({ '/api/calendar': { items: [entry], by_day: {}, timezone: 'Europe/Paris' } })
    renderCalendar()
    expect(await screen.findByText('TikTok Démo 1')).toBeInTheDocument()
    expect(screen.getByText('Programmée')).toBeInTheDocument()
  })

  it('place la publication sur son jour à Paris, même après minuit en heure locale', async () => {
    mockApi({ '/api/calendar': { items: [{ ...entry, scheduled_at: '2026-04-15T22:30:00Z' }], by_day: {}, timezone: 'Europe/Paris' } })
    renderCalendar()
    const card = await screen.findByText('TikTok Démo 1')
    const cell = card.closest('article')!.parentElement!.parentElement!
    expect(cell.querySelector('p')).toHaveTextContent('16')
    expect(screen.getByText('00:30')).toBeInTheDocument()
  })

  it('signale une action humaine requise', async () => {
    mockApi({ '/api/calendar': { items: [{ ...entry, requires_user_action: true, status: 'waiting_for_user', status_label: 'Action humaine requise' }], by_day: {} } })
    renderCalendar()
    expect(await screen.findByText('Action humaine requise')).toBeInTheDocument()
  })

  it('affiche un état vide sur une période sans publication', async () => {
    mockApi({ '/api/calendar': { items: [], by_day: {} } })
    renderCalendar()
    expect(await screen.findByText('Aucune publication sur cette période')).toBeInTheDocument()
  })

  it('bascule en vue liste', async () => {
    mockApi({ '/api/calendar': { items: [entry], by_day: {} } })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderCalendar()
    await user.click(await screen.findByRole('button', { name: 'Liste' }))
    expect(await screen.findByRole('link', { name: 'Ouvrir' })).toBeInTheDocument()
  })

  it('reprogramme par glisser-déposer en conservant l’heure', async () => {
    const { calls } = mockApi({
      '/api/calendar': { items: [entry], by_day: {} },
      '/api/calendar/targets/t1/move': { post_target_id: 't1' },
    })
    renderCalendar()
    const card = await screen.findByText('TikTok Démo 1')
    fireEvent.dragStart(card.closest('article')!)
    const cells = document.querySelectorAll('[class*="min-h-\\[120px\\]"]')
    fireEvent.dragOver(cells[10])
    fireEvent.drop(cells[10])
    await waitFor(() => {
      const call = calls.find((item) => item.path.includes('/move'))
      expect(call).toBeDefined()
      expect(new Date(String((call?.body as { scheduled_at: string }).scheduled_at)).getUTCHours()).toBe(9)
    })
  })

  it('préserve l\'heure de Paris quand un déplacement traverse le changement d\'heure', async () => {
    vi.setSystemTime(new Date('2027-03-10T12:00:00Z'))
    const { calls } = mockApi({
      '/api/calendar': { items: [{ ...entry, scheduled_at: '2027-03-27T08:30:00Z' }], by_day: {} },
      '/api/calendar/targets/t1/move': { post_target_id: 't1' },
    })
    renderCalendar()
    const card = await screen.findByText('TikTok Démo 1')
    fireEvent.dragStart(card.closest('article')!)
    const day = screen.getByText('28').parentElement!
    fireEvent.drop(day)
    await waitFor(() => expect(calls.find((call) => call.path.includes('/move'))?.body).toEqual({
      scheduled_at: '2027-03-28T07:30:00.000Z',
    }))
  })
})
