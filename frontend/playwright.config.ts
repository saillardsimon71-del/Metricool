import { defineConfig, devices } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

/**
 * Tests de bout en bout contre le serveur réel : FastAPI sert l'interface
 * compilée (frontend/dist) ET l'API sur le même port, exactement comme
 * l'installation Windows. Aucune donnée de test n'est écrite dans le
 * répertoire utilisateur : SOCIALDOCK_DATA_DIR pointe sur un dossier temporaire.
 */
const dataDir = mkdtempSync(join(tmpdir(), 'socialdock-e2e-'))

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:8000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'python -m uvicorn socialdock.main:app --host 127.0.0.1 --port 8000',
    cwd: '..',
    url: 'http://127.0.0.1:8000/api/health',
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: { PYTHONPATH: 'backend', SOCIALDOCK_DATA_DIR: dataDir, SOCIALDOCK_SCHEDULER_TICK_SECONDS: '1' },
  },
})
