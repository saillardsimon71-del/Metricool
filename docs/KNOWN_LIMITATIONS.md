# Limitations connues

Document volontairement inconfortable : il liste ce que SocialDock **ne fait
pas**, et pourquoi. Une limitation non écrite est une promesse implicite.

## 1. Aucune intégration n'est validée contre l'API réelle

C'est la limite principale du projet.

* Les connecteurs YouTube, Instagram et TikTok sont **implémentés** sur la base
  de la documentation officielle et **testés** sur des réponses simulées
  (`httpx.MockTransport`).
* Ils n'ont **jamais été exécutés avec de vrais identifiants** : la création des
  applications développeur (Google Cloud, Meta, TikTok for Developers) et leurs
  revues/audits exigent un humain, un compte et du temps de validation.
* Conséquence : un détail d'implémentation (nom de champ, en-tête, format de
  date) peut différer de l'API réelle. Les tests prouvent la logique, pas la
  conformité du premier appel.

**Ce qu'il faut pour lever cette limite** : suivre
[CONNECT_YOUTUBE.md](CONNECT_YOUTUBE.md),
[CONNECT_INSTAGRAM.md](CONNECT_INSTAGRAM.md) et
[CONNECT_TIKTOK.md](CONNECT_TIKTOK.md), connecter un compte réel, publier une
vidéo de test, puis consigner le résultat. Le reste du parcours
(composition, planification, verrous, journal, statistiques) est déjà testé.

## 2. Audits et revues des plateformes

| Plateforme | Contrainte | Effet |
|---|---|---|
| YouTube | Projets créés après le 28/07/2020 verrouillés en privé sans audit | Publications en `published_private` tant que l'audit n'est pas déclaré |
| TikTok | App non auditée : `SELF_ONLY` + 5 utilisateurs/24 h | Pas de publication publique ; mode boîte de réception recommandé |
| Instagram | Compte **Professionnel** obligatoire, app en mode développement limitée aux testeurs | Compte personnel refusé ; publication publique après revue Meta |

Ces contraintes sont **externes** : aucun code ne peut les contourner, et
SocialDock ne cherche pas à le faire.

## 3. Programmation

* YouTube est la seule des trois plateformes à offrir une programmation native
  (`publishAt`) — utilisée par SocialDock.
* Instagram et TikTok n'en offrent **aucune** : c'est le scheduler local qui
  publie. **L'ordinateur doit donc être allumé et SocialDock lancé** à l'heure
  prévue. Les tâches manquées sont détectées et signalées au redémarrage, mais
  rien ne peut être publié rétroactivement à l'heure exacte.

## 4. Statistiques

* **TikTok** : la Content Posting API n'expose aucune métrique → la page
  Statistiques n'affiche **rien** pour TikTok (jamais de valeur inventée).
* Les métriques sont collectées **à la demande** (`POST /api/stats/collect`) ou
  par le scheduler : il n'y a pas d'historique rétroactif avant la première
  collecte.
* Aucune donnée d'audience globale (abonnés, portée du compte) n'est agrégée :
  seules les métriques par publication fournies par les APIs sont stockées.

## 5. Médias

* **FFmpeg/FFprobe sont externes** : sans eux, l'import fonctionne mais sans
  métadonnées techniques fiables ni miniatures. Un binaire portable
  (`imageio-ffmpeg`) est détecté automatiquement s'il est installé.
* **Pas de ré-encodage automatique** : un fichier non conforme est signalé avec
  les corrections recommandées ; la transformation FFmpeg reste une action
  explicite de l'utilisateur.
* Les originaux ne sont jamais supprimés sans confirmation.
* Pas de montage vidéo, pas de sous-titres automatiques, pas de génération de
  miniature par IA — hors périmètre.

## 6. Périmètre fonctionnel

* Une **vidéo** par publication. Les carrousels Instagram multi-images, les
  Stories et les publications texte ne sont pas implémentés (les contraintes
  sont documentées dans [PLATFORM_FEASIBILITY.md](PLATFORM_FEASIBILITY.md)).
* Pas de boîte de réception de commentaires, pas de réponse aux messages,
  pas de veille concurrentielle.
* Pas de gestion d'équipe : **un seul utilisateur**, une machine. Il n'y a ni
  authentification multi-utilisateurs, ni rôles, ni partage.
* Pas de synchronisation multi-appareils, pas de sauvegarde cloud automatique.
* Pas de LLM intégré : les variantes de description sont générées
  déterministiquement (limites de caractères, hashtags, ton par plateforme).
  L'intégration Studio IA est **optionnelle** et externe.

## 7. Technique

* **SQLite** : excellent pour un poste local ; inadapté à plusieurs processus
  écrivant simultanément ou à un déploiement multi-utilisateurs.
* Le scheduler tourne **dans le processus FastAPI** : arrêter le serveur arrête
  la programmation (les tâches persistent en base).
* **Windows d'abord** : les scripts `install.ps1` / `start.bat` / `stop.bat`
  ciblent Windows. Le backend et les tests fonctionnent sur Linux/macOS (le
  développement et la CI l'attestent), mais l'installation assistée n'y est pas
  fournie.
* Les scripts Windows n'ont **pas pu être exécutés** dans l'environnement de
  développement (Linux) : chaque commande qu'ils appellent a été validée
  individuellement, mais le chemin complet `.ps1` → `.bat` reste à confirmer sur
  une machine Windows.
* Interface en français par défaut ; l'anglais est présent dans le dictionnaire
  i18n mais n'est pas exhaustif.

## 8. Sécurité

* La clé de chiffrement et la base vivent sur le même disque, protégées par le
  compte utilisateur Windows : un attaquant ayant déjà votre session peut les
  lire. Le chiffrement protège contre la copie isolée de la base.
* L'API locale accepte les requêtes sans en-tête `Origin` (nécessaire aux
  scripts et à Studio IA) : la protection repose sur le jeton d'ingestion et sur
  l'écoute `127.0.0.1`.
* Pas de journal d'audit signé, pas de chiffrement au repos géré par SocialDock
  (BitLocker/FileVault s'en chargent).

## 9. Ce qui n'est pas un « faux bouton »

Chaque action de l'interface appelle une API réellement implémentée. Les seuls
éléments explicitement non réels sont les **comptes de démonstration**
(`mode="demo"`), affichés comme tels partout, et le connecteur de démonstration
qui n'effectue aucun appel réseau.
