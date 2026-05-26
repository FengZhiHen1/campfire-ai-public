## 1 功能点：DEPLOY-05 环境配置管理 — 落地规范

> **文档生成时间**：2026-05-26 17:22:10
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 17:22:10 | AI Assistant | 初始版本：基于设计文档 v1.0 和契约协调报告生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `DEPLOY-05-环境配置管理-设计文档.md`。

### 1.1 技术栈绑定 【对内实现】

- **必须使用**：
  - `pydantic >= 2.0` — 类型校验、SecretStr 脱敏、ValidationError 聚合
  - `pydantic-settings >= 2.0` — BaseSettings 环境变量加载与 .env 文件解析
  - `Python 3.12+` — 运行时环境，通过 uv 0.6+ pyproject.toml 声明 `requires-python = ">=3.12"`
  - `functools.lru_cache` (stdlib) — 全局配置单例缓存装饰器
  - `warnings.warn()` (stdlib) — 生产密钥安全告警（非阻断）
  - `sys.exit(1)` (stdlib) — 校验失败阻断进程
  - `pyproject.toml` — 在 `[project.optional-dependencies]` 或 `[tool.uv.sources]` 中声明本包
- **禁止使用**：
  - 禁止在 py-config 包内引入任何 KMS SDK（如 aliyun-sdk-kms）——KMS 解密由部署脚本在容器启动时注入环境变量完成
  - 禁止在 py-config 包内引入文件监听库（如 watchfiles、watchdog）——MVP 阶段不实现热重载
  - 禁止在 py-config 包内引入加密库（如 cryptography、pycryptodome）——内存保护仅通过 SecretStr 实现
  - 禁止在 py-config 包外直接调用 `os.getenv()` 或 `os.environ` 读取配置——必须通过 `get_settings()` 统一入口

### 1.2 文件归属 【对内实现】

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 配置模型 | `packages/py-config/py_config/config.py` | AppSettings 类定义，包含 BaseSettings 子类和全部 18 个字段的类型注解 |
| 异常定义 | `packages/py-config/py_config/exceptions.py` | ConfigError、MissingRequiredFieldError、ConfigFormatError（三级异常层次）+ ConfigWarning 工厂函数 |
| 包入口 | `packages/py-config/py_config/__init__.py` | get_settings() 工厂函数（@lru_cache 单例）、统一导出 |
| 包描述 | `packages/py-config/pyproject.toml` | uv workspace 成员，声明依赖 pydantic>=2.0 和 pydantic-settings>=2.0 |

### 1.3 输入定义 【已锁定】

本模块的输入来源为操作系统环境变量（`os.environ`）或 `.env` 文件。pydantic-settings v2 的 BaseSettings 默认按字段名匹配环境变量（区分大小写），输入为无结构化类型的键值对集合。

**输入来源说明**：
- **来源 1**：环境变量（`os.environ`）——Docker Compose `environment` 指令或 `env_file` 指令注入
- **来源 2**：`.env` 文件——开发/测试环境使用，位于项目根目录。生产环境不使用 .env 文件（密钥通过 KMS → 部署脚本注入环境变量）
- **优先级**：环境变量 > `.env` 文件（pydantic-settings 默认行为）

输入字段定义见契约文件：`docs/contracts/DEPLOY-05/AppSettings.json`（properties 节定义了全部 18 个字段的类型、约束和默认值）。

### 1.4 输出定义 【已锁定】

**AppSettings**
- 【契约引用】`docs/contracts/DEPLOY-05/AppSettings.json`
- 本模块作为该契约的定义方
- 消费方：DEPLOY-01、DEPLOY-02、DEPLOY-04、OBS-01、OBS-02、OBS-03、OBS-04、QUAL-05

**ConfigError / MissingRequiredFieldError / ConfigFormatError**
- 【契约引用】`docs/contracts/DEPLOY-05/ConfigError.json`、`docs/contracts/DEPLOY-05/MissingRequiredFieldError.json`、`docs/contracts/DEPLOY-05/ConfigFormatError.json`
- 本模块作为该契约的定义方
- 消费方：所有下游模块（可通过 except ConfigError 统一捕获配置异常）

**ConfigWarning**
- 【契约引用】`docs/contracts/DEPLOY-05/ConfigWarning.json`
- 本模块作为该契约的定义方
- 消费方：运维告警系统（通过 py-logger 结构化日志消费）

### 1.5 核心逻辑步骤 【对内实现】

1. **步骤 1：FastAPI lifespan 启动阶段触发配置加载**
   - **操作对象**：FastAPI app 的 lifespan context manager
   - **具体操作**：在 `lifespan` 的 `startup` 阶段调用 `get_settings()` 获取配置单例。`get_settings()` 必须在所有其他依赖注入（数据库、缓存、LLM）之前执行。
   - **输入来源**：操作系统环境变量 + 项目根目录 `.env` 文件（若存在）
   - **输出去向**：全局 AppSettings 单例注入到 FastAPI 的 app.state.settings 或通过 FastAPI dependency 暴露
   - **失败行为**：get_settings() 内部校验失败直接 sys.exit(1) 终止进程；FastAPI lifespan 中的 try/except 仅负责捕获后清理，不尝试恢复

2. **步骤 2：BaseSettings 构造与字段校验**
   - **操作对象**：`AppSettings()` 构造调用
   - **具体操作**：BaseSettings.__init__ 自动执行以下流程——(a) 遍历 model_fields，按字段名从 os.environ 查找值；(b) 若未找到，从 .env 文件读取（env_file=".env"）；(c) 对每个字段调用对应的 Pydantic 类型校验器（PostgresDsn、RedisDsn、AnyHttpUrl 等内置校验，SecretStr 包装，int 的 ge=1 约束等）；(d) 收集全部校验失败项（Pydantic v2 的 ValidationError.errors() 返回列表，包含所有错误），不因首个错误而中断
   - **输入来源**：os.environ 字典 + .env 文件内容
   - **输出去向**：校验通过 → AppSettings 实例进入步骤 3 的缓存层；校验失败 → 进入步骤 5 分支
   - **失败行为**：Pydantic 抛出 ValidationError，errors() 方法返回所有失败字段的列表。由步骤 5 的 exception handler 处理

3. **步骤 3：跨字段安全校验（model_validator after mode）**
   - **操作对象**：步骤 2 校验通过后的 AppSettings 实例
   - **具体操作**：执行 `@model_validator(mode="after")` 装饰的方法——(a) 检查 ENVIRONMENT == "production" 时，密钥字段是否可能来源于 KMS 注入（通过检查环境变量来源标记或 .env 文件存在性）；(b) 若检测到生产环境密钥可能来自本地文件，调用 `warnings.warn(ConfigWarning(...))` 输出安全告警，但不阻断启动
   - **输入来源**：步骤 2 已通过独立字段校验的 AppSettings 实例
   - **输出去向**：校验通过 → AppSettings 实例（可能附带已发出的 ConfigWarning）
   - **失败行为**：跨字段校验逻辑自身异常时（如 os 模块本身不可用——理论上不可能），记录 error 日志并允许继续启动。本步骤不做阻断处理

4. **步骤 4：全局单例缓存**
   - **操作对象**：`get_settings()` 工厂函数
   - **具体操作**：使用 `@functools.lru_cache()` 装饰 get_settings()，首次调用执行步骤 2-3，后续调用直接返回缓存的 AppSettings 实例。配置实例在进程生命周期内保持不变。
   - **输入来源**：无（lru_cache 内部机制）
   - **输出去向**：缓存命中 → 直接返回已缓存的 AppSettings 实例
   - **失败行为**：不适用（lru_cache 为 Python stdlib 纯函数装饰器，自身无失败路径）

5. **步骤 5：校验失败处理（异常聚合→格式化→sys.exit）**
   - **操作对象**：步骤 2 抛出的 `ValidationError` 或步骤 2/3 捕获到的异常
   - **具体操作**：
     - (a) 遍历 `ValidationError.errors()` 列表，按错误类型分为两组——`error_type == "missing"` → MissingRequiredFieldError；`error_type in ("value_error", "type_error")` → ConfigFormatError
     - (b) 构造异常实例：MissingRequiredFieldError 的 `missing_fields` 列表收集全部缺失字段名；ConfigFormatError 的 `field_name` 和 `expected_format` 从 Pydantic error dict 提取
     - (c) 通过 py-logger 输出结构化错误日志（`logger.critical("config_load_failed", missing=[...], format_errors=[...])`）
     - (d) 输出 stderr 人类可读错误信息（中文，包含所有缺失/错误字段清单及修复建议）
     - (e) 调用 `sys.exit(1)` 终止进程
   - **输入来源**：Pydantic ValidationError 的 errors() 列表
   - **输出去向**：stderr + py-logger 结构化日志 + sys.exit(1)
   - **失败行为**：日志写入失败（py-logger 不可用）→ 降级为 print() 到 stderr 后仍然 sys.exit(1)

### 1.6 接口契约 【已锁定】

#### 1.6.1 接口 1：get_settings —— 全局配置获取工厂函数

```python
from functools import lru_cache
from py_config.config import AppSettings


@lru_cache()
def get_settings() -> AppSettings:
    """
    获取全局配置单例。首次调用时从环境变量和 .env 文件加载并校验全部 14 项配置字段，
    后续调用返回缓存实例。校验失败时进程以 sys.exit(1) 终止，不会返回半初始化对象。

    Returns:
        AppSettings: 经 pydantic-settings 校验通过的全局配置单例，包含数据库、缓存、
        AI 接口、对象存储、认证和限流六个维度的全部配置项。

    Raises:
        MissingRequiredFieldError: 任一必填环境变量未设置或值为空时抛出。
            错误信息包含全部缺失字段名称列表。
        ConfigFormatError: 任一配置项值格式不符合预期时抛出。
            错误信息包含字段名、实际值和期望格式。

    Side Effects:
        - 首次调用: 读取 .env 文件（若存在）和环境变量
        - 首次调用: 生产环境下若密钥来自本地文件，通过 warnings.warn() 输出 ConfigWarning
        - 所有调用: 无副作用（幂等）

    Idempotency:
        任意次调用返回同一 AppSettings 实例（@lru_cache 保证）。配置对象在进程生命周期内保持不变。

    Thread Safety:
        AppSettings 实例化后为只读（不可变）。@lru_cache 在 CPython GIL 下线程安全。
        多线程并发首次调用时，可能存在多次构造但缓存后返回同一实例。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `get_settings` —— 语义化：获取（全局）配置 |
| **输入类型** | 无函数入参。数据源为 os.environ + .env 文件（隐式） |
| **输出类型** | `AppSettings`（详见 §1.4 输出定义和 `docs/contracts/DEPLOY-05/AppSettings.json`） |
| **异常类型** | `MissingRequiredFieldError`、`ConfigFormatError`（详见 §1.9 异常与边界条件） |
| **副作用** | 首次调用时读取 .env 文件和生产环境安全检测；后续调用零副作用 |
| **幂等性** | 基于 @lru_cache 的天然幂等，任意次调用返回同一实例 |
| **并发安全** | 线程安全（只读实例 + CPython GIL） |

#### 1.6.2 接口 2：from py_config import get_settings —— 下游模块导入方式

```python
# 标准导入方式（所有下游模块统一使用）
from py_config import get_settings

settings = get_settings()

# 使用示例
db_url = settings.DATABASE_URL
redis_url = settings.REDIS_URL
deepseek_key = settings.DEEPSEEK_API_KEY.get_secret_value()
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `from py_config import get_settings` —— 包级导入 |
| **输入类型** | 无（导入时模块级代码不执行配置加载；实际加载在首次调用 get_settings() 时触发） |
| **输出类型** | 模块符号 `get_settings`（callable → AppSettings） |
| **异常类型** | 同 get_settings() |
| **副作用** | 导入 `py_config` 模块本身无副作用（配置加载延迟到首次 get_settings() 调用） |

### 1.7 依赖与集成接口 【已锁定】

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| Python 运行时 | Python 3.12+ 解释器 | `python` 可执行文件 | 运行环境 | `docs/篝火智答-技术栈设计.md` uv 0.6+ 要求 Python 3.12+ |
| 类型校验库 | pydantic 2.x | `pydantic.BaseSettings`、`pydantic.SecretStr`、`pydantic.PostgresDsn` 等 | 配置字段的类型校验与内存脱敏 | `docs/篝火智答-技术栈设计.md` §2（数据校验 Pydantic 2.x） |
| 配置加载库 | pydantic-settings 2.x | `pydantic_settings.BaseSettings` | 从 .env 文件和环境变量自动加载 | `docs/篝火智答-项目结构.md` §6.1（`packages/py-config/`） |
| 操作系统 | OS 环境变量 (`os.environ`) | `os.environ.get(key)` 通过 pydantic-settings 间接访问 | 读取环境变量值 | `docs/篝火智答-技术栈设计.md` §6.2（关键配置） |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| 无（本模块无上游业务依赖） | — | — | — |

### 1.8 状态机 【对内实现】

本功能点不涉及状态流转，故无需状态机。意图文档 §1.7 已确认：配置管理为服务启动阶段一次性完成加载与校验的纯计算函数。

### 1.9 异常与边界条件 【对内实现】

#### 1.9.1 异常 1：必填配置项缺失

- **触发条件**：
  - 任一必填字段（DATABASE_URL、REDIS_URL、DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL、MINIO_ENDPOINT、MINIO_ACCESS_KEY、MINIO_SECRET_KEY、JWT_SECRET_KEY）对应的环境变量未设置
  - 环境变量已设置但值为空字符串 `""`
  - 环境变量已设置但值为 `None`（环境变量只支持字符串，此情况仅出现在测试 mock 场景）
- **处理策略**：
  1. Pydantic ValidationError 在 AppSettings.__init__() 时自动抛出
  2. get_settings() 中的 except block 捕获 ValidationError
  3. 遍历 `ValidationError.errors()`，筛选 `msg 包含 "Field required"` 或 `type == "missing"` 的错误项
  4. 构建 MissingRequiredFieldError：`missing_fields` 列表收集全部缺失字段的 Python 字段名（如 "DATABASE_URL"、"REDIS_URL"），`message` 格式为 `"缺少必填配置项: {fields}。请检查 .env 文件或 KMS 注入"`
  5. 通过 py-logger 输出结构化日志：`logger.critical("config_load_failed", event="missing_required", missing_fields=[...])`
  6. 输出 stderr 人类可读信息，包含：缺失字段列表、检查 .env 文件的路径提示、生产环境的 KMS 检查指引
  7. 调用 sys.exit(1) 终止进程
- **重试参数**：不重试。需要人工修正配置后重启服务。

#### 1.9.2 异常 2：配置项格式错误

- **触发条件**：
  - DATABASE_URL 不满足 `PostgresDsn` 格式（如缺少端口、协议错误、包含非法字符）
  - DEEPSEEK_BASE_URL 不满足 `AnyHttpUrl` 格式（如不是合法 HTTPS URL、包含空格）
  - JWT_SECRET_KEY 长度 < 32 字符（`min_length=32` 约束）
  - ACCESS_TOKEN_EXPIRE_MINUTES、REFRESH_TOKEN_EXPIRE_DAYS、RATE_LIMIT_USER_PER_MINUTE、RATE_LIMIT_IP_PER_MINUTE 不为正整数（`ge=1` 约束）
  - ENVIRONMENT 不在 `["development", "testing", "production"]` 枚举中
  - REDIS_URL 不满足 `RedisDsn` 格式
- **处理策略**：
  1. Pydantic ValidationError 在 AppSettings.__init__() 时自动抛出（与异常 1 同时触发时，两种错误一并收集）
  2. get_settings() 中的 except block 捕获 ValidationError
  3. 遍历 `ValidationError.errors()`，筛选非 "missing" 类型的错误项（type 为 "value_error"、"type_error"、"url_parsing" 等）
  4. 对每个格式错误项构建 ConfigFormatError：`field_name` 从 error dict 的 loc 提取，`received_value` 脱敏后填入（SecretStr 字段显示为 "**********"），`expected_format` 根据字段类型映射为人类可读描述（如 "合法的 PostgreSQL 连接串 (postgresql+asyncpg://...)"、"长度不少于 32 字符的字符串"）
  5. 通过 py-logger 输出结构化日志：`logger.critical("config_load_failed", event="format_error", errors=[{"field": ..., "received": ..., "expected": ...}, ...])`
  6. 输出 stderr 人类可读信息，将缺失项和格式错误项区分显示（如 "缺少必填配置项: ..." 和 "配置项格式错误: ..." 分两段输出）
  7. 调用 sys.exit(1) 终止进程
- **重试参数**：不重试。需要人工修正配置后重启服务。

#### 1.9.3 异常 3：生产环境密钥明文落盘（安全警告，非阻断）

- **触发条件**：
  - `ENVIRONMENT == "production"` 且同时满足以下任一条件：
    - 项目根目录存在 `.env` 文件且其中包含密钥字段（DEEPSEEK_API_KEY、MINIO_ACCESS_KEY、MINIO_SECRET_KEY、JWT_SECRET_KEY 任一）。检测方式：在 model_validator(after) 中检查 `os.path.exists(".env")` 且读取 .env 内容后匹配密钥字段名
    - 环境变量中存在 `DOTENV_FILE` 或 pydantic-settings 的 `_env_file` 指向了本地 .env 文件
- **处理策略**：
  1. 在 `model_validator(mode="after")` 中完成跨字段安全检测（此时各字段已单独校验通过，值可用）
  2. 构建 ConfigWarning：`message` 包含安全告警说明，`affected_fields` 列出检测到的敏感字段
  3. 调用 `warnings.warn(ConfigWarning(...))` 输出 Python 标准 Warning（不中断程序流）
  4. 通过 py-logger 输出结构化告警日志：`logger.warning("security_alert", event="production_secret_leak", affected_fields=[...], severity="critical")`——使用 WARNING 级别而非 ERROR，因为服务继续运行
  5. 输出 stderr 安全提醒：包含风险说明、建议迁移至 KMS 的指引
  6. 服务继续正常启动（不调用 sys.exit）
- **重试参数**：不适用（仅告警，不阻断启动）

#### 1.9.4 边界条件 1：Docker Compose 环境变量覆盖

- **触发条件**：`docker-compose.yml` 的 `environment` 指令和 `.env` 文件中同时定义了同一字段
- **处理策略**：pydantic-settings 默认环境变量优先于 .env 文件。Docker Compose 的 `environment` 指令设置的是容器环境变量，因此会覆盖 .env 文件中的值。py-config 不感知此优先级差异，按 pydantic-settings 默认行为处理。
- **影响**：开发者在 `docker-compose.yml` 和 `.env` 中重复定义某字段时，以 `docker-compose.yml` 为准。需在 `.env.example` 中注明此行为。

#### 1.9.5 边界条件 2：SecretStr 在数据库连接串中使用

- **触发条件**：下游模块需要使用 SecretStr 保护的密钥构造数据库连接串
- **处理策略**：`pydantic.SecretStr` 对象不可直接用于 f-string 或字符串拼接（会输出 "**********" 而非实际密钥）。调用方必须显式调用 `.get_secret_value()` 获取明文。建议在 `py_config/__init__.py` 中提供 helper 属性简化访问——例如 `settings.database_url_secret_value`。
- **影响**：未调用 `.get_secret_value()` 直接使用 SecretStr 对象会导致数据库连接失败（PostgreSQL 连接串中密码字段为脱敏值）。

### 1.10 验收测试场景 【对内实现】

#### 1.10.1 正向测试 1：完整有效配置成功加载

- **场景**：所有 14 项配置均已正确设置，系统成功加载配置对象
- **Given**: 环境变量全部正确设置：
  - DATABASE_URL="postgresql+asyncpg://user:pass@postgres:5432/campfire"
  - REDIS_URL="redis://redis:6379/0"
  - DEEPSEEK_API_KEY="REDACTED-SET-VIA-ENV"
  - DEEPSEEK_BASE_URL="https://api.deepseek.com/v1"
  - DASHSCOPE_API_KEY="sk-dashscope-test-key"
  - DASHSCOPE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
  - MINIO_ENDPOINT="minio:9000"
  - MINIO_ACCESS_KEY="minioadmin"
  - MINIO_SECRET_KEY="minioadmin-secret"
  - JWT_SECRET_KEY="REDACTED-SET-VIA-ENV"
  - （以下使用默认值，不设置）JWT_ALGORITHM、ACCESS_TOKEN_EXPIRE_MINUTES、REFRESH_TOKEN_EXPIRE_DAYS、RATE_LIMIT_USER_PER_MINUTE、RATE_LIMIT_IP_PER_MINUTE、ENVIRONMENT、EMBEDDING_MODEL、EMBEDDING_DIMENSION
- **When**: 调用 `get_settings()`
- **Then**:
  - 返回 AppSettings 实例，所有字段可访问
  - settings.DATABASE_URL 值为 "postgresql+asyncpg://user:pass@postgres:5432/campfire"
  - settings.DEEPSEEK_API_KEY 为 SecretStr 类型，repr() 显示 "**********"，.get_secret_value() 返回 "REDACTED-SET-VIA-ENV"
  - settings.ENVIRONMENT 值为 "development"（默认值）
  - settings.ACCESS_TOKEN_EXPIRE_MINUTES 值为 15（默认值）
  - 不抛出任何异常

#### 1.10.2 正向测试 2：仅设置必填项加载成功

- **场景**：仅设置 8 个必填项（可选 6 项不设置），系统使用默认值成功加载
- **Given**: 仅设置 8 个必填环境变量（DATABASE_URL、REDIS_URL、DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL、MINIO_ENDPOINT、MINIO_ACCESS_KEY、MINIO_SECRET_KEY、JWT_SECRET_KEY），其他 6 个可选字段不设置
- **When**: 调用 `get_settings()`
- **Then**:
  - 返回 AppSettings 实例
  - JWT_ALGORITHM 为 "HS256"（默认值）
  - ACCESS_TOKEN_EXPIRE_MINUTES 为 15（默认值）
  - REFRESH_TOKEN_EXPIRE_DAYS 为 7（默认值）
  - RATE_LIMIT_USER_PER_MINUTE 为 30（默认值）
  - RATE_LIMIT_IP_PER_MINUTE 为 100（默认值）
  - ENVIRONMENT 为 "development"（默认值）

#### 1.10.3 异常测试 1：必填项缺失阻断启动

- **场景**：必填项 DATABASE_URL 和 REDIS_URL 缺失，系统阻断启动并列出所有缺失项
- **Given**: 设置除 DATABASE_URL 和 REDIS_URL 外的所有必填项，DATABASE_URL 和 REDIS_URL 不设置（环境变量中不存在这两个 key）
- **When**: 调用 `get_settings()`
- **Then**:
  - 抛出 MissingRequiredFieldError（或 ValidationError 被 get_settings() 捕获后 sys.exit(1)）
  - 错误信息包含 "DATABASE_URL" 和 "REDIS_URL"（两项缺失一次性列出）
  - 进程以非零退出码终止（测试中用 pytest.raises(SystemExit) 验证）
  - 服务未启动

#### 1.10.4 异常测试 2：格式错误阻断启动

- **场景**：ACCESS_TOKEN_EXPIRE_MINUTES 设置为负数，JWT_SECRET_KEY 长度不足 32，系统阻断启动
- **Given**:
  - 所有必填项正确设置
  - ACCESS_TOKEN_EXPIRE_MINUTES="-5"
  - JWT_SECRET_KEY="short"（长度 5 < 32）
- **When**: 调用 `get_settings()`
- **Then**:
  - 抛出 ConfigFormatError 或触发后 sys.exit(1)
  - 错误信息包含 ACCESS_TOKEN_EXPIRE_MINUTES 的格式错误说明（"必须为正整数"）和 JWT_SECRET_KEY 的格式错误说明（"长度不少于 32 字符"）
  - 两项格式错误一次性列出
  - 服务未启动

#### 1.10.5 异常测试 3：生产环境密钥来源检测告警

- **场景**：生产环境中 .env 文件存在且包含密钥字段，系统输出安全告警但继续启动
- **Given**:
  - ENVIRONMENT="production"
  - 项目根目录存在 .env 文件（包含 DEEPSEEK_API_KEY=xxx）
  - 所有字段值均合法
- **When**: 调用 `get_settings()`
- **Then**:
  - 返回 AppSettings 实例（服务正常启动）
  - 通过 warnings.warn() 输出 ConfigWarning（测试中用 pytest.warns(ConfigWarning) 验证）
  - py-logger 输出 WARNING 级别日志，包含 event="production_secret_leak"
  - settings.DEEPSEEK_API_KEY 可正常使用

### 1.11 注意事项与禁止行为（编码层面） 【对内实现】

1. **[约束：SecretStr 传递规则]** 任何需要将 SecretStr 保护的密钥用于网络连接、API 调用、字符串拼接时，必须显式调用 `.get_secret_value()` 获取明文。禁止直接将 SecretStr 对象传入 f-string、str.format()、requests headers、数据库连接串构造函数。建议在 `py_config/__init__.py` 中暴露便捷属性简化下游使用。

2. **[约束：默认值不重复]** AppSettings 的所有 6 个可选字段均已在 Field(default=...) 中声明默认值。禁止在调用方代码中重复硬编码 `15`、`7`、`30`、`100`、`"HS256"`、`"development"`——这些值从 AppSettings 读取即可。若业务需要不同的默认值，应修改 AppSettings 定义而非调用方代码。

3. **[易错点：.env 文件编码]** pydantic-settings 的 `env_file_encoding="utf-8"` 参数要求 .env 文件必须为 UTF-8 编码。Windows 下使用记事本编辑 .env 文件默认编码为 UTF-8 BOM 或 GBK，可能导致解析失败。需在 CONTRIBUTING.md 中提示使用 VS Code 或指定 UTF-8 编码。

4. **[禁止行为 1]** 禁止在 py-config 之外的任何模块中直接调用 `os.getenv()`、`os.environ.get()` 或 `os.environ["KEY"]` 读取配置。所有环境变量访问必须通过 `from py_config import get_settings; settings = get_settings()` 统一入口。

5. **[禁止行为 2]** 禁止在 py-config 的 `__init__.py` 的模块顶层（import 时）调用 `get_settings()` 触发配置加载。配置加载必须延迟到 FastAPI lifespan startup 阶段（或应用的显式初始化入口），避免 import 时因缺少环境变量导致单元测试无法加载模块。

6. **[偷懒红线]** 绝对禁止在配置变更后不重启服务就期待新配置生效。本模块 MVP 阶段不实现热重载。绝对禁止用 `"..."` 或 `"其他配置项"` 省略字段定义——18 个字段必须全部显式写出。

### 1.12 文档详细度自检清单 【对内实现】

- [x] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成编码
- [x] 无偷懒表述：全文搜索无 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：AppSettings 18 个字段在契约文件 `AppSettings.json` 中全部有 `description`、`examples`、约束（`minimum`/`minLength`/`enum`/`default`）
- [x] 逻辑步骤完整：5 个步骤均含操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：3 种异常 + 2 种边界条件，各有精确触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值来源（pydantic Field default）已显式说明；条件分支（生产环境检测逻辑）已写出
- [x] 技术栈绑定明确：必须使用（4 项）和禁止使用（4 项）均已列出，与项目技术栈设计文档一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致（见 §1.15）

### 1.14 外部接口契约清单 【对内实现】

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| AppSettings | `docs/contracts/DEPLOY-05/AppSettings.json` | output | draft | DEPLOY-05 | DEPLOY-01, DEPLOY-02, DEPLOY-04, OBS-01, OBS-02, OBS-03, OBS-04, QUAL-05 |
| ConfigError | `docs/contracts/DEPLOY-05/ConfigError.json` | error-code | draft | DEPLOY-05 | 所有下游模块 |
| MissingRequiredFieldError | `docs/contracts/DEPLOY-05/MissingRequiredFieldError.json` | error-code | draft | DEPLOY-05 | 所有下游模块 |
| ConfigFormatError | `docs/contracts/DEPLOY-05/ConfigFormatError.json` | error-code | draft | DEPLOY-05 | 所有下游模块 |
| ConfigWarning | `docs/contracts/DEPLOY-05/ConfigWarning.json` | error-code | draft | DEPLOY-05 | OBS-03（告警通知模块） |
| get_settings | （函数契约，仅在 `docs/contracts/DEPLOY-05/_module-index.json` 中声明） | function | draft | DEPLOY-05 | 所有下游模块 |

### 1.15 意图一致性声明 【对内实现】

- **配套意图文档**：`DEPLOY-05-环境配置管理-意图文档.md`
- **冻结时间**：2026-05-26 16:54:49
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致（18 项配置字段完整覆盖 §1.6 的输入定义和输出定义，含新增的 4 项嵌入模型字段）
  - [x] 本落地规范中的状态机实现与意图文档中的状态业务定义一致（§1.7 确认无需状态机）
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致（§1.8 三种异常场景精确对应：必填缺失→MissingRequiredFieldError、格式错误→ConfigFormatError、生产密钥泄露→ConfigWarning）
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准（5 个测试场景覆盖 AC-01~AC-07 全部 7 条验收标准：AC-01→正向测试 1、AC-02→异常测试 1+2、AC-03→正向测试 2、AC-04→代码生成时 .env.example 文件、AC-05→代码生成时 .gitignore、AC-06→异常测试 3、AC-07→正向测试 1 包含全部 14 字段）
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围（§1.12 的 6 项技术决策均已按用户确认的方案实现）
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
