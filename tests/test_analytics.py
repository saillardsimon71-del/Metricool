"""Statistiques : uniquement des données réelles (ou démonstration explicite)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from socialdock.models import AnalyticsSample, MediaAsset, PostStatus, utcnow
from socialdock.services.analytics import available_metrics, collect_all, collect_for_target, export_csv, ranking, series
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.conftest import FakeConnector, make_post


def test_metrices_disponibles_par_plateforme():
    youtube = {item["key"] for item in available_metrics("youtube")}
    tiktok = {item["key"] for item in available_metrics("tiktok")}
    assert "views" in youtube
    assert "likes" in youtube
    assert tiktok == set(), "TikTok Content Posting API n'expose pas de statistiques : rien ne doit être inventé"


@pytest.fixture()
def published(session: Session, imported_media: MediaAsset, demo_accounts):
    post = make_post(session, imported_media, demo_accounts[:2])
    for index, target in enumerate(post.targets):
        target.status = PostStatus.PUBLISHED.value
        target.remote_id = f"remote-{index}"
        target.remote_url = f"https://demo.socialdock.local/x/{index}"
        target.published_at = utcnow() - timedelta(days=1)
    session.commit()
    return post


def test_collecte_depuis_le_connecteur(session: Session, published, monkeypatch):
    connector = FakeConnector(analytics={"metrics": {"views": 1200, "likes": 88}, "source": "demo"})
    monkeypatch.setattr("socialdock.services.analytics.connector_for_account", lambda account, settings=None, client=None: connector)
    result = collect_all(session)
    assert result["targets"] == 2
    assert result["samples_stored"] == 2
    rows = session.scalars(select(AnalyticsSample)).all()
    assert len(rows) == 2
    assert rows[0].metrics["views"] == 1200


def test_compte_reel_sans_jeton_ne_produit_aucune_donnee(session: Session, imported_media, monkeypatch):
    from socialdock.services.accounts import create_account

    account = create_account(session, platform="youtube", display_name="Réel non connecté")
    account.extra = {}
    post = make_post(session, imported_media, [account])
    post.targets[0].status = PostStatus.PUBLISHED.value
    post.targets[0].remote_id = "VID1"
    session.commit()
    connector = FakeConnector()
    monkeypatch.setattr("socialdock.services.analytics.connector_for_account", lambda a, settings=None, client=None: connector)
    result = collect_all(session)
    assert result["samples_stored"] == 0, "aucune statistique ne doit être fabriquée sans source réelle"
    assert connector.calls == []


def test_metrique_absente_non_remplie(session: Session, published, monkeypatch):
    connector = FakeConnector(analytics={"metrics": {"views": 10}, "source": "demo"})
    monkeypatch.setattr("socialdock.services.analytics.connector_for_account", lambda a, settings=None, client=None: connector)
    collect_all(session)
    sample = session.scalars(select(AnalyticsSample)).first()
    assert sample.metrics["views"] == 10
    assert "likes" not in sample.metrics, "une métrique absente doit rester absente, pas mise à zéro"


def test_serie_et_classement(session: Session, published, monkeypatch):
    connector = FakeConnector(analytics={"metrics": {"views": 500}, "source": "demo"})
    monkeypatch.setattr("socialdock.services.analytics.connector_for_account", lambda a, settings=None, client=None: connector)
    collect_all(session)
    points = series(session, start=date.today() - timedelta(days=7), end=date.today(), metric="views")
    assert len(points) == 2
    assert all(point["value"] == 500 for point in points)
    items = ranking(session, metric="views", limit=10)
    assert len(items) == 2


def test_export_csv_contient_les_donnees_reelles(session: Session, published, monkeypatch):
    connector = FakeConnector(analytics={"metrics": {"views": 77, "likes": 3}, "source": "demo"})
    monkeypatch.setattr("socialdock.services.analytics.connector_for_account", lambda a, settings=None, client=None: connector)
    collect_all(session)
    content = export_csv(session, start=date.today() - timedelta(days=7), end=date.today())
    assert "views" in content
    assert "77" in content
    assert "inventé" not in content


def test_collecte_d_une_cible_sans_identifiant_distant(session: Session, imported_media, demo_accounts, monkeypatch):
    post = make_post(session, imported_media, demo_accounts[:1])
    post.targets[0].status = PostStatus.PUBLISHED.value
    session.commit()
    connector = FakeConnector()
    monkeypatch.setattr("socialdock.services.analytics.connector_for_account", lambda a, settings=None, client=None: connector)
    assert collect_for_target(session, post.targets[0]) is None


def test_route_stats_expose_la_note_anti_estimation(client):
    payload = client.get("/api/stats/metrics").json()
    assert "jamais estimée" in payload["note"]
    assert payload["by_platform"]["tiktok"] == []
