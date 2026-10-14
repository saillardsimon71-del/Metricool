"""Callbacks OAuth : validation du state puis retour vers l'interface.

Ces routes renvoient une page HTML simple : l'utilisateur revient dans
SocialDock avec un message explicite (succès, refus, expiration).
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..config import Settings
from ..services.accounts import AccountError, complete_oauth
from .deps import db_session, get_current_settings

router = APIRouter(prefix="/api/oauth", tags=["oauth"])

_PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>SocialDock — {title}</title>
<style>body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0b1220;color:#e6edf3;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{background:#111a2e;padding:32px 40px;border-radius:14px;max-width:560px;box-shadow:0 12px 40px rgba(0,0,0,.4)}}
h1{{font-size:20px;margin:0 0 8px}}p{{color:#9fb0c8;line-height:1.5}}a{{color:#7cc4ff}}</style></head>
<body><div class="card"><h1>{title}</h1><p>{message}</p>
<p><a href="/accounts">Revenir à SocialDock</a></p></div></body></html>"""


def _finish(request: Request, *, ok: bool, title: str, message: str) -> HTMLResponse:
    return HTMLResponse(_PAGE.format(title=title, message=message), status_code=200 if ok else 400)


@router.get("/{platform}/callback", response_class=HTMLResponse)
def callback(
    platform: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_current_settings),
) -> HTMLResponse:
    if platform not in {"youtube", "instagram", "tiktok"}:
        return _finish(request, ok=False, title="Plateforme inconnue", message=f"« {platform} » n'est pas une plateforme supportée.")
    if error:
        return _finish(
            request,
            ok=False,
            title="Autorisation refusée",
            message=f"{error} — {error_description or 'la plateforme a refusé la demande.'}",
        )
    if not code or not state:
        return _finish(request, ok=False, title="Paramètres manquants", message="Le callback OAuth doit contenir « code » et « state ».")
    try:
        account = complete_oauth(session, platform=platform, code=code, state=state, settings=settings)
    except AccountError as exc:
        return _finish(request, ok=False, title="Connexion échouée", message=str(exc))
    return _finish(
        request,
        ok=True,
        title="Compte connecté",
        message=f"{account.display_name} ({platform}) est connecté. Vous pouvez fermer cet onglet.",
    )


@router.get("/{platform}/redirect")
def redirect_to_provider(platform: str, session: Session = Depends(db_session), settings: Settings = Depends(get_current_settings)) -> RedirectResponse:
    """Pratique pour les tests manuels : déclenche le parcours puis redirige."""
    from ..services.accounts import start_oauth

    try:
        started = start_oauth(session, platform, settings)
    except AccountError as exc:
        return RedirectResponse(f"/accounts?{urlencode({'error': str(exc)})}")
    return RedirectResponse(started["authorization_url"])
