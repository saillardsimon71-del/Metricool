"""Point d'entrée console de SocialDock.

Usage (Windows)::

    python -m socialdock run --port 8000
    python -m socialdock stop
    python -m socialdock migrate
    python -m socialdock doctor

Aucun conteneur ni service distant n'est requis : tout tourne en local.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import __version__
from .config import Settings, get_settings


def _pid_file(settings: Settings) -> Path:
    return settings.data_dir / "socialdock.pid"


def _write_pid(settings: Settings) -> None:
    settings.ensure_dirs()
    _pid_file(settings).write_text(str(os.getpid()), encoding="utf-8")


def _clear_pid(settings: Settings) -> None:
    with contextlib.suppress(OSError):
        _pid_file(settings).unlink()


def _migrate(settings: Settings) -> None:
    """Applique les migrations Alembic sur la base configurée."""
    from alembic import command
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[2]
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url)
    command.upgrade(config, "head")
    print(f"Migrations appliquées sur {settings.resolved_database_url}")


def cmd_run(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    settings.ensure_dirs()
    _migrate(settings)
    _write_pid(settings)

    if args.browser:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{args.host}:{args.port}/")).start()

    host = args.host or settings.host
    port = args.port or settings.port
    print(f"SocialDock {__version__} — http://{host}:{port}")
    print(f"Données : {settings.data_dir}")
    print("Arrêt : Ctrl+C, ou « python -m socialdock stop » dans une autre fenêtre.")

    if args.reload and args.no_scheduler:
        _clear_pid(settings)
        raise SystemExit("--reload et --no-scheduler sont incompatibles (le rechargement exige une cible importable).")

    try:
        if args.no_scheduler:
            # Application construite ici : utile pour déboguer l'API sans moteur.
            from .main import create_app

            uvicorn.run(create_app(settings, run_scheduler=False), host=host, port=port, log_level=args.log_level)
        else:
            uvicorn.run(
                "socialdock.main:create_app",
                factory=True,
                host=host,
                port=port,
                reload=args.reload,
                log_level=args.log_level,
            )
    finally:
        _clear_pid(settings)
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    settings = get_settings()
    pid_file = _pid_file(settings)
    if not pid_file.exists():
        print("SocialDock ne semble pas lancé (aucun fichier PID).")
        return 0
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        print(f"Fichier PID illisible : {pid_file}")
        return 1

    print(f"Arrêt de SocialDock (PID {pid})…")
    if os.name == "nt":
        # /T termine aussi uvicorn reloader éventuel, sans tuer brutalement d'emblée
        os.system(f"taskkill /PID {pid} /T >nul 2>&1")
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            print("Processus déjà terminé.")
    for _ in range(20):
        time.sleep(0.25)
        if not pid_file.exists():
            break
    _clear_pid(settings)
    print("SocialDock arrêté.")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    from .database import get_session_factory, init_engine
    from .services.diagnostics import export_text_report

    settings = get_settings()
    settings.ensure_dirs()
    # Le rapport doit fonctionner même sur une installation neuve : on s'assure
    # que le schéma existe avant d'interroger la base.
    _migrate(settings)
    init_engine(settings)
    session = get_session_factory()()
    try:
        print(export_text_report(session, settings))
    finally:
        session.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="socialdock", description="SocialDock — gestionnaire local de réseaux sociaux")
    parser.add_argument("--version", action="version", version=f"SocialDock {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Démarre le serveur local")
    run.add_argument("--host", default=None, help="Interface d'écoute (défaut : 127.0.0.1, local uniquement)")
    run.add_argument("--port", type=int, default=None, help="Port d'écoute (défaut : 8000)")
    run.add_argument("--log-level", default="info")
    run.add_argument("--no-browser", dest="browser", action="store_false", help="Ne pas ouvrir le navigateur")
    run.add_argument("--no-scheduler", action="store_true", help="Démarrer sans le moteur de programmation")
    run.add_argument("--reload", action="store_true", help="Mode développement (rechargement automatique)")
    run.set_defaults(func=cmd_run)

    stop = subparsers.add_parser("stop", help="Arrête proprement le serveur lancé")
    stop.set_defaults(func=cmd_stop)

    migrate = subparsers.add_parser("migrate", help="Applique les migrations de base de données")
    migrate.set_defaults(func=lambda _args: (_migrate(get_settings()), 0)[1])

    doctor = subparsers.add_parser("doctor", help="Affiche le rapport de diagnostics")
    doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
