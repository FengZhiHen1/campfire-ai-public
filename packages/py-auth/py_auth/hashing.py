"""py-auth 密码哈希 — BcryptHasher 实现。

实现 PasswordHasher 契约，使用 bcrypt 进行不可逆哈希和校验。
每次哈希使用随机 salt，相同输入产生不同输出。

核心类:
  - BcryptHasher: 实现 PasswordHasher 契约，bcrypt 密码哈希

Usage:
    from py_auth.hashing import BcryptHasher
    hasher = BcryptHasher()
    hashed = hasher.hash_password("mypassword")
    assert hasher.verify_password("mypassword", hashed)
"""

from __future__ import annotations

import bcrypt

from py_auth.auth_contract import PasswordHasher
from py_auth.exceptions import HashingError
from py_config.security import get_security_config
from py_logger import logger


class BcryptHasher(PasswordHasher):
    """bcrypt 密码哈希实现，继承 PasswordHasher 契约。

    自动从 py-config 读取 BCRYPT_ROUNDS 配置。
    """

    def __init__(self) -> None:
        self._rounds: int = get_security_config().BCRYPT_ROUNDS

    # ------------------------------------------------------------------
    # 契约钩子
    # ------------------------------------------------------------------

    def _do_hash(self, plain_password: str) -> str:
        """执行 bcrypt 哈希计算。

        输入约束:
          - plain_password 已通过父类长度校验
        异常:
          - HashingError: bcrypt 引擎内部错误
        """
        try:
            salt = bcrypt.gensalt(rounds=self._rounds)
            hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
            return hashed.decode("utf-8")
        except Exception as exc:
            logger.error(
                "py-auth",
                f"bcrypt 哈希计算失败: {exc}",
                op_type="认证",
                extra={"error_type": type(exc).__name__},
            )
            raise HashingError(
                f"bcrypt 哈希计算失败: {exc}", operation="hash"
            ) from exc

    def _do_verify(self, plain_password: str, hashed_password: str) -> bool:
        """执行密码比对校验。"""
        try:
            return bcrypt.checkpw(
                plain_password.encode("utf-8"),
                hashed_password.encode("utf-8"),
            )
        except Exception as exc:
            logger.error(
                "py-auth",
                f"bcrypt 密码校验失败: {exc}",
                op_type="认证",
                extra={"error_type": type(exc).__name__},
            )
            raise HashingError(
                f"bcrypt 密码校验失败: {exc}", operation="verify"
            ) from exc


# ============================================================================
# 惰性初始化（避免 import 时触发 get_security_config）
# ============================================================================

_hasher_instance: BcryptHasher | None = None


def _get_hasher() -> BcryptHasher:
    """获取 BcryptHasher 单例（惰性初始化）。"""
    global _hasher_instance
    if _hasher_instance is None:
        _hasher_instance = BcryptHasher()
    return _hasher_instance


# ============================================================================
# 便捷函数（兼容旧 API）
# ============================================================================


def hash_password(plain_password: str) -> str:
    """便捷函数——使用 BcryptHasher 实例执行哈希。

    推荐在新代码中直接实例化 BcryptHasher 使用。
    """
    return _get_hasher().hash_password(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """便捷函数——使用 BcryptHasher 实例校验密码。"""
    return _get_hasher().verify_password(plain_password, hashed_password)


__all__ = [
    "BcryptHasher",
    "hash_password",
    "verify_password",
]
