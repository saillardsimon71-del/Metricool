# Tests

Trois niveaux, tous exécutés en CI (`.github/workflows/ci.yml`) :

| Niveau | Outil | Nombre | Commande |
|---|---|---|---|
| Backend (unitaires + intégration API) | pytest | **144** | `PYTHONPATH=backend python -m pytest` |
| Frontend (composants + logique) | Vitest + Testing Library | **34** | `cd frontend && npm test` |
| Bout en bout (navigateur réel) | Playwright | **8 scénarios** | `cd frontend && npx playwright test` |

Couverture backend : **75 %** des lignes de `backend/socialdock`
(`--cov=backend/socialdock`).

## 1. Backend

```bash
pip install -r requirements-dev.txt
PYTHONPATH=backend python -m pytest                 # tout
PYTHONPATH=backend python -m pytest tests/test_publisher.py -v
PYTHONPATH=backend python -m pytest -m ffmpeg       # seulement les tests FFmpeg
PYTHONPATH=backend python -m pytest --cov=backend/socialdock --cov-report=term-missing
```

Configuration : `pytest.ini` (`pythonpath = backend`, marqueurs `ffmpeg` et
`integration`). Les fixtures sont dans `tests/conftest.py` :

* `settings` : répertoire de données **temporaire** par test (aucune écriture
  dans `%LOCALAPPDATA%`) — l'appel à `get_settings()` est réinitialisé pour
  chaque test ;
* `session` : session SQLAlchemy isolée ;
* `client` : `TestClient` sur l'application réelle, scheduler désactivé ;
* `sample_video` : vraie vidéo 1080×1920, 4 s, H.264 + AAC générée par FFmpeg ;
* `FakeConnector` : connecteur programmable (succès, privé, échec, incertain,
  action humaine) qui journalise ses appels.

### Ce que les tests vérifient réellement

| Fichier | Garanties |
|---|---|
| `test_states.py` | transitions autorisées/refusées de la machine à états |
| `test_security.py` | chiffrement/déchiffrement, expurgation des secrets, comparaison à temps constant, protection de chemin |
| `test_ffprobe.py` / `test_media_service.py` | métadonnées, miniatures, anti-doublon SHA-256, validation par plateforme, filtres et pagination |
| `test_publisher.py` | idempotence, refus de republication en `uncertain`, mode assisté, journal expurgé, verrous |
| `test_scheduler.py` | sélection des tâches échues, verrous, reprise après crash, backoff, tâches en retard, boucle asyncio |
| `test_connector_youtube.py` | upload résumable avec reprise `308`, `publishAt`, verrou privé sans audit, quota, erreurs |
| `test_connector_instagram.py` | conteneur + `rupload` + polling + publication, compte personnel refusé, quota, jeton longue durée |
| `test_connector_tiktok.py` | plan de chunks, `privacy_level` restreint, mode inbox, erreurs, PKCE |
| `test_oauth_flow.py` | state unique/expiré, PKCE, chiffrement, aucun jeton renvoyé par l'API |
| `test_api.py` | 17 scénarios HTTP (composition, calendrier, suppression confirmée, diagnostics, batch) |
| `test_watcher.py` / `test_ingest_api.py` | dossiers surveillés, stabilité, jeton et périmètre d'ingestion |
| `test_analytics.py` | aucune métrique inventée, séries, classement, export CSV |
| `test_migrations.py` | `alembic upgrade head` sur une base vierge, aller-retour downgrade/upgrade |
| `test_acceptance.py` | parcours complet : 6 destinations, 5 issues différentes, aucune double publication après redémarrage |

> Les réponses des plateformes sont **simulées** via `httpx.MockTransport`, à
> partir de la documentation officielle. Cela prouve que le code traite
> correctement les formats et les erreurs ; cela **ne prouve pas** qu'un vrai
> jeton OAuth fonctionne — voir [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

## 2. Frontend

```bash
cd frontend
npm ci
npm test                      # 34 tests Vitest (jsdom + Testing Library)
npm run test:watch
npx eslint src e2e --ext .ts,.tsx --max-warnings 0
npx tsc -b --pretty false
```

Suites : logique du composeur (`compose.test.ts`, 8), formatage (`format.test.ts`, 3),
badges de statut (3), puis les pages Composer, Library, Posts et Calendar (5
chacune). Les appels réseau sont interceptés par `src/test/mockApi.ts` — aucune
donnée n'est inventée dans les composants eux-mêmes.

## 3. Bout en bout (Playwright)

```bash
cd frontend
npm ci && npm run build
npx playwright install chromium
npx playwright test           # démarre FastAPI sur 127.0.0.1:8000 avec une base temporaire
```

Les scénarios (`e2e/parcours.spec.ts`) s'exécutent contre le **serveur réel** :
FastAPI sert l'interface compilée et l'API sur le même port, avec
`SOCIALDOCK_DATA_DIR` pointant sur un dossier temporaire. Ils couvrent :
navigation des neuf pages, création des six comptes de démonstration et matrice
de capacités, tableau de bord, composeur à six destinations, refus d'un fichier
non média, jeton d'ingestion, calendrier, absence de statistiques inventées.

> Playwright télécharge les navigateurs depuis son CDN : cette étape nécessite un
> accès réseau et n'est donc pas exécutable dans tous les environnements. Elle
> est réalisée en CI.

## 4. Lint, types et sécurité

```bash
python -m ruff check backend tests                  # règles E/F/I/UP/B/SIM
cd frontend && npx eslint src e2e --ext .ts,.tsx --max-warnings 0
cd frontend && npx tsc -b --pretty false            # TypeScript strict
python -m pip_audit --requirement requirements.txt
cd frontend && npm audit --omit=dev --audit-level=high
```

## 5. Avant de committer

```bash
python -m ruff check backend tests && \
PYTHONPATH=backend python -m pytest && \
cd frontend && npx eslint src e2e --ext .ts,.tsx --max-warnings 0 && \
npx tsc -b --pretty false && npm test && npm run build
```
