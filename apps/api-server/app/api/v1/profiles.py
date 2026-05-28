"""PROF-01 个人档案管理 — MVP Phase 1 简化版路由。

- GET  /api/v1/profiles/me — 查询当前匿名用户的档案
- POST /api/v1/profiles    — 创建/更新档案（upsert）

去除 JWT、RBAC、隐私控制、事件管理。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.anonymous_user import get_anonymous_user
from app.dependencies.auth_dependencies import get_db_session
from app.services.profile_service import ProfileService
from py_schemas.profiles import ProfileCreate, ProfileResponse

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
# GET /api/v1/profiles/me
# ===========================================================================


@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="获取我的档案",
    description="查询当前匿名用户（device_id）关联的个人档案。若无档案返回 404。",
    response_model=ProfileResponse,
    responses={
        200: {"description": "成功返回档案详情"},
        404: {"description": "该用户暂无档案"},
    },
)
async def get_my_profile(
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    """获取当前用户档案端点。"""
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
# POST /api/v1/profiles
# ===========================================================================


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="创建或更新档案",
    description=(
        "为当前匿名用户创建或更新患者档案。"
        "若已存在档案则更新，不存在则创建。"
    ),
    response_model=ProfileResponse,
    responses={
        201: {"description": "档案创建/更新成功"},
        422: {"description": "请求体校验失败"},
    },
)
async def upsert_profile(
    input_data: ProfileCreate,
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    """创建/更新档案端点。"""
    caregiver_id = _extract_user_id(anonymous_user)
    return await _profile_service.get_or_create_profile(
        caregiver_id=caregiver_id,
        input_data=input_data,
        session=session,
    )


__all__ = ["router"]
