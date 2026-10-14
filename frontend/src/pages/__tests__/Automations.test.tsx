import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import Automations from '../Automations'
import { ToastProvider } from '../../hooks/useToasts'
import { mockApi } from '../../test/mockApi'

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

it('programme les prochains jours selon la date de Paris', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date('2027-07-15T22:30:00Z'))
  const { calls } = mockApi({
    '/api/accounts': [{ id: 'tiktok-1', display_name: 'TikTok 1', platform: 'tiktok' }],
    '/api/media': { items: [{ id: 'media-1', display_name: 'Clip vertical' }] },
    '/api/posts/templates': [], '/api/watchers': [],
    '/api/posts/batch-schedule': { scheduled: [{}] },
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ToastProvider><MemoryRouter><Automations /></MemoryRouter></ToastProvider>
    </QueryClientProvider>,
  )
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  await user.click(await screen.findByRole('checkbox', { name: /Clip vertical/ }))
  await user.click(screen.getByText('TikTok 1'))
  fireEvent.change(screen.getByLabelText('Jours'), { target: { value: '2' } })
  await user.click(screen.getByRole('button', { name: 'Programmer le lot' }))
  await screen.findByText(/publication\(s\) répartie\(s\)/)
  expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
    media_ids: ['media-1'], account_ids: ['tiktok-1'], days: ['2027-07-16', '2027-07-17'],
    times: ['12:30', '18:30'], template_id: null,
  })
})
