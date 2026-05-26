## 1 功能点：OBS-04 健康检查 — 落地规范

> **文档生成时间**：2026-05-26 23:07:02
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 23:07:02 | AI Assistant | 初始版本：基于 s08 契约协调报告（5 类型/0 冲突）和设计文档 v1.0 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `OBS-04-健康检查-设计文档.md`。
> **契约协调依据**：`.tmp/contract-harmonize-report.json` — 5 个新类型，零冲突，4 项消费外部契约。

---

## 【对内实现】

### 1.1 技术栈绑定

- **必须使用**：
  - Python 3.12+ 标准库 `asyncio`（并发执行三个组件的连通性检查，使用 `asyncio.gather(return_exceptions=True)` + `asyncio.wait_for()` 超时控制）
  - Python 3.12+ 标准库 `datetime`（时间戳生成，含 `datetime.timezone.utc`）
  - Python 3.12+ 标准库 `time`（获取服务启动时间，计算 `uptime_seconds`）
  - Python 3.12+ 标准库 `json`（JSON 序列化，log.extra 字段组装）
  - `fastapi>=0.115` 的 `APIRouter`（注册 `/health` 和 `/ready` 路由，返回 `JSONResponse` 并显式设置 `status_code`）
  - `pydantic>=2.0` 的 `BaseModel`、`Field`（响应模型定义，含 `examples`、`description`）
  - `sqlalchemy>=2.0` 的 `create_async_engine`、`text("SELECT 1")`、`AsyncEngine`（独立轻量引擎用于 PostgreSQL 连通性验证）
  - `redis>=5.0` 的 `redis.asyncio.Redis`（独立短连接用于 Redis PING 验证）
  - `minio>=7.0` 的 `Minio` 客户端（独立短连接用于 MinIO bucket_exists 验证）
  - `py_logger.core.logger`（OBS-01 定义的结构化日志接口，状态变更时写入 `logger.warning()`/`logger.info()`）
  - `py_config.config.settings`（DEPLOY-05 定义的全局配置，获取 `DATABASE_URL`、`REDIS_URL`、`MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`）
  - 项目结构 §6.1 规定的目录：`apps/api-server/app/api/v1/health.py`（路由文件，厚度 < 30 行）；推论共享包路径 `packages/py-health/py_health/`（含 `checker.py`、`models.py`）
- **禁止使用**：
  - 禁止健康检查复用业务数据库引擎（`py_db.database.engine`）——必须创建独立的 `create_async_engine()` 实例
  - 禁止在健康检查中执行写操作（`INSERT`、`UPDATE`、`DELETE`、`SET key value`、`put_object()` 等任何副作用操作）
  - 禁止在健康检查中引入 `asyncio.sleep()` 作为超时模拟（应通过实际连接超时参数控制）
  - 禁止在健康检查中调用业务 Service/Repository 层的任何函数——健康检查仅访问基础设施层的原始客户端
  - 禁止使用 `orjson`、`ujson` 等第三方 JSON 库（标准库 `json` 满足需求）
  - 禁止在 `/health` 路由上启用 JWT 认证中间件——健康检查是项目中唯一豁免认证的公开端点

### 1.2 文件归属

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 路由文件 | `apps/api-server/app/api/v1/health.py` | FastAPI 路由注册：`GET /health`（别名 `/api/v1/health`）和 `GET /ready`（别名 `/api/v1/ready`），调用 shared checker 并序列化响应 |
| 探测逻辑 | `packages/py-health/py_health/checker.py` | `check_all()` 协程：并发执行全部三个组件的连通性检查，聚合结果，计算整体状态 |
| 响应模型 | `packages/py-health/py_health/models.py` | Pydantic 响应模型定义：`HealthCheckResponse`、`ReadinessResponse`、`ComponentHealth`，枚举 `HealthStatus`、`ComponentStatus` |
| 状态追踪 | `packages/py-health/py_health/state.py` | 模块级 `_last_overall_status` 变量和 `_consecutive_failures` 计数器，支持状态变更防抖和连续失败计数 |
| 测试文件 | `packages/py-health/tests/test_checker.py` | `check_all()` 和 `/health`/`/ready` 端点的单元测试与集成测试 |
| 测试文件 | `packages/py-health/tests/test_state.py` | 状态变更防抖、连续失败计数器的正确性测试 |
| 路由测试 | `apps/api-server/tests/test_health_endpoints.py` | FastAPI TestClient 直接测试 `/health` 和 `/ready` 端点的 HTTP 行为和状态码 |

### 1.5 核心逻辑步骤

1. **步骤 1：接收 HTTP 请求**
   - **操作对象**：FastAPI `Request` 对象
   - **具体操作**：FastAPI 路由函数接收 `GET /health`（或 `GET /ready`）请求，提取 `User-Agent` 头部作为来源标识
   - **输入来源**：外部 HTTP 请求（Docker HEALTHCHECK 探针、运维 curl、监控系统）
   - **输出去向**：请求上下文进入步骤 2
   - **失败行为**：非 GET 方法 → 路由层返回 HTTP 405 Method Not Allowed（无需进入检查逻辑）

2. **步骤 2：初始化独立连接（仅 /health 端点）**
   - **操作对象**：PostgreSQL `AsyncEngine`、Redis `redis.asyncio.Redis`、MinIO `Minio` 客户端
   - **具体操作**：
     - 创建独立 SQLAlchemy `AsyncEngine`：`create_async_engine(settings.DATABASE_URL, pool_size=1, max_overflow=0)`
     - 创建独立 Redis 客户端：`redis.asyncio.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=3)`
     - 创建独立 MinIO 客户端：`Minio(settings.MINIO_ENDPOINT, access_key=settings.MINIO_ACCESS_KEY, secret_key=settings.MINIO_SECRET_KEY, secure=False)`
   - **输入来源**：`py_config.config.settings`（DEPLOY-05 AppSettings 契约）中的连接参数
   - **输出去向**：三个就绪的客户端实例进入步骤 3
   - **失败行为**：连接参数缺失 → 对应组件立即标记为 `ComponentStatus.disconnected`，错误信息为 `"configuration_missing"`，不终止其他组件的初始化；`create_async_engine()` 本身是惰性的（不立即建立连接），失败仅在步骤 3 的 `connect()` 时暴露

3. **步骤 3：并发执行组件连通性检查（对于 /health；/ready 仅执行 PostgreSQL 检查）**
   - **操作对象**：三个 async 检查函数 `_check_postgresql()`、`_check_redis()`、`_check_minio()`
   - **具体操作**：
     - `_check_postgresql()`：通过独立引擎获取连接 `conn = await engine.connect()`，执行 `await conn.execute(text("SELECT 1"))`，读取结果 `await result.fetchone()`，然后 `await conn.close()`
     - `_check_redis()`：执行 `await redis_client.ping()`，期望返回 `True`
     - `_check_minio()`：执行 `minio_client.bucket_exists("campfire")`（同步调用，在 `asyncio.to_thread()` 中执行）
     - 用 `asyncio.wait_for(check_fn(), timeout=TIMEOUT)` 分别管控超时（PG 3s、Redis 3s、MinIO 5s）
     - 用 `asyncio.gather(*checks, return_exceptions=True)` 并发执行
   - **输入来源**：步骤 2 初始化的独立客户端
   - **输出去向**：每个组件的检查结果（成功返回 `(component_name, True, latency_ms, None)`，失败返回 `(component_name, False, latency_ms, error_message)`）进入步骤 4
   - **失败行为**：
     - 单个组件超时 (`asyncio.TimeoutError`) → 该组件标记为 `disconnected`，错误信息为 `"timeout: exceeded {TIMEOUT}s"`
     - 单个组件连接异常 → 该组件标记为 `disconnected`，错误信息为异常消息（截断至 256 字符）
     - `return_exceptions=True` 确保一个组件的失败不终止其他组件的检查——总是收集全部三个组件的结果

4. **步骤 4：聚合结果与判定整体状态（对于 /health；/ready 直接用 PostgreSQL 结果）**
   - **操作对象**：步骤 3 返回的三个组件检查结果
   - **具体操作**：
     - `/health`：统计 `disconnected` 的组件数。0 → `HealthStatus.healthy`；1 或 2 → `HealthStatus.degraded`；3 → `HealthStatus.unhealthy`
     - `/ready`：`ready = (postgresql.status == "connected")`。true → HTTP 200；false → HTTP 503
     - 比较当前状态与 `_last_overall_status`——若不同，写入结构化日志（`logger.warning()` 或 `logger.info()`），更新 `_last_overall_status`
     - 更新 `_consecutive_failures` 计数器：有任一 failure → +1；全部成功 → 归零
   - **输入来源**：步骤 3 的组件检查结果 + 内存中的状态变量
   - **输出去向**：`HealthCheckResponse` 或 `ReadinessResponse` Pydantic 模型实例进入步骤 5
   - **失败行为**：不适用（聚合逻辑本身不涉及 I/O 或外部依赖，不会失败）

5. **步骤 5：返回 HTTP 响应**
   - **操作对象**：`HealthCheckResponse` 或 `ReadinessResponse` 模型实例
   - **具体操作**：
     - 调用 `.model_dump()` 序列化为字典
     - 构造 `JSONResponse(content=data_dict, status_code=200_or_503)`
     - `/health`：`status == "healthy"` → 200，其他（degraded/unhealthy）→ 503
     - `/ready`：`ready == true` → 200，`false` → 503
   - **输入来源**：步骤 4 聚合后的 Pydantic 模型实例
   - **输出去向**：HTTP 响应体（JSON）返回给调用方；Docker 日志驱动采集 stdout（由 OBS-01 间接消费）
   - **失败行为**：Pydantic 序列化失败 → 降级返回 `{"status": "unhealthy", "error": "internal_serialization_error"}`，HTTP 503，不向上传播异常

### 1.8 状态机

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 副作用 |
|----------|----------|----------|----------|--------|
| 健康（healthy） | 任一组件连通性检查失败 | 降级（degraded） | 至少一个组件 `disconnected` 且至少一个 `connected` | 写入 `logger.warning()` 日志（含变更前后状态、触发组件、错误详情）；更新 `_last_overall_status`；`_consecutive_failures` +1 |
| 健康（healthy） | 全部组件连通性检查失败 | 不健康（unhealthy） | 三个组件全部 `disconnected` | 写入 `logger.warning()` 日志；更新 `_last_overall_status`；`_consecutive_failures` +1 |
| 降级（degraded） | 全部组件恢复连通 | 健康（healthy） | 三个组件全部 `connected` | 写入 `logger.info()` 日志（含恢复详情）；更新 `_last_overall_status`；`_consecutive_failures` 归零 |
| 降级（degraded） | 剩余连通组件也全部故障 | 不健康（unhealthy） | 三个组件全部 `disconnected` | 写入 `logger.warning()` 日志；更新 `_last_overall_status`；`_consecutive_failures` +1 |
| 不健康（unhealthy） | 至少一个组件恢复连通 | 降级（degraded）或 健康（healthy） | 至少一个组件恢复 `connected` | 写入 `logger.info()` 日志；更新 `_last_overall_status`；若全部恢复则 `_consecutive_failures` 归零 |

> 注：(1) 以上状态均为每次请求实时计算得出的瞬时观测值，未持久化到数据库或缓存。(2) `_last_overall_status` 模块级变量用于防抖——仅在状态实际变化时才写入日志。(3) 连续失败计数器 `_consecutive_failures` 独立于 Docker HEALTHCHECK 的失败计数（`retries=3`），形成双重安全网。

### 1.9 异常与边界条件

#### 1.9.1 异常 1：PostgreSQL 连接失败

- **触发条件**：
  - `await engine.connect()` 抛出 `sqlalchemy.exc.OperationalError`（TCP 连接拒绝、DNS 解析失败）
  - `await conn.execute(text("SELECT 1"))` 超时 > 3 秒（`asyncio.wait_for` 触发 `asyncio.TimeoutError`）
  - 认证失败（用户/密码错误）导致 `sqlalchemy.exc.ProgrammingError`
- **处理策略**：
  1. 在 `_check_postgresql()` 内部捕获异常，不向上传播
  2. 记录 `latency_ms`（从 `conn.connect()` 开始到异常发生或超时的实际耗时）
  3. 构造 `ComponentHealth(status="disconnected", error="<异常类名>: <异常消息截断至 256 字符>")`
  4. 关闭已建立的连接（如果存在）：`await conn.close()`，然后 `await engine.dispose()`
  5. 将结果返回给 `asyncio.gather()`，继续等待其他组件的检查结果
  6. 若 PostgreSQL 是唯一故障组件（Redis 和 MinIO 正常）：整体状态 → `degraded`
- **重试参数**：单次请求内**不重试**（避免延长响应时间）。Docker HEALTHCHECK 的 `retries=3` 参数在容器层面提供重试安全网。

#### 1.9.2 异常 2：Redis 连接失败

- **触发条件**：
  - `redis_client.ping()` 网络超时 > 3 秒（`asyncio.wait_for` 触发 `asyncio.TimeoutError`）
  - Redis 服务未启动：`redis.exceptions.ConnectionError`
  - 认证失败：`redis.exceptions.AuthenticationError`
- **处理策略**：
  1. 在 `_check_redis()` 内部捕获异常，不向上传播
  2. 构造 `ComponentHealth(status="disconnected", error="<异常类名>: <异常消息截断至 256 字符>")`
  3. 关闭 Redis 连接：`await redis_client.aclose()`
  4. 将结果返回给 `asyncio.gather()`，继续等待其他组件的检查结果
- **重试参数**：单次请求内**不重试**。

#### 1.9.3 异常 3：MinIO 连接失败

- **触发条件**：
  - `minio_client.bucket_exists("campfire")` 网络超时 > 5 秒
  - MinIO 服务未启动：`urllib3.exceptions.MaxRetryError` 或 `httpcore.ConnectError`（MinIO SDK 底层依赖）
  - 认证失败：`minio.error.S3Error`（状态码 403）
  - Bucket 不存在：`bucket_exists()` 返回 `False`（非异常，但标记为连通但 bucket 未就绪）
- **处理策略**：
  1. `bucket_exists()` 在 `asyncio.to_thread()` 中执行以避免阻塞事件循环
  2. 在 `_check_minio()` 内部捕获异常，不向上传播
  3. 若为网络/认证异常：构造 `ComponentHealth(status="disconnected", error="<异常类名>: <异常消息截断至 256 字符>")`
  4. 若 bucket 不存在：不标记为 disconnected——`bucket_exists()` 返回 False 说明连通性和认证正常，但 bucket 未创建。标记为 `connected` 并在 error 中记录 `"bucket_not_found: campfire"` 供运维参考
- **重试参数**：单次请求内**不重试**。

#### 1.9.4 异常 4：整体健康检查超时

- **触发条件**：`asyncio.gather()` 的总等待时间超过 5 秒（整体响应的红线），但仍有组件检查未完成
- **处理策略**：
  1. 在外层使用 `asyncio.wait_for(asyncio.gather(...), timeout=5.0)` 包裹
  2. 超时时 `asyncio.gather()` 被取消——已返回的组件结果保留，未完成的组件标记为 `ComponentHealth(status="disconnected", error="timeout: overall_health_check_exceeded_5s")`
  3. 已获取部分结果的情况下，正常聚合已完成的检查结果，未完成的组件按 disconnected 处理
  4. 已在 `asyncio.gather()` 中传入 `return_exceptions=True`——取消异常不会导致已收集的结果丢失
- **重试参数**：不重试。总超时是防御性措施，正常情况下三个并发检查应在 5 秒内全部完成。

#### 1.9.5 异常 5：连续失败计数达到阈值

- **触发条件**：`_consecutive_failures` 达到 3（对应 Docker HEALTHCHECK 的 `retries=3` 和探测间隔 30 秒的设计）
- **处理策略**：
  1. 仅影响 HTTP 状态码判定——当 `_consecutive_failures >= 3` 时，即使当前整体状态为 `degraded`（非核心组件故障），也将 HTTP 状态码设为 503
  2. 不改变响应的 JSON body 内容——仍如实报告各组件状态和整体 HealthStatus
  3. 计数器的管理：每次检查任一组件失败 `_consecutive_failures += 1`；全部成功 `_consecutive_failures = 0`
  4. 计数器仅存在于进程内存中——容器重启后归零
- **重试参数**：不适用。计数器是状态追踪机制，由 Docker 层的 `retries=3` 在容器层面做出重启决策。

### 1.10 验收测试场景

#### 1.10.1 正向测试 1：全部组件健康

- **场景**：PostgreSQL、Redis、MinIO 三个基础服务均正常运行且可连通
- **Given**: 所有服务已启动——PostgreSQL 接受连接且 `SELECT 1` 正常返回；Redis 响应 `PING` 返回 `True`；MinIO 的 `campfire` bucket 存在
- **When**: 发送 `GET /health` 请求（不带认证头部）
- **Then**:
  - HTTP 状态码为 **200 OK**
  - 响应 JSON 满足以下断言：
    - `status == "healthy"`
    - `components.postgresql.status == "connected"`，`components.postgresql.error == null`
    - `components.redis.status == "connected"`，`components.redis.error == null`
    - `components.minio.status == "connected"`，`components.minio.error == null`
    - `version` 为非空字符串
    - `uptime_seconds >= 0`
    - `timestamp` 为合法的 ISO 8601 字符串

#### 1.10.2 正向测试 2：/ready 端点仅验证 PostgreSQL

- **场景**：PostgreSQL 可连通，但 Redis 和 MinIO 尚未启动（模拟容器启动阶段）
- **Given**: PostgreSQL 正常——`SELECT 1` 返回结果；Redis 和 MinIO 不可达
- **When**: 发送 `GET /ready` 请求
- **Then**:
  - HTTP 状态码为 **200 OK**（因为 PostgreSQL 连通）
  - 响应 JSON 满足：
    - `ready == true`
    - `database.status == "connected"`
    - 响应体中**不包含** Redis 和 MinIO 的状态字段

#### 1.10.3 异常测试 1：单组件故障（Redis 断开）

- **场景**：Redis 服务因网络问题无法连接，PostgreSQL 和 MinIO 正常
- **Given**: PostgreSQL 和 MinIO 正常；Redis 服务已停止或网络不通（Mock Redis 客户端 `ping()` 抛出 `ConnectionError`）
- **When**: 发送 `GET /health` 请求
- **Then**:
  - HTTP 状态码为 **503 Service Unavailable**
  - 响应 JSON 满足：
    - `status == "degraded"`
    - `components.postgresql.status == "connected"`
    - `components.redis.status == "disconnected"`，`components.redis.error` 包含 `"ConnectionError"`
    - `components.minio.status == "connected"`
  - 结构化日志中出现一条 WARNING 级别日志，包含状态从 `"healthy"` 变为 `"degraded"`

#### 1.10.4 异常测试 2：全部组件故障

- **场景**：PostgreSQL、Redis、MinIO 全部不可达（模拟宿主机网络故障）
- **Given**: 三个服务全部不可达（Mock 全部三个客户端抛异常）
- **When**: 发送 `GET /health` 请求
- **Then**:
  - HTTP 状态码为 **503 Service Unavailable**
  - 响应 JSON 满足：
    - `status == "unhealthy"`
    - `components.postgresql.status == "disconnected"`
    - `components.redis.status == "disconnected"`
    - `components.minio.status == "disconnected"`
    - 三个组件的 `error` 字段均非空

#### 1.10.5 异常测试 3：非 GET 方法请求拒绝

- **场景**：使用 POST 方法请求 `/health` 端点
- **Given**: API 服务正常运行
- **When**: 发送 `POST /health` 请求
- **Then**:
  - HTTP 状态码为 **405 Method Not Allowed**
  - 响应体中包含 `Allow` 头部，值为 `GET`

#### 1.10.6 异常测试 4：状态变更防抖

- **场景**：连续两次健康检查结果相同（状态未变化），不应重复记录日志
- **Given**: 第一次检查 `_last_overall_status = "healthy"`，当前检查结果也为 `healthy`
- **When**: 执行 `check_all()` 并聚合结果
- **Then**:
  - 不写入新的结构化日志（`logger.warning()` 和 `logger.info()` 均不被调用）
  - `_last_overall_status` 保持为 `"healthy"`

### 1.11 注意事项与禁止行为（编码层面）

1. **[约束：连接资源必须释放]** 每次健康检查请求中创建的所有数据库连接、Redis 连接、MinIO 客户端在请求结束后必须显式关闭/释放。使用 `try/finally` 或 `async with` 确保无论检查成功或失败，连接资源均被归还。PG 引擎调用 `await engine.dispose()`，Redis 客户端调用 `await redis_client.aclose()`。**禁止**依赖 GC 回收连接。

2. **[约束：异常不向上传播]** `_check_postgresql()`、`_check_redis()`、`_check_minio()` 三个函数最外层必须有 `try/except Exception as e:` 捕获所有异常并转为 `ComponentHealth(status="disconnected", error=str(e)[:256])`。**禁止**让数据库驱动或网络层面的异常传播到路由层——健康检查请求不应因一个组件的故障而返回 500。

3. **[易错点：asyncio.gather 的 return_exceptions=True]** 必须使用 `asyncio.gather(*checks, return_exceptions=True)`。若遗漏 `return_exceptions=True`，第一个失败的检查会立即取消其他所有进行中的检查，导致响应中只有部分组件的结果。

4. **[易错点：MinIO 客户端的同步调用]** MinIO Python SDK 的 `bucket_exists()` 是同步阻塞调用。必须在 `asyncio.to_thread()` 中执行以避免阻塞 FastAPI 事件循环。同时将 `asyncio.wait_for()` 应用于 `asyncio.to_thread()` 的包装以控制超时。

5. **[易错点：独立引擎的惰性初始化]** `create_async_engine()` 本身不立即建立 TCP 连接——真正的连接在 `engine.connect()` 时建立。健康检查的计时（`latency_ms`）应从 `engine.connect()` 开始计算，而非从 `create_async_engine()` 开始。

6. **[禁止行为：不得导入业务模块]** 健康检查路由文件（`health.py`）禁止导入任何业务层的 Service/Repository/Model 类（如 `from py_db.repositories.user_repository import UserRepository`）。健康检查仅依赖基础设施层的 `py_config`、`py_logger` 和原生客户端。

7. **[禁止行为：不得修改响应格式以迎合特定消费者]** `/health` 的 JSON 响应格式由 `HealthCheckResponse` 契约严格定义，不得为适配某个监控工具或告警平台而增删字段。所有消费方通过解读同一份契约的字段完成集成。

8. **[偷懒红线]** 禁止写 `try: ... except: pass` 吞掉异常不做任何记录。每个捕获的异常至少要：记录 `error` 字段到 `ComponentHealth` + 在日志中写入异常类名和消息。绝对禁止以"这个很简单"为由跳过状态变更防抖逻辑或连续失败计数器的实现。

### 1.12 文档详细度自检清单

- [ ] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成编码
- [ ] 无偷懒表述：全文搜索并消除 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [ ] 类型定义完整：每个 Pydantic 字段都有 `description` + `examples` + 约束（`min_length`/`max_length`/`ge`/`le`/`pattern` 等）
- [ ] 逻辑步骤完整：每个步骤都有操作对象、具体操作、输入来源、输出去向、失败行为
- [ ] 异常处理完整：每种异常都有精确的触发阈值、逐步处理策略、精确重试参数
- [ ] 无隐藏假设：所有默认值来源、条件分支、业务规则都已显式写出
- [ ] 技术栈绑定明确：必须使用和禁止使用的项均已列出，且与项目技术栈设计文档保持一致
- [ ] 意图一致性：已确认技术实现与已冻结的意图文档一致

### 1.14 外部接口契约清单

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| ComponentStatus | `docs/contracts/OBS-04/ComponentStatus.json` | shared-enum | draft | OBS-04 | — |
| HealthStatus | `docs/contracts/OBS-04/HealthStatus.json` | shared-enum | draft | OBS-04 | OBS-03 |
| ComponentHealth | `docs/contracts/OBS-04/ComponentHealth.json` | output | draft | OBS-04 | — |
| HealthCheckResponse | `docs/contracts/OBS-04/HealthCheckResponse.json` | output | draft | OBS-04 | DEPLOY-01, OBS-03 |
| ReadinessResponse | `docs/contracts/OBS-04/ReadinessResponse.json` | output | draft | OBS-04 | DEPLOY-01 |
| HealthCheckProbe | `docs/contracts/DEPLOY-01/HealthCheckProbe.json` | shared-model | draft | DEPLOY-01 | OBS-04（复用） |
| ContainerServiceName | `docs/contracts/DEPLOY-01/ContainerServiceName.json` | shared-enum | draft | DEPLOY-01 | OBS-04（复用） |
| AppSettings | `docs/contracts/DEPLOY-05/AppSettings.json` | output | draft | DEPLOY-05 | OBS-04（复用） |
| LogEntry | `docs/contracts/OBS-01/LogEntry.json` | output | draft | OBS-01 | OBS-04（复用） |

### 1.15 意图一致性声明

- **配套意图文档**：`OBS-04-健康检查-意图文档.md`
- **冻结时间**：2026-05-26 22:48:26
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致
  - [x] 本落地规范中的状态机实现与意图文档中的状态业务定义一致
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围
- **偏差说明**：无偏差，技术实现与意图文档完全一致。8 项技术决策项（路由注册方式、超时时间、并发执行策略、数据模型命名、Docker HEALTHCHECK 集成、测试策略、日志告警触发方式、连接池策略）均已按设计文档 v1.0 确定的方案落地。

---

## 【已锁定】

### 1.3 输入定义（精确类型 / 或契约引用）

**HTTP 请求**
- **HTTP 方法**：`GET`（仅此方法，其他方法返回 405）
- **请求路径**：`/health`（主路径）或 `/api/v1/health`（别名）用于健康检查；`/ready`（主路径）或 `/api/v1/ready`（别名）用于启动就绪探针
- **请求头**：`User-Agent` 可选，用于标识调用来源（Docker HEALTHCHECK → `"Docker-HealthCheck/1.0"`；外部监控 → 自定义字符串；人工 → `"curl/8.0"` 等）
- **请求体**：无（GET 请求，不接受 Body）
- **查询参数**：无
- **认证**：不需要（健康检查是项目中唯一豁免 JWT 认证的公开端点）

本模块不定义新的输入契约类型——所有输入为 HTTP GET 请求，无需请求体模型。连接所需配置字段（`DATABASE_URL`、`REDIS_URL`、`MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`）通过消费 DEPLOY-05 的 `AppSettings` 契约获取。

### 1.4 输出定义（精确类型 / 或契约引用）

**HealthCheckResponse**
- 【契约引用】`docs/contracts/OBS-04/HealthCheckResponse.json`
- 本模块作为该契约的定义方
- 消费方：DEPLOY-01（Docker HEALTHCHECK 集成）、OBS-03（告警规则引擎）

**ReadinessResponse**
- 【契约引用】`docs/contracts/OBS-04/ReadinessResponse.json`
- 本模块作为该契约的定义方
- 消费方：DEPLOY-01（容器启动就绪判定）

**ComponentHealth**
- 【契约引用】`docs/contracts/OBS-04/ComponentHealth.json`
- 本模块作为该契约的定义方
- 内嵌于 `HealthCheckResponse.components.*` 和 `ReadinessResponse.database` 中，无独立的外部消费方

**HealthStatus**
- 【契约引用】`docs/contracts/OBS-04/HealthStatus.json`
- 本模块作为该契约的定义方
- 消费方：OBS-03（告警通知模块，基于 HealthStatus 变化判定是否触发告警）

**ComponentStatus**
- 【契约引用】`docs/contracts/OBS-04/ComponentStatus.json`
- 本模块作为该契约的定义方
- 内嵌于 `ComponentHealth.status` 中，无独立的外部消费方

### 1.6 接口契约（对外暴露的公共接口）

#### 1.6.1 接口 1：get_health — 系统整体健康检查

```python
async def get_health(
    request: Request,
) -> JSONResponse:
    """
    执行系统整体健康检查，并发探测 PostgreSQL、Redis、MinIO 三个基础服务的连通性。

    每次请求实时执行全部三个组件的连通性验证，不依赖缓存或上次检查结果。
    返回 JSON 格式的健康状态报告，包含整体状态、各组件详情和检查时间戳。

    HTTP 状态码：
        - 200 OK：status == "healthy"
        - 503 Service Unavailable：status == "degraded" 或 "unhealthy"

    Args:
        request: FastAPI Request 对象，用于提取 User-Agent 头部作为调用来源标识

    Returns:
        JSONResponse: 响应体符合 HealthCheckResponse 契约

    Raises:
        不向上抛出异常——所有组件级异常在内部捕获并转为 ComponentHealth 中的 error 字段。
        若所有检查均异常失败，返回 503 且 status="unhealthy"，不返回 500。

    Side Effects:
        - 创建并释放三个独立的连接（PG AsyncEngine、Redis 短连接、MinIO 客户端）
        - 状态变更时通过 py_logger 写入结构化日志（WARNING 或 INFO 级别）
        - 更新模块级内存变量 _last_overall_status 和 _consecutive_failures

    Idempotency:
        健康检查天然幂等——纯只读操作，不修改任何数据或状态（业务数据、缓存键值、对象存储对象）。
        同一请求多次调用返回一致的连通性状态（除时间戳外的字段）。

    Thread Safety:
        本函数使用模块级变量 _last_overall_status 和 _consecutive_failures。
        在 asyncio 单线程事件循环中，await 之间的代码是原子的——不存在竞态条件。
        不适用于多 worker 进程场景（每个 worker 进程维护自己的状态变量，互不影响）。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `get_health` —— 语义化，描述"获取系统健康状态"的业务动作 |
| **HTTP 方法** | GET |
| **路由路径** | `/health`（主）、`/api/v1/health`（别名） |
| **输入类型** | `Request`（FastAPI Request 对象，无请求体模型） |
| **输出类型** | `JSONResponse`（响应体符合 `HealthCheckResponse` 契约） |
| **成功状态码** | 200（全部健康） |
| **失败状态码** | 503（部分或全部不健康） |
| **异常类型** | 不向上抛出——所有组件异常在内部捕获（见 `1.9 异常与边界条件`） |
| **副作用** | 创建/释放连接、状态变更日志、更新内存变量 |
| **幂等性** | 天然幂等——纯只读，无数据修改 |
| **并发安全** | asyncio 单线程安全（模块级变量的读写均在 await 之间完整执行） |

#### 1.6.2 接口 2：get_ready — 启动就绪探针

```python
async def get_ready(
    request: Request,
) -> JSONResponse:
    """
    检查服务是否就绪，仅验证 PostgreSQL 组件的连通性（不检查 Redis 和 MinIO）。

    用于容器启动阶段的就绪判定。在数据库迁移（DEPLOY-04）执行期间，Redis 和 MinIO
    可能尚未就绪——此端点提供精确的就绪信号，避免容器在启动期间被 Docker HEALTHCHECK
    错误标记为 unhealthy 并触发重启。

    HTTP 状态码：
        - 200 OK：PostgreSQL 连通
        - 503 Service Unavailable：PostgreSQL 不连通

    Args:
        request: FastAPI Request 对象

    Returns:
        JSONResponse: 响应体符合 ReadinessResponse 契约

    Raises:
        不向上抛出异常——PostgreSQL 连接异常在内部捕获并转为 ReadinessResponse 中的
        database.error 字段。

    Side Effects:
        - 创建并释放 PostgreSQL 独立连接
        - 状态变更时通过 py_logger 写入结构化日志

    Idempotency:
        纯只读操作，天然幂等。

    Thread Safety:
        asyncio 单线程安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `get_ready` —— 语义化，描述"检查服务就绪状态"的业务动作 |
| **HTTP 方法** | GET |
| **路由路径** | `/ready`（主）、`/api/v1/ready`（别名） |
| **输入类型** | `Request`（FastAPI Request 对象，无请求体模型） |
| **输出类型** | `JSONResponse`（响应体符合 `ReadinessResponse` 契约） |
| **成功状态码** | 200（PostgreSQL 连通） |
| **失败状态码** | 503（PostgreSQL 不连通） |
| **异常类型** | 不向上抛出——PostgreSQL 异常在内部捕获 |
| **副作用** | 创建/释放 PostgreSQL 连接，写入状态变更日志 |
| **幂等性** | 天然幂等 |
| **并发安全** | asyncio 单线程安全 |

### 1.7 依赖与集成接口（本模块调用的外部接口）

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 关系型数据库 | PostgreSQL 17.x | `sqlalchemy.ext.asyncio.create_async_engine(settings.DATABASE_URL, pool_size=1, max_overflow=0)` → `engine.connect()` → `conn.execute(text("SELECT 1"))` | 验证 PostgreSQL 连通性（TCP 连接 + 认证 + 查询执行三层） | `docs/篝火智答-技术栈设计.md` §6.3；`docs/篝火智答-项目结构.md` §6.1 packages/py-db/ |
| 内存缓存 | Redis 7.x | `redis.asyncio.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=3)` → `await client.ping()` | 验证 Redis 连通性（TCP 连接 + 协议级 PING） | `docs/篝火智答-技术栈设计.md` §6.3；`docs/篝火智答-项目结构.md` §6.1 packages/py-cache/ |
| 对象存储 | MinIO | `Minio(settings.MINIO_ENDPOINT, access_key=..., secret_key=..., secure=False)` → `minio_client.bucket_exists("campfire")`（在 `asyncio.to_thread()` 中执行） | 验证 MinIO 连通性（TCP 连接 + 认证 + 基本 I/O） | `docs/篝火智答-技术栈设计.md` §6.3；`docs/篝火智答-项目结构.md` §6.1 packages/py-storage/ |
| 结构化日志 | OBS-01 py_logger | `py_logger.core.logger.info(event, extra={...})`、`py_logger.core.logger.warning(event, extra={...})` | 状态变更时写入结构化日志（含变更前后状态、触发组件、错误详情） | `docs/篝火智答-项目结构.md` §6.1 packages/py-logger/ |
| 环境配置 | DEPLOY-05 py_config | `py_config.config.settings.DATABASE_URL`、`.REDIS_URL`、`.MINIO_ENDPOINT`、`.MINIO_ACCESS_KEY`、`.MINIO_SECRET_KEY` | 获取三个基础服务的连接参数 | `docs/篝火智答-项目结构.md` §6.1 packages/py-config/ |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| DEPLOY-01 容器编排 | `HealthCheckProbe` 契约（`docs/contracts/DEPLOY-01/HealthCheckProbe.json`）：`interval=30s, timeout=10s, retries=3, start_period=60s` | 引用 Docker HEALTHCHECK 探针参数，为本模块的连续失败计数器提供配置依据 | ✅ 已落地（DEPLOY-01 落地规范已冻结） |
| DEPLOY-05 环境配置管理 | `AppSettings` 契约（`docs/contracts/DEPLOY-05/AppSettings.json`）：消费 `DATABASE_URL`、`REDIS_URL`、`MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY` | 获取组件连接参数 | ✅ 已落地（DEPLOY-05 落地规范已冻结） |
| OBS-01 结构化日志 | `LogEntry` 契约（`docs/contracts/OBS-01/LogEntry.json`）：通过 `extra` 字段传递组件级别详情 | 健康状态变更时写入结构化日志 | ✅ 已落地（OBS-01 落地规范已冻结） |
| OBS-03 告警通知 | `HealthStatus` 枚举（`docs/contracts/OBS-04/HealthStatus.json`）：本模块定义，OBS-03 消费 | 下游告警模块基于 HealthStatus 枚举值变化触发告警通知 | ⏭️ 待落地（OBS-03 尚未设计；本模块仅提供枚举值，告警触发逻辑由 OBS-03 负责） |
