"""待处理写入记录：表、仓储与状态推进。

归属（2026-09-29 用户裁决）：`pending_write` 是 profile 与 memory 共用的事实表，
因此归 `core/`。依据是依赖白名单（见 docs/项目结构设计.md 第 7 节）：
`modules/*` 只能依赖 `core/*`、且模块之间不得互相 import——共用表若放在任一
业务模块里，另一个模块就用不上。

设计真源是 docs/技术设计/technical-details/写入路径.md：
形状见其第 3 节、投递与消费见第 4 节、幂等见第 5 节、失败语义见第 6 节。
本包只实现表与状态机；投递（Taskiq）在 `core/jobs`，业务消费在各自的模块
（`modules/memory` 等）。

不变量：「没写进去」不得被当作「写进去了」——只有 `state = done` 才算成功。
"""

from campfire.core.pending_write.models import (
    KIND_MEMORY_EPISODE,
    KIND_PROFILE_ITEM,
    KINDS,
    ORIGIN_AI_INFERENCE,
    ORIGIN_GUARDIAN_OBSERVATION,
    ORIGIN_SYSTEM_OBSERVATION,
    ORIGIN_USER_STATEMENT,
    ORIGINS,
    STATE_DEAD,
    STATE_DONE,
    STATE_FAILED,
    STATE_PENDING,
    STATE_PROCESSING,
    STATES,
    UNFINISHED_STATES,
    PendingWrite,
)
from campfire.core.pending_write.repository import (
    LEASE_SECONDS,
    MAX_ATTEMPTS,
    RECLAIM_MAX_LIMIT,
    SWEEP_MAX_LIMIT,
    InsufficientPayloadError,
    PendingWriteError,
    PendingWriteNotFoundError,
    enqueue,
    find_undelivered,
    mark_dead,
    mark_done,
    mark_retryable_failure,
    reclaim_expired_leases,
    take_for_processing,
)

__all__ = [
    # 表与词表
    "KINDS",
    "KIND_MEMORY_EPISODE",
    "KIND_PROFILE_ITEM",
    "ORIGINS",
    "ORIGIN_AI_INFERENCE",
    "ORIGIN_GUARDIAN_OBSERVATION",
    "ORIGIN_SYSTEM_OBSERVATION",
    "ORIGIN_USER_STATEMENT",
    "STATES",
    "STATE_DEAD",
    "STATE_DONE",
    "STATE_FAILED",
    "STATE_PENDING",
    "STATE_PROCESSING",
    "UNFINISHED_STATES",
    "PendingWrite",
    # 参数
    "LEASE_SECONDS",
    "MAX_ATTEMPTS",
    "RECLAIM_MAX_LIMIT",
    "SWEEP_MAX_LIMIT",
    # 异常
    "InsufficientPayloadError",
    "PendingWriteError",
    "PendingWriteNotFoundError",
    # 仓储
    "enqueue",
    "find_undelivered",
    "mark_dead",
    "mark_done",
    "mark_retryable_failure",
    "reclaim_expired_leases",
    "take_for_processing",
]
