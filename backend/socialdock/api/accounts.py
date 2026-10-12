"""API comptes : connexion OAuth, vérification, capacités, préférences."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Account
from ..schemas import AccountCreate, AccountOut, AccountPatch, DemoAccountSeed, VerifyReport
from ..services import accounts as account_service
from ..services.accounts import AccountError
from .deps import db_session, get_current_settings

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountOut])
def list_accounts(platform: str | None = None, session: Session = Depends(db_session)) -> list[Account]:
    return account_service.list_accounts(session, platform=platform)


@router.post("/demo/seed", response_model=list[AccountOut], status_code=201)
def seed_demo(session: Session = Depends(db_session)) -> list[Account]:
    """Crée les six destinations de démonstration (2 TikTok, 2 Instagram, 2 YouTube)."""
    return account_service.seed_demo_accounts(session)


@router.post("/demo", response_model=AccountOut, status_code=201)
def create_demo(payload: DemoAccountSeed, session: Session = Depends(db_session)) -> Account:
    try:
        return account_service.create_demo_account(session, platform=payload.platform, display_name=payload.display_name, index=payload.index)
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", response_model=AccountOut, status_code=201)
def create_account(payload: AccountCreate, session: Session = Depends(db_session)) -> Account:
    try:
        if payload.mode == "demo":
            return account_service.create_demo_account(session, platform=payload.platform, display_name=payload.display_name)
        account = account_service.create_account(session, platform=payload.platform, display_name=payload.display_name)
        session.commit()
        return account
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{account_id}/oauth/start")
def start_oauth(account_id: str, session: Session = Depends(db_session), settings: Settings = Depends(get_current_settings)) -> dict[str, Any]:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    try:
        return account_service.start_oauth(session, account.platform, settings, account_id=account.id)
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{account_id}/verify", response_model=VerifyReport)
def verify(account_id: str, session: Session = Depends(db_session), settings: Settings = Depends(get_current_settings)) -> dict[str, Any]:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    return account_service.verify_account(session, account, settings)


@router.post("/{account_id}/disconnect", response_model=AccountOut)
def disconnect(account_id: str, session: Session = Depends(db_session), settings: Settings = Depends(get_current_settings)) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    return account_service.disconnect_account(session, account, settings)


@router.patch("/{account_id}", response_model=AccountOut)
def patch_account(account_id: str, payload: AccountPatch, session: Session = Depends(db_session)) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    data = payload.model_dump(exclude_none=True)
    audit = data.pop("audit_passed", None)
    scenario = data.pop("demo_scenario", None)
    extra = dict(account.extra or {})
    if audit is not None:
        extra["audit_passed"] = bool(audit)
    if scenario is not None:
        extra["demo_scenario"] = scenario or None
    account.extra = extra
    for key, value in data.items():
        setattr(account, key, value)
    account_service.refresh_capabilities(session, account)
    session.commit()
    return account


@router.get("/{account_id}/capabilities")
def capabilities(account_id: str, session: Session = Depends(db_session), settings: Settings = Depends(get_current_settings)) -> dict[str, Any]:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    return account_service.refresh_capabilities(session, account, settings).capabilities
