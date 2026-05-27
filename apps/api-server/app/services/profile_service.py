"""PROF-05 档案隐私控制 — Service 层编排。

本模块是档案操作业务逻辑的唯一编排入口，实现双层鉴权架构的第二层——
每个 Service 方法在执行业务逻辑前调用 PrivacyGuard.check_access()
进行档案级细粒度权限校验。

允许时继续执行数据库操作并返回业务结果；
拒绝时抛出 ForbiddenAccess（全局异常处理器捕获后返回 HTTP 403）。

下游模块（PROF-01/PROF-03/PROF-04）在实现具体业务逻辑时，
应在此骨架方法中填充实际的数据库 CRUD 操作。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from py_auth.rbac import PrivacyGuard
from py_config.exceptions import ForbiddenAccess
from py_logger import logger
from py_schemas.profiles import AccessDecision, AccessOperation, AccessRequest

_logger = logging.getLogger(__name__)


# ===========================================================================
# 档案查看
# ===========================================================================


async def view_profile(
    target_profile_id: UUID,
    requester_id: UUID,
    requester_role: str,
    db_session: AsyncSession,
) -> dict[str, Any]:
    """查看个人档案。

    流程：
    1. 构造 AccessRequest 并调用 PrivacyGuard.check_access()
    2. 根据裁决结果：允许则查询并返回档案数据；拒绝则抛出 ForbiddenAccess

    Args:
        target_profile_id: 目标个人档案 UUID。
        requester_id: 请求发起人用户 UUID。
        requester_role: 请求发起人角色（family/teacher/expert/admin/maintainer）。
        db_session: 异步数据库会话。

    Returns:
        档案数据字典（字段集取决于 visible_scope）。

    Raises:
        ForbiddenAccess: 拒绝访问时抛出。
    """
    request = AccessRequest(
        operation=AccessOperation.VIEW,
        target_profile_id=target_profile_id,
        requester_id=requester_id,
        requester_role=requester_role,
    )

    decision: AccessDecision = await PrivacyGuard.check_access(
        request=request, db_session=db_session,
    )

    if not decision.allowed:
        _log_unauthorized(request)
        raise ForbiddenAccess(detail="数据不存在")

    # ---------- 允许：查询并返回档案数据 ----------
    # TODO: PROF-01 填充实际的档案查询逻辑
    # visible_scope 决定返回字段集：
    # - all_fields → 返回完整档案数据
    # - metadata_only → 仅返回聚合统计信息
    return {
        "profile_id": str(target_profile_id),
        "visible_scope": decision.visible_scope.value,
        "message": "档案数据将在 PROF-01 实现后返回完整内容",
    }


# ===========================================================================
# 事件记录操作
# ===========================================================================


async def create_event(
    target_profile_id: UUID,
    requester_id: UUID,
    requester_role: str,
    db_session: AsyncSession,
    event_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """新增事件记录。

    Args:
        target_profile_id: 目标个人档案 UUID。
        requester_id: 请求发起人用户 UUID。
        requester_role: 请求发起人角色。
        db_session: 异步数据库会话。
        event_data: 事件数据（由 PROF-03 定义具体字段）。

    Returns:
        创建成功的事件记录概要。

    Raises:
        ForbiddenAccess: 拒绝访问时抛出。
    """
    request = AccessRequest(
        operation=AccessOperation.CREATE,
        target_profile_id=target_profile_id,
        requester_id=requester_id,
        requester_role=requester_role,
    )

    decision: AccessDecision = await PrivacyGuard.check_access(
        request=request, db_session=db_session,
    )

    if not decision.allowed:
        _log_unauthorized(request)
        raise ForbiddenAccess(detail="数据不存在")

    # ---------- 允许：创建事件记录 ----------
    # TODO: PROF-03 填充实际的事件创建逻辑
    return {
        "profile_id": str(target_profile_id),
        "operation": "create_event",
        "status": "permission_granted",
        "message": "事件创建逻辑将在 PROF-03 实现后填充",
    }


async def update_event(
    target_profile_id: UUID,
    requester_id: UUID,
    requester_role: str,
    db_session: AsyncSession,
    event_id: str | None = None,
    event_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """修改事件记录。

    Args:
        target_profile_id: 目标个人档案 UUID。
        requester_id: 请求发起人用户 UUID。
        requester_role: 请求发起人角色。
        db_session: 异步数据库会话。
        event_id: 事件记录 UUID（由 PROF-03 定义）。
        event_data: 更新数据（由 PROF-03 定义具体字段）。

    Returns:
        更新成功的事件记录概要。

    Raises:
        ForbiddenAccess: 拒绝访问时抛出。
    """
    request = AccessRequest(
        operation=AccessOperation.UPDATE,
        target_profile_id=target_profile_id,
        requester_id=requester_id,
        requester_role=requester_role,
    )

    decision: AccessDecision = await PrivacyGuard.check_access(
        request=request, db_session=db_session,
    )

    if not decision.allowed:
        _log_unauthorized(request)
        raise ForbiddenAccess(detail="数据不存在")

    # ---------- 允许：更新事件记录 ----------
    # TODO: PROF-03 填充实际的事件更新逻辑
    return {
        "profile_id": str(target_profile_id),
        "event_id": event_id or "unknown",
        "operation": "update_event",
        "status": "permission_granted",
    }


async def delete_event(
    target_profile_id: UUID,
    requester_id: UUID,
    requester_role: str,
    db_session: AsyncSession,
    event_id: str | None = None,
) -> dict[str, Any]:
    """删除事件记录。

    Args:
        target_profile_id: 目标个人档案 UUID。
        requester_id: 请求发起人用户 UUID。
        requester_role: 请求发起人角色。
        db_session: 异步数据库会话。
        event_id: 事件记录 UUID（由 PROF-03 定义）。

    Returns:
        删除成功状态。

    Raises:
        ForbiddenAccess: 拒绝访问时抛出。
    """
    request = AccessRequest(
        operation=AccessOperation.DELETE,
        target_profile_id=target_profile_id,
        requester_id=requester_id,
        requester_role=requester_role,
    )

    decision: AccessDecision = await PrivacyGuard.check_access(
        request=request, db_session=db_session,
    )

    if not decision.allowed:
        _log_unauthorized(request)
        raise ForbiddenAccess(detail="数据不存在")

    # ---------- 允许：删除事件记录 ----------
    # TODO: PROF-03 填充实际的事件删除逻辑
    return {
        "profile_id": str(target_profile_id),
        "event_id": event_id or "unknown",
        "operation": "delete_event",
        "status": "permission_granted",
    }


# ===========================================================================
# 专业评估补充
# ===========================================================================


async def supplement_assessment(
    target_profile_id: UUID,
    requester_id: UUID,
    requester_role: str,
    db_session: AsyncSession,
    assessment_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """补充专业评估。

    Args:
        target_profile_id: 目标个人档案 UUID。
        requester_id: 请求发起人用户 UUID。
        requester_role: 请求发起人角色（teacher/expert）。
        db_session: 异步数据库会话。
        assessment_data: 评估数据（由 PROF-04 定义具体字段）。

    Returns:
        专业评估提交成功状态。

    Raises:
        ForbiddenAccess: 拒绝访问时抛出。
    """
    request = AccessRequest(
        operation=AccessOperation.SUPPLEMENT_ASSESSMENT,
        target_profile_id=target_profile_id,
        requester_id=requester_id,
        requester_role=requester_role,
    )

    decision: AccessDecision = await PrivacyGuard.check_access(
        request=request, db_session=db_session,
    )

    if not decision.allowed:
        _log_unauthorized(request)
        raise ForbiddenAccess(detail="数据不存在")

    # ---------- 允许：提交专业评估 ----------
    # TODO: PROF-04 填充实际的评估写入逻辑
    return {
        "profile_id": str(target_profile_id),
        "operation": "supplement_assessment",
        "status": "permission_granted",
        "message": "专业评估写入逻辑将在 PROF-04 实现后填充",
    }


# ===========================================================================
# 解除老师关联
# ===========================================================================


async def unlink_teacher(
    target_profile_id: UUID,
    requester_id: UUID,
    requester_role: str,
    db_session: AsyncSession,
    link_id: UUID | None = None,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """解除老师与档案的关联关系。

    此操作仅限家属角色使用，会在同一事务中执行两步原子操作：
    1. 更新 teacher_links.unlinked_at = NOW()
    2. 批量设置 professional_notes.visible_after_unlink = false

    两步在同一事务中执行，要么全部成功要么全部回滚。

    Args:
        target_profile_id: 目标个人档案 UUID。
        requester_id: 请求发起人（家属）用户 UUID。
        requester_role: 请求发起人角色。
        db_session: 异步数据库会话。
        link_id: 待解除的关联关系 link_id。
        expected_version: 乐观锁期望版本号。

    Returns:
        解除关联操作结果。

    Raises:
        ForbiddenAccess: 拒绝访问时抛出。
    """
    request = AccessRequest(
        operation=AccessOperation.UNLINK,
        target_profile_id=target_profile_id,
        requester_id=requester_id,
        requester_role=requester_role,
    )

    decision: AccessDecision = await PrivacyGuard.check_access(
        request=request, db_session=db_session,
    )

    if not decision.allowed:
        _log_unauthorized(request)
        raise ForbiddenAccess(detail="数据不存在")

    # ---------- 允许：执行解除关联 ----------
    # TODO: PROF-01 填充实际的解除关联逻辑（含事务原子性）
    # 步骤 1：更新 teacher_links.unlinked_at
    # 步骤 2：批量设置 professional_notes.visible_after_unlink = false
    return {
        "profile_id": str(target_profile_id),
        "link_id": str(link_id) if link_id else "unknown",
        "operation": "unlink_teacher",
        "status": "permission_granted",
        "message": "解除关联逻辑将在 PROF-01 实现后填充",
    }


# ===========================================================================
# 内部辅助函数
# ===========================================================================


def _log_unauthorized(request: AccessRequest) -> None:
    """记录越权访问审计日志。

    日志输出包含完整的权限上下文（请求人、目标档案、操作类型），
    供事后审计追踪使用。日志写入失败不影响主流程。

    Args:
        request: 被拒绝的访问请求。
    """
    try:
        logger.info(
            "api-server",
            "unauthorized_access",
            op_type="UNAUTHORIZED_ACCESS",
            extra={
                "event_type": "unauthorized_access",
                "requester_id": str(request.requester_id),
                "target_profile_id": str(request.target_profile_id),
                "requester_role": request.requester_role,
                "operation": request.operation.value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception:
        _logger.warning(
            "unauthorized_access_log_failed",
            extra={
                "requester_id": str(request.requester_id),
                "target_profile_id": str(request.target_profile_id),
            },
        )


__all__ = [
    "view_profile",
    "create_event",
    "update_event",
    "delete_event",
    "supplement_assessment",
    "unlink_teacher",
]
