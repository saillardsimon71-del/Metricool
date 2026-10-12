"""Machine à états : transitions autorisées et refusées."""

from __future__ import annotations

import pytest

from socialdock.models import PostStatus
from socialdock.services.states import InvalidTransition, assert_transition, can_transition, describe_status, needs_human


def test_transitions_normales_autorisees():
    assert can_transition(PostStatus.DRAFT, PostStatus.SCHEDULED)
    assert can_transition(PostStatus.SCHEDULED, PostStatus.UPLOADING)
    assert can_transition(PostStatus.UPLOADING, PostStatus.PUBLISHING)
    assert can_transition(PostStatus.PUBLISHING, PostStatus.PUBLISHED)


def test_transition_illegale_refusee():
    assert not can_transition(PostStatus.CANCELLED, PostStatus.PUBLISHED)
    assert not can_transition(PostStatus.PUBLISHED, PostStatus.DRAFT)
    with pytest.raises(InvalidTransition):
        assert_transition(PostStatus.PUBLISHED, PostStatus.SCHEDULED)


def test_un_statut_inconnu_leve_une_erreur():
    with pytest.raises(ValueError):
        can_transition("inexistant", PostStatus.PUBLISHED)


def test_etats_exigeant_une_intervention_humaine():
    assert needs_human(PostStatus.WAITING_FOR_USER.value)
    assert needs_human(PostStatus.UNCERTAIN.value)
    assert not needs_human(PostStatus.PUBLISHED.value)


def test_tous_les_statuts_ont_un_libelle_francais():
    for status in PostStatus:
        label = describe_status(status.value)
        assert label and label != status.value
