"""PROF-05 档案隐私控制 — FastAPI 路由注册。

档案相关 API 路由，实现双层鉴权架构的第一层（路由级角色校验）。
所有涉及档案操作的路由通过 require_role() Depends 进行角色存在性检查，
再调用 profile_service 对应方法进行第二层档案级权限校验。

路由设计原则（接口层极简化）：
- 路由层仅处理请求解析、校验分发与响应封装
- 所有业务逻辑（含 PrivacyGuard 调用）委托给 profile_service
- 角色校验由 require_role() Depends 自动完成
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth_dependencies import get_db_session
from app.services import profile_service
from py_auth.dependencies import get_current_user
from py_auth.rbac import require_role

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])


# ===========================================================================
# 档案查看
# ===========================================================================


@router.get(
    "/{profile_id}",
    status_code=status.HTTP_200_OK,
    summary="查看个人档案",
    description=(
        "查看指定个人档案的完整内容或元数据（取决于角色权限）。"
        "路由层 require_role() 校验角色存在性，"
        "Service 层 PrivacyGuard 执行档案级细粒度权限判定。"
    ),
    responses={
        200: {"description": "成功返回档案数据（字段集取决于角色权限）"},
        403: {"description": "当前角色无权访问此档案"},
        422: {"description": "路径参数格式错误"},
    },
)
async def get_profile(
    profile_id: UUID,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role()),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """查看个人档案端点。

    Args:
        profile_id: 目标个人档案 UUID（路径参数）。
        current_user: 当前用户 JWT payload（由 get_current_user 注入）。
        session: 数据库异步会话（请求结束时自动关闭）。

    Returns:
        dict: 档案数据（字段集取决于 PrivacyGuard 裁定的 visible_scope）。
    """
    # 从 JWT payload 中提取用户信息
    requester_id_str: str = current_user.get("sub", current_user.get("user_id", ""))
    roles: list[str] = current_user.get("roles", [])
    requester_role: str = roles[0] if roles else ""

    return await profile_service.view_profile(
        target_profile_id=profile_id,
        requester_id=UUID(requester_id_str) if requester_id_str else UUID(int=0),
        requester_role=requester_role,
        db_session=session,
    )


# ===========================================================================
# 事件记录
# ===========================================================================


@router.post(
    "/{profile_id}/events",
    status_code=status.HTTP_201_CREATED,
    summary="新增事件记录",
    description="为目标档案新增一条事件记录。仅家属角色可执行此操作。",
    responses={
        201: {"description": "事件记录创建成功"},
        403: {"description": "当前角色无权新增事件记录"},
    },
)
async def create_event(
    profile_id: UUID,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role()),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """新增事件记录端点。

    Args:
        profile_id: 目标个人档案 UUID。
        current_user: 当前用户 JWT payload。
        session: 数据库异步会话。

    Returns:
        dict: 事件创建结果。
    """
    requester_id_str: str = current_user.get("sub", current_user.get("user_id", ""))
    roles: list[str] = current_user.get("roles", [])
    requester_role: str = roles[0] if roles else ""

    return await profile_service.create_event(
        target_profile_id=profile_id,
        requester_id=UUID(requester_id_str) if requester_id_str else UUID(int=0),
        requester_role=requester_role,
        db_session=session,
    )


@router.put(
    "/{profile_id}/events/{event_id}",
    status_code=status.HTTP_200_OK,
    summary="修改事件记录",
    description="修改指定事件记录的内容。仅家属角色可执行此操作。",
    responses={
        200: {"description": "事件记录修改成功"},
        403: {"description": "当前角色无权修改事件记录"},
    },
)
async def update_event(
    profile_id: UUID,
    event_id: str,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role()),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """修改事件记录端点。

    Args:
        profile_id: 目标个人档案 UUID。
        event_id: 事件记录标识。
        current_user: 当前用户 JWT payload。
        session: 数据库异步会话。

    Returns:
        dict: 事件更新结果。
    """
    requester_id_str: str = current_user.get("sub", current_user.get("user_id", ""))
    roles: list[str] = current_user.get("roles", [])
    requester_role: str = roles[0] if roles else ""

    return await profile_service.update_event(
        target_profile_id=profile_id,
        requester_id=UUID(requester_id_str) if requester_id_str else UUID(int=0),
        requester_role=requester_role,
        db_session=session,
        event_id=event_id,
    )


@router.delete(
    "/{profile_id}/events/{event_id}",
    status_code=status.HTTP_200_OK,
    summary="删除事件记录",
    description="删除指定事件记录。仅家属角色可执行此操作。",
    responses={
        200: {"description": "事件记录删除成功"},
        403: {"description": "当前角色无权删除事件记录"},
    },
)
async def delete_event(
    profile_id: UUID,
    event_id: str,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role()),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """删除事件记录端点。

    Args:
        profile_id: 目标个人档案 UUID。
        event_id: 事件记录标识。
        current_user: 当前用户 JWT payload。
        session: 数据库异步会话。

    Returns:
        dict: 事件删除结果。
    """
    requester_id_str: str = current_user.get("sub", current_user.get("user_id", ""))
    roles: list[str] = current_user.get("roles", [])
    requester_role: str = roles[0] if roles else ""

    return await profile_service.delete_event(
        target_profile_id=profile_id,
        requester_id=UUID(requester_id_str) if requester_id_str else UUID(int=0),
        requester_role=requester_role,
        db_session=session,
        event_id=event_id,
    )


# ===========================================================================
# 专业评估补充
# ===========================================================================


@router.post(
    "/{profile_id}/assessments",
    status_code=status.HTTP_201_CREATED,
    summary="补充专业评估",
    description="为指定档案补充专业评估记录。仅关联老师/专家可执行此操作。",
    responses={
        201: {"description": "专业评估提交成功"},
        403: {"description": "当前角色无权补充专业评估"},
    },
)
async def supplement_assessment(
    profile_id: UUID,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role()),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """补充专业评估端点。

    Args:
        profile_id: 目标个人档案 UUID。
        current_user: 当前用户 JWT payload。
        session: 数据库异步会话。

    Returns:
        dict: 评估提交结果。
    """
    requester_id_str: str = current_user.get("sub", current_user.get("user_id", ""))
    roles: list[str] = current_user.get("roles", [])
    requester_role: str = roles[0] if roles else ""

    return await profile_service.supplement_assessment(
        target_profile_id=profile_id,
        requester_id=UUID(requester_id_str) if requester_id_str else UUID(int=0),
        requester_role=requester_role,
        db_session=session,
    )


# ===========================================================================
# 解除老师关联
# ===========================================================================


@router.post(
    "/{profile_id}/unlink",
    status_code=status.HTTP_200_OK,
    summary="解除老师关联",
    description="解除指定老师与目标档案的关联关系。仅家属角色可执行此操作。",
    responses={
        200: {"description": "关联关系解除成功"},
        403: {"description": "当前角色无权解除关联"},
    },
)
async def unlink_teacher(
    profile_id: UUID,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_role()),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """解除老师关联端点。

    Args:
        profile_id: 目标个人档案 UUID。
        current_user: 当前用户 JWT payload。
        session: 数据库异步会话。

    Returns:
        dict: 解除关联操作结果。
    """
    requester_id_str: str = current_user.get("sub", current_user.get("user_id", ""))
    roles: list[str] = current_user.get("roles", [])
    requester_role: str = roles[0] if roles else ""

    return await profile_service.unlink_teacher(
        target_profile_id=profile_id,
        requester_id=UUID(requester_id_str) if requester_id_str else UUID(int=0),
        requester_role=requester_role,
        db_session=session,
    )


__all__ = ["router"]
