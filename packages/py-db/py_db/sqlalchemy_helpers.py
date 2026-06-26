"""SQLAlchemy 类型辅助函数。

将库签名未精确表达的运行时语义（如 DML 结果的 rowcount）
集中在单一位置显式收窄，避免在业务代码中散落 type: ignore。
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy.engine import CursorResult
from sqlalchemy.engine.result import Result


def rowcount(result: Result[Any]) -> int:
    """返回 DML 语句影响的行数。

    SQLAlchemy 2.0 中，``session.execute()`` 对 UPDATE/DELETE/INSERT
    实际返回 ``CursorResult``，但 mypy 存根统一返回 ``Result[Any]``。
    本辅助函数通过 ``cast`` 显式收窄类型，供 Repository 层使用。

    Args:
        result: ``session.execute()`` 返回的结果对象。

    Returns:
        受影响的行数；无匹配行时为 0。
    """
    return cast(CursorResult[Any], result).rowcount
