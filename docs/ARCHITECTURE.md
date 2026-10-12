# Architecture de SocialDock

Objectif : une application **locale, mono-processus, inspectable**. Pas de
microservices, pas de file de messages externe, pas de conteneur : un processus
Python, une base SQLite, une interface React compilée servie par ce même processus.

## 1. Vue d'ensemble

```
frontend/  React 18 + TypeScript + Vite + Tailwind + TanStack Query + React Router
   │  appels HTTP relatifs (/api/...) — jamais de localhost codé en dur
   ▼
backend/socialdock/
   api/         12 routeurs FastAPI · 80 opérations · schémas Pydantic (schemas.py)
   services/    logique métier testable, sans dépendance à FastAPI
   connectors/  abstraction plateforme + 4 implémentations
   models.py    SQLAlchemy 2.0 (typage Mapped[...]) · 13 tables
   database.py  moteur, session, WAL, migrations
   security.py  chiffrement des secrets, jeton local, expurgation des journaux
   main.py      fabrique d'application, CORS local, montage de l'interface
   __main__.py  CLI : run · stop · migrate · doctor
```

Le serveur **sert aussi l'interface compilée** (`frontend/dist`) : une seule
origine, donc aucun CORS en production et aucun proxy à maintenir. En
développement, Vite (`:5173`) proxyse `/api` vers `:8000`.

## 2. Modèle de données (13 tables)

| Table | Rôle | Points clés |
|---|---|---|
| `accounts` | Comptes de réseaux sociaux | `mode` (`real`/`demo`), `capabilities` JSON, `credential_blob` chiffré, `external_id` |
| `account_groups` | Regroupements d'affichage | — |
| `media_assets` | Bibliothèque médias | `sha256` **unique** (anti-doublon), métadonnées ffprobe, `probe_status` |
| `posts` | Une composition (titre, description, hashtags, média, série) | — |
| `post_targets` | **Une cible = un compte = une publication** | statut, `idempotency_key` unique, `remote_id`, verrous, `requires_user_action` |
| `publish_attempts` | Journal de chaque tentative | phase, code HTTP, détail **expurgé** des secrets |
| `post_templates` | Modèles réutilisables | — |
| `series` | Séries / épisodes | — |
| `watched_folders` | Dossiers surveillés (Studio IA) | empreintes déjà vues |
| `analytics_samples` | Métriques par compte et par jour | upsert quotidien, `_source` de la donnée |
| `oauth_states` | États OAuth en cours | consommation unique, expiration, `code_verifier` PKCE |
| `app_settings` | Préférences et intégrations | jeton d'ingestion |
| `event_log` | Journal applicatif | affiché dans la page Diagnostics |

Migrations Alembic : `migrations/versions/6abf8800da6d_*.py`
(`alembic upgrade head` exécuté automatiquement au démarrage).

## 3. La cible de publication : une machine à états explicite

```
        ┌────────► cancelled
        │
draft ──► ready ──► scheduled ──► uploading ──► processing ──► publishing ──► published
                     │  ▲                                             │       published_private
                     │  └────────────── failed ◄──────┐               │
                     ▼                                │               ▼
              waiting_for_user ◄──────────────────────┴──────────► uncertain
```

* Toute transition illégale est refusée (`services/states.py`, testé).
* `uncertain` = « la plateforme a peut-être publié, mais la confirmation a été
  perdue ». **Aucune relance automatique** : un humain tranche
  (`POST /api/posts/targets/{id}/resolve`).
* `published_private` = publié mais non public (projet YouTube non audité,
  TikTok `SELF_ONLY`). `requires_user_action` est alors `true`.

### Idempotence

Trois garde-fous (`services/publisher.py`, tous testés) :

1. **`remote_id` présent** → on ne republie pas, on vérifie le statut distant.
2. **Verrou** par cible (`locked_by`, `lock_expires_at`) : un second worker
   n'exécute pas la même cible.
3. **`idempotency_key` unique** par (publication, compte, horaire) : la même
   composition ne crée jamais deux envois.

Après un crash, `SchedulerEngine.recover_interrupted()` libère les verrous
périmés et bascule les envois interrompus en `uncertain` — jamais en
« à republier ».

## 4. Le scheduler

`services/scheduler.py` : boucle `asyncio` dans le processus FastAPI, tick
configurable (`SOCIALDOCK_SCHEDULER_TICK_SECONDS`, 5 s par défaut).

* Sélection des cibles échues **en SQL** (dates stockées en UTC, affichées en
  `Europe/Paris`).
* Retries avec backoff exponentiel (`2^min(tentatives, 4)` minutes), plafond
  `SOCIALDOCK_MAX_PUBLISH_ATTEMPTS` (3).
* Détection des tâches en retard (`GET /api/scheduler/missed`).
* Persistance totale : un redémarrage ne perd aucune tâche.

## 5. Les connecteurs

Interface `connectors/base.py::SocialConnector` :

```
get_capabilities · begin_auth · handle_auth_callback · refresh_auth
get_account_info · validate_media · validate_post · upload_media
publish · get_publish_status · get_post_url · get_analytics · disconnect
```

Quatre implémentations :

| Connecteur | Réalité | Particularités |
|---|---|---|
| `YouTubeConnector` | YouTube Data API v3 | upload **résumable** (session, chunks 256 KB, reprise sur `308 Range`), `status.publishAt`, verrouillage privé des projets non audités, quota 10 000 unités/j |
| `InstagramConnector` | Graph API (Instagram Login) | conteneur `media_type=REELS`, upload `rupload.facebook.com` (en-têtes `offset`/`file_size`), polling `status_code`, `media_publish`, quota 24 h |
| `TikTokConnector` | Content Posting API v2 | chunks 5–64 Mo (`≤ 1000`), `privacy_level`, `creator_info`, mode **inbox** (brouillon), restriction `SELF_ONLY` des apps non auditées |
| `DemoConnector` | Aucune | cinq scénarios déterministes ; relaie la matrice de capacités **réelle** de la plateforme avec mention du mode démo |

Erreurs typées : `PermanentError` (échec définitif), `RetriableError`
(réessai avec backoff), `AmbiguousError` → `uncertain`. Aucun appel
d'endpoint privé, aucun cookie de session, aucune technique anti-détection.

## 6. API

80 opérations sur 70 chemins (`GET /docs/api` une fois le serveur lancé) :
`/api/media`, `/api/posts`, `/api/posts/targets/*`, `/api/calendar`,
`/api/accounts`, `/api/oauth/{platform}/*`, `/api/scheduler/*`, `/api/stats/*`,
`/api/watchers/*`, `/api/ingest/*`, `/api/settings`, `/api/diagnostics`.

Sécurité applicative :

* Écoute `127.0.0.1` par défaut, port configurable.
* Middleware d'origine : toute requête portant un `Origin` non autorisé est
  refusée (403).
* Jeton `X-SocialDock-Token` requis pour `/api/ingest/*` (comparaison à temps
  constant) et périmètre limité aux dossiers surveillés.
* Secrets chiffrés en base (`security.py::SecretVault`), journaux expurgés
  (`redact`).

## 7. Frontend

* `src/lib/api.ts` : client HTTP en URLs relatives, erreurs typées.
* `src/lib/i18n.ts` : dictionnaire `fr` (défaut) et `en`, typé par une interface
  commune `Dictionary` (aucune divergence silencieuse possible).
* `src/lib/compose.ts` : logique du composeur extraite et testée
  (limites par plateforme, génération de variantes, hashtags).
* Pages : Tableau de bord, Calendrier, Publications (composeur), Bibliothèque,
  Comptes, Statistiques, Automatisations, Paramètres, Diagnostics.
  Aucune page n'est factice : les modules incomplets affichent leur état réel.
* TanStack Query pour le cache et l'invalidation ; aucune donnée simulée
  injectée dans l'interface (les « comptes de démonstration » sont explicites et
  marqués `mode="demo"` côté base).

## 8. Décisions assumées

| Choix | Pourquoi |
|---|---|
| SQLite en WAL | Zéro administration, transactions fiables, suffisant pour un poste local |
| Scheduler dans le processus | Un seul exécutable à lancer ; la persistance en base couvre les crashs |
| Pas de LLM | La génération de variantes est déterministe et explicable ; Studio IA reste optionnel et externe |
| FFmpeg/FFprobe externes | Pas de ré-encodage systématique ; l'import n'est jamais bloquant |
| Connecteurs sans cache d'API privée | Respect strict des conditions des plateformes |
