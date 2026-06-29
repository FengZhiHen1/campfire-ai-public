# @contract
"""DEPLOY-05 环境配置管理 — AppSettings 配置模型。

基于 pydantic-settings BaseSettings 实现环境变量加载与校验。
包含数据库、缓存、LLM 接口、嵌入模型、对象存储、认证和限流七个维度的全部 18 项配置字段。
"""

import os
import warnings
from typing import Literal

from pydantic import (
    AnyHttpUrl,
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from py_config.exceptions import ConfigWarning

# 生产环境需检测的敏感字段名列表
_SECRET_FIELD_NAMES = (
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "JWT_SECRET_KEY",
)


class AppSettings(BaseSettings):
    """全局配置对象。

    从环境变量和 .env 文件加载并校验全部 18 项配置字段。
    校验通过后作为不可变单例供所有下游模块使用。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ===== 必填字段 (10) =====

    DATABASE_URL: PostgresDsn = Field(
        description="PostgreSQL 连接串（含异步驱动 asyncpg），"
        "必须包含数据库地址、端口、用户名、密码和数据库名",
    )

    REDIS_URL: RedisDsn = Field(
        description="Redis 连接串，必须包含 Redis 地址、端口和数据库编号",
    )

    DEEPSEEK_API_KEY: SecretStr = Field(
        description="DeepSeek API 身份凭证。调用 .get_secret_value() 获取明文。",
        min_length=3,
    )

    DEEPSEEK_BASE_URL: AnyHttpUrl = Field(
        description="DeepSeek API 的服务端点地址，必须为合法 HTTPS URL",
    )

    DASHSCOPE_API_KEY: SecretStr = Field(
        description="阿里云 DashScope 嵌入模型服务 API 密钥。调用 .get_secret_value() 获取明文。",
        min_length=3,
    )

    DASHSCOPE_BASE_URL: AnyHttpUrl = Field(
        default=AnyHttpUrl("https://dashscope.aliyuncs.com/compatible-mode/v1"),
        description="阿里云 DashScope API 的服务端点地址，必须为合法 HTTPS URL",
    )

    MINIO_ENDPOINT: str = Field(
        description="MinIO 对象存储服务端点，必须包含地址和端口",
        min_length=1,
    )

    MINIO_ACCESS_KEY: SecretStr = Field(
        description="MinIO 对象存储访问密钥。调用 .get_secret_value() 获取明文。",
        min_length=1,
    )

    MINIO_SECRET_KEY: SecretStr = Field(
        description="MinIO 对象存储私有密钥。调用 .get_secret_value() 获取明文。",
        min_length=1,
    )

    JWT_SECRET_KEY: SecretStr = Field(
        description="JWT 签名密钥，长度不少于 32 字符。调用 .get_secret_value() 获取明文。",
        min_length=32,
    )

    # ===== 可选字段 (8) — 均有默认值 =====

    JWT_ALGORITHM: Literal["HS256", "HS384", "HS512"] = Field(
        default="HS256",
        description="JWT 签名算法。可选值：HS256、HS384、HS512",
    )

    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=15,
        description="访问令牌过期时间（分钟）。必须为正整数。",
        ge=1,
    )

    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7,
        description="刷新令牌过期时间（天）。必须为正整数。",
        ge=1,
    )

    RATE_LIMIT_USER_PER_MINUTE: int = Field(
        default=30,
        description="单用户每分钟的 API 请求上限。必须为正整数。",
        ge=1,
    )

    RATE_LIMIT_IP_PER_MINUTE: int = Field(
        default=100,
        description="单 IP 每分钟的 API 请求上限。必须为正整数。",
        ge=1,
    )

    ENVIRONMENT: Literal["development", "testing", "production"] = Field(
        default="development",
        description="当前运行环境标识。允许值：development、testing、production",
    )

    EMBEDDING_MODEL: str = Field(
        default="text-embedding-v4",
        description="嵌入模型名称。默认值 text-embedding-v4。",
    )

    EMBEDDING_DIMENSION: int = Field(
        default=1024,
        description="嵌入向量维度数。默认值 1024。",
        ge=1,
    )

    DEEPSEEK_MODEL: str = Field(
        default="deepseek-v4-pro",
        description="DeepSeek 对话模型名称。用于应急咨询（危机分级复审 + 方案生成）的 LLM 调用。",
    )

    GENERATION_TEMPERATURE: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="LLM 生成温度参数（意图文档约束 ≤ 0.3）。CSLT-03 使用。",
    )

    GENERATION_MAX_TOKENS: int = Field(
        default=8192,
        ge=1,
        le=32768,
        description="LLM 单次生成的最大 Token 数。CSLT-03 使用。",
    )

    GENERATION_TIMEOUT_S: float = Field(
        default=300.0,
        ge=1.0,
        le=600.0,
        description="LLM 全流程超时秒数。CSLT-03 全流程硬超时。",
    )

    # ===== MVP 评委体验账号配置 =====
    # 当前产品面向评委线上评审，无普通用户场景。
    # 所有未携带 JWT 的请求默认映射到该预置 expert 账号，实现打开即用。

    JUDGE_USERNAME: str = Field(
        default="judge",
        min_length=1,
        max_length=32,
        description="预置评委账号用户名。所有匿名请求默认映射到此账号。",
    )

    JUDGE_PHONE: str = Field(
        default="19900000000",
        min_length=11,
        max_length=11,
        pattern=r"^1[3-9]\d{9}$",
        description="预置评委账号占位手机号。",
    )

    JUDGE_REAL_NAME: str = Field(
        default="评审专家",
        min_length=1,
        max_length=20,
        description="预置评委账号显示名称。",
    )

    # ===== SSE 流式推送配置 (5) — CSLT-04 =====

    SSE_MAX_CONCURRENT_CONNECTIONS: int = Field(
        default=500,
        ge=1,
        le=10000,
        description="每个 Uvicorn worker 进程的最大并发 SSE 连接数。"
        "达到上限时新连接返回 HTTP 429。4 workers × 500 = 2000 全局上限。",
    )

    SSE_SESSION_TTL_SECONDS: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="流式推送会话过期时间（秒）。连接断开后会话保留此时间"
        "供重连续传，超时后自动清理释放内存。默认 300 秒（5 分钟）。",
    )

    SSE_HEARTBEAT_INTERVAL_SECONDS: int = Field(
        default=15,
        ge=1,
        le=120,
        description="SSE 心跳保活事件发送间隔（秒）。默认 15 秒。"
        "用于防止移动端网络或中间代理因长时间无数据而断开 SSE 连接。",
    )

    SSE_FIRST_CHUNK_TIMEOUT_SECONDS: int = Field(
        default=60,
        ge=1,
        le=300,
        description="首 chunk 软超时阈值（秒）。超过此时间未收到上游 CSLT-03 "
        "的第一个 chunk 时，发送进度提示事件但不终止流。默认 60 秒。",
    )

    SSE_FULL_TIMEOUT_SECONDS: int = Field(
        default=300,
        ge=5,
        le=600,
        description="全流程硬超时阈值（秒）。从会话创建起超过此时间尚未完成"
        "全部推送时，强制关闭上游 Generator 并发送 DoneEvent(finish_reason=TIMEOUT)。"
        "默认 300 秒（5 分钟）。",
    )

    @model_validator(mode="after")
    def _check_production_secrets(self) -> "AppSettings":
        """生产环境安全检测。

        在 production 环境下检测 .env 文件是否存在且包含敏感密钥字段，
        若存在则通过 warnings.warn() 输出安全告警，但不阻断启动。
        """
        if self.ENVIRONMENT != "production":
            return self

        # 检查 .env 文件是否存在
        env_file_path = ".env"
        if not os.path.exists(env_file_path):
            return self

        try:
            with open(env_file_path, encoding="utf-8") as f:
                env_content = f.read()
        except OSError:
            # 文件不可读（权限等），不做阻断处理
            return self

        # 检测 .env 文件内容中是否包含敏感字段
        affected_fields: list[str] = []
        for field_name in _SECRET_FIELD_NAMES:
            if field_name in env_content:
                affected_fields.append(field_name)

        if affected_fields:
            warning_message = (
                "生产环境中检测到密钥来源于本地 .env 文件（非 KMS 注入），"
                "存在安全隐患。"
            )
            warnings.warn(
                ConfigWarning(
                    message=warning_message,
                    affected_fields=affected_fields,
                )
            )

        return self
