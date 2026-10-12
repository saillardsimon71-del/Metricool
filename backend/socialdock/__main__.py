"""Point d'entrée : ``python -m socialdock`` (utilisé par start.bat)."""

from __future__ import annotations

import argparse
import os

import uvicorn

from .config import get_settings
from .database import create_all, init_engine
from .main import build_scheduler, create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="SocialDock — serveur local")
    parser.add_argument("--host", default=None, help="Adresse d'écoute (défaut : 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Port d'écoute (défaut : 8000)")
    parser.add_argument("--no-scheduler", action="store_true", help="Démarrer sans le moteur de programmation")
    parser.add_argument("--reload", action="store_true", help="Mode développement (rechargement automatique)")
    args = parser.parse_args()

    settings = get_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    os.environ.setdefault("SOCIALDOCK_HOST", host)
    os.environ.setdefault("SOCIALDOCK_PORT", str(port))

    init_engine(settings)
    create_all()
    app = create_app(settings, run_scheduler=not args.no_scheduler, engine=build_scheduler(settings))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
