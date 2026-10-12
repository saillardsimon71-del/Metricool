"""Modèles de publication : métadonnées réutilisables en un clic."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import Post, PostStatus, PostTarget, PostTemplate, utcnow


def default_payload(platform: str, post: Post, *, hashtags: list[str] | None = None) -> dict[str, Any]:
    """Construit la variante par plateforme à partir des métadonnées communes.

    Seuls les champs réellement acceptés par l'API sont produits (voir
    ``docs/PLATFORM_FEASIBILITY.md``) : aucun paramètre fictif n'est généré.
    """
    tags = hashtags if hashtags is not None else list(post.hashtags or [])
    tag_line = " ".join(t if t.startswith("#") else f"#{t}" for t in tags)
    description = (post.description or "").strip()
    if platform == "youtube":
        body = description
        if tag_line:
            body = f"{body}\n\n{tag_line}".strip()
        return {
            "title": (post.title or "Sans titre")[:100],
            "description": body[:5000],
            "tags": [t.lstrip("#") for t in tags][:30],
            "category_id": None,
            "privacy": "private",
            "language": post.language or "fr",
            "made_for_kids": False,
            "embeddable": True,
            "public_stats_viewable": True,
        }
    if platform == "instagram":
        caption = description
        if tag_line:
            caption = f"{caption}\n\n{tag_line}".strip()
        return {
            "caption": caption[:2200],
            "share_to_feed": True,
            "thumb_offset_ms": 1000,
            "video_url": None,
        }
    if platform == "tiktok":
        caption = f"{description} {tag_line}".strip()
        return {
            "caption": caption[:2200],
            "privacy": "SELF_ONLY",
            "disable_comment": False,
            "disable_duet": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 1000,
            "is_aigc": False,
            "mode": "direct",
        }
    return {"caption": f"{description} {tag_line}".strip()[:4000]}


def apply_template(session: Session, post: Post, template_id: str) -> Post:
    template = session.get(PostTemplate, template_id)
    if template is None:
        return post
    payload = template.payload or {}
    post.hashtags = list(payload.get("hashtags") or post.hashtags or [])
    post.description = payload.get("description") or post.description
    post.language = payload.get("language") or post.language
    post.template_id = template.id
    per_platform = payload.get("per_platform") or {}
    for target in post.targets:
        platform = target.account.platform if target.account else "demo"
        base = default_payload(platform, post, hashtags=post.hashtags)
        base.update(per_platform.get(platform) or {})
        target.payload = base
    session.flush()
    return post


def build_payload_for(platform: str, post: Post, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = default_payload(platform, post)
    payload.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return payload


def create_targets_for_accounts(session: Session, post: Post, account_ids: list[str], *, scheduled_at=None) -> list[PostTarget]:
    """Ajoute une cible par compte, avec sa variante de métadonnées."""
    from ..models import Account

    existing = {t.account_id for t in post.targets}
    created: list[PostTarget] = []
    for account_id in account_ids:
        if account_id in existing:
            continue
        account = session.get(Account, account_id)
        if account is None:
            continue
        target = PostTarget(
            account_id=account.id,
            status=PostStatus.DRAFT.value,
            scheduled_at=scheduled_at,
            payload=default_payload(account.platform, post),
        )
        # Ajout via la relation : la collection ``post.targets`` reste synchronisée
        # sans requête supplémentaire (sinon l'API renverrait une liste vide).
        post.targets.append(target)
        session.add(target)
        created.append(target)
    session.flush()
    return created


def template_from_post(session: Session, post: Post, name: str, description: str | None = None) -> PostTemplate:
    """Enregistre la configuration d'une publication comme modèle réutilisable."""
    per_platform: dict[str, Any] = {}
    for target in post.targets:
        platform = target.account.platform if target.account else "demo"
        per_platform[platform] = dict(target.payload or {})
    template = PostTemplate(
        name=name,
        description=description,
        payload={
            "hashtags": list(post.hashtags or []),
            "description": post.description,
            "language": post.language,
            "per_platform": per_platform,
            "account_ids": [t.account_id for t in post.targets],
        },
    )
    session.add(template)
    session.flush()
    return template
