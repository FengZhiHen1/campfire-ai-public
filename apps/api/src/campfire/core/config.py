"""配置唯一入口：应用读取环境变量的唯一位置。

规则（见 docs/项目结构设计.md 第 10 节）：

- 其它模块不得各自读取环境变量，避免形成第二真相。
- 密钥只经环境注入，不入版本库；本文件不得出现任何真实凭据字面量，
  因此可含密钥的字段一律无默认值（未配置即 ``None``，由健康检查如实报告）。
- 模型名由 ``campfire.agent.model`` 从这里取值，业务代码不得硬编码模型名。
"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# 本文件位于 <仓库根>/apps/api/src/campfire/core/config.py，
# 因此 parents[5] 是仓库根、parents[3] 是 apps/api。层级写死在此处，
# 文件移动时必须同步修改。
_REPO_ROOT = Path(__file__).resolve().parents[5]
_APP_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    """应用配置。字段名对应同名的大写环境变量（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 应用 ---
    app_env: str = "development"
    log_level: str = "INFO"

    # --- 数据主库（PostgreSQL 17 + pgvector）---
    # 含凭据，故无默认值；未配置时健康检查报 not_configured 而非伪装可用。
    database_url: str | None = None

    # --- 缓存与队列 broker（Redis 7）---
    redis_url: str = "redis://localhost:6379/0"
    # Taskiq broker 的队列名；core/jobs 用它读待消费积压。
    taskiq_queue_name: str = "campfire"

    # --- 模型路由（腾讯云 TokenHub / DeepSeek-V4.1-Flash）---
    # 接口地址与开通地域绑定，不支持跨地域调用（见 docs/技术栈设计.md 第 6 节）。
    tokenhub_base_url: str = "https://tokenhub.tencentmaas.com/v1"
    tokenhub_api_key: SecretStr | None = None
    model_name: str = "deepseek-v4.1-flash"

    # --- 认证（SuperTokens core 容器）---
    # 会话校验在 Python SDK 内完成、不经过 core；core 只在注册、登录、
    # 重置、刷新时被调用。此处只用于健康检查探测 core 可达性（``GET /hello``
    # 不需要 API Key），故暂无 supertokens_api_key 字段——它在 SDK 装配落地时加入。
    supertokens_connection_uri: str = "http://localhost:3567"

    # 通用记忆（Graphiti + FalkorDB）的连接配置同理：内存模块落地时，
    # 连同它的消费者一起加入。

    # --- skill 内容根目录 ---
    # 由配置指定（见 docs/项目结构设计.md 第 10 节）；默认指向应用内的 skills/。
    skill_root: Path = _APP_ROOT / "skills"


@lru_cache
def get_settings() -> Settings:
    """返回进程内唯一的配置实例。"""
    return Settings()
