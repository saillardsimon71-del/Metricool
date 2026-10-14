# Installation sur Windows

SocialDock est une application **locale** : tout s'installe dans votre session
utilisateur, sans droits administrateur, sans Docker, sans service cloud.

## 1. Prérequis

| Élément | Version | Vérification | Obligatoire ? |
|---|---|---|---|
| Windows | 10 ou 11 | — | oui |
| Python | 3.11 ou plus | `python --version` | oui |
| Node.js | 20 ou plus | `node --version` | pour l'interface web |
| FFmpeg / FFprobe | 6+ | `ffmpeg -version` | recommandé |
| Git | — | `git --version` | pour cloner le dépôt |

* Python : <https://www.python.org/downloads/windows/> — cochez
  **« Add python.exe to PATH »** pendant l'installation.
* Node.js : <https://nodejs.org/> (version LTS).
* FFmpeg : <https://www.gyan.dev/ffmpeg/builds/> (archive `ffmpeg-release-essentials.zip`,
  ajoutez le dossier `bin` au PATH) **ou** laissez le projet utiliser le binaire
  portable fourni par la dépendance de test `imageio-ffmpeg`.

Sans FFmpeg, l'import de médias fonctionne mais les métadonnées techniques et les
miniatures sont limitées — SocialDock vous le dit explicitement
(page **Diagnostics** ou `python -m socialdock doctor`).

## 2. Installation

```powershell
cd C:\chemin\vers\Metricool
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Ce que fait le script :

1. vérifie Python 3.11+ ;
2. crée un environnement virtuel dans `%LOCALAPPDATA%\SocialDock\venv` ;
3. installe `requirements.txt` (ajoutez `-WithDevTools` pour pytest/ruff/pip-audit) ;
4. compile l'interface React dans `frontend\dist` (si Node.js est présent,
   sinon `-SkipFrontend` puis `npm ci ; npm run build` plus tard) ;
5. applique les migrations SQLite (`python -m socialdock migrate`) ;
6. affiche l'état de FFmpeg.

> PowerShell bloque l'exécution des scripts par défaut : c'est l'objet de
> `-ExecutionPolicy Bypass`, qui ne s'applique qu'à ce lancement.

## 3. Démarrage

```powershell
.\start.bat                 # démarre et ouvre http://127.0.0.1:8000
```

* Port différent : `set PORT=8010 && .\start.bat`
* Sans navigateur : `%LOCALAPPDATA%\SocialDock\venv\Scripts\python.exe -m socialdock run --no-browser`
* Sans le moteur de programmation : `... -m socialdock run --no-scheduler`

Le serveur **n'écoute que `127.0.0.1`** : aucune machine du réseau ne peut y
accéder. Pour changer le port de façon permanente, créez un fichier `.env` à la
racine du dépôt :

```ini
SOCIALDOCK_PORT=8010
SOCIALDOCK_SCHEDULER_TICK_SECONDS=5
SOCIALDOCK_DEMO_MODE=true
```

`.env` est ignoré par Git ; le modèle est fourni (`.env.example`).

## 4. Arrêt propre

```powershell
.\stop.bat                  # ou Ctrl+C dans la fenêtre du serveur
```

`stop.bat` lit le fichier `%LOCALAPPDATA%\SocialDock\socialdock.pid`, termine le
processus, et SocialDock écrit son état avant de sortir : les tâches en cours ne
sont jamais perdues, et toute cible interrompue en plein envoi devient
`incertaine` (jamais republiée automatiquement).

## 5. Où sont mes données ?

```
%LOCALAPPDATA%\SocialDock\
├── venv\            environnement Python
├── socialdock.db    base SQLite (+ .db-wal / .db-shm)
├── socialdock.pid   PID du serveur en cours
├── media\           vidéos et images importées
├── thumbnails\      miniatures générées
├── logs\            journaux applicatifs
└── secrets\         clé de chiffrement, jeton d'ingestion (permissions restreintes)
```

Rien n'est écrit dans le dépôt Git. Pour déplacer vos données, arrêtez le
serveur puis définissez `SOCIALDOCK_DATA_DIR`.

## 6. Lancement au démarrage de Windows (optionnel)

```powershell
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\SocialDock.lnk")
$Shortcut.TargetPath = "C:\chemin\vers\Metricool\start.bat"
$Shortcut.WorkingDirectory = "C:\chemin\vers\Metricool"
$Shortcut.WindowStyle = 7   # fenêtre réduite
$Shortcut.Save()
```

Supprimez le raccourci `SocialDock.lnk` du dossier `shell:startup` pour annuler.

## 7. Connexion d'un compte réel

Aucun compte n'est requis pour explorer l'application. Pour publier réellement,
il faut créer **votre** application développeur (gratuit) puis renseigner ses
identifiants :

| Plateforme | Guide | Variables `.env` |
|---|---|---|
| YouTube | [CONNECT_YOUTUBE.md](CONNECT_YOUTUBE.md) | `SOCIALDOCK_GOOGLE_CLIENT_ID`, `SOCIALDOCK_GOOGLE_CLIENT_SECRET` |
| Instagram | [CONNECT_INSTAGRAM.md](CONNECT_INSTAGRAM.md) | `SOCIALDOCK_META_APP_ID`, `SOCIALDOCK_META_APP_SECRET` |
| TikTok | [CONNECT_TIKTOK.md](CONNECT_TIKTOK.md) | `SOCIALDOCK_TIKTOK_CLIENT_KEY`, `SOCIALDOCK_TIKTOK_CLIENT_SECRET` |

Puis : **Comptes → Connecter / reconnecter**. SocialDock ouvre le navigateur sur
la page officielle d'autorisation, reçoit le jeton, le chiffre et l'enregistre.
Aucun mot de passe n'est demandé, jamais.

## 8. Mettre à jour

```powershell
git pull
powershell -ExecutionPolicy Bypass -File .\install.ps1
.\start.bat
```

Les migrations s'appliquent automatiquement au démarrage ; vos données sont
conservées.

## 9. Désinstallation

```powershell
.\stop.bat
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\SocialDock"
Remove-Item -Recurse -Force C:\chemin\vers\Metricool
```

Pensez à révoquer les accès depuis les comptes concernés si vous aviez connecté
des comptes réels : [Google](https://myaccount.google.com/permissions),
[Meta](https://www.facebook.com/settings?tab=business_tools),
[TikTok](https://www.tiktok.com/settings/manage-apps).

## 10. En cas de problème

```powershell
%LOCALAPPDATA%\SocialDock\venv\Scripts\python.exe -m socialdock doctor
```

Le rapport indique l'état de la base, de FFmpeg, du scheduler, de l'espace disque
et la configuration de chaque connecteur. Voir aussi
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).
