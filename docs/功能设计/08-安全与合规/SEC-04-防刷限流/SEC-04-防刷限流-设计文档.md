# 1 功能点：SEC-04 防刷限流 — 设计文档（瘦身版）

> **文档生成时间**：2026-05-26 21:11:43
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 21:11:43 | AI Assistant | 初始版本 |
>
> **配套文档**：
> - 本模块的业务意图和验收标准见 `SEC-04-防刷限流-意图文档.md`（已冻结，2026-05-26 18:45:00）
> - 本模块的精确编码规格见 `SEC-04-防刷限流-落地规范.md`

### 1.1 技术实现思路

防刷限流模块采用 **Redis ZSET 原子滑动窗口** 作为核心技术方案，以 **FastAPI 全局 HTTP 中间件** 形式注册在路由处理之前、身份认证之前执行。

**为什么选择 ZSET + LUA 原子脚本而非多 key 模式。**

滑动窗口限流的经典实现有两种路径：多 key 模式（每秒一个 key，窗口内统计 60 个 key 的计数总和）和 ZSET 单 key 模式（一个 key 存储窗口内所有请求时间戳）。本模块选用 ZSET 单 key 模式，理由是：每个用户/IP 仅维护 1 个 ZSET key，内存开销可预测（每条请求约 30 bytes），且 LUA 脚本 `redis.eval()` 在一次原子操作内完成 ZADD（添加当前时间戳 member）、ZREMRANGEBYSCORE（移除窗口外过期 member）、ZCARD（统计窗口内请求数）三个操作，无需额外的清理任务或分布式锁。相比之下，多 key 模式虽然时间精度一致，但 key 数量膨胀 60 倍，在攻击场景下内存压力更大，而本模块对精度的要求（秒级）两种模式均可满足。

**短路优化的执行顺序。**

已登录用户同时受用户级和 IP 级双重限流。由于用户级阈值（30/min）远低于 IP 级阈值（100/min），已登录用户总是先触达用户级限制。因此采用短路优化：先检查用户级（如已登录），超限则直接拒绝不检查 IP 级；用户级通过或无 user_id 时再检查 IP 级。这一策略对已登录用户的拒绝场景节省约 50% 的 Redis 调用，不影响限流正确性（独立判断，任一超限即拒绝）。

**Fail-open 降级策略。**

Redis 不可用时，中间件捕获连接异常，放行所有请求并记录 CRITICAL 级别告警日志。这一决策基于意图文档明确的"降级可用原则"——限流故障不得导致全服务不可用。降级期间不记录任何限流拒绝事件（因为限流服务未运行）。Redis 恢复后限流能力自动恢复，无需人工介入。

**IP 来源的可靠获取。**

对于通过 Nginx 反向代理转发的请求，`request.client.host` 仅能获取 Nginx 内网 IP，无法反映真实客户端地址。因此优先读取 `X-Forwarded-For` 头取第一个非内网 IP，回退到 `request.client.host`。Nginx 侧（DEPLOY-02）需配置 `proxy_set_header X-Forwarded-For $remote_addr` 覆盖客户端伪造的头部值，确保 IP 来源可信。

**白名单豁免机制。**

健康检查端点 `/health` 和 Prometheus 指标端点 `/metrics` 通过硬编码白名单集合绕过限流检查。白名单路径极少且稳定（意图文档明确仅 `/health` 可豁免，技术栈设计追加 `/metrics`），硬编码为 Python 集合常量 `RATE_LIMIT_WHITELIST_PATHS = {"/health", "/metrics"}` 在可读性和运行时性能上均优于配置文件或环境变量方案。

**限流 key 的内存管理。**

每个 ZSET key 的 TTL 设为窗口大小（60s）+ 缓冲值（10s）= 70 秒。TTL 到期后 key 被 Redis 自动回收。每次原子操作中 ZREMRANGEBYSCORE 自动清除窗口外的过期 member，双重保障防止内存泄漏。极端攻击场景下（大量 IP 同时高频请求），依赖 Redis `allkeys-lru` 淘汰策略作为兜底，由运维层统一处理而非代码层面解决。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：
  - `docs/篝火智答-技术栈设计.md` 第 5 章（安全设计）
  - `docs/功能设计/08-安全与合规/SEC-01-传输存储安全/SEC-01-传输存储安全-意图文档.md`
  - `docs/功能设计/08-安全与合规/SEC-01-传输存储安全/SEC-01-传输存储安全-落地规范.md`
  - `docs/contracts/SEC-01/check_rate_limit.json`（maturity: draft）
  - `docs/contracts/SEC-01/RateLimitConfig.json`（maturity: draft）
  - `docs/contracts/SEC-01/RateLimitExceededResponse.json`（maturity: draft）
  - `docs/功能设计/01-用户认证与授权/AUTH-04-五级RBAC鉴权/AUTH-04-五级RBAC鉴权-设计文档.md`
  - `docs/功能设计/07-系统可观测性/OBS-01-结构化日志/OBS-01-结构化日志-设计文档.md`

- **兼容性结论**：
  - **无冲突**：SEC-04 作为 SEC-01 预定义限流契约的纯消费者，不定义新的对外类型接口，与全部已有规格文档无类型冲突。
  - **依赖方向兼容**：SEC-04 → SEC-01（共享 Redis 基础设施）、SEC-04 → AUTH-02（用户身份标识获取）、SEC-04 → DEPLOY-02（Nginx X-Forwarded-For 协同），均为合理的单向依赖，不产生循环依赖。
  - **路径兼容**：项目结构已预留 `apps/api-server/app/middleware/rate_limit.py` 作为限流中间件实现位置，技术栈设计已确认 Redis 7.x 作为限流基础设施。
  - **AUTH-04 Depends 链兼容**：AUTH-04 的 `get_current_user` 在 `request.state.user` 中注入 `user_id` 字段，本模块从此字段提取用户身份标识进行用户级限流，与 AUTH-04 的 Depends 链兼容。

- **复用的已有设计**：
  - 限流检查接口参数定义（`check_rate_limit.json` 契约）：`user_id: str | None` + `ip: str`
  - 限流配置参数结构（`RateLimitConfig.json` 契约）：`RATE_LIMIT_USER_PER_MINUTE` / `RATE_LIMIT_IP_PER_MINUTE` / `RATE_LIMIT_WINDOW_SECONDS`
  - 限流拒绝响应格式（`RateLimitExceededResponse.json` 契约）：`detail` + `retry_after_seconds`
  - Redis key 命名规范（SEC-01 意图文档 §1.3(4)）：`ratelimit:user:{user_id}` 和 `ratelimit:ip:{ip}`
  - Redis 不可用时 fail-open 降级策略（SEC-01 已定义的共享策略）

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| Redis 7.x（`py-cache`） | 读写 | 通过 `redis_client.eval()` 执行 LUA 脚本实现原子滑动窗口计数。key 命名遵循 `ratelimit:user:{user_id}` 和 `ratelimit:ip:{ip}` 规范 |
| SEC-01 限流契约 | 消费 | 复用 3 份预定义契约：`check_rate_limit`（输入参数格式）、`RateLimitConfig`（配置参数）、`RateLimitExceededResponse`（429 响应体） |
| AUTH-02 身份认证 | 上游数据来源 | 从 `request.state.user.id` 读取已登录用户的 user_id（由 AUTH-04 `get_current_user` Depends 注入）；无 user_id 时仅执行 IP 级限流 |
| DEPLOY-02 Nginx 反代 | 协同防御 | 依赖 Nginx 配置 `proxy_set_header X-Forwarded-For $remote_addr` 提供可信客户端 IP；Nginx 层同时执行粗粒度 IP 前置限流 |
| `py-config` 配置系统 | 读取 | 通过 pydantic-settings 加载限流阈值环境变量（`RATE_LIMIT_USER_PER_MINUTE`、`RATE_LIMIT_IP_PER_MINUTE`、`RATE_LIMIT_WINDOW_SECONDS`） |
| `py-logger` 日志系统 | 写入 | 拒绝时记录 WARNING 级别结构化日志；Redis 故障时记录 CRITICAL 级别告警日志；正常通过不记日志 |
| Prometheus + Grafana | 指标暴露 | 暴露 3 个自定义指标：`rate_limit_check_total`（Counter，含 status/labels）、`rate_limit_active_keys`（Gauge）、`rate_limit_redis_health`（Gauge 0/1）用于监控和告警 |

### 1.4 状态机设计（技术实现策略，如适用）

本功能点不涉及状态流转，故无需状态机。限流检查是同步的无状态操作——请求到达，检查计数，放行或拒绝，不维护请求间的状态依赖。Redis ZSET 的过期机制是数据生命周期管理而非业务状态流转。

```
请求到达 → IP 来源解析 → 白名单匹配（白名单路径直接放行）
                        → 已登录？→ 是：用户级 ZSET 检查（超限则 429）
                        → 否或用户级通过：IP 级 ZSET 检查（超限则 429）
                        → 全部通过 → 放行至下一个中间件/路由处理
```

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| 1 | 厚 package、薄 app | 限流中间件（app 层）仅编排检查逻辑，原子滑动窗口操作通过 LUA 脚本封装在共享能力层 `py-cache` 的 `redis_client.eval()` 中执行 |
| 2 | 单向依赖 | 限流中间件（L1 app 层）调用 `py-cache`（L2 共享能力层），L2 层通过 pydantic-settings 加载配置，不反向依赖 L1。中间件不直接 import 其他 app 模块 |
| 5 | 最小化可工作 | 仅实现意图文档明确要求的用户级/IP 级限流、健康检查白名单、fail-open 降级、计数指标暴露。不实现未规划的功能（如用户黑名单、分布式限流协调、限流配置热更新） |
| — | 可观测性 | 正常通过不记日志（避免日志洪峰），拒绝时记录 WARNING 结构化日志，Redis 故障时记录 CRITICAL 告警日志，通过 Prometheus 3 指标暴露运行状态 |

### 1.6 架构权衡与备选方案

#### 1.6.1 自主确定的技术决策（10 项）

以下决策已在技术预研阶段完成分析并自主确定：

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 中间件注册位置 | 全局中间件，身份认证前执行 | 路由级中间件 | 保证限流在认证前执行，防止未认证请求消耗认证资源；与意图文档 §1.1 对齐 |
| 限流 key 数据结构 | Redis ZSET 单 key | 多 key（每秒一 key） | 单 key 管理简单，内存开销可预测；LUA 原子操作无需额外清理任务 |
| 原子操作实现 | LUA 脚本 `redis.eval()` | 应用层 WATCH/MULTI/EXEC | LUA 脚本保证原子性且减少网络往返（1 次 eval 替代 3+ 次独立命令） |
| IP 来源策略 | X-Forwarded-For 优先，回退 client.host | 仅使用 client.host | 反代场景下 client.host 为 Nginx 内网 IP，X-Forwarded-For 为互联网标准做法 |
| Prometheus 指标 | 3 个自定义指标（check_total/active_keys/redis_health） | 仅使用默认 instrumentator 指标 | 按 level 标签区分用户级/IP 级；redis_health 用于 Grafana 告警触发 |
| 429 响应 | HTTP 429 + Retry-After 头部 + JSON body | 仅 JSON body | Retry-After 是 HTTP 标准头部（RFC 7231），Nginx 和浏览器原生理解 |
| 限流幂等性 | 不修改业务数据，天然幂等 | 不适用 | 限流仅读写 Redis 计数器，不涉及业务实体；受意图文档约束 |
| 全局异常处理 | 中间件内捕获 Redis 异常，fail-open | 抛出 HTTP 500 | 受意图文档 §1.11(4) 降级可用原则约束 |
| 日志记录策略 | 通过不记，拒绝记 WARNING，Redis 故障记 CRITICAL | 全部请求记日志 | 避免攻击场景下的日志洪峰；WARNING 级别可在生产环境按需过滤 |
| 健康检查豁免 | 硬编码集合 `{"/health", "/metrics"}` | 环境变量/配置文件 | 白名单路径极少且稳定，硬编码可读性最高且运行时性能最优 |

#### 1.6.2 业务矛盾标记及处理方式（8 项）

以下 8 项来自意图文档 §1.12"留给规范阶段的技术决策"，经技术预研分析后推荐方案如下。无用户历史裁决，以报告推荐为准。

| # | 矛盾点 | 最终处理 | 推荐方案摘要 | 备选方案及其代价 |
|---|--------|----------|-------------|-----------------|
| 1 | 限流算法：ZSET vs 多 key | ZSET 单 key + LUA 脚本 | 单 key 管理简单，内存开销可预测；每次原子操作自动清除过期 member | 多 key 方案 key 数量膨胀 60 倍，攻击场景内存压力更大 |
| 2 | 白名单配置方式 | **硬编码** | `/health` 和 `/metrics` 两个路径，变更频率极低（意图文档明确），硬编码可读性最高 | 环境变量方案增加配置复杂度而无实质收益 |
| 3 | Redis 故障告警通道 | **Grafana Alert + 5 分钟重复间隔** | 复用项目已有 Prometheus + Grafana 体系，5 分钟间隔与现有 5xx 告警一致 | 独立告警通道增加运维碎片化 |
| 4 | 异常行为存储方式 | **PostgreSQL 持久化，保留 90 天** | 分析场景需要历史数据的持久性和可查询性；数据量极小（百万用户日均 < 1000 条，90 天 < 9 万条） | Redis 临时存储不适合长期查询；两阶段存储增加复杂度 |
| 5 | 限流配置运行时调整 | **MVP 重启生效（环境变量）** | 阈值已冻结，无迹象表明 MVP 阶段需频繁调整；`docker compose restart api-server` 耗时 < 1s | 热更新需要配置中心/Redis 热 key + API 端点 + 权限控制，1-3 人团队建设成本高 |
| 6 | 429 响应体扩展字段 | **严格按 SEC-01 契约，不扩展** | 契约已定义 `detail` + `retry_after_seconds`；信息隐藏原则（§1.11(5)）不暴露内部细节 | 添加 trace_id 应在全局响应头处理，不应仅在限流场景特殊处理 |
| 7 | 限流执行顺序 | **短路优化：用户级→IP 级** | 用户级阈值（30/min）远低于 IP 级（100/min），已登录用户先触达用户级，短路节省 50% Redis 调用 | 全量检查无性能收益，适用于需要同时统计两组指标的场景 |
| 8 | key 的 TTL 与内存管理 | **TTL = 70s（60+10 缓冲）** | 确保窗口期内所有 member 可查；ZSET 在每次操作时自动清理过期 member；TTL 到期自动回收 | 更短的 TTL 无实际意义，更长的 TTL 增加无谓内存占用 |

### 1.7 注意事项与禁止行为（设计层面）

1. **【约束 1】** 限流中间件必须注册为全局中间件，在所有路由处理之前执行。禁止注册为路由级中间件——部分路由可能遗漏导致限流绕过风险。

2. **【约束 2】** 响应体必须严格遵循 SEC-01 `RateLimitExceededResponse.json` 契约，仅输出 `detail` 和 `retry_after_seconds` 两个字段。禁止添加自定义字段（如内部错误码、Redis key 名称），违反意图文档 §1.11(5) 信息隐藏原则。

3. **【易错点 1】** 注意区分用户级限流和 IP 级限流的执行路径：已登录用户同时执行两级检查，短路优化先查用户级；未登录用户仅执行 IP 级。不要在未提供 user_id 的场景下执行用户级检查（会导致空值误判）。

4. **【易错点 2】** Redis 连接异常的捕获范围：需要同时覆盖 `redis_client.eval()` 调用和 Redis 连接池获取连接两个环节。连接池耗尽（连接池满导致获取连接超时）与连接被拒绝是两种不同的异常类型，都需要捕获并 fail-open。

5. **【设计边界】** 本模块不负责：（1）身份认证（AUTH 系列）；（2）传输加密（SEC-01）；（3）请求内容的 Schema 校验（SEC-05）；（4）IP 黑白名单（本模块仅频率维度检查，黑名单不属于设计范围）。禁止在本模块中实现上述不属于职责范围的功能。

6. **【禁止行为】** 禁止在限流中间件中获取业务数据或调用业务服务（如查询数据库获取用户信息）。限流中间件应当只依赖请求头（`X-Forwarded-For`、`Authorization`）和 `request.state` 中的身份信息，不得引入业务数据依赖——这会破坏限流层与业务层的解耦。

7. **【禁止行为】** 禁止将 Redis 故障降级（fail-open）替换为 fail-close（拒绝所有请求）。意图文档明确要求"限流服务自身故障时自动降级放行所有请求，不得因限流故障导致全服务不可用"。任何后续维护者不得以提高安全等级为由将降级策略改为 fail-close。

8. **【约束 3】** LUA 脚本必须通过 `redis.replicate_commands()` 保持与 Redis 复制的兼容性。不调用此函数可能导致 LUA 脚本在 Redis 主从复制场景下产生不一致。

### 1.8 引用：配套意图文档

- **意图文档**：`SEC-04-防刷限流-意图文档.md`
- **冻结时间**：2026-05-26 18:45:00
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。如有歧义，以意图文档为准。
