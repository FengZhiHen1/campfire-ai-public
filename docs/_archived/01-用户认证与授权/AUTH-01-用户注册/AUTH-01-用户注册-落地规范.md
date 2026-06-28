## 1 功能点：AUTH-01 用户注册 — 落地规范

> **文档生成时间**：2026-05-26 21:09:49
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 21:09:49 | AI Assistant | 初始版本，基于已冻结的意图文档 v2.0 和设计文档 v1.0 生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `AUTH-01-用户注册-设计文档.md`。

---

### 1.1 技术栈绑定 【对内实现】

- **必须使用**：
  - `fastapi>=0.115` — APIRouter、Depends() 依赖注入、HTTPException
  - `pydantic>=2.0` — BaseModel、Field()、model_validator
  - `sqlalchemy>=2.0` — async engine、async session、declarative Base、sa.Enum
  - `passlib>=1.7` — CryptContext（bcrypt 实现）
  - `uuid`（Python 标准库） — 仅用于类型注解，实际生成由 PostgreSQL gen_random_uuid() 执行
  - `asyncio`（Python 标准库） — create_task() 投递审计日志异步任务
- **禁止使用**：
  - 禁止直接调用 `bcrypt` 库（必须通过 `packages/py-auth/hashing.py` 封装）
  - 禁止在路由层拼接 SQL 字符串（必须通过 Repository 层使用 SQLAlchemy 参数化查询）
  - 禁止在注册接口中签发 JWT Token（JWT 签发归属 AUTH-02）
  - 禁止在注册后自动创建 Redis Session（会话管理归属 AUTH-06）

### 1.2 文件归属 【对内实现】

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| Pydantic Schema | `packages/py-schemas/py_schemas/auth.py` | RegisterRequest、RegisterResponse、UserRole 枚举 |
| ORM 模型 | `packages/py-db/py_db/models/auth.py` | User ORM 模型，映射 users 表 |
| ORM 基类 | `packages/py-db/py_db/models/base.py` | 共享 Base + UUID PK Mixin + Timestamp Mixin |
| Repository | `packages/py-db/py_db/repositories/user_repository.py` | create()、find_by_username_lower()、find_by_phone() |
| Service 层 | `apps/api-server/app/services/auth_service.py` | register_user() — 核心注册逻辑编排 |
| 路由注册 | `apps/api-server/app/api/v1/auth.py` | POST /api/v1/auth/register |
| 异常类（复用） | `packages/py-auth/py_auth/exceptions.py` | HashingError（已存在）；新增 DuplicateFieldError |
| 密码哈希（复用） | `packages/py-auth/py_auth/hashing.py` | hash_password() — SEC-01 定义，AUTH-01 消费 |
| 测试文件 | `apps/api-server/tests/api/v1/test_auth_register.py` | 注册接口单元/集成测试 |

---

### 1.3 输入定义 【已锁定】

**RegisterRequest**
- 【契约引用】`docs/contracts/AUTH-01/RegisterRequest.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-05（登录注册界面）

### 1.4 输出定义 【已锁定】

**RegisterResponse**
- 【契约引用】`docs/contracts/AUTH-01/RegisterResponse.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-05（登录注册界面）

**ValidationErrorResponse**
- 【契约引用】`docs/contracts/SEC-05/ValidationErrorResponse.json`
- 本模块作为该契约的消费方（复用 SEC-05 已定义的 422 错误格式）
- 消费方：AUTH-05（登录注册界面）

**UserRole**
- 【契约引用】`docs/contracts/AUTH-01/UserRole.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-02（用户登录）、AUTH-04（五级RBAC鉴权）

### 1.5 核心逻辑步骤 【对内实现】

按执行顺序列出 7 个原子步骤。每步失败即中断流程，返回对应错误响应，不进入后续步骤。

1. **步骤 1：Pydantic 输入校验**
   - **操作对象**：HTTP 请求体（JSON）
   - **具体操作**：FastAPI 路由层通过 `Depends(RegisterRequest)` 自动执行 Pydantic 校验。校验规则：username（`Field(min_length=4, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")`）、password（`Field(min_length=8)`）、role（UserRole 枚举自动校验）、phone（`Field(min_length=11, max_length=11, pattern=r"^1[3-9]\d{9}$")`）、real_name（`Field(default=None, min_length=2, max_length=20)`）
   - **输入来源**：`POST /api/v1/auth/register` 请求体 JSON
   - **输出去向**：校验通过的 `RegisterRequest` 实例 → 步骤 2（Service 层调用 `register_user(request)` 继续处理）
   - **失败行为**：Pydantic 校验失败 → FastAPI 自动返回 HTTP 422，响应体格式 `{"errors": [{"field": "username", "reason": "字段 'username' 校验失败", "constraint": "min_length"}]}`。不执行任何后续步骤。

2. **步骤 2：密码强度校验**
   - **操作对象**：`RegisterRequest.password` 字段值（str）
   - **具体操作**：在 Service 层使用正则 `^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$` 校验密码复杂度。该正则使用正向前瞻断言：`(?=.*[a-z])` 确保至少包含一个小写字母、`(?=.*[A-Z])` 至少一个大写字母、`(?=.*\d)` 至少一个数字、`.{8,}` 至少 8 位。特殊字符不禁止。
   - **输入来源**：步骤 1 校验通过的 `RegisterRequest.password`
   - **输出去向**：校验通过的密码原文 → 步骤 5（密码哈希）
   - **失败行为**：正则不匹配 → 抛出 `HTTPException(status_code=422, detail={"errors": [{"field": "password", "reason": "密码必须同时包含大写字母、小写字母和数字", "constraint": "password_complexity"}]})`。不执行后续步骤。

3. **步骤 3：真实姓名条件必填校验**
   - **操作对象**：`RegisterRequest.real_name` 字段值（str | None）
   - **具体操作**：检查 `role == UserRole.EXPERT` 且 `real_name is None` → 视为校验失败。其他角色下 real_name 为 None 属合法。
   - **输入来源**：步骤 1 校验通过的 `RegisterRequest.role` 和 `RegisterRequest.real_name`
   - **输出去向**：校验通过 → 步骤 4
   - **失败行为**：专家角色缺少真实姓名 → 抛出 `HTTPException(status_code=422, detail={"errors": [{"field": "real_name", "reason": "专家角色必须填写真实姓名", "constraint": "required_for_expert"}])}`。不执行后续步骤。

4. **步骤 4：用户名唯一性检查**
   - **操作对象**：`RegisterRequest.username` 字段值（str）
   - **具体操作**：调用 `user_repository.find_by_username_lower(username)` → 执行 SQL `SELECT 1 FROM users WHERE LOWER(username) = LOWER(:val) LIMIT 1`。走 `idx_users_username_lower` 索引（B-tree on `LOWER(username)`）。
   - **输入来源**：步骤 1 校验通过的 `RegisterRequest.username`
   - **输出去向**：未查到 → 步骤 5（手机号唯一性检查）
   - **失败行为**：查询返回记录 → 抛出 `HTTPException(status_code=409, detail={"code": "DUPLICATE_USERNAME", "message": "该用户名已被注册"})`。不泄露已注册账号的角色类型、注册时间等信息。不执行后续步骤。

5. **步骤 5：手机号唯一性检查**
   - **操作对象**：`RegisterRequest.phone` 字段值（str）
   - **具体操作**：调用 `user_repository.find_by_phone(phone)` → 执行 SQL `SELECT 1 FROM users WHERE phone = :val LIMIT 1`。走 `idx_users_phone` 唯一索引。
   - **输入来源**：步骤 1 校验通过的 `RegisterRequest.phone`
   - **输出去向**：未查到 → 步骤 6（密码哈希）
   - **失败行为**：查询返回记录 → 抛出 `HTTPException(status_code=409, detail={"code": "DUPLICATE_PHONE", "message": "该手机号已被注册"})`。不泄露已注册账号的任何信息。不执行后续步骤。

6. **步骤 6：密码哈希**
   - **操作对象**：步骤 2 校验通过的密码原文（str）
   - **具体操作**：调用 `hash_password(plain_password: str) -> str` → 该函数位于 `packages/py-auth/py_auth/hashing.py`，使用 `passlib.context.CryptContext(schemes=["bcrypt"])`，salt rounds 默认 12（优先从 `get_settings().BCRYPT_ROUNDS` 读取，缺失时使用硬编码默认值 12）。哈希计算耗时约 250ms。
   - **输入来源**：步骤 2 校验通过的密码原文
   - **输出去向**：bcrypt 哈希密文（str）→ 步骤 7（数据写入）
   - **失败行为**：bcrypt 内部错误（如 `passlib.exc.PasswordSizeError`、内存不足）→ hashing.py 抛出 `HashingError("Password hashing failed")`。Service 层捕获后抛出 `HTTPException(status_code=500, detail="系统繁忙，请稍后重试")`。记录审计日志：`logger.error("hash_password_failed", error=str(e))`。不执行后续步骤。

7. **步骤 7：数据写入与审计日志**
   - **操作对象**：`User` ORM 模型实例
   - **具体操作**：
     1. 构造 `User` 实例：`User(username=request.username, password_hash=hashed, role=request.role, phone=request.phone, real_name=request.real_name)`。`id` 字段由 PostgreSQL `gen_random_uuid()` 自动生成，`created_at` 和 `updated_at` 由 Timestamp Mixin 自动填充。
     2. 调用 `user_repository.create(user)` → 执行 SQL `INSERT INTO users (id, username, password_hash, role, phone, real_name, created_at, updated_at) VALUES (DEFAULT, :username, :password_hash, :role, :phone, :real_name, NOW(), NOW()) RETURNING *`。
     3. INSERT 成功后，通过 `asyncio.create_task()` 异步投递审计日志：`logger.critical(op_type="USER_REGISTER", user_id=str(user.id), username=user.username, role=user.role.value)`。审计日志写入失败不阻塞注册响应。
   - **输入来源**：步骤 1 的所有字段 + 步骤 6 的密码哈希值
   - **输出去向**：数据库 `users` 表新增一行记录；审计日志流写入日志系统。返回 `RegisterResponse(result="success", user_id=str(user.id), message="注册成功")` + HTTP 201 Created。
   - **失败行为**：
     - SQLAlchemy `IntegrityError`（数据库 UNIQUE 约束冲突，TOCTOU 竞态场景）→ 捕获异常，检查 `error.orig.pgcode == "23505"`（唯一约束违反），根据约束名称（`unique_username` / `unique_phone`）区分错误类型。若无法精确区分，返回通用 409 `{"detail": {"code": "DUPLICATE_FIELD", "message": "用户名或手机号已被注册"}}`。
     - SQLAlchemy `OperationalError` / `DBAPIError`（数据库连接异常）→ 抛出 `HTTPException(status_code=500, detail="系统繁忙，请稍后重试")`。
     - 任何未预期的 Exception → 全局异常处理器捕获，返回 500，记录 `logger.critical("unexpected_error", error=str(e), traceback=...)`。

### 1.6 接口契约 【已锁定】

#### 1.6.1 接口：register_user — 用户注册

```python
async def register_user(
    request: RegisterRequest,           # Pydantic 校验后的注册请求
    user_repo: UserRepository,          # FastAPI Depends 注入的 Repository
    password_hasher: PasswordHasher,    # FastAPI Depends 注入的 hashing 适配器
    audit_logger: AuditLogger,          # FastAPI Depends 注入的审计日志器
) -> RegisterResponse:
    """
    接收用户提交的注册信息，经三层校验（格式→唯一性→持久化）后创建用户账号，
    返回全局唯一的用户标识。

    Args:
        request: Pydantic 校验通过的注册请求，包含 username/password/role/phone/real_name
        user_repo: UserRepository 实例，封装 users 表的 CRUD 操作
        password_hasher: PasswordHasher 适配器，封装 bcrypt 哈希调用
        audit_logger: AuditLogger 适配器，封装审计日志写入

    Returns:
        RegisterResponse(result="success", user_id=str, message="注册成功")
        HTTP 201 Created

    Raises:
        HTTPException(422):
            - Pydantic 字段级校验失败（password 长度不足、username 格式不匹配等）
            - 密码复杂度校验失败（缺少大写/小写/数字）
            - 专家角色缺少 real_name
        HTTPException(409):
            - detail.code="DUPLICATE_USERNAME" — 用户名已被注册
            - detail.code="DUPLICATE_PHONE" — 手机号已被注册
        HTTPException(500):
            - 密码 bcrypt 哈希计算失败
            - 数据库 INSERT 操作失败
            - 其他未预期的内部错误

    Side Effects:
        - 写入一条新记录到 PostgreSQL users 表（事务保证原子性）
        - 异步写入一条审计日志（op_type="USER_REGISTER"）
        - 数据库层面通过 gen_random_uuid() 生成 UUIDv4 主键

    Idempotency:
        非幂等操作。每次调用创建新的独立用户账号。通过唯一性检查（步骤 4、5）防止重复创建。

    Thread Safety:
        线程安全。内部无共享可变状态，所有状态通过 Repository 层的数据库事务管理。
        唯一性检查（SELECT）与 INSERT 之间存在 TOCTOU 竞态窗口，数据库 UNIQUE 约束为最终安全网。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `register_user` — 语义化，描述"注册用户"的业务动作 |
| **输入类型** | `RegisterRequest`（【契约引用】`docs/contracts/AUTH-01/RegisterRequest.json`） |
| **输出类型** | `RegisterResponse`（【契约引用】`docs/contracts/AUTH-01/RegisterResponse.json`） |
| **异常类型** | `HTTPException(422)` — 格式复用 SEC-05 ValidationErrorResponse；`HTTPException(409)` — 自定义错误码 DUPLICATE_USERNAME/DUPLICATE_PHONE；`HTTPException(500)` — 通用内部错误 |
| **副作用** | 写入 PostgreSQL users 表；写入审计日志 |
| **幂等性** | 非幂等。唯一性校验提供去重保护，但每次调用创建新账号 |
| **并发安全** | 线程安全；TOCTOU 竞态由数据库 UNIQUE 约束兜底 |

#### 1.6.2 路由注册：POST /api/v1/auth/register

```python
from fastapi import APIRouter, Depends, status
from packages.py_schemas.py_schemas.auth import RegisterRequest, RegisterResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "注册成功"},
        422: {"description": "输入校验失败", "model": ValidationErrorResponse},
        409: {"description": "用户名或手机号已存在"},
        500: {"description": "系统内部错误"}
    }
)
async def register(
    request: RegisterRequest = Depends(),      # Pydantic Body 校验
    user_repo: UserRepository = Depends(get_user_repository),
    password_hasher: PasswordHasher = Depends(get_password_hasher),
    audit_logger: AuditLogger = Depends(get_audit_logger),
) -> RegisterResponse:
    """
    用户注册端点。POST /api/v1/auth/register

    Request Body (JSON):
        {
            "username": "zhang_san",
            "password": "Abc12345",
            "role": "family",
            "phone": "13800138000",
            "real_name": "张三"
        }

    Success Response 201:
        {
            "result": "success",
            "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "message": "注册成功"
        }

    Error Response 422 (ValidationErrorResponse, 复用 SEC-05 格式):
        {
            "errors": [
                {"field": "username", "reason": "用户名格式不正确", "constraint": "pattern"},
                {"field": "password", "reason": "密码必须同时包含大写字母、小写字母和数字", "constraint": "password_complexity"}
            ]
        }

    Error Response 409 (Conflict):
        {
            "detail": {
                "code": "DUPLICATE_USERNAME",
                "message": "该用户名已被注册"
            }
        }
    """
    return await register_user(request, user_repo, password_hasher, audit_logger)
```

### 1.7 依赖与集成接口 【已锁定】

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 关系型数据库 | PostgreSQL 17.x | `async_session.execute(select(User).where(...))` | 查询用户名/手机号唯一性；INSERT 创建用户记录 | 项目结构 §6.1（`packages/py-db/`） |
| 密码哈希服务 | `packages/py-auth/hashing.py` | `hash_password(plain: str) -> str` | bcrypt 哈希计算（salt rounds=12，passlib CryptContext） | 项目结构 §6.1（`packages/py-auth/py_auth/hashing.py`）；技术栈 §5 |
| 配置服务 | `packages/py-config/` | `get_settings().BCRYPT_ROUNDS` | 读取 bcrypt rounds 配置（当前未定义，hashing.py 使用默认值 12） | 项目结构 §6.1（`packages/py-config/`）；DEPLOY-05 |
| 日志系统 | `packages/py-logger/` | `logger.critical(op_type="USER_REGISTER", ...)`; `logger.error(...)` | 注册成功审计日志（`critical()`）；异常记录（`error()`） | 项目结构 §6.1（`packages/py-logger/`）；OBS-01 §1.1 |
| Schema 契约 | `packages/py-schemas/py_schemas/auth.py` | `RegisterRequest.model_validate(data)` | Pydantic v2 输入校验 | 项目结构 §6.1（`packages/py-schemas/`） |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| AUTH-04（五级RBAC鉴权） | UserRole 枚举值 `family/teacher/expert` 写入 users 表 `role` 字段 | 注册时写入初始角色，供 AUTH-04 后续权限判定 | ⏭️ 待落地（AUTH-01 仅写入 ENUM 值，不调用 AUTH-04 接口） |
| SEC-05（输入校验防护） | ValidationErrorResponse 错误格式 `{"errors": [{"field", "reason", "constraint"}]}` | 复用 422 错误响应格式 | ✅ 已落地 |

---

### 1.8 状态机 【对内实现】

本功能点不涉及状态流转，故无需状态机。注册流程为一次性操作——用户提交信息后，系统要么创建成功（生成账号），要么拒绝创建（返回失败原因）。不涉及中间状态或后续状态转换。

### 1.9 异常与边界条件 【对内实现】

#### 1.9.1 异常 1：输入信息不合法（422 Unprocessable Entity）

- **触发条件**：
  - Pydantic 字段级校验不通过：username 长度不在 [4, 32] 区间、username 包含不允许的字符、password 长度 < 8、role 值不在枚举中、phone 不匹配 `^1[3-9]\d{9}$`、real_name 长度不在 [2, 20] 区间（非 None 时）
  - Service 层密码复杂度校验不通过：密码不含大写字母、不含小写字母、不含数字
  - 专家角色缺少 real_name（role=expert 且 real_name is None）
  - 必填字段缺失：request body 中缺少 username/password/role/phone 任一字段（real_name 执行条件必填）
- **处理策略**：
  1. Pydantic 校验失败 → FastAPI 自动拦截，在路由层返回 422 响应，不进入 Service 层。响应体复用 SEC-05 格式：`{"errors": [{"field": "<字段名>", "reason": "<人类可读原因>", "constraint": "<约束名>"}]}`
  2. Service 层密码复杂度校验失败 → 在 `register_user()` 中主动检测，抛出 `HTTPException(status_code=422)` 使用相同格式
  3. 专家角色缺少 real_name → 在 `register_user()` 中主动检测，抛出 `HTTPException(status_code=422)`
  4. 所有 422 响应**不执行任何后续步骤**（不查询数据库、不计算哈希）
  5. 记录结构化日志：`logger.warning("input_validation_failed", errors=error_details)`
- **重试参数**：无需重试。客户端修正输入后重新发起请求。

#### 1.9.2 异常 2：用户名或手机号已被注册（409 Conflict）

- **触发条件**：
  - Repository 层 `find_by_username_lower(username)` 查询返回非空记录（`LOWER(username)` 大小写不敏感匹配命中）
  - Repository 层 `find_by_phone(phone)` 查询返回非空记录（phone 精确匹配命中）
  - PostgreSQL INSERT 时触发 UNIQUE 约束违反（TOCTOU 竞态场景，两个并发请求同时通过唯一性检查）
- **处理策略**：
  1. 步骤 4/5 中 Repository 预检查发现重复 → 立即中断，抛出 `HTTPException(status_code=409)`。响应的 `detail.code` 精确区分 `"DUPLICATE_USERNAME"` 和 `"DUPLICATE_PHONE"`。`detail.message` 提供用户可读的提示文本（"该用户名已被注册" / "该手机号已被注册"）。
  2. 步骤 7 中 INSERT 触发 IntegrityError（唯一约束违反）→ 捕获 `exc.orig.pgcode == "23505"`，解析 `exc.orig.diag.constraint_name` 区分 `unique_username` / `unique_phone`。若约束名解析失败（极边缘情况），返回通用 409 `{"code": "DUPLICATE_FIELD", "message": "用户名或手机号已被注册"}`。
  3. 不泄露已注册账号的任何额外信息（角色类型、注册时间、手机号等）。
- **重试参数**：无需重试。用户需更换用户名/手机号后重新提交。

#### 1.9.3 异常 3：数据库或内部服务错误（500 Internal Server Error）

- **触发条件**：
  - 密码哈希计算失败：`hashing.py` 的 `hash_password()` 抛出 `HashingError`（原因包括 passlib 内部错误、内存不足）
  - 数据库 INSERT 操作失败：`user_repository.create()` 抛出 `OperationalError`（连接超时、连接池耗尽）、`DBAPIError`（驱动级错误）
  - 任何未预期的 Python Exception（如 `TypeError`、`AttributeError` 等编码缺陷）
- **处理策略**：
  1. `HashingError` → Service 层捕获，返回 `HTTPException(status_code=500, detail="系统繁忙，请稍后重试")`。记录 `logger.error("hash_password_failed", error=str(e))`。
  2. SQLAlchemy 数据库异常 → Service 层捕获，返回通用 500 响应（不泄露数据库连接字符串、表结构等内部信息）。记录 `logger.critical("database_error", pg_code=..., detail=str(e))`。
  3. 未预期的 Exception → 全局异常处理器捕获：`@app.exception_handler(Exception) async def generic_exception_handler(request, exc)` → 返回 500，记录 `logger.critical("unexpected_error", path=request.url.path, error=str(exc), traceback=traceback.format_exc())`。
  4. 所有 500 响应保持当前注册页面状态（前端不跳转、不重定向）。不丢失用户已填写的合法信息（前端通过保持表单状态实现）。
  5. 审计日志写入为 `asyncio.create_task()` 异步投递，日志系统故障不影响 201 注册成功响应（但写入失败时记录 warning 日志）。
- **重试参数**：无需服务端自动重试。用户可稍后手动重新提交。Hashing 操作和数据库操作不实现内建重试——这些是瞬时故障，重试不提高成功率。

#### 1.9.4 边界条件 1：并发注册同一用户名（TOCTOU 竞态）

- **触发条件**：两个并发请求使用相同用户名，在步骤 4 的唯一性 SELECT 查询中均返回"未找到"，然后同时执行步骤 7 的 INSERT。数据库 UNIQUE 约束确保最终只有一条记录成功。
- **处理策略**：
  1. 第一条 INSERT 成功 → 返回 201，`RegisterResponse` 包含 user_id
  2. 第二条 INSERT 失败 → PostgreSQL 返回 `UNIQUE constraint violation (SQLSTATE 23505)`，Service 层捕获 IntegrityError，解析约束名确认是 `unique_username`，返回 409 `{"code": "DUPLICATE_USERNAME", "message": "该用户名已被注册"}`
  3. 此场景在低并发注册（用户注册非高频操作）下发生概率极低，不引入 SELECT ... FOR UPDATE 锁（会显著增加延迟）
- **重试参数**：无需重试。

### 1.10 验收测试场景 【对内实现】

#### 1.10.1 正向测试 1：家属角色完整注册成功

- **场景**：家属用户提供完整合法的注册信息，系统成功创建账号
- **Given**:
  ```json
  {
    "username": "family_user",
    "password": "Family123",
    "role": "family",
    "phone": "13800000001",
    "real_name": "张爸爸"
  }
  ```
- **When**: 发送 `POST /api/v1/auth/register`，请求体为上述 JSON
- **Then**:
  - HTTP 状态码 = `201 Created`
  - 响应体包含：`result: "success"`、`user_id`（36 字符 UUIDv4 格式，符合正则 `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`）、`message: "注册成功"`
  - 数据库 users 表新增一行，`username = "family_user"`，`role = "family"`，`real_name = "张爸爸"`，`password_hash` 为 bcrypt 哈希值（以 `$2b$` 或 `$2a$` 开头，长度 ≥ 60）
  - 审计日志中有一条 `op_type="USER_REGISTER"` 的 `critical` 级别日志

#### 1.10.2 正向测试 2：老师角色可选 real_name 注册成功

- **场景**：老师用户未填写真实姓名（选填字段），系统成功创建账号
- **Given**:
  ```json
  {
    "username": "teacher_li",
    "password": "Teacher88",
    "role": "teacher",
    "phone": "13900000002",
    "real_name": null
  }
  ```
- **When**: 发送 `POST /api/v1/auth/register`，请求体为上述 JSON
- **Then**:
  - HTTP 状态码 = `201 Created`
  - 响应体 `result: "success"`
  - 数据库 users 表中 `real_name` 字段值为 `NULL`

#### 1.10.3 正向测试 3：大小写不同用户名视为同一用户

- **场景**：已注册用户 "User_Test"，他人尝试注册 "user_test" 被拒绝（大小写不敏感唯一性）
- **Given**: 系统中已存在 `username = "User_Test"` 的账号
  ```json
  {
    "username": "user_test",
    "password": "Testing12",
    "role": "family",
    "phone": "13800000099",
    "real_name": null
  }
  ```
- **When**: 发送 `POST /api/v1/auth/register`，请求体为上述 JSON
- **Then**:
  - HTTP 状态码 = `409 Conflict`
  - 响应体 `detail.code = "DUPLICATE_USERNAME"`，`detail.message = "该用户名已被注册"`

#### 1.10.4 异常测试 1：密码复杂度不足（仅大小写、缺数字）

- **场景**：用户密码缺少数字，系统拒绝
- **Given**:
  ```json
  {
    "username": "weak_user",
    "password": "AbCdEfGh",
    "role": "family",
    "phone": "13700000003",
    "real_name": null
  }
  ```
- **When**: 发送 `POST /api/v1/auth/register`
- **Then**:
  - HTTP 状态码 = `422`
  - 响应体 `errors[0].field = "password"`，`errors[0].reason` 包含"必须同时包含大写字母、小写字母和数字"，`errors[0].constraint = "password_complexity"`
  - 数据库中无新记录创建

#### 1.10.5 异常测试 2：手机号格式不正确

- **场景**：用户输入非中国大陆手机号格式
- **Given**:
  ```json
  {
    "username": "bad_phone_user",
    "password": "BadPhone1",
    "role": "teacher",
    "phone": "12345678901",
    "real_name": null
  }
  ```
- **When**: 发送 `POST /api/v1/auth/register`
- **Then**:
  - HTTP 状态码 = `422`
  - 响应体 `errors[0].field = "phone"`，`errors[0].constraint = "pattern"`
  - 数据库中无新记录创建

#### 1.10.6 异常测试 3：专家缺少 real_name

- **场景**：专家角色未填写真实姓名（专家必填），系统拒绝
- **Given**:
  ```json
  {
    "username": "expert_no_name",
    "password": "Expert099",
    "role": "expert",
    "phone": "13600000004",
    "real_name": null
  }
  ```
- **When**: 发送 `POST /api/v1/auth/register`
- **Then**:
  - HTTP 状态码 = `422`
  - 响应体 `errors[0].field = "real_name"`，`errors[0].reason` 包含"专家角色必须填写真实姓名"
  - 数据库中无新记录创建

#### 1.10.7 异常测试 4：必填字段缺失（缺少 phone）

- **场景**：用户提交不包含 phone 字段的请求体
- **Given**:
  ```json
  {
    "username": "missing_phone",
    "password": "Missing1",
    "role": "family",
    "real_name": null
  }
  ```
- **When**: 发送 `POST /api/v1/auth/register`，请求体缺少 `phone` 字段
- **Then**:
  - HTTP 状态码 = `422`
  - 响应体 `errors` 数组中包含 `field: "phone"` 的条目
  - 数据库中无新记录创建

### 1.11 注意事项与禁止行为（编码层面） 【对内实现】

1. **[约束] 密码不可逆存储**：用户密码在 `users.password_hash` 列中仅存储 bcrypt 哈希值。禁止在任何位置（数据库、日志、异常消息、调试输出）记录密码原文或哈希值。`hashing.py` 的 `hash_password()` 是唯一密码写入入口。

2. **[约束] 审计日志不可绕过**：注册成功时 `logger.critical(op_type="USER_REGISTER")` 必须执行。即使是异步投递方式（`asyncio.create_task()`），也不允许被 `try-except` 静默吞掉——task 回调中必须用 `logger.warning()` 记录日志写入异常。

3. **[易错点] 密码校验分成两层**：Schema 层仅校验 `min_length=8`，Service 层校验大小写字母+数字。不要在 Schema 层使用 `pattern=r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$"` —— 这会将密码复杂度校验混入字段级校验，失去精确的错误提示能力。

4. **[易错点] 大小写不敏感唯一性依赖索引**：`LOWER(username)` 查询需要对应索引 `CREATE UNIQUE INDEX idx_users_username_lower ON users (LOWER(username))`。若索引不存在，查询将执行全表扫描。建议在 Alembic 迁移脚本中显式创建此索引。

5. **[易错点] TOCTOU 竞态的错误码粒度**：步骤 7 的 `IntegrityError` 捕获逻辑中，`exc.orig.diag.constraint_name` 返回值依赖 PostgreSQL 方言和 SQLAlchemy 版本。务必在集成测试中覆盖两个约束分别触发的场景，确认错误码映射正确。

6. **[禁止行为] 禁止注册后自动登录**：注册成功响应禁止包含 Access Token 或 Refresh Token。禁止在注册 Service 中调用 JWT 签发函数。禁止在注册后创建 Redis Session。前端收到 201 后应引导用户进入登录页面，而非自动登录。

7. **[禁止行为] 禁止在 REPL/调试时打印密码**：开发和调试过程中，禁止使用 `print(request.password)`、`logger.info(f"password={...}")` 等任何形式输出密码原文。

8. **[禁止行为] 禁止绕过 Repository 层直接操作数据库**：路由层和 Service 层必须通过 `UserRepository` 进行数据库操作。禁止在 Service 中导入 `async_session` 直接执行 SQL——这会破坏单向依赖原则，并使单元测试中无法 mock 数据库层。

9. **[偷懒红线] 禁止省略密码哈希失败处理**：不能假设 `hash_password()` 调用永不会失败。bcrypt 内部可能因内存不足、passlib 版本不兼容等原因抛出异常。必须显式 catch `HashingError` 并返回 500。

### 1.12 文档详细度自检清单 【对内实现】

- [x] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成编码
- [x] 无偷懒表述：全文无 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：所有对外类型已转为契约引用（§1.3、§1.4）；内部类型约束在 §1.6 接口签名中给出
- [x] 逻辑步骤完整：7 个步骤，每步有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：4 种异常/边界场景（422、409、500、TOCTOU），每种有精确触发阈值、逐步处理策略、重试参数
- [x] 无隐藏假设：所有默认值来源（BCRYPT_ROUNDS=12）、条件分支（专家 role 必填 real_name）、业务规则（大小写不敏感唯一性）都已显式写出
- [x] 技术栈绑定明确：必须使用和禁止使用的项均已列出（§1.1）
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致（见 §1.15）

### 1.14 外部接口契约清单 【对内实现】

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| RegisterRequest | `docs/contracts/AUTH-01/RegisterRequest.json` | input | draft | AUTH-01 | AUTH-05 |
| RegisterResponse | `docs/contracts/AUTH-01/RegisterResponse.json` | output | draft | AUTH-01 | AUTH-05 |
| UserRole | `docs/contracts/AUTH-01/UserRole.json` | shared-enum | draft | AUTH-01 | AUTH-02, AUTH-04 |
| ValidationErrorResponse | `docs/contracts/SEC-05/ValidationErrorResponse.json` | output | draft | SEC-05 | AUTH-01, AUTH-05 |

### 1.15 意图一致性声明 【对内实现】

- **配套意图文档**：`AUTH-01-用户注册-意图文档.md`
- **冻结时间**：2026-05-26 20:50:52
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档 §1.6.1/§1.6.2 中的业务字段定义一致
  - [x] 本落地规范中的状态机实现与意图文档 §1.7 中的状态业务定义一致（均无状态机）
  - [x] 本落地规范中的异常处理策略与意图文档 §1.8 中的异常业务策略一致（输入不合法→422、重复→409、系统错误→500）
  - [x] 本落地规范中的验收测试场景（§1.10）覆盖意图文档中全部 10 项验收标准（AC-01~AC-10）
  - [x] 本落地规范中的技术实现未超出意图文档 §1.12 中 8 项"留给规范阶段的技术决策"的范围
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
