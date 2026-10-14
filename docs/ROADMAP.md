# Feuille de route

Ordre volontaire : **valider le réel avant d'élargir**. Ajouter des fonctionnalités
sur des connecteurs non validés produirait du code invérifiable.

## 1. Validation réelle (priorité absolue)

- [ ] Créer l'application Google Cloud, connecter une chaîne, publier une vidéo
      de test → consigner le résultat exact (statut, `remote_id`, URL, journal).
- [ ] Créer l'application Meta, connecter un compte Professionnel, publier un
      Reel → vérifier conteneur, `rupload`, `media_publish`, `permalink`.
- [ ] Créer l'application TikTok, tester le mode **boîte de réception** (sans
      audit), puis demander l'audit pour le Direct Post public.
- [ ] Ajouter à `tests/` un marqueur `integration` exécuté **manuellement** avec
      de vrais identifiants (jamais en CI : pas de secrets dans les workflows).
- [ ] Demander l'audit YouTube et l'extension de quota ; vérifier `publishAt`.
- [ ] Documenter les écarts constatés entre documentation et comportement réel.

## 2. Fiabilisation

- [ ] Suivi de progression d'upload dans l'interface (pourcentages déjà produits
      par `context.report`) via WebSocket ou SSE.
- [ ] File d'attente prioritaire et fenêtre de publication par compte
      (anti-spam configurable).
- [ ] Sauvegarde/restauration chiffrée de la base + des médias
      (`python -m socialdock backup`).
- [ ] Rotation automatique de la clé de chiffrement.
- [ ] Tests de charge du scheduler (milliers de cibles) sur SQLite WAL.

## 3. Fonctionnel

- [ ] Publications **images** (Instagram carrousel, photo simple).
- [ ] Stories Instagram et TikTok (contraintes différentes, déjà documentées).
- [ ] Statistiques de compte (abonnés, portée) si les APIs les exposent.
- [ ] Édition de miniature intégrée (recadrage, texte) via FFmpeg/Canvas.
- [ ] Suggestions de hashtags basées sur l'historique local (sans service externe).
- [ ] Modèles de série avancés : publication récurrente, épisodes auto-numérotés.
- [ ] Notifications Windows natives (le service existe, `services/notifications.py`,
      à brancher sur `win10toast`/Toast WinRT).

## 4. Interface

- [ ] Compléter le dictionnaire i18n anglais.
- [ ] Mode clair/sombre complet (variables CSS déjà présentes).
- [ ] Vue « approbation » pour relire une semaine de publications avant envoi.
- [ ] Raccourcis clavier et navigation accessible (audit ARIA).

## 5. Distribution

- [ ] Installeur Windows (MSIX ou Inno Setup) avec icône et désinstalleur.
- [ ] Vérification des scripts `install.ps1` / `start.bat` / `stop.bat` sur une
      machine Windows vierge (jamais exécutés en environnement Linux).
- [ ] Paquet macOS/Linux (systemd/launchd) si un besoin réel apparaît.
- [ ] Signature de code (évite les avertissements SmartScreen).

## 6. Explicitement hors périmètre

* Multi-utilisateurs, équipes, rôles, facturation.
* Hébergement web, SaaS, compte utilisateur distant.
* Endpoints privés, automatisation d'interface, contournement des quotas.
* Génération de contenu par LLM intégrée (Studio IA reste un outil externe
  optionnel).
* Microservices, orchestrateur, base distribuée : l'application est locale.
