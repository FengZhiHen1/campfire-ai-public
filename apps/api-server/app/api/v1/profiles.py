"""PROF-01 个人档案管理 + PROF-03 事件记录管理 — FastAPI 路由注册。

PROF-01 部分：个人档案管理的 RESTful 路由层（6 个端点）。
PROF-03 部分：事件记录管理的 RESTful 路由层（4 个端点，挂载于档案子路径）。

- GET  /api/v1/profiles            — 档案列表（分页）
- POST /api/v1/profiles            — 创建档案
- GET  /api/v1/profiles/me/default — 获取默认档案（须在 /{profile_id} 前注册）
- GET  /api/v1/profiles/{profile_id}       — 档案详情
- PUT  /api/v1/profiles/{profile_id}       — 更新档案
- DELETE /api/v1/profiles/{profile_id}     — 删除档案
- POST   /api/v1/profiles/{profile_id}/events          — 创建事件
- GET    /api/v1/profiles/{profile_id}/events          — 查询事件列表
- PUT    /api/v1/profiles/{profile_id}/events/{event_id}  — 更新事件
- DELETE /api/v1/profiles/{profile_id}/events/{event_id}  — 删除事件

路由设计原则：
- 路由层仅处理请求解析、校验分发与响应封装
- 所有业务逻辑委托给 ProfileService
- 角色校验由 require_role() Depends 自动完成
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth_dependencies import get_db_session
from app.services.profile_service import ProfileService
from py_auth.dependencies import get_current_user
from py_auth.rbac import require_role
from py_config.exceptions import (
    EventLimitExceededError,
    ForbiddenAccess,
    ProfileConflictError,
    ProfileLimitExceededError,
)
from py_schemas.auth import UserRole
from py_schemas.profiles import (
    EventCreate,
    EventResponse,
    EventUpdate,
    ProfileCreate,
    ProfileResponse,
    ProfileUpdate,
)

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])

# Service 实例（无状态，可复用）
_profile_service = ProfileService()


def _extract_caregiver_id(current_user: dict) -> UUID:
    """从 JWT payload 中提取家属用户 UUID。

    Args:
        current_user: get_current_user 返回的 JWT payload 字典。

    Returns:
        UUID: 家属用户标识。

    Raises:
        HTTPException(401): user_id 不存在或格式无效。
    """
    user_id_str: str = current_user.get("sub", current_user.get("user_id", ""))
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无法从令牌中解析用户标识",
        )
    try:
        return UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户标识格式无效",
        )


def _handle_service_error(exc: Exception) -> None:
    """将 Service 层异常转换为 HTTP 异常。

    Args:
        exc: Service 层抛出的异常。

    Raises:
        HTTPException: 转换后的 HTTP 异常。
    """
    if isinstance(exc, ForbiddenAccess):
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        )
    if isinstance(exc, ProfileLimitExceededError):
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "detail": exc.detail,
                "error_code": exc.error_code,
                "current_count": exc.current_count,
                "max_allowed": exc.max_allowed,
            },
        )
    if isinstance(exc, EventLimitExceededError):
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "detail": exc.detail,
                "error_code": exc.error_code,
                "current_count": exc.current_count,
                "max_allowed": exc.max_allowed,
            },
        )
    if isinstance(exc, ProfileConflictError):
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "detail": exc.detail,
                "error_code": exc.error_code,
            },
        )
    # 422 — 业务校验失败（如追溯期超限、字段值不合法但非 Pydantic 校验覆盖）
    if "超出可追溯范围" in str(exc) or "超出" in str(exc):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    # 未知异常或 404
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND
        if "不存在" in str(exc)
        else status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=str(exc) if "不存在" in str(exc) else "服务器内部错误",
    )


# ===========================================================================
# 注意：/me/default 路由必须在 /{profile_id} 之前注册，
# 否则 "me" 会被 FastAPI 捕获为 profile_id 路径参数。
# ===========================================================================


@router.get(
    "/me/default",
    status_code=status.HTTP_200_OK,
    summary="获取默认档案",
    description=(
        "获取当前家属账号下的默认档案。"
        "用于应急咨询等需要默认关联的场景。"
        "冷启动状态下（无档案）返回 404。"
    ),
    response_model=ProfileResponse,
    responses={
        200: {"description": "成功返回默认档案详情"},
        404: {"description": "账号下无档案（冷启动状态）"},
    },
)
async def get_default_profile(
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role(exact_roles=[UserRole.FAMILY])),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    """获取当前账号默认档案端点。

    Args:
        current_user: 当前用户 JWT payload。
        session: 异步数据库会话。

    Returns:
        ProfileResponse: 默认档案完整详情。
    """
    caregiver_id = _extract_caregiver_id(current_user)
    try:
        return await _profile_service.get_default_profile(
            caregiver_id=caregiver_id,
            session=session,
        )
    except Exception as exc:
        _handle_service_error(exc)
        raise  # unreachable


# ===========================================================================
# 档案列表（分页）
# ===========================================================================


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    summary="获取档案列表",
    description=(
        "获取当前家属账号下所有档案的分页列表。"
        "每个条目为 ProfileListItem 精简版。"
    ),
    responses={
        200: {"description": "成功返回分页档案列表"},
        422: {"description": "查询参数格式错误"},
    },
)
async def list_profiles(
    page: int = 1,
    page_size: int = 10,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role(exact_roles=[UserRole.FAMILY])),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """获取档案列表端点。

    Args:
        page: 页码（从 1 开始）。
        page_size: 每页条数。
        current_user: 当前用户 JWT payload。
        session: 异步数据库会话。

    Returns:
        dict: 分页列表。
    """
    caregiver_id = _extract_caregiver_id(current_user)
    return await _profile_service.list_profiles(
        caregiver_id=caregiver_id,
        page=page,
        page_size=page_size,
        session=session,
    )


# ===========================================================================
# 创建档案
# ===========================================================================


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="创建个人档案",
    description=(
        "为当前家属创建新患者档案。"
        "必填字段为 birth_date、diagnosis_type、primary_behavior 共 3 项。"
        "若为第一份档案，自动设为默认档案。"
    ),
    response_model=ProfileResponse,
    responses={
        201: {"description": "档案创建成功"},
        409: {"description": "档案数量已达上限或并发冲突"},
        422: {"description": "请求体校验失败"},
    },
)
async def create_profile(
    input_data: ProfileCreate,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role(exact_roles=[UserRole.FAMILY])),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    """创建个人档案端点。

    Args:
        input_data: 档案创建请求体（Pydantic 自动校验）。
        current_user: 当前用户 JWT payload。
        session: 异步数据库会话。

    Returns:
        ProfileResponse: 创建成功的档案完整数据。
    """
    caregiver_id = _extract_caregiver_id(current_user)
    try:
        return await _profile_service.create_profile(
            caregiver_id=caregiver_id,
            input_data=input_data,
            session=session,
        )
    except Exception as exc:
        _handle_service_error(exc)
        raise  # unreachable


# ===========================================================================
# 档案详情
# ===========================================================================


@router.get(
    "/{profile_id}",
    status_code=status.HTTP_200_OK,
    summary="获取档案详情",
    description="获取指定档案的完整详情。需通过 PrivacyGuard 权限校验。",
    response_model=ProfileResponse,
    responses={
        200: {"description": "成功返回档案详情"},
        403: {"description": "无权限访问此档案"},
        404: {"description": "档案不存在"},
    },
)
async def get_profile(
    profile_id: UUID,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role(exact_roles=[UserRole.FAMILY])),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    """获取档案详情端点。

    Args:
        profile_id: 目标档案 UUID（路径参数）。
        current_user: 当前用户 JWT payload。
        session: 异步数据库会话。

    Returns:
        ProfileResponse: 档案完整详情。
    """
    caregiver_id = _extract_caregiver_id(current_user)
    try:
        return await _profile_service.get_profile(
            caregiver_id=caregiver_id,
            profile_id=profile_id,
            session=session,
        )
    except Exception as exc:
        _handle_service_error(exc)
        raise  # unreachable


# ===========================================================================
# 更新档案
# ===========================================================================


@router.put(
    "/{profile_id}",
    status_code=status.HTTP_200_OK,
    summary="更新个人档案",
    description=(
        "更新已有档案的部分字段。所有字段均为可选（partial update）。"
        "使用乐观锁防止并发冲突。"
    ),
    response_model=ProfileResponse,
    responses={
        200: {"description": "档案更新成功"},
        403: {"description": "无权限更新此档案"},
        409: {"description": "乐观锁冲突，数据已被其他设备修改"},
        422: {"description": "请求体校验失败"},
    },
)
async def update_profile(
    profile_id: UUID,
    input_data: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role(exact_roles=[UserRole.FAMILY])),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    """更新档案端点。

    Args:
        profile_id: 目标档案 UUID（路径参数）。
        input_data: 更新字段请求体（Pydantic 自动校验）。
        current_user: 当前用户 JWT payload。
        session: 异步数据库会话。

    Returns:
        ProfileResponse: 更新后的档案完整数据。
    """
    caregiver_id = _extract_caregiver_id(current_user)
    try:
        return await _profile_service.update_profile(
            caregiver_id=caregiver_id,
            profile_id=profile_id,
            input_data=input_data,
            session=session,
        )
    except Exception as exc:
        _handle_service_error(exc)
        raise  # unreachable


# ===========================================================================
# 删除档案
# ===========================================================================


@router.delete(
    "/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除档案",
    description=(
        "删除指定档案及关联数据。硬删除不可恢复。"
        "若删除的是默认档案，自动提升另一档案为默认。"
    ),
    responses={
        204: {"description": "档案删除成功（无响应体）"},
        403: {"description": "无权限删除此档案"},
        404: {"description": "档案不存在"},
    },
)
async def delete_profile(
    profile_id: UUID,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role(exact_roles=[UserRole.FAMILY])),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """删除档案端点。

    Args:
        profile_id: 目标档案 UUID（路径参数）。
        current_user: 当前用户 JWT payload。
        session: 异步数据库会话。

    Returns:
        None（HTTP 204 No Content）。
    """
    caregiver_id = _extract_caregiver_id(current_user)
    try:
        await _profile_service.delete_profile(
            caregiver_id=caregiver_id,
            profile_id=profile_id,
            session=session,
        )
    except Exception as exc:
        _handle_service_error(exc)
        raise  # unreachable


# ===========================================================================
# PROF-03 — 事件记录管理端点
# ===========================================================================


@router.post(
    "/{profile_id}/events",
    status_code=status.HTTP_201_CREATED,
    summary="创建事件记录",
    description=(
        "为指定档案创建一条新的事件记录。"
        "必填字段为 event_time、behavior_type、severity_level 及 4 个描述文本字段。"
        "事件时间需在 30 天追溯期内，档案下事件数上限 500 条。"
    ),
    response_model=EventResponse,
    responses={
        201: {"description": "事件创建成功"},
        403: {"description": "角色非家属 / 无权操作本档案"},
        404: {"description": "目标档案不存在"},
        409: {"description": "事件记录数已达 500 条上限"},
        422: {"description": "必填字段缺失 / 枚举值非法 / 事件时间超追溯期"},
        500: {"description": "数据库操作失败"},
    },
)
async def create_event(
    profile_id: UUID,
    data: EventCreate,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role(exact_roles=[UserRole.FAMILY])),
    session: AsyncSession = Depends(get_db_session),
) -> EventResponse:
    """创建事件记录端点。

    Args:
        profile_id: 目标档案标识（URL 路径参数）。
        data: 事件创建请求体（EventCreate，Pydantic 自动校验）。
        current_user: 当前用户 JWT payload。
        session: 异步数据库会话。

    Returns:
        EventResponse: 创建成功的事件完整详情（16 字段）。
    """
    caregiver_id = _extract_caregiver_id(current_user)
    try:
        return await _profile_service.create_event(
            profile_id=profile_id,
            user_id=caregiver_id,
            data=data,
            session=session,
        )
    except Exception as exc:
        _handle_service_error(exc)
        raise  # unreachable


@router.get(
    "/{profile_id}/events",
    status_code=status.HTTP_200_OK,
    summary="查询事件记录列表",
    description=(
        "查询指定档案下的事件记录列表，支持按行为类型筛选和分页。"
        "按 event_time 降序排列，默认每页 20 条。"
    ),
    responses={
        200: {"description": "成功返回分页事件列表"},
        403: {"description": "角色非家属 / 无权访问本档案"},
        404: {"description": "目标档案不存在"},
        422: {"description": "查询参数格式错误"},
    },
)
async def list_events(
    profile_id: UUID,
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(
        default=20, ge=1, le=100, description="每页条数，默认 20，最大 100"
    ),
    behavior_type: str | None = Query(
        default=None, description="可选行为类型筛选"
    ),
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role(exact_roles=[UserRole.FAMILY])),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """查询事件列表端点。

    Args:
        profile_id: 目标档案标识。
        page: 页码（从 1 开始）。
        page_size: 每页条数（默认 20，最大 100）。
        behavior_type: 可选行为类型筛选。
        current_user: 当前用户 JWT payload。
        session: 异步数据库会话。

    Returns:
        dict: 分页列表，含 items、total、page、page_size、total_pages。
    """
    caregiver_id = _extract_caregiver_id(current_user)
    try:
        return await _profile_service.list_events(
            profile_id=profile_id,
            user_id=caregiver_id,
            page=page,
            page_size=page_size,
            behavior_type=behavior_type,
            session=session,
        )
    except Exception as exc:
        _handle_service_error(exc)
        raise  # unreachable


@router.put(
    "/{profile_id}/events/{event_id}",
    status_code=status.HTTP_200_OK,
    summary="更新事件记录",
    description=(
        "更新指定事件的字段（Merge Patch 语义）。"
        "仅更新请求体中非 null 的字段，未传字段保持原值不变。"
        "仅事件创建者本人可执行更新。"
    ),
    response_model=EventResponse,
    responses={
        200: {"description": "事件更新成功"},
        403: {"description": "角色非家属 / 无权操作 / 非事件创建者"},
        404: {"description": "事件不存在"},
        422: {"description": "更新后的事件时间超 30 天追溯期"},
        500: {"description": "数据库操作失败"},
    },
)
async def update_event(
    profile_id: UUID,
    event_id: UUID,
    data: EventUpdate,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role(exact_roles=[UserRole.FAMILY])),
    session: AsyncSession = Depends(get_db_session),
) -> EventResponse:
    """更新事件记录端点。

    Args:
        profile_id: 目标档案标识。
        event_id: 目标事件标识。
        data: 事件更新请求体（所有字段可选，Pydantic 自动校验）。
        current_user: 当前用户 JWT payload。
        session: 异步数据库会话。

    Returns:
        EventResponse: 更新后的事件完整详情。
    """
    caregiver_id = _extract_caregiver_id(current_user)
    try:
        return await _profile_service.update_event(
            profile_id=profile_id,
            event_id=event_id,
            user_id=caregiver_id,
            data=data,
            session=session,
        )
    except Exception as exc:
        _handle_service_error(exc)
        raise  # unreachable


@router.delete(
    "/{profile_id}/events/{event_id}",
    status_code=status.HTTP_200_OK,
    summary="删除事件记录",
    description=(
        "硬删除指定事件记录。删除后不可恢复。"
        "仅事件创建者本人可执行删除。"
    ),
    responses={
        200: {"description": "事件删除成功"},
        403: {"description": "角色非家属 / 无权操作 / 非事件创建者"},
        404: {"description": "事件不存在"},
        500: {"description": "数据库操作失败"},
    },
)
async def delete_event(
    profile_id: UUID,
    event_id: UUID,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role(exact_roles=[UserRole.FAMILY])),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """删除事件记录端点。

    Args:
        profile_id: 目标档案标识。
        event_id: 目标事件标识。
        current_user: 当前用户 JWT payload。
        session: 异步数据库会话。

    Returns:
        dict: {"detail": "事件已删除"}
    """
    caregiver_id = _extract_caregiver_id(current_user)
    try:
        await _profile_service.delete_event(
            profile_id=profile_id,
            event_id=event_id,
            user_id=caregiver_id,
            session=session,
        )
        return {"detail": "事件已删除"}
    except Exception as exc:
        _handle_service_error(exc)
        raise  # unreachable


__all__ = ["router"]
