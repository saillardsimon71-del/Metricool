"""Primitives OAuth 2.0 partagées (code, refresh, révocation, PKCE)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from ..security import redact
from .base import ConnectorError, PermanentError, RetriableError


def build_authorization_url(
    authorize_endpoint: str,
    *,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    state: str,
    scope_separator: str = " ",
    extra: dict[str, str] | None = None,
) -> str:
    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope_separator.join(scopes),
        "state": state,
    }
    params.update(extra or {})
    return f"{authorize_endpoint}?{urlencode(params)}"


class OAuthError(ConnectorError):
    pass


def _raise_for_token_response(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    try:
        payload = response.json()
    except ValueError:
        payload = {"error": "invalid_response", "error_description": response.text[:300]}
    code = str(payload.get("error") or "oauth_error")
    description = redact(str(payload.get("error_description") or payload.get("error") or "Erreur OAuth")) or ""
    message = f"{code}: {description}".strip(": ")
    if response.status_code in {429, 500, 502, 503, 504}:
        raise RetriableError(message, code=code, http_status=response.status_code)
    raise PermanentError(message, code=code, http_status=response.status_code)


def exchange_code(
    client: httpx.Client,
    token_endpoint: str,
    *,
    data: dict[str, Any],
    auth: tuple[str, str] | None = None,
) -> dict[str, Any]:
    response = client.post(token_endpoint, data=data, auth=auth)
    _raise_for_token_response(response)
    return response.json()


def refresh_token(
    client: httpx.Client,
    token_endpoint: str,
    *,
    data: dict[str, Any],
    auth: tuple[str, str] | None = None,
) -> dict[str, Any]:
    response = client.post(token_endpoint, data=data, auth=auth)
    _raise_for_token_response(response)
    return response.json()


def revoke(client: httpx.Client, revoke_endpoint: str, *, data: dict[str, Any], auth: tuple[str, str] | None = None) -> None:
    try:
        client.post(revoke_endpoint, data=data, auth=auth)
    except httpx.HTTPError as exc:  # la révocation est best-effort
        raise ConnectorError(f"Révocation impossible : {exc}") from exc


def bearer_headers(token: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    headers.update(extra or {})
    return headers
