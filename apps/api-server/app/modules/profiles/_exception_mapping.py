"""profiles 域异常 → HTTP 状态码映射。

模块: app.modules.profiles._exception_mapping
职责: 将业务异常（ProfileDomainError 子类）映射为 FastAPI HTTPException。
      路由层统一使用此模块完成异常转换，避免在每个端点上重复 try/except。
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.modules.profiles.exceptions import (
    EventNotFoundError,
    EventTimeOutOfRangeError,
    ExpertLinkConflictError,
    ExpertLinkNotFoundError,
    ProfileConflictError,
    ProfileDomainError,
    ProfileLimitExceededError,
    ProfileNotFoundError,
)

# 异常类型 → HTTP 状态码映射
_EXCEPTION_STATUS_MAP: dict[type[ProfileDomainError], int] = {
    ProfileNotFoundError: status.HTTP_404_NOT_FOUND,
    ProfileLimitExceededError: status.HTTP_409_CONFLICT,
    ProfileConflictError: status.HTTP_409_CONFLICT,
    EventNotFoundError: status.HTTP_404_NOT_FOUND,
    EventTimeOutOfRangeError: status.HTTP_400_BAD_REQUEST,
    ExpertLinkNotFoundError: status.HTTP_404_NOT_FOUND,
    ExpertLinkConflictError: status.HTTP_409_CONFLICT,
}


def map_domain_error(exc: ProfileDomainError) -> HTTPException:
    """将业务异常转换为对应的 HTTPException。

    Args:
        exc: ProfileDomainError 子类实例。

    Returns:
        HTTPException: 对应的 HTTP 异常，内含 status_code 和结构化 detail。
    """
    http_status = _EXCEPTION_STATUS_MAP.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    return HTTPException(
        status_code=http_status,
        detail={
            "code": exc.code,
            "message": exc.message,
            "detail": exc.detail,
        },
    )


__all__ = ["map_domain_error"]
