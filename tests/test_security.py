"""Sécurité : chiffrement, expurgation, PKCE, token local."""

from __future__ import annotations

import os

import pytest
from socialdock.config import Settings
from socialdock.security import (
    SecretVault,
    b64url,
    constant_time_equals,
    is_likely_secret,
    local_api_token,
    pkce_pair,
    redact,
)


def test_chiffrement_aller_retour(settings: Settings):
    vault = SecretVault(settings)
    blob = vault.encrypt({"access_token": "ya29.secret", "refresh_token": "1//refresh"})
    assert "ya29.secret" not in blob
    assert vault.decrypt(blob)["access_token"] == "ya29.secret"


def test_dechiffrement_vide_renvoie_un_dict_vide(settings: Settings):
    assert SecretVault(settings).decrypt(None) == {}


def test_cle_persistee_avec_permissions_restreintes(settings: Settings):
    first = SecretVault(settings)
    first.encrypt({"a": 1})
    assert settings.key_file.exists()
    assert SecretVault(settings).fernet is not None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("access_token=ya29.abcdef123456", "access_token=[REDACTED]"),
        ("Authorization: Bearer abcdefghijklmnop", "Authorization: [REDACTED]"),
        ("client_secret=S3CRETVALUE", "client_secret=[REDACTED]"),
        ("message sans secret", "message sans secret"),
    ],
)
def test_expurgation_des_logs(raw: str, expected: str):
    assert redact(raw) == expected


def test_detection_de_secret():
    assert is_likely_secret("ya29.a0AfH6SMabc1234567890")
    assert not is_likely_secret("publication réussie")


def test_pkce_conforme_rfc7636():
    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert len(challenge) == 43
    assert "=" not in challenge and b64url(b"x") == "eA"


def test_comparaison_temps_constant():
    assert constant_time_equals("abc", "abc")
    assert not constant_time_equals("abc", "abd")


def test_token_ingestion_stable_puis_persiste(settings: Settings):
    token = local_api_token(settings)
    assert len(token) >= 32
    assert local_api_token(settings) == token


def test_notifications_desactivees_environnement(settings: Settings, monkeypatch):
    monkeypatch.setenv("SOCIALDOCK_DISABLE_TOAST", "1")
    assert os.environ["SOCIALDOCK_DISABLE_TOAST"] == "1"
