## 1 功能点：AUTH-04 五级RBAC鉴权 — 落地规范

> **文档生成时间**：2026-05-26 21:31:57 (Asia/Shanghai)
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-26 21:31:57` | AI Assistant | 初始版本，基于设计文档 v1.0 和契约协调报告生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `AUTH-04-五级RBAC鉴权-设计文档.md`。
> **流水线上下文**：本落地规范基于已冻结的 `AUTH-04-五级RBAC鉴权-意图文档.md`（冻结于 `2026-05-26 20:38:03`）编写。技术实现必须与意图文档中的业务定义保持一致。

---

### 1.1 技术栈绑定

> 【对内实现】

- **必须使用**：
  - Python `>=3.11` — 项目统一运行时
  - FastAPI `>=0.115` — API 路由与 Depends 依赖注入系统，`require_role` 通过 `Depends()` 注入到路由端点
  - Pydantic `>=2.0` — 入参校验与类型定义，使用 `BaseModel` + `Field()` 约束
  - `python-jose` — JWT Token 解析（从 `request.state.user` 中提取 `roles` 字段）
  - Redis `>=7.x` — 角色变更黑名单存储，AUTH-04 负责定义 Key 模式（`token_blacklist:{jti}`）和 TTL（900s）
  - `structlog` 或 Python `logging` — 结构化日志记录，通过 `packages/py-logger/` 统一入口
  - `packages/py-config` — 读取 `JWT_SECRET_KEY`、`JWT_ALGORITHM`、`REDIS_URL` 等安全配置
  - `redis-py` (`>=5.0`) — Redis 客户端，用于黑名单 Key 的写入（角色变更时）和查询（JWT 校验时）

- **禁止使用**：
  - 禁止使用 ASGI 中间件实现权限校验 — 权限校验必须通过 FastAPI `Depends()` 依赖注入，粒度精确到单个路由端点
  - 禁止在拒绝响应中返回权限规则细节（如 `expected_role`、`required_level`） — 违反意图文档 §1.11 约束 5（信息最小化约束）
  - 禁止在业务模块的 Service 或路由处理函数中重复实现 `get_masked_phone()` 调用 — 手机号脱敏必须在 SEC-01 响应脱敏中间件层统一处理
  - 禁止在 JWT payload 或数据库中使用中文角色值 — 枚举值统一使用英文小写（`family`/`teacher`/`expert`/`admin`/`maintainer`）
  - 禁止在路由 Depends 中跳过 `get_current_user` 直接使用 `require_role` — `require_role` 依赖 `request.state.user.roles`

### 1.2 文件归属

> 【对内实现】

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| RBAC 核心实现 | `packages/py-auth/rbac.py` | `require_role()` 和 `get_masked_phone()` 的实现位置，包含 `UserRole` 枚举定义 |
| Pydantic Schema | `packages/py-schemas/py_schemas/auth.py` | `UserRole` 枚举的 Pydantic 定义（含 level/display_name 属性）、`PermissionDeniedResponse` 响应模型 |
| Redis 黑名单操作 | `packages/py-auth/blacklist.py` | Redis 黑名单 Key 的写入（`add_to_blacklist(jti)`）和查询（`is_blacklisted(jti) -> bool`）函数 |
| 单元测试 | `apps/api-server/tests/auth/test_rbac.py` | `require_role()` 和 `get_masked_phone()` 的单元测试 |
| 集成测试 | `apps/api-server/tests/auth/test_auth_flow.py` | 完整的鉴权流程测试（JWT → get_current_user → require_role） |

### 1.3 输入定义

> 【已锁定】对外接口类型使用契约引用。

**require_role 参数**（FastAPI Depends 注入时的输入参数）
- 【契约引用】`docs/contracts/AUTH-04/require_role.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-01~08、CASE-01~09、TICK-01~09、PROF-05、KNOW-01~07

**get_masked_phone 参数**（被 SEC-01 调用时的输入参数）
- 【契约引用】`docs/contracts/AUTH-04/get_masked_phone.json`
- 本模块作为该契约的定义方
- 消费方：SEC-01（响应脱敏中间件）

**UserRole 枚举**（全平台共享的角色类型）
- 【契约引用】`docs/contracts/AUTH-04/UserRole.json`
- 本模块作为该契约的定义方
- 消费方：KNOW-01、SEC-01、CSLT-01~08、CASE-01~09、TICK-01~09、PROF-05、AUTH-02

### 1.4 输出定义

> 【已锁定】对外接口类型使用契约引用。

**require_role 输出**（函数无返回，权限拒绝时抛出 HTTPException）
- 权限通过：函数正常返回 `None`，控制流进入路由处理函数
- 权限拒绝：抛出 `HTTPException(status_code=403)`，响应体为 `PermissionDeniedResponse`
- 【契约引用】`docs/contracts/AUTH-04/PermissionDeniedResponse.json`

**get_masked_phone 输出**
- 管理员角色（admin/maintainer）：返回原始 `phone` 字符串，不做脱敏处理
- 其他角色：返回脱敏格式字符串（保留前3位和后4位，中间替换为 `****`），例如 `"138****5678"`
- 返回类型：`str`

### 1.5 核心逻辑步骤

> 【对内实现】

#### 1.5.1 require_role 核心逻辑

1. **步骤 1：验证前置依赖就绪**
   - **操作对象**：`request.state.user` 对象（由 AUTH-02 `get_current_user` Depends 注入）
   - **具体操作**：检查 `request.state.user` 是否存在且包含 `roles` 属性
   - **输入来源**：FastAPI 请求上下文的 `state.user`，由上游 `Depends(get_current_user)` 填充
   - **输出去向**：校验通过后进入步骤 2；校验失败进入异常处理（抛出 HTTP 401）
   - **失败行为**：`request.state.user` 不存在或 `user.roles` 为空 → 抛出 `HTTPException(401, detail="未登录或角色信息缺失，请重新登录")`，不进入后续步骤

2. **步骤 2：确定校验模式**
   - **操作对象**：`require_role` 函数参数 `min_level` 和 `exact_roles`
   - **具体操作**：
     - 若 `min_level` 非空 → 采用层级累加模式，进入步骤 3a
     - 若 `exact_roles` 非空 → 采用精确模式，进入步骤 3b
     - 若两者均为空 → 进入步骤 3a，使用默认 min_level=UserRole.FAMILY
   - **输入来源**：调用方在路由 Depends 中声明的参数，如 `Depends(require_role(min_level=UserRole.EXPERT))`
   - **输出去向**：确定模式后进入对应的校验步骤
   - **失败行为**：无失败路径（两种模式的判定不依赖外部状态）

3. **步骤 3a：层级累加模式校验**
   - **操作对象**：`request.state.user.roles` 角色列表 + `min_level` 参数
   - **具体操作**：
     - 从 `user.roles` 中提取所有角色的 `level` 值
     - 取最高层级 `max_level = max(role.level for role in user_roles)`
     - 比较 `max_level >= min_level.level`
   - **输入来源**：步骤 1 的 `user.roles` 和步骤 2 的 `min_level` 参数
   - **输出去向**：比较通过 → 正常返回 `None`，控制流进入路由处理函数；比较失败 → 进入步骤 4
   - **失败行为**：`max_level < min_level.level` → 进入步骤 4

4. **步骤 3b：精确模式校验**
   - **操作对象**：`request.state.user.roles` 角色列表 + `exact_roles` 参数
   - **具体操作**：检查 `user.roles` 中是否存在任意一个角色在 `exact_roles` 集合中，即 `set(user_roles) & set(exact_roles)` 非空
   - **输入来源**：步骤 1 的 `user.roles` 和步骤 2 的 `exact_roles` 参数
   - **输出去向**：命中 → 正常返回 `None`；未命中 → 进入步骤 4
   - **失败行为**：`set(user_roles) & set(exact_roles)` 为空 → 进入步骤 4

5. **步骤 4：权限拒绝处理**
   - **操作对象**：`require_role` 函数返回
   - **具体操作**：
     - 记录结构化日志：`logger.warning("permission_denied", user_id=request.state.user.id, target_route=request.url.path, required_roles=..., actual_roles=user.roles, timestamp=..., trace_id=...)`
     - 通过 `packages/py-logger` 输出，事件类型标记为 `permission_denied`
     - 抛出 `HTTPException(status_code=403, detail="当前角色无权执行此操作，如需权限请联系管理员")`
   - **输入来源**：步骤 3a 或 3b 的校验失败结果
   - **输出去向**：异常向上传播给 FastAPI 异常处理器，返回 HTTP 403 响应
   - **失败行为**：日志记录失败不影响异常抛出（使用 `try/exclude` 确保主路径不因日志失败而中断）

#### 1.5.2 get_masked_phone 核心逻辑

1. **步骤 1：提取用户角色层级**
   - **操作对象**：`user_roles: list[UserRole]` 参数
   - **具体操作**：提取 `user_roles` 中所有角色的 `level` 值，取最大值 `max_level = max(role.level for role in user_roles)`
   - **输入来源**：调用方传入的 `user_roles` 参数（由 SEC-01 响应脱敏中间件在序列化阶段提供）
   - **输出去向**：`max_level` 值进入步骤 2 的判定分支
   - **失败行为**：`user_roles` 为空列表 → 默认按非管理员处理（走脱敏分支，步骤 2b）

2. **步骤 2a：管理员角色 — 返回完整手机号**
   - **操作对象**：`phone: str` 参数
   - **具体操作**：如果 `max_level >= 4`（即 `max_level` 对应 admin 或 maintainer），直接返回原始 `phone` 字符串
   - **输入来源**：步骤 1 的 `max_level` + 调用方传入的 `phone` 参数
   - **输出去向**：返回原始手机号，SEC-01 在序列化时使用
   - **失败行为**：无失败路径

3. **步骤 2b：非管理员角色 — 返回脱敏手机号**
   - **操作对象**：`phone: str` 参数
   - **具体操作**：如果 `max_level < 4`，执行脱敏：`phone[:3] + "****" + phone[-4:]`，例如 `"13812345678"` 变为 `"138****5678"`
   - **输入来源**：步骤 1 的 `max_level` + 调用方传入的 `phone` 参数
   - **输出去向**：返回脱敏手机号，SEC-01 在序列化时使用
   - **失败行为**：`phone` 长度不足 11 位或格式异常 → 返回 `"****"`（四星掩码），同时在日志中记录警告

#### 1.5.3 Token 黑名单查询（AUTH-02 get_current_user 联动 — 本模块定义查询契约）

1. **步骤 1：解析 JWT 获取 jti**
   - **操作对象**：`access_token` 字符串
   - **具体操作**：调用 `python-jose` 的 `decode()` 函数解码 JWT，提取 `jti` claim
   - **输入来源**：请求头 `Authorization: Bearer <token>`
   - **输出去向**：解析后的 `jti` 字符串进入步骤 2；Token 过期或签名无效进入异常处理
   - **失败行为**：`jwt.exceptions.ExpiredSignatureError` → 返回 HTTP 401 "Token 已过期"；`jwt.exceptions.JWTError` → 返回 HTTP 401 "Token 无效"

2. **步骤 2：查询 Redis 黑名单**
   - **操作对象**：Redis 连接（通过 `packages/py-config` 读取 `REDIS_URL` 获取连接参数）
   - **具体操作**：执行 `redis_client.get(f"token_blacklist:{jti}")`，检查返回值是否非空
   - **输入来源**：步骤 1 的 `jti` 字符串
   - **输出去向**：非空（命中黑名单） → 返回 HTTP 401 "Token 已被撤销，请重新登录"；空（未命中） → 正常放行
   - **失败行为**：`Redis.ConnectionError` → 执行 fail-open 降级，跳过黑名单查询，正常放行。记录日志 `logger.warning("redis_connection_failed", strategy="fail_open")`

### 1.6 接口契约

> 【已锁定】对外接口使用语义化命名。

#### 1.6.1 require_role

```python
async def require_role(
    min_level: UserRole | None = None,
    exact_roles: list[UserRole] | None = None,
) -> None:
    """
    路由级权限校验 FastAPI Depends 函数。
    基于当前用户角色，检查是否满足目标路由的角色要求。

    两种模式（互斥）：
    - 层级累加模式：用户最高角色层级 >= min_level 层级值时放行
    - 精确模式：用户角色必须在 exact_roles 集合内才放行

    Args:
        min_level: 层级累加模式的最小角色要求。与 exact_roles 互斥。
        exact_roles: 精确模式的角色白名单。与 min_level 互斥。

    Returns:
        None: 校验通过，控制流进入路由处理函数

    Raises:
        HTTPException(401): request.state.user 不存在或 roles 为空
        HTTPException(403): 权限校验未通过（响应体为 PermissionDeniedResponse）

    Side Effects:
        - 权限拒绝时通过 packages/py-logger 记录结构化日志
        - 日志事件类型: permission_denied

    Prerequisites:
        - 必须在 get_current_user Depends 之后执行
        - 路由 Depends 声明顺序: Depends(get_current_user) → Depends(require_role(...))
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `require_role` — FastAPI Depends 可调用对象 |
| **输入类型** | `min_level: UserRole | None`, `exact_roles: list[UserRole] | None`（详见 1.3 输入定义） |
| **输出类型** | `None | HTTPException`（详见 1.4 输出定义） |
| **异常类型** | `HTTPException(401/403)`（详见 1.9 异常与边界条件） |
| **副作用** | 权限拒绝时记录审计日志 |
| **幂等性** | 每次调用独立校验，相同输入始终产生相同结果（无状态） |
| **并发安全** | 纯函数 + 无状态，线程安全 |

#### 1.6.2 get_masked_phone

```python
async def get_masked_phone(
    phone: str,
    user_roles: list[UserRole],
) -> str:
    """
    手机号字段级脱敏判定纯函数。
    根据用户角色判定手机号的可见性并执行脱敏。

    Args:
        phone: 原始手机号字符串（11位数字）
        user_roles: 当前用户的角色列表

    Returns:
        str: 管理员角色返回原始手机号；其他角色返回脱敏格式（138****5678）

    Raises:
        无异常抛出（非管理员角色但手机号格式异常时返回 "****" 并记日志）

    Side Effects:
        phone 格式异常时记录 warning 日志

    Idempotency:
        相同输入始终产生相同输出

    Thread Safety:
        纯函数，完全线程安全
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `get_masked_phone` — 手机号脱敏判定函数 |
| **输入类型** | `phone: str`, `user_roles: list[UserRole]`（详见 1.3 输入定义） |
| **输出类型** | `str`（详见 1.4 输出定义） |
| **异常类型** | 不抛出异常（格式异常时降级返回 `"****"`） |
| **副作用** | 手机号格式异常时记录 warning 日志 |
| **幂等性** | 相同输入产生相同输出 |
| **并发安全** | 纯函数，完全线程安全 |

### 1.7 依赖与集成接口

> 【已锁定】

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 缓存服务 | Redis 7.x | `redis_client.get(key: str) -> str | None` | 黑名单查询：`token_blacklist:{jti}` Key 是否存在 |
| 缓存服务 | Redis 7.x | `redis_client.setex(key: str, ttl: int, value: str) -> bool` | 黑名单写入：角色变更时写入被撤销 Token 的 jti |
| 日志系统 | packages/py-logger | `logger.info("event", key=value)` 或 `logger.warning(...)` | 权限拒绝事件的结构化日志记录 |
| 配置服务 | packages/py-config | `config.JWT_SECRET_KEY`, `config.JWT_ALGORITHM`, `config.REDIS_URL` | 读取安全配置和 Redis 连接参数 |
| 令牌校验 | python-jose | `jose.jwt.decode(token, key, algorithms)` | JWT 解析，提取 sub（用户 ID）、roles（角色列表）、jti（Token ID） |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| AUTH-02 | `get_current_user` Depends → `request.state.user.roles` | 提供当前用户的角色列表 | 待落地 |
| AUTH-02 | `get_current_user` Depends → Redis `token_blacklist:{jti}` 查询 | JWT 校验时查询黑名单，角色变更后 Token 实时失效 | 待落地 |
| SEC-01 | 响应脱敏中间件（`masking.py`）调用 `get_masked_phone()` | 在响应序列化阶段自动对手机号字段脱敏 | ✅ 已落地 |

### 1.8 状态机

> 【对内实现】

本功能点不涉及状态流转，故无需状态机。权限校验为无状态同步查询，每次请求独立校验，不维护校验状态。

唯一的"状态"概念存在于 Redis 黑名单中——被撤销的 Token jti 有明确的 TTL（900 秒），过期后自动清除。这是键过期行为，非业务状态机。

### 1.9 异常与边界条件

> 【对内实现】

#### 1.9.1 异常 1：角色权限不足（Permission Denied）

- **触发条件**：
  - 层级累加模式：用户最高角色层级 `max_level < min_level.level`
  - 精确模式：`set(user_roles) & set(exact_roles)` 为空
  - 用户角色不在目标资源的允许角色范围内

- **处理策略**：
  1. 在 `require_role` 函数中捕获校验失败结果
  2. 记录结构化日志：`logger.warning("permission_denied", user_id=..., target_route=request.url.path, required_roles=..., actual_roles=user.roles, timestamp=..., trace_id=...)`
  3. 抛出 `HTTPException(status_code=403, detail="当前角色无权执行此操作，如需权限请联系管理员")`
  4. FastAPI 异常处理器捕获 HTTPException 并返回 HTTP 403 响应
  5. **禁止**在响应中包含 `expected_role`、`required_level` 等权限规则细节

- **重试参数**：不重试。用户需要使用有权限的角色重新登录后再次尝试。

#### 1.9.2 异常 2：用户身份或角色信息缺失（Missing Identity）

- **触发条件**：
  - `request.state.user` 为 `None`（未经过 `get_current_user` Depends 注入）
  - `request.state.user.roles` 为 `None` 或空列表
  - JWT 解析失败（Token 过期、签名无效、格式错误）

- **处理策略**：
  1. 在 `require_role` 函数入口处检查 `request.state.user` 的存在性
  2. 若 `request.state.user` 不存在或 `roles` 为空，不进入校验逻辑
  3. 抛出 `HTTPException(status_code=401, detail="未登录或角色信息缺失，请重新登录")`
  4. 记录日志：`logger.warning("auth_context_missing", target_route=request.url.path, trace_id=...)`

- **重试参数**：不重试。用户需重新登录以获取完整的身份和角色信息。

#### 1.9.3 异常 3：Redis 连接失败（黑名单查询降级）

- **触发条件**：
  - `redis_client.get()` 调用抛出 `redis.exceptions.ConnectionError` 或超时
  - Redis 服务不可用或网络分区
  - Redis 连接池耗尽

- **处理策略**：
  1. 捕获 `redis.exceptions.ConnectionError` / `redis.exceptions.TimeoutError`
  2. 执行 fail-open 降级：跳过黑名单查询，正常放行当前请求
  3. 记录日志：`logger.warning("redis_connection_failed", key=f"token_blacklist:{jti}", strategy="fail_open", trace_id=...)`
  4. 旧角色 Token 继续有效直到自然过期（最多 15 分钟）
  5. 不抛出 HTTP 异常，不影响正常请求处理

- **重试参数**：单次请求内不重试（降级后直接放行）。下一个请求会重新尝试连接 Redis。

#### 1.9.4 异常 4：角色信息与数据库不一致（Stale Role）

- **触发条件**：
  - JWT payload 中的 `roles` 字段与 `PostgreSQL users` 表中的最新角色记录不一致
  - 用户的角色在 Token 签发后被管理员修改，但旧 Token 尚未过期
  - 角色变更操作已完成 Redis 黑名单写入，但用户使用旧 Token 发起请求

- **处理策略**：
  1. 在 `get_current_user` 环节（JWT 校验成功后），可选地查询 `PostgreSQL users` 表验证角色一致性
  2. 若发现不一致 → 返回 HTTP 401，响应体：`{"detail": "角色信息已变更，请重新登录"}`
  3. 记录日志：`logger.info("role_changed_force_relogin", user_id=..., old_roles=..., new_roles=...)`
  4. 用户重新登录后，签发的新 Token 携带最新角色信息

- **重试参数**：不重试。用户必须重新登录以获取携带新角色信息的 Token。

### 1.10 验收测试场景

> 【对内实现】

#### 1.10.1 正向测试 1：层级累加校验通过（高级角色访问低级资源）

- **场景**：专家用户（层级 3）访问需要老师权限（层级 2）的资源，应放行
- **Given**: 用户已登录，JWT payload 中 `roles: ["expert"]`；目标路由声明 `Depends(require_role(min_level=UserRole.TEACHER))`
- **When**: 请求到达目标路由
- **Then**:
  - `require_role` 正常返回 `None`
  - 请求进入路由处理函数
  - HTTP 响应状态码为 200（非 403）

**验证数据**：
```json
{
  "route": "POST /api/v1/cases",
  "jwt_roles": ["expert"],
  "route_required": {"min_level": "teacher"},
  "expected_result": "allow",
  "expected_status": 200
}
```

#### 1.10.2 正向测试 2：精确模式校验通过（管理员执行运维操作）

- **场景**：管理员用户（层级 4）访问需要管理员或维护人员权限的资源，应放行
- **Given**: 用户已登录，JWT payload 中 `roles: ["admin"]`；目标路由声明 `Depends(require_role(exact_roles=["admin", "maintainer"]))`
- **When**: 请求到达目标路由
- **Then**:
  - `require_role` 正常返回 `None`
  - 请求进入路由处理函数
  - HTTP 响应状态码为 200

**验证数据**：
```json
{
  "route": "POST /api/v1/admin/users/role",
  "jwt_roles": ["admin"],
  "route_required": {"exact_roles": ["admin", "maintainer"]},
  "expected_result": "allow",
  "expected_status": 200
}
```

#### 1.10.3 正向测试 3：手机号脱敏（非管理员角色）

- **场景**：专家用户查看包含手机号的响应数据，手机号字段被自动脱敏
- **Given**: 用户已登录，JWT payload 中 `roles: ["expert"]`；SEC-01 响应脱敏中间件已启用
- **When**: 请求返回的响应中包含手机号字段 `phone: "13812345678"`
- **Then**:
  - 响应中的 `phone` 字段值为 `"138****5678"`
  - 其他非手机号字段不受影响
  - HTTP 响应状态码为 200

**验证数据**：
```json
{
  "jwt_roles": ["expert"],
  "original_response": {"name": "张三", "phone": "13812345678"},
  "expected_response": {"name": "张三", "phone": "138****5678"}
}
```

#### 1.10.4 异常测试 1：角色越权访问被拒绝

- **场景**：家属用户（层级 1）访问需要专家权限（层级 3）的资源，应被拒绝
- **Given**: 用户已登录，JWT payload 中 `roles: ["family"]`；目标路由声明 `Depends(require_role(min_level=UserRole.EXPERT))`
- **When**: 请求到达目标路由
- **Then**:
  - `require_role` 抛出 `HTTPException(status_code=403)`
  - 响应体为 `{"detail": "当前角色无权执行此操作，如需权限请联系管理员"}`
  - 日志中记录了 `permission_denied` 事件

**验证数据**：
```json
{
  "route": "POST /api/v1/cases/review",
  "jwt_roles": ["family"],
  "route_required": {"min_level": "expert"},
  "expected_result": "deny",
  "expected_status": 403,
  "expected_detail": "当前角色无权执行此操作，如需权限请联系管理员"
}
```

#### 1.10.5 异常测试 2：身份信息缺失被拒绝

- **场景**：请求未携带有效的用户身份信息，应被拒绝
- **Given**: 请求头中无 `Authorization` 头或 Token 无效
- **When**: 请求到达需要权限校验的路由
- **Then**:
  - `get_current_user` Depends 抛出 `HTTPException(status_code=401)`
  - 响应体为 `{"detail": "未登录或角色信息缺失，请重新登录"}`
  - `require_role` 未被执行（Depends 链在 `get_current_user` 处中断）

**验证数据**：
```json
{
  "scenario": "missing_token",
  "headers": {},
  "expected_status": 401,
  "expected_detail": "未登录或角色信息缺失，请重新登录"
}
```

#### 1.10.6 异常测试 3：Redis 不可用时黑名单降级

- **场景**：Redis 服务不可用，但请求仍应正常放行（fail-open）
- **Given**: Redis 服务已停止；用户 Token 有效且角色未变更
- **When**: 请求到达需要权限校验的路由
- **Then**:
  - `require_role` 正常返回 `None`（角色校验不依赖 Redis）
  - `get_current_user` 中的黑名单查询因 Redis 不可用而降级（fail-open）
  - 请求正常执行，HTTP 状态码为 200
  - 日志中记录 Redis 连接失败的 warning 日志

**验证数据**：
```json
{
  "scenario": "redis_unavailable",
  "redis_status": "down",
  "jwt_roles": ["teacher"],
  "route_required": {"min_level": "teacher"},
  "expected_result": "allow",
  "expected_status": 200,
  "expected_log": "redis_connection_failed"
}
```

#### 1.10.7 异常测试 4：精确模式下运维操作隔离

- **场景**：专家用户（层级 3）尝试执行仅限管理员/维护人员的运维操作，应被拒绝
- **Given**: 用户已登录，JWT payload 中 `roles: ["expert"]`；目标路由声明 `Depends(require_role(exact_roles=["admin", "maintainer"]))`
- **When**: 请求到达运维操作路由
- **Then**:
  - `require_role` 抛出 `HTTPException(status_code=403)`
  - 专家角色（层级 3 但不在精确集合内）被拒绝
  - 响应体为 `{"detail": "当前角色无权执行此操作，如需权限请联系管理员"}`

**验证数据**：
```json
{
  "route": "POST /api/v1/admin/users/role",
  "jwt_roles": ["expert"],
  "route_required": {"exact_roles": ["admin", "maintainer"]},
  "expected_result": "deny",
  "expected_status": 403,
  "expected_detail": "当前角色无权执行此操作，如需权限请联系管理员"
}
```

### 1.11 注意事项与禁止行为（编码层面）

> 【对内实现】

1. **[Depends 链顺序]** 路由端点声明 Depends 时，`get_current_user` 必须出现在 `require_role` 之前。错误示例：`Depends(require_role(...)), Depends(get_current_user)`。正确示例：`Depends(get_current_user), Depends(require_role(...))`。

2. **[双模式互斥约束]** `require_role` 的 `min_level` 和 `exact_roles` 参数不能同时非空。如果两者都传，函数应抛出 `ValueError("min_level 和 exact_roles 参数不能同时使用")`。

3. **[枚举值大小写]** `UserRole` 枚举值必须统一使用英文小写。前端 `ts-shared` 中的角色类型与后端 `packages/py-schemas` 中的定义必须一致。禁止出现混合大小写（如 `Admin`、`Expert`）或中文值。

4. **[黑名单 Key 前缀固定]** Redis 黑名单 Key 必须统一使用 `token_blacklist:` 前缀。禁止不同模块或场景使用不同的前缀格式（如 `blacklist:`、`revoked_token:`）。

5. **[信息最小化编码红线]** 在 `require_role` 的 HTTPException 中，禁止在任何环境下（包括 debug 模式）泄露权限规则细节。响应体 `detail` 字段必须始终使用预设的固定文案。

6. **[get_masked_phone 角色判定基准]** 多角色用户场景下，脱敏判定以用户角色列表中的最高层级为准。例如用户同时持有 `["teacher", "expert"]`（教师和专家双重身份），`get_masked_phone` 使用 `max_level=3` 判定，按非管理员处理返回脱敏结果。

7. **[禁止在业务代码中嵌入脱敏逻辑]** 各业务模块的 Service 方法中禁止调用 `get_masked_phone()`。业务模块的响应应始终包含完整手机号，脱敏由 SEC-01 响应中间件统一处理。

### 1.12 文档详细度自检清单

> 【对内实现】

输出前强制自检以下项目：

- [x] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成编码
- [x] 无偷懒表述：全文已消除 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"参考其他模块"`
- [x] 类型定义完整：所有契约通过引用 `docs/contracts/AUTH-04/*.json` 提供完整字段定义
- [x] 逻辑步骤完整：3 组核心逻辑（require_role / get_masked_phone / Token 黑名单查询）均有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：4 种异常（权限不足 / 身份缺失 / Redis 降级 / 角色不一致）均有精确触发阈值、逐步处理策略、重试参数
- [x] 无隐藏假设：所有默认值来源（min_level 默认 FAMILY）、条件分支（双模式互斥）、业务规则（多角色取最高层级）均已显式写出
- [x] 技术栈绑定明确：必须使用和禁止使用的项均已列出，且与项目技术栈设计文档保持一致
- [x] 意图一致性：已确认技术实现与已冻结的 AUTH-04 意图文档一致

### 1.14 外部接口契约清单

> 【对内实现】

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| UserRole | `docs/contracts/AUTH-04/UserRole.json` | shared-enum | draft | AUTH-04 | KNOW-01, SEC-01, CSLT-01, CASE-01, TICK-01, PROF-05, AUTH-02 |
| require_role | `docs/contracts/AUTH-04/require_role.json` | input | draft | AUTH-04 | CSLT-01, CASE-01, TICK-01, PROF-05, KNOW-01 |
| get_masked_phone | `docs/contracts/AUTH-04/get_masked_phone.json` | input | draft | AUTH-04 | SEC-01 |
| TokenBlacklistKey | `docs/contracts/AUTH-04/TokenBlacklistKey.json` | shared-model | draft | AUTH-04 | AUTH-02 |
| PermissionDeniedResponse | `docs/contracts/AUTH-04/PermissionDeniedResponse.json` | error-code | draft | AUTH-04 | CSLT-01, CASE-01, TICK-01, PROF-05, KNOW-01 |

### 1.15 意图一致性声明

> 【对内实现】

- **配套意图文档**：`AUTH-04-五级RBAC鉴权-意图文档.md`
- **冻结时间**：`2026-05-26 20:38:03`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致
  - [x] 本落地规范中的状态机实现与意图文档中的状态业务定义一致（两者均为无状态）
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准（AC-01 至 AC-07）
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
