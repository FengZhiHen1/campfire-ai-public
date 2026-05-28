"""SEC-01 密码哈希与校验。

使用 bcrypt 库直接对明文密码进行不可逆哈希和校验。
每次哈希使用随机 salt，相同输入产生不同输出。

公开函数：
  - hash_password: bcrypt 密码哈希（不幂等，随机 salt）
  - verify_password: 密码校验（幂等）
"""

from __future__ import annotations

import bcrypt

from py_auth.exceptions import HashingError
from py_config.security import get_security_config


def hash_password(plain_password: str) -> str:
    """使用 bcrypt 对明文密码进行不可逆哈希。

    每次调用使用随机 salt，相同输入产生不同哈希值。
    密码校验必须使用 verify_password，禁止直接比对哈希串。

    Args:
        plain_password: 明文密码原文，长度 8-64 字符。

    Returns:
        str: bcrypt 哈希字符串，格式 ``$2b$12$...``。

    Raises:
        ValueError: plain_password 长度不在 [8, 64] 范围内。
        HashingError: bcrypt 引擎内部错误。

    Side Effects:
        无。纯函数，无 I/O 操作。
    """
    length = len(plain_password)
    if length < 8 or length > 64:
        raise ValueError(
            f"密码长度必须在 8-64 之间，当前长度为 {length}"
        )

    try:
        rounds = get_security_config().BCRYPT_ROUNDS
        salt = bcrypt.gensalt(rounds=rounds)
        hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
        return hashed.decode("utf-8")
    except Exception as exc:
        raise HashingError(f"bcrypt 哈希计算失败: {exc}") from exc


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码是否匹配已存储的 bcrypt 哈希值。

    Args:
        plain_password: 待验证的明文密码，长度 8-64 字符。
        hashed_password: bcrypt 哈希值，格式 ``$2b$12$...`` 或 ``$2a$...``。

    Returns:
        bool: True 表示密码匹配，False 表示不匹配。

    Raises:
        ValueError: plain_password 长度不在 [8, 64] 范围内，
                    或 hashed_password 不以 ``$2b$`` / ``$2a$`` 开头。
        HashingError: bcrypt 引擎内部错误。

    Side Effects:
        无。纯函数，无 I/O 操作。
    """
    length = len(plain_password)
    if length < 8 or length > 64:
        raise ValueError(
            f"密码长度必须在 8-64 之间，当前长度为 {length}"
        )

    if not isinstance(hashed_password, str):
        raise ValueError(
            f"hashed_password 必须是 str 类型，实际为 {type(hashed_password).__name__}"
        )

    if not hashed_password.startswith("$2b$") and not hashed_password.startswith(
        "$2a$"
    ):
        raise ValueError(
            "hashed_password 格式不合法，必须以 $2b$ 或 $2a$ 开头"
        )

    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception as exc:
        raise HashingError(f"bcrypt 密码校验失败: {exc}") from exc


__all__ = [
    "hash_password",
    "verify_password",
]
