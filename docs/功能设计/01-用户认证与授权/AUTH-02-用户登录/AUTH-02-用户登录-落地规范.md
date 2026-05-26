## 1 功能点：AUTH-02 用户登录 — 落地规范

> **文档生成时间**：`2026-05-26 23:29:26`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-26 23:29:26` | AI Assistant | 初始版本，基于 s06 技术预研报告（14 项决策确定 + 6 项待裁决推断）和 s08 契约协调（3 新类型）生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `AUTH-02-用户登录-设计文档.md`。

---

### 1.1 技术栈绑定 `【对内实现】`

- **必须使用**：
  - `fastapi>=0.115` — APIRouter、Depends() 依赖注入、HTTPException
  - `pydantic>=2.0` — BaseModel、Field() 输入校验
  - `python-jose[cryptography]>=3.3.0` — JWT 签发（`jose.jwt.encode`），项目技术栈 §5 规定
  - `passlib>=1.7` — CryptContext（bcrypt 实现），用于 `packages/py-auth/hashing.py`
  - `asyncpg` — PostgreSQL 异步驱动（通过 `packages/py-db` 封装），项目技术栈 §3.1 规定
  - `uuid`（Python 标准库） — `uuid.uuid4()` 生成 JTI（令牌唯一标识）
  - 审计日志格式 `logger.critical(op_type="USER_LOGIN", ...)` — 与 OBS-01 §1.1 规范一致
  - 响应格式 `{"detail": "..."}` — 项目统一的错误响应格式，与 SEC-01/SEC-05/AUTH-04 一致

- **禁止使用**：
  - 禁止直接调用 `bcrypt` 库（必须通过 `packages/py-auth/hashing.py` 的 `verify_password()`）
  - 禁止使用 `PyJWT` 库替代 `python-jose`（技术栈 §5 明确选定 python-jose）
  - 禁止在登录响应中返回 `password_hash`、完整 `User` 对象或任何非必要的用户个人信息
  - 禁止在审计日志、异常消息、调试输出中记录密码原文或哈希值
  - 禁止在登录成功后自动续期 Token 或创建 Session（续期归属 AUTH-03，会话管理归属 AUTH-06）
  - 禁止在凭据错误时区分"用户名不存在"和"密码错误"——必须始终执行固定时间密码比对

### 1.2 文件归属 `【对内实现】`

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 登录路由端点 | `apps/api-server/app/api/v1/auth.py` | `POST /api/v1/auth/login` 端点定义，含 `login()` 路由处理函数（与 AUTH-01 注册端点同文件） |
| 登录服务逻辑 | `apps/api-server/app/services/auth_service.py` | `login_user()` 服务函数，编排登录完整流程（格式校验→用户查询→密码比对→账号状态检查→双令牌签发→审计日志） |
| 登录请求/响应模型 | `packages/py-schemas/py_schemas/auth.py` | `LoginRequest`、`LoginResponse`、`LoginErrorResponse` Pydantic 模型（与 AUTH-01 注册模型同文件） |
| JWT 签发函数（复用） | `packages/py-auth/py_auth/jwt_utils.py` | `create_access_token()` 签发访问令牌和续期令牌（已存在，归属 SEC-01，本模块复用） |
| 密码比对函数（复用） | `packages/py-auth/py_auth/hashing.py` | `verify_password(plain, hashed)` bcrypt 哈希比对（已存在，归属 SEC-01，本模块复用） |
| 用户查询（复用） | `packages/py-db/py_db/repositories/user_repository.py` | `find_by_username_lower(username)` 大小写不敏感用户查询（已存在，AUTH-01 实现） |
| 路由 Depends | `apps/api-server/app/dependencies/auth_dependencies.py` | `get_current_user()` 薄封装，调用 `py-auth` 的 `decode_and_validate_token()` 并注入 `request.state.user` |
| 测试文件 | `apps/api-server/_tmp_test/test_auth_login.py` | `login_user` 端点的单元/集成测试（推断） |

### 1.3 输入定义 `【已锁定】`

**LoginRequest**
- 【契约引用】`docs/contracts/AUTH-02/LoginRequest.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-05（登录注册界面）

### 1.4 输出定义 `【已锁定】`

**LoginResponse**
- 【契约引用】`docs/contracts/AUTH-02/LoginResponse.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-05（登录注册界面）、AUTH-06（认证会话管理）

**LoginErrorResponse**
- 【契约引用】`docs/contracts/AUTH-02/LoginErrorResponse.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-05（登录注册界面）

**ValidationErrorResponse（422 格式，复用 SEC-05）**
- 【契约引用】`docs/contracts/SEC-05/ValidationErrorResponse.json`
- 本模块作为该契约的消费方（复用 SEC-05 已定义的 422 错误格式）
- 消费方：AUTH-05（登录注册界面）

**UserRole（复用 AUTH-01）**
- 【契约引用】`docs/contracts/AUTH-01/UserRole.json`
- 本模块作为该契约的消费方（读取角色值注入令牌 payload）
- 定义方：AUTH-01（用户注册）

### 1.5 核心逻辑步骤 `【对内实现】`

**主流程函数签名**：
```python
async def login_user(
    request: LoginRequest,
    user_repo: UserRepository,
) -> LoginResponse:
    ...
```

登录流程采用五阶段编排：格式校验 → 用户查询 → 密码校验 → 账号状态检查 → 令牌签发 → 审计日志。每阶段失败即中断，不进入后续阶段。

1. **步骤 1：格式校验（路由层）**
   - **操作对象**：HTTP 请求体 JSON
   - **具体操作**：FastAPI 路由层通过 `Depends(LoginRequest)` 自动执行 Pydantic 校验。校验规则：`username`（`Field(min_length=4, max_length=32)`）、`password`（`Field(min_length=8)`）。仅校验存在性和长度，不校验用户名是否存在或密码是否正确。
   - **输入来源**：`POST /api/v1/auth/login` 请求体 JSON
   - **输出去向**：校验通过的 `LoginRequest` 实例 → 步骤 2（Service 层调用 `login_user(request)` 继续处理）
   - **失败行为**：Pydantic 校验失败（缺失必填字段、`username` 长度不足 4、`password` 长度不足 8）→ FastAPI 自动返回 HTTP 422，响应体格式 `{"errors": [{"field": "username", "reason": "字段 'username' 校验失败", "constraint": "min_length"}]}`（与 SEC-05 自定义 422 格式一致）。不执行任何后续步骤。

2. **步骤 2：用户查询 + 固定时间密码比对**
   - **操作对象**：PostgreSQL `users` 表
   - **具体操作**：
     - 调用 `user_repo.find_by_username_lower(request.username)` 执行大小写不敏感查询，SQL `SELECT * FROM users WHERE LOWER(username) = LOWER(:val) LIMIT 1`，走 `idx_users_username_lower` 索引
     - 若返回 `User` 对象 → 提取 `user.password_hash`；若返回 `None` → 使用固定 dummy hash（`"$2b$12$dummyhashdummyhashdummyhashdummyhashdummyhashdummyhashdu"`）
     - 调用 `hashing.verify_password(request.password, password_hash_to_compare)` 执行 bcrypt 哈希比对
   - **输入来源**：步骤 1 校验通过的 `LoginRequest.username` 和 `LoginRequest.password`
   - **输出去向**：比对结果 + `user` 对象（或 None）→ 进入步骤 3 的判断分支
   - **失败行为**：
     - 用户不存在且固定时间比对完成 → 进入步骤 3 的用户不存在分支（不直接返回，继续执行后续步骤混合判断路径以保持固定响应时间）
     - 密码不匹配 → 进入步骤 3 的密码不匹配分支
     - `verify_password()` 抛出异常（如 bcrypt 内部错误）→ 记录 `logger.error("password_verification_error", username=sanitized_log_username)`，抛出 `HTTPException(status_code=500, detail="系统繁忙，请稍后重试")`

3. **步骤 3：凭据验证结果判定**
   - **操作对象**：步骤 2 的比对结果和 `user` 对象
   - **具体操作**：执行以下判定逻辑，按顺序检查：
     1. 若 `verify_password()` 返回 `False` → 无论用户存在与否，统一返回"用户名或密码错误，请重新输入"
     2. 若 `user` 为 `None`（用户不存在但使用了 dummy hash，步骤 2 中 `verify_password()` 应返回 `False`，故理论上不会进入此分支，但作为安全防御保留）→ 统一返回相同提示
     3. 若 `verify_password()` 返回 `True` 且 `user` 不为 `None` → 进入步骤 4
   - **输入来源**：步骤 2 的 `verify_password()` 返回值和 `user` 对象
   - **输出去向**：验证通过 → `user` 对象进入步骤 4；验证失败 → 构造 `LoginErrorResponse` 并返回（步骤 3 内终止）
   - **失败行为**：验证失败时，记录审计日志：`logger.critical(op_type="USER_LOGIN", user_id=user.id if user else "unknown", username=sanitized_log_username, success=False, ip=client_ip)`，然后返回 HTTP 401 + `{"detail": "用户名或密码错误，请重新输入"}`。多个失败条件使用相同日志格式和相同响应体消息，确保无法区分失败原因。

4. **步骤 4：账号状态检查**
   - **操作对象**：`User.is_active` 字段
   - **具体操作**：
     - 检查 `user.is_active` 值。若 `is_active` 字段尚不存在于 `User` 模型（优雅降级）→ 跳过本步骤，默认用户为活跃状态
     - 若 `is_active` 存在且为 `True` → 进入步骤 5
     - 若 `is_active` 存在且为 `False` → 返回"当前账号无法登录，请联系管理员"
   - **输入来源**：步骤 3 输出的 `user` 对象
   - **输出去向**：活跃用户 → 进入步骤 5；禁用账号 → 返回错误（步骤 4 内终止）
   - **失败行为**：账号被禁用时，记录审计日志：`logger.critical(op_type="USER_LOGIN", user_id=user.id, username=sanitized_log_username, success=False, reason="account_disabled", ip=client_ip)`，返回 HTTP 401 + `{"detail": "当前账号无法登录，请联系管理员"}`。必须使用 401 而非 403（与 AUTH-04 的权限拒绝 403 形成区分，参见设计文档 §1.1 业务矛盾推断 #5）。

5. **步骤 5：双令牌签发**
   - **操作对象**：`packages/py-auth/py_auth/jwt_utils.py` 的 `create_access_token()` 函数
   - **具体操作**：
     - 生成 JTI：`jti = str(uuid.uuid4())`，格式为连字符 UUID（如 `"b7e8d2f3-4a56-43c7-8e9a-123456789abc"`）
     - 签发访问令牌：`access_token = create_access_token(data={"sub": str(user.id), "roles": [user.role.value], "jti": jti}, expires_delta=timedelta(minutes=15))`
       - `data["sub"]` 为 UUID 字符串（非 UUID 对象），`data["roles"]` 为字符串列表（如 `["family"]`），`data["jti"]` 为连字符 UUID 字符串
       - 签名算法 HS256，密钥从 `SecurityConfig.JWT_SECRET` 读取
     - 签发续期令牌：`refresh_token = create_access_token(data={"sub": str(user.id), "roles": [], "jti": str(uuid.uuid4()), "token_type": "refresh"}, expires_delta=timedelta(days=7))`
       - `token_type` claim 固定为 `"refresh"`，用于标识令牌类型（与访问令牌的默认 type 区分）
       - `roles` 为空列表（角色信息仅由 Access Token 携带）
     - 计算 `expires_in`：`ACCESS_TOKEN_EXPIRE_MINUTES * 60`（默认 900 秒）
   - **输入来源**：步骤 4 输出的 `user.id`、`user.role.value`
   - **输出去向**：`access_token` 和 `refresh_token` 字符串 → 步骤 6
   - **失败行为**：JWT 签发失败（理论上不应发生）→ 抛出 `HTTPException(status_code=500, detail="系统繁忙，请稍后重试")`，记录 `logger.critical("token_creation_failed", user_id=user.id)`

6. **步骤 6：返回响应与审计日志**
   - **操作对象**：`LoginResponse` 模型 + 审计日志
   - **具体操作**：
     - 构造 `LoginResponse(access_token=access_token, refresh_token=refresh_token, token_type="Bearer", expires_in=expires_in)` → HTTP 200
     - 通过 `asyncio.create_task()` 异步投递审计日志：`logger.critical(op_type="USER_LOGIN", user_id=str(user.id), username=sanitized_log_username, success=True, role=user.role.value, ip=client_ip)`
     - 审计日志投递失败不阻塞 200 响应返回
   - **输入来源**：步骤 5 的 `access_token`、`refresh_token`、`expires_in`
   - **输出去向**：`LoginResponse` 实例序列化为 JSON → HTTP 200 返回给客户端
   - **失败行为**：序列化失败（不应发生）→ 抛出 `HTTPException(status_code=500, detail="系统繁忙，请稍后重试")`

### 1.6 接口契约 `【已锁定】`

#### 1.6.1 接口 1：login_user — 用户登录服务

```python
async def login_user(
    request: LoginRequest,
    user_repo: UserRepository = Depends(get_user_repository),
) -> LoginResponse:
    """
    验证用户凭据（用户名和密码）的合法性，验证通过后签发访问凭证。

    服务端处理流程：
    1. 路由层 Pydantic 校验（LoginRequest）→ 格式校验
    2. 用户查询（find_by_username_lower）+ 固定时间 bcrypt 密码比对
    3. 凭据验证判定（统一模糊提示，不区分用户名不存在和密码错误）
    4. 账号状态检查（is_active 字段，优雅降级处理）
    5. 双令牌签发（access_token + refresh_token）
    6. 异步审计日志 + 返回响应

    Args:
        request: Pydantic 校验通过的登录请求，包含 username 和 password
        user_repo: UserRepository 实例，封装 users 表的 CRUD 操作
            （通过 FastAPI Depends 注入）

    Returns:
        LoginResponse:
            - access_token: 新签发的访问令牌（JWT，有效期 15 分钟/900 秒）
            - refresh_token: 新签发的续期令牌（JWT，有效期 7 天/604800 秒）
            - token_type: "Bearer"
            - expires_in: 访问令牌有效期（秒）

    Raises:
        HTTPException(422):
            username 长度不足 4、password 长度不足 8、必填字段缺失
            响应体复用 SEC-05 ValidationErrorResponse 格式：
            {"errors": [{"field": "...", "reason": "...", "constraint": "..."}]}
        HTTPException(401):
            - 凭据错误：{"detail": "用户名或密码错误，请重新输入"}
            - 账号已禁用：{"detail": "当前账号无法登录，请联系管理员"}
        HTTPException(500):
            - 密码哈希比对服务内部错误
            - JWT 签发失败
            - 其他未预期的内部错误
            响应体：{"detail": "系统繁忙，请稍后重试"}

    Side Effects:
        - 读取 PostgreSQL users 表（查询用户记录）
        - 调用 py-auth/hashing.py verify_password() 执行 bcrypt 比对
        - 调用 py-auth/jwt_utils.py create_access_token() 签发 JWT（两次）
        - 异步写入审计日志（op_type="USER_LOGIN"）

    Idempotency:
        非幂等操作。每次成功登录签发新的 Token 对，旧的 Token 不被撤销。
        同一用户连续登录多次不会影响前次 Token 的有效性。

    Thread Safety:
        线程安全。内部无共享可变状态，所有状态通过局部变量管理。
        不维护服务器端会话状态。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `login_user` — 语义化，描述"用户登录"的业务动作 |
| **输入类型** | `LoginRequest`（【契约引用】`docs/contracts/AUTH-02/LoginRequest.json`） |
| **输出类型** | `LoginResponse`（【契约引用】`docs/contracts/AUTH-02/LoginResponse.json`） |
| **异常类型** | `HTTPException(422)` — 复用 SEC-05 ValidationErrorResponse 格式；`HTTPException(401)` — LoginErrorResponse 格式；`HTTPException(500)` — 通用内部错误 |
| **副作用** | 读取 PostgreSQL users 表；调用 bcrypt 比对；两次 JWT 签发；异步审计日志 |
| **幂等性** | 非幂等。每次成功登录签发新 Token 对，旧 Token 仍有效 |
| **并发安全** | 线程安全，无共享可变状态 |

#### 1.6.2 路由注册：POST /api/v1/auth/login

```python
from fastapi import APIRouter, Depends
from packages.py_schemas.py_schemas.auth import LoginRequest, LoginResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=200,
    responses={
        200: {"description": "登录成功，返回访问令牌和续期令牌"},
        401: {"description": "凭据错误或账号异常", "model": LoginErrorResponse},
        422: {"description": "输入校验失败", "model": ValidationErrorResponse},
        500: {"description": "系统内部错误"},
    }
)
async def login(
    request: LoginRequest = Depends(),
    user_repo: UserRepository = Depends(get_user_repository),
) -> LoginResponse:
    """
    用户登录端点。POST /api/v1/auth/login

    Request Body (JSON):
        {
            "username": "zhang_san",
            "password": "Abc12345"
        }

    Success Response 200:
        {
            "access_token": "REDACTED-SET-VIA-ENV",
            "refresh_token": "REDACTED-SET-VIA-ENV",
            "token_type": "Bearer",
            "expires_in": 900
        }

    Error Response 401 (凭据错误):
        {
            "detail": "用户名或密码错误，请重新输入"
        }

    Error Response 401 (账号禁用):
        {
            "detail": "当前账号无法登录，请联系管理员"
        }

    Error Response 422 (ValidationErrorResponse, 复用 SEC-05 格式):
        {
            "errors": [
                {"field": "username", "reason": "字段 'username' 校验失败", "constraint": "min_length"}
            ]
        }
    """
    return await login_user(request, user_repo)
```

### 1.7 依赖与集成接口 `【已锁定】`

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 关系型数据库 | PostgreSQL 17.x | `UserRepository.find_by_username_lower(username) -> User|None` 执行 SQL `SELECT * FROM users WHERE LOWER(username) = LOWER(:val) LIMIT 1`，走 `idx_users_username_lower` 索引 | 项目结构 §6.1（`packages/py-db/`） |
| 密码哈希服务 | `packages/py-auth/hashing.py` | `verify_password(plain: str, hashed: str) -> bool` — bcrypt 哈希比对，约耗时 250ms，salt rounds 从 `get_settings().BCRYPT_ROUNDS` 读取（默认 12） | 项目结构 §6.1（`packages/py-auth/py_auth/hashing.py`）；技术栈 §5 |
| JWT 签发服务 | `packages/py-auth/jwt_utils.py` | `create_access_token(data: dict, expires_delta: timedelta) -> str` — HS256 签名 JWT，密钥从 `SecurityConfig.JWT_SECRET` 读取。调用两次：一次签发 access_token（15 分钟），一次签发 refresh_token（7 天 + 额外 `token_type: "refresh"`） | 项目结构 §6.1（`packages/py-auth/py_auth/jwt_utils.py`）；技术栈 §5 |
| 配置服务 | `packages/py-config/` | `get_security_config()` 读取 `JWT_SECRET`、`ACCESS_TOKEN_EXPIRE_MINUTES`、`REFRESH_TOKEN_EXPIRE_DAYS`、`BCRYPT_ROUNDS` | 项目结构 §6.1（`packages/py-config/`）；DEPLOY-05 |
| 日志系统 | `packages/py-logger/` | `logger.critical(op_type="USER_LOGIN", user_id=..., username=..., success=True|False, role=..., ip=...)` — 成功/失败均写入审计日志，采用 `asyncio.create_task()` 异步投递 | 项目结构 §6.1（`packages/py-logger/`）；OBS-01 §1.1 |
| Schema 契约 | `packages/py-schemas/py_schemas/auth.py` | `LoginRequest.model_validate(data)`、`LoginResponse.model_validate(data)`、`LoginErrorResponse.model_validate(data)` — Pydantic v2 输入/输出校验 | 项目结构 §6.1（`packages/py-schemas/`） |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| AUTH-01（用户注册） | `UserRepository.find_by_username_lower()`、`User` ORM 模型（`password_hash`/`role`/`is_active` 字段） | 本模块查询 AUTH-01 创建的用户数据进行登录验证 | ✅ 设计文档已冻结 |
| AUTH-04（五级RBAC鉴权） | 消费 `create_access_token()` payload 中的 `roles` 字段 | 本模块将用户角色注入 Access Token，AUTH-04 读取该字段进行请求级权限校验 | ✅ 设计文档已冻结 |
| SEC-04（防刷限流） | 消费审计日志 `op_type="USER_LOGIN"` + `success=False` | 本模块的登录失败日志为 SEC-04 提供暴力破解计数的数据源 | ✅ 设计文档已冻结 |
| SEC-05（输入校验防护） | `ValidationErrorResponse` 错误格式 `{"errors": [{"field", "reason", "constraint"}]}` | 复用 422 错误响应格式 | ✅ 已落地 |
| OBS-01（结构化日志） | `logger.critical(op_type="USER_LOGIN", ...)` 格式 | 审计日志格式规范 | ✅ 已落地 |
| AUTH-06（认证会话管理） | 消费 `LoginResponse`（access_token + refresh_token） | 前端管理 Token 持久化存储和自动注入 | ⏭️ 待落地 |

#### 1.7.3 固定时间 dummy hash 常量

```python
# 用于固定时间密码比对的 dummy bcrypt hash。
# 当查询的用户不存在时，使用此 hash 进行 verify_password() 比对，
# 确保存在用户和不存在用户的响应时间一致，防止侧信道泄露。
DUMMY_BCRYPT_HASH = "$2b$12$dummyhashdummyhashdummyhashdummyhashdummyhashdummyhashdu"
```

### 1.8 状态机 `【对内实现】`

本功能点不涉及状态流转，故无需状态机。登录流程为一次性的请求-响应操作——用户提交凭据后，系统要么验证通过（签发双令牌），要么验证失败（返回错误提示）。不涉及中间状态或后续状态转换（意图文档 §1.7）。

### 1.9 异常与边界条件 `【对内实现】`

#### 1.9.1 异常 1：用户名或密码错误（401 Unauthorized）

- **触发条件**：
  - 用户提交的用户名在 `users` 表中不存在（`find_by_username_lower()` 返回 `None`）
  - 用户提交的密码与 `users.password_hash` 的 bcrypt 哈希比对不匹配（`verify_password()` 返回 `False`）
  - 以上两种情况使用相同的错误消息和 HTTP 状态码，前端无法区分
- **处理策略**：
  1. 步骤 2 中始终执行 `verify_password()`（存在用户使用真实 hash，不存在用户使用 `DUMMY_BCRYPT_HASH`）
  2. 步骤 3 中凭据验证失败 → 返回 HTTP 401 + `{"detail": "用户名或密码错误，请重新输入"}`
  3. 响应体不包含错误码、内部标识或任何差别性信息
  4. 不清空用户已输入的用户名（HTTP 是无状态的，由前端负责保持表单状态）
  5. 记录审计日志：`logger.critical(op_type="USER_LOGIN", user_id=..., username=..., success=False, ip=...)`
- **重试参数**：不重试。用户修正凭据后重新提交。连续失败触发的限流保护由 SEC-04 基于审计日志的滑动窗口计数处理。

#### 1.9.2 异常 2：账号状态异常（401 Unauthorized）

- **触发条件**：
  - 用户存在且密码比对通过
  - `User.is_active` 字段值为 `False`（账号被管理员禁用）
  - 若 `is_active` 字段尚不存在于 `User` 模型（迁移未执行），跳过此检查，不触发此异常
- **处理策略**：
  1. 步骤 4 中检查 `user.is_active` → 发现为 `False`
  2. 返回 HTTP 401 + `{"detail": "当前账号无法登录，请联系管理员"}`
  3. 不透露具体是何种状态异常（禁用、删除、还是其他状态）
  4. 不引导用户重试，引导用户联系管理员
  5. 记录审计日志：`logger.critical(op_type="USER_LOGIN", user_id=user.id, username=..., success=False, reason="account_disabled", ip=...)`
- **重试参数**：不重试。用户需通过人工渠道（联系管理员）处理账号问题后重新登录。

#### 1.9.3 异常 3：必填字段缺失或格式错误（422 Unprocessable Entity）

- **触发条件**：
  - `username` 为 `None` 或空字符串
  - `username` 长度 < 4 字符
  - `password` 为 `None` 或空字符串
  - `password` 长度 < 8 字符
  - 请求体缺少 `username` 或 `password` 字段
- **处理策略**：
  1. 路由层 `Depends(LoginRequest)` 自动拦截，不进入 Service 层
  2. FastAPI 返回 HTTP 422，响应体格式：`{"errors": [{"field": "<字段名>", "reason": "<人类可读原因>", "constraint": "<约束名>"}]}`
  3. 当 `username` 有值但 `password` 为空/缺失时，返回字段级 422 错误告知用户"密码为必填字段"
  4. 与 §1.9.1 的 401 凭据错误形成精确区分：字段缺失 → 422（指导用户补充），密码错误 → 401（模糊提示）
  5. 记录结构化日志：`logger.warning("input_validation_failed", errors=error_details)`
- **重试参数**：不重试。客户端修正输入后重新发起请求。

#### 1.9.4 异常 4：系统内部错误（500 Internal Server Error）

- **触发条件**：
  - `verify_password()` 抛出异常（bcrypt 内部错误、passlib 版本不兼容）
  - `create_access_token()` 抛出异常（密钥无效、JOSE 库错误）
  - 数据库查询抛出 `DatabaseError`（连接超时、连接池耗尽）
  - 任何未预期的 Python 异常（`TypeError`、`AttributeError` 等编码缺陷）
- **处理策略**：
  1. 捕获具体异常类型，统一返回 HTTP 500 + `{"detail": "系统繁忙，请稍后重试"}`
  2. 保持当前登录页面状态，不清空已输入的信息（由前端通过保持表单状态实现）
  3. 记录错误日志：`logger.critical("login_internal_error", error=str(e), traceback=traceback.format_exc())`
  4. 审计日志中记录失败的登录尝试（`success=False`，`reason="internal_error"`）
  5. 禁止在错误响应中暴露内部异常细节、堆栈跟踪、数据库连接信息
- **重试参数**：不自动重试。允许用户稍后手动重新提交。

#### 1.9.5 边界条件 1：dummy hash 固定时间比对防侧信道

- **触发条件**：
  - 用户提交的用户名在系统中不存在
  - 攻击者通过测量响应时间来推测用户名是否存在
- **处理策略**：
  1. 当 `find_by_username_lower()` 返回 `None` 时，使用 `DUMMY_BCRYPT_HASH`（固定 bcrypt hash，约 250ms）执行 `verify_password()`
  2. 无论用户是否存在，步骤 2 的总耗时均约为 255ms（<5ms 查询 + 250ms 比对）
  3. 验证结果判定在步骤 3 统一处理，步骤 2 的返回接口对 Service 层透明
  4. dummy hash 在模块级定义为常量，使用固定的合法 bcrypt hash 字符串
- **重试参数**：不适用。此为设计层面的安全防护，无重试逻辑。

#### 1.9.6 边界条件 2：is_active 字段优雅降级

- **触发条件**：
  - `User` ORM 模型中尚未添加 `is_active` 字段（Alembic 迁移未执行）
  - 访问 `user.is_active` 时抛出 `AttributeError`
- **处理策略**：
  1. 使用 `getattr(user, 'is_active', True)` 安全访问，默认 `True`
  2. 记录单次警告日志：`logger.warning("is_active_field_not_found", user_id=user.id)`（仅在首次检测到缺失时记录，避免日志洪泛）
  3. 跳过账号状态检查，默认所有用户为活跃状态
  4. 迁移完成后（`is_active` 字段存在），账号禁用检查自动生效
- **重试参数**：不适用。此为运行时兼容处理，无重试逻辑。

### 1.10 验收测试场景 `【对内实现】`

#### 1.10.1 正向测试 1：正确凭据登录成功

- **场景**：已注册用户使用正确的用户名和密码登录，成功获得双令牌
- **Given**:
  - 数据库中存在用户：
    ```json
    {"username": "zhang_san", "password_hash": "$2b$12$...", "role": "family", "is_active": true}
    ```
  - 用户输入的凭据：`username="zhang_san"`、`password="Abc12345"`（与注册时设置的密码一致）
- **When**: 发送 `POST /api/v1/auth/login`，请求体：
  ```json
  {"username": "zhang_san", "password": "Abc12345"}
  ```
- **Then**:
  - HTTP 状态码 = `200 OK`
  - 响应体包含：
    - `access_token`：JWT 字符串，解码后 payload 包含 `sub`（用户 UUID 字符串）、`roles: ["family"]`、`jti`（UUID 格式）、`exp`（当前时间+900秒）、`iat`（当前时间）
    - `refresh_token`：JWT 字符串，解码后 payload 包含 `sub`（与 access_token 相同的用户 UUID）、`roles: []`、`jti`（UUID 格式）、`type: "refresh"`、`exp`（当前时间+7天）、`iat`（当前时间）
    - `token_type: "Bearer"`
    - `expires_in: 900`
  - 审计日志中有一条 `op_type="USER_LOGIN"`、`success=True` 的 `critical` 级别日志

#### 1.10.2 正向测试 2：已注册三种角色均可成功登录

- **场景**：家属、老师、专家三种已注册角色均可凭正确凭据完成登录
- **Given**:
  - 数据库中存在三个用户：`role="family"`、`role="teacher"`、`role="expert"`，均有正确密码哈希和 `is_active=true`
- **When**: 分别使用三个账号的正确凭据调用 `POST /api/v1/auth/login`
- **Then**:
  - 三个请求均返回 HTTP 200
  - 每个响应中的 `access_token` 解码后 `roles` 字段分别包含 `["family"]`、`["teacher"]`、`["expert"]`
  - 三个账号的 `token_type` 均为 `"Bearer"`，`expires_in` 均为 900

#### 1.10.3 异常测试 1：使用错误密码登录拒绝

- **场景**：已注册用户输入错误密码，系统返回统一模糊提示
- **Given**:
  - 数据库中存在用户 `username="zhang_san"`、`password_hash="$2b$12$..."`（对应正确密码 `"Abc12345"`）
  - 用户输入的凭据：`username="zhang_san"`、`password="WrongPass1"`（错误密码）
- **When**: 发送 `POST /api/v1/auth/login`，请求体：
  ```json
  {"username": "zhang_san", "password": "WrongPass1"}
  ```
- **Then**:
  - HTTP 状态码 = `401 Unauthorized`
  - 响应体：`{"detail": "用户名或密码错误，请重新输入"}`
  - 响应体中不包含 `access_token` 或 `refresh_token` 字段
  - 审计日志中记录 `op_type="USER_LOGIN"`、`success=False`

#### 1.10.4 异常测试 2：不存在的用户名登录拒绝

- **场景**：未注册的用户名登录，返回与错误密码完全相同的提示
- **Given**:
  - 数据库中不存在 `username="not_exist_user"`
- **When**: 发送 `POST /api/v1/auth/login`，请求体：
  ```json
  {"username": "not_exist_user", "password": "AnyPass123"}
  ```
- **Then**:
  - HTTP 状态码 = `401 Unauthorized`
  - 响应体：`{"detail": "用户名或密码错误，请重新输入"}`
  - 响应体与异常测试 1 的响应体完全相同（字符串精确匹配）
  - 响应时间 ≈ 255ms（即使 `find_by_username_lower()` 返回 None，仍执行了 dummy hash 的固定时间比对）

#### 1.10.5 正向测试 3：固定时间比对防侧信道

- **场景**：验证存在用户和不存在用户的响应时间差异在安全范围内
- **Given**:
  - 用户 `"zhang_san"` 存在于数据库中
  - 用户 `"not_exist_user"` 不存在于数据库中
- **When**: 分别以错误密码调用两个用户名，各执行 10 次
- **Then**:
  - 两类请求的平均响应时间差值 < 50ms（dummy hash 固定时间比对有效）
  - 无法通过响应时间推测用户名是否存在

#### 1.10.6 异常测试 3：必填字段缺失（422）

- **场景**：请求体缺少 password 字段
- **Given**: `username="zhang_san"`，但请求体中不包含 password 字段
- **When**: 发送 `POST /api/v1/auth/login`，请求体：
  ```json
  {"username": "zhang_san"}
  ```
- **Then**:
  - HTTP 状态码 = `422 Unprocessable Entity`
  - 响应体 `errors` 数组中包含 `field: "password"` 的条目
  - 不进入 Service 层（路由层 Pydantic 校验拦截）
  - 数据库中无任何查询操作，无审计日志写入

#### 1.10.7 异常测试 4：账号被禁用登录拒绝

- **场景**：已注册但被管理员禁用的账号尝试登录
- **Given**:
  - 数据库中存在用户 `username="disabled_user"`、密码正确、`is_active=false`
- **When**: 发送 `POST /api/v1/auth/login`，使用正确凭据
- **Then**:
  - HTTP 状态码 = `401 Unauthorized`
  - 响应体：`{"detail": "当前账号无法登录，请联系管理员"}`
  - 审计日志中记录 `success=False`、`reason="account_disabled"`
  - 不透露 `is_active=false` 的具体状态

### 1.11 注意事项与禁止行为 `【对内实现】`

1. **[约束] 固定时间比对不可跳过**：步骤 2 中，无论用户是否存在，都必须执行 `verify_password()`。禁止"先查用户，不存在则直接返回 401"的短路逻辑。对不存在用户使用 `DUMMY_BCRYPT_HASH` 执行固定时间比对。此约束不可通过配置关闭。

2. **[约束] 统一错误提示字符串精确匹配**：用户名不存在和密码错误两种情况必须返回完全相同的字符串——`"用户名或密码错误，请重新输入"`。禁止追加任何差别性信息（错误码、空格、标点差异），禁止通过不同的 HTTP Header 或响应体字段区分两种场景。验收标准 AC-09 要求"前端无法区分两种失败原因"。

3. **[易错点] roles 字段格式一致性**：`create_access_token()` 的 `data["roles"]` 参数接受字符串列表（如 `["family"]`），而非单个字符串。AUTH-04 的 `rbac.py` 消费端期望 `List[str]` 格式。格式不匹配将导致所有鉴权请求被拒绝。`data["sub"]` 应为 `str` 类型（UUID 字符串），非 `UUID` 对象——否则 JWT 编码时会被序列化为不可解析的格式。

4. **[易错点] 续期令牌的 token_type claim**：续期令牌必须通过额外的 `token_type: "refresh"` claim 与访问令牌区分。AUTH-03 在续期时将校验此字段。访问令牌也可以设置 `token_type: "access"` 以显式标识，但非强制。续期令牌的 `roles` 字段应设置为空列表 `[]`。

5. **[易错点] 字段缺失与密码错误的区分边界**：当 `username` 有值但 `password` 为空字符串 `""` 或 `None` 时，返回 422 字段级错误（SEC-05 格式），告知"密码为必填字段"。当 `username` 有值且 `password` 非空（>=8 字符）但哈希比对失败时，返回 401 统一提示。两者的边界条件：`password=""`（或缺失）→ 422；`password="Abc12345"` 但比对失败 → 401。

6. **[易错点] jti 生成格式**：所有 jti 必须通过 `str(uuid.uuid4())` 生成，格式为连字符 UUID（如 `"b7e8d2f3-4a56-43c7-8e9a-123456789abc"`）。AUTH-02 和 AUTH-03 的 jti 生成方式必须一致，否则黑名单 key 格式不匹配。禁止使用 `uuid.uuid4().hex`（无连字符格式）或自定义字符串。

7. **[禁止行为] 禁止在响应中暴露敏感信息**：`LoginResponse` 中禁止返回 `password_hash`、用户的完整 `User` 对象、或任何非必要的个人信息（如手机号、真实姓名）。`LoginErrorResponse` 的 `detail` 字段禁止透露失败具体原因。

8. **[禁止行为] 禁止绕过审计日志**：登录成功和失败时 `logger.critical(op_type="USER_LOGIN")` 调用不可省略、不可被 `try-except` 静默吞掉。日志中禁止包含密码原文或哈希值。审计日志写入失败（异步投递）不阻塞登录成功响应，但必须在回调中记录 `logger.warning()`。

9. **[禁止行为] 禁止在登录成功后自动执行 Token 续期**：AUTH-02 仅负责在登录成功时签发续期令牌。续期令牌的使用、轮换、过期处理均归属 AUTH-03。AUTH-02 的 Service 层禁止调用任何续期逻辑。

10. **[偷懒红线] 禁止假设 verify_password() 永不失败**：bcrypt 内部可能因内存不足、passlib 版本不兼容等原因抛出异常。步骤 2 中必须显式捕获 `HashingError` 并返回 500，不能假设"哈希比对永不会失败"。

### 1.12 文档详细度自检清单 `【对内实现】`

- [x] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成编码
- [x] 无偷懒表述：全文无 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：所有对外类型已转为契约引用（§1.3、§1.4）；内部类型约束在 §1.6 接口签名和 §1.5 逻辑步骤中给出
- [x] 逻辑步骤完整：6 个步骤，每步有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：4 种异常 + 2 种边界条件，每种有精确触发阈值、逐步处理策略、重试参数
- [x] 无隐藏假设：所有默认值来源（`ACCESS_TOKEN_EXPIRE_MINUTES=15`、`REFRESH_TOKEN_EXPIRE_DAYS=7`、`BCRYPT_ROUNDS=12`）、条件分支（dummy hash 防侧信道、is_active 优雅降级）、业务规则均已显式写出
- [x] 技术栈绑定明确：必须使用和禁止使用的项均已列出（§1.1），且与项目技术栈设计文档保持一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致（见 §1.15）

### 1.14 外部接口契约清单 `【已锁定】`

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| LoginRequest | `docs/contracts/AUTH-02/LoginRequest.json` | input | draft | AUTH-02 | AUTH-05 |
| LoginResponse | `docs/contracts/AUTH-02/LoginResponse.json` | output | draft | AUTH-02 | AUTH-05, AUTH-06 |
| LoginErrorResponse | `docs/contracts/AUTH-02/LoginErrorResponse.json` | output | draft | AUTH-02 | AUTH-05 |
| UserRole | `docs/contracts/AUTH-01/UserRole.json` | shared-enum | draft | AUTH-01 | AUTH-02 (复用) |
| ValidationErrorResponse | `docs/contracts/SEC-05/ValidationErrorResponse.json` | output | draft | SEC-05 | AUTH-02 (复用) |

### 1.15 意图一致性声明 `【对内实现】`

- **配套意图文档**：`AUTH-02-用户登录-意图文档.md`
- **冻结时间**：`2026-05-26 22:47:13`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档 §1.6.1/§1.6.2 中的业务字段定义一致（LoginRequest 对应输入定义、LoginResponse 对应输出定义、LoginErrorResponse 对应失败原因说明）
  - [x] 本落地规范中的状态机实现与意图文档 §1.7 中的状态业务定义一致（均无状态机，一次性请求-响应操作）
  - [x] 本落地规范中的异常处理策略与意图文档 §1.8 中的异常业务策略一致（§1.9.1 凭据错误对应 §1.8.1；§1.9.2 账号状态异常对应 §1.8.3；§1.9.3 字段缺失对应 §1.8.2；§1.9.4 系统错误对应 §1.8.4）
  - [x] 本落地规范中的验收测试场景（§1.10）覆盖意图文档中全部 10 项验收标准（AC-01~AC-10）
  - [x] 本落地规范中的技术实现未超出意图文档 §1.12 中 9 项"留给规范阶段的技术决策"的范围
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
