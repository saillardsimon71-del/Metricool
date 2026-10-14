"""Application FastAPI de SocialDock (serveur local + interface intégrée)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from . import __product__, __version__
from .api import accounts, calendar, diagnostics, ingest, media, oauth, posts, scheduler, stats, system, watchers
from .api import settings as settings_api
from .config import Settings, get_settings, set_settings
from .database import create_all, init_engine
from .logging_setup import configure_logging, log_event
from .models import LogLevel
from .services.notifications import NotificationService
from .services.scheduler import SchedulerEngine

log = logging.getLogger(__name__)

# « testclient » est l'hôte virtuel du TestClient Starlette (aucun accès réseau).
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
DOCS_DIR = REPO_ROOT / "docs"


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    """Refuse toute requête non locale et tout cross-origin non déclaré."""

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        if self.settings.require_local_origin:
            client_host = request.client.host if request.client else None
            if client_host and client_host not in LOCAL_HOSTS:
                return JSONResponse({"detail": "SocialDock n'accepte que les connexions locales (127.0.0.1)."}, status_code=403)
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            allowed = set(self.settings.allowed_origins)
            allowed.add(f"http://127.0.0.1:{self.settings.port}")
            allowed.add(f"http://localhost:{self.settings.port}")
            if origin and origin not in allowed:
                return JSONResponse({"detail": f"Origine non autorisée : {origin}"}, status_code=403)
        return await call_next(request)


def create_app(settings: Settings | None = None, *, run_scheduler: bool = True, engine: SchedulerEngine | None = None) -> FastAPI:
    """Fabrique l'application (utilisée par uvicorn et par les tests)."""
    settings = set_settings(settings) if settings else get_settings()
    settings.ensure_dirs()
    configure_logging(settings)
    init_engine(settings)
    create_all()

    # Sans moteur explicite, on en construit un : sinon le démarrage standard
    # (`python -m socialdock run`, donc start.bat) ne lancerait jamais la boucle
    # de programmation et aucune publication ne partirait à l'heure prévue.
    scheduler_engine = engine if engine is not None else build_scheduler(settings)
    notifications = NotificationService(enabled=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.notifications = notifications
        if scheduler_engine is not None:
            app.state.scheduler = scheduler_engine
            if run_scheduler:
                await scheduler_engine.start()
        from .database import get_session_factory

        session = get_session_factory()()
        try:
            log_event(session, source="system", message=f"{__product__} {__version__} démarré (PID local)", level=LogLevel.INFO.value)
        finally:
            session.close()
        log.info("%s %s prêt sur http://%s:%s", __product__, __version__, settings.host, settings.port)
        try:
            yield
        finally:
            if app.state.scheduler is not None:
                await app.state.scheduler.stop()
            log.info("%s arrêté proprement", __product__)

    app = FastAPI(
        title=f"{__product__} API",
        version=__version__,
        description="Gestionnaire de réseaux sociaux local — TikTok, Instagram, YouTube.",
        docs_url="/docs/api",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.scheduler = scheduler_engine
    app.add_middleware(LocalOnlyMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["*"],
    )

    for router in (
        system.router,
        media.router,
        accounts.router,
        oauth.router,
        posts.router,
        calendar.router,
        scheduler.router,
        stats.router,
        settings_api.router,
        watchers.router,
        diagnostics.router,
        ingest.router,
    ):
        app.include_router(router)

    @app.get("/api/version")
    def version() -> dict[str, Any]:
        return {"product": __product__, "version": __version__}

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Sert l'interface React compilée ; sinon, renvoie une page explicative."""
    if FRONTEND_DIST.exists() and (FRONTEND_DIST / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Route API inconnue."}, status_code=404)
            candidate = FRONTEND_DIST / full_path
            if full_path and candidate.exists() and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    else:

        @app.get("/", include_in_schema=False)
        def placeholder() -> JSONResponse:
            return JSONResponse(
                {
                    "product": __product__,
                    "version": __version__,
                    "message": (
                        "Interface non compilée. Lancez « npm install && npm run build » dans frontend/, "
                        "ou « npm run dev » pour le mode développement (http://127.0.0.1:5173)."
                    ),
                    "api_docs": "/docs/api",
                }
            )


def build_scheduler(settings: Settings | None = None) -> SchedulerEngine:
    settings = settings or get_settings()
    notifications = NotificationService(enabled=True)
    return SchedulerEngine(settings, notifier=notifications)


app = create_app()
