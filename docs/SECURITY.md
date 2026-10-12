# Sécurité

SocialDock manipule des jetons d'accès à vos réseaux sociaux : c'est la ressource
la plus sensible du projet. Ce document décrit les mesures implémentées, ce
qu'elles couvrent, et ce qui reste de votre responsabilité.

## 1. Modèle de menace

| Menace | Réponse implémentée |
|---|---|
| Un autre processus local lit la base et récupère les jetons | Jetons **chiffrés** (Fernet) avec une clé stockée hors base, permissions restreintes |
| Un site web malveillant appelle l'API locale depuis le navigateur (DNS rebinding / CSRF) | Middleware d'**origine** : toute requête avec un `Origin` non autorisé est refusée (403) |
| Un processus local fait lire à SocialDock un fichier arbitraire du disque | API d'ingestion protégée par **jeton** + périmètre limité aux dossiers surveillés |
| Rejeu d'un état OAuth (CSRF sur le callback) | `state` **persistant**, consommation unique, expiration (10 min), vérification de la plateforme |
| Interception du code d'autorisation | **PKCE** (S256) sur les plateformes qui le supportent |
| Fuite de jeton dans les journaux ou les messages d'erreur | **Expurgation** systématique (`security.redact`) avant écriture |
| Vol de mot de passe de réseau social | **Aucun mot de passe n'est jamais demandé** : OAuth 2.0 uniquement |
| Publication en double après un incident | Idempotence (`remote_id`, verrous, `uncertain`) — voir [ARCHITECTURE.md](ARCHITECTURE.md) |
| Exposition du service sur le réseau | Écoute `127.0.0.1` uniquement par défaut |

## 2. Chiffrement des secrets

* `backend/socialdock/security.py::SecretVault` chiffre les identifiants OAuth
  avec **Fernet** (AES-128-CBC + HMAC-SHA256, `cryptography`).
* La clé est générée au premier lancement dans
  `%LOCALAPPDATA%\SocialDock\secrets\secret.key`, avec permissions restreintes
  (`0600` sous POSIX ; ACL utilisateur sous Windows).
* `accounts.credential_blob` ne contient donc **jamais** un jeton en clair —
  vérifié par `tests/test_oauth_flow.py::test_callback_reussit_et_chiffre_le_jeton`.
* Le jeton de l'API d'ingestion est stocké séparément (`secrets\ingest.token`).

> Limite assumée : la clé et la base vivent sur le même disque, protégées par le
> compte utilisateur Windows. Un attaquant disposant déjà de votre session
> Windows peut lire ces données — comme n'importe quelle application locale.
> Le chiffrement protège contre la copie de la base seule (sauvegarde,
> synchronisation, autre compte).

## 3. OAuth 2.0

* `state` aléatoire (`secrets.token_urlsafe(24)`), persisté en base, **consommé
  une seule fois**, expiré après 10 minutes, lié à la plateforme et au compte.
* **PKCE** : `code_verifier` stocké avec l'état, `code_challenge` S256 envoyé à
  l'autorisation, vérifié à l'échange du code.
* **Scopes minimaux** par plateforme (voir `CONNECT_*.md`) : rien au-delà de
  l'upload, de la publication et de la lecture de vos propres statistiques.
* Rafraîchissement automatique des jetons ; déconnexion = révocation côté
  plateforme + suppression du secret local.
* Tests : `tests/test_oauth_flow.py` (7 tests : démarrage, callback, réutilisation
  refusée, expiration, mauvaise plateforme, erreur transmise, chiffrement).

## 4. Périmètre réseau

* `SOCIALDOCK_HOST=127.0.0.1` par défaut : **rien n'est accessible depuis le
  réseau local**. Pour changer d'interface, il faut le faire explicitement.
* `allowed_origins` : `http://127.0.0.1:5173` et `http://localhost:5173`
  (développement Vite). Toute autre origine portant un en-tête `Origin` est
  refusée — testé par `tests/test_api.py::test_middleware_refuse_les_origines_non_autorisees`.
* Les requêtes **sans** en-tête `Origin` (curl, Studio IA local, scripts) restent
  possibles : c'est volontaire, l'API d'ingestion en dépend.

## 5. API d'ingestion

* Jeton requis (`X-SocialDock-Token`), comparé en **temps constant**.
* Périmètre : répertoire de données + dossiers surveillés déclarés.
  Le répertoire personnel complet n'est **pas** autorisé.
* Résolution du chemin avant comparaison (bloque `../` et liens symboliques
  sortants) ; seuls les formats média sont acceptés.
* Tests : `tests/test_ingest_api.py` (7 tests).

## 6. Journalisation et expurgation

* Les journaux (`%LOCALAPPDATA%\SocialDock\logs\`) et le journal applicatif
  (page Diagnostics) passent par `security.redact`, qui masque les valeurs
  ressemblant à des jetons (`ya29.…`, `IGQ…`, `access_token=…`, etc.).
* La table `publish_attempts.detail` est expurgée avant insertion — testé par
  `tests/test_publisher.py::test_jamais_de_secret_dans_le_journal`.
* Aucun jeton n'est renvoyé par l'API : le schéma de sortie `AccountOut`
  (`backend/socialdock/schemas.py`) ne contient **aucun champ** d'identifiant —
  seuls `status`, `scopes` et `credentials_expire_at` décrivent l'état de la
  connexion. Vérifié par
  `tests/test_oauth_flow.py::test_api_ne_renvoie_jamais_le_jeton`.

## 7. Données et médias

* Les fichiers importés sont **copiés** dans le répertoire de données :
  l'original n'est jamais modifié ni supprimé sans confirmation explicite.
* Aucune transformation FFmpeg n'est appliquée sans demande explicite
  (pas de ré-encodage systématique).
* La suppression d'une publication exige `?confirm=true` (testé).

## 8. Dépendances

* `pip-audit` sur `requirements.txt` et `npm audit --omit=dev --audit-level=high`
  sont exécutés en CI (`.github/workflows/ci.yml`, job `security`).
* Aucun secret versionné : le job vérifie `git ls-files`.
* `.env` est ignoré par Git ; `.env.example` ne contient aucune valeur réelle.

## 9. À faire de votre côté

1. Chiffrez votre disque (BitLocker) : c'est la protection principale d'une
   application locale.
2. Ne partagez jamais `%LOCALAPPDATA%\SocialDock\secrets\`.
3. Révoquez les accès si vous doutez :
   [Google](https://myaccount.google.com/permissions) ·
   [Meta](https://www.facebook.com/settings?tab=business_tools) ·
   [TikTok](https://www.tiktok.com/settings/manage-apps),
   puis **Comptes → Déconnecter** dans SocialDock.
4. Régénérez le jeton d'ingestion après avoir partagé un écran ou une capture
   (**Paramètres → Intégration Studio IA → Régénérer**).

## 10. Ce que SocialDock ne fait pas

* Pas de télémétrie, pas d'analytics tiers, pas d'appel sortant autre que vers
  les APIs officielles des plateformes.
* Pas d'endpoints privés, pas de cookies de session détournés, pas d'automatisation
  d'interface, pas de technique anti-détection.
* Pas de stockage de mots de passe de réseaux sociaux.
* Pas de partage de vos médias avec un serveur intermédiaire.
