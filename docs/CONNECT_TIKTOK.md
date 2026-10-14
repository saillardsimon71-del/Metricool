# Connecter TikTok

La Content Posting API de TikTok est la plus contraignante des trois : une
application **non auditée** ne peut publier qu'en **`SELF_ONLY`** (visible par
vous seul) et est limitée à **5 utilisateurs par 24 h**. Ce document explique
comment obtenir l'accès, et surtout **l'alternative autorisée** que SocialDock
met en œuvre pendant ce temps.

## 1. Créer l'application

1. <https://developers.tiktok.com/> → **Manage apps → Connect an app**.
2. Renseignez le nom, l'URL du site (une page de présentation suffit) et
   l'**URL de redirection** : `http://127.0.0.1:8000/api/oauth/tiktok/callback`.
3. Dans **Products**, ajoutez **Content Posting API**.
4. Copiez la **Client Key** et la **Client Secret**.

## 2. Renseigner SocialDock

```ini
SOCIALDOCK_TIKTOK_CLIENT_KEY=awxxxxxxxxxxxxxxx
SOCIALDOCK_TIKTOK_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SOCIALDOCK_OAUTH_REDIRECT_BASE=http://127.0.0.1:8000
```

Puis **Comptes → votre compte TikTok → Connecter**.

### Scopes demandés

| Scope | Usage |
|---|---|
| `user.info.basic` | identifier le compte |
| `user.info.profile` | afficher le nom d'utilisateur et l'avatar |
| `video.publish` | **Direct Post** (publication sans intervention manuelle) |
| `video.upload` | **Upload vers la boîte de réception** (brouillon à terminer dans l'app) |

Le flux OAuth utilise **PKCE** (`code_challenge` S256) et un `state` persistant
consommé une seule fois.

## 3. Deux modes de publication

### Mode « Direct Post » (`video.publish`)

`POST /v2/post/publish/video/init/` → envoi des chunks →
`POST /v2/post/publish/status/fetch/` jusqu'à `PUBLISH_COMPLETE`.

* **Application non auditée** : `privacy_level` est forcé à `SELF_ONLY`, et la
  publication est enregistrée comme **`published_private`** avec une action
  requise. SocialDock ne prétend jamais que la vidéo est publique.
* **Application auditée** : `PUBLIC_TO_EVERYONE` est possible si
  `creator_info.privacy_level_options` l'autorise.

### Mode « Boîte de réception » (`video.upload`) — l'alternative autorisée

La vidéo est déposée dans la boîte de réception du créateur : TikTok notifie
l'utilisateur, qui **termine la publication dans l'application officielle**
(légende, confidentialité, publication).

C'est exactement le **mode assisté** de SocialDock :

1. la cible passe en `waiting_for_user` avec une consigne explicite ;
2. vous ouvrez TikTok, la vidéo est déjà là, vous validez ;
3. dans SocialDock : **Cibles → Enregistrer le lien / statut**.

Ce mode respecte les règles de la plateforme (aucune automatisation de
l'interface, aucun endpoint privé) et reste utilisable **sans audit** — c'est la
voie recommandée pour un usage personnel. Choisissez-le dans le composeur
(option « Mode boîte de réception » du compte TikTok).

## 4. Demander l'audit (Direct Post public)

1. Dans le portail développeur, soumettez l'app à **review** pour la
   Content Posting API : description de l'usage, vidéo de démonstration,
   politique de confidentialité, URL de support.
2. TikTok vérifie notamment : consentement explicite de l'utilisateur, respect
   des quotas, absence de publication automatique non sollicitée.
3. Après approbation, déclarez-le dans SocialDock :
   **Comptes → case « Audit réussi »** (`extra.audit_passed`).
   `privacy_level` pourra alors être `PUBLIC_TO_EVERYONE`.

## 5. Règles techniques respectées par SocialDock

| Élément | Règle | Implémentation |
|---|---|---|
| Taille des chunks | 5–64 Mo (dernier ≤ 128 Mo) | plan calculé, fichiers < 5 Mo en un seul chunk |
| Nombre de chunks | ≤ 1000 | refus explicite au-delà (~64 Go) |
| `title` | ≤ 2200 unités UTF-16 | troncature contrôlée |
| `privacy_level` | uniquement ceux de `privacy_level_options` | lecture préalable de `creator_info` |
| Durée | ≤ `max_video_post_duration_sec` | validation avant publication |
| Débit sur `init` | 6 req/min/jeton | erreur `rate_limit_exceeded` traitée comme réessayable |
| URL d'upload | expire après 1 h | réinitialisation si expiration |
| Médias | MP4/MOV/WebM, H.264/H.265/VP8/VP9, 23–60 fps, 360–4096 px, ≤ 4 Go | validation locale (ffprobe) |

`is_aigc` est transmis à `true` lorsque la publication provient d'un flux
Studio IA — c'est une exigence de transparence de TikTok pour les contenus
générés par IA.

## 6. Statistiques

La Content Posting API **ne fournit pas de statistiques**. SocialDock n'affiche
donc **aucune métrique TikTok** plutôt que d'en inventer : la page Statistiques
indique explicitement que la plateforme ne les expose pas.

## 7. Pannes fréquentes

| Symptôme | Cause | Solution |
|---|---|---|
| `unaudited_client_can_only_post_to_private_accounts` | App non auditée | Mode `SELF_ONLY` (automatique) ou mode boîte de réception |
| `reached_active_user_cap` | > 5 utilisateurs/24 h (non audité) | Attendez 24 h ou demandez l'audit |
| `privacy_level_option_mismatch` | Niveau non autorisé pour ce compte | SocialDock n'utilise que les niveaux annoncés |
| `spam_risk_too_many_posts` | Publications trop rapprochées | Espacez les publications |
| `url_ownership_unverified` | `PULL_FROM_URL` sur domaine non vérifié | Utilisez `FILE_UPLOAD` (par défaut) |
| `rate_limit_exceeded` | > 6 `init`/min | Réessai automatique avec backoff |
| `FAILED` avec `file_format_check_failed` | Codec/conteneur refusé | Ré-encodez en H.264/MP4 |
