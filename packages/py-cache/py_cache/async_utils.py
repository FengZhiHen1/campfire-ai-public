"""异步运行时工具函数。

处理部分第三方库（如 aioredis）方法签名同时返回协程或值的情况，
在边界处显式收窄类型，避免业务代码散落 type: ignore。
"""

from __future__ import annotations

import inspect
from typing import Awaitable, TypeVar

T = TypeVar("T")


async def maybe_await(value: Awaitable[T] | T) -> T:
    """如果 value 是协程则 await，否则直接返回。

    用于 aioredis 等类型签名返回 ``Awaitable[T] | T`` 的方法调用点，
    将运行时不确定性收敛到单一类型安全入口。

    Args:
        value: 可能是协程对象，也可能是已解析的值。

    Returns:
        解析后的值。
    """
    if inspect.isawaitable(value):
        return await value
    return value
