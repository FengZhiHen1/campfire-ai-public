"""三组系统适配器（A 直接问答 / B 受控 RAG / C 生产 Agent）。

职责：对外只暴露共同形状与装配入口。

边界：各组的差异化实现各在自己模块里；本文件不实现任何一组。
参考：协议 01 第 4 节（对照组定义）、05 第 4 节（公平性实施顺序）。
"""

from .base import (
    ALL_STATUSES,
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_NO_OUTPUT,
    STATUS_TIMEOUT,
    SystemAdapter,
    SystemMeta,
    TurnInput,
    TurnOutcome,
)
from .build import AdapterBundle, build_adapters

__all__ = [
    "ALL_STATUSES",
    "STATUS_COMPLETED",
    "STATUS_ERROR",
    "STATUS_NO_OUTPUT",
    "STATUS_TIMEOUT",
    "AdapterBundle",
    "SystemAdapter",
    "SystemMeta",
    "TurnInput",
    "TurnOutcome",
    "build_adapters",
]
