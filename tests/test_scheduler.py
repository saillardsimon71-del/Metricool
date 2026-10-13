"""Moteur de programmation : persistance, verrous, reprise après crash, retards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from socialdock.models import MediaAsset, PostStatus, PostTarget
from socialdock.services.posts import PostError, cancel_target, publish_now, schedule_target, unschedule_target
from socialdock.services.publisher import acquire_lock
from socialdock.services.scheduler import SchedulerEngine
from sqlalchemy.orm import Session

from tests.conftest import FakeConnector, make_post


def utc_past(minutes: int = 5) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


def utc_future(minutes: int = 30) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


def statuses(session: Session, post) -> list[str]:
    """Relit les statuts en base : le scheduler travaille dans sa propre session."""
    session.expire_all()
    return [session.get(PostTarget, target.id).status for target in post.targets]


@pytest.fixture()
def post(session: Session, imported_media: MediaAsset, demo_accounts):
    return make_post(session, imported_media, demo_accounts[:3])


def test_taches_echues_executees_au_tick(session: Session, post, engine: SchedulerEngine, monkeypatch):
    connector = FakeConnector()
    monkeypatch.setattr("socialdock.services.publisher.connector_for_account", lambda account, settings=None, client=None: connector)
    for target in post.targets:
        schedule_target(session, target, utc_past())
    session.commit()
    report = engine.run_tick()
    assert report.due == 3
    assert report.executed == 3
    assert report.errors == 0
    assert statuses(session, post) == [PostStatus.PUBLISHED.value] * 3


def test_taches_futures_non_executees(session: Session, post, engine: SchedulerEngine, monkeypatch):
    connector = FakeConnector()
    monkeypatch.setattr("socialdock.services.publisher.connector_for_account", lambda account, settings=None, client=None: connector)
    for target in post.targets:
        schedule_target(session, target, utc_future())
    session.commit()
    report = engine.run_tick()
    assert report.due == 0
    assert connector.calls == []


def test_verrou_empeche_la_double_execution(session: Session, post, engine: SchedulerEngine, monkeypatch):
    connector = FakeConnector()
    monkeypatch.setattr("socialdock.services.publisher.connector_for_account", lambda account, settings=None, client=None: connector)
    target = post.targets[0]
    schedule_target(session, target, utc_past())
    session.commit()
    acquire_lock(session, target, "autre-worker")
    report = engine.run_tick()
    assert report.skipped == 1
    assert connector.calls == []


def test_reprise_apres_crash_ne_duplique_pas(session: Session, post, engine: SchedulerEngine, monkeypatch):
    """Une cible bloquée en cours d'envoi devient incertaine, jamais republiée."""
    connector = FakeConnector()
    monkeypatch.setattr("socialdock.services.publisher.connector_for_account", lambda account, settings=None, client=None: connector)
    target = post.targets[0]
    target.status = PostStatus.UPLOADING.value
    target.locked_by = "worker-mort"
    target.locked_at = utc_past(60)
    target.lock_expires_at = utc_past(30)
    session.commit()
    result = engine.recover_interrupted()
    assert result["released"] == 1
    assert result["ambiguous"] == 1
    session.refresh(target)
    assert target.status == PostStatus.UNCERTAIN.value
    assert target.locked_by is None
    report = engine.run_tick()
    assert connector.calls == [], "aucune republication automatique après crash"
    assert report.due == 0


def test_taches_en_retard_detectees(session: Session, post, engine: SchedulerEngine):
    for target in post.targets:
        schedule_target(session, target, utc_past(90))
    session.commit()
    missed = engine.detect_missed(session)
    assert len(missed) == 3
    assert all(item["late_seconds"] > 0 for item in missed)
    engine.refresh_counts(session)
    assert engine.status.late_count == 3


def test_nouvelle_execution_apres_echec_avec_backoff(session: Session, post, engine: SchedulerEngine, monkeypatch):
    connector = FakeConnector(outcomes=["failure", "success"])
    monkeypatch.setattr("socialdock.services.publisher.connector_for_account", lambda account, settings=None, client=None: connector)
    target = post.targets[0]
    schedule_target(session, target, utc_past())
    session.commit()
    engine.run_tick()
    session.expire_all()
    target = session.get(PostTarget, target.id)
    assert target.status == PostStatus.FAILED.value
    assert target.next_retry_at is not None
    # Tant que le délai de nouvelle tentative n'est pas écoulé, rien ne se passe
    target.status = PostStatus.SCHEDULED.value
    session.commit()
    assert engine.due_targets(session) == []
    target.next_retry_at = utc_past()
    session.commit()
    engine.run_tick()
    session.expire_all()
    assert session.get(PostTarget, target.id).status == PostStatus.PUBLISHED.value


def test_compteurs_du_statut_scheduler(session: Session, post, engine: SchedulerEngine):
    schedule_target(session, post.targets[0], utc_future())
    post.targets[1].status = PostStatus.WAITING_FOR_USER.value
    post.targets[2].status = PostStatus.UNCERTAIN.value
    session.commit()
    engine.refresh_counts(session)
    assert engine.status.scheduled_count == 1
    assert engine.status.waiting_user_count == 1
    assert engine.status.uncertain_count == 1


def test_programmation_refuse_un_horaire_sans_fuseau(session: Session, post):
    with pytest.raises(PostError, match="fuseau"):
        schedule_target(session, post.targets[0], datetime(2026, 5, 1, 10, 0))


def test_publication_immediate_et_annulation(session: Session, post):
    target = post.targets[0]
    publish_now(session, target)
    assert target.status == PostStatus.SCHEDULED.value
    assert target.scheduled_at <= datetime.now(UTC) + timedelta(seconds=1)
    cancel_target(session, target)
    assert target.status == PostStatus.CANCELLED.value


def test_deprogrammation_conserve_les_donnees(session: Session, post):
    target = post.targets[0]
    payload_avant = dict(target.payload)
    schedule_target(session, target, utc_future())
    unschedule_target(session, target)
    assert target.status == PostStatus.READY.value
    assert target.scheduled_at is None
    assert target.payload == payload_avant


def test_boucle_asyncio_demarre_et_s_arrete(session: Session, engine: SchedulerEngine):
    import asyncio

    async def scenario() -> None:
        await engine.start()
        assert engine.status.running is True
        await asyncio.sleep(0.2)
        await engine.stop()

    asyncio.run(scenario())
    assert engine.status.running is False


def test_le_scheduler_demarre_avec_l_application(settings):
    """Régression : `python -m socialdock run` ne passait aucun moteur,
    la boucle de programmation ne démarrait donc jamais."""
    from fastapi.testclient import TestClient

    from socialdock.main import create_app

    with TestClient(create_app(settings, run_scheduler=True)) as client:
        status = client.get("/api/scheduler/status").json()
        assert status["running"] is True, "la boucle de programmation doit tourner"
        assert status["pid"] is not None
        assert status["tick_seconds"] == settings.scheduler_tick_seconds


def test_le_scheduler_ne_demarre_pas_quand_il_est_desactive(settings):
    from fastapi.testclient import TestClient

    from socialdock.main import create_app

    with TestClient(create_app(settings, run_scheduler=False)) as client:
        assert client.get("/api/scheduler/status").json()["running"] is False
