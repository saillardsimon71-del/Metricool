"""Parcours OAuth : state, PKCE, expiration, réutilisation, chiffrement du jeton."""

from __future__ import annotations

from datetime import timedelta

import pytest
from socialdock.connectors.youtube import YouTubeConnector
from socialdock.models import OAuthState, as_utc, utcnow
from socialdock.security import SecretVault
from socialdock.services.accounts import AccountError, complete_oauth, start_oauth
from sqlalchemy.orm import Session


class FakeOAuthConnector(YouTubeConnector):
    """Connecteur YouTube réel dont seul le dialogue réseau est remplacé."""

    def __init__(self) -> None:
        super().__init__(client_id="id", client_secret="secret", redirect_uri="http://127.0.0.1:8000/api/oauth/youtube/callback")

    def begin_auth(self, *, state, redirect_uri, account=None):
        from socialdock.connectors.base import AuthStart

        return AuthStart(
            authorization_url=f"https://accounts.google.com/o/oauth2/v2/auth?state={state}&code_challenge=xyz",
            state=state,
            scopes=["https://www.googleapis.com/auth/youtube.upload"],
            redirect_uri=redirect_uri,
            notes=["verifier-123"],
        )

    def handle_auth_callback(self, *, code, state, redirect_uri, code_verifier=None):
        assert code_verifier == "verifier-123", "le PKCE doit être transmis à l'échange du code"
        return {
            "access_token": "ya29.accesstoken123456",
            "refresh_token": "1//refreshtoken",
            "scope": "https://www.googleapis.com/auth/youtube.upload",
            "expires_at": (utcnow() + timedelta(hours=1)).isoformat(),
        }

    def get_account_info(self, credential):
        return {"id": "UC123", "title": "Ma chaîne", "username": "@machaine", "avatar_url": "https://x/a.png"}


@pytest.fixture()
def patched_connector(monkeypatch):
    connector = FakeOAuthConnector()
    monkeypatch.setattr("socialdock.services.accounts.connector_for_account", lambda account, settings=None, client=None: connector)
    return connector


def test_demarrage_oauth_persiste_un_state_avec_pkce(session: Session, settings, patched_connector):
    started = start_oauth(session, "youtube", settings)
    assert started["authorization_url"].startswith("https://accounts.google.com/")
    assert "code_challenge=xyz" in started["authorization_url"]
    state = session.get(OAuthState, started["state"])
    assert state is not None
    assert state.code_verifier == "verifier-123"
    assert state.consumed is False
    assert as_utc(state.expires_at) > utcnow()


def test_callback_reussit_et_chiffre_le_jeton(session: Session, settings, patched_connector):
    started = start_oauth(session, "youtube", settings)
    account = complete_oauth(session, platform="youtube", code="le-code", state=started["state"], settings=settings)
    assert account.status == "connected"
    assert account.external_id == "UC123"
    assert account.display_name == "Ma chaîne"
    assert account.username == "@machaine"
    # Le jeton ne doit jamais apparaître en clair en base
    assert "ya29.accesstoken123456" not in (account.credential_blob or "")
    assert SecretVault(settings).decrypt(account.credential_blob)["access_token"] == "ya29.accesstoken123456"


def test_state_reutilise_refuse(session: Session, settings, patched_connector):
    started = start_oauth(session, "youtube", settings)
    complete_oauth(session, platform="youtube", code="c", state=started["state"], settings=settings)
    with pytest.raises(AccountError, match="déjà été utilisé"):
        complete_oauth(session, platform="youtube", code="c", state=started["state"], settings=settings)


def test_state_inconnu_refuse(session: Session, settings, patched_connector):
    with pytest.raises(AccountError, match="inconnu"):
        complete_oauth(session, platform="youtube", code="c", state="state-inexistant", settings=settings)


def test_state_expire_refuse(session: Session, settings, patched_connector):
    started = start_oauth(session, "youtube", settings)
    state = session.get(OAuthState, started["state"])
    state.expires_at = utcnow().replace(tzinfo=None) - timedelta(minutes=1)
    session.commit()
    with pytest.raises(AccountError, match="expiré"):
        complete_oauth(session, platform="youtube", code="c", state=started["state"], settings=settings)


def test_state_d_une_autre_plateforme_refuse(session: Session, settings, patched_connector):
    started = start_oauth(session, "youtube", settings)
    with pytest.raises(AccountError, match="inconnu"):
        complete_oauth(session, platform="tiktok", code="c", state=started["state"], settings=settings)


def test_erreur_de_la_plateforme_transmise_clairement(session: Session, settings, monkeypatch):
    class RefusingConnector(FakeOAuthConnector):
        def handle_auth_callback(self, **kwargs):
            raise AccountError("invalid_grant: code expiré")

    monkeypatch.setattr("socialdock.services.accounts.connector_for_account", lambda account, s=None, client=None: RefusingConnector())
    started = start_oauth(session, "youtube", settings)
    with pytest.raises(AccountError, match="invalid_grant"):
        complete_oauth(session, platform="youtube", code="c", state=started["state"], settings=settings)


def test_api_ne_renvoie_jamais_le_jeton(session: Session, settings, patched_connector, client):
    """Le schéma de sortie ne doit exposer aucun identifiant, même après connexion."""
    started = start_oauth(session, "youtube", settings)
    complete_oauth(session, platform="youtube", code="le-code", state=started["state"], settings=settings)
    session.commit()
    accounts = client.get("/api/accounts").json()
    payload = str(accounts)
    assert "ya29.accesstoken123456" not in payload
    assert "1//refreshtoken" not in payload
    assert "credential_blob" not in payload
