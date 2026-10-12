"""API publications : compositeur, cibles, programmation, mode assisté."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Post, PostStatus, PostTarget, PostTemplate
from ..schemas import (
    AssistedCompletionRequest,
    BatchScheduleRequest,
    PostCreate,
    PostOut,
    PostPatch,
    PostTargetOut,
    ResolveUncertainRequest,
    ScheduleRequest,
    TemplateCreate,
    TemplateOut,
)
from ..services import posts as post_service
from ..services.posts import PostError
from ..services.publisher import refresh_remote_status, resolve_uncertain
from ..services.states import describe_status
from ..services.templates import apply_template, template_from_post
from .deps import db_session

router = APIRouter(prefix="/api/posts", tags=["posts"])


def _target(session: Session, target_id: str) -> PostTarget:
    target = session.get(PostTarget, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Cible de publication introuvable.")
    return target


def _post(session: Session, post_id: str) -> Post:
    post = session.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Publication introuvable.")
    return post


@router.get("", response_model=dict[str, Any])
def list_posts(
    status: list[str] | None = Query(default=None),
    account_id: list[str] | None = Query(default=None),
    q: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    targets, total = post_service.list_targets(
        session, status=status, account_ids=account_id, start=start, end=end, query=q, limit=limit, offset=offset
    )
    return {
        "items": [
            {
                "target": PostTargetOut.model_validate(t).model_dump(mode="json"),
                "post": PostOut.model_validate(t.post).model_dump(mode="json") if t.post else None,
                "account": {"id": t.account.id, "display_name": t.account.display_name, "platform": t.account.platform, "mode": t.account.mode}
                if t.account
                else None,
                "status_label": describe_status(t.status),
            }
            for t in targets
        ],
        "total": total,
    }


@router.post("", response_model=PostOut, status_code=201)
def create_post(payload: PostCreate, session: Session = Depends(db_session)) -> Post:
    try:
        post = post_service.create_post(
            session,
            title=payload.title,
            description=payload.description,
            hashtags=payload.hashtags,
            media_asset_id=payload.media_asset_id,
            thumbnail_media_id=payload.thumbnail_media_id,
            series_id=payload.series_id,
            episode_number=payload.episode_number,
            language=payload.language,
            internal_notes=payload.internal_notes,
            account_ids=payload.account_ids,
            per_platform=payload.per_platform,
        )
    except PostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    return post


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(session: Session = Depends(db_session)) -> list[PostTemplate]:
    return list(session.scalars(select(PostTemplate).order_by(PostTemplate.name.asc())).all())


@router.post("/templates", response_model=TemplateOut, status_code=201)
def create_template(payload: TemplateCreate, session: Session = Depends(db_session)) -> PostTemplate:
    if payload.from_post_id:
        post = _post(session, payload.from_post_id)
        template = template_from_post(session, post, payload.name, payload.description)
    else:
        template = PostTemplate(name=payload.name, description=payload.description, payload=payload.payload)
        session.add(template)
    session.commit()
    return template


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: str, session: Session = Depends(db_session)) -> None:
    template = session.get(PostTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Modèle introuvable.")
    session.delete(template)


@router.post("/{post_id}/template", response_model=PostOut)
def apply_post_template(post_id: str, template_id: str, session: Session = Depends(db_session)) -> Post:
    post = _post(session, post_id)
    apply_template(session, post, template_id)
    session.commit()
    return post


@router.post("/batch-schedule", response_model=dict[str, Any])
def batch_schedule(payload: BatchScheduleRequest, session: Session = Depends(db_session)) -> dict[str, Any]:
    try:
        result = post_service.batch_schedule(
            session,
            media_ids=payload.media_ids,
            account_ids=payload.account_ids,
            days=payload.days,
            times=payload.times,
            template_id=payload.template_id,
            per_platform=payload.per_platform,
            title_prefix=payload.title_prefix,
            stagger_minutes=payload.stagger_minutes,
        )
    except PostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    return result


@router.get("/{post_id}", response_model=PostOut)
def get_post(post_id: str, session: Session = Depends(db_session)) -> Post:
    return _post(session, post_id)


@router.patch("/{post_id}", response_model=PostOut)
def patch_post(post_id: str, payload: PostPatch, session: Session = Depends(db_session)) -> Post:
    try:
        post = post_service.update_post(session, post_id, **payload.model_dump(exclude_unset=True))
    except PostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    return post


@router.post("/{post_id}/duplicate", response_model=PostOut, status_code=201)
def duplicate_post(post_id: str, session: Session = Depends(db_session)) -> Post:
    try:
        post = post_service.duplicate_post(session, post_id)
    except PostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    return post


@router.delete("/{post_id}", status_code=204)
def delete_post(post_id: str, confirm: bool = Query(default=False), session: Session = Depends(db_session)) -> None:
    try:
        post_service.delete_post(session, post_id, confirm=confirm)
    except PostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/targets/{target_id}", response_model=PostTargetOut)
def get_target(target_id: str, session: Session = Depends(db_session)) -> PostTarget:
    return _target(session, target_id)


@router.patch("/targets/{target_id}", response_model=PostTargetOut)
def patch_target_payload(target_id: str, payload: dict[str, Any], session: Session = Depends(db_session)) -> PostTarget:
    target = _target(session, target_id)
    try:
        return post_service.update_target_payload(session, target, payload)
    except PostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/targets/{target_id}/schedule", response_model=PostTargetOut)
def schedule_target(target_id: str, payload: ScheduleRequest, session: Session = Depends(db_session)) -> PostTarget:
    target = _target(session, target_id)
    try:
        return post_service.schedule_target(session, target, payload.scheduled_at)
    except PostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/targets/{target_id}/unschedule", response_model=PostTargetOut)
def unschedule_target(target_id: str, session: Session = Depends(db_session)) -> PostTarget:
    target = _target(session, target_id)
    try:
        return post_service.unschedule_target(session, target)
    except PostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/targets/{target_id}/publish-now", response_model=PostTargetOut)
def publish_now(target_id: str, session: Session = Depends(db_session)) -> PostTarget:
    target = _target(session, target_id)
    try:
        return post_service.publish_now(session, target)
    except PostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/targets/{target_id}/cancel", response_model=PostTargetOut)
def cancel_target(target_id: str, session: Session = Depends(db_session)) -> PostTarget:
    target = _target(session, target_id)
    try:
        return post_service.cancel_target(session, target)
    except PostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/targets/{target_id}/resolve", response_model=PostTargetOut)
def resolve(target_id: str, payload: ResolveUncertainRequest, session: Session = Depends(db_session)) -> PostTarget:
    target = _target(session, target_id)
    if target.status != PostStatus.UNCERTAIN.value:
        raise HTTPException(status_code=409, detail="Seule une publication au statut incertain peut être résolue ici.")
    try:
        return resolve_uncertain(session, target, payload.resolution, remote_url=payload.remote_url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/targets/{target_id}/refresh-status", response_model=PostTargetOut)
def refresh_status(target_id: str, session: Session = Depends(db_session)) -> PostTarget:
    target = _target(session, target_id)
    return refresh_remote_status(session, target)


@router.post("/targets/{target_id}/assisted", response_model=PostTargetOut)
def prepare_assisted(target_id: str, session: Session = Depends(db_session)) -> PostTarget:
    """Bascule explicitement une cible en mode assisté (action humaine)."""
    target = _target(session, target_id)
    if target.status in {PostStatus.PUBLISHED.value, PostStatus.PUBLISHED_PRIVATE.value}:
        raise HTTPException(status_code=409, detail="Publication déjà effective.")
    target.requires_user_action = True
    target.user_action_hint = (
        "Publication assistée : ouvrez la plateforme, importez le média préparé, collez la description, "
        "puis enregistrez le lien publié ci-dessous."
    )
    target.status = PostStatus.WAITING_FOR_USER.value
    session.commit()
    return target


@router.post("/targets/{target_id}/assisted/complete", response_model=PostTargetOut)
def complete_assisted(target_id: str, payload: AssistedCompletionRequest, session: Session = Depends(db_session)) -> PostTarget:
    target = _target(session, target_id)
    if target.status not in {PostStatus.WAITING_FOR_USER.value, PostStatus.DRAFT.value, PostStatus.READY.value, PostStatus.UNCERTAIN.value}:
        raise HTTPException(status_code=409, detail=f"Statut incompatible : {describe_status(target.status)}.")
    from ..models import utcnow

    target.remote_url = payload.remote_url
    target.status = payload.status
    target.published_at = payload.published_at or utcnow()
    target.requires_user_action = False
    target.user_action_hint = None
    session.commit()
    return target
