## 1 功能点：DEPLOY-05 环境配置管理 — 设计文档（瘦身版）

> **文档生成时间**：2026-05-26 17:06:18
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 17:06:18 | AI Assistant | 初始版本：基于技术预研报告生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `DEPLOY-05-环境配置管理-意图文档.md`（已冻结）
> - 本模块的精确编码规格见 `DEPLOY-05-环境配置管理-落地规范.md`

### 1.1 技术实现思路

本模块采用 pydantic-settings v2 的 `BaseSettings` 作为配置加载核心，而非手写 `os.environ` 解析。选择 pydantic-settings 的理由有三：

**类型驱动校验取代布尔守卫**：意图文档 §1.6 定义了 14 个配置字段，每个字段都有格式约束（连接串须含端口、密钥须长度为 32 字符、限流阈值为正整数等）。若采用 `os.getenv("KEY") or raise` 模式，需手写 14 条 if 分支和格式校验逻辑，代码膨胀且容易遗漏。pydantic-settings 的 `PostgresDsn`、`RedisDsn`、`AnyHttpUrl`、`SecretStr` 等专用类型由 Pydantic 内置校验器在构造时自动执行，零手工校验代码量。

**fail-fast 启动阻断**：`BaseSettings.__init__` 在构造时同步执行全部字段校验。若任何必填字段缺失或格式不合法，Pydantic 抛 `ValidationError`，由 FastAPI 的 `lifespan` startup 阶段的 `try/except` 捕获后以 `sys.exit(1)` 终止进程。这一设计确保服务不会在"半配置"状态下启动——要么全部校验通过，要么进程直接退出。此策略与意图文档 AC-01、AC-02 的启动阻断要求严格对齐。

**单例与脱敏的零成本实现**：全局配置通过模块级 `@lru_cache` + `get_settings()` 工厂函数实现单例模式。所有密钥字段使用 `pydantic.SecretStr`——在 `repr()` 和 `str()` 输出时自动脱敏为 `'**********'`，防止日志误泄露。需要显式明文获取时调用 `.get_secret_value()` 方法。这一方案直接满足了意图文档 §1.11 中的"密钥安全红线"对内存保护的基本要求，且无需引入第三方加密库。

数据流为严格单向管道：`OS 环境变量 / .env 文件 → pydantic-settings BaseSettings 构造 → 校验（通过/阻断） → 全局单例 Settings 对象 → 下游模块通过 get_settings() 获取`。加载完成后，配置对象为不可变（pydantic 默认 frozen=False 但推荐配合 `model_config = {"frozen": True}` 或运行时不修改的惯例）。此管道中不存在分支或延迟加载，保证任意调用方拿到的配置值始终一致。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：`docs/篝火智答-技术栈设计.md` §2（数据校验 Pydantic 2.x）、§6.2（关键配置 14 项清单）；`docs/篝火智答-项目结构.md` §6.1（`packages/py-config/` 目录骨架）；`docs/功能设计/模块依赖关系分析.md`（DEPLOY-05 依赖分析）；`docs/功能设计/` 下全部已有规格文档（扫描结果：无其他模块的落地规范）

- **兼容性结论**：**无冲突**。本模块为项目 L1 基础层首批模块，不存在已有规格的兼容性冲突。14 项环境变量定义与技术栈设计 §6.2 的 `.env` 清单完全对齐——DATABASE_URL、REDIS_URL、DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL、MINIO_ENDPOINT、MINIO_ACCESS_KEY、MINIO_SECRET_KEY、JWT_SECRET_KEY、JWT_ALGORITHM、ACCESS_TOKEN_EXPIRE_MINUTES、REFRESH_TOKEN_EXPIRE_DAYS、RATE_LIMIT_USER_PER_MINUTE、RATE_LIMIT_IP_PER_MINUTE、ENVIRONMENT。

- **复用的已有设计**：技术栈设计 §6.2 的 14 项环境变量清单作为本模块的唯一字段来源；项目结构设计 §6.1 `packages/py-config/` 目录树（`config.py`、`exceptions.py`、`__init__.py`）作为文件归属的直接依据。

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| Python 3.12+ 运行时 | 运行时依赖 | 解释器运行环境，通过 uv 0.6+ 的 `pyproject.toml` 声明 `requires-python = ">=3.12"` |
| pydantic 2.x + pydantic-settings 2.x | 库依赖 | `BaseSettings` 类用于环境变量加载与字段校验；`PostgresDsn`/`RedisDsn`/`AnyHttpUrl`/`SecretStr` 用于类型级校验与脱敏 |
| 操作系统环境变量 | 数据来源 | 通过 `os.environ` 或 `.env` 文件读取，pydantic-settings 默认优先取环境变量再取 `.env` |
| 容器编排（DEPLOY-01） | 下游消费 | `docker-compose.yml` 通过 `env_file` 指令引用 `.env` 或 `.env.prod`；容器启动时环境变量注入由编排层完成，py-config 不感知容器 |
| 反向代理路由（DEPLOY-02） | 间接消费 | Nginx 所需域名、SSL 证书路径由部署层通过环境变量注入，py-config 不直接向 Nginx 提供配置 |
| 数据库迁移（DEPLOY-04） | 下游消费 | Alembic 通过 `from py_config import get_settings; settings.DATABASE_URL` 获取数据库连接串 |
| 结构化日志（OBS-01） | 下游消费 | py-logger 从 py-config 读取日志级别配置；py-config 的异常也通过 py-logger 输出结构化日志 |
| 指标监控（OBS-02） | 间接消费 | Prometheus 抓取端点地址来自环境配置（部署层处理） |
| 告警通知（OBS-03） | 间接消费 | Webhook 地址来自环境配置（部署层处理） |
| 健康检查（OBS-04） | 下游消费 | 健康检查端点通过 py-config 获取 DATABASE_URL / REDIS_URL / MINIO_ENDPOINT 以验证外部服务连通性 |
| 数据备份恢复（QUAL-05） | 间接消费 | 备份策略参数（频率、保留天数）来自环境配置 |

> 精确的函数签名、类名、Cypher 查询模板见落地规范。本模块作为 L2 共享能力层公共包，可被任意上层模块引用，不形成循环依赖（项目结构 §5.3 第 5 条：`py-config` 为公共层，无反向依赖）。

### 1.4 状态机设计（技术实现策略）

本功能点不涉及状态流转，故无需状态机。意图文档 §1.7 已确认：配置管理为服务启动阶段一次性完成加载与校验的纯计算函数，不存在运行时的状态变化。

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| §三.1 | 厚 package、薄 app | 环境配置逻辑全部集中在 `packages/py-config/` 内（`config.py` + `exceptions.py`），app 端仅通过 `from py_config import get_settings` 获取配置实例。未来新增 worker 时无需复制配置代码，直接 import 即可。 |
| §三.2 | 单向依赖 | `py-config` 位于 L2 共享能力层，本身无业务依赖。下游模块通过统一入口 `get_settings()` 获取配置，不反向依赖任何 app。项目结构 §5.3 明确 py-config 为"可被任意层引用"的公共层。 |
| §三.5 | 最小化可工作 | 不预装 KMS SDK 依赖——生产环境密钥通过部署脚本在容器启动时从 KMS 解密后注入环境变量，py-config 仅从环境变量读取（与普通 `.env` 加载路径完全相同）。不实现热重载——MVP 阶段遵从意图文档"变更后需重启"的原则。不引入文件监听库（watchfiles）或信号处理机制。 |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 配置加载框架 | pydantic-settings BaseSettings | 手写 `os.environ` + if-else 校验 | pydantic-settings 内置类型校验（`PostgresDsn`、`RedisDsn` 等），将 14 项字段的格式校验从手写代码转为声明式类型注解，代码量减少约 60%。Pydantic 的 `ValidationError` 天然支持一次收集全部错误字段，满足 AC-01 的"多项缺失一次性列出"要求。 |
| 密钥内存保护 | `pydantic.SecretStr`（脱敏 repr + 显式获取） | 自定义加密类（Fernet/AES 内存加密） | `SecretStr` 是 Python 标准级解决方案，零额外依赖，在 `repr()`/`str()` 输出时自动脱敏为 `'**********'`。MVP 阶段云服务器进程内存攻击面极小，引入内存加密的密钥管理（加密密钥本身也需要保护）会形成密钥递归问题，ROI 低。后续若安全合规要求提升，可替换 `get_secret_value()` 内部实现为 KMS 实时解密而不影响调用方。 |
| 启动策略 | fail-fast 校验失败立即 `sys.exit(1)` | 降级启动（警告后继续运行） | 意图文档 §1.11 业务约束 3 明确要求"任何必填配置项缺失或格式不合法均须阻断启动，不得以降级模式运行"。带病运行会增加事故排查成本。 |
| 多环境配置管理 | 单 `AppSettings` 类 + Docker Compose `env_file` 多文件切换 | (A) 单个 .env + CI/CD 变量替换；(B) pydantic-settings 嵌套多环境类 | 方案 (C) Docker Compose `env_file` 与项目已有的 DEPLOY-01 容器编排模块完全契合——`docker-compose.yml` 各服务的 `env_file` 指令直接指定 `.env.dev` / `.env.prod`，py-config 无需感知环境切换逻辑，真正做到"代码零修改"。方案 (B) 需要 py-config 类层级里维护多环境差异，增加维护成本。 |
| 生产密钥管理 | 部署脚本在容器启动时从 KMS 解密后注入环境变量 | 在 py-config 中引入 KMS SDK（如 `aliyun-sdk-kms`）直接调用解密 | 零 KMS SDK 依赖——py-config 仅从环境变量读取（与开发/测试环境完全一致）。KMS 解密由部署层的初始化脚本处理，密钥不落盘但环境变量中为明文（容器内隔离空间，攻击面可控）。后续如需增强安全（env 变量中也不存明文），可在 py-config 中增加 KMS 适配层而不必改动部署流程。受技术预研报告建议方案约束。 |
| 配置热重载 | MVP 不实现，维持"变更后重启" | 引入 `watchfiles` 库监听 `.env` 文件变更并自动重载 | 意图文档明确"当前设计为启动时一次性加载，变更后需重启"。热重载涉及 10+ 配置项的变更检测、原子性替换、9 个下游模块的引用刷新问题，技术复杂度远大于收益。pydantic-settings 不原生支持热重载，需自建文件监听 + 信号处理机制。MVP 阶段遵从未做能力的推断。受技术预研报告建议方案约束。 |
| 异常层级设计 | 三级层次：`ConfigError → MissingRequiredFieldError / ConfigFormatError` + `ConfigWarning` | 单一 `ConfigError` 笼统报错 | 意图文档 §1.8 定义的三种异常场景（缺失、格式错误、生产密钥泄露警告）需要三种不同的技术响应——前两者阻断启动，后者仅警告。三级层次精确对应三种语义，避免所有错误被同一异常类捕获导致场景混乱。 |

### 1.7 注意事项与禁止行为（设计层面）

1. **[约束：启动顺序]** py-config 必须在所有其他模块（数据库、缓存、LLM、对象存储）之前完成初始化。FastAPI lifespan startup 阶段中，`get_settings()` 必须是第一行代码。这是 L1 基础层模块的基本约束。

2. **[约束：环境变量命名]** pydantic-settings 默认按 `model_fields` 的字段名匹配环境变量（区分大小写）。`ENVIRONMENT` 字段名与 `ENV` / `APP_ENV` 等常见命名不同——需在 `.env.example` 中明确标注此项。若后续需要前缀（如 `CAMPFIRE_`），应在 `BaseSettings.model_config` 中设置 `{"env_prefix": "CAMPFIRE_"}`。

3. **[易错点：SecretStr 传递]** `SecretStr` 对象不可直接用于构造数据库连接串中的密码字段（如 `f"postgresql://user:{settings.DB_PASSWORD}@host/db"`）。必须显式调用 `.get_secret_value()` 获取明文。建议在 py-config 中提供 `DATABASE_URL.get_secret_value()` 的便捷属性或 helper 函数。

4. **[易错点：Docker 环境变量覆盖]** Docker Compose 通过 `environment` 指令注入的环境变量会覆盖 `.env` 文件中的同名变量，且 pydantic-settings 默认环境变量优先于 `.env` 文件。如果开发者在 `docker-compose.yml` 和 `.env` 中同时定义了同一字段，以 `docker-compose.yml` 为准。需在 `.env.example` 中注明此行为。

5. **[设计边界]** 本模块仅负责配置的加载、校验与分发。不负责：(a) 配置值的业务语义校验（如限流阈值 30 次/分钟是否合理——由各消费模块自行判断）；(b) 密钥的生成（密钥由运维团队在 KMS 控制台创建）；(c) 配置变更后的热重载（变更需重启服务生效）；(d) 配置的远程管理或审计日志。

6. **[禁止行为]** 禁止在 py-config 之外的模块中直接调用 `os.getenv()` 或 `os.environ` 读取配置——所有环境变量读取必须通过 `get_settings()` 统一入口。禁止在日志中直接打印 Settings 对象的完整内容（即便 `SecretStr` 已脱敏——仍应避免将非密钥配置值泄漏到非结构化日志中）。

### 1.8 引用：配套意图文档

- **意图文档**：`DEPLOY-05-环境配置管理-意图文档.md`
- **冻结时间**：2026-05-26 16:54:49
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。所有 14 项配置字段均直接映射到 pydantic-settings 的类型注解，三种异常场景均通过异常层级设计精确对应，启动阻断策略严格满足 AC-01、AC-02 验收标准。多环境管理、KMS 集成、热重载策略、默认值等项均基于技术预研报告 (2026-05-26 17:00) 的建议方案推断，以意图文档的业务约束为最高优先级。如有歧义，以意图文档为准。
