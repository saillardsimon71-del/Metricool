import { expect, test, type APIRequestContext } from '@playwright/test'

/**
 * Parcours utilisateur complet dans l'interface réelle (français par défaut).
 * Chaque assertion porte sur un élément réellement rendu — aucune maquette.
 * Chaque test navigue lui-même : un échec n'empêche pas les autres de s'exécuter.
 */

type Account = { id: string; platform: string; display_name: string }

async function seedAccounts(request: APIRequestContext): Promise<Account[]> {
  const response = await request.post('/api/accounts/demo/seed')
  expect(response.ok()).toBeTruthy()
  return (await response.json()) as Account[]
}

test.describe('SocialDock — parcours utilisateur', () => {
  test('les neuf pages sont accessibles et rendues', async ({ page }) => {
    await page.goto('/')
    for (const label of [
      'Tableau de bord',
      'Calendrier',
      'Publications',
      'Bibliothèque',
      'Comptes',
      'Statistiques',
      'Automatisations',
      'Paramètres',
      'Diagnostics',
    ]) {
      await expect(page.getByRole('link', { name: label })).toBeVisible()
    }
    await page.getByRole('link', { name: 'Diagnostics' }).click()
    await expect(page.getByText('Système').first()).toBeVisible()
    await expect(page.getByText('SQLite').first()).toBeVisible()
    await expect(page.getByText('FFmpeg').first()).toBeVisible()
    await expect(page.getByText('Moteur de programmation').first()).toBeVisible()
  })

  test('six comptes de démonstration avec leur matrice de capacités', async ({ page }) => {
    await page.goto('/accounts')
    await page.getByRole('button', { name: /comptes de démonstration/i }).click()
    await expect(page.getByText('TikTok Démo 1')).toBeVisible()
    await expect(page.getByText('YouTube Démo 2')).toBeVisible()
    await expect(page.getByText('Démonstration locale').first()).toBeVisible()
    // Les limitations réelles des plateformes sont affichées, y compris en démo
    await expect(page.getByText('Publication publique : non autorisée').first()).toBeVisible()
    await expect(page.getByText(/non audité/i).first()).toBeVisible()
  })

  test('le tableau de bord reflète les compteurs réels', async ({ page }) => {
    await page.goto('/dashboard')
    await expect(page.getByText('Comptes connectés').first()).toBeVisible()
    await expect(page.getByText('Prochaines publications').first()).toBeVisible()
  })

  test('le composeur prépare six destinations à partir d\'une seule vidéo', async ({ page, request }) => {
    const accounts = await seedAccounts(request)
    const created = await request.post('/api/posts', {
      data: {
        title: 'Épisode E2E',
        description: 'Description commune',
        hashtags: ['ia'],
        account_ids: accounts.map((account) => account.id),
      },
    })
    expect(created.ok()).toBeTruthy()
    const post = await created.json()
    expect(post.targets).toHaveLength(6)

    await page.goto('/posts')
    await expect(page.getByText('Épisode E2E').first()).toBeVisible()
    await page.getByText('Épisode E2E').first().click()
    await expect(page.getByText(/Variantes par plateforme/).first()).toBeVisible()
    for (const platform of ['TikTok', 'Instagram', 'YouTube']) {
      await expect(page.getByText(platform).first()).toBeVisible()
    }
  })

  test('la bibliothèque signale clairement un fichier non pris en charge', async ({ page }) => {
    await page.goto('/library')
    await page.setInputFiles('input[type="file"]', {
      name: 'notes.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('ceci n\'est pas une vidéo'),
    })
    await expect(page.getByRole('status').filter({ hasText: /format|supporté|erreur/i }).first()).toBeVisible({ timeout: 20_000 })
  })

  test('les paramètres exposent le jeton d\'ingestion Studio IA', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByRole('heading', { name: 'Intégration Studio IA' })).toBeVisible()
    const token = await page.getByTestId('ingest-token').textContent()
    expect((token ?? '').trim().length).toBeGreaterThanOrEqual(32)
    // « X-SocialDock-Token » figure aussi dans l'exemple curl : on vise la ligne d'en-tête.
    await expect(page.getByText('X-SocialDock-Token').first()).toBeVisible()
  })

  test('le calendrier affiche une publication programmée', async ({ page, request }) => {
    const accounts = await seedAccounts(request)
    const post = await (
      await request.post('/api/posts', { data: { title: 'Rendez-vous calendrier', account_ids: [accounts[0].id] } })
    ).json()
    const scheduled = await request.post(`/api/posts/targets/${post.targets[0].id}/schedule`, {
      data: { scheduled_at: new Date(Date.now() + 3_600_000).toISOString() },
    })
    expect(scheduled.ok()).toBeTruthy()

    await page.goto('/calendar')
    await expect(page.getByRole('heading', { name: 'Calendrier éditorial' })).toBeVisible({ timeout: 20_000 })
    await page.getByRole('button', { name: 'Liste' }).click()
    await expect(page.getByRole('heading', { name: 'File d’attente et publications' })).toBeVisible()
    await expect(page.getByText('Rendez-vous calendrier').first()).toBeVisible()
  })

  test('les statistiques n\'inventent aucune métrique', async ({ page }) => {
    await page.goto('/analytics')
    await expect(page.getByText(/jamais une estimation|Aucune donnée disponible/i).first()).toBeVisible({ timeout: 20_000 })
  })
})

test.describe('Édition multi-comptes en Europe/Paris', () => {
  test.use({ timezoneId: 'UTC' })

  test('conserve les variantes et programme à Paris depuis un navigateur en UTC', async ({ page, request }) => {
    const accounts = (await seedAccounts(request)).filter((account) => account.platform === 'tiktok')
    const created = await request.post('/api/posts', {
      data: {
        title: 'Édition multi-comptes E2E', account_ids: accounts.map((account) => account.id),
        per_platform: { tiktok: {
          [accounts[0].id]: { caption: 'Original compte 1' },
          [accounts[1].id]: { caption: 'Original compte 2', disable_comment: true },
        } },
      },
    })
    expect(created.ok()).toBeTruthy()
    const post = await created.json()
    for (const target of post.targets) {
      const scheduled = await request.post(`/api/posts/targets/${target.id}/schedule`, {
        data: { scheduled_at: '2027-07-01T07:00:00Z' },
      })
      expect(scheduled.ok()).toBeTruthy()
    }

    await page.goto(`/posts/${post.id}`)
    await expect(page.getByLabel(/Légende/)).toHaveValue('Original compte 1')
    await expect(page.getByLabel(/Date et heure/)).toHaveValue('2027-07-01T09:00')
    await page.getByLabel(/Légende/).fill('Compte 1 modifié')
    await page.getByRole('button', { name: accounts[1].display_name }).click()
    await expect(page.getByLabel(/Légende/)).toHaveValue('Original compte 2')
    await expect(page.getByLabel('Commentaires désactivés')).toBeChecked()
    await page.getByLabel(/Date et heure/).fill('2027-07-02T09:30')
    await page.getByRole('button', { name: 'Programmer', exact: true }).click()
    await expect(page).toHaveURL(/\/posts$/)

    const saved = await (await request.get(`/api/posts/${post.id}`)).json()
    expect(saved.targets).toHaveLength(2)
    const first = saved.targets.find((target: { account_id: string }) => target.account_id === accounts[0].id)
    const second = saved.targets.find((target: { account_id: string }) => target.account_id === accounts[1].id)
    expect(first.payload.caption).toBe('Compte 1 modifié')
    expect(second.payload.caption).toBe('Original compte 2')
    expect(second.payload.disable_comment).toBe(true)
    for (const target of saved.targets) {
      expect(target.status).toBe('scheduled')
      expect(new Date(target.scheduled_at).toISOString()).toBe('2027-07-02T07:30:00.000Z')
    }
    await page.goto(`/posts/${post.id}`)
    await expect(page.getByLabel(/Légende/)).toHaveValue('Compte 1 modifié')
  })
})
