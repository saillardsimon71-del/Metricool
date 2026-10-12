@echo off
REM ============================================================
REM  SocialDock - demarrage local (Windows)
REM  Le serveur n'ecoute que 127.0.0.1 : rien n'est expose au reseau.
REM ============================================================
setlocal
set "REPO=%~dp0"
set "DATA=%LOCALAPPDATA%\SocialDock"
set "VENV_PY=%DATA%\venv\Scripts\python.exe"
if "%PORT%"=="" set "PORT=8000"

if not exist "%VENV_PY%" (
    echo [SocialDock] Environnement virtuel introuvable : %VENV_PY%
    echo [SocialDock] Lancez d'abord : powershell -ExecutionPolicy Bypass -File "%REPO%install.ps1"
    exit /b 1
)

cd /d "%REPO%"
set "PYTHONPATH=%REPO%backend"
echo [SocialDock] Demarrage sur http://127.0.0.1:%PORT%  (donnees : %DATA%)
echo [SocialDock] Arret : Ctrl+C, ou stop.bat depuis une autre fenetre.
"%VENV_PY%" -m socialdock run --port %PORT%
endlocal
