# SocialDock — gestionnaire local de réseaux sociaux

**SocialDock** est un gestionnaire de publications pour TikTok, Instagram et YouTube qui
tourne **entièrement sur votre machine Windows** : aucune donnée ne part vers un serveur
tiers, aucun Docker, aucun Postgres, aucun Redis, aucun abonnement.

> Le dépôt s'appelle `Metricool` (nom historique) mais le produit est **SocialDock**.
> Il ne reprend **aucun code** de Metricool, Buffer ou Postiz : l'interface et
> l'architecture sont des implémentations originales, les plateformes citées ne sont
> que des inspirations fonctionnelles.

![Python 3.11](https://img.shields.io/badge/python-3.11+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-local-009688) ![React 18 + TS](https://img.shields.io/badge/React-18_+_TypeScript-61dafb) ![SQLite](https://img.shields.io/badge/SQLite-WAL-orange)

---

## Ce que SocialDock fait réellement

| Fonction | Statut | Preuve |
|---|---|---|
| Composer une vidéo → 6 destinations (2 TikTok, 2 Instagram, 2 YouTube) | **Vérifié** | `tests/test_acceptance.py`, `Composer.test.tsx` |
| Variantes de description par plateforme (limites de caractères, hashtags) | **Vérifié** | `compose.test.ts` (8 tests) |
| Bibliothèque médias : import, SHA-256 anti-doublon, ffprobe, miniatures, lecteur | **Vérifié** | `tests/test_media_service.py` (17 tests) |
| Calendrier mois/semaine/jour/liste/file, glisser-déposer, `Europe/Paris` | **Vérifié** | `tests/test_api.py`, `Calendar.test.tsx` |
| Scheduler persistant : survit au redémarrage, verrous, retries, tâches en retard | **Vérifié** | `tests/test_scheduler.py` (11 tests) |
| Idempotence : jamais de double publication, statut `uncertain` si doute | **Vérifié** | `tests/test_publisher.py` (12 tests) |
| Connecteur YouTube (upload résumable, audit, `publishAt`) | **Implémenté + vérifié sur réponses API simulées** | `tests/test_connector_youtube.py` (13 tests) |
| Connecteur Instagram (conteneur, `rupload`, polling, publication) | **Implémenté + vérifié sur réponses API simulées** | `tests/test_connector_instagram.py` (10 tests) |
| Connecteur TikTok (chunks 5–64 Mo, `privacy_level`, inbox) | **Implémenté + vérifié sur réponses API simulées** | `tests/test_connector_tiktok.py` (12 tests) |
| Mode assisté universel (préparer → copier → publier à la main → enregistrer le lien) | **Vérifié** | `tests/test_api.py::test_mode_assiste_puis_finalisation` |
| Statistiques : uniquement des données d'API réelles, jamais inventées | **Vérifié** | `tests/test_analytics.py` (8 tests) |
| Intégration Studio IA (dossier surveillé + API d'ingestion à jeton) | **Vérifié** | `tests/test_ingest_api.py` (7 tests) |
| **Publication réelle sur TikTok/Instagram/YouTube** | **Non validée en réel** | Voir [Limitations connues](docs/KNOWN_LIMITATIONS.md) |

**Lecture du tableau** — `Implémenté` = le code existe ; `Vérifié` = un test
automatisé l'exécute ; `Validé en réel` = un appel réussi contre l'API officielle
avec de vrais identifiants. **Aucune fonction de ce projet n'est « validée en réel »** :
les identifiants des applications développeur (Google Cloud, Meta, TikTok for
Developers) doivent être créés par vous. Tout le reste du parcours est prêt et testé.

---

## Démarrage rapide (Windows)

```powershell
# 1. Depuis la racine du dépôt
powershell -ExecutionPolicy Bypass -File .\install.ps1

# 2. Démarrer (ouvre http://127.0.0.1:8000)
.\start.bat

# 3. Arrêter proprement
.\stop.bat
```

Prérequis : **Windows 10/11**, **Python 3.11+** ([python.org](https://www.python.org/downloads/windows/),
cochez *Add python.exe to PATH*), **Node.js 20+** (pour l'interface web),
**FFmpeg** recommandé (analyse des vidéos). Détails : [docs/INSTALL_WINDOWS.md](docs/INSTALL_WINDOWS.md).

Premiers pas dans l'application : **Comptes → « Créer les comptes de démonstration »**.
Ces six comptes simulent localement les cinq issues possibles d'une publication
(succès, privé, échec, incertain, action humaine) — rien n'est envoyé sur Internet.

Développement (Linux/macOS/Windows) :

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
PYTHONPATH=backend python -m socialdock migrate
PYTHONPATH=backend python -m socialdock run          # http://127.0.0.1:8000
cd frontend && npm ci && npm run dev                 # http://127.0.0.1:5173 (proxy /api)
```

---

## Architecture en une image

```
┌────────────────────────────── votre machine Windows ──────────────────────────────┐
│                                                                                   │
│  Navigateur ──► FastAPI (127.0.0.1:8000) ──► SQLite (WAL)                         │
│                    │      │                                                       │
│                    │      ├── Scheduler persistant (verrous, retries, incertains) │
│                    │      ├── Services : médias, publications, statistiques       │
│                    │      └── Connecteurs : YouTube / Instagram / TikTok / démo   │
│                    │                                                              │
│  Studio IA ────► API d'ingestion à jeton  ──┐                                     │
│  (dossier surveillé)                        ├──► FFprobe / FFmpeg                 │
│                                             └──► Bibliothèque médias              │
│  Données : %LOCALAPPDATA%\SocialDock  (base, médias, miniatures, secrets chiffrés) │
└───────────────────────────────────────────────────────────────────────────────────┘
                                        │  HTTPS, OAuth 2.0 + PKCE, scopes minimaux
                                        ▼
                    APIs officielles (Google, Meta, TikTok) — jamais d'endpoint privé
```

Détail complet : [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Documentation

| Document | Contenu |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Couches, modèle de données, machine à états, 80 opérations API |
| [INSTALL_WINDOWS.md](docs/INSTALL_WINDOWS.md) | Installation pas à pas, FFmpeg, autostart, désinstallation |
| [PLATFORM_FEASIBILITY.md](docs/PLATFORM_FEASIBILITY.md) | Ce que chaque API autorise vraiment (quotas, audit, formats) |
| [CONNECT_YOUTUBE.md](docs/CONNECT_YOUTUBE.md) | Projet Google Cloud, scopes, audit, vérification OAuth |
| [CONNECT_INSTAGRAM.md](docs/CONNECT_INSTAGRAM.md) | App Meta, compte Professionnel, `rupload`, quotas |
| [CONNECT_TIKTOK.md](docs/CONNECT_TIKTOK.md) | App TikTok, audit Direct Post, `SELF_ONLY`, mode boîte de réception |
| [STUDIO_AI_INTEGRATION.md](docs/STUDIO_AI_INTEGRATION.md) | Dossier surveillé + API d'ingestion sécurisée |
| [SECURITY.md](docs/SECURITY.md) | Jetons chiffrés, PKCE, périmètre réseau, menaces traitées |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Pannes courantes et commandes de diagnostic |
| [TESTING.md](docs/TESTING.md) | Comment lancer les 143 + 34 + 8 tests |
| [ROADMAP.md](docs/ROADMAP.md) | Suite logique du projet |
| [KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) | Ce qui n'est **pas** fait, et pourquoi |
| [RESUME.md](docs/RESUME.md) | État exact du chantier pour reprendre sans repartir de zéro |

---

## Tests et intégration continue

```bash
PYTHONPATH=backend python -m pytest                 # 143 tests backend (75 % de couverture)
cd frontend && npm test                             # 34 tests Vitest
cd frontend && npx playwright test                  # 8 scénarios E2E (navigateur réel)
python -m ruff check backend tests                  # lint
cd frontend && npx eslint src e2e --ext .ts,.tsx --max-warnings 0
python -m pip_audit --requirement requirements.txt  # audit de vulnérabilités
```

Le workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) exécute tout cela à
chaque push : backend, frontend, sécurité, puis E2E Playwright contre le serveur réel.

---

## Sécurité

* Le serveur n'écoute que `127.0.0.1` (configurable) et refuse les origines inconnues.
* Les jetons OAuth sont chiffrés (Fernet, clé dans `%LOCALAPPDATA%\SocialDock\secrets`,
  permissions restreintes) — jamais en clair en base, jamais dans les journaux
  (expurgation automatique des valeurs sensibles).
* Aucun mot de passe de réseau social n'est demandé : uniquement OAuth 2.0 avec `state`
  persistant et PKCE.
* L'API d'ingestion Studio IA exige un jeton et n'accepte que les dossiers surveillés
  (pas de lecture arbitraire du disque).
* `.env` est ignoré par Git ; `.env.example` documente les variables.

Voir [docs/SECURITY.md](docs/SECURITY.md).

## Licence

Code original de ce dépôt : MIT (voir [LICENSE](LICENSE)). Les marques TikTok,
Instagram et YouTube appartiennent à leurs propriétaires respectifs ; ce projet
n'est affilié à aucun d'eux.
