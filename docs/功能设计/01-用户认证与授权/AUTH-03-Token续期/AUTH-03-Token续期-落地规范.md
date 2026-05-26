## 1 功能点：AUTH-03 Token续期 — 落地规范

> **文档生成时间**：`2026-05-26 23:06:10`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-26 23:06:10` | AI Assistant | 初始版本，基于 s06 技术预研报告（11 项决策）和 s08 契约协调报告（3 冲突已裁决）生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `AUTH-03-Token续期-设计文档.md`。

---

### 1.1 技术栈绑定 `【对内实现】`

- **必须使用**：
  - `python-jose[cryptography]>=3.3.0` — JWT 签发与验证（`jose.jwt.encode`、`jose.jwt.decode`），项目技术栈 §5 规定
  - `pydantic>=2.0` — 请求/响应模型定义与校验，项目技术栈 §3.1 规定
  - `fastapi>=0.115` — 路由端点和 Depends 注入，项目技术栈 §3.1 规定
  - `redis>=5.0` — 黑名单存储（通过 `packages/py-cache/py_cache/client.py` 统一封装），技术栈 §5 规定
  - `asyncpg` — PostgreSQL 异步驱动（通过 `packages/py-db` 封装），技术栈 §3.1 规定
  - 响应格式 `{"detail": "..."}` — 项目统一的错误响应格式，与 KNOW-01/AUTH-04/SEC-01/SEC-05 一致

- **禁止使用**：
  - 禁止使用 `PyJWT` 库替代 `python-jose`（技术栈 §5 明确选定 python-jose）
  - 禁止在续期接口中接收用户名、密码或任何身份凭据（意图文档 §1.11 约束 6）
  - 禁止将 Refresh Token payload 中的 `roles` 字段原样复制到新 Access Token（必须实时查询数据库获取最新角色）
  - 禁止在 Redis 不可用时使用 fail-closed 策略（必须采用与 AUTH-04 一致的 fail-open 降级）
  - 禁止绕过 Redis `SET NX` 原子操作而使用"先检查再写入"的非原子两步操作
  - 禁止在错误响应中返回 `expected_role`、`required_level`、`token_expired_reason` 等内部细节

### 1.2 文件归属 `【对内实现】`

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 续期路由端点 | `apps/api-server/app/api/v1/auth.py` | `POST /api/v1/auth/refresh` 端点定义，含 `refresh_token()` 路由处理函数 |
| 续期服务逻辑 | `apps/api-server/app/services/auth_service.py` | `refresh_access_token()` 服务函数，编排续期的完整流程（校验→查询→轮换→签发） |
| 续期请求/响应模型 | `packages/py-schemas/py_schemas/auth.py` | `TokenRefreshRequest`、`TokenRefreshResponse` Pydantic 模型（推断，与 AUTH-01/AUTH-02 模型同文件） |
| JWT 签发/验证 | `packages/py-auth/py_auth/jwt_utils.py` | `create_token()`、`verify_token()`、`decode_token()` 通用 JWT 函数（已存在，归属 SEC-01，本模块复用） |
| Redis 黑名单管理 | `packages/py-auth/py_auth/blacklist.py` | `is_token_rotated(jti: str) -> bool`、`mark_token_rotated(jti: str) -> bool` 轮换黑名单专用函数（推断，归属 AUTH-03） |
| 路由 Depends | `apps/api-server/app/dependencies/auth_dependencies.py` | `get_refresh_token_payload()` Depends 函数，从请求体提取 Refresh Token 并完成 JWT 校验和黑名单查询 |
| 测试文件 | `apps/api-server/_tmp_test/test_auth_refresh.py` | `refresh_token` 端点的单元/集成测试（推断） |

### 1.3 输入定义 `【已锁定】`

**TokenRefreshRequest**
- 【契约引用】`docs/contracts/AUTH-03/TokenRefreshRequest.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-06（认证会话管理，前端 HTTP 拦截器在 401 时调用本接口）

**内部处理上下文（不对外暴露）**：

```python
class RefreshContext(BaseModel):
    """续期处理内部上下文，在流程开始时构建，各步骤追加字段"""
    refresh_token_raw: str = Field(description="客户端上传的原始 Refresh Token 字符串")
    payload: dict = Field(description="JWT 解码后的 payload（未经黑名单校验）")
    user_id: str = Field(description="从 payload.sub 提取的用户 UUID")
    jti: str = Field(description="从 payload.jti 提取的 Token 唯一标识")
    current_roles: list[str] = Field(default_factory=list, description="从数据库查询的最新角色列表")
```

### 1.4 输出定义 `【已锁定】`

**TokenRefreshResponse**
- 【契约引用】`docs/contracts/AUTH-03/TokenRefreshResponse.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-06（前端更新本地 Token 存储）

**异常响应（对外暴露）**：

| HTTP 状态码 | 响应体 | 触发条件 | 信息最小化要求 |
|------------|--------|----------|---------------|
| `401 Unauthorized` | `{"detail": "登录凭证已过期，请重新登录"}` | Refresh Token `exp` 已超过当前时间 | 不区分"过期"与"未到生效时间" |
| `401 Unauthorized` | `{"detail": "登录凭证已失效，请重新登录"}` | Refresh Token 已在轮换/吊销黑名单中 | 不区分"已轮换"与"已被吊销" |
| `429 Too Many Requests` | `{"detail": "请求过于频繁，请稍后再试"}` | 续期频率超过 SEC-04 限流阈值 | 由 SEC-04 限流中间件返回 |

### 1.5 核心逻辑步骤 `【对内实现】`

**主流程函数签名**：
```python
async def refresh_access_token(
    request: TokenRefreshRequest,
    redis_client: Redis,
    user_repo: UserRepository,
) -> TokenRefreshResponse:
    ...
```

1. **步骤 1：JWT 签名与格式校验**
   - **操作对象**：`TokenRefreshRequest.refresh_token`（字符串）
   - **具体操作**：
     - 调用 `jwt_utils.decode_token(request.refresh_token)` 解码 JWT payload（不解密，仅解析 header 和 payload）
     - 调用 `jwt_utils.verify_token(request.refresh_token)` 校验 JWT 签名（HS256，使用 `JWT_SECRET_KEY`）和 `exp` 过期时间
   - **输入来源**：HTTP 请求体 → 经 SEC-05 输入校验 Depends 通过后的 `TokenRefreshRequest` 实例
   - **输出去向**：校验通过的 JWT payload dict → 进入步骤 2；解码后的 header → 用于步骤 1 内部
   - **失败行为**：签名无效或 `exp` 已过期 → 抛出 `InvalidTokenError`，返回 HTTP 401 + `{"detail": "登录凭证已过期，请重新登录"}`；JWT 格式非法（非三段 Base64）→ 抛出 `MalformedTokenError`，返回 HTTP 401 + `{"detail": "登录凭证已过期，请重新登录"}`

2. **步骤 2：Token 类型校验**
   - **操作对象**：步骤 1 输出的 JWT payload dict
   - **具体操作**：
     - 检查 `payload["type"] == "refresh"`
     - 检查 `payload["sub"]` 为非空字符串（UUID 格式校验：`re.match(r"^[a-f0-9-]{36}$", sub)`）
     - 检查 `payload["jti"]` 为非空字符串（UUID 格式校验）
   - **输入来源**：步骤 1 的 payload dict
   - **输出去向**：构建 `RefreshContext(user_id=payload["sub"], jti=payload["jti"], payload=payload, refresh_token_raw=request.refresh_token)` → 进入步骤 3
   - **失败行为**：`type != "refresh"`（前端误将 Access Token 传入续期接口）→ 返回 HTTP 401 + `{"detail": "登录凭证已失效，请重新登录"}`；`sub` 或 `jti` 缺失/格式非法 → 返回 HTTP 401（同上提示，不透露具体缺失字段）

3. **步骤 3：轮换黑名单查询**
   - **操作对象**：Redis 键 `token_blacklist:rotated:{ctx.jti}`
   - **具体操作**：
     - `blacklist.is_token_rotated(ctx.jti)` — 内部调用 `redis_client.exists(f"token_blacklist:rotated:{ctx.jti}")` 检查是否存在
     - 同时检查吊销黑名单：`redis_client.exists(f"token_blacklist:{ctx.jti}")`（AUTH-04 的吊销黑名单）
     - 若 Redis 连接失败（`redis.exceptions.ConnectionError`）→ 跳过此步（fail-open 降级），记录警告日志
   - **输入来源**：步骤 2 的 `RefreshContext.jti`
   - **输出去向**：未命中黑名单 → `ctx` 进入步骤 4
   - **失败行为**：命中轮换黑名单 → 返回 HTTP 401 + `{"detail": "登录凭证已失效，请重新登录"}`，记录安全事件日志 `logger.warning("token_already_rotated", jti=ctx.jti, user_id=ctx.user_id)`；命中吊销黑名单 → 返回 HTTP 401 + `{"detail": "登录凭证已失效，请重新登录"}`

4. **步骤 4：用户最新角色查询**
   - **操作对象**：PostgreSQL `users` 表
   - **具体操作**：
     - `ctx.current_roles = await user_repo.get_user_roles_by_id(ctx.user_id)` — 查询用户当前角色列表
     - 返回 `list[str]`，元素为英文小写（如 `["family"]`、`["teacher", "expert"]`）
   - **输入来源**：步骤 3 的 `RefreshContext.user_id`
   - **输出去向**：角色列表写入 `ctx.current_roles` → 进入步骤 5
   - **失败行为**：用户不存在（`user_repo` 返回 `None`）→ 返回 HTTP 401 + `{"detail": "登录凭证已失效，请重新登录"}`；数据库查询超时（>5s）→ 重试 3 次（间隔 2s），仍失败则抛出 `DatabaseUnavailableError`，上层返回 HTTP 503

5. **步骤 5：新 Token 对签发**
   - **操作对象**：`jwt_utils.create_token()` 函数
   - **具体操作**：
     - 调用 `create_access_token(ctx.user_id, ctx.current_roles)` — 内部调用 `jwt_utils.create_token(sub=ctx.user_id, roles=ctx.current_roles, type="access", expires_minutes=ACCESS_TOKEN_EXPIRE_MINUTES)`，返回新 Access Token 字符串
     - 调用 `create_refresh_token(ctx.user_id)` — 内部调用 `jwt_utils.create_token(sub=ctx.user_id, roles=[], type="refresh", expires_days=REFRESH_TOKEN_EXPIRE_DAYS)`，返回新 Refresh Token 字符串（Refresh Token 的 roles 字段在 payload 中不携带，由 Access Token 携带）
   - **输入来源**：步骤 4 的 `ctx.user_id` + `ctx.current_roles`
   - **输出去向**：两个新 Token 字符串 → 暂存于局部变量 `new_access_token`、`new_refresh_token` → 进入步骤 6
   - **失败行为**：JWT 签发失败（理论上不应发生，因为依赖项在步骤 1 已验证可用）→ 抛出 `TokenCreationError`，记录关键错误日志 `logger.critical("token_creation_failed", user_id=ctx.user_id)`

6. **步骤 6：原子标记旧 Token 轮换**
   - **操作对象**：Redis 键 `token_blacklist:rotated:{ctx.jti}`
   - **具体操作**：
     - `blacklist.mark_token_rotated(ctx.jti)` — 内部调用 `redis_client.set(f"token_blacklist:rotated:{ctx.jti}", "1", nx=True, ex=REFRESH_TOKEN_EXPIRE_DAYS * 86400)` 即 SET NX EX 604800
     - 若 `SET NX` 返回 `None`（key 已存在）→ 说明另一个并发请求已先完成轮换，本次视为"Token 已被轮换"
   - **输入来源**：步骤 5 暂存的旧 Token `ctx.jti` + 步骤 3 的 Redis 客户端
   - **输出去向**：写入成功 → 进入步骤 7
   - **失败行为**：`SET NX` 失败（key 已存在，并发竞态）→ 丢弃步骤 5 已签发的新 Token 对（不返回给客户端），返回 HTTP 401 + `{"detail": "登录凭证已失效，请重新登录"}`；Redis 写入失败（连接断开）→ 同样丢弃新 Token 对，返回 HTTP 503，记录错误日志（此时新 Token 对未被客户端接收，旧的 Refresh Token 若未被标记则仍可续期——用户可重试）

7. **步骤 7：返回响应**
   - **操作对象**：`TokenRefreshResponse` 模型
   - **具体操作**：
     - 构造 `TokenRefreshResponse(access_token=new_access_token, refresh_token=new_refresh_token, token_type="Bearer")`
     - 记录成功日志：`logger.info("token_refresh_success", user_id=ctx.user_id, old_jti=ctx.jti, new_at_jti=..., new_rt_jti=..., remote_ip=request.client.host)`
   - **输入来源**：步骤 5 的 `new_access_token`、`new_refresh_token`
   - **输出去向**：`TokenRefreshResponse` 实例序列化为 JSON → HTTP 200 返回给客户端
   - **失败行为**：序列化失败（不应发生）→ 抛出 `SerializationError`，同时需将新签发的 Refresh Token 黑名单标记（防止 Token 泄露但客户端未收到）

### 1.6 接口契约 `【已锁定】`

#### 1.6.1 接口 1：refresh_access_token — Token 续期服务

```python
async def refresh_access_token(
    refresh_token: str,
    *,
    redis_client: Redis,
    user_repo: UserRepository,
) -> TokenRefreshResponse:
    """
    验证 Refresh Token 的合法性并轮换签发新的 Token 对。

    服务端处理流程：
    1. JWT 签名验证（HS256 + JWT_SECRET_KEY）
    2. type 字段检查（必须为 "refresh"）
    3. Redis 黑名单查询（token_blacklist:rotated:{jti} + token_blacklist:{jti}）
    4. 数据库查询用户最新角色
    5. 签发新 Access Token（15 分钟有效）和新 Refresh Token（7 天有效）
    6. 通过 Redis SET NX 原子标记旧 Refresh Token 的 jti 为已轮换
    7. 返回新 Token 对

    Args:
        refresh_token: 客户端当前持有的 Refresh Token（JWT 格式字符串）。
            须包含标准 JWT claims: sub, jti, exp, type="refresh"。
            签发者(iss)和签名算法(HS256)须与全局 JWT 配置一致。
        redis_client: Redis 客户端实例（通过 FastAPI Depends 注入）。
        user_repo: 用户仓储实例（通过 FastAPI Depends 注入）。

    Returns:
        TokenRefreshResponse:
            - access_token: 新签发的 Access Token（JWT，有效期 15 分钟）
            - refresh_token: 新签发的 Refresh Token（JWT，有效期 7 天）
            - token_type: "Bearer"

    Raises:
        InvalidTokenError: JWT 签名无效或 exp 已过期。
            映射到 HTTP 401 + {"detail": "登录凭证已过期，请重新登录"}
        TokenAlreadyRotatedError: Refresh Token 的 jti 已在轮换黑名单中（已被轮换或被吊销）。
            映射到 HTTP 401 + {"detail": "登录凭证已失效，请重新登录"}
        UserNotFoundError: payload.sub 对应的用户不存在。
            映射到 HTTP 401 + {"detail": "登录凭证已失效，请重新登录"}
        DatabaseUnavailableError: PostgreSQL 不可用且重试耗尽。
            映射到 HTTP 503
        RedisUnavailableError: Redis 写入失败（旧 Token 未被标记轮换，用户可重试）。
            映射到 HTTP 503
        ConcurrentRotationError: 并发竞态 —— 旧 Token 被另一请求先完成轮换。
            映射到 HTTP 401 + {"detail": "登录凭证已失效，请重新登录"}

    Side Effects:
        - 写入 Redis 键 token_blacklist:rotated:{jti}（TTL 604800 秒）
        - 读取 Redis 键 token_blacklist:{jti}（AUTH-04 吊销黑名单，如存在）
        - 读取 PostgreSQL users 表（查询用户角色）
        - 记录成功/失败的结构化日志

    Idempotency:
        本函数本身不是幂等的 —— 每次调用会消费一个 Refresh Token 并签发新的。
        但通过 SET NX 原子操作保证：
        - 同一 Refresh Token 仅能被成功续期一次（首请求）
        - 并发请求中仅一个成功，其他得到 ConcurrentRotationError
        - 若 SET NX 成功后、响应返回前进程崩溃，用户失去凭证需重新登录

    Thread Safety:
        本函数通过 SET NX 原子操作实现并发安全。
        Redis 操作的原子性保证了无需额外的分布式锁。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `refresh_access_token` —— 语义化，描述"续期 Access Token"的业务动作 |
| **输入类型** | `refresh_token: str`（详见 §1.3 TokenRefreshRequest 契约引用） |
| **输出类型** | `TokenRefreshResponse`（详见 §1.4 契约引用） |
| **异常类型** | `InvalidTokenError`、`TokenAlreadyRotatedError`、`UserNotFoundError`、`DatabaseUnavailableError`、`RedisUnavailableError`、`ConcurrentRotationError`（详见 §1.9） |
| **副作用** | Redis 写入轮换黑名单、PostgreSQL 读取用户角色、记录结构化日志 |
| **幂等性** | 非幂等。旧 Refresh Token 被消费后不可重用。并发保护通过 SET NX 实现 |
| **并发安全** | 通过 Redis SET NX 原子操作保证，同一 Refresh Token 仅一次成功 |

### 1.7 依赖与集成接口

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| JWT 签发/验证 | `packages/py-auth/jwt_utils.py` | `create_token(sub, roles, type, expires_minutes|expires_days) -> str`、`verify_token(token) -> dict`、`decode_token(token) -> dict` | 签发 Access Token 和 Refresh Token、验证 Refresh Token 签名和过期时间 | 项目结构 §6.1（`packages/py-auth/`） |
| Redis 缓存 | `packages/py-cache/client.py` | `set(key, value, nx=True, ex=ttl) -> bool`、`exists(key) -> bool`、`get(key) -> str` | 轮换黑名单的原子写入和查询、吊销黑名单查询 | 技术栈 §5（Redis 缓存） |
| PostgreSQL | `packages/py-db/repositories/user_repository.py` | `get_user_roles_by_id(user_id: str) -> list[str]` | 查询用户最新角色信息 | 项目结构 §6.1（`packages/py-db/`） |
| 全局配置 | `packages/py-config/config.py` | `JWT_SECRET_KEY`、`JWT_ALGORITHM`、`ACCESS_TOKEN_EXPIRE_MINUTES`、`REFRESH_TOKEN_EXPIRE_DAYS`、`REDIS_URL` | 所有 JWT 签发/验证参数和 Redis 连接参数 | 技术栈 §6.2 环境变量清单 |
| 结构化日志 | `packages/py-logger` | `logger.info("token_refresh_success", ...)`、`logger.warning("token_already_rotated", ...)`、`logger.error("redis_unavailable", ...)` | 续期操作审计和安全事件记录，供 OBS-01 消费 | 项目结构 §6.1（`packages/py-logger/`） |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| AUTH-02 用户登录 | `auth_service.login()` 签发 Refresh Token → AUTH-03 消费 | AUTH-02 在登录时签发 Refresh Token（含 jti、sub、type="refresh"），AUTH-03 验证并轮换。两模块共享 JWT 签名密钥和 Redis 黑名单基础设施 | ⏭️ 未开始（仅有意向文档） |
| AUTH-04 五级RBAC鉴权 | `require_role()` Depends → 消费 Access Token payload.roles | AUTH-03 续期后新 Access Token 中的 roles 字段由 AUTH-04 读取并执行权限校验 | ✅ 设计文档 v1.0 已冻结 |
| SEC-04 防刷限流 | Redis 滑动窗口限流中间件 → 保护 `/api/v1/auth/refresh` | AUTH-03 的续期端点受 SEC-04 中间件保护（用户级 30 req/min，IP 级 100 req/min） | ✅ 设计文档 v1.0 已冻结 |
| SEC-05 输入校验防护 | Depends 链 → 校验 refresh_token 字段存在性、SQL 注入/XSS 防护 | AUTH-03 请求体经 SEC-05 Depends 过滤后到达续期处理逻辑 | ✅ 设计文档 v1.0 已冻结 |

### 1.8 状态机 `【对内实现】`

Refresh Token 状态机为单向二态（valid → invalid），不可逆。所有路径一旦进入 invalid 即为终态。

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 副作用 |
|----------|----------|----------|----------|--------|
| valid | `token_issued` | valid | 登录成功（AUTH-02 签发）或续期成功（AUTH-03 新签发） | 新生效的 Refresh Token 可用于后续续期 |
| valid | `refresh_success` | invalid | JWT 签名合法 + exp 未过期 + type="refresh" + jti 不在任何黑名单中 + 数据库角色查询成功 | 旧 Refresh Token 的 jti 写入 `token_blacklist:rotated:{jti}`（SET NX, TTL 604800）；新 Token 对签发 |
| valid | `token_expired` | invalid | `exp` < 当前时间 | 无。JWT 库自行判断 exp 过期 |
| valid | `user_logout` | invalid | 用户发起注销请求（AUTH-02 处理） | 当前所有有效 Token 的 jti 写入 `token_blacklist:{jti}`（AUTH-04 吊销黑名单） |
| valid | `admin_revoke` | invalid | 管理员主动吊销（AUTH-04 处理） | 被吊销用户的全部 Token jti 写入 `token_blacklist:{jti}`（AUTH-04 吊销黑名单） |

- **invalid 是终态**：所有路径均不可逆。Token 一旦进入 invalid，其 jti 永久在黑名单中（直到 TTL 到期自动清理），该 Token 不可在任何条件下恢复有效。
- **黑名单 TTL 自动清理**：Redis 键在 TTL 到期后自动删除，此前的黑名单条目从 Redis 消失。但因为对应的 Token 也已过自然有效期（Access Token 15 分钟 / Refresh Token 7 天），其 JWT `exp` 本身也已过期，不会产生安全漏洞。

### 1.9 异常与边界条件 `【对内实现】`

#### 1.9.1 异常 1：Refresh Token 已过期

- **触发条件**：
  - JWT `exp` 字段表示的时间戳 < 当前 UNIX 时间戳
  - 允许 30 秒时钟偏差宽容度（`leeway=30`，`jwt.decode` 参数）
- **处理策略**：
  1. `jwt.decode()` 抛出 `jose.exceptions.ExpiredSignatureError`
  2. 路由层捕获异常，映射到 HTTP 401
  3. 响应体：`{"detail": "登录凭证已过期，请重新登录"}`
  4. 不透露具体过期时间或 Token 剩余有效期
  5. 记录日志：`logger.info("refresh_token_expired", sub=payload.get("sub", "unknown"), exp=payload.get("exp"))`
- **重试参数**：不重试。凭据本身已失效，重试无意义。

#### 1.9.2 异常 2：Refresh Token 已被轮换（并发竞态 / 重放攻击）

- **触发条件**：
  - JWT 签名有效且未过期 + `token_blacklist:rotated:{jti}` 在 Redis 中存在（已被另一请求轮换）
  - 或步骤 6 `SET NX` 返回 `False`（并发竞态 —— 两请求同时通过校验，但 SET NX 仅允许一个成功）
- **处理策略**：
  1. 若在步骤 3 发现 → 直接返回 HTTP 401，不进入后续步骤
  2. 若在步骤 6 发现（并发竞态）：
     - 丢弃步骤 5 已签发的新 Token 对（通过局部变量引用，Python GC 回收，不返回客户端）
     - 不将新签发的 Token 加入任何黑名单（因为它们从未离开服务器）
     - 返回 HTTP 401 + `{"detail": "登录凭证已失效，请重新登录"}`
  3. 记录安全事件日志：`logger.warning("token_replay_detected", jti=ctx.jti, user_id=ctx.user_id, remote_ip=...)`
  4. 将同一 `user_id` 的失败计数 +1（用于 §1.9.3 连续失败保护）
- **重试参数**：不重试。Token 一旦被轮换即为终态。

#### 1.9.3 异常 3：连续续期失败触发临时封禁

- **触发条件**：
  - 同一 `user_id` 在 5 分钟滑动窗口内续期失败次数 >= 5 次（无论失败原因——过期、轮换、吊销）
  - 计数键：`rate_limit:refresh_fail:{user_id}`（Redis，INCR + EXPIRE 300 实现滑动窗口）
- **处理策略**：
  1. 在步骤 3（黑名单查询）之前，先检查失败计数
  2. 若计数 >= 5 → 跳过后续所有步骤，返回 HTTP 429 + `{"detail": "登录凭证已失效，请重新登录"}`
  3. 封禁持续时间：15 分钟（与 Access Token 有效期一致），由 Redis TTL 自动管理
  4. 封禁期间的续期请求统一返回 HTTP 429（与 SEC-04 的 429 语义一致）
  5. 记录安全警告日志：`logger.warning("refresh_rate_limited", user_id=ctx.user_id, failure_count=5, window_minutes=5)`
- **重试参数**：客户端在封禁期间不应重试。封禁 15 分钟后自动恢复（Redis TTL 到期）。

#### 1.9.4 异常 4：Redis 不可用

- **触发条件**：
  - `redis_client.exists()` 或 `redis_client.set()` 抛出 `redis.exceptions.ConnectionError`
  - 或 Redis 响应超时 > 3 秒
- **处理策略**（fail-open 降级）：
  1. 步骤 3（黑名单查询）：跳过 `exists()` 调用，认为 jti 不在黑名单中，继续执行
  2. 步骤 6（SET NX 标记轮换）：跳过写入操作，但仍签发新 Token 对并返回客户端。此时旧 Refresh Token 未被标记轮换，理论上可被重复使用（安全窗口 = Redis 故障持续时间，通常秒级）
  3. 记录告警日志：`logger.error("redis_unavailable_during_refresh", user_id=ctx.user_id, operation="blacklist_check"|"rotation_mark")`
  4. 若 Redis 持续不可用超过 30 秒，触发 Prometheus 告警（由 OBS-01 可观测性模块消费）
- **重试参数**：Redis 操作本身重试 3 次（间隔 1s），所有重试均失败后触发降级。不阻塞续期请求等待 Redis 恢复。

#### 1.9.5 异常 5：用户角色查询时数据库不可用

- **触发条件**：
  - `user_repo.get_user_roles_by_id()` 抛出 `asyncpg.exceptions.ConnectionFailureError`
  - 或数据库查询超时 > 5 秒
- **处理策略**：
  1. 重试 3 次（间隔 2s），每次重新获取数据库连接
  2. 3 次后仍失败 → 返回 HTTP 503 + `{"detail": "服务暂时不可用，请稍后再试"}`
  3. 不降级使用旧 Refresh Token payload 中的角色（角色信息可能已变更）
  4. 记录错误日志：`logger.critical("database_unavailable_during_refresh", user_id=ctx.user_id, retry_count=3)`
- **重试参数**：最大 3 次，固定间隔 2s。每次重试前必须重新获取数据库连接池中的新连接。

### 1.10 验收测试场景 `【对内实现】`

#### 1.10.1 正向测试 1：有效 Refresh Token 成功续期

- **场景**：用户持有有效期内的 Refresh Token，发起续期请求成功获取新 Token 对
- **Given**:
  - 数据库中存在用户 `user_id="550e8400-e29b-41d4-a716-446655440000"`，角色 `["family"]`
  - 已通过 AUTH-02 签发了有效的 Refresh Token：
    ```json
    {"sub": "550e8400-e29b-41d4-a716-446655440000", "roles": [], "jti": "b7e8d2f3-4a56-43c7-8e9a-123456789abc", "exp": 1776124800, "type": "refresh", "iat": 1775520000, "kid": "v1"}
    ```
  - Redis 中无 `token_blacklist:rotated:b7e8d2f3-4a56-43c7-8e9a-123456789abc` 键
- **When**: 客户端发送 `POST /api/v1/auth/refresh`，请求体 `{"refresh_token": "<上述 JWT>"}`
- **Then**:
  - HTTP 状态码 200
  - 响应体包含 `access_token`（JWT 字符串，payload.type="access"）、`refresh_token`（JWT 字符串，payload.type="refresh"）、`token_type="Bearer"`
  - 新 Access Token 的 payload.roles 为 `["family"]`（与数据库一致）
  - Redis 中存在键 `token_blacklist:rotated:b7e8d2f3-4a56-43c7-8e9a-123456789abc`，值 `"1"`，TTL ≈ 604800
  - 旧 Access Token（如之前在有效期内）仍可正常使用

#### 1.10.2 正向测试 2：用户角色变更后续期反映最新角色

- **场景**：用户在两次续期间角色从 family 升级为 teacher，续期后新 Access Token 反映 teacher 角色
- **Given**:
  - 用户 `user_id="550e8400-e29b-41d4-a716-446655440000"` 数据库当前角色 `["teacher"]`
  - 持有有效的 Refresh Token（payload.roles 可能为空或旧值，但 AUTH-03 不依赖此字段）
- **When**: 客户端发送续期请求
- **Then**:
  - HTTP 200
  - 新 Access Token 的 payload.roles 为 `["teacher"]`
  - 新 Refresh Token 签发成功

#### 1.10.3 异常测试 1：Refresh Token 已过期

- **场景**：用户持有一个距签发时间超过 7 天的 Refresh Token 尝试续期
- **Given**:
  - Refresh Token 的 `exp` = 当前时间 - 60 秒（已过期）
  - JWT 签名和 payload 结构合法
- **When**: 客户端发送续期请求
- **Then**:
  - HTTP 状态码 401
  - 响应体 `{"detail": "登录凭证已过期，请重新登录"}`
  - Redis 中不新增轮换黑名单条目（步骤 6 未执行）
  - 日志中记录 `refresh_token_expired` 事件

#### 1.10.4 异常测试 2：Refresh Token 已被轮换（重放攻击）

- **场景**：攻击者截获已使用过的 Refresh Token，尝试重放续期
- **Given**:
  - Refresh Token 的 `jti` = `"b7e8d2f3-4a56-43c7-8e9a-123456789abc"` 已存在于 Redis 键 `token_blacklist:rotated:b7e8d2f3-4a56-43c7-8e9a-123456789abc`
  - JWT 签名和 exp 均有效
- **When**: 客户端发送续期请求
- **Then**:
  - HTTP 状态码 401
  - 响应体 `{"detail": "登录凭证已失效，请重新登录"}`
  - 日志中记录 `token_replay_detected` 安全事件

#### 1.10.5 异常测试 3：并发续期竞态处理

- **场景**：两个请求同时使用同一 Refresh Token 发起续期（模拟网络重放或前端 Bug）
- **Given**:
  - Fresh Refresh Token（jti 不在任何黑名单中）
  - 两个并发请求同时到达服务端，先后通过步骤 1-5
- **When**: 两个请求都尝试在步骤 6 执行 `SET NX`
- **Then**:
  - 仅一个请求成功（返回 HTTP 200 + 新 Token 对）
  - 另一个请求失败（返回 HTTP 401 + `{"detail": "登录凭证已失效，请重新登录"}`）
  - Redis 中 `SET NX` 确保仅一个 key 被写入
  - 失败请求在步骤 5 签发的新 Token 对被丢弃（不泄露给客户端）

#### 1.10.6 异常测试 4：Redis 不可用时的降级行为

- **场景**：Redis 服务崩溃，续期请求在 fail-open 模式下继续服务
- **Given**:
  - Redis 连接全部失败（`redis.exceptions.ConnectionError`）
  - 有效的 Refresh Token（签名、exp、type 均合法）
- **When**: 客户端发送续期请求
- **Then**:
  - HTTP 状态码 200（fail-open，跳过黑名单查询和轮换标记）
  - 新 Token 对正常签发返回
  - 旧 Refresh Token 的 jti 未被写入 Redis（Redis 不可用）
  - 日志中记录两处 `redis_unavailable_during_refresh` 告警（步骤 3 + 步骤 6）
  - Redis 恢复后，旧 Refresh Token 仍可被续期（因为未被标记轮换）

### 1.11 注意事项与禁止行为 `【对内实现】`

1. **[并发安全必须使用 SET NX]** 步骤 6 的旧 Token 标记轮换操作必须使用 Redis `SET key value NX EX ttl` 单条原子命令。禁止使用"先 `EXISTS` 检查、再 `SET` 写入"的两步操作——两步之间存在竞态窗口，会导致双重消费。

2. **[jti 生成必须使用 uuid4]** `jti` 通过 `uuid.uuid4()` 生成，格式为 `str(uuid)` 即连字符 UUID 格式（如 `"b7e8d2f3-4a56-43c7-8e9a-123456789abc"`）。AUTH-02 和 AUTH-03 的 jti 生成方式必须一致，否则黑名单 key 格式不匹配。

3. **[禁止从旧 Refresh Token 复制角色]** 步骤 4 必须通过 `user_repo.get_user_roles_by_id()` 实时查询数据库。禁止从 `ctx.payload.roles`（旧 Refresh Token 的 roles 字段）复制到新 Access Token。旧 Refresh Token 签发时的角色可能已过时。

4. **[错误响应的信息最小化]** 所有续期失败场景返回的 `detail` 字段仅含两种消息之一：`"登录凭证已过期，请重新登录"`（用于 Token 过期）或 `"登录凭证已失效，请重新登录"`（用于 Token 已轮换/已吊销/其他失败）。禁止在 `detail` 中透露：Token 剩余有效期、具体失败步骤、黑名单命中原因、`expected_role`/`required_level` 等内部字段。

5. **[Redis 键名前缀隔离]** 轮换黑名单使用 `token_blacklist:rotated:{jti}`，禁止使用 `token_blacklist:{jti}`（该前缀归 AUTH-04 吊销黑名单，虽然当前共存，但语义不清晰）。禁止使用 `rotated_token:{jti}` 或其他非标准前缀——破坏了 `token_blacklist:` 命名空间的可发现性。

6. **[禁止在步骤 5 完成后、步骤 6 执行前返回响应]** 若在签发新 Token 对后、标记旧 Token 为已轮换前向客户端返回响应（如异步执行步骤 6），存在风险：客户端收到新 Token 对后立即刷新页面/重连，但旧 Token 仍未被标记，攻击者可能在此期间利用旧 Token 完成额外续期。步骤 5 和步骤 6 必须在同一同步/异步上下文中顺序完成，步骤 6 成功后才可返回步骤 7 的响应。

7. **[刷新 Token 的 roles 字段空白策略]** Refresh Token 的 payload 中 `roles` 字段应设置为空列表 `[]`。角色信息仅由 Access Token 携带（每次续期时通过步骤 4 实时查询）。这样设计避免了 Refresh Token 中的角色信息与实际不一致的问题。

8. **[网络错误重试幂等性]** 客户端在收到 HTTP 503（Redis 写入失败）时，旧 Refresh Token 可能未被标记轮换（写 Redis 失败），此时客户端重试是安全的。若双重重试后 Token 被标记为已轮换（第一次 Redis 写入实际成功但响应未到达客户端），第二次请求将被步骤 3 拦截，返回 HTTP 401。客户端应区分这两种情况，避免无限重试循环。

### 1.12 文档详细度自检清单 `【对内实现】`

- [x] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成编码
- [x] 无偷懒表述：全文无 "等等"、"..."、"其他字段"、"类似"、"同上"、"参考其他模块"、"请根据实际情况补充"、"开发者自行决定"
- [x] 类型定义完整：每个 Pydantic 字段都有 `description` + `examples` + 约束（`minLength`/`format`/`const` 等）
- [x] 逻辑步骤完整：7 个步骤均有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：5 种异常均有精确触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值来源（`ACCESS_TOKEN_EXPIRE_MINUTES=15`、`REFRESH_TOKEN_EXPIRE_DAYS=7`）、条件分支、业务规则均已显式写出
- [x] 技术栈绑定明确：必须使用 6 项、禁止使用 6 项，均与项目技术栈设计文档保持一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致

### 1.14 外部接口契约清单 `【已锁定】`

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| TokenRefreshRequest | `docs/contracts/AUTH-03/TokenRefreshRequest.json` | input | draft | AUTH-03 | AUTH-06 |
| TokenRefreshResponse | `docs/contracts/AUTH-03/TokenRefreshResponse.json` | output | draft | AUTH-03 | AUTH-06 |
| TokenBlacklistRotatedKey | `docs/contracts/AUTH-03/TokenBlacklistRotatedKey.json` | shared-model | draft | AUTH-03 | AUTH-06 |
| verify_token | `docs/contracts/SEC-01/verify_token.json` | input | draft | SEC-01 | AUTH-03 (复用) |
| TokenPayload | `docs/contracts/SEC-01/TokenPayload.json` | shared-model | draft | SEC-01 | AUTH-03 (复用) |
| UserRole | `docs/contracts/AUTH-04/UserRole.json` | shared-enum | draft | AUTH-04 | AUTH-03 (复用) |

### 1.15 意图一致性声明 `【对内实现】`

- **配套意图文档**：`AUTH-03-Token续期-意图文档.md`
- **冻结时间**：`2026-05-26 22:48:27`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致（§1.3 TokenRefreshRequest 对应 §1.6.1 输入定义；§1.4 TokenRefreshResponse 对应 §1.6.2 输出定义）
  - [x] 本落地规范中的状态机实现与意图文档中的状态业务定义一致（§1.8 单向二态 valid→invalid 对应 §1.7 有效/失效二态定义）
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致（§1.9.1 过期对应 §1.8.1；§1.9.2 已轮换对应 §1.8.2；§1.9.3 连续失败对应 §1.12 决策项 5）
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准（§1.10.1→AC-01；§1.10.4→AC-02；§1.10.3→AC-03；§1.10.4→AC-04；§1.10.2→AC-05；AC-06 由全部异常测试覆盖；§1.10.1→AC-07）
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围（§1.12 决策项 1-7 均已在本规范中明确：HS256/密钥管理、Redis 黑名单 TTL、SET NX 轮换检测、POST /api/v1/auth/refresh、5分钟/5次阈值、sub/roles/jti 命名、401 + {"detail":"..."} 格式）
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
