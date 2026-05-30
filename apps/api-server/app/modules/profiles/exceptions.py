# @contract
"""profiles 域统一异常层次。

模块: app.modules.profiles.exceptions
职责: 定义档案域（PROF-01/03/05）所有业务异常的统一层次结构。
      所有异常继承自 ProfileDomainError，上层可通过 `except ProfileDomainError`
      统一捕获本域的所有错误。每个异常携带诊断字段，供路由层做 HTTP 状态码映射。

数据来源:
  - 无外部数据依赖（纯异常定义）

边界:
  - 依赖: Python 标准库
  - 被依赖: profiles_contract.py, events_contract.py, experts_contract.py, routes.py

禁止行为:
  - 禁止在异常类中引用 FastAPI HTTPException（保持与传输层解耦）
  - 禁止异常类包含循环导入（不 import 任何项目内部模块）
"""

from __future__ import annotations

from typing import Any


class ProfileDomainError(Exception):
    """档案域统一异常基类。

    触发条件: 档案域（PROF-01/03/05）中任何可恢复的业务异常。
    诊断字段:
      - message: 人类可读的错误描述
      - code: 机器可读的错误码（用于 HTTP 状态码映射）
      - detail: 可选的错误详情字典
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "PROFILE_ERROR",
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.message: str = message
        self.code: str = code
        self.detail: dict[str, Any] | None = detail
        super().__init__(self.message)


# ============================================================================
# PROF-01 档案相关异常
# ============================================================================


class ProfileNotFoundError(ProfileDomainError):
    """档案不存在或无权访问。

    触发条件: 按 profile_id + caregiver_id 联合查询无结果。
    安全约束: 不区分「不存在」和「无权访问」（防枚举攻击）。
    映射: HTTP 404
    """

    def __init__(self, profile_id: str, actual_reason: str = "not_found") -> None:
        super().__init__(
            "档案不存在",
            code="PROFILE_NOT_FOUND",
            detail={"profile_id": profile_id, "actual_reason": actual_reason},
        )


class ProfileLimitExceededError(ProfileDomainError):
    """档案数量超限。

    触发条件: 家属账号下活跃档案数已达上限（默认 5 个）。
    映射: HTTP 409
    """

    def __init__(self, current_count: int, max_count: int) -> None:
        super().__init__(
            f"档案数量已达上限（{max_count} 个），请清理后重试",
            code="PROFILE_LIMIT_EXCEEDED",
            detail={"current_count": current_count, "max_count": max_count},
        )


class ProfileConflictError(ProfileDomainError):
    """档案并发修改冲突。

    触发条件: 乐观锁 updated_at 不匹配，并发修改同一档案。
    映射: HTTP 409
    """

    def __init__(self, profile_id: str) -> None:
        super().__init__(
            "档案已被其他操作修改，请刷新后重试",
            code="PROFILE_CONFLICT",
            detail={"profile_id": profile_id},
        )


# ============================================================================
# PROF-03 事件相关异常
# ============================================================================


class EventNotFoundError(ProfileDomainError):
    """事件记录不存在。

    触发条件: 按 event_id + profile_id 联合查询无结果。
    映射: HTTP 404
    """

    def __init__(self, event_id: str, profile_id: str) -> None:
        super().__init__(
            "事件不存在",
            code="EVENT_NOT_FOUND",
            detail={"event_id": event_id, "profile_id": profile_id},
        )


class EventTimeOutOfRangeError(ProfileDomainError):
    """事件时间超出追溯期。

    触发条件: 事件发生时间早于当前时间 30 天。
    映射: HTTP 400
    """

    def __init__(self, event_time: str, cutoff_days: int = 30) -> None:
        super().__init__(
            f"仅支持补录最近 {cutoff_days} 天内的事件",
            code="EVENT_TIME_OUT_OF_RANGE",
            detail={"event_time": event_time, "cutoff_days": cutoff_days},
        )


# ============================================================================
# PROF-05 专家关联异常
# ============================================================================


class ExpertLinkNotFoundError(ProfileDomainError):
    """专家关联不存在。

    触发条件: 按 link_id + profile_id 联合查询无结果。
    映射: HTTP 404
    """

    def __init__(self, link_id: str, profile_id: str) -> None:
        super().__init__(
            "关联不存在",
            code="LINK_NOT_FOUND",
            detail={"link_id": link_id, "profile_id": profile_id},
        )


class ExpertLinkConflictError(ProfileDomainError):
    """专家关联乐观锁冲突。

    触发条件: 解除关联时 version 不匹配（并发修改）。
    映射: HTTP 409
    """

    def __init__(self, link_id: str) -> None:
        super().__init__(
            "关联已被其他操作修改，请刷新后重试",
            code="LINK_CONFLICT",
            detail={"link_id": link_id},
        )


__all__ = [
    "ProfileDomainError",
    "ProfileNotFoundError",
    "ProfileLimitExceededError",
    "ProfileConflictError",
    "EventNotFoundError",
    "EventTimeOutOfRangeError",
    "ExpertLinkNotFoundError",
    "ExpertLinkConflictError",
]
