"""配置唯一入口：应用读取环境变量的唯一位置。

职责：定义 `Settings`，集中承载本应用的全部环境变量配置。
边界：其它模块不得各自读取环境变量；密钥只经环境注入，含密钥字段一律无默认值。
参考：docs/项目结构设计.md 第 10 节；完整规则与理由见 :class:`Settings`。
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# 本文件位于 <仓库根>/apps/api/src/campfire/core/config.py，
# 因此 parents[5] 是仓库根、parents[3] 是 apps/api。层级写死在此处，
# 文件移动时必须同步修改。
_REPO_ROOT = Path(__file__).resolve().parents[5]
_APP_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"

#: 嵌入维度：与 `embedding_model_name`（`Kinfra-Text-Embedding-4b`）绑定，
#: 固定不可配置——可配置的维度会诱发「配错维度混库」，使检索静默失准
#: （RAG 策略第 7 节纪律 4）。换模型必须整库重建。
#:
#: 为什么放在 core 而不是某个模块内（2026-09-29 定）：检索链（`modules/library`）
#: 与记忆侧（`modules/memory`，Graphiti 的嵌入器）必须用同一个向量模型与维度
#: （RAG 策略第 11 节），而 [项目结构设计] 第 7 节禁止 `modules/*` 之间互相 import。
#: 若常量留在 library，memory 只能靠 `library` 导入或各自复制一份——前者越过白名单，
#: 后者制造第二真源（本项目已因「同一事实两处定义」修过一次）。因此它与
#: `embedding_model_name` 放在同一处：模型名的唯一配置处，也是维度的唯一常量处。
EMBEDDING_DIM = 2560


class Settings(BaseSettings):
    """应用配置。字段名对应同名的大写环境变量（大小写不敏感）。

    规则（见 docs/项目结构设计.md 第 10 节）：

    - 其它模块不得各自读取环境变量，避免形成第二真相。
    - 密钥只经环境注入，不入版本库；本文件不得出现任何真实凭据字面量，
      因此可含密钥的字段一律无默认值（未配置即 `None`，由健康检查如实报告）。
    - 模型名由 `campfire.agent.model` 从这里取值，业务代码不得硬编码模型名。
    """

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
    # 引用索引的单次操作超时（秒）。端口契约（`agent/context/citations.py`）要求
    # 实现自带超时上界，理由是这个写入在注入渲染的路径上：它慢就会拖住整次运行，
    # 而运行另有 180 秒通用上限（基座第 2 节），无界等待会让上限失效。
    # 有界且远小于 180 秒：DB 侧异常应尽快落进明确失败，而不是把预算耗在等待上。
    citation_timeout_seconds: float = Field(default=5.0, gt=0)

    # --- 缓存与队列 broker（Redis 7）---
    redis_url: str = "redis://localhost:6379/0"
    # Taskiq broker 的队列名；core/jobs 用它读待消费积压。
    taskiq_queue_name: str = "campfire"

    # --- 模型路由（腾讯云 TokenHub / DeepSeek-V4.1-Flash）---
    # 接口地址与开通地域绑定，不支持跨地域调用（见 docs/技术栈设计.md 第 6 节）。
    tokenhub_base_url: str = "https://tokenhub.tencentmaas.com/v1"
    tokenhub_api_key: SecretStr | None = None
    model_name: str = "deepseek-v4.1-flash"
    # 嵌入模型名（RAG 策略第 2 节「配置与 DDL 归属」）：唯一配置处是本文件，
    # 因为 `core/*` 不得依赖 `agent/*`（项目结构设计第 7 节）——`agent/model`
    # 只拥有 LLM 模型名。复用上面的 base_url 与 api_key：嵌入服务同为 TokenHub，
    # 不引入第二套凭据（RAG 策略第 11 节要求记忆侧也用同一个向量模型）。
    # 维度（2560）与模型绑定，不做成可配置项——可配置的维度会诱发配错维度
    # 混库，使检索静默失准（RAG 策略第 7 节纪律 4）；常量见本模块的 EMBEDDING_DIM。
    embedding_model_name: str = "kinfra-text-embedding-4b"
    # 单次请求超时与重试上界。三者的最坏组合必须落在基座第 2 节的 180 秒通用响应
    # 上限之内（默认值最坏 45×3 + 退避(1.125+2.25)，gateway 的算术按 SDK 的抖动上界算），
    # 否则重试会被运行上限从中间砍断；越界配置在 agent.model 构造期即抛错，
    # 见 docs/技术设计/technical-details/通用基座.md 第 6 节。
    #
    # 数值边界写进类型约束（而不是只靠构造期校验）：负数重试会让「最坏耗时」算成 0 秒、
    # 使那条闸门对任何超时值都放行——实测 model_max_retries=-1 配 timeout=1000 可构造成功。
    model_request_timeout_seconds: float = Field(default=45.0, gt=0)
    model_max_retries: int = Field(default=2, ge=0)
    model_retry_initial_delay_seconds: float = Field(default=1.0, ge=0)
    model_retry_max_delay_seconds: float = Field(default=8.0, ge=0)
    # --- 压缩阈值算术的两个输入（见压缩策略第 2、10 节）---
    # W：模型上下文上限。2026-09-29 经用户确认为 1024k = 1,048,576（压缩策略第 2 节）。
    model_context_window_tokens: int = Field(default=1_048_576, gt=0)
    # O：为输出预留的额度，代入阈值公式 floor(min(W×0.8, W−O−headroom))。
    # 注意：基座第 2 节不设 token 上限，因此我们不在请求上写 max_tokens——
    # 这里的 O 是预算假设（压缩策略第 2 节按 8192 代入），不是截断值。
    model_output_reserve_tokens: int = Field(default=8192, ge=0)

    # --- 认证（SuperTokens core 容器）---
    # core 在鉴权关键路径上（2026-09-29 裁决，见
    # docs/技术设计/decisions/会话校验逐请求查证数据库.md）：SDK 以
    # `check_database=True` 逐请求查证，而该查证由 core 执行。因此 core 不可用时，
    # 注册、登录、重置、刷新以及全部受限操作都不可用（fail-closed）。
    # 此处只用于健康检查探测 core 可达性（`GET /hello` 不需要 API Key）。
    supertokens_connection_uri: str = "http://localhost:3567"
    # Management API 密钥。实测必须有值：core 启动时若配置了 `API_KEYS`，
    # 未带该 key 的请求会被拒——实测 `GET /apiversion` 返回
    # `401 Invalid API key`，SDK 因此在建号的第一步就失败。
    # 含凭据，故无默认值；未配置时装配期显式报错，不静默降级。
    supertokens_api_key: SecretStr | None = None
    # 应用对外地址。SDK 需要它做 same-site 判定与 cookie 域推导，不是可选装饰：
    # 官方要求至少提供 `website_domain` 或 `origin`，否则 `init` 直接抛错
    # （实测 `AppInfo` 的 `raise_general_exception`）。
    # 一期前后端同顶级域（经同一 Nginx 暴露，见技术栈设计第 6 节）。
    supertokens_api_domain: str = "http://localhost:8000"
    supertokens_website_domain: str = "http://localhost:5173"
    # 身份服务路由的挂载路径（SDK 的 `api_base_path`）。契约的一部分：
    # 前端与运维文档据此拼 URL（认证与账号第 5 节的 `/auth/*`）。
    supertokens_api_base_path: str = "/auth"

    # --- 通用记忆（Graphiti + FalkorDB）---
    # 连接配置在此集中：modules/memory 不得自己读环境变量（第 10 节唯一入口）。
    # FalkorDB 是 Redis 分支，故端口与 Docker 的宿主机映射一致（compose 里 6380:6379，
    # 避开 Redis 自己的 6379）。密码可空——本地容器默认无密码；生产必须设。
    # 图库名（database）一期固定一个：记忆按账号分区靠 group_id，不靠分库
    # （见 docs/技术设计/decisions/通用记忆归属为账号.md），分库会让账号隔离
    # 与一次查询分区的设计同时失效。
    falkordb_host: str = "localhost"
    falkordb_port: int = Field(default=6380, gt=0, lt=65536)
    falkordb_password: SecretStr | None = None
    # 图库名必须满足 Graphiti 的 group_id 判据（`^[a-zA-Z0-9_-]+$`，见
    # `validate_group_id`）：它在每次请求里被拿来与账号 id 比较
    # （`_resolve_request_scope` 的 `group_id == driver._database`），含非法字符
    # 或为空都会让「是否同一个图」的判定失效。实测未加约束时
    # `'campfire test'`/`'bad/name'`/`''`/非 ASCII 全部放行。
    falkordb_database: str = Field(default="campfire", min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    # 单次图库操作超时（秒）。有界：应急预注入在首字时延路径上（`RQ-EMG-03`），
    # 图库慢时必须尽快落进「明确标注不可用」的降级分支，而不是拖住整次运行。
    falkordb_timeout_seconds: float = Field(default=5.0, gt=0)
    # 图库并发上界，传给 Graphiti 的 max_coroutines。Graphiti 默认取环境变量
    # SEMAPHORE_LIMIT（默认 20）；我们显式传入，避免该行为随环境漂移。
    falkordb_max_coroutines: int = Field(default=20, gt=0)

    # --- skill 内容根目录 ---
    # 由配置指定（见 docs/项目结构设计.md 第 10 节）；默认指向应用内的 skills/。
    skill_root: Path = _APP_ROOT / "skills"


@lru_cache
def get_settings() -> Settings:
    """返回进程内唯一的配置实例。"""
    return Settings()
