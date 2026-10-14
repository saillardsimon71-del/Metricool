# Faisabilité par plateforme (état réel des APIs, octobre 2026)

Ce document explique **ce que chaque API autorise** et comment SocialDock s'y
conforme. Il existe pour éviter la principale déception des outils de
publication : promettre une capacité que la plateforme refuse.

Sources officielles consultées :

* YouTube Data API v3 — `videos.insert` et son historique de révisions :
  <https://developers.google.com/youtube/v3/docs/videos/insert>,
  <https://developers.google.com/youtube/v3/revision_history>
* Instagram Platform (Graph API) — objets média et publication :
  <https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media/>
* TikTok for Developers — Content Posting API :
  <https://developers.tiktok.com/doc/content-posting-api-get-started>

---

## 1. YouTube

| Capacité | Réalité | Conséquence dans SocialDock |
|---|---|---|
| Upload vidéo | ✅ `videos.insert` (upload résumable) | Implémenté, chunks 256 KB, reprise sur `308 Range` |
| Publication publique immédiate | ⚠️ **Seulement après audit du projet API** | `publish_public=false` tant que l'audit n'est pas déclaré ; toute publication est marquée `published_private` |
| Publication programmée native | ✅ `status.publishAt` | Utilisée (valable uniquement avec `privacyStatus=private` sur une vidéo jamais publiée) |
| Shorts | ✅ vidéo verticale/carrée ≤ 3 min | Détection du format + recommandations |
| Statistiques | ✅ `videos.list?part=statistics` | Vues, likes, commentaires |
| Suppression à distance | ❌ non exposée | Non proposé dans l'interface |

**Le point bloquant** — depuis la révision du 28 juillet 2020, « les vidéos
téléversées via `videos.insert` par des **projets API non audités** créés après
cette date sont verrouillées en **privé** ». L'audit de conformité YouTube
(formulaire « YouTube API Services Audit ») lève ce verrou.
Procédure : [CONNECT_YOUTUBE.md](CONNECT_YOUTUBE.md).

**Quota** : 10 000 unités/jour/projet par défaut ; `videos.insert` coûte
1 600 unités → **≈ 6 uploads/jour** avec un quota standard, davantage après
extension de quota. `search.list` coûte 100 unités.

**Limites de fichier** : 256 Go ou 12 h par vidéo.

**Erreurs gérées** : `invalidPublishAt`, `uploadLimitExceeded`,
`youtubeSignupRequired`, `forbiddenPrivacySetting`, `quotaExceeded`
(réessayable), `rejected` avec `rejectionReason` (échec définitif, message
conservé).

## 2. Instagram (Reels)

| Capacité | Réalité | Conséquence |
|---|---|---|
| Publication de Reels | ✅ conteneur `media_type=REELS` puis `media_publish` | Implémenté (2 étapes + polling) |
| Type de compte | ⚠️ **Professionnel (Business ou Créateur) obligatoire** | Un compte personnel est refusé avec un message explicite |
| Upload du fichier | ✅ upload résumable `rupload.facebook.com` ou `video_url` publique | Résumable par défaut (aucun hébergement requis) |
| Publication programmée native | ❌ **inexistante** | La programmation est gérée par le scheduler local de SocialDock |
| Statistiques | ✅ `insights` (vues, likes, portée…) | Collecte quotidienne |
| Suppression à distance | ✅ `DELETE /{media-id}` | Non utilisé (prudence) |

**Deux voies d'authentification** :

* **Instagram Login** (`graph.instagram.com`) — scopes
  `instagram_business_basic` + `instagram_business_content_publish`,
  **sans Page Facebook**. C'est la voie retenue par SocialDock.
* **Facebook Login** (`graph.facebook.com`) — scopes `instagram_basic`,
  `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`.
  Les noms courts (`instagram_basic`, etc.) sont dépréciés depuis le
  27 janvier 2025 au profit des noms longs.

**Contraintes Reels** : MOV/MP4 (atome `moov` en tête), H.264/HEVC, AAC ≤ 48 kHz,
23–60 fps, largeur ≤ 1920 px, ratio 0.01:1–10:1 (9:16 recommandé),
**3 s à 15 min**, **300 Mo**. Story : vidéo 60 s / 100 Mo, image JPEG 8 Mo.
Légende ≤ 2200 caractères.

**Quota** : `GET /{ig-user-id}/content_publishing_limit` (≈ 50 publications/24 h
par compte). SocialDock lit ce quota avant de publier.

**Erreurs gérées** : `2207026` (format invalide), `2207052` (récupération
impossible), `2207003` (téléchargement trop lent), `2207010` (légende), statut de
conteneur `ERROR`/`EXPIRED` (24 h), polling recommandé 1×/minute pendant 5 min.

## 3. TikTok

| Capacité | Réalité | Conséquence |
|---|---|---|
| Publication directe | ⚠️ **Apps non auditées : `SELF_ONLY` et 5 utilisateurs/24 h** | Sans audit, SocialDock publie en `SELF_ONLY` et le signale (`published_private`) |
| Brouillon en boîte de réception | ✅ scope `video.upload` | **Mode assisté autorisé** : l'utilisateur termine dans l'app TikTok |
| Source du fichier | `FILE_UPLOAD` (chunks) ou `PULL_FROM_URL` (domaine vérifié) | `FILE_UPLOAD` par défaut |
| Publication programmée native | ❌ non exposée | Scheduler local |
| Statistiques | ❌ non disponibles dans la Content Posting API | **Aucune statistique TikTok n'est affichée** — jamais inventée |

**Chunks** : 5–64 Mo, dernier chunk jusqu'à 128 Mo, ≤ 1000 chunks, fichiers
< 5 Mo en un seul chunk ; l'URL d'upload expire après 1 h. Au-delà de
1000 × 64 Mo (~64 Go) SocialDock **refuse explicitement** plutôt que d'envoyer un
plan invalide.

**Publication** : `POST /v2/post/publish/video/init/` avec `post_info`
(`title` ≤ 2200 unités UTF-16, `privacy_level` ∈
`PUBLIC_TO_EVERYONE` / `MUTUAL_FOLLOW_FRIENDS` / `FOLLOWER_OF_CREATOR` /
`SELF_ONLY`, `disable_comment/duet/stitch`, `video_cover_timestamp_ms`,
`is_aigc`) et `source_info`. Puis `POST /v2/post/publish/status/fetch/` jusqu'à
`PUBLISH_COMPLETE` ou `FAILED` (avec `fail_reason`).

**Avant tout envoi**, SocialDock appelle `/v2/post/publish/creator_info/query/`
pour connaître `creator_username`, `privacy_level_options` et
`max_video_post_duration_sec` (3 min en général, plafond API 10 min) — et
n'utilise **que** les niveaux de confidentialité réellement autorisés.

**Erreurs gérées** : `unaudited_client_can_only_post_to_private_accounts`,
`reached_active_user_cap`, `spam_risk_too_many_posts`,
`privacy_level_option_mismatch`, `url_ownership_unverified`,
`rate_limit_exceeded` (6 req/min sur `init` → réessayable).

**Médias** : 4 Go max, MP4/MOV/WebM, H.264/H.265/VP8/VP9, 23–60 fps, 360–4096 px.

---

## 4. Synthèse honnête

| Opération | YouTube | Instagram | TikTok |
|---|---|---|---|
| Connexion OAuth | ✅ conçu + implémenté | ✅ conçu + implémenté | ✅ conçu + implémenté |
| Upload vidéo | ✅ résumable | ✅ `rupload` | ✅ chunks |
| Publication publique | ⚠️ après audit | ✅ compte Pro | ⚠️ après audit |
| Publication privée / brouillon | ✅ privé | — | ✅ `SELF_ONLY` / inbox |
| Programmation native | ✅ `publishAt` | ❌ | ❌ |
| Statistiques réelles | ✅ | ✅ | ❌ |
| **Validé contre l'API réelle** | ❌ | ❌ | ❌ |

**Aucune de ces intégrations n'a été exécutée contre l'API réelle** : il faut des
identifiants d'application développeur que seul vous pouvez créer. Tout le
parcours est implémenté et testé sur des réponses API simulées fidèles à la
documentation (voir [TESTING.md](TESTING.md)) ; il reste à le valider avec vos
clés — la procédure est décrite dans les trois guides `CONNECT_*.md`.

## 5. Ce que SocialDock ne fera jamais

* Utiliser des endpoints privés ou non documentés.
* Réutiliser des cookies de session de navigateur pour contourner l'API.
* Employer des techniques anti-détection, de rotation d'empreinte ou de proxy résidentiel.
* Publier plus vite que les quotas ou les limites anti-spam des plateformes.
* Inventer une statistique absente d'une API.

Si une capacité n'est pas autorisée, SocialDock **le dit** et propose le mode
assisté (voir [CONNECT_TIKTOK.md](CONNECT_TIKTOK.md) pour l'exemple le plus
contraint).
