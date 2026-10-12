# Dépannage

Premier réflexe, quel que soit le problème :

```powershell
%LOCALAPPDATA%\SocialDock\venv\Scripts\python.exe -m socialdock doctor
```

Le rapport couvre la base de données (intégrité, mode WAL), FFmpeg, le scheduler,
l'espace disque et la configuration de chaque connecteur. Il est aussi disponible
dans l'application : **Diagnostics → Rapport texte**.

## 1. Démarrage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `python n'est pas reconnu` | Python absent du PATH | Réinstallez Python en cochant *Add python.exe to PATH* |
| `Environnement virtuel introuvable` | `install.ps1` non exécuté | Lancez `install.ps1` |
| `address already in use` / port occupé | Un autre service sur 8000 | `set PORT=8010 && .\start.bat`, ou `netstat -ano \| findstr :8000` pour identifier le processus |
| Écran blanc dans le navigateur | Interface non compilée | `cd frontend && npm ci && npm run build` |
| Page inaccessible depuis un autre PC | Volontaire : écoute `127.0.0.1` | Voir [SECURITY.md](SECURITY.md) — l'exposition réseau n'est pas un objectif |
| PowerShell refuse le script | Politique d'exécution | `powershell -ExecutionPolicy Bypass -File .\install.ps1` |

## 2. Base de données

| Symptôme | Solution |
|---|---|
| `database is locked` | Un second serveur tourne : `.\stop.bat`, vérifiez `%LOCALAPPDATA%\SocialDock\socialdock.pid`, relancez |
| Base corrompue après coupure | Le mode WAL limite le risque ; sinon renommez `socialdock.db` et relancez (la base est recréée, **les publications sont perdues**) |
| Réinitialiser sans tout réinstaller | Arrêtez, supprimez `socialdock.db*`, relancez : `start.bat` réapplique les migrations |
| Vérifier l'intégrité | `python -m socialdock doctor` (contrôle `PRAGMA integrity_check`) |

## 3. Médias et FFmpeg

| Symptôme | Cause | Solution |
|---|---|---|
| « FFmpeg : absent » | FFmpeg non installé | Installez FFmpeg, ou `pip install imageio-ffmpeg` dans le venv (binaire portable détecté automatiquement) |
| Métadonnées incomplètes | ffprobe non résolu | Même solution ; puis **Bibliothèque → Réanalyser** |
| Import refusé | Extension non supportée | MP4/MOV/WebM/MKV/AVI/JPEG/PNG/WebP |
| Miniature absente | Pas de FFmpeg | Idem |
| Doublon signalé | Empreinte SHA-256 identique | Normal : **Bibliothèque → Doublons** montre les correspondances |
| Lecture impossible dans le lecteur | Codec absent du navigateur | Utilisez Chrome/Edge (H.264) ou ré-encodez |

## 4. Publications

| Symptôme | Cause | Solution |
|---|---|---|
| Cible bloquée en `incertaine` | Réponse perdue (réseau, timeout) | Vérifiez la plateforme, puis **Cibles → Résoudre** (publiée / échouée / relancer) |
| `published_private` sur YouTube | Projet API non audité | [CONNECT_YOUTUBE.md](CONNECT_YOUTUBE.md) §3 |
| `published_private` sur TikTok | App non auditée (`SELF_ONLY`) | [CONNECT_TIKTOK.md](CONNECT_TIKTOK.md) §3 |
| `waiting_for_user` | Mode assisté ou capacité absente | Suivez la consigne affichée puis enregistrez le lien |
| Échec `quotaExceeded` | Quota quotidien atteint | Attendez le renouvellement ; la cible est réessayée automatiquement |
| Rien ne se publie à l'heure | Ordinateur éteint / serveur arrêté | Les tâches sont détectées en retard au redémarrage (**Tableau de bord**, `/api/scheduler/missed`) |
| Publication en double ? | Ne peut pas arriver sans `remote_id` manquant | Chaque tentative est journalisée : **Diagnostics → Tentatives récentes** |

## 5. Connexion OAuth

| Symptôme | Solution |
|---|---|
| `redirect_uri_mismatch` | Déclarez l'URI exacte `http://127.0.0.1:8000/api/oauth/{plateforme}/callback` chez le fournisseur |
| « La session d'autorisation a expiré » | Relancez la connexion (durée de vie 10 minutes) |
| « Cet état OAuth a déjà été utilisé » | Rechargez la page et recommencez : l'état est à usage unique |
| Fenêtre du navigateur vide | Le serveur n'était pas prêt : réessayez, ou copiez l'URL affichée |
| Jeton expiré | Renouvellement automatique ; sinon **Comptes → Connecter / reconnecter** |

## 6. Intégration Studio IA

| Réponse HTTP | Signification |
|---|---|
| `401` | Jeton `X-SocialDock-Token` absent/invalide → **Paramètres → Intégration Studio IA** |
| `403` | Chemin hors des dossiers autorisés → déclarez le dossier dans **Automatisations → Dossiers surveillés** |
| `404` | Fichier introuvable |
| `400` | Format non supporté |

## 7. Journaux utiles

```powershell
# Journal applicatif (page Diagnostics, ou fichier)
Get-Content "$env:LOCALAPPDATA%\SocialDock\logs\*.log" -Tail 50

# Rapport complet exportable
curl http://127.0.0.1:8000/api/diagnostics/report.txt
```

## 8. Repartir de zéro (sans perdre le code)

```powershell
.\stop.bat
Remove-Item "$env:LOCALAPPDATA%\SocialDock\socialdock.db*"
.\start.bat          # la base est recréée et migrée automatiquement
```

Vos médias (`media\`, `thumbnails\`) sont conservés ; seules les publications et
les connexions sont perdues. Pour tout supprimer, voir
[INSTALL_WINDOWS.md](INSTALL_WINDOWS.md) §9.

## 9. Signaler un problème

Fournissez : la sortie de `python -m socialdock doctor`, la version
(`python -m socialdock --version`), les 50 dernières lignes du journal, et
l'état de la cible concernée (**Diagnostics → Tentatives récentes**).
**N'envoyez jamais** le contenu de `secrets\` ni votre fichier `.env`.
