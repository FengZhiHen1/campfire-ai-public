"""OBS-04 健康检查 — 模块级状态追踪。

维护两个模块级变量：
    - _last_overall_status: 最近一次检查的整体健康状态，用于状态变更防抖
    - _consecutive_failures: 连续失败计数器

两个变量仅存在于进程内存中（容器重启后归零），
在 asyncio 单线程事件循环中读写安全。
"""

from __future__ import annotations

from py_health.models import HealthStatus

# ---------------------------------------------------------------------------
# 模块级状态变量
# ---------------------------------------------------------------------------

_last_overall_status: HealthStatus | None = None
"""最近一次检查的整体健康状态。
仅在状态实际变化时写日志（防抖），同状态重复检查不记录。
初始值为 None，表示首次检查（必定触发日志记录）。
"""

_consecutive_failures: int = 0
"""连续失败计数器。
每次检查中任一组件失败 → +1；全部成功 → 归零。
计数器 ≥ 3 时影响 HTTP 状态码判定（即使整体状态为 degraded 也返回 503）。
独立于 Docker HEALTHCHECK 的失败计数（retries=3），形成双重安全网。
"""


# ---------------------------------------------------------------------------
# 访问器函数（对外接口）
# ---------------------------------------------------------------------------


def get_last_status() -> HealthStatus | None:
    """获取最近一次检查的整体健康状态。

    Returns:
        HealthStatus | None: 上次检查状态，None 表示尚无历史记录。
    """
    return _last_overall_status


def set_last_status(new_status: HealthStatus) -> None:
    """更新最近一次检查的整体健康状态。

    Args:
        new_status: 本次检查的整体健康状态。
    """
    global _last_overall_status
    _last_overall_status = new_status


def get_consecutive_failures() -> int:
    """获取当前连续失败计数。

    Returns:
        int: 连续失败次数（0 表示最近一次检查全部成功）。
    """
    return _consecutive_failures


def increment_failures() -> int:
    """递增连续失败计数器。

    Returns:
        int: 递增后的计数值。
    """
    global _consecutive_failures
    _consecutive_failures += 1
    return _consecutive_failures


def reset_failures() -> None:
    """归零连续失败计数器（全部组件恢复时调用）。"""
    global _consecutive_failures
    _consecutive_failures = 0
