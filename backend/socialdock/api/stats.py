"""API statistiques : métriques réelles, comparaisons, exports."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from ..services import analytics
from .deps import db_session

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/metrics")
def metrics(platform: str | None = None) -> dict[str, Any]:
    if platform:
        return {"platform": platform, "metrics": analytics.available_metrics(platform)}
    return {
        "definitions": analytics.METRIC_DEFINITIONS,
        "by_platform": {p: analytics.available_metrics(p) for p in ("youtube", "instagram", "tiktok", "demo")},
        "note": "Une métrique absente n'est jamais estimée : les cases vides correspondent à des données non fournies par la plateforme.",
    }


@router.get("/series")
def series(
    metric: str = "views",
    start: date | None = None,
    end: date | None = None,
    account_id: list[str] | None = Query(default=None),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    end = end or date.today()
    start = start or (end - timedelta(days=30))
    return {"metric": metric, "points": analytics.series(session, start=start, end=end, account_ids=account_id, metric=metric)}


@router.get("/compare/{post_id}")
def compare(post_id: str, metric: str = "views", session: Session = Depends(db_session)) -> dict[str, Any]:
    return {"metric": metric, "accounts": analytics.compare_post(session, post_id, metric=metric)}


@router.get("/ranking")
def ranking(
    metric: str = "views",
    limit: int = Query(default=20, ge=1, le=200),
    account_id: list[str] | None = Query(default=None),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    return {"metric": metric, "items": analytics.ranking(session, metric=metric, limit=limit, account_ids=account_id)}


@router.post("/collect")
def collect(session: Session = Depends(db_session)) -> dict[str, Any]:
    return analytics.collect_all(session)


@router.get("/export.csv", response_class=PlainTextResponse)
def export_csv(start: date | None = None, end: date | None = None, session: Session = Depends(db_session)) -> PlainTextResponse:
    return PlainTextResponse(analytics.export_csv(session, start=start, end=end), media_type="text/csv; charset=utf-8")


@router.get("/export.json")
def export_json(start: date | None = None, end: date | None = None, session: Session = Depends(db_session)) -> Response:
    return Response(analytics.export_json(session, start=start, end=end), media_type="application/json; charset=utf-8")
