"""Machine à états des publications (voir ``models.ALLOWED_TRANSITIONS``)."""

from __future__ import annotations

from ..models import ALLOWED_TRANSITIONS, PostStatus, PostTarget


class InvalidTransition(ValueError):
    def __init__(self, current: str, requested: str) -> None:
        super().__init__(f"Transition refusée : {current} → {requested}")
        self.current = current
        self.requested = requested


def can_transition(current: str | PostStatus, requested: str | PostStatus) -> bool:
    current = PostStatus(current)
    requested = PostStatus(requested)
    return requested in ALLOWED_TRANSITIONS.get(current, set())


def assert_transition(current: str | PostStatus, requested: str | PostStatus) -> None:
    if not can_transition(current, requested):
        raise InvalidTransition(str(current), str(requested))


def set_status(target: PostTarget, status: str | PostStatus) -> PostTarget:
    """Applique une transition validée. Toute autre voie est un bug."""
    assert_transition(target.status, status)
    target.status = str(PostStatus(status))
    return target


def is_terminal(status: str) -> bool:
    return status in {s.value for s in (PostStatus.PUBLISHED, PostStatus.PUBLISHED_PRIVATE, PostStatus.CANCELLED)}


def needs_human(status: str) -> bool:
    return status in {PostStatus.WAITING_FOR_USER.value, PostStatus.UNCERTAIN.value}


def describe_status(status: str) -> str:
    """Libellés français utilisés par l'interface."""
    return {
        PostStatus.DRAFT.value: "Brouillon",
        PostStatus.READY.value: "Prête",
        PostStatus.SCHEDULED.value: "Programmée",
        PostStatus.WAITING_FOR_USER.value: "Action humaine requise",
        PostStatus.UPLOADING.value: "Envoi en cours",
        PostStatus.PROCESSING.value: "Traitement plateforme",
        PostStatus.PUBLISHING.value: "Publication en cours",
        PostStatus.PUBLISHED.value: "Publiée",
        PostStatus.PUBLISHED_PRIVATE.value: "Publiée (privée)",
        PostStatus.FAILED.value: "Échec",
        PostStatus.UNCERTAIN.value: "Statut incertain",
        PostStatus.CANCELLED.value: "Annulée",
    }.get(status, status)
