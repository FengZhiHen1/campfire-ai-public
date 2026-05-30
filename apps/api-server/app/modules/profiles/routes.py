"""PROF-01 个人档案管理 — API 路由。

端点:
- GET    /api/v1/profiles                — 查询当前用户的档案列表
- GET    /api/v1/profiles/me             — 查询当前用户的默认档案
- GET    /api/v1/profiles/tags/preset    — 预设标签池
- GET    /api/v1/profiles/{profile_id}    — 查询指定档案详情
- POST   /api/v1/profiles                — 创建新档案
- PUT    /api/v1/profiles/{profile_id}    — 更新档案
- DELETE /api/v1/profiles/{profile_id}    — 删除档案
- PUT    /api/v1/profiles/{profile_id}/default — 设为默认档案
"""

from __future__ import annotations

import math
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.anonymous_user import get_anonymous_user
from app.core.dependencies.auth_dependencies import get_db_session
from app.modules.profiles._constants import PRESET_TAGS
from app.modules.profiles._exception_mapping import map_domain_error
from app.modules.profiles._user_utils import extract_user_id
from app.modules.profiles.exceptions import ProfileDomainError
from app.modules.profiles.profile_service import ProfileServiceImpl
from py_schemas.cases import PaginatedResponse
from py_schemas.profiles import ProfileCreate, ProfileListItem, ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])
_profile_service = ProfileServiceImpl()


# ===========================================================================
# GET /api/v1/profiles — 档案列表
# ===========================================================================


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    summary="获取档案列表",
    response_model=PaginatedResponse[ProfileListItem],
)
async def list_profiles_endpoint(
    page: int = Query(default=1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(default=10, ge=1, le=100, description="每页条数"),
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[ProfileListItem]:
    caregiver_id = extract_user_id(anonymous_user)
    try:
        items, total = await _profile_service.list_profiles(
            caregiver_id=caregiver_id,
            session=session,
            page=page,
            page_size=page_size,
        )
    except ProfileDomainError as exc:
        raise map_domain_error(exc)

    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return PaginatedResponse[ProfileListItem](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ===========================================================================
# GET /api/v1/profiles/me — 默认档案
# ===========================================================================


@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="获取我的默认档案",
    response_model=ProfileResponse,
    responses={
        200: {"description": "成功返回档案详情"},
        404: {"description": "该用户暂无档案"},
    },
)
async def get_my_profile_endpoint(
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    caregiver_id = extract_user_id(anonymous_user)
    try:
        return await _profile_service.get_my_profile(
            caregiver_id=caregiver_id,
            session=session,
        )
    except ProfileDomainError as exc:
        raise map_domain_error(exc)


# ===========================================================================
# GET /api/v1/profiles/tags/preset — 预设标签池
# ===========================================================================


@router.get(
    "/tags/preset",
    status_code=status.HTTP_200_OK,
    summary="获取预设标签池",
)
async def get_preset_tags_endpoint() -> dict[str, list[str]]:
    return {"tags": PRESET_TAGS}


# ===========================================================================
# GET /api/v1/profiles/{profile_id} — 档案详情
# ===========================================================================


@router.get(
    "/{profile_id}",
    status_code=status.HTTP_200_OK,
    summary="获取档案详情",
    response_model=ProfileResponse,
    responses={
        200: {"description": "成功返回档案详情"},
        404: {"description": "档案不存在"},
    },
)
async def get_profile_endpoint(
    profile_id: UUID,
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    caregiver_id = extract_user_id(anonymous_user)
    try:
        return await _profile_service.get_profile(
            profile_id=profile_id,
            caregiver_id=caregiver_id,
            session=session,
        )
    except ProfileDomainError as exc:
        raise map_domain_error(exc)


# ===========================================================================
# POST /api/v1/profiles — 创建档案
# ===========================================================================


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="创建档案",
    response_model=ProfileResponse,
    responses={
        201: {"description": "档案创建成功"},
        409: {"description": "档案数量已达上限"},
        422: {"description": "请求体校验失败"},
    },
)
async def create_profile_endpoint(
    input_data: ProfileCreate,
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    caregiver_id = extract_user_id(anonymous_user)
    try:
        return await _profile_service.create_profile(
            caregiver_id=caregiver_id,
            input_data=input_data,
            session=session,
        )
    except ProfileDomainError as exc:
        raise map_domain_error(exc)


# ===========================================================================
# PUT /api/v1/profiles/{profile_id} — 更新档案
# ===========================================================================


@router.put(
    "/{profile_id}",
    status_code=status.HTTP_200_OK,
    summary="更新档案",
    response_model=ProfileResponse,
    responses={
        200: {"description": "档案更新成功"},
        404: {"description": "档案不存在"},
        422: {"description": "请求体校验失败"},
    },
)
async def update_profile_endpoint(
    profile_id: UUID,
    input_data: ProfileUpdate,
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    caregiver_id = extract_user_id(anonymous_user)
    try:
        return await _profile_service.update_profile(
            profile_id=profile_id,
            caregiver_id=caregiver_id,
            input_data=input_data,
            session=session,
        )
    except ProfileDomainError as exc:
        raise map_domain_error(exc)


# ===========================================================================
# DELETE /api/v1/profiles/{profile_id} — 删除档案
# ===========================================================================


@router.delete(
    "/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除档案",
    responses={
        204: {"description": "删除成功"},
        404: {"description": "档案不存在"},
    },
)
async def delete_profile_endpoint(
    profile_id: UUID,
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    caregiver_id = extract_user_id(anonymous_user)
    try:
        await _profile_service.delete_profile(
            profile_id=profile_id,
            caregiver_id=caregiver_id,
            session=session,
        )
    except ProfileDomainError as exc:
        raise map_domain_error(exc)


# ===========================================================================
# PUT /api/v1/profiles/{profile_id}/default — 设为默认
# ===========================================================================


@router.put(
    "/{profile_id}/default",
    status_code=status.HTTP_200_OK,
    summary="设为默认档案",
    response_model=ProfileResponse,
    responses={
        200: {"description": "设置成功"},
        404: {"description": "档案不存在"},
    },
)
async def set_default_profile_endpoint(
    profile_id: UUID,
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    caregiver_id = extract_user_id(anonymous_user)
    try:
        return await _profile_service.set_default_profile(
            profile_id=profile_id,
            caregiver_id=caregiver_id,
            session=session,
        )
    except ProfileDomainError as exc:
        raise map_domain_error(exc)


__all__ = ["router"]
