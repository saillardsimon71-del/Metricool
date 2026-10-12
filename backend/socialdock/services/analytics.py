"""Statistiques : uniquement des valeurs réellement renvoyées par les API.

Règle stricte : une métrique absente n'est jamais complétée par une estimation.
Le mode démonstration produit des données explicitement étiquetées et stockées
avec ``source="demo.local"``.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Iterable
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..connectors.registry import connector_for_account
from ..models import Account, AnalyticsSample, PostStatus, PostTarget, utcnow
from .publisher import credential_for

log = logging.getLogger(__name__)

METRIC_DEFINITIONS: dict[str, dict[str, Any]] = {
    "views": {"label": "Vues", "platforms": ["youtube", "instagram", "demo"], "definition": "Nombre de lectures comptabilisées par la plateforme."},
    "likes": {"label": "Mentions J'aime", "platforms": ["youtube", "instagram", "demo"], "definition": "Réactions positives."},
    "comments": {"label": "Commentaires", "platforms": ["youtube", "instagram", "demo"], "definition": "Commentaires publiés."},
    "shares": {"label": "Partages", "platforms": ["instagram", "demo"], "definition": "Partages du contenu."},
    "saved": {"label": "Enregistrements", "platforms": ["instagram", "demo"], "definition": "Contenus enregistrés par les utilisateurs."},
    "reach": {"label": "Portée", "platforms": ["instagram", "demo"], "definition": "Comptes uniques ayant vu le contenu."},
    "total_interactions": {"label": "Interactions", "platforms": ["instagram", "demo"], "definition": "Somme des interactions déclarées par Meta."},
}


class AnalyticsError(RuntimeError):
    pass


def available_metrics(platform: str) -> list[dict[str, Any]]:
    return [
        {"key": key, **meta} for key, meta in METRIC_DEFINITIONS.items() if platform in meta["platforms"]
    ]


def collect_for_target(session: Session, target: PostTarget, *, settings: Settings | None = None, on_date: date | None = None) -> AnalyticsSample | None:
    """Rapatrie les métriques d'une publication et les stocke (upsert par jour)."""
    settings = settings or get_settings()
    if target.status not in {PostStatus.PUBLISHED.value, PostStatus.PUBLISHED_PRIVATE.value}:
        return None
    if not target.remote_id:
        # Sans identifiant distant, aucune métrique de publication n'est
        # récupérable : on ne stocke rien plutôt que d'inventer.
        log.info("Statistiques ignorées pour %s : aucun identifiant distant", target.id)
        return None
    account = target.account
    credential = credential_for(account, settings)
    if account.mode == "real" and not credential.get("access_token"):
        # Compte réel non connecté : aucune donnée, aucun appel réseau inutile.
        log.info("Statistiques ignorées pour %s : compte non connecté", account.id)
        return None
    connector = connector_for_account(account, settings)
    try:
        from ..connectors.base import PublishContext

        context = PublishContext(target=target, post=target.post, account=account, credential=credential)
        payload = connector.get_analytics(context)
    except Exception as exc:  # noqa: BLE001 — une plateforme indisponible ne bloque pas les autres
        log.warning("Statistiques indisponibles pour %s : %s", target.id, exc)
        return None
    finally:
        connector.close()
    metrics = payload.get("metrics") or {}
    if not metrics:
        return None
    return store_sample(session, account=account, target=target, metrics=metrics, on_date=on_date, source=payload.get("source"))


def store_sample(
    session: Session,
    *,
    account: Account,
    target: PostTarget | None,
    metrics: dict[str, Any],
    on_date: date | None = None,
    source: str | None = None,
) -> AnalyticsSample:
    day = (on_date or utcnow().date()).isoformat()
    existing = session.scalar(
        select(AnalyticsSample).where(
            AnalyticsSample.account_id == account.id,
            AnalyticsSample.post_target_id == (target.id if target else None),
            AnalyticsSample.metric_date == day,
        )
    )
    if existing is not None:
        existing.metrics = {**existing.metrics, **metrics, **({"_source": source} if source else {})}
        existing.fetched_at = utcnow()
        session.flush()
        return existing
    sample = AnalyticsSample(
        account_id=account.id,
        post_target_id=target.id if target else None,
        metric_date=day,
        metrics={**metrics, **({"_source": source} if source else {})},
    )
    session.add(sample)
    session.flush()
    return sample


def collect_all(session: Session, *, settings: Settings | None = None) -> dict[str, int]:
    targets = session.scalars(
        select(PostTarget).where(PostTarget.status.in_([PostStatus.PUBLISHED.value, PostStatus.PUBLISHED_PRIVATE.value]))
    ).all()
    stored = 0
    for target in targets:
        if collect_for_target(session, target, settings=settings) is not None:
            stored += 1
    session.commit()
    return {"targets": len(targets), "samples_stored": stored}


def series(
    session: Session,
    *,
    start: date,
    end: date,
    account_ids: Iterable[str] | None = None,
    metric: str = "views",
) -> list[dict[str, Any]]:
    stmt = select(AnalyticsSample).where(AnalyticsSample.metric_date >= start.isoformat(), AnalyticsSample.metric_date <= end.isoformat())
    if account_ids:
        stmt = stmt.where(AnalyticsSample.account_id.in_(list(account_ids)))
    rows = session.scalars(stmt.order_by(AnalyticsSample.metric_date.asc())).all()
    points: list[dict[str, Any]] = []
    for row in rows:
        value = (row.metrics or {}).get(metric)
        if value is None:
            continue
        points.append({"date": row.metric_date, "account_id": row.account_id, "metric": metric, "value": value})
    return points


def compare_post(session: Session, post_id: str, metric: str = "views") -> list[dict[str, Any]]:
    """Comparaison d'une même vidéo sur plusieurs comptes."""
    rows = session.scalars(
        select(AnalyticsSample).where(AnalyticsSample.post_target_id.in_(select(PostTarget.id).where(PostTarget.post_id == post_id)))
    ).all()
    by_account: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = (row.metrics or {}).get(metric)
        if value is None:
            continue
        account = session.get(Account, row.account_id)
        key = row.account_id
        entry = by_account.setdefault(
            key,
            {
                "account_id": key,
                "account": account.display_name if account else None,
                "platform": account.platform if account else None,
                "values": [],
            },
        )
        entry["values"].append({"date": row.metric_date, "value": value})
    for entry in by_account.values():
        numeric = [v["value"] for v in entry["values"] if isinstance(v["value"], (int, float))]
        entry["latest"] = entry["values"][-1]["value"] if entry["values"] else None
        entry["max"] = max(numeric) if numeric else None
    return sorted(by_account.values(), key=lambda item: (item["latest"] is None, -(item["latest"] or 0)))


def ranking(session: Session, *, metric: str = "views", limit: int = 20, account_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    rows = session.scalars(select(AnalyticsSample).order_by(AnalyticsSample.fetched_at.desc()).limit(500)).all()
    scored: list[dict[str, Any]] = []
    for row in rows:
        value = (row.metrics or {}).get(metric)
        if value is None or not isinstance(value, (int, float)):
            continue
        if account_ids and row.account_id not in set(account_ids):
            continue
        target = session.get(PostTarget, row.post_target_id) if row.post_target_id else None
        account = session.get(Account, row.account_id)
        scored.append(
            {
                "account_id": row.account_id,
                "account": account.display_name if account else None,
                "platform": account.platform if account else None,
                "post_target_id": row.post_target_id,
                "title": target.post.title if (target and target.post) else None,
                "date": row.metric_date,
                "metric": metric,
                "value": value,
                "demo": (row.metrics or {}).get("_source") == "demo.local",
            }
        )
    scored.sort(key=lambda item: item["value"], reverse=True)
    return scored[:limit]


def export_csv(session: Session, *, start: date | None = None, end: date | None = None) -> str:
    stmt = select(AnalyticsSample)
    if start:
        stmt = stmt.where(AnalyticsSample.metric_date >= start.isoformat())
    if end:
        stmt = stmt.where(AnalyticsSample.metric_date <= end.isoformat())
    rows = session.scalars(stmt.order_by(AnalyticsSample.metric_date.asc())).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date", "account_id", "account", "platform", "post_target_id", "metric", "value", "source"])
    for row in rows:
        account = session.get(Account, row.account_id)
        for key, value in (row.metrics or {}).items():
            if key.startswith("_"):
                continue
            writer.writerow(
                [
                    row.metric_date,
                    row.account_id,
                    account.display_name if account else "",
                    account.platform if account else "",
                    row.post_target_id or "",
                    key,
                    value,
                    (row.metrics or {}).get("_source", ""),
                ]
            )
    return buffer.getvalue()


def export_json(session: Session, *, start: date | None = None, end: date | None = None) -> str:
    stmt = select(AnalyticsSample)
    if start:
        stmt = stmt.where(AnalyticsSample.metric_date >= start.isoformat())
    if end:
        stmt = stmt.where(AnalyticsSample.metric_date <= end.isoformat())
    rows = session.scalars(stmt.order_by(AnalyticsSample.metric_date.asc())).all()
    payload = [
        {
            "date": row.metric_date,
            "account_id": row.account_id,
            "post_target_id": row.post_target_id,
            "metrics": row.metrics,
            "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        }
        for row in rows
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)
