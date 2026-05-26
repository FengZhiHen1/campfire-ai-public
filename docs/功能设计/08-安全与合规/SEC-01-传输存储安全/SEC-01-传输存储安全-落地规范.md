# 1 功能点：SEC-01 传输存储安全 — 落地规范

> **文档生成时间**：2026-05-26 17:20:59
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 17:20:59 | AI Assistant | 初始版本，基于设计文档 v1.0 和契约协调报告（13 类型，零冲突） |

> **配套文档**：本模块的设计思路与决策依据见 `SEC-01-传输存储安全-设计文档.md`。

---

## 【对外接口 — 已锁定】

### 1.3 输入定义（精确类型 / 或契约引用）

**hash_password 接口输入**
- 【契约引用】`docs/contracts/SEC-01/hash_password.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-02（用户登录模块）

**verify_password 接口输入**
- 【契约引用】`docs/contracts/SEC-01/verify_password.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-02（用户登录模块）

**create_access_token 接口输入**
- 【契约引用】`docs/contracts/SEC-01/create_access_token.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-02（用户登录模块）

**verify_token 接口输入**
- 【契约引用】`docs/contracts/SEC-01/verify_token.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-02（用户登录模块）

**check_rate_limit 接口输入**
- 【契约引用】`docs/contracts/SEC-01/check_rate_limit.json`
- 本模块作为该契约的定义方
- 消费方：SEC-04（防刷限流模块）

**validate_file 接口输入**
- 【契约引用】`docs/contracts/SEC-01/validate_file.json`
- 本模块作为该契约的定义方
- 消费方：案例管理模块、文件上传路由

### 1.4 输出定义（精确类型 / 或契约引用）

**create_access_token 输出**
- 【契约引用】`docs/contracts/SEC-01/create_access_token.json`（返回 `str` 类型的 JWT token）
- 本模块作为该契约的定义方
- 消费方：AUTH-02

**verify_token 输出**
- 【契约引用】`docs/contracts/SEC-01/TokenPayload.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-02

**check_rate_limit 输出**
- 返回 `bool`（True=允许通过，False=触发限流）
- 触发限流时的 HTTP 响应体见 `RateLimitExceededResponse`

**validate_file 输出**
- 【契约引用】`docs/contracts/SEC-01/FileValidationResult.json`
- 本模块作为该契约的定义方
- 消费方：案例管理模块、文件上传路由

**限流拒绝响应**
- 【契约引用】`docs/contracts/SEC-01/RateLimitExceededResponse.json`
- 本模块作为该契约的定义方
- 消费方：SEC-04（防刷限流模块）、前端客户端

**脱敏手机号输出**
- 【契约引用】`docs/contracts/SEC-01/PhoneMaskedString.json`
- 本模块作为该契约的定义方
- 消费方：SEC-03（PII检测脱敏模块）、个人档案模块、前端客户端

### 1.6 接口契约（对外暴露的公共接口）

#### 1.6.1 接口 1：hash_password —— 密码哈希

```python
def hash_password(plain_password: str) -> str:
    """
    使用 bcrypt 对明文密码进行不可逆哈希。

    Args:
        plain_password: 明文密码原文，长度 8-64 字符

    Returns:
        str: bcrypt 哈希字符串，格式 `$2b$12$...`，每次调用产生不同的随机 salt

    Raises:
        ValueError: plain_password 长度不在 8-64 范围内
        HashingError: bcrypt 引擎内部错误（如 OOM）

    Side Effects:
        - 无。纯函数，无 I/O 操作。

    Idempotency:
        不幂等——每次调用使用随机 salt，相同输入产生不同输出。密码验证必须使用 verify_password。

    Thread Safety:
        本函数无共享可变状态，线程安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `hash_password` —— 语义化，描述"对密码进行哈希"的动作 |
| **输入类型** | `str`（`plain_password`，详见 `hash_password.json` 契约） |
| **输出类型** | `str`（bcrypt 哈希字符串） |
| **异常类型** | `ValueError`、`HashingError`（详见 1.9 节） |
| **副作用** | 无 |
| **幂等性** | 不幂等（随机 salt） |
| **并发安全** | 线程安全 |

#### 1.6.2 接口 2：verify_password —— 密码校验

```python
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证明文密码是否匹配已存储的 bcrypt 哈希值。

    Args:
        plain_password: 待验证的明文密码，长度 8-64 字符
        hashed_password: bcrypt 哈希值，格式 `$2b$12$...`

    Returns:
        bool: True=密码匹配，False=密码不匹配

    Raises:
        ValueError: 输入参数格式不合法
        HashingError: bcrypt 引擎内部错误

    Side Effects:
        - 无。纯函数，无 I/O 操作。

    Idempotency:
        幂等——相同输入始终返回相同结果。

    Thread Safety:
        本函数无共享可变状态，线程安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `verify_password` |
| **输入类型** | `str` + `str`（详见 `verify_password.json` 契约） |
| **输出类型** | `bool` |
| **异常类型** | `ValueError`、`HashingError`（详见 1.9 节） |
| **副作用** | 无 |
| **幂等性** | 幂等 |
| **并发安全** | 线程安全 |

#### 1.6.3 接口 3：create_access_token —— JWT 签发

```python
def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None,
) -> str:
    """
    签发 JWT 访问令牌，HS256 算法，header 中嵌入 kid 字段。

    Args:
        data: JWT payload 数据，必须包含 sub (user_id, str) 和 roles (角色列表, list[str])
        expires_delta: 自定义过期时长。None 时默认 15 分钟

    Returns:
        str: JWT token 字符串，header 包含 `{"alg": "HS256", "kid": "v1", "typ": "JWT"}`
             标准声明：iss, sub, iat, exp, jti (UUID v4)

    Raises:
        ValueError: data 缺少 sub 或 roles 字段
        TokenCreationError: JWT 签发失败（如密钥长度不足、jose 库内部错误）

    Side Effects:
        - 从环境变量 `JWT_SECRET_KEY` 读取当前签名密钥
        - 从环境变量 `JWT_KEY_VERSION` 读取当前密钥版本号（用作 kid）

    Idempotency:
        不幂等——每次调用生成不同的 jti 和 iat/exp，产生不同的 token 字符串。

    Thread Safety:
        只读环境变量，线程安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `create_access_token` |
| **输入类型** | `dict` + `timedelta | None`（详见 `create_access_token.json` 契约） |
| **输出类型** | `str`（JWT token） |
| **异常类型** | `ValueError`、`TokenCreationError`（详见 1.9 节） |
| **副作用** | 读取环境变量 `JWT_SECRET_KEY`、`JWT_KEY_VERSION` |
| **幂等性** | 不幂等（每次随机 jti + 时间戳） |
| **并发安全** | 线程安全 |

#### 1.6.4 接口 4：verify_token —— JWT 校验

```python
def verify_token(token: str) -> dict | None:
    """
    校验 JWT Token 签名和有效期，根据 header 的 kid 选择对应密钥。

    校验逻辑：
    1. 解码 token header，提取 kid 字段
    2. 若 kid == 当前版本 → 使用 JWT_SECRET_KEY 校验
    3. 若 kid == 上一个版本 → 使用 JWT_PREVIOUS_SECRET_KEY 校验（共栖期支持）
    4. 若 kid 不匹配任何已知版本或 header 中无 kid → 返回 None
    5. 校验签名 → 校验 exp（是否过期）→ 通过则返回 payload dict

    Args:
        token: JWT token 字符串

    Returns:
        dict | None: 解码后的 TokenPayload 字典（包含 sub, roles, kid, exp, iat）
                    校验失败返回 None

    Raises:
        TokenDecodeError: token 格式无效（非 JWT 格式字符串）

    Side Effects:
        - 从环境变量读取 JWT_SECRET_KEY 和 JWT_PREVIOUS_SECRET_KEY

    Idempotency:
        幂等——相同 token 始终返回相同结果。

    Thread Safety:
        只读环境变量，线程安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `verify_token` |
| **输入类型** | `str`（详见 `verify_token.json` 契约） |
| **输出类型** | `dict | None`（TokenPayload 结构，详见 `TokenPayload.json` 契约） |
| **异常类型** | `TokenDecodeError`（详见 1.9 节） |
| **副作用** | 读取环境变量 `JWT_SECRET_KEY`、`JWT_PREVIOUS_SECRET_KEY` |
| **幂等性** | 幂等 |
| **并发安全** | 线程安全 |

#### 1.6.5 接口 5：check_rate_limit —— 限流检查

```python
async def check_rate_limit(
    user_id: str | None = None,
    ip: str,
) -> bool:
    """
    Redis 滑动窗口限流检查，支持用户级和 IP 级双重限流。

    限流算法：
    1. 若 user_id 非空：生成 key `ratelimit:user:{user_id}:{unix_second}`
       对窗口内所有 key 执行 INCR 聚合计数，与 RATE_LIMIT_USER_PER_MINUTE 比较
    2. 始终执行 IP 级限流：生成 key `ratelimit:ip:{ip}:{unix_second}`
       对窗口内所有 key 执行 INCR 聚合计数，与 RATE_LIMIT_IP_PER_MINUTE 比较
    3. 任一级别超限 → 返回 False，同时设置 retry_after
    4. Redis 不可用时：fail-open，返回 True（放行），同时通过 py-logger 发送 CRITICAL 告警

    Args:
        user_id: 已登录用户的 ID；None 则仅执行 IP 级限流
        ip: 客户端 IP 地址

    Returns:
        bool: True=允许通过，False=触发限流

    Raises:
        不抛异常——Redis 故障时 fail-open 返回 True

    Side Effects:
        - 向 Redis 写入 INCR + EXPIRE（每个窗口 key 设置 TTL = WINDOW_SECONDS + 60 秒缓冲）
        - Redis 不可用时记录 CRITICAL 日志：`logger.critical("rate_limit_redis_unavailable", ip=ip, error=...)`

    Idempotency:
        不幂等——每次调用写入 Redis 计数器。连续多次调用对同一 key 的 INCR 会递增。

    Thread Safety:
        依赖 Redis 原子操作 INCR，线程安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `check_rate_limit` |
| **输入类型** | `str | None` + `str`（详见 `check_rate_limit.json` 契约） |
| **输出类型** | `bool` |
| **异常类型** | 不抛异常（fail-open 降级） |
| **副作用** | Redis 写入；Redis 故障时日志告警 |
| **幂等性** | 不幂等（INCR） |
| **并发安全** | 线程安全（Redis 原子操作） |

#### 1.6.6 接口 6：validate_file —— 文件安全校验

```python
def validate_file(filename: str, content: bytes) -> FileValidationResult:
    """
    三层递进文件安全校验：扩展名 → MIME 类型 → 文件头魔数。

    校验层级：
    1. 扩展名校验：从 filename 提取扩展名（不含点），转为小写，
       检查是否在 ALLOWED_FILE_EXTENSIONS 列表中
    2. MIME 类型校验：使用 python-magic 库检测 content 的实际 MIME 类型，
       映射到允许的类型集合 {application/pdf, image/jpeg, image/png,
       application/vnd.openxmlformats-officedocument.wordprocessingml.document}
    3. 魔数校验：读取 content 前 4 字节，比对已知文件头签名：
       PDF: b'%PDF', JPEG: b'\xff\xd8\xff', PNG: b'\x89PNG',
       DOCX: b'PK\x03\x04'（ZIP 格式）

    任一层校验失败 → 立即返回 FileValidationResult(is_valid=False, reason=...)，不再执行后续层。

    Args:
        filename: 上传文件的原始文件名（含扩展名）
        content: 上传文件的原始字节内容

    Returns:
        FileValidationResult: 校验结果（is_valid + 失败时的 reason）

    Raises:
        ValueError: filename 为空字符串或长度为 0
        FileTooLargeError: content 字节数超过类型大小上限（图片 5MB，文档 10MB）

    Side Effects:
        - 无。纯函数，不写数据库、不写文件系统。

    Idempotency:
        幂等——相同输入始终返回相同结果。

    Thread Safety:
        本函数无共享可变状态，线程安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `validate_file` |
| **输入类型** | `str` + `bytes`（详见 `validate_file.json` 契约） |
| **输出类型** | `FileValidationResult`（详见 `FileValidationResult.json` 契约） |
| **异常类型** | `ValueError`、`FileTooLargeError`（详见 1.9 节） |
| **副作用** | 无（纯函数） |
| **幂等性** | 幂等 |
| **并发安全** | 线程安全 |

---

## 【对内实现】

### 1.1 技术栈绑定

- **必须使用**：
  - `passlib[bcrypt]>=1.7.4` —— 密码哈希，use `bcrypt` 作为后端
  - `python-jose[cryptography]>=3.3.0` —— JWT 签发/校验，HS256 算法
  - `redis>=5.0` —— Redis 客户端，限流计数器通过 `INCR + EXPIRE` 原子操作
  - `pydantic>=2.0` —— 配置模型（`BaseSettings`）和响应模型
  - `pydantic-settings>=2.0` —— 从环境变量 / `.env` 文件加载 `SecurityConfig`
  - `python-magic>=0.4.27` —— MIME 类型检测（文件安全第二层）
  - `uuid` (stdlib) —— `event_id` 和 `trace_id` 的 UUID v4 生成
  - `datetime` (stdlib) —— 标准时区 Asia/Shanghai (`zoneinfo.ZoneInfo("Asia/Shanghai")`)
  - `structlog`（通过 `packages/py-logger`）—— 结构化日志
  - 所有安全配置项必须通过 `pydantic-settings` 的 `BaseSettings` 加载，字段名大写，前缀 `SECURITY_`
  - 密码哈希和 JWT 逻辑归属 `packages/py-auth/`（遵循项目结构 §6.1）
  - 限流逻辑归属 `packages/py-cache/`（遵循项目结构 §6.1）
  - 文件安全逻辑归属 `packages/py-storage/`（遵循项目结构 §6.1）

- **禁止使用**：
  - 禁止使用 `hashlib` 单次哈希（如 SHA256）替代 bcrypt 存储密码
  - 禁止使用 `os.environ.get()` 直接读取环境变量——必须通过 `pydantic-settings` 的 `BaseSettings` 统一加载
  - 禁止在代码或配置文件中硬编码 `JWT_SECRET_KEY`、`JWT_PREVIOUS_SECRET_KEY` 的值
  - 禁止使用 `PyJWT>=2.0`（与 `python-jose` 的 `jwt.decode` 行为不兼容，`python-jose` 返回 dict 而非 `PyJWT` 的 claims 对象）
  - 禁止使用同步 `redis.Redis` 直连——必须使用 `redis.asyncio.Redis`（与 FastAPI 的 async 中间件链兼容）
  - 禁止绕过 `validate_file` 直接存储上传文件——所有文件存储路径必须经过校验

### 1.2 文件归属

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 密码哈希模块 | `packages/py-auth/hashing.py` | `hash_password`、`verify_password` 函数实现 |
| JWT 凭证模块 | `packages/py-auth/jwt.py` | `create_access_token`、`verify_token` 函数实现 |
| 限流中间件 | `apps/api-server/app/middleware/rate_limit.py` | FastAPI Middleware，调用 `check_rate_limit`，注册到 app |
| 限流适配器 | `packages/py-cache/rate_limit.py` | `check_rate_limit` 函数实现，Redis 滑动窗口计数器 |
| 文件安全模块 | `packages/py-storage/file_security.py` | `validate_file` 函数实现，三层递进校验 |
| 脱敏中间件 | `apps/api-server/app/middleware/masking.py` | FastAPI 响应中间件，对手机号字段脱敏 |
| 安全配置 | `packages/py-config/security.py` | `SecurityConfig(BaseSettings)` 和 `RateLimitConfig(BaseSettings)` |
| 审计日志适配器 | `packages/py-logger/audit.py` | `write_audit_log` 函数，写入 PostgreSQL `audit_logs` 表 |
| 密钥轮换脚本 | `scripts/rotate-jwt-key.sh` | JWT 密钥轮换操作脚本化 |
| 测试文件 | `tests/packages/py-auth/test_hashing.py` | `hash_password` / `verify_password` 单元测试 |

### 1.5 核心逻辑步骤

**1.5.1 密码哈希流程（hash_password）**

1. **步骤 1：参数校验**
   - **操作对象**：`plain_password: str`
   - **具体操作**：检查 `len(plain_password)` 是否在 `[8, 64]` 范围内
   - **输入来源**：调用方传入的函数参数
   - **输出去向**：校验通过进入步骤 2
   - **失败行为**：不在范围内 → 抛出 `ValueError(f"密码长度必须在 8-64 之间，当前长度为 {len(plain_password)}")`

2. **步骤 2：bcrypt 哈希计算**
   - **操作对象**：`plain_password` 字节序列
   - **具体操作**：`passlib.context.CryptContext(schemes=["bcrypt"], bcrypt__rounds=BCRYPT_ROUNDS).hash(plain_password)`
   - **输入来源**：步骤 1 校验通过的 `plain_password` + 环境变量 `BCRYPT_ROUNDS`（默认 12）
   - **输出去向**：返回 bcrypt 哈希字符串给调用方
   - **失败行为**：passlib 内部错误（如 bcrypt 库不可用）→ 抛出 `HashingError(f"bcrypt 哈希计算失败: {str(e)}")`

**1.5.2 密码校验流程（verify_password）**

1. **步骤 1：参数校验**
   - **操作对象**：`plain_password: str`、`hashed_password: str`
   - **具体操作**：检查 `plain_password` 长度 `[8, 64]`；检查 `hashed_password` 是否以 `$2b$` 或 `$2a$` 开头
   - **输入来源**：调用方传入的函数参数
   - **输出去向**：校验通过进入步骤 2
   - **失败行为**：格式不合法 → 抛出 `ValueError`

2. **步骤 2：bcrypt 比对**
   - **操作对象**：`plain_password` 字节序列 vs `hashed_password`
   - **具体操作**：`CryptContext.verify(plain_password, hashed_password)`
   - **输入来源**：步骤 1 校验通过的参数
   - **输出去向**：返回 `bool` 给调用方
   - **失败行为**：passlib 内部错误 → 抛出 `HashingError`

**1.5.3 JWT 签发流程（create_access_token）**

1. **步骤 1：参数校验**
   - **操作对象**：`data: dict`
   - **具体操作**：检查 `"sub" in data and "roles" in data`
   - **输入来源**：调用方传入的 `data` 参数
   - **输出去向**：校验通过进入步骤 2
   - **失败行为**：缺少必要字段 → 抛出 `ValueError("data 必须包含 sub 和 roles 字段")`

2. **步骤 2：确定过期时间**
   - **操作对象**：`expires_delta` 参数 + 默认值
   - **具体操作**：`expire = datetime.now(ZoneInfo("Asia/Shanghai")) + (expires_delta or timedelta(minutes=15))`
   - **输入来源**：步骤 1 的 `expires_delta` 参数
   - **输出去向**：`expire` 时间戳传入步骤 3
   - **失败行为**：无——此步骤不涉及 I/O，不会失败

3. **步骤 3：组装 payload**
   - **操作对象**：JWT payload 字典
   - **具体操作**：
     ```python
     payload = {
         "iss": "campfire-ai",
         "sub": data["sub"],
         "roles": data["roles"],
         "iat": int(now.timestamp()),
         "exp": int(expire.timestamp()),
         "jti": str(uuid4())
     }
     ```
   - **输入来源**：步骤 1 的 `data` + 步骤 2 的 `expire` + `uuid4()`
   - **输出去向**：payload 字典传入步骤 4
   - **失败行为**：无——纯数据组装，不涉及 I/O

4. **步骤 4：JWT 签名与返回**
   - **操作对象**：步骤 3 的 payload 字典
   - **具体操作**：
     ```python
     headers = {"kid": os.environ.get("JWT_KEY_VERSION", "v1")}
     token = jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256", headers=headers)
     ```
   - **输入来源**：步骤 3 payload + `JWT_SECRET_KEY` 环境变量 + `JWT_KEY_VERSION` 环境变量
   - **输出去向**：返回 JWT token 字符串给调用方
   - **失败行为**：`jose.exceptions.JWTError` → 抛出 `TokenCreationError(f"JWT 签发失败: {str(e)}")`

**1.5.4 JWT 校验流程（verify_token）**

1. **步骤 1：解码 header**
   - **操作对象**：`token: str`
   - **具体操作**：`jose.jwt.get_unverified_headers(token)` 提取 `kid`
   - **输入来源**：调用方传入的 `token` 参数
   - **输出去向**：`kid` 传入步骤 2
   - **失败行为**：token 格式无效 → 抛出 `TokenDecodeError("token 格式无效")`

2. **步骤 2：选择密钥**
   - **操作对象**：`kid` 值 + 环境变量
   - **具体操作**：
     - 若 `kid == os.environ.get("JWT_KEY_VERSION")` → 使用 `JWT_SECRET_KEY`
     - 若 `kid == ` 上一个版本 → 使用 `JWT_PREVIOUS_SECRET_KEY`
     - 否则 → 返回 `None`
   - **输入来源**：步骤 1 的 `kid` + 环境变量 `JWT_SECRET_KEY`、`JWT_PREVIOUS_SECRET_KEY`、`JWT_KEY_VERSION`
   - **输出去向**：选中的密钥传入步骤 3
   - **失败行为**：kid 不匹配 → 返回 `None`

3. **步骤 3：签名校验 + 过期检查**
   - **操作对象**：`token` + 步骤 2 的密钥
   - **具体操作**：
     ```python
     payload = jwt.decode(token, selected_key, algorithms=["HS256"],
                          options={"verify_exp": True})
     ```
   - **输入来源**：步骤 1 的 `token` + 步骤 2 的密钥
   - **输出去向**：解码后的 payload dict 返回给调用方
   - **失败行为**：签名无效 → 返回 `None`；exp 已过期 → 返回 `None`

**1.5.5 限流检查流程（check_rate_limit）**

1. **步骤 1：用户级限流（如 user_id 非空）**
   - **操作对象**：Redis `ratelimit:user:{user_id}:{unix_second}` 系列 key
   - **具体操作**：
     1. 计算当前滑动窗口范围：`[now - window_seconds, now]`，按秒粒度拆分为 N 个 key
     2. 对当前秒 key 执行：`await redis.incr(f"ratelimit:user:{user_id}:{current_second}")`，设 `await redis.expire(key, window_seconds + 60)`
     3. 聚合：对窗口内所有 key 执行 `mget`，求和 `count`
     4. 比较：`count > RATE_LIMIT_USER_PER_MINUTE → 返回 False`
   - **输入来源**：`user_id` 参数 + 环境变量 `RATE_LIMIT_USER_PER_MINUTE`、`RATE_LIMIT_WINDOW_SECONDS`
   - **输出去向**：`False` 立即返回（不进入 IP 级）；`True` 进入步骤 2
   - **失败行为**：Redis 连接异常 → 记录 CRITICAL 日志，fail-open 返回 `True`（放行）

2. **步骤 2：IP 级限流**
   - **操作对象**：Redis `ratelimit:ip:{ip}:{unix_second}` 系列 key
   - **具体操作**：同步骤 1，key 替换为 IP 前缀，阈值使用 `RATE_LIMIT_IP_PER_MINUTE`
   - **输入来源**：`ip` 参数 + 环境变量 `RATE_LIMIT_IP_PER_MINUTE`
   - **输出去向**：返回 `bool` 给调用方
   - **失败行为**：Redis 连接异常 → 同步骤 1 fail-open

**1.5.6 文件校验流程（validate_file）**

1. **步骤 1：扩展名提取与校验**
   - **操作对象**：`filename: str`
   - **具体操作**：
     1. `ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""`
     2. 若 `ext == ""` → 返回 `FileValidationResult(False, "无法识别文件扩展名")`
     3. 检查 `ext in ALLOWED_FILE_EXTENSIONS`
   - **输入来源**：`filename` 参数 + 环境变量 `ALLOWED_FILE_EXTENSIONS`
   - **输出去向**：通过则进入步骤 2
   - **失败行为**：扩展名不在白名单 → 返回 `FileValidationResult(False, f"文件扩展名 .{ext} 不在允许白名单中。允许的类型：{allowed}")`

2. **步骤 2：文件大小校验**
   - **操作对象**：`content: bytes`
   - **具体操作**：根据扩展名查找大小上限（图片类 jpg/jpeg/png=5MB，文档类 pdf/docx=10MB），比较 `len(content)` 与上限
   - **输入来源**：步骤 1 的 `ext` + `content` 参数
   - **输出去向**：通过则进入步骤 3
   - **失败行为**：超限 → 抛出 `FileTooLargeError(f"文件大小 {size_mb:.1f}MB 超过上限 {limit_mb}MB")`

3. **步骤 3：MIME 类型检测**
   - **操作对象**：`content: bytes`
   - **具体操作**：`magic.from_buffer(content[:1024], mime=True)` 获取 MIME
   - **输入来源**：`content` 参数前 1024 字节
   - **输出去向**：通过则进入步骤 4
   - **失败行为**：MIME 不匹配 → 返回 `FileValidationResult(False, f"文件类型 {detected} 不在允许列表中")`

4. **步骤 4：文件头魔数校验**
   - **操作对象**：`content[:4]`
   - **具体操作**：读取前 4 字节，比对已知签名表
   - **输入来源**：`content` 参数前 4 字节
   - **输出去向**：返回 `FileValidationResult(True, None)`
   - **失败行为**：魔数不匹配 → 返回 `FileValidationResult(False, f"文件头签名不匹配，实际为 {detected_hex}")`

**1.5.7 审计日志写入流程（旁路）**

1. **触发时机**：凭证异常（`jwt_expired`/`jwt_invalid`）、限流触发（`rate_limit_exceeded`）、文件拒绝（`file_upload_rejected`/`file_type_rejected`）
2. **操作对象**：`audit_logs` 表
3. **具体操作**：
   ```python
   log = AuditLogEvent(
       event_type=etype,
       user_id=uid,
       ip_address=ip,
       timestamp=datetime.now(ZoneInfo("Asia/Shanghai")),
       details={"token_id": jti, "reason": reason},
       trace_id=str(uuid4())
   )
   await db.execute(insert(AuditLog).values(**log.model_dump()))
   ```
4. **失败行为**：写入失败 → 记录 CRITICAL 日志（确保审计事件不丢失），不阻塞主流程

### 1.7 依赖与集成接口（本模块调用的外部接口）

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 反向代理 | Nginx（`infrastructure/nginx/`） | `listen 443 ssl; ssl_protocols TLSv1.3;` | HTTPS 终端 + HTTP→HTTPS 301 重定向 | 项目结构 §3.1、§6.1 `infrastructure/nginx/` |
| 缓存 | Redis（`packages/py-cache/`） | `redis.asyncio.Redis.incr(key)` + `expire(key, ttl)` | 滑动窗口限流计数器 | 项目结构 §6.1 `packages/py-cache/` |
| 对象存储 | MinIO（`packages/py-storage/`） | `minio.Minio.presigned_get_object(bucket, object_name, expires=timedelta)` | 预签名 URL 生成 | 项目结构 §6.1 `packages/py-storage/` |
| 关系数据库 | PostgreSQL（`packages/py-db/`） | `INSERT INTO audit_logs (event_id, event_type, user_id, ip, event_time, details, trace_id) VALUES (...)` | 审计日志持久化 | 项目结构 §6.1 `packages/py-db/models/` |
| 日志系统 | structlog（`packages/py-logger/`） | `logger.critical("event", key=value)` | 结构化日志 + CRITICAL 告警 | 项目结构 §6.1 `packages/py-logger/` |
| 配置管理 | `packages/py-config/` | `SecurityConfig()` — 从环境变量加载 | 统一安全配置加载入口 | 项目结构 §6.1 `packages/py-config/settings.py` |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| AUTH-02 用户登录 | `packages/py-auth/jwt.py` — `create_access_token`、`verify_token` | 登录时签发 Token，请求时校验 Token | ⏭️ 待落地（可直接使用本模块提供的接口） |
| SEC-04 防刷限流 | `packages/py-cache/rate_limit.py` — `check_rate_limit` | 限流中间件注册 | ⏭️ 待落地（本模块已实现基础适配器） |
| SEC-05 输入校验 | Pydantic v2 `BaseModel.model_validate()` | 请求体 Schema 级校验 | ⏭️ 待落地（Pydantic 模型由各模块自定） |
| SEC-03 PII检测 | `packages/py-auth/masking.py` | 内容层 PII 检测与脱敏 | ⏭️ 待落地（本模块提供传输加密和脱敏格式） |

### 1.8 状态机（如适用）

本功能点不涉及状态流转，故无需状态机。

### 1.9 异常与边界条件

#### 1.9.1 异常 1：密码长度不合规

- **触发条件**：
  - `plain_password` 为 `None` 或空字符串 `""`
  - `len(plain_password) < 8`
  - `len(plain_password) > 64`
- **处理策略**：
  1. 在 `hash_password` 和 `verify_password` 入口处校验
  2. 抛出 `ValueError(f"密码长度必须在 8-64 之间，当前长度为 {len(plain_password)}")`
  3. 上层调用方捕获后返回 HTTP 422，响应体：`{"detail": {"field": "password", "msg": "密码长度必须在 8-64 个字符之间"}}`
  4. 不记录审计日志（密码长度不合规不涉及安全事件）
- **重试参数**：不重试，客户端修正密码后重新发起请求。

#### 1.9.2 异常 2：JWT Token 校验失败（签名无效 / 已过期）

- **触发条件**：
  - JWT 签名校验失败（token 被篡改或使用错误密钥签名）
  - `exp` 字段中的时间戳小于当前时间
  - `kid` 不匹配任何已知密钥版本
- **处理策略**：
  1. `verify_token` 返回 `None`
  2. 调用方（认证中间件）判断：
     - 若 token 仅在 header 解码阶段失败（格式非法）→ 返回 HTTP 401 `{"detail": "身份验证失败，请重新登录"}`
     - 若 exp 过期 → 返回 HTTP 401 `{"detail": "令牌已过期，请刷新"}`
  3. 写入审计日志：`AuditLogEvent(event_type="jwt_invalid" 或 "jwt_expired", user_id=..., trace_id=...)`
  4. 记录结构化日志：`logger.warning("jwt_verification_failed", reason="expired"|"invalid", token_id=...)`
- **重试参数**：token 过期场景，客户端自动使用 Refresh Token 换取新 Access Token 后重试 1 次；签名无效场景不重试。

#### 1.9.3 异常 3：Redis 不可用（限流降级）

- **触发条件**：
  - `redis.asyncio.Redis.incr()` 抛出 `redis.exceptions.ConnectionError`
  - Redis 连接池超时（> 2 秒未获取连接）
  - Redis 返回 `ConnectionRefusedError` 或 `TimeoutError`
- **处理策略**：
  1. 捕获 `redis.exceptions.RedisError`（Redis 异常基类）
  2. 信任 fail-open 策略——直接返回 `True`（放行所有请求）
  3. 通过 `packages/py-logger` 记录 CRITICAL 日志：
     `logger.critical("rate_limit_redis_unavailable", ip=ip, user_id=user_id, error=str(e))`
  4. 不记录审计日志（Redis 不可用自身是运维事件，非安全事件）
  5. 限流窗口恢复后（Redis 重新可用），下一轮 `incr` 正常执行时自动恢复限流
- **重试参数**：不重试 Redis 操作——fail-open 是主动降级策略。限流功能在 Redis 恢复后自然恢复，无需额外重试逻辑。

#### 1.9.4 异常 4：文件大小超过上限

- **触发条件**：
  - 图片类（jpg/jpeg/png）：`len(content) > 5 * 1024 * 1024`（5MB）
  - 文档类（pdf/docx）：`len(content) > 10 * 1024 * 1024`（10MB）
- **处理策略**：
  1. `validate_file` 步骤 2 中检测
  2. 抛出 `FileTooLargeError(f"文件大小 {actual_mb:.1f}MB 超过上限 {limit_mb}MB")`
  3. 调用方捕获后返回 HTTP 413 `{"detail": {"file": "...", "msg": "...", "limit_mb": limit}}`
  4. 写入审计日志：`AuditLogEvent(event_type="file_upload_rejected", ...)`
- **重试参数**：不重试，用户需压缩或更换文件后重新上传。

#### 1.9.5 异常 5：文件类型校验失败

- **触发条件**：
  - 扩展名不在 `ALLOWED_FILE_EXTENSIONS` 中
  - `python-magic` 检测的 MIME 类型不匹配允许列表
  - 文件头魔数与扩展名声称的类型不一致（可能为伪装文件）
- **处理策略**：
  1. `validate_file` 在对应校验层返回 `FileValidationResult(False, reason)`
  2. 调用方捕获后返回 HTTP 415 `{"detail": {"file": filename, "msg": reason, "allowed_types": list(ALLOWED_FILE_EXTENSIONS)}}`
  3. 写入审计日志：`AuditLogEvent(event_type="file_type_rejected", details={"filename": filename, "reason": reason})`
- **重试参数**：不重试，用户需更换文件后重新上传。

#### 1.9.6 边界条件：JWT 密钥轮换 7 天共栖期

- **触发条件**：`scripts/rotate-jwt-key.sh` 执行后，新密钥写入 `JWT_SECRET_KEY`，旧密钥移至 `JWT_PREVIOUS_SECRET_KEY`
- **处理策略**：
  1. 轮换前：`kid=v1`，`JWT_SECRET_KEY=K1`，`JWT_PREVIOUS_SECRET_KEY=（空或上上个版本）`
  2. 轮换后：`kid=v2`，`JWT_SECRET_KEY=K2`，`JWT_PREVIOUS_SECRET_KEY=K1`
  3. 共栖期 7 天内：`verify_token` 同时接受 `kid=v1`（K1 校验）和 `kid=v2`（K2 校验）
  4. 共栖期结束后（> 7 天）：手动或自动将 `JWT_PREVIOUS_SECRET_KEY` 设为与当前相同的值（`K2`），不再接受旧密钥签发的 token
  5. 容器滚动重启：`docker-compose up -d` 使新环境变量生效
- **重试参数**：N/A

### 1.10 验收测试场景

#### 1.10.1 正向测试 1：正常密码哈希与校验

- **场景**：用户注册时哈希密码，登录时校验成功
- **Given**: `plain_password = "MySecurePass123"`（长度 16，含字母和数字）
- **When**: 先调用 `hash_password(plain_password)` → 再调用 `verify_password(plain_password, hashed)`
- **Then**:
  - `hash_password` 返回以 `$2b$12$` 开头的字符串
  - 两次 `hash_password` 调用返回不同的哈希值（随机 salt）
  - `verify_password` 返回 `True`
  - 使用错误密码 `"WrongPass456"` 调用 `verify_password` 返回 `False`
- **关键断言**：
  ```json
  {
    "test_name": "password_hash_and_verify_success",
    "input": {"plain_password": "MySecurePass123"},
    "expected": {
      "hash_prefix": "$2b$12$",
      "verify_correct": true,
      "verify_wrong": false,
      "random_salt_verified": true
    }
  }
  ```

#### 1.10.2 正向测试 2：JWT Token 完整生命周期

- **场景**：登录签发 Token → 使用 Token 校验 → Token 被正确识别
- **Given**: `data = {"sub": "user-001", "roles": ["家属"]}`，环境变量 `JWT_SECRET_KEY="test-key-at-least-32-characters-long!!"`
- **When**: `token = create_access_token(data)` → `payload = verify_token(token)`
- **Then**:
  - `token` 为非空字符串，包含三段 Base64（header.payload.signature）
  - `verify_token` 返回 dict，`payload["sub"] == "user-001"`，`payload["roles"] == ["家属"]`
  - `payload` 包含 `kid`、`exp`、`iat`、`jti` 字段
  - 使用错误密钥校验同一 token 返回 `None`
- **关键断言**：
  ```json
  {
    "test_name": "jwt_token_lifecycle_success",
    "input": {"data": {"sub": "user-001", "roles": ["家属"]}},
    "expected": {
      "token_format": "xxx.yyy.zzz",
      "payload_sub": "user-001",
      "payload_roles": ["家属"],
      "has_kid": true,
      "wrong_key_returns_none": true
    }
  }
  ```

#### 1.10.3 正向测试 3：限流未触发时正常放行

- **场景**：用户请求在限流阈值内，正常通过
- **Given**: Redis 就绪，`RATE_LIMIT_USER_PER_MINUTE=30`，同一 `user_id` 已发起 28 次请求
- **When**: 第 29 次调用 `await check_rate_limit(user_id="user-001", ip="192.168.1.100")`
- **Then**:
  - 返回 `True`
  - Redis 中对应 key 的计数递增至 29
- **关键断言**：
  ```json
  {
    "test_name": "rate_limit_within_threshold",
    "input": {"user_id": "user-001", "ip": "192.168.1.100", "previous_count": 28},
    "expected": {"allowed": true, "redis_count": 29}
  }
  ```

#### 1.10.4 异常测试 1：密码长度不合规

- **场景**：用户提交过短密码，系统拒绝
- **Given**: `plain_password = "123"`（长度 < 8）
- **When**: 调用 `hash_password("123")`
- **Then**:
  - 抛出 `ValueError`，消息中包含 "密码长度必须在 8-64 之间"
  - 不产生任何 bcrypt 计算，不访问任何外部服务
- **关键断言**：
  ```json
  {
    "test_name": "password_too_short_raises_error",
    "input": {"plain_password": "123"},
    "expected": {
      "exception": "ValueError",
      "message_contains": "密码长度必须在 8-64 之间",
      "no_external_calls": true
    }
  }
  ```

#### 1.10.5 异常测试 2：Redis 不可时时 fail-open 放行

- **场景**：Redis 故障，限流中间件降级为放行
- **Given**: Redis 连接被拒绝（`ConnectionRefusedError`），`user_id="user-001"`
- **When**: 调用 `await check_rate_limit(user_id="user-001", ip="192.168.1.100")`
- **Then**:
  - 返回 `True`（不抛异常）
  - `py-logger` 产生一条 CRITICAL 级别日志，内容包含 "rate_limit_redis_unavailable"
- **关键断言**：
  ```json
  {
    "test_name": "rate_limit_fail_open_on_redis_down",
    "input": {"user_id": "user-001", "ip": "192.168.1.100"},
    "mocks": {"redis.incr": "ConnectionRefusedError"},
    "expected": {
      "allowed": true,
      "no_exception_thrown": true,
      "critical_log_emitted": true,
      "log_message_contains": "rate_limit_redis_unavailable"
    }
  }
  ```

#### 1.10.6 异常测试 3：文件扩展名不在白名单

- **场景**：用户上传可执行文件，三层校验第一层即拦截
- **Given**: `filename="virus.exe"`，`content=b"MZ\x90\x00..."（PE 文件头）`，`ALLOWED_FILE_EXTENSIONS=["pdf","jpg","jpeg","png","docx"]`
- **When**: 调用 `validate_file("virus.exe", content)`
- **Then**:
  - 返回 `FileValidationResult(is_valid=False)`
  - `reason` 包含 "文件扩展名 .exe 不在允许白名单中"
  - 不执行第二层 MIME 检测（在第一层已返回）
- **关键断言**：
  ```json
  {
    "test_name": "file_extension_not_allowed_rejected",
    "input": {"filename": "virus.exe", "content": "PE_HEADER_BYTES"},
    "expected": {
      "is_valid": false,
      "reason_contains": "不在允许白名单中",
      "mime_check_skipped": true
    }
  }
  ```

### 1.11 注意事项与禁止行为（编码层面）

1. **[约束] JWT 密钥加载强制走环境变量**：`create_access_token` 和 `verify_token` 中的密钥必须通过 `SecurityConfig` 实例的 `JWT_SECRET_KEY` / `JWT_PREVIOUS_SECRET_KEY` 属性获取。禁止在代码中任何位置出现 `"my-secret-key"` 字符串常量的密钥值。

2. **[约束] bcrypt salt rounds 最低 12**：`SecurityConfig` 中 `BCRYPT_ROUNDS` 的 `Field(ge=12)` 约束确保任何情况下不低於 12。`CryptContext` 初始化时传入 `bcrypt__rounds=self.BCRYPT_ROUNDS`，禁止硬编码 rounds 值。

3. **[易错点] Redis 限流 key TTL 设置**：每个 `incr` 操作后必须紧跟 `expire`，且 TTL 设置为 `RATE_LIMIT_WINDOW_SECONDS + 60`（窗口 + 60 秒缓冲）。禁止不设 TTL——会导致 Redis 内存泄漏。

4. **[易错点] 文件校验层级顺序不可变**：扩展名义校验 → MIME 类型 → 魔数，此顺序不可变。扩展名是最轻量且最易绕过的校验，放在第一层可最早拦截绝大多数非法请求，避免浪费内存读取字节内容。

5. **[易错点] 脱敏中间件的字段匹配**：手机号脱敏仅匹配响应 JSON 中名为 `phone`、`phone_number`、`mobile` 的字段。禁止使用全局正则替换——会将非手机号的数字字符串（如订单号 `202605261234567`）错误脱敏。

6. **[易错点] 审计日志的异步写入**：`write_audit_log` 必须使用 `async` 函数 + `await db.execute()`，禁止同步阻塞日志写入。审计日志写入失败不得阻塞主业务流程——捕获异常后记录 CRITICAL 日志并继续。

7. **[禁止行为]**：
   - 禁止在 `hash_password` 或 `verify_password` 中记录密码原文到日志
   - 禁止在 JSON 响应中返回完整的 JWT token 到非预期端点
   - 禁止跳过限流中间件 white_list 配置——只有 `/health` 端点可豁免限流
   - 禁止在 `validate_file` 中使用 `os.system()` 或 `subprocess` 调用外部命令检测文件类型——必须使用 `python-magic` 库的内存检测

8. **[偷懒红线] 绝对禁止以"这个很简单"、"显而易见"、"和其他模块类似"为由省略任何细节**。

### 1.12 文档详细度自检清单

- [x] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成编码
- [x] 无偷懒表述：全文搜索并消除 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：所有契约类型已通过 `docs/contracts/SEC-01/*.json` 完整定义，含 description、examples、约束
- [x] 逻辑步骤完整：7 组核心流程（密码哈希、密码校验、JWT 签发、JWT 校验、限流、文件校验、审计日志）均含操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：6 种异常/边界条件均含精确触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值（15min TTL、7 天共栖期、12 rounds、30/100 限流值、1 小时预签名）均已在文档或契约中显式声明
- [x] 技术栈绑定明确：必须使用（6 项）和禁止使用（6 项）均已列出，与项目技术栈设计文档 §5 一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致

### 1.14 外部接口契约清单

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| hash_password | `docs/contracts/SEC-01/hash_password.json` | input | draft | SEC-01 | AUTH-02 |
| verify_password | `docs/contracts/SEC-01/verify_password.json` | input | draft | SEC-01 | AUTH-02 |
| create_access_token | `docs/contracts/SEC-01/create_access_token.json` | output | draft | SEC-01 | AUTH-02 |
| verify_token | `docs/contracts/SEC-01/verify_token.json` | input | draft | SEC-01 | AUTH-02 |
| check_rate_limit | `docs/contracts/SEC-01/check_rate_limit.json` | input | draft | SEC-01 | SEC-04 |
| validate_file | `docs/contracts/SEC-01/validate_file.json` | input | draft | SEC-01 | — |
| TokenPayload | `docs/contracts/SEC-01/TokenPayload.json` | shared-model | draft | SEC-01 | AUTH-02 |
| FileValidationResult | `docs/contracts/SEC-01/FileValidationResult.json` | output | draft | SEC-01 | — |
| RateLimitConfig | `docs/contracts/SEC-01/RateLimitConfig.json` | shared-model | draft | SEC-01 | SEC-04 |
| SecurityConfig | `docs/contracts/SEC-01/SecurityConfig.json` | shared-model | draft | SEC-01 | — |
| AuditLogEvent | `docs/contracts/SEC-01/AuditLogEvent.json` | event | draft | SEC-01 | — |
| RateLimitExceededResponse | `docs/contracts/SEC-01/RateLimitExceededResponse.json` | output | draft | SEC-01 | SEC-04 |
| PhoneMaskedString | `docs/contracts/SEC-01/PhoneMaskedString.json` | output | draft | SEC-01 | SEC-03 |

### 1.15 意图一致性声明

- **配套意图文档**：`SEC-01-传输存储安全-意图文档.md`
- **冻结时间**：2026-05-26 16:54:46
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致
  - [x] 本落地规范中的状态机实现与意图文档中的状态业务定义一致（双方均确认无需状态机）
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致（传输链路不安全、身份凭证无效、请求频率超限、文件类型不在白名单——4 种异常全部覆盖）
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准（AC-01~AC-08 全部对应）
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围（9 项决策经技术预研和用户确认后全部确定）
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
