import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import StatusBadge from '../StatusBadge'

describe('StatusBadge', () => {
  it('affiche le libellé français de chaque état métier', () => {
    render(<StatusBadge status="waiting_for_user" />)
    expect(screen.getByText('Action humaine requise')).toBeInTheDocument()
  })

  it('distingue publié et publié en privé', () => {
    const { rerender } = render(<StatusBadge status="published" />)
    expect(screen.getByText('Publiée')).toBeInTheDocument()
    rerender(<StatusBadge status="published_private" />)
    expect(screen.getByText('Publiée (privée)')).toBeInTheDocument()
  })

  it('signale explicitement un statut incertain', () => {
    render(<StatusBadge status="uncertain" />)
    expect(screen.getByText('Statut incertain')).toBeInTheDocument()
  })
})
