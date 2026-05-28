"""SEC-01 传输存储安全 — 安全配置模型。

提供 SecurityConfig（全量安全配置，18 字段，env_prefix=SECURITY_）
和 RateLimitConfig（限流配置子集，纯数据模型）。

SecurityConfig 从环境变量加载，字段名大写且带 SECURITY_ 前缀：
  - SECURITY_BCRYPT_ROUNDS (默认 12)
  - SECURITY_JWT_SECRET_KEY (必填, >=32 字符)
  - SECURITY_JWT_PREVIOUS_SECRET_KEY (必填, >=32 字符)
  - SECURITY_JWT_ALGORITHM (默认 HS256)
  - SECURITY_JWT_KEY_VERSION (默认 v1)
  - SECURITY_JWT_PREVIOUS_KEY_VERSION (默认空字符串)
  - SECURITY_RATE_LIMIT_USER_PER_MINUTE (默认 30)
  - SECURITY_RATE_LIMIT_IP_PER_MINUTE (默认 100)
  - SECURITY_RATE_LIMIT_WINDOW_SECONDS (默认 60)
  - SECURITY_MINIO_PRESIGNED_URL_EXPIRY_SECONDS (默认 3600)
  - SECURITY_ALLOWED_FILE_EXTENSIONS (默认 ["pdf","jpg","jpeg","png","docx"])
"""

from __future__ import annotations

import functools
import os
from typing import Literal

from pydantic import Field, BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# MVP 兼容：SecurityConfig 需要 SECURITY_ 前缀的环境变量，但项目 .env 使用无前缀的变量名。
# 若 SECURITY_ 前缀变量缺失，自动回退到普通变量名。
if not os.environ.get("SECURITY_JWT_SECRET_KEY"):
    fallback = os.environ.get("JWT_SECRET_KEY", "")
    if fallback:
        os.environ.setdefault("SECURITY_JWT_SECRET_KEY", fallback)
if not os.environ.get("SECURITY_JWT_PREVIOUS_SECRET_KEY"):
    fallback = os.environ.get("JWT_SECRET_KEY", "")
    if fallback:
        os.environ.setdefault("SECURITY_JWT_PREVIOUS_SECRET_KEY", fallback)


class RateLimitConfig(BaseModel):
    """限流配置参数（纯数据模型，供 SEC-04 等消费方使用）。

    三个字段均可从 SecurityConfig 对应字段映射获得。
    """

    RATE_LIMIT_USER_PER_MINUTE: int = Field(
        default=30,
        ge=1,
        description="每个用户每分钟最大请求数",
    )
    RATE_LIMIT_IP_PER_MINUTE: int = Field(
        default=100,
        ge=1,
        description="每个 IP 每分钟最大请求数",
    )
    RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=60,
        ge=1,
        description="限流滑动窗口大小（秒）",
    )


class SecurityConfig(BaseSettings):
    """SEC-01 传输存储安全模块的全量安全配置。

    通过 pydantic-settings 从 SECURITY_ 前缀的环境变量加载。
    JWT_SECRET_KEY 和 JWT_PREVIOUS_SECRET_KEY 为必填字段，
    其余字段均有默认值。

    注意：JWT_KEY_VERSION 和 JWT_PREVIOUS_KEY_VERSION 为契约外补充字段，
    用于 JWT kid 密钥选择机制。详见 pending-confirmations.md。
    """

    model_config = SettingsConfigDict(
        env_prefix="SECURITY_",
        env_file_encoding="utf-8",
    )

    # ===== 密码哈希 =====
    BCRYPT_ROUNDS: int = Field(
        default=12,
        ge=12,
        description="bcrypt 哈希 salt 加固轮次，OWASP 推荐 >=12",
    )

    # ===== JWT 密钥 =====
    JWT_SECRET_KEY: str = Field(
        min_length=32,
        description="当前 JWT 签名密钥，>=256 位（32 字符）",
    )

    JWT_PREVIOUS_SECRET_KEY: str = Field(
        min_length=32,
        description="上一个 JWT 签名密钥，密钥轮换共栖期使用",
    )

    JWT_ALGORITHM: Literal["HS256"] = Field(
        default="HS256",
        description="JWT 签名算法，仅支持 HS256",
    )

    # 以下两个字段不在 SecurityConfig 契约中，属实现所需的补充字段
    # 详见 packages/py-auth/py_auth/pending-confirmations.md
    JWT_KEY_VERSION: str = Field(
        default="v1",
        description="当前密钥版本标识（kid），签发时写入 JWT header",
    )

    JWT_PREVIOUS_KEY_VERSION: str = Field(
        default="",
        description="上一个密钥版本标识，共栖期校验时匹配旧 token 的 kid",
    )

    # ===== 限流 =====
    RATE_LIMIT_USER_PER_MINUTE: int = Field(
        default=30,
        ge=1,
        description="每个用户每分钟最大请求数",
    )

    RATE_LIMIT_IP_PER_MINUTE: int = Field(
        default=100,
        ge=1,
        description="每个 IP 每分钟最大请求数",
    )

    RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=60,
        ge=1,
        description="限流滑动窗口大小（秒）",
    )

    # ===== 对象存储 =====
    MINIO_PRESIGNED_URL_EXPIRY_SECONDS: int = Field(
        default=3600,
        ge=60,
        description="MinIO 预签名 URL 默认过期时间（秒）",
    )

    # ===== 文件安全 =====
    ALLOWED_FILE_EXTENSIONS: list[str] = Field(
        default=["pdf", "jpg", "jpeg", "png", "docx"],
        description="允许上传的文件扩展名白名单（不含前导点）",
    )


@functools.lru_cache(maxsize=1)
def get_security_config() -> SecurityConfig:
    """获取 SecurityConfig 单例（线程安全，惰性初始化）。

    首次调用时从环境变量（SECURITY_ 前缀）加载并校验配置。
    后续调用返回缓存实例。

    Returns:
        SecurityConfig: 校验通过的安全配置单例。

    Raises:
        pydantic.ValidationError: 环境变量校验失败时向上传播。
    """
    return SecurityConfig()  # type: ignore[call-arg]


__all__ = [
    "SecurityConfig",
    "RateLimitConfig",
    "get_security_config",
]
