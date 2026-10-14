@echo off
REM Arret propre du serveur SocialDock (termine les envois en cours, puis ecrit l'etat).
setlocal
set "DATA=%LOCALAPPDATA%\SocialDock"
set "VENV_PY=%DATA%\venv\Scripts\python.exe"
cd /d "%~dp0"
set "PYTHONPATH=%~dp0backend"
if not exist "%VENV_PY%" (
    echo [SocialDock] Installation introuvable : executez install.ps1
    exit /b 1
)
"%VENV_PY%" -m socialdock stop
endlocal
