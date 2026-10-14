# Connecter Instagram

Objectif : publier des **Reels** depuis SocialDock via l'API officielle
(Instagram Login, `graph.instagram.com`), sans Page Facebook.

## 1. Prérequis côté Instagram

1. Un compte Instagram **Professionnel** (Business ou Créateur) —
   *Paramètres → Type de compte → Passer à un compte professionnel*.
   Un compte personnel est **refusé par l'API** ; SocialDock affiche alors un
   message explicite plutôt qu'un échec opaque.
2. Le compte doit être lié à une Page Facebook **ou** utilisé via Instagram Login
   (SocialDock utilise la seconde voie).

## 2. Créer l'application Meta

1. Allez sur <https://developers.facebook.com/> → **Mes applications → Créer une application**.
2. Cas d'usage : **« Autre » → « Business »** (ou « Aucun » selon l'interface du moment).
3. Dans **Ajouter un produit**, ajoutez **Instagram** (Instagram API / Instagram Login).
4. **Paramètres → Base** : copiez l'**ID de l'application** et la **clé secrète**.
5. **Instagram → API Setup** → *Allowed redirect URIs for OAuth* : ajoutez
   `http://127.0.0.1:8000/api/oauth/instagram/callback`.
6. **App Review** : pour un usage personnel avec votre propre compte en mode
   développement, ajoutez votre compte comme **testeur**
   (*Rôles → Testeurs*). La publication en mode « Live » exige une revue Meta.

## 3. Renseigner SocialDock

```ini
SOCIALDOCK_META_APP_ID=1234567890123456
SOCIALDOCK_META_APP_SECRET=abcdef0123456789abcdef0123456789
SOCIALDOCK_META_API_VERSION=v23.0
SOCIALDOCK_OAUTH_REDIRECT_BASE=http://127.0.0.1:8000
```

Puis **Comptes → votre compte Instagram → Connecter**.

### Scopes demandés

| Scope | Usage |
|---|---|
| `instagram_business_basic` | lire l'identité du compte professionnel |
| `instagram_business_content_publish` | créer un conteneur média et le publier |

Rien d'autre : pas d'accès aux messages, aux pages, aux publicités ni aux données
d'audience d'autres comptes.

## 4. Ce que fait SocialDock à la publication

1. `POST /{ig-user-id}/media` avec `media_type=REELS`, la légende (≤ 2200
   caractères, hashtags inclus) et `upload_type=resumable` → obtient un
   **conteneur**.
2. Envoie la vidéo par **upload résumable** :
   `POST https://rupload.facebook.com/ig-api-upload/v{version}/{container_id}`
   avec les en-têtes `offset`, `file_size` et `Authorization: OAuth {token}`.
3. Interroge le conteneur (`status_code`) jusqu'à `FINISHED`
   (`IN_PROGRESS` → on attend ; `ERROR`/`EXPIRED` → échec explicite).
4. `POST /{ig-user-id}/media_publish` → identifiant du média publié.
5. Lit le `permalink` pour stocker l'URL publique.

**Alternative `video_url`** : si vous renseignez
`SOCIALDOCK_INSTAGRAM_PUBLIC_BASE_URL`, SocialDock fournit une URL publique au
lieu d'uploader. Ce mode est **désactivé par défaut** : il exigerait d'exposer
vos vidéos sur Internet.

## 5. Contraintes à respecter (sinon refus de la plateforme)

| Élément | Valeur |
|---|---|
| Conteneur | MP4 ou MOV, atome `moov` en tête (faststart) |
| Codec | H.264 ou HEVC, audio AAC ≤ 48 kHz |
| Images/seconde | 23–60 |
| Largeur | ≤ 1920 px |
| Ratio | 0.01:1 à 10:1 (9:16 recommandé) |
| Durée | 3 s à 15 min |
| Taille | ≤ 300 Mo |
| Légende | ≤ 2200 caractères |

La page **Bibliothèque → détails du média** affiche la conformité par plateforme
avant publication, avec les recommandations de correction.

## 6. Quota et jeton

* `GET /{ig-user-id}/content_publishing_limit` : quota glissant sur 24 h
  (≈ 50 publications). SocialDock le lit et le journalise.
* Le jeton court (1 h) est échangé contre un **jeton longue durée** (60 jours) à
  la connexion, puis renouvelé automatiquement (`ig_refresh_token`).

## 7. Programmation

Instagram **n'offre aucune programmation native**. C'est le scheduler local de
SocialDock qui déclenche la publication à l'heure prévue : l'ordinateur doit
donc être allumé et SocialDock lancé au moment voulu (les tâches manquées sont
signalées dans **Tableau de bord** et `/api/scheduler/missed`).

## 8. Pannes fréquentes

| Symptôme | Cause | Solution |
|---|---|---|
| `OAuthException 10` / permission refusée | Compte personnel | Passez le compte en Professionnel |
| `2207026` | Format/codec non supporté | Ré-encodez (H.264 + AAC, MP4 faststart) |
| `2207003` / `2207052` | URL `video_url` inaccessible | Utilisez le mode résumable (par défaut) |
| Conteneur `EXPIRED` | > 24 h avant publication | Relancez la publication |
| `redirect_uri_mismatch` | URI non déclarée | Ajoutez l'URI exacte dans l'app Meta |
| « Application en mode développement » | Compte non testeur | Ajoutez-vous comme testeur |
