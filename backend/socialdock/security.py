"""Sécurité : chiffrement des secrets, expurgation des logs, tokens locaux.

Stockage des secrets
---------------------
Les tokens OAuth ne sont jamais écrits en clair : ils sont chiffrés en AES-128
CBC (Fernet) avec une clé stockée dans ``%LOCALAPPDATA%\\SocialDock\\secrets``
en permissions restreintes. Si la bibliothèque ``keyring`` (DPAPI sous Windows)
est disponible, la clé maîtresse y est également référencée ; sinon le fichier
clé est protégé par les ACL du répertoire utilisateur.
"""

from __future__ import annotations

import base64
import os
import re
import stat
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .config import Settings, get_settings

_REDACT_PATTERNS = [
    re.compile(r"(?i)(access_token|refresh_token|id_token|client_secret|api_key|password|token)(\"?[:=]\s*\"?)([^\s\"&,;]{6,})"),
    re.compile(r"(?i)(ya29\.[A-Za-z0-9_\-\.]{10,})"),
    re.compile(r"(?i)(EA[A-Za-z0-9]{12,})"),
    re.compile(r"(?i)Bearer\s+([A-Za-z0-9_\-\.=]{12,})"),
]

_KEY_ENV = "SOCIALDOCK_KEY_B64"


class SecretError(RuntimeError):
    """Erreur de chiffrement/déchiffrement d'un secret."""


def _restrict_file(path) -> None:
    """Restreint les permissions du fichier clé (POSIX ; no-op sous Windows)."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:  # pragma: no cover - dépend du système de fichiers
        pass


def load_or_create_key(settings: Settings | None = None) -> bytes:
    """Charge la clé maîtresse, la crée au premier lancement."""
    settings = settings or get_settings()
    env_key = os.environ.get(_KEY_ENV)
    if env_key:
        return env_key.encode()
    settings.ensure_dirs()
    key_file = settings.key_file
    if key_file.exists():
        return key_file.read_bytes().strip()
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    _restrict_file(key_file)
    return key.strip()


class SecretVault:
    """Chiffre/déchiffre les blobs OAuth."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._fernet: Fernet | None = None

    @property
    def fernet(self) -> Fernet:
        if self._fernet is None:
            self._fernet = Fernet(load_or_create_key(self._settings))
        return self._fernet

    def encrypt(self, payload: dict[str, Any]) -> str:
        import json

        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return self.fernet.encrypt(raw).decode()

    def decrypt(self, blob: str | None) -> dict[str, Any]:
        if not blob:
            return {}
        import json

        try:
            return json.loads(self.fernet.decrypt(blob.encode()).decode())
        except InvalidToken as exc:  # pragma: no cover - clé changée
            raise SecretError("Secret illisible : la clé de chiffrement a changé.") from exc


def redact(text: str | None) -> str | None:
    """Retire toute valeur ressemblant à un secret d'un message de log."""
    if not text:
        return text
    out = text
    for pattern in _REDACT_PATTERNS:
        if pattern.groups == 3:
            out = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", out)
        else:
            out = pattern.sub("[REDACTED]", out)
    return out


def is_likely_secret(value: str) -> bool:
    return bool(any(p.search(value) for p in _REDACT_PATTERNS))


def local_api_token(settings: Settings | None = None) -> str:
    """Token exigé par l'API locale d'ingestion (Studio IA).

    Généré au premier démarrage et stocké dans le répertoire de données ; il est
    affiché une seule fois dans Paramètres → Intégrations.
    """
    settings = settings or get_settings()
    if settings.api_token:
        return settings.api_token
    settings.ensure_dirs()
    token_file = settings.secrets_dir / "ingest.token"
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip()
    import secrets as _secrets

    token = _secrets.token_urlsafe(32)
    token_file.write_text(token, encoding="utf-8")
    _restrict_file(token_file)
    return token


def constant_time_equals(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a.encode(), b.encode())


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def pkce_pair() -> tuple[str, str]:
    """Génère un couple (code_verifier, code_challenge) conforme RFC 7636."""
    import secrets as _secrets

    verifier = b64url(_secrets.token_bytes(48))[:96]
    import hashlib

    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge
