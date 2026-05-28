"""PROF-01 个人档案管理 — MVP Phase 1 多档案版路由。

- GET  /api/v1/profiles           — 查询当前用户的档案列表
- GET  /api/v1/profiles/me        — 查询当前用户的默认档案（快捷端点）
- GET  /api/v1/profiles/{id}      — 查询指定档案详情
- POST /api/v1/profiles           — 创建新档案
- PUT  /api/v1/profiles/{id}      — 更新档案
- DELETE /api/v1/profiles/{id}    — 删除档案
- PUT  /api/v1/profiles/{id}/default — 设为默认档案

去除 JWT、RBAC、隐私控制。
"""

from __future__ import annotations

import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.anonymous_user import get_anonymous_user
from app.dependencies.auth_dependencies import get_db_session
from app.services.profile_service import ProfileService
from py_schemas.cases import PaginatedResponse
from py_schemas.profiles import ProfileCreate, ProfileListItem, ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])
_profile_service = ProfileService()


def _extract_user_id(anonymous_user: dict) -> UUID:
    """从匿名用户字典中提取用户 UUID。"""
    user_id_str: str = anonymous_user.get("sub", anonymous_user.get("user_id", ""))
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无法解析用户标识",
        )
    try:
        return UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户标识格式无效",
        )


# ===========================================================================
# GET /api/v1/profiles — 档案列表
# ===========================================================================


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    summary="获取档案列表",
    description="查询当前匿名用户的所有档案列表，按创建时间倒序排列。",
    response_model=PaginatedResponse[ProfileListItem],
)
async def list_profiles_endpoint(
    page: int = Query(default=1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(default=10, ge=1, le=100, description="每页条数"),
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[ProfileListItem]:
    """档案列表端点。"""
    caregiver_id = _extract_user_id(anonymous_user)
    items, total = await _profile_service.list_profiles(
        caregiver_id=caregiver_id,
        session=session,
        page=page,
        page_size=page_size,
    )
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return PaginatedResponse[ProfileListItem](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ===========================================================================
# GET /api/v1/profiles/me — 默认档案（快捷端点）
# ===========================================================================


@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="获取我的默认档案",
    description="查询当前匿名用户的默认档案。若无档案返回 404。",
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
    """获取当前用户默认档案端点。"""
    caregiver_id = _extract_user_id(anonymous_user)
    result = await _profile_service.get_my_profile(
        caregiver_id=caregiver_id,
        session=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="暂无档案，请先创建",
        )
    return result


# ===========================================================================
# GET /api/v1/profiles/{profile_id} — 档案详情
# ===========================================================================


@router.get(
    "/{profile_id}",
    status_code=status.HTTP_200_OK,
    summary="获取档案详情",
    description="按 ID 查询指定档案详情。仅返回当前用户自己的档案。",
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
    """档案详情端点。"""
    caregiver_id = _extract_user_id(anonymous_user)
    result = await _profile_service.get_profile(
        profile_id=profile_id,
        caregiver_id=caregiver_id,
        session=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="档案不存在",
        )
    return result


# ===========================================================================
# POST /api/v1/profiles — 创建档案
# ===========================================================================


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="创建档案",
    description="为当前匿名用户创建新档案。若用户尚无档案，自动设为默认。",
    response_model=ProfileResponse,
    responses={
        201: {"description": "档案创建成功"},
        422: {"description": "请求体校验失败"},
    },
)
async def create_profile_endpoint(
    input_data: ProfileCreate,
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    """创建档案端点。"""
    caregiver_id = _extract_user_id(anonymous_user)
    return await _profile_service.create_profile(
        caregiver_id=caregiver_id,
        input_data=input_data,
        session=session,
    )


# ===========================================================================
# PUT /api/v1/profiles/{profile_id} — 更新档案
# ===========================================================================


@router.put(
    "/{profile_id}",
    status_code=status.HTTP_200_OK,
    summary="更新档案",
    description="部分更新指定档案。仅更新提供的字段，未提供的字段保持原值。",
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
    """更新档案端点。"""
    caregiver_id = _extract_user_id(anonymous_user)
    return await _profile_service.update_profile(
        profile_id=profile_id,
        caregiver_id=caregiver_id,
        input_data=input_data,
        session=session,
    )


# ===========================================================================
# DELETE /api/v1/profiles/{profile_id} — 删除档案
# ===========================================================================


@router.delete(
    "/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除档案",
    description="删除指定档案。若删除的是默认档案，自动将最新更新的剩余档案提升为默认。",
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
    """删除档案端点。"""
    caregiver_id = _extract_user_id(anonymous_user)
    await _profile_service.delete_profile(
        profile_id=profile_id,
        caregiver_id=caregiver_id,
        session=session,
    )


# ===========================================================================
# PUT /api/v1/profiles/{profile_id}/default — 设为默认
# ===========================================================================


@router.put(
    "/{profile_id}/default",
    status_code=status.HTTP_200_OK,
    summary="设为默认档案",
    description="将指定档案设为默认，同时取消该用户其他档案的默认标记。",
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
    """设为默认档案端点。"""
    caregiver_id = _extract_user_id(anonymous_user)
    return await _profile_service.set_default_profile(
        profile_id=profile_id,
        caregiver_id=caregiver_id,
        session=session,
    )


__all__ = ["router"]
