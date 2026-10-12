"""Gestion des comptes : connexion OAuth, vérification, capacités."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..connectors.base import PermanentError, SocialConnector
from ..connectors.registry import connector_for_account
from ..logging_setup import log_event
from ..models import Account, AccountGroup, AccountStatus, OAuthState, Platform, utcnow
from ..security import SecretVault
from .publisher import credential_for, store_credential

log = logging.getLogger(__name__)

STATE_TTL_MINUTES = 10


class AccountError(RuntimeError):
    pass


def create_demo_account(session: Session, *, platform: str, display_name: str, index: int = 1) -> Account:
    if platform not in {"youtube", "instagram", "tiktok"}:
        raise AccountError(f"Plateforme inconnue pour un compte de démonstration : {platform}")
    account = Account(
        platform=platform,
        display_name=display_name,
        external_id=f"demo-{platform}-{index}",
        username=f"@{platform}{index}.demo",
        mode="demo",
        status=AccountStatus.DEMO.value,
        scopes=[],
        capabilities={},
        default_privacy="private" if platform != "instagram" else "public",
        extra={"demo": True, "demo_scenario": None},
    )
    session.add(account)
    session.flush()
    refresh_capabilities(session, account)
    log_event(session, source="accounts", message=f"Compte de démonstration créé : {display_name}")
    return account


def seed_demo_accounts(session: Session) -> list[Account]:
    """Les six destinations de l'utilisateur : 2 TikTok, 2 Instagram, 2 YouTube."""
    existing = session.scalar(select(Account).where(Account.mode == "demo"))
    if existing is not None:
        return list(session.scalars(select(Account).where(Account.mode == "demo")).all())
    plan = [("tiktok", 1), ("tiktok", 2), ("instagram", 1), ("instagram", 2), ("youtube", 1), ("youtube", 2)]
    labels = {
        "tiktok": "TikTok Démo",
        "instagram": "Instagram Démo",
        "youtube": "YouTube Démo",
    }
    created = [create_demo_account(session, platform=platform, display_name=f"{labels[platform]} {index}", index=index) for platform, index in plan]
    session.commit()
    return created


def refresh_capabilities(session: Session, account: Account, settings: Settings | None = None) -> Account:
    connector = connector_for_account(account, settings)
    try:
        capabilities = connector.get_capabilities(account).as_dict()
    finally:
        connector.close()
    account.capabilities = capabilities
    account.permissions_missing = capabilities.get("permissions_missing") or []
    session.flush()
    return account


def create_account(session: Session, *, platform: str, display_name: str, **fields: Any) -> Account:
    if platform not in {p.value for p in Platform}:
        raise AccountError(f"Plateforme inconnue : {platform}")
    account = Account(platform=platform, display_name=display_name, mode=fields.pop("mode", "real"), **fields)
    session.add(account)
    session.flush()
    refresh_capabilities(session, account)
    return account


def start_oauth(session: Session, platform: str, settings: Settings | None = None, *, account_id: str | None = None) -> dict[str, Any]:
    """Démarre un parcours OAuth : state persistant + PKCE lorsque pertinent."""
    settings = settings or get_settings()
    account = session.get(Account, account_id) if account_id else None
    if account is None:
        account = create_account(session, platform=platform, display_name=f"{platform.capitalize()} (à connecter)")
        session.commit()
    connector = connector_for_account(account, settings)
    state = secrets.token_urlsafe(24)
    redirect_uri = f"{settings.oauth_redirect_base.rstrip('/')}/api/oauth/{platform}/callback"
    try:
        start = connector.begin_auth(state=state, redirect_uri=redirect_uri, account=account)
    except PermanentError as exc:
        raise AccountError(str(exc)) from exc
    finally:
        connector.close()
    verifier = start.notes[0] if start.notes else None
    session.add(
        OAuthState(
            state=state,
            platform=platform,
            code_verifier=verifier,
            redirect_uri=redirect_uri,
            account_id=account.id,
            scopes=start.scopes,
            expires_at=utcnow() + timedelta(minutes=STATE_TTL_MINUTES),
        )
    )
    session.commit()
    return {
        "authorization_url": start.authorization_url,
        "state": state,
        "redirect_uri": redirect_uri,
        "scopes": start.scopes,
        "account_id": account.id,
        "notes": start.notes[1:],
    }


def complete_oauth(
    session: Session,
    *,
    platform: str,
    code: str,
    state: str,
    settings: Settings | None = None,
) -> Account:
    """Valide le callback : state consommé une seule fois, expiration vérifiée."""
    settings = settings or get_settings()
    entry = session.get(OAuthState, state)
    if entry is None or entry.platform != platform:
        raise AccountError("État OAuth inconnu : relancez la connexion (possible tentative de CSRF).")
    if entry.consumed:
        raise AccountError("Cet état OAuth a déjà été utilisé.")
    if entry.expires_at and entry.expires_at < utcnow():
        raise AccountError("La session d'autorisation a expiré : relancez la connexion.")
    connector = connector_for_account(
        session.get(Account, entry.account_id) if entry.account_id else Account(platform=platform, display_name=platform),
        settings,
    )
    try:
        credential = connector.handle_auth_callback(
            code=code, state=state, redirect_uri=entry.redirect_uri, code_verifier=entry.code_verifier
        )
        info = connector.get_account_info(credential)
        capabilities = connector.get_capabilities().as_dict()
    finally:
        connector.close()

    account = session.get(Account, entry.account_id) if entry.account_id else None
    if account is None:
        account = create_account(session, platform=platform, display_name=info.get("title") or platform)
    account.external_id = str(info.get("id") or account.external_id or "")
    account.username = info.get("username") or account.username
    account.display_name = info.get("title") or account.display_name
    account.avatar_url = info.get("avatar_url") or account.avatar_url
    account.status = AccountStatus.CONNECTED.value
    account.mode = "real"
    account.scopes = credential.get("scope", "").split() if isinstance(credential.get("scope"), str) else list(credential.get("scope") or [])
    account.capabilities = capabilities
    account.last_error = None
    account.last_verified_at = utcnow()
    account.extra = {**(account.extra or {}), **{k: v for k, v in info.items() if k not in {"id", "title", "username", "avatar_url"}}}
    store_credential(account, credential, settings)
    entry.consumed = True
    session.commit()
    log_event(session, source="accounts", message=f"Compte connecté : {account.display_name} ({platform})")
    return account


def verify_account(session: Session, account: Account, settings: Settings | None = None) -> dict[str, Any]:
    """Test réel du compte : rafraîchissement du jeton + lecture des infos."""
    settings = settings or get_settings()
    connector = connector_for_account(account, settings)
    report: dict[str, Any] = {"ok": False, "checked_at": utcnow().isoformat()}
    try:
        if account.mode == "demo":
            account.status = AccountStatus.DEMO.value
            account.last_verified_at = utcnow()
            refresh_capabilities(session, account, settings)
            report.update({"ok": True, "mode": "demo", "message": "Compte de démonstration local."})
            session.commit()
            return report
        credential = credential_for(account, settings)
        if not credential.get("access_token"):
            raise PermanentError("Aucun jeton stocké : reconnectez le compte.")
        try:
            credential = connector.refresh_auth(credential)
            store_credential(account, credential, settings)
            report["token_refreshed"] = True
        except PermanentError as exc:
            account.status = AccountStatus.EXPIRED.value
            account.last_error = str(exc)
            session.commit()
            report.update({"ok": False, "message": f"Jeton invalide : {exc}"})
            return report
        info = connector.get_account_info(credential)
        account.external_id = str(info.get("id") or account.external_id or "")
        account.username = info.get("username") or account.username
        account.avatar_url = info.get("avatar_url") or account.avatar_url
        account.status = AccountStatus.CONNECTED.value
        account.last_error = None
        account.last_verified_at = utcnow()
        account.extra = {**(account.extra or {}), **{k: v for k, v in info.items() if k not in {"id", "username", "avatar_url"}}}
        refresh_capabilities(session, account, settings)
        session.commit()
        report.update({"ok": True, "message": "Compte joignable.", "info": info})
        return report
    except PermanentError as exc:
        account.status = AccountStatus.ERROR.value
        account.last_error = str(exc)
        session.commit()
        report.update({"ok": False, "message": str(exc)})
        return report
    finally:
        connector.close()


def disconnect_account(session: Session, account: Account, settings: Settings | None = None) -> Account:
    settings = settings or get_settings()
    if account.mode == "demo":
        session.delete(account)
        session.commit()
        return account
    connector = connector_for_account(account, settings)
    try:
        credential = credential_for(account, settings)
        connector.disconnect(credential)
    except Exception as exc:  # noqa: BLE001 — la déconnexion locale prime
        log.warning("Révocation distante impossible pour %s : %s", account.display_name, exc)
    finally:
        connector.close()
    account.credential_blob = None
    account.status = AccountStatus.NOT_CONFIGURED.value
    account.credentials_expire_at = None
    account.last_error = None
    refresh_capabilities(session, account, settings)
    session.commit()
    log_event(session, source="accounts", message=f"Compte déconnecté : {account.display_name}", level="warning")
    return account


def list_accounts(session: Session, *, platform: str | None = None) -> list[Account]:
    stmt = select(Account).order_by(Account.platform.asc(), Account.display_name.asc())
    if platform:
        stmt = stmt.where(Account.platform == platform)
    return list(session.scalars(stmt).all())


def get_group(session: Session, name: str) -> AccountGroup:
    group = session.scalar(select(AccountGroup).where(AccountGroup.name == name))
    if group is None:
        group = AccountGroup(name=name)
        session.add(group)
        session.flush()
    return group
