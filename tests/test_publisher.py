"""Pipeline de publication : idempotence, incertitude, mode assisté, journal."""

from __future__ import annotations

import pytest
from socialdock.models import AttemptOutcome, MediaAsset, PostStatus, PublishAttempt
from socialdock.services.publisher import publish_target, refresh_remote_status, resolve_uncertain
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.conftest import FakeConnector, make_post


@pytest.fixture()
def post(session: Session, imported_media: MediaAsset, demo_accounts) -> object:
    return make_post(session, imported_media, demo_accounts[:2])


def test_publication_reussie_met_a_jour_statut_et_url(session: Session, post, fake_connector: FakeConnector):
    target = post.targets[0]
    publish_target(session, target, connector=fake_connector)
    assert target.status == PostStatus.PUBLISHED.value
    assert target.remote_id == "remote-123"
    assert target.remote_url == "https://demo.local/x"
    assert target.published_at is not None
    assert target.attempts_count == 1


def test_aucune_republication_si_un_identifiant_distant_existe(session: Session, post, fake_connector: FakeConnector):
    """Règle d'idempotence : une cible déjà publiée n'est jamais renvoyée."""
    target = post.targets[0]
    publish_target(session, target, connector=fake_connector)
    assert fake_connector.calls == ["publish"]
    fake_connector.calls.clear()
    publish_target(session, target, connector=fake_connector)
    assert fake_connector.calls == ["status"], "la cible aurait dû être vérifiée, pas republiée"
    assert target.attempts_count == 1


def test_statut_incertain_ne_relance_jamais_automatiquement(session: Session, post, fake_connector: FakeConnector):
    fake_connector.outcomes = ["uncertain"]
    target = post.targets[0]
    publish_target(session, target, connector=fake_connector)
    assert target.status == PostStatus.UNCERTAIN.value
    assert target.requires_user_action is True
    fake_connector.calls.clear()
    publish_target(session, target, connector=fake_connector)
    assert fake_connector.calls == [], "aucune nouvelle tentative automatique n'est autorisée"


def test_resolution_humaine_d_un_statut_incertain(session: Session, post, fake_connector: FakeConnector):
    fake_connector.outcomes = ["uncertain"]
    target = post.targets[0]
    publish_target(session, target, connector=fake_connector)
    resolve_uncertain(session, target, "published", remote_url="https://youtu.be/xyz")
    assert target.status == PostStatus.PUBLISHED.value
    assert target.remote_url == "https://youtu.be/xyz"
    assert target.requires_user_action is False


def test_echec_journalise_avec_message_expurge(session: Session, post, fake_connector: FakeConnector):
    fake_connector.outcomes = ["failure"]
    target = post.targets[0]
    publish_target(session, target, connector=fake_connector)
    assert target.status == PostStatus.FAILED.value
    assert target.next_retry_at is not None
    attempt = session.scalar(select(PublishAttempt).where(PublishAttempt.post_target_id == target.id))
    assert attempt is not None
    assert attempt.outcome == AttemptOutcome.FAILURE.value
    assert attempt.http_status == 403
    assert "Refus simulé" in attempt.detail


def test_jamais_de_secret_dans_le_journal(session: Session, post, fake_connector: FakeConnector):
    fake_connector.outcomes = ["failure"]
    target = post.targets[0]
    target.error_message = None
    publish_target(session, target, connector=fake_connector)
    attempt = session.scalar(select(PublishAttempt).where(PublishAttempt.post_target_id == target.id))
    attempt.detail = "access_token=ya29.ABCDEFGHIJ1234567890 perdu"
    from socialdock.security import redact

    assert "ya29" not in (redact(attempt.detail) or "")


def test_publication_privee_signalee_et_action_requise(session: Session, post, fake_connector: FakeConnector):
    fake_connector.outcomes = ["private"]
    target = post.targets[0]
    publish_target(session, target, connector=fake_connector)
    assert target.status == PostStatus.PUBLISHED_PRIVATE.value
    assert target.requires_user_action is True


def test_compte_sans_capacite_de_publication_bascule_en_mode_assiste(session: Session, post):
    connector = FakeConnector(publish_video=False)
    target = post.targets[0]
    publish_target(session, target, connector=connector)
    assert target.status == PostStatus.WAITING_FOR_USER.value
    assert connector.calls == []
    assert "assisté" in (target.user_action_hint or "")


def test_compte_reel_sans_identifiants_ne_publie_pas(session: Session, imported_media, demo_accounts):
    """Un compte réel non configuré ne doit jamais être marqué comme publié."""
    from socialdock.services.accounts import create_account

    account = create_account(session, platform="youtube", display_name="YouTube réel non configuré")
    account.extra = {}
    post = make_post(session, imported_media, [account])
    target = post.targets[0]
    connector = FakeConnector(auth_available=False)
    publish_target(session, target, connector=connector)
    assert target.status == PostStatus.WAITING_FOR_USER.value
    assert connector.calls == []


def test_erreur_inattendue_du_connecteur_produit_un_statut_incertaint(session: Session, post):
    class ExplodingConnector(FakeConnector):
        def publish(self, context):  # noqa: D102 - comportement de test
            raise RuntimeError("panique réseau access_token=ya29.SECRET123456")

    target = post.targets[0]
    publish_target(session, target, connector=ExplodingConnector())
    assert target.status == PostStatus.UNCERTAIN.value
    assert target.requires_user_action is True
    assert "ya29" not in (target.error_message or "")


def test_verrou_empeche_l_execution_concurrente(session: Session, post, fake_connector: FakeConnector):
    from socialdock.services.publisher import acquire_lock, release_lock

    target = post.targets[0]
    assert acquire_lock(session, target, "worker-A") is True
    assert acquire_lock(session, target, "worker-B") is False
    release_lock(session, target)
    assert acquire_lock(session, target, "worker-B") is True


def test_verification_du_statut_distant(session: Session, post, fake_connector: FakeConnector):
    fake_connector.outcomes = ["uncertain"]
    target = post.targets[0]
    publish_target(session, target, connector=fake_connector)
    target.remote_id = "remote-123"
    refresh_remote_status(session, target, connector=fake_connector)
    assert target.status == PostStatus.PUBLISHED.value
    assert "status" in fake_connector.calls
