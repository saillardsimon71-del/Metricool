# Reprendre le chantier sans repartir de zéro

Document écrit pour qu'une autre session (ou vous-même dans six mois) puisse
continuer immédiatement.

## 1. État au 12 octobre 2026

* Dépôt : `https://github.com/saillardsimon71-del/Metricool`
* Branche de travail : `arena/fc95127f-metricool` (issue de `main`, commit initial
  `1f3d9e7`)
* Commits successifs :

| SHA | Contenu |
|---|---|
| `7bc35d6` | Fondations backend : configuration, base SQLite (WAL), 13 modèles SQLAlchemy, sécurité (Fernet, expurgation), journalisation |
| `7f18e7c` | Connecteurs YouTube/Instagram/TikTok/démo, scheduler persistant, API FastAPI complète |
| `3ac28d5` | Interface React/TypeScript (9 pages) + 34 tests Vitest |
| `291cb14` | 143 tests pytest + 9 correctifs révélés par ces tests |
| `808b1c5` | CI GitHub Actions, CLI `socialdock`, scripts Windows, ESLint, E2E Playwright |
| *(ce commit)* | Documentation complète (README + 13 documents) |

## 2. Ce qui est terminé et vérifié

```bash
python -m ruff check backend tests        # All checks passed
PYTHONPATH=backend python -m pytest       # 144 passed (couverture 75 %)
cd frontend && npx eslint src e2e --ext .ts,.tsx --max-warnings 0   # 0 problème
cd frontend && npx tsc -b --pretty false  # aucun diagnostic
cd frontend && npm test                   # 34 passed
cd frontend && npm run build              # build OK
python -m pip_audit --requirement requirements.txt   # No known vulnerabilities
cd frontend && npm audit --omit=dev       # 0 vulnerabilities
```

Vérifications « réelles » effectuées, pas seulement des tests :

* serveur démarré puis arrêté proprement via le CLI
  (`python -m socialdock run` / `stop`) : `SocialDock arrêté proprement` ;
* interface compilée servie par FastAPI : `/`, `/calendar`, `/assets/*.js`
  → 200 ;
* `python -m socialdock doctor` : base OK (WAL), FFmpeg absent dans cet
  environnement, scheduler arrêté, connecteurs non configurés listés ;
* `alembic upgrade head` sur base vierge, puis downgrade/upgrade.

## 3. Ce qui reste à faire (ordre conseillé)

1. **Valider en réel** — voir [ROADMAP.md](ROADMAP.md) §1. C'est la seule chose
   qui manque pour qualifier le produit de « gestionnaire local utilisable en
   production ». Aucune ligne de code n'est bloquante : il faut des identifiants
   d'application développeur.
2. **Exécuter les scripts Windows** sur une machine Windows vierge
   (`install.ps1`, `start.bat`, `stop.bat`) — non exécutables sous Linux.
3. **Lancer Playwright** avec navigateurs (`npx playwright install chromium`) :
   les scénarios sont écrits et typés, ils s'exécutent en CI.
4. Vérifier le premier run de `.github/workflows/ci.yml` sur GitHub et corriger
   d'éventuels écarts d'environnement.

## 4. Repères de code

| Besoin | Fichier |
|---|---|
| Ajouter une plateforme | `backend/socialdock/connectors/` (hériter de `SocialConnector`) + `registry.py` |
| Modifier la machine à états | `backend/socialdock/services/states.py` (+ `tests/test_states.py`) |
| Comprendre l'idempotence | `backend/socialdock/services/publisher.py` (+ `tests/test_publisher.py`) |
| Changer le scheduler | `backend/socialdock/services/scheduler.py` (+ `tests/test_scheduler.py`) |
| Ajouter une route | `backend/socialdock/api/*.py` + schéma dans `schemas.py` + test dans `tests/test_api.py` |
| Ajouter une migration | `alembic revision --autogenerate -m "…"` (script_location = `migrations`) |
| Ajouter une page | `frontend/src/pages/` + route dans `App.tsx` + libellé dans `lib/i18n.ts` + test |
| Composeur (limites/variantes) | `frontend/src/lib/compose.ts` (+ `__tests__/compose.test.ts`) |

## 5. Pièges déjà rencontrés (à ne pas répéter)

* **SQLite renvoie des `datetime` naïfs** : toute comparaison Python avec
  `utcnow()` doit passer par `models.as_utc()`. Deux bugs de production sont
  nés de là (verrou du scheduler, expiration OAuth).
* `npx tsc -b` renvoie **0 tout en affichant des diagnostics** : lire la sortie,
  pas seulement le code de retour.
* Les tests marqués `ffmpeg` sont **sautés silencieusement** sans binaire ;
  `conftest._ensure_ffmpeg()` résout `imageio-ffmpeg` automatiquement.
* `migrations/env.py` utilisait la base par défaut : il honore désormais
  `sqlalchemy.url`. Sans cela, un test de migration écrit dans
  `%LOCALAPPDATA%`.
* Le scheduler travaille dans **sa propre session** : après `run_tick()`, un test
  doit `session.expire_all()` avant de relire les statuts.
* `account.extra` vaut `None` sur un objet non persisté : utiliser
  `(account.extra or {})`.
* ESLint 10 exige la **flat config** (`eslint.config.js`).
* Les limites de caractères des plateformes se comptent parfois en **unités
  UTF-16** (TikTok) : ne pas utiliser `len()` naïvement.

## 6. Commandes utiles

```bash
# Backend
PYTHONPATH=backend python -m socialdock migrate
PYTHONPATH=backend python -m socialdock run --port 8000 --no-browser
PYTHONPATH=backend python -m socialdock doctor
PYTHONPATH=backend python -m pytest tests/test_scheduler.py -v

# Frontend
cd frontend && npm run dev          # http://127.0.0.1:5173 (proxy /api → :8000)
cd frontend && npm run build        # dist servi ensuite par FastAPI

# Diagnostic rapide d'un compte
curl http://127.0.0.1:8000/api/diagnostics/report.txt
```
