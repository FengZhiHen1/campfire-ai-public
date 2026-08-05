"""profiles 模块路由（ADR-010 四层档案）。

端点（角色收敛：family 主控；teacher/expert/volunteer 受邀协作）：
- GET/POST   /api/v1/profiles                          — 档案列表/创建
- GET/PATCH/DELETE /api/v1/profiles/{id}               — 详情/更新/删除
- GET/POST   /api/v1/profiles/{id}/events              — 事件时间线/一键打点
- POST       /api/v1/profiles/{id}/events/{eid}/complete — 事后补全
- POST       /api/v1/profiles/{id}/notes               — 专业评估挂载
- GET        /api/v1/profiles/{id}/events/{eid}/notes  — 事件评估列表
- GET/POST   /api/v1/profiles/{id}/access              — 关联列表/邀请
- DELETE     /api/v1/profiles/{id}/access/{aid}        — 解除关联
- GET        /api/v1/profiles/shared-with-me           — 我受邀的档案（协作方视角）
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from py_db.repositories.profile_repository import (
    EventLogRepository,
    ProfessionalNoteRepository,
    ProfileAccessRepository,
    ProfileRepository,
)
from py_db.repositories.user_repository import UserRepository
from py_schemas.auth import UserRole
from py_schemas.profiles import (
    EventCompleteRequest,
    EventCreateRequest,
    ProfessionalNoteCreateRequest,
    ProfileAccessCreateRequest,
    ProfileCreateRequest,
    ProfileUpdateRequest,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.auth_dependencies import (
    CurrentUser,
    _get_session_factory,
    get_db_session,
    require_roles,
)
from app.modules.profiles.access_service import AccessService, NoteService
from app.modules.profiles.event_service import EventService
from app.modules.profiles.exceptions import (
    AccessNotFoundError,
    DuplicateAccessError,
    EventNotFoundError,
    InviteeNotFoundError,
    ProfileError,
    ProfileForbiddenError,
    ProfileNotFoundError,
)
from app.modules.profiles.guard import require_profile_access
from app.modules.profiles.profile_service import ProfileService

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])

_PROFILE_ROLES = (UserRole.FAMILY, UserRole.VOLUNTEER, UserRole.TEACHER, UserRole.EXPERT)

_EXCEPTION_STATUS: dict[type[ProfileError], int] = {
    ProfileNotFoundError: 404,
    EventNotFoundError: 404,
    AccessNotFoundError: 404,
    ProfileForbiddenError: 403,
    InviteeNotFoundError: 422,
    DuplicateAccessError: 409,
}


def _raise_http(exc: ProfileError) -> None:
    raise HTTPException(
        status_code=_EXCEPTION_STATUS.get(type(exc), 500),
        detail={"code": exc.code, "message": exc.message},
    )


def _repos() -> tuple[ProfileRepository, ProfileAccessRepository]:
    factory = _get_session_factory()
    return ProfileRepository(session_factory=factory), ProfileAccessRepository(session_factory=factory)


async def _viewer(
    session: AsyncSession,
    profile_id: str,
    user: CurrentUser,
) -> Any:
    profile_repo, access_repo = _repos()
    return await require_profile_access(session, profile_id, user, profile_repo, access_repo)


# ===========================================================================
# 档案 CRUD
# ===========================================================================


@router.get("", summary="档案列表（家属名下 + 受邀协作）")
async def list_profiles(
    current_user: CurrentUser = Depends(require_roles(*_PROFILE_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = ProfileService(ProfileRepository(session_factory=_get_session_factory()))
    items = await service.list_mine(db, current_user.user_id)

    # 受邀协作档案（teacher/expert/volunteer 视角）
    access_repo = ProfileAccessRepository(session_factory=_get_session_factory())
    accesses = await access_repo.list_by_user(db, UUID(current_user.user_id))
    shared: list[dict[str, Any]] = []
    profile_repo = ProfileRepository(session_factory=_get_session_factory())
    for access in accesses:
        profile = await profile_repo.get_by_id(db, access.profile_id)
        if profile:
            shared.append(
                {
                    "profile_id": str(profile.profile_id),
                    "nickname": profile.nickname,
                    "age_range": service.to_response(profile).age_range,
                    "diagnosis_type": profile.diagnosis_type,
                    "primary_behavior": profile.primary_behavior.value,
                    "is_default": False,
                    "created_at": profile.created_at.isoformat(),
                    "shared_role": access.role.value,
                }
            )
    return {
        "items": [i.model_dump(mode="json") for i in items],
        "shared_items": shared,
        "total": len(items),
    }


@router.post("", status_code=status.HTTP_201_CREATED, summary="创建档案（家属）")
async def create_profile(
    request: ProfileCreateRequest,
    current_user: CurrentUser = Depends(require_roles(UserRole.FAMILY)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = ProfileService(ProfileRepository(session_factory=_get_session_factory()))
    return (await service.create(db, current_user.user_id, request)).model_dump(mode="json")


@router.get("/{profile_id}", summary="档案详情（家属/关联者）")
async def get_profile(
    profile_id: str,
    current_user: CurrentUser = Depends(require_roles(*_PROFILE_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        viewer = await _viewer(db, profile_id, current_user)
    except ProfileError as exc:
        _raise_http(exc)
    service = ProfileService(ProfileRepository(session_factory=_get_session_factory()))
    return service.to_response(viewer.profile, viewer).model_dump(mode="json")


@router.patch("/{profile_id}", summary="更新档案（仅家属，分层部分更新）")
async def update_profile(
    profile_id: str,
    request: ProfileUpdateRequest,
    current_user: CurrentUser = Depends(require_roles(UserRole.FAMILY)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        viewer = await _viewer(db, profile_id, current_user)
        if not viewer.can_edit_profile:
            raise ProfileForbiddenError()
        service = ProfileService(ProfileRepository(session_factory=_get_session_factory()))
        return (await service.update(db, viewer.profile, request)).model_dump(mode="json")
    except ProfileError as exc:
        _raise_http(exc)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除档案（仅家属）")
async def delete_profile(
    profile_id: str,
    current_user: CurrentUser = Depends(require_roles(UserRole.FAMILY)),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    try:
        viewer = await _viewer(db, profile_id, current_user)
        if not viewer.can_edit_profile:
            raise ProfileForbiddenError()
        service = ProfileService(ProfileRepository(session_factory=_get_session_factory()))
        await service.delete(db, viewer.profile)
    except ProfileError as exc:
        _raise_http(exc)


# ===========================================================================
# 事件（双模式）
# ===========================================================================


@router.get("/{profile_id}/events", summary="事件时间线")
async def list_events(
    profile_id: str,
    current_user: CurrentUser = Depends(require_roles(*_PROFILE_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        viewer = await _viewer(db, profile_id, current_user)
        service = EventService(EventLogRepository(session_factory=_get_session_factory()))
        items = await service.list_events(db, viewer)
        return {"items": [i.model_dump(mode="json") for i in items], "total": len(items)}
    except ProfileError as exc:
        _raise_http(exc)


@router.post("/{profile_id}/events", status_code=status.HTTP_201_CREATED, summary="一键打点")
async def quick_log_event(
    profile_id: str,
    request: EventCreateRequest,
    current_user: CurrentUser = Depends(require_roles(*_PROFILE_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        viewer = await _viewer(db, profile_id, current_user)
        service = EventService(EventLogRepository(session_factory=_get_session_factory()))
        return (await service.quick_log(db, viewer, current_user.user_id, request)).model_dump(mode="json")
    except ProfileError as exc:
        _raise_http(exc)


@router.post("/{profile_id}/events/{event_id}/complete", summary="事后补全（仅家属）")
async def complete_event(
    profile_id: str,
    event_id: str,
    request: EventCompleteRequest,
    current_user: CurrentUser = Depends(require_roles(UserRole.FAMILY)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        viewer = await _viewer(db, profile_id, current_user)
        service = EventService(EventLogRepository(session_factory=_get_session_factory()))
        return (await service.complete(db, viewer, event_id, request)).model_dump(mode="json")
    except ProfileError as exc:
        _raise_http(exc)


# ===========================================================================
# 专业评估
# ===========================================================================


@router.post("/{profile_id}/notes", status_code=status.HTTP_201_CREATED, summary="专业评估挂载（老师/专家）")
async def create_note(
    profile_id: str,
    request: ProfessionalNoteCreateRequest,
    current_user: CurrentUser = Depends(require_roles(UserRole.TEACHER, UserRole.EXPERT)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        viewer = await _viewer(db, profile_id, current_user)
        service = NoteService(ProfessionalNoteRepository(session_factory=_get_session_factory()))
        return (
            await service.create_note(db, viewer, current_user.user_id, current_user.role.value, request)
        ).model_dump(mode="json")
    except ProfileError as exc:
        _raise_http(exc)


@router.get("/{profile_id}/events/{event_id}/notes", summary="事件的专业评估列表")
async def list_notes(
    profile_id: str,
    event_id: str,
    current_user: CurrentUser = Depends(require_roles(*_PROFILE_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        await _viewer(db, profile_id, current_user)  # 访问判定（无权即 404）
        service = NoteService(ProfessionalNoteRepository(session_factory=_get_session_factory()))
        items = await service.list_notes_for_event(db, event_id)
        return {"items": [i.model_dump(mode="json") for i in items], "total": len(items)}
    except ProfileError as exc:
        _raise_http(exc)


# ===========================================================================
# 关联管理
# ===========================================================================


@router.get("/{profile_id}/access", summary="关联列表（家属）")
async def list_access(
    profile_id: str,
    current_user: CurrentUser = Depends(require_roles(UserRole.FAMILY)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        viewer = await _viewer(db, profile_id, current_user)
        service = AccessService(
            ProfileAccessRepository(session_factory=_get_session_factory()),
            UserRepository(session_factory=_get_session_factory()),
        )
        items = await service.list_access(db, viewer)
        return {"items": [i.model_dump(mode="json") for i in items], "total": len(items)}
    except ProfileError as exc:
        _raise_http(exc)


@router.post("/{profile_id}/access", status_code=status.HTTP_201_CREATED, summary="关联邀请（家属）")
async def invite_access(
    profile_id: str,
    request: ProfileAccessCreateRequest,
    current_user: CurrentUser = Depends(require_roles(UserRole.FAMILY)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        viewer = await _viewer(db, profile_id, current_user)
        service = AccessService(
            ProfileAccessRepository(session_factory=_get_session_factory()),
            UserRepository(session_factory=_get_session_factory()),
        )
        return (await service.invite(db, viewer, current_user.user_id, request)).model_dump(mode="json")
    except ProfileError as exc:
        _raise_http(exc)


@router.delete("/{profile_id}/access/{access_id}", status_code=status.HTTP_204_NO_CONTENT, summary="解除关联（家属）")
async def revoke_access(
    profile_id: str,
    access_id: str,
    current_user: CurrentUser = Depends(require_roles(UserRole.FAMILY)),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    try:
        viewer = await _viewer(db, profile_id, current_user)
        service = AccessService(
            ProfileAccessRepository(session_factory=_get_session_factory()),
            UserRepository(session_factory=_get_session_factory()),
        )
        await service.revoke(db, viewer, access_id)
    except ProfileError as exc:
        _raise_http(exc)


__all__ = ["router"]
