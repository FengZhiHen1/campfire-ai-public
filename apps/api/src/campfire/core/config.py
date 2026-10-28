"""配置唯一入口：应用读取环境变量的唯一位置。

职责：定义 `Settings`，集中承载本应用的全部环境变量配置；并拥有进程环境里
`no_proxy` 家族的规范化（见本模块末尾一节）。
边界：其它模块不得各自读取环境变量；密钥只经环境注入，含密钥字段一律无默认值。
参考：docs/项目结构设计.md 第 10 节；完整规则与理由见 :class:`Settings`。
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
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
    model_request_timeout_seconds: float = Field(default=120.0, gt=0)
    model_max_retries: int = Field(default=1, ge=0)
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
    #
    # 2026-10-01 起为 `/api/auth`（此前是 `/auth`）：与四个业务面一起收进 `/api` 前缀，
    # 让接口路径与前端页面路径不可能相撞（页面在 `/consult`，接口在 `/api/consult`）。
    # 此前 `/auth` 恰好没与页面路由冲突，但把认证单独留在根会让「哪些路径是接口」这条
    # 规则出现例外——例外正是下次踩坑的地方。
    # 多段前缀 SDK 支持（实测 `NormalisedURLPath('/api/auth')` 可表达并参与前缀匹配）。
    supertokens_api_base_path: str = "/api/auth"

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


# ---------------------------------------------------------------------------
# 进程环境的 no_proxy 规范化
#
# 为什么它归 `core/config`：配置唯一入口的职责是「进程怎么读环境」。`no_proxy` 的
# 取值形态会让 httpx/openai 在**构造客户端**时崩，那是环境读入侧的问题，与谁在构造
# 客户端无关。放在 `core/config` 的第二个理由是层白名单：`agent/*` 只放行
# `campfire.core.config`（docs/项目结构设计.md 第 7 节，机械检查见
# `apps/api/tests/test_layer_boundaries.py`），因此下沉到这里，`agent/model/proxy_env`
# 可以照旧复用同一份实现，而不必新增一条白名单（新增会与文档产生第二真源）。
#
# 缺陷（2026-10-01 实测，2026-10-05 由 T18 修为进程级）：
#
# 宿主机 `no_proxy` 含**带方括号的 IPv6 字面量**（如 `127.0.0.1,localhost,::1,[::1]`）时，
# `httpx` 的 `get_environment_proxies()` 把它拼成 `all://*[::1]`，`URLPattern` 构造期
# 把 `:1]` 当端口 ⇒ 抛 `InvalidURL: Invalid port: ':1]'`。httpx 0.28.1 与 httpx2 2.13.1
# **两个包都会崩**（`openai` 用的是 httpx2，且两者的 `InvalidURL` 互不为子类）。
#
# 而这发生在**客户端构造期**，于是 SuperTokens 的 querier（`querier.py:110` 自己
# `AsyncClient(timeout=30.0)`，**未传 `trust_env=False`**）让注册与登录的**第一步就 500**。
# 产品侧曾经的防护只覆盖了两条不重合的路径：`core/auth` 的探针用 `trust_env=False`
# 绕开（所以 `/readyz` 的 `auth` 项**仍报 ok**），`agent/model/gateway.py` 用构造窗口
# 规范化——**querier 不在任何一条上**。「探针绿而功能坏」正是这样来的。
#
# 为什么是「进程内、两个大小写键都写」，而不是在启动脚本里设环境变量：
#
# Windows 上进程环境块里 `NO_PROXY` 与 `no_proxy` **可以并存**，而
# `os.py::_createenviron` 的 nt 分支做 `data[key.upper()] = value`——**按块内顺序折叠，
# 后出现的那条胜出**（本机实测 `no_proxy` 在后，故小写那条胜出）。而
# `SetEnvironmentVariableW` 大小写不敏感地匹配**首个**条目并保留其原有大小写，
# 于是从 shell（cmd/PowerShell）无论设大写还是小写，改动都落在大写那条上，
# **Python 子进程读到的仍是被继承的旧小写值**（实测：shell 设完，子进程
# `os.environ['no_proxy']` 仍是旧值）。⇒ 唯一可靠的修法是在**本进程内**把两个键
# 都写进 `os.environ`：`encodekey` 会双双落到 `NO_PROXY`，本进程此后读到的即新值。
#
# 边界（诚实声明，实测）：这**不能**修正已经在环境块里的那条残留小写条目，因此
# **子进程**（如本进程再 spawn 的 Python）折叠后仍可能读到旧值——本修法的作用域是
# 「本进程内的 httpx/openai 消费者」，那正是产品路径出问题的地方。
# ---------------------------------------------------------------------------

#: 参与规范化的环境变量名。大小写两种都要：`urllib.getproxies_environment` 的
#: 第二遍只认全小写（故小写优先），而部分平台/工具只设大写。
PROXY_ENV_NAMES: tuple[str, ...] = ("no_proxy", "NO_PROXY")

#: httpx 解析不了带方括号的 IPv6 字面量，因此把它们去掉方括号。
#:
#: 判据写成「以 `[` 开头、以 `]` 结尾且中间含 `:`」而不是匹配固定几个取值：
#: 任何 IPv6 字面量在 no_proxy 里都可能被这样写（`[2001:db8::1]` 同样会让解析器崩），
#: 而只处理 `[::1]` 会把同类问题留给下一个地址。
_IPV6_BRACKET_PREFIX = "["
_IPV6_BRACKET_SUFFIX = "]"


def normalize_no_proxy(value: str) -> str:
    """把一个 `no_proxy` 取值里的方括号 IPv6 字面量规范化。

    保留分隔符与顺序（逗号分隔，含空项与前后空白原样保留），只改「方括号包 IPv6」
    这一种形态；其余取值（域名、IPv4、通配、CIDR）逐字不动。

    判别性：输入 `127.0.0.1,[::1],example.com` → `127.0.0.1,::1,example.com`；
    输入 `example.com,10.0.0.0/8` → 原样返回。

    为什么是无方括号形式：不带方括号的 IPv6 字面量正是 httpx 自己 `URLPattern` 的输出
    形式（实测 `[::1]` 与 `::1` 解析出的豁免模式**完全相同**，都是 `all://[::1]`），
    即它就是「解析器想要的输入」。因此本函数只改词法，不改任何豁免匹配结果。
    """
    parts: list[str] = []
    for raw in value.split(","):
        token = raw.strip()
        if token.startswith(_IPV6_BRACKET_PREFIX) and token.endswith(_IPV6_BRACKET_SUFFIX):
            inner = token[len(_IPV6_BRACKET_PREFIX) : -len(_IPV6_BRACKET_SUFFIX)]
            # 含 `:` 才是 IPv6 字面量；`[host]` 这类别的写法不动它（不猜）。
            if ":" in inner:
                # 保留原取值的前后空白形状，只替换中间那一段。
                leading = raw[: len(raw) - len(raw.lstrip())]
                trailing = raw[len(raw.rstrip()) :]
                parts.append(f"{leading}{inner}{trailing}")
                continue
        parts.append(raw)
    return ",".join(parts)


def apply_no_proxy_normalization() -> str | None:
    """进程级一次性规范化：`no_proxy` 家族**大小写两个键都写**成规范化后的值。

    在三个地方调用，且都必须在任何 httpx/openai 消费者**构造客户端**之前：

    1. `main.py` 与 `worker.py` 的**模块导入期**（排在项目内其它 import 之前）
       ——入口级时序保证；
    2. `core/auth/supertokens.py` 的 `init_supertokens` 里、SDK `init(...)` 之前
       ——那是本仓唯一的 SDK 装配入口，**API 与 CLI** 两个进程经它，
       因此「谁忘了在入口调一次」不会让 querier 重新坏掉。

    ⚠ **Worker 不调 `init_supertokens`**（2026-10-06 订正，T18 复查发现的 P2）——
    它由上面第 1 条覆盖。**别把 Worker 的入口调用当成多余的删掉**：
    删掉之后 Worker 侧会重新暴露在同一个代理陷阱下。

    为什么是进程级、且不回滚：SuperTokens 的 querier 在**任意请求时刻**才
    `AsyncClient(timeout=30.0)`（`querier.py:110`），构造窗口式的临时规范化覆盖不到它。
    这正是原实现（`agent/model/proxy_env` 的上下文管理器）修不了产品侧路径的原因。

    幂等：重复调用得到同一结果。

    Returns:
        写入的规范化取值；两个键都没有设置时返回 `None`（此时**什么都不写**——
        把「未设置」变成「设置为空」会改变 httpx 的行为，空串与未设置不是一回事）。
    """
    current = os.environ.get(PROXY_ENV_NAMES[0])
    if current is None:
        # 只有大写键存在（POSIX 上可能如此）：以它的值为准，但结果仍写两个键。
        current = os.environ.get(PROXY_ENV_NAMES[1])
    if current is None:
        return None

    normalized = normalize_no_proxy(current)
    # 两个键都写：见本节开头「为什么是两个大小写键都写」。在 Windows 上两次写入
    # 经 `encodekey` 折叠到同一个条目，故顺序无关；在 POSIX 上是两个条目，
    # 而 `urllib` 以小写为准，故先写大写、后写小写，让「最后一次写入」也是权威那个。
    for name in reversed(PROXY_ENV_NAMES):
        os.environ[name] = normalized
    return normalized


@contextmanager
def normalized_no_proxy_environment() -> Iterator[None]:
    """在块内把 `no_proxy` 家族规范化，退出时逐字还原。

    这是**构造窗口**式的纵深防护，保留给「不在装配路径上构造客户端」的调用方
    （CLI 命令、单元测试，以及 `agent/model` 里两处构造）。产品路径靠
    :func:`apply_no_proxy_normalization` 的进程级规范化——两者不互相替代：
    前者覆盖任意时刻的构造，后者覆盖「有人没走装配路径」。

    还原是精确的：某个变量原本不存在，退出后仍然不存在（不被写成空串）——见
    :func:`apply_no_proxy_normalization` 对「未设置 ≠ 空串」的同一说明。

    线程安全说明（如实声明残余风险）：`os.environ` 是进程级的，窗口期内若有别的线程
    同时构造客户端，它也会看到规范化后的取值——那对它同样是修复而非破坏（规范化
    不改变语义，只让解析不崩），因此这个窗口是可接受的。
    """
    saved: dict[str, str | None] = {name: os.environ.get(name) for name in PROXY_ENV_NAMES}
    try:
        for name in PROXY_ENV_NAMES:
            current = saved[name]
            if current is not None:
                os.environ[name] = normalize_no_proxy(current)
        yield
    finally:
        for name, original in saved.items():
            if original is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = original
