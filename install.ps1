<#
.SYNOPSIS
    Installation de SocialDock sur Windows (aucun Docker, aucun service cloud).

.DESCRIPTION
    1. Vérifie Python 3.11+ (et Node.js, optionnel, pour l'interface web).
    2. Crée un environnement virtuel dans %LOCALAPPDATA%\SocialDock\venv.
    3. Installe les dépendances Python.
    4. Compile l'interface React (si Node.js est présent).
    5. Applique les migrations de la base SQLite locale.

    Les données utilisateur (base, médias, jetons chiffrés) restent dans
    %LOCALAPPDATA%\SocialDock — jamais dans le dépôt Git.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -SkipFrontend
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -WithDevTools
#>
[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$WithDevTools,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$RepoRoot = $PSScriptRoot
$DataRoot = Join-Path $env:LOCALAPPDATA 'SocialDock'
$VenvDir  = Join-Path $DataRoot 'venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

function Write-Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }
function Write-Ok($message)   { Write-Host "    [OK] $message" -ForegroundColor Green }
function Write-Warn2($message){ Write-Host "    [!]  $message" -ForegroundColor Yellow }

Write-Host "SocialDock — installation locale Windows" -ForegroundColor Magenta
Write-Host "Dépôt  : $RepoRoot"
Write-Host "Données: $DataRoot"

# ---------------------------------------------------------------- 1. Python
Write-Step 'Vérification de Python 3.11+'
$pythonCmd = $null
foreach ($candidate in @('python', 'py -3.12', 'py -3.11', 'python3')) {
    try {
        $version = & cmd /c "$candidate --version 2>&1"
        if ($LASTEXITCODE -eq 0 -and $version -match 'Python (\d+)\.(\d+)') {
            if ([int]$Matches[1] -ge 3 -and [int]$Matches[2] -ge 11) { $pythonCmd = $candidate; break }
        }
    } catch { }
}
if (-not $pythonCmd) {
    Write-Error "Python 3.11 ou plus récent est requis. Installez-le depuis https://www.python.org/downloads/windows/ (cochez « Add python.exe to PATH »)."
}
Write-Ok "Python détecté : $pythonCmd ($(& cmd /c "$pythonCmd --version 2>&1"))"

# ------------------------------------------------------------- 2. Venv
Write-Step "Création de l'environnement virtuel ($VenvDir)"
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
if (-not (Test-Path $VenvPython)) {
    & cmd /c "$pythonCmd -m venv `"$VenvDir`""
    if ($LASTEXITCODE -ne 0) { Write-Error "Impossible de créer l'environnement virtuel." }
}
Write-Ok "Environnement virtuel prêt"

# ------------------------------------------------- 3. Dépendances Python
Write-Step 'Installation des dépendances Python'
& $VenvPython -m pip install --upgrade pip | Out-Null
$reqFile = if ($WithDevTools) { 'requirements-dev.txt' } else { 'requirements.txt' }
& $VenvPython -m pip install -r (Join-Path $RepoRoot $reqFile)
if ($LASTEXITCODE -ne 0) { Write-Error "Échec de l'installation des dépendances ($reqFile)." }
Write-Ok "Dépendances installées ($reqFile)"

# --------------------------------------------------------- 4. Interface web
$env:PYTHONPATH = Join-Path $RepoRoot 'backend'
if ($SkipFrontend) {
    Write-Warn2 'Interface web non compilée (-SkipFrontend). L’API reste accessible, l’interface nécessitera Node.js puis « npm ci ; npm run build ».'
} else {
    Write-Step 'Compilation de l’interface React (Node.js requis)'
    $node = Get-Command node -ErrorAction SilentlyContinue
    if (-not $node) {
        Write-Warn2 'Node.js absent : interface non compilée. Installez Node.js 20+ puis relancez, ou exécutez « npm ci ; npm run build » dans frontend\.'
    } else {
        Push-Location (Join-Path $RepoRoot 'frontend')
        try {
            & cmd /c 'npm ci'
            if ($LASTEXITCODE -ne 0) { throw 'npm ci a échoué' }
            & cmd /c 'npm run build'
            if ($LASTEXITCODE -ne 0) { throw 'npm run build a échoué' }
            Write-Ok 'Interface compilée dans frontend\dist'
        } finally { Pop-Location }
    }
}

# ------------------------------------------------------------- 5. Migrations
Write-Step 'Initialisation de la base de données locale'
Push-Location $RepoRoot
try {
    & $VenvPython -m socialdock migrate
    if ($LASTEXITCODE -ne 0) { Write-Error 'Échec des migrations.' }
} finally { Pop-Location }
Write-Ok 'Base prête'

# ---------------------------------------------------------------- 6. FFmpeg
Write-Step 'Vérification de FFmpeg (analyse vidéo, optionnel mais recommandé)'
Push-Location $RepoRoot
try {
    & $VenvPython -m socialdock doctor | Select-String -Pattern 'FFmpeg'
} finally { Pop-Location }
Write-Warn2 "Sans FFmpeg, l'import fonctionne mais les métadonnées/miniatures sont limitées. Voir docs\TROUBLESHOOTING.md"

Write-Host "`nInstallation terminée." -ForegroundColor Green
Write-Host @"

Démarrer SocialDock :
    .\start.bat                (ou : $VenvPython -m socialdock run --port $Port)
    puis ouvrir http://127.0.0.1:$Port

Arrêter proprement :
    .\stop.bat

Premiers pas : Comptes → « Créer les comptes de démonstration » pour explorer,
puis connectez un compte réel (docs\CONNECT_YOUTUBE.md, CONNECT_INSTAGRAM.md,
CONNECT_TIKTOK.md). Diagnostic : $VenvPython -m socialdock doctor
"@
