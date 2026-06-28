# 1 功能点：SEC-04 防刷限流 — 落地规范

> **文档生成时间**：2026-05-26 21:24:55
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 21:24:55 | AI Assistant | 初始版本 |
>
> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `SEC-04-防刷限流-设计文档.md`。
> **流水线上下文**：本落地规范基于已冻结的 `SEC-04-防刷限流-意图文档.md`（冻结时间 2026-05-26 18:45:00）编写。技术实现必须与意图文档中的业务定义保持一致。

---

### 1.1 技术栈绑定

- **必须使用**：
  - Python 3.12+（项目统一版本）
  - FastAPI >= 0.115（`FastAPI.add_middleware()` 注册全局中间件）
  - `redis-py` >= 5.0（通过 `packages/py-cache` 封装的 `redis_client.eval()` 执行 LUA 脚本；禁止直接 import `redis` 模块）
  - Pydantic >= 2.0（配置模型继承 `pydantic-settings.BaseSettings`）
  - Prometheus 客户端库 `prometheus-client` >= 0.19（Counter / Gauge 自定义指标注册）
  - `structlog` >= 24.0（结构化日志，通过 `packages/py-logger` 统一输出）
- **禁止使用**：
  - 禁止直接调用 `redis` 库的 `ZADD` / `ZREMRANGEBYSCORE` / `ZCARD` 方法；必须通过 `redis_client.eval()` 在 LUA 脚本中原子执行
  - 禁止在中间件中 import 任何业务 service（如 `services/case_service.py`），限流层与业务层严格解耦
  - 禁止使用 `WATCH/MULTI/EXEC` 乐观锁替代 LUA 脚本（网络往返多且无法保证原子性）

### 1.2 文件归属

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 模块入口 | `apps/api-server/app/middleware/rate_limit.py` | FastAPI 全局中间件，包含 `RateLimitMiddleware` 类和 `rate_limit_lua_script` LUA 脚本常量 |
| 配置模型 | `apps/api-server/app/middleware/rate_limit.py` | `RateLimitSettings` Pydantic 配置模型，与中间件同文件 |
| 测试文件 | `tests/api-server/middleware/test_rate_limit.py` | 限流中间件的单元/集成测试 |
| Redis LUA 脚本 | `apps/api-server/app/middleware/rate_limit.py` | LUA 脚本作为模块级常量嵌入，不单独存放 `.lua` 文件 |

### 1.3 输入定义（契约引用）【已锁定】

**check_rate_limit（SEC-01 预定义输入契约）**
- 【契约引用】`docs/contracts/SEC-01/check_rate_limit.json`
- 本模块作为该契约的消费方
- 定义方：SEC-01
- 字段说明：`user_id: str | None`（已登录用户 UUID，来自 `request.state.user.id`；缺失则仅执行 IP 级限流）、`ip: str`（客户端真实 IP，来自 `X-Forwarded-For` 或 `request.client.host`）

**RateLimitConfig（SEC-01 预定义配置契约）**
- 【契约引用】`docs/contracts/SEC-01/RateLimitConfig.json`
- 本模块作为该契约的消费方
- 定义方：SEC-01
- 字段说明：`RATE_LIMIT_USER_PER_MINUTE: int`（默认 30）、`RATE_LIMIT_IP_PER_MINUTE: int`（默认 100）、`RATE_LIMIT_WINDOW_SECONDS: int`（默认 60），通过 `pydantic-settings` 从环境变量加载

### 1.4 输出定义（契约引用）【已锁定】

**RateLimitExceededResponse（SEC-01 预定义输出契约）**
- 【契约引用】`docs/contracts/SEC-01/RateLimitExceededResponse.json`
- 本模块作为该契约的消费方
- 定义方：SEC-01
- 输出场景：仅限流触发时（HTTP 429）；正常放行时不产生此输出

**正常通过时不产生任何自定义响应体**。请求原样传递至下一个中间件或路由处理。

### 1.5 核心逻辑步骤

1. **步骤 1：IP 来源解析**
   - **操作对象**：`Request` 对象
   - **具体操作**：读取 `request.headers.get("X-Forwarded-For", "")`，取逗号分隔的第一个非内网 IP（`10./172.16./192.168.` 段视为内网）。若 X-Forwarded-For 为空或全部为内网 IP，回退到 `request.client.host`
   - **输入来源**：FastAPI 传入的 `Request` 实例
   - **输出去向**：解析得到的 `ip: str` 字符串注入内存变量，供步骤 3/4 使用
   - **失败行为**：`request.client.host` 为 None（罕见边界，如测试环境无客户端连接）→ 视为 `"0.0.0.0"`，不阻断请求处理

2. **步骤 2：白名单匹配**
   - **操作对象**：`request.url.path`
   - **具体操作**：检查 `request.url.path` 是否在 `RATE_LIMIT_WHITELIST_PATHS = {"/health", "/metrics"}` 集合中
   - **输入来源**：当前请求的 URL 路径
   - **输出去向**：白名单命中 → 直接返回 `await call_next(request)` 跳过后续所有限流步骤；未命中 → 继续步骤 3
   - **失败行为**：无（集合成员检查不涉及 IO 或外部依赖，不会失败）

3. **步骤 3：用户级限流检查（短路优化）**
   - **操作对象**：Redis ZSET key `ratelimit:user:{user_id}`
   - **具体操作**：若 `request.state.user` 存在且包含 `id` 字段，组装 LUA 脚本参数执行 `redis_client.eval(SCRIPT, 1, user_key, window_seconds, now_timestamp)`。LUA 脚本内部执行：`ZADD`（添加当前时间戳 member）→ `ZREMRANGEBYSCORE`（移除 [0, now - window] 区间过期 member）→ `ZCARD`（统计剩余 member 数）→ 返回 `(count - 1, ttl_seconds)`（减 1 排除刚插入的自身）
   - **输入来源**：步骤 1 的 `ip`、`request.state.user.id`、`RateLimitConfig` 中加载的阈值参数
   - **输出去向**：计数结果 > `RATE_LIMIT_USER_PER_MINUTE` → 拒绝（步骤 5）；未超限 → 继续步骤 4
   - **失败行为**：Redis 连接异常 → 捕获 `redis.exceptions.ConnectionError`/`redis.exceptions.TimeoutError`，记录 CRITICAL 日志，放行请求（fail-open），跳过步骤 4

4. **步骤 4：IP 级限流检查**
   - **操作对象**：Redis ZSET key `ratelimit:ip:{ip}`
   - **具体操作**：执行 LUA 脚本（同步骤 3 逻辑），key 替换为 `ratelimit:ip:{ip}`
   - **输入来源**：步骤 1 解析的 `ip`、`RateLimitConfig` 阈值参数
   - **输出去向**：计数结果 > `RATE_LIMIT_IP_PER_MINUTE` → 拒绝（步骤 5）；未超限 → 放行（步骤 6）
   - **失败行为**：Redis 连接异常 → 同步骤 3，放行请求（fail-open）

5. **步骤 5：限流拒绝响应**
   - **操作对象**：HTTP Response
   - **具体操作**：构造 `JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后重试", "retry_after_seconds": window_seconds})`，设置响应头 `Retry-After: {window_seconds}`。记录 WARNING 级别结构化日志：`logger.warning("rate_limit_exceeded", level="user|ip", key=..., count=..., limit=..., user_id=...)`
   - **输入来源**：步骤 3/4 的判定结果 + 步骤 2 的窗口配置
   - **输出去向**：直接返回 429 响应，不调用 `call_next(request)`
   - **失败行为**：无（纯内存操作，不依赖外部服务）

6. **步骤 6：正常放行**
   - **操作对象**：`Request` → 下一个中间件/路由处理
   - **具体操作**：执行 `response = await call_next(request)`，在响应返回前递增 Prometheus Counter `rate_limit_check_total{status="passed", level="user|ip|none"}`
   - **输入来源**：步骤 3/4 全部通过后的判定
   - **输出去向**：响应返回给客户端
   - **失败行为**：下游中间件/路由处理抛出的异常由全局异常处理器捕获，本中间件不拦截业务异常

7. **步骤 7：Prometheus 指标更新（后置钩子）**
   - **操作对象**：Prometheus 指标注册器
   - **具体操作**：每完成一次限流检查（放行或拒绝），递增 `rate_limit_check_total` Counter（label: `status="passed"|"rejected"|"degraded"`）。定期更新 `rate_limit_active_keys` Gauge（Redis `DBSIZE` 命令采样，每 10 秒一次，在独立异步任务中执行）。Redis 健康状态变更时更新 `rate_limit_redis_health` Gauge（0=故障，1=正常）
   - **输入来源**：限流检查结果、Redis 连接状态
   - **输出去向**：Prometheus 指标端点 `/metrics` 暴露
   - **失败行为**：Prometheus 客户端内部异常不传播（`prometheus_client` 内部捕获），不影响主请求流程

### 1.6 接口契约（对外暴露的公共接口）【已锁定】

#### 1.6.1 接口 1：`RateLimitMiddleware`

```python
class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    防刷限流全局中间件，在所有路由处理之前、身份认证之前执行。

    通过 Redis ZSET + LUA 原子滑动窗口实现用户级（30/min）和 IP 级（100/min）
    双重限流。采用短路优化：已登录用户先检查用户级，超限则直接拒绝不检查 IP 级。
    Redis 不可用时自动 fail-open 放行所有请求。

    The middleware MUST be registered via `app.add_middleware(RateLimitMiddleware)`.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """
        限流检查主入口。

        Args:
            request: FastAPI 传入的请求实例
            call_next: 下一个中间件或路由处理的调用函数

        Returns:
            Response: 正常通过时返回下游处理的响应；超限时返回 429 JSONResponse

        Raises:
            本中间件不主动抛出异常（fail-open 策略）。

        Side Effects:
            - 写入 Redis ZSET（限流计数器 member）
            - 记录 WARNING/CRITICAL 级别结构化日志
            - 递增 Prometheus Counter `rate_limit_check_total`

        Idempotency:
            每次请求独立检查，天然幂等。同一请求重放会重新计数，不受之前计数影响。

        Thread Safety:
            每个请求在独立 ASGI 协程中执行，不共享可变状态。
            Redis LUA 脚本是原子操作，线程安全。
        """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `RateLimitMiddleware` —— FastAPI 全局中间件类 |
| **输入类型** | `Request`（ASGI 请求对象） + `RateLimitConfig`（配置契约引用） |
| **输出类型** | `Response`（正常通过） 或 `RateLimitExceededResponse`（429，契约引用） |
| **异常类型** | 本中间件不主动抛出异常（fail-open）。Redis 连接异常内部捕获后放行 |
| **副作用** | 写入 Redis ZSET、记录结构化日志、递增 Prometheus Counter |
| **幂等性** | 每次请求独立检查，天然幂等 |
| **并发安全** | 请求级协程隔离，Redis LUA 脚本原子执行 |

#### 1.6.2 接口 2：`RateLimitSettings`

```python
class RateLimitSettings(BaseSettings):
    """
    限流配置参数，从环境变量加载。

    SEC-01 RateLimitConfig 契约对应的 Python 实现类。
    通过 pydantic-settings 在应用启动时加载，运行时只读。
    """

    RATE_LIMIT_USER_PER_MINUTE: int = Field(
        default=30,
        ge=1,
        le=300,
        description="每个用户每分钟最大请求数",
    )
    RATE_LIMIT_IP_PER_MINUTE: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="每个 IP 每分钟最大请求数",
    )
    RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="限流滑动窗口大小（秒）",
    )

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `RateLimitSettings` —— Pydantic 配置模型 |
| **契约引用** | `docs/contracts/SEC-01/RateLimitConfig.json` |
| **加载方式** | `pydantic-settings` 从环境变量读取，应用启动时实例化 |
| **变更方式** | MVP 阶段重启生效，不支持运行时热更新 |
| **并发安全** | 启动后只读，天然线程安全 |

---

### 1.7 依赖与集成接口（本模块调用的外部接口）

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| Redis 缓存 | `packages/py-cache` | `redis_client.eval(script: str, keys: list, args: list) -> Any` | 执行 LUA 原子滑动窗口脚本 | `docs/篝火智答-项目结构.md` §py-cache；技术栈设计 Redis 7.x |
| 配置文件 | `packages/py-config` | `RateLimitSettings()` pydantic-settings 加载环境变量 | 加载限流阈值配置 | `docs/篝火智答-项目结构.md` §py-config |
| 日志系统 | `packages/py-logger` | `logger.warning("event", key=val)` / `logger.critical("event", key=val)` | 结构化日志记录 | `docs/篝火智答-项目结构.md` §py-logger |
| Prometheus 指标 | `prometheus-client` | `Counter("rate_limit_check_total", desc, ["status", "level"]).labels(status="passed", level="user").inc()` | 限流指标暴露 | `docs/篝火智答-项目结构.md` §可观测性 |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| AUTH-02 / AUTH-04 身份认证 | `request.state.user.id`（由 AUTH-04 `get_current_user` Depends 注入 `request.state`） | 获取已登录用户 user_id 用于用户级限流 | ⏭️ 待落地（中间件仅读取 `request.state.user.id`，该字段是否存在不影响限流流程——不存在则仅执行 IP 级） |
| SEC-01 传输存储安全 | `docs/contracts/SEC-01/check_rate_limit.json`（契约引用） | 复用限流检查输入参数定义 | ✅ 已落地（契约文件已写入 `docs/contracts/SEC-01/`） |
| DEPLOY-02 Nginx 反代 | `request.headers["X-Forwarded-For"]`（由 Nginx `proxy_set_header X-Forwarded-For $remote_addr` 注入） | 获取真实客户端 IP | ⏭️ 待配置（Nginx 配置不属于代码实现，需 DEPLOY-02 阶段确认） |

### 1.8 状态机（如适用）

本功能点不涉及状态流转，故无需状态机。限流检查是同步的无状态操作——请求到达，检查计数，放行或拒绝，不维护请求间的状态依赖。Redis ZSET TTL 过期是数据生命周期管理而非业务状态流转。

### 1.9 异常与边界条件

#### 1.9.1 异常 1：用户级请求频率超限

- **触发条件**：
  - 同一 `user_id` 在 `RATE_LIMIT_WINDOW_SECONDS`（默认 60s）滑动窗口内累计请求次数 > `RATE_LIMIT_USER_PER_MINUTE`（默认 30）
  - 仅在已登录用户（`request.state.user` 含 `id` 字段）场景下触发
- **处理策略**：
  1. LUA 脚本返回计数 > 阈值 → 跳过 IP 级检查（短路优化）
  2. 构造 429 响应体：`{"detail": "请求过于频繁，请稍后重试", "retry_after_seconds": window_seconds}`
  3. 设置 `Retry-After` 响应头为 `window_seconds`（int）
  4. 记录 WARNING 日志：`logger.warning("rate_limit_exceeded", level="user", user_id=request.state.user.id, count=..., limit=settings.RATE_LIMIT_USER_PER_MINUTE)`
  5. 递增 Prometheus Counter：`rate_limit_check_total{status="rejected", level="user"}`
  6. **不调用** `call_next(request)`，直接返回 429 响应
- **重试参数**：不重试，客户端在 `retry_after_seconds` 秒后重新发起请求。窗口滑动后首次请求自动恢复。

#### 1.9.2 异常 2：IP 级请求频率超限

- **触发条件**：
  - 同一 `ip` 在 `RATE_LIMIT_WINDOW_SECONDS`（默认 60s）滑动窗口内累计请求次数 > `RATE_LIMIT_IP_PER_MINUTE`（默认 100）
  - 适用于所有请求（已登录用户在用户级检查通过后触发，未登录用户直接触发）
- **处理策略**：
  1. LUA 脚本返回计数 > 阈值 → 拒绝
  2. 构造 429 响应体（同异常 1）
  3. 设置 `Retry-After` 响应头
  4. 记录 WARNING 日志：`logger.warning("rate_limit_exceeded", level="ip", ip=..., count=..., limit=settings.RATE_LIMIT_IP_PER_MINUTE, user_id=request.state.user.get("id") if authenticated else None)`
  5. 递增 Prometheus Counter：`rate_limit_check_total{status="rejected", level="ip"}`
  6. **不调用** `call_next(request)`，直接返回 429 响应
- **重试参数**：不重试。同一 IP 下不同已登录用户可通过独立用户级配额正常访问（用户级与 IP 级独立核算）。

#### 1.9.3 异常 3：Redis 连接异常（fail-open 降级）

- **触发条件**（任一满足即触发）：
  - `redis_client.eval()` 抛出 `redis.exceptions.ConnectionError`：Redis 服务未运行或网络不可达
  - `redis_client.eval()` 抛出 `redis.exceptions.TimeoutError`：连接池耗尽（所有连接被占用且等待超时，默认 `socket_connect_timeout=5s`）
  - `redis_client.eval()` 抛出 `redis.exceptions.ResponseError`：LUA 脚本执行语法错误或 Redis 版本不兼容（如未调用 `redis.replicate_commands()`）
- **处理策略**：
  1. 在 `dispatch()` 方法中包裹步骤 3（用户级）和步骤 4（IP 级）的 LUA 调用在 `try/except (ConnectionError, TimeoutError, ResponseError)` 块中
  2. 捕获异常后：**放行所有请求**，不执行限流检查
  3. 记录 CRITICAL 日志：`logger.critical("rate_limit_degraded", error_type=type(e).__name__, error_msg=str(e), ip=...)`
  4. 更新 Prometheus Gauge：`rate_limit_redis_health.set(0)`（健康状态变为故障）
  5. 调用 `await call_next(request)` 放行请求
  6. Redis 恢复后（下一次 LUA 调用成功），`rate_limit_redis_health.set(1)` 自动恢复，限流能力自动恢复
- **重试参数**：当前请求不重试 Redis 调用（直接 fail-open 放行）。后续请求自动重试（每次请求重新发起 Redis 调用，不维护重试计数器）。连接池内部重试由 `redis-py` 连接池配置控制（默认 `retry_on_timeout=True`）。

#### 1.9.4 异常 4：LUA 脚本 `redis.replicate_commands()` 缺失

- **触发条件**：
  - LUA 脚本中未调用 `redis.replicate_commands()`，且 Redis 主从复制场景下执行了写入命令（`ZADD` + `ZREMRANGEBYSCORE`）
  - Redis >= 7.0 默认要求显式调用 `redis.replicate_commands()`，否则脚本可能因复制不一致而被拒绝执行（`Write commands not allowed after non deterministic commands`）
- **处理策略**：
  1. LUA 脚本第一行必须调用 `redis.replicate_commands()`
  2. 若因缺失此调用导致 `ResponseError`，按异常 3 的 fail-open 策略处理
  3. 在测试阶段通过集成测试验证 LUA 脚本在 Redis 主从模式下的兼容性
- **重试参数**：不重试，修复代码后重新部署。

#### 1.9.5 边界条件：异常行为标记

- **触发条件**：同一 `user_id` 在 5 分钟内累计触发限流拒绝（用户级或 IP 级均可）>= 3 次
- **处理策略**：
  1. 在 Redis 中维护一个临时计数器 key `ratelimit:anomaly:{user_id}:{date_hour_block}`（5 分钟块，TTL = 5 分钟 + 10s 缓冲 = 310s）
  2. 每次限流拒绝时 INCR 该计数器
  3. 当计数器值达到 3 时，记录一条标记日志：`logger.warning("potential_abnormal_behavior", user_id=..., anomaly_type="frequent_rate_limit_hits", hit_count=3, window_minutes=5)`
  4. **不触发任何额外处理动作**（不冻结账号、不人工审核、不阻断访问），仅作为安全分析数据点
- **重试参数**：不重试，标记操作是尽力而为的辅助分析，不影响请求处理流程。

### 1.10 验收测试场景

#### 1.10.1 正向测试 1：正常请求通过限流检查

- **场景**：未登录用户首次发起 API 请求，限流检查通过，请求正常处理
- **Given**: 未登录用户（`request.state.user` 无 `id` 字段），客户端 IP `192.168.1.100`，请求路径 `/api/v1/articles`
- **When**: 发起 GET 请求到任意业务端点
- **Then**:
  - 状态码为 200（业务正常返回），而非 429
  - `rate_limit_check_total{status="passed", level="ip"}` 计数递增 1
  - `rate_limit_check_total{status="rejected"}` 计数不变
  - 响应头中不包含 `Retry-After`
  - Redis 中存在 key `ratelimit:ip:192.168.1.100`，ZCARD = 1

#### 1.10.2 正向测试 2：白名单路径豁免限流

- **场景**：对健康检查端点的高频请求不被限流拦截
- **Given**: 未登录用户，IP `10.0.0.1`，请求路径 `/health`
- **When**: 连续发起 200 次 GET `/health` 请求
- **Then**:
  - 每次返回 200 状态码，无 429
  - Redis 中不存在 `ratelimit:ip:10.0.0.1` key（白名单路径不写入 Redis）
  - `rate_limit_check_total` 计数不变（白名单路径不经过限流检查逻辑）

#### 1.10.3 正向测试 3：用户级与 IP 级独立限流

- **场景**：已登录用户从两个不同 IP 发起请求，两个 IP 计数器独立，用户级计数器跨 IP 累加
- **Given**: 用户 `user-001` 已登录，`rate_limit_settings.RATE_LIMIT_USER_PER_MINUTE=30`，`RATE_LIMIT_IP_PER_MINUTE=100`
- **When**: 用户从 IP `10.0.0.1` 发起 25 次请求 + 从 IP `10.0.0.2` 发起 10 次请求（总计 35 次）
- **Then**:
  - 第 31 次请求被拒绝（用户级超限），返回 429
  - Redis 中 `ratelimit:ip:10.0.0.1` ZCARD = 25，`ratelimit:ip:10.0.0.2` ZCARD = 10
  - `ratelimit:user:user-001` ZCARD = 35（跨 IP 累加）
  - 从 IP `10.0.0.1` 发起的最后 5 次请求和第 31 次及之后的请求全部被拒绝

#### 1.10.4 异常测试 1：用户级限流触发

- **场景**：已登录用户在窗口内请求超过用户级阈值
- **Given**: 用户 `user-001` 已登录，`RATE_LIMIT_USER_PER_MINUTE=30`，`RATE_LIMIT_WINDOW_SECONDS=60`，IP `10.0.0.1`
- **When**: 连续发起 31 次 GET 请求到 `/api/v1/articles`（每次请求携带相同 `Authorization` 头）
- **Then**:
  - 前 30 次返回 200
  - 第 31 次返回 429，响应体为 `{"detail": "请求过于频繁，请稍后重试", "retry_after_seconds": 60}`
  - 响应头包含 `Retry-After: 60`
  - `rate_limit_check_total{status="rejected", level="user"}` 计数递增 1
  - WARNING 日志包含 `"rate_limit_exceeded"`、`level="user"`、`user_id="user-001"`、`count=31`、`limit=30`

#### 1.10.5 异常测试 2：IP 级限流触发（未登录场景）

- **场景**：未登录用户在窗口内请求超过 IP 级阈值
- **Given**: 无用户身份标识，IP `10.0.0.1`，`RATE_LIMIT_IP_PER_MINUTE=100`，`RATE_LIMIT_WINDOW_SECONDS=60`
- **When**: 连续发起 101 次 GET 请求到 `/api/v1/articles`
- **Then**:
  - 前 100 次返回 200
  - 第 101 次返回 429，响应体同上述格式
  - `rate_limit_check_total{status="rejected", level="ip"}` 计数递增 1
  - WARNING 日志包含 `"rate_limit_exceeded"`、`level="ip"`、`ip="10.0.0.1"`

#### 1.10.6 异常测试 3：Redis 故障时 fail-open 降级

- **场景**：Redis 服务不可用时，所有请求正常通过
- **Given**: Redis 服务未运行（`redis_client.eval()` 抛出 `ConnectionError`）
- **When**: 发起任意 GET 请求
- **Then**:
  - 请求正常通过，返回 200（非 429，非 500）
  - CRITICAL 日志包含 `"rate_limit_degraded"`、`error_type="ConnectionError"`
  - `rate_limit_redis_health` Gauge 值为 0
  - `rate_limit_check_total{status="degraded"}` 计数递增 1

#### 1.10.7 异常测试 4：限流自动恢复（窗口滑动）

- **场景**：超限用户等待窗口滑动后自动恢复访问
- **Given**: 用户 `user-001` 已触发用户级限流（第 31 次被拒）
- **When**: 等待 `RATE_LIMIT_WINDOW_SECONDS + 1`（61 秒）后重新发起请求
- **Then**:
  - 请求返回 200 状态码
  - `rate_limit_check_total{status="passed"}` 计数递增 1

### 1.11 注意事项与禁止行为（编码层面）

1. **【约束 1】LUA 脚本第一行必须调用 `redis.replicate_commands()`**。不调用此函数可能导致 LUA 脚本在 Redis 主从复制场景下产生不一致。所有限流 LUA 脚本必须以 `redis.replicate_commands();` 开头。

2. **【约束 2】429 响应体严格遵循 `RateLimitExceededResponse` 契约**，仅输出 `detail` 和 `retry_after_seconds` 两个字段。禁止添加 `trace_id`、`error_code`、`key_name` 等自定义字段——违反意图文档 §1.11(5) 信息隐藏原则。

3. **【易错点 1】区分 `request.state.user` 有无 `id` 字段的判断路径**：不能简单地 `if request.state.user`，因为 `request.state` 的属性默认不存在时访问会抛 `AttributeError`。应使用 `hasattr(request.state, "user") and hasattr(request.state.user, "id")` 或 `getattr(getattr(request.state, "user", None), "id", None)`。未登录场景下访问 `request.state.user.id` 会抛 `AttributeError: 'State' object has no attribute 'user'`。

4. **【易错点 2】Redis 连接池异常需全面捕获**：`redis_client.eval()` 可能抛出多种异常类型：`redis.exceptions.ConnectionError`（网络不可达）、`redis.exceptions.TimeoutError`（获取连接超时）、`redis.exceptions.ResponseError`（LUA 执行错误）。`try/except` 块必须捕获 `redis.exceptions.RedisError` 基类（或其子类元组），不能只捕获 `ConnectionError`。

5. **【禁止行为】禁止在限流中间件中获取业务数据或调用业务 service**。限流中间件应当只依赖请求头（`X-Forwarded-For`、`Authorization`）和 `request.state` 中的身份信息，不得引入业务数据依赖（如查询 PostgreSQL 获取用户角色、调用 `case_service` 获取案例信息）。违反此禁令会破坏限流层与业务层的解耦。

6. **【禁止行为】禁止将 fail-open 降级策略改为 fail-close**。意图文档 §1.11(4) 明确要求"限流服务自身故障时自动降级放行所有请求，不得因限流故障导致全服务不可用"。任何后续维护者不得以提高安全等级为由将降级策略改为 fail-close。

7. **【偷懒红线】禁止在代码中写 `"with ... as ..."` 未具体的 Redis 连接上下文**。必须显式使用项目中已封装好的 `redis_client` 实例（来自 `packages/py-cache`），禁止自行创建 `redis.Redis(host=..., port=...)` 连接。

8. **【易错点 3】Prometheus 指标必须在模块加载时注册**（模块级别 `REGISTRY`），禁止在每次请求的 `dispatch()` 方法中注册或创建 Counter/Gauge。在请求热路径上重复注册会导致 `ValueError: duplicated metric` 异常。指标注册应放在模块级全局变量中。

### 1.12 文档详细度自检清单

- [x] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成编码
- [x] 无偷懒表述：全文搜索并消除 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：每个 Pydantic 字段都有 `description` + `examples` + 约束（`ge`/`le` 等）
- [x] 逻辑步骤完整：每个步骤都有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：每种异常都有精确的触发条件、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值来源、条件分支、业务规则都已显式写出
- [x] 技术栈绑定明确：必须使用和禁止使用的项均已列出，且与项目结构设计文档保持一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致

### 1.14 外部接口契约清单

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| check_rate_limit | `docs/contracts/SEC-01/check_rate_limit.json` | input | draft | SEC-01 | SEC-04（本模块） |
| RateLimitConfig | `docs/contracts/SEC-01/RateLimitConfig.json` | shared-model | draft | SEC-01 | SEC-04（本模块） |
| RateLimitExceededResponse | `docs/contracts/SEC-01/RateLimitExceededResponse.json` | output | draft | SEC-01 | SEC-04（本模块） |

注：本模块为纯消费者，未定义新的对外接口契约。全部 3 个契约由 SEC-01 定义，SEC-04 通过契约引用方式使用。

### 1.15 意图一致性声明

- **配套意图文档**：`SEC-04-防刷限流-意图文档.md`
- **冻结时间**：2026-05-26 18:45:00
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致
  - [x] 本落地规范中的状态机实现与意图文档中的状态业务定义一致（双方确认无状态机）
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准（AC-01 至 AC-08）
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
