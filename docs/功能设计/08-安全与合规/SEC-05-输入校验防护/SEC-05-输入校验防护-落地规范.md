# 1 功能点：SEC-05 输入校验防护 — 落地规范

> **文档生成时间**：`2026-05-26 17:21:10`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-26 17:21:10` | AI Assistant | 初始版本（基于设计文档 v1.0 + 契约协调报告，8 个新类型，零冲突） |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `SEC-05-输入校验防护-设计文档.md`。

---

## 【对内实现】

### 1.1 技术栈绑定

- **必须使用**：
  - `pydantic>=2.0` —— 请求/响应 Schema 定义与校验引擎，通过 `BaseModel` 子类定义各接口校验规则，`Field()` 声明逐字段约束
  - `fastapi>=0.115` —— API 框架，通过 `Depends()` 声明式注入 Pydantic Schema 校验，自动处理 422 响应生成
  - `sqlalchemy>=2.0` —— 异步 ORM，通过 `AsyncSession` + Repository 模式执行参数化查询，禁止裸 `session.execute()`
  - `html`（Python 标准库）—— `html.escape(s, quote=True)` 执行 OWASP 五字符 HTML 实体转义
  - `packages/py-schemas/` —— 项目统一 DTO 契约目录，所有对外校验 Schema 的存放位置
  - `packages/py-db/repositories/` —— Repository 模式数据访问层，所有数据库操作必须通过此层的 Repository 类
  - `packages/py-logger/` —— 结构化 JSON 日志基础设施，安全审计日志通过独立 `logger_name="security_audit"` 输出
- **禁止使用**：
  - 禁止在 `apps/api-server/app/` 任何位置调用 `session.execute(text(...))`、`session.execute("SELECT ...")` 或字符串拼接 SQL
  - 禁止创建独立的 HTTP 中间件（Starlette `BaseHTTPMiddleware`）用于校验——校验必须通过 FastAPI `Depends()` 路由依赖注入实现
  - 禁止使用第三方 HTML 清洗库（如 `bleach`）替代标准库 `html.escape()`——避免引入额外依赖

### 1.2 文件归属

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 校验 Schema 定义 | `packages/py-schemas/src/security/validation_schemas.py` | 各接口的 Pydantic 请求校验 Schema，包含 `Field()` 约束声明 |
| 安全检测服务 | `packages/py-schemas/src/security/security_detector.py` | SQL 注入特征检测、XSS 载荷检测、请求格式异常检测逻辑 |
| 内容安全清洗 | `packages/py-schemas/src/security/sanitizer.py` | `sanitize_html()` 函数，HTML 实体转义封装 |
| 文件校验服务 | `packages/py-schemas/src/security/file_validator.py` | `validate_file()` 函数，文件类型白名单 + 大小校验 + 魔数检测 |
| 错误响应处理器 | `apps/api-server/app/middleware/validation_handler.py` | 自定义 FastAPI Exception Handler，覆盖默认 422 格式为 `ValidationErrorResponse` |
| Repository 基类 | `packages/py-db/src/repositories/base_repository.py` | Repository 基类，定义参数化查询的接口约束 |
| 测试文件 | `tests/packages/security/test_validation_schemas.py` | 校验 Schema 的单元测试 |
| 安全测试 | `tests/packages/security/test_security_detector.py` | SQL 注入/XSS 检测的单元测试 |
| 文件校验测试 | `tests/packages/security/test_file_validator.py` | 文件校验的单元测试 |
| 集成测试 | `tests/apps/api_server/test_validation_integration.py` | API 路由的校验集成测试 |

---

## 【已锁定】

### 1.3 输入定义

**ValidationInput**（函数参数签名字典，不做独立类型导出）
- `request_body: dict[str, Any] | None` —— API 请求体，字段结构由各接口 Pydantic Schema 定义。`None` 表示 GET 请求无请求体
- `query_params: dict[str, str]` —— URL 查询参数字典，keys 为参数名，values 为参数值字符串
- `path_params: dict[str, str]` —— URL 路径参数字典，keys 为路径变量名，values 为匹配的路径片段
- `file_upload: UploadFile | None` —— FastAPI `UploadFile` 对象，包含 `filename`、`content_type`、`file`（`SpooledTemporaryFile`）属性

**ValidationErrorItem**
- 【契约引用】`docs/contracts/SEC-05/ValidationErrorItem.json`
- 本模块作为该契约的定义方
- 消费方：待下游模块引用

**FileValidationRule**
- 【契约引用】`docs/contracts/SEC-05/FileValidationRule.json`
- 本模块作为该契约的定义方
- 消费方：CASE-02（案例附件上传）

### 1.4 输出定义

**ValidationErrorResponse**（HTTP 响应体）
- 【契约引用】`docs/contracts/SEC-05/ValidationErrorResponse.json`
- 本模块作为该契约的定义方
- 消费方：所有 API 模块（隐式依赖——校验失败时的标准错误响应格式）

**FileValidationResult**
- 【契约引用】`docs/contracts/SEC-05/FileValidationResult.json`
- 本模块作为该契约的定义方
- 消费方：CASE-02（案例附件上传）

**SecurityAuditLogEntry**（日志条目）
- 【契约引用】`docs/contracts/SEC-05/SecurityAuditLogEntry.json`
- 本模块作为该契约的定义方
- 消费方：OBS-01（结构化日志服务，作为日志接收方）

---

## 【对内实现】

### 1.5 核心逻辑步骤

1. **步骤 1：请求数据 Pydantic 校验**
   - **操作对象**：各接口的 Pydantic Schema 模型实例（如 `ConsultRequestSchema`、`ProfileRequestSchema`）
   - **具体操作**：FastAPI 路由参数的 `Annotated[T, Depends()]` 声明触发 Pydantic 自动校验，逐字段检查类型、必填、范围、格式约束
   - **输入来源**：HTTP 请求体（`application/json`）或查询参数/路径参数
   - **输出去向**：校验通过的强类型 Pydantic 实例进入步骤 2（路由处理函数）；校验失败触发 FastAPI 默认 `ValidationError`
   - **失败行为**：FastAPI 自动返回 HTTP 422，由自定义 Exception Handler（`apps/api-server/app/middleware/validation_handler.py`）拦截并重写为 `ValidationErrorResponse` 格式 `{"errors": [{"field": "...", "reason": "...", "constraint": "..."}]}`

2. **步骤 2：路由处理函数执行业务前安全检测**
   - **操作对象**：步骤 1 中 Pydantic 校验通过但尚未进入 Repository 的请求数据
   - **具体操作**：调用 `security_detector.detect_threats(validated_data)` 检测 SQL 注入特征（正则匹配 `UNION SELECT`、`DROP TABLE`、`1=1` 等模式）、XSS 载荷（正则匹配 `<script`、`onerror=`、`javascript:` 等模式）、请求格式异常（字段名含特殊字符、超出预期深度嵌套）
   - **输入来源**：步骤 1 校验通过的 Pydantic 实例
   - **输出去向**：检测通过 → 数据进入步骤 3（Repository 调用）；检测到威胁 → 拦截请求
   - **失败行为**：检测到威胁后：(a) 返回 HTTP 400，响应体为通用 `{"errors": [{"field": "_request", "reason": "invalid_content", "constraint": "数据包含不安全内容"}]}`，不透露检测到的具体特征；(b) 调用 `py-logger` 写入安全审计日志（`logger_name="security_audit"`），记录 `trace_id`、`event_type`（sql_injection/xss_payload/malformed_request）、`detection_detail`（不包含用户原始输入全文）；(c) 不进入后续步骤

3. **步骤 3：Repository 参数化查询执行**
   - **操作对象**：SQLAlchemy ORM 模型实例
   - **具体操作**：通过 Repository 类的方法（如 `UserRepository.create(data)`）执行 ORM 操作，SQLAlchemy 自动将用户输入值通过 DBAPI 的 `bindparam()` 参数绑定传递至 PostgreSQL，从根本上杜绝字符串拼接
   - **输入来源**：步骤 2 安全检测通过的数据，映射为 ORM 模型属性值
   - **输出去向**：数据库操作结果返回给 Service 层
   - **失败行为**：数据库连接失败 → 抛出 `DependencyCommunicationError`，重试 3 次（固定间隔 2s，每次重试前从连接池获取新连接）

4. **步骤 4：响应内容安全清洗**
   - **操作对象**：API 响应体中包含用户提交文本内容的字段
   - **具体操作**：在构造 API 响应 Pydantic 模型实例前，对 `content` 类型的字符串字段调用 `sanitizer.sanitize_html(text)`，执行 `html.escape(s, quote=True)` 转义
   - **输入来源**：步骤 3 从数据库读取的包含用户文本的数据
   - **输出去向**：清洗后的纯文本赋值到响应模型的对应字段，返回给调用方
   - **失败行为**：`html.escape()` 为标准库纯函数，不会失败（不接受非字符串输入——若传入非字符串类型，在 Pydantic 响应模型校验阶段即会被拦截）

5. **步骤 5（条件触发）：文件上传校验**
   - **操作对象**：FastAPI `UploadFile` 实例
   - **具体操作**：调用 `validate_file(file: UploadFile, rules: FileValidationRule) -> FileValidationResult`：(a) 读取文件头前 256 字节检测魔数（magic bytes）确定真实 MIME 类型；(b) 比对 `rules.allowed_mime_types` 列表；(c) 比对 `rules.allowed_extensions` 列表（从 `file.filename` 提取扩展名）；(d) 检查 `file.size` 是否超过 `rules.max_size_bytes`
   - **输入来源**：路由处理函数中的 `UploadFile` 参数 + 预配置的 `FileValidationRule`
   - **输出去向**：`FileValidationResult` 返回调用方，`is_valid=True` 时文件数据传递给 CASE-02 存储逻辑
   - **失败行为**：文件类型或大小不满足约束 → 返回 `FileValidationResult(is_valid=False, error_message="...允许的类型：pdf, jpg, ...", detected_mime_type=...)`，文件不进入存储系统。MIME 检测失败（无法识别魔数）→ 视为不安全，`is_valid=False`，`detected_mime_type="application/octet-stream"`

### 1.6 接口契约（对外暴露的公共接口）

#### 1.6.1 接口 1：sanitize_html —— 内容安全清洗

```python
def sanitize_html(
    text: str,
) -> str:
    """
    对用户提交的文本内容执行 HTML 实体转义，返回安全的纯文本。

    转义字符集（OWASP XSS Prevention Cheat Sheet Rule #1）：
      & → &amp;
      < → &lt;
      > → &gt;
      " → &quot;
      ' → &#x27;

    Args:
        text: 待清洗的原始文本，可能包含 HTML 标签或脚本片段

    Returns:
        str: 经过 html.escape() 转义后的纯文本，可安全嵌入 HTML 页面展示

    Raises:
        TypeError: 如果 text 不是字符串类型（调用方必须在传入前通过 Pydantic 校验确保类型正确）

    Side Effects:
        无。本函数为纯函数，不访问外部资源。

    Thread Safety:
        本函数内部不维护可变状态，线程安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `sanitize_html` —— 语义化，描述"清洗 HTML"的安全操作 |
| **输入类型** | `text: str` —— 待清洗的原始文本 |
| **输出类型** | `str` —— 转义后的纯文本 |
| **异常类型** | `TypeError` —— 非字符串输入（调用方前置校验保障） |
| **副作用** | 无 |
| **幂等性** | 是。对同一文本多次调用返回相同结果。`sanitize_html(sanitize_html(x)) == sanitize_html(x)` |
| **并发安全** | 线程安全，无共享可变状态 |

#### 1.6.2 接口 2：validate_file —— 文件上传安全校验

```python
async def validate_file(
    file: UploadFile,
    rules: FileValidationRule,
) -> FileValidationResult:
    """
    对用户上传的文件执行类型白名单和大小上限双重校验。

    校验流程：
      1. 检查 file.size 是否超过 rules.max_size_bytes
      2. 读取文件头 256 字节检测魔数（magic bytes）确定真实 MIME 类型
      3. 比对真实 MIME 类型是否在 rules.allowed_mime_types 白名单中
      4. 比对文件扩展名（从 file.filename 提取）是否在 rules.allowed_extensions 白名单中
      5. MIME 类型和扩展名均匹配 → is_valid=True，否则 is_valid=False

    Args:
        file: FastAPI UploadFile 对象，包含 filename, content_type, size, file (SpooledTemporaryFile)
        rules: 文件校验规则配置，包含 MIME 白名单、扩展名白名单、大小上限

    Returns:
        FileValidationResult: 校验结果，包含 is_valid, error_message, detected_mime_type, file_size_bytes

    Raises:
        IOError: 文件读取失败（魔数检测阶段文件不可读）
        DependencyCommunicationError: 文件对象已关闭（重复读取）

    Side Effects:
        - 读取文件的文件头字节（前 256 字节），Seek 回原位后不影响后续读取
        - 不修改文件内容

    Thread Safety:
        本函数读取 file 对象的共享状态（Seek 位置），不同时对同一 UploadFile 并发调用即为安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `validate_file` —— 语义化，描述"校验文件"的安全操作 |
| **输入类型** | `file: UploadFile`、`rules: FileValidationRule` |
| **输出类型** | `FileValidationResult`（【契约引用】`docs/contracts/SEC-05/FileValidationResult.json`） |
| **异常类型** | `IOError`、`DependencyCommunicationError`（详见 §1.9） |
| **副作用** | 读取文件头字节后 Seek 回原位 |
| **幂等性** | 是。对同一文件同一规则多次调用返回相同结果 |
| **并发安全** | 对同一 UploadFile 对象串行调用安全；并发调用需外部同步 |

#### 1.6.3 接口 3：detect_security_threat —— 安全威胁检测

```python
def detect_security_threat(
    validated_data: dict[str, object],
) -> SecurityDetectionType | None:
    """
    对 Pydantic 校验通过的数据执行 SQL 注入/XSS 载荷特征检测。

    检测规则（不区分大小写）：
      - sql_injection: 正则匹配 UNION SELECT、DROP TABLE、ALTER TABLE、INSERT INTO、
        DELETE FROM、1=1、OR '1'='1'、--（注释注入）、;（语句终止）
      - xss_payload: 正则匹配 <script、javascript:、onerror=、onload=、onclick=、
        <iframe、<img.*src=javascript、eval\(、document\.cookie
      - malformed_request: 字段名含非字母数字下划线字符、嵌套深度超过 5 层

    Args:
        validated_data: Pydantic 校验通过后的字典数据

    Returns:
        SecurityDetectionType | None: 检测到的威胁类型，无威胁时返回 None

    Side Effects:
        无。本函数为纯函数，不记录日志（日志由调用方在检测到威胁后写入）。

    Thread Safety:
        本函数内部不维护可变状态，线程安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `detect_security_threat` —— 语义化，描述"检测安全威胁"的操作 |
| **输入类型** | `validated_data: dict[str, object]` —— Pydantic 校验通过后的字典 |
| **输出类型** | `SecurityDetectionType | None`（【契约引用】`docs/contracts/SEC-05/SecurityDetectionType.json`） |
| **异常类型** | 无异常抛出（函数内 try/except 捕获所有异常，异常时返回 None 放行） |
| **副作用** | 无 |
| **幂等性** | 是 |
| **并发安全** | 线程安全 |

---

## 【已锁定】

### 1.7 依赖与集成接口

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| Web 框架 | FastAPI | `Depends()` 依赖注入 + `Annotated[T, Depends()]` 路由参数声明 | 自动触发 Pydantic Schema 校验并生成 422 响应 | 项目结构 §5.2（L1-sub 接口层） |
| 数据校验 | Pydantic v2 | `BaseModel.model_validate()` + `Field()` 约束声明 | 声明式校验规则定义，自动拦截不合法请求 | 技术栈 §2（数据校验列） |
| 数据库 ORM | SQLAlchemy 2.0 async | `AsyncSession` + `Repository.create()` / `Repository.find()` 等 | 参数化查询，DBAPI `bindparam()` 自动绑定 | 技术栈 §2；项目结构 §6.1 `packages/py-db/` |
| 日志系统 | `packages/py-logger` | `logger.bind(trace_id=...).info("security_event", ...)` 结构化日志写入 | 安全审计日志输出，`logger_name="security_audit"` 独立实例 | 技术栈 §6.3；项目结构 §6.1 |
| 反向代理 | Nginx | `client_max_body_size` 配置（协同） | 请求体大小在校验前由 Nginx 层拦截超大请求 | 技术栈 §6.2（Nginx 代理） |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| AUTH-04（五级 RBAC 鉴权） | `Depends(get_current_user) -> UserContext` —— 解析 JWT payload，注入 `request.state.user` | 校验依赖认证上下文进行 trace_id 关联；认证在 Depends 链中位于校验之前 | 未开始 |
| OBS-01（结构化日志） | `packages/py-logger` 的 Logger 实例（共享基础设施） | 安全审计日志通过 `py-logger` 输出 | 未开始 |
| 所有 API 模块 | 隐式依赖——校验通过后路由处理函数收到的参数已是类型安全的 Pydantic 实例 | 各 API 路由无需自行编写校验逻辑 | 未开始 |
| CASE-02（案例附件上传） | 调用 `validate_file()` 校验附件安全性后传递 `UploadFile` 给 CASE-02 存储逻辑 | 文件类型白名单和大小的前置校验 | 未开始 |

---

## 【对内实现】

### 1.8 状态机

本功能点不涉及状态流转，故无需状态机。输入校验是同步的无状态操作——输入数据进入，校验后放行或拒绝，不维护业务状态。

### 1.9 异常与边界条件

#### 1.9.1 异常 1：Pydantic 校验失败（请求数据格式/完整性不合规）

- **触发条件**：
  - 必填字段缺失（如 `ConsultRequestSchema.behavior_description` 为 `None` 或请求体中不存在）
  - 字段类型不匹配（如 `age` 字段期望 `int`，实际传入字符串 `"seven"`）
  - 字段值越界（如 `age` 字段 `Field(ge=0, le=150)`，实际传入 `-3` 或 `200`）
  - 字符串超长（如 `Field(max_length=500)`，实际传入 600 字符）
  - 枚举值不在允许列表中（如 `status` 期望 `open/closed`，实际传入 `deleted`）
- **处理策略**：
  1. FastAPI 内部调用 `BaseModel.model_validate()` 触发 `ValidationError`
  2. 自定义 Exception Handler（`apps/api-server/app/middleware/validation_handler.py`）注册为 `@app.exception_handler(RequestValidationError)`
  3. Handler 中遍历 `ValidationError.errors()`，将每个错误映射为 `ValidationErrorItem {field, reason, constraint}`：
     - `field` → 提取 `err["loc"][-1]`（最末级字段名）
     - `reason` → 映射 Pydantic 错误类型：`missing` → `"field_required"`、`string_type` → `"expected_string"`、`int_parsing` → `"expected_integer"`、`less_than_equal` / `greater_than_equal` → `"value_out_of_range"`
     - `constraint` → 从 `err["ctx"]` 提取约束值（如 `{"ge": 0}` → `"value >= 0"`）
  4. 构建 `ValidationErrorResponse(errors=[{"field": ..., "reason": ..., "constraint": ...}, ...])`
  5. 返回 HTTP 422，`Content-Type: application/json`
  6. 不记录安全审计日志（格式校验失败属于正常输入错误，非安全事件）
- **重试参数**：不重试。客户端修正输入后重新发起请求。

#### 1.9.2 异常 2：安全威胁检测命中（SQL 注入 / XSS 载荷 / 格式异常）

- **触发条件**：
  - SQL 注入特征：请求数据中包含大小写不敏感的 `UNION SELECT`、`DROP TABLE`、`ALTER TABLE`、`INSERT INTO`、`DELETE FROM`、`OR '1'='1'`、`1=1`、SQL 注释符 `--`、语句终止符 `;`（在非预期的位置）
  - XSS 载荷：请求数据中包含 `<script`、`javascript:`、`onerror=`、`onload=`、`onclick=`、`<iframe`、包含 `src=javascript` 的 `<img` 标签、`eval(`、`document.cookie`
  - 格式异常：字段名含字符 `<>"';&|`、JSON 嵌套深度超过 5 层
- **处理策略**：
  1. `detect_security_threat()` 返回非 `None` 的 `SecurityDetectionType`
  2. 立即构造 HTTP 400 响应：`{"errors": [{"field": "_request", "reason": "invalid_content", "constraint": "数据包含不安全内容"}]}`（不暴露检测到的具体特征）
  3. 调用 `py-logger` 写入安全审计日志：
     ```python
     audit_logger = logger.bind(trace_id=request.state.trace_id)
     audit_logger.warning(
         "security_threat_detected",
         event_type=threat_type.value,  # "sql_injection" | "xss_payload" | "malformed_request"
         detection_detail=f"Threat type '{threat_type.value}' detected in request data",
         # 注意：不得包含用户原始输入全文
     )
     ```
  4. 不进入任何后续步骤（业务逻辑完全不执行）
- **重试参数**：不重试。由调用方（如有需要）修正后重新提交。

#### 1.9.3 异常 3：文件校验失败（类型 / 大小不满足安全约束）

- **触发条件**：
  - 文件真实 MIME 类型（通过魔数检测）不在 `rules.allowed_mime_types` 白名单中
  - 文件扩展名（从 `file.filename` 提取）不在 `rules.allowed_extensions` 白名单中
  - 文件大小 `file.size` 超过 `rules.max_size_bytes`
  - 文件头魔数检测失败（无法识别的二进制格式）→ 视为 `application/octet-stream`，不在白名单中
  - `file.file` 已经关闭或不可读
- **处理策略**：
  1. `validate_file()` 返回 `FileValidationResult(is_valid=False, error_message="...允许的类型：pdf, jpg, png, webp, mp4, doc, docx；最大大小：10MB", detected_mime_type="application/octet-stream", file_size_bytes=...)`
  2. 调用方（路由处理函数）检查 `is_valid`，若为 `False` → 返回 HTTP 400，响应体包含 `error_message`
  3. 记录日志（非安全审计——正常文件校验失败）：`logger.info("file_validation_failed", filename=..., reason=..., detected_type=..., file_size=...)`
  4. 文件数据不进入存储系统
- **重试参数**：不重试。由用户更换合规文件后重新上传。

#### 1.9.4 异常 4：数据库连接失败

- **触发条件**：
  - PostgreSQL 连接池返回 `sqlalchemy.exc.OperationalError`（如 `could not connect to server`）
  - 连接超时（超过数据库连接池 `pool_timeout=30s`）
  - 事务执行超时（超过 `statement_timeout=30000ms`）
- **处理策略**：
  1. Repository 层捕获 `OperationalError` / `TimeoutError`
  2. 关闭当前失效连接：`await session.close()`
  3. 从连接池获取新连接：`async with AsyncSessionFactory() as new_session`
  4. 重试操作（最大 3 次，固定间隔 2s）
  5. 第 3 次仍失败 → 抛出 `DependencyCommunicationError`（向上层传递到 FastAPI，返回 HTTP 503）
  6. 记录日志：`logger.error("database_connection_failure", retry_count=..., error=str(e))`
- **重试参数**：最大 3 次，固定间隔 2s。每次重试前必须 `session.close()` + 重新获取连接，禁止在失效连接上重试。

#### 1.9.5 异常 5：响应内容清洗时非字符串类型输入

- **触发条件**：
  - `sanitize_html()` 收到的 `text` 参数不是 `str` 类型（如 `int`、`dict`、`bytes`）
  - 这种情况表明调用方在 Pydantic Schema 校验阶段未正确约束字段类型
- **处理策略**：
  1. 抛出 `TypeError(f"sanitize_html expects str, got {type(text).__name__}")`
  2. 调用方（响应构造代码）应在调用 `sanitize_html` 前通过 `isinstance(text, str)` 防御性检查
  3. 若在响应构造中触发 → 该字段降级为空字符串 `""` 并记录告警日志
- **重试参数**：不重试（非字符串输入不会因重试而变为字符串——这是代码缺陷）

### 1.10 验收测试场景

#### 1.10.1 正向测试 1：合法请求数据校验通过并放行

- **场景**：用户提交完全符合 Schema 约定的请求数据，校验通过，业务逻辑正常执行
- **Given**:
  ```json
  {
    "behavior_description": "孩子不停地拍打桌子，情绪激动",
    "age": 7,
    "gender": "male",
    "consult_mode": "emergency"
  }
  ```
  且 Pydantic Schema 定义了 `behavior_description: str (必填, max_length=500)`、`age: int (必填, ge=0, le=150)`
- **When**: 路由处理函数接收到 `Annotated[ConsultRequestSchema, Depends()]` 参数
- **Then**:
  - FastAPI 自动调用 `ConsultRequestSchema.model_validate(data)`
  - 校验通过，`request.behavior_description == "孩子不停地拍打桌子，情绪激动"`、`request.age == 7`
  - 不触发任何异常，路由处理函数正常执行
  - HTTP 状态码 = 200（由业务逻辑决定）

#### 1.10.2 正向测试 2：内容安全清洗正确转义 XSS 载荷

- **场景**：用户提交的文本包含 XSS 载荷，经 `sanitize_html()` 清洗后安全展示
- **Given**:
  ```python
  dirty_text = '用户反馈：<script>alert("XSS Attack!")</script><img src=x onerror=alert(1)>'
  ```
- **When**: 调用 `sanitize_html(dirty_text)`
- **Then**:
  - 返回: `'用户反馈：&lt;script&gt;alert(&quot;XSS Attack!&quot;)&lt;/script&gt;&lt;img src=x onerror=alert(1)&gt;'`
  - 原始 `<script>` 标签、`onerror` 属性均被转义为纯文本实体
  - 在 HTML 页面渲染时，不会触发脚本执行
  - `sanitize_html(sanitize_html(text)) == sanitize_html(text)`（幂等性）

#### 1.10.3 正向测试 3：文件校验通过（合法 PDF 文件）

- **场景**：用户上传一个标准的 PDF 文件，文件校验通过
- **Given**:
  ```python
  rules = FileValidationRule(
      allowed_mime_types=["application/pdf", "image/jpeg", "image/png"],
      allowed_extensions=[".pdf", ".jpg", ".png"],
      max_size_bytes=10_485_760
  )
  # file 为包含合法 PDF 文件头（%PDF-1.4...）的 UploadFile
  ```
- **When**: 调用 `await validate_file(file, rules)`
- **Then**:
  - 返回 `FileValidationResult(is_valid=True, error_message=None, detected_mime_type="application/pdf", file_size_bytes=1048576)`
  - 魔数检测识别为 `application/pdf`
  - MIME 类型在白名单中 ✓，扩展名 `.pdf` 在白名单中 ✓，大小 1MB < 10MB ✓

#### 1.10.4 异常测试 1：必填字段缺失被正确拦截

- **场景**：用户提交的请求缺少必填字段 `behavior_description`
- **Given**:
  ```json
  {
    "age": 7,
    "gender": "male"
  }
  ```
  其中 `behavior_description` 在 Schema 中为必填（`Field(...)` 无 `default`）
- **When**: 路由处理函数接收数据
- **Then**:
  - FastAPI 返回 HTTP 422
  - 响应体格式为：
    ```json
    {
      "errors": [
        {
          "field": "behavior_description",
          "reason": "field_required",
          "constraint": "field is required"
        }
      ]
    }
    ```
  - 不进入路由处理函数

#### 1.10.5 异常测试 2：SQL 注入载荷被安全检测拦截

- **场景**：攻击者在查询参数中注入 SQL 片段
- **Given**:
  ```json
  {
    "sort_by": "name; DROP TABLE users; --",
    "page": 1
  }
  ```
  该数据已通过 Pydantic 格式校验（`sort_by` 为字符串，`page` 为整数，格式合法）
- **When**: 路由处理函数调用 `detect_security_threat(validated_data)`
- **Then**:
  - 返回 `SecurityDetectionType.sql_injection`
  - 路由处理函数返回 HTTP 400，响应体为：
    ```json
    {
      "errors": [
        {
          "field": "_request",
          "reason": "invalid_content",
          "constraint": "数据包含不安全内容"
        }
      ]
    }
    ```
  - 安全审计日志记录了 `event_type="sql_injection"`、`trace_id`、`detection_detail`（不含 `sort_by` 的原始值全文）
  - 数据库查询未执行

#### 1.10.6 异常测试 3：XSS 载荷被安全检测拦截

- **场景**：攻击者在文本字段中注入 XSS 代码
- **Given**:
  ```json
  {
    "behavior_description": "<script>alert('xss')</script>",
    "age": 10
  }
  ```
- **When**: 路由处理函数调用 `detect_security_threat(validated_data)`
- **Then**:
  - 返回 `SecurityDetectionType.xss_payload`
  - HTTP 400，通用错误响应（不透露检测到的具体 XSS 载荷）
  - 安全审计日志记录 `event_type="xss_payload"`、`trace_id`、`detection_detail`

#### 1.10.7 异常测试 4：文件类型不在白名单中被拒绝

- **场景**：用户尝试上传一个 `.exe` 文件（不在白名单中）
- **Given**:
  ```python
  rules = FileValidationRule(
      allowed_mime_types=["application/pdf", "image/jpeg", "image/png"],
      allowed_extensions=[".pdf", ".jpg", ".png"],
      max_size_bytes=10_485_760
  )
  # file 为 UploadFile(filename="malware.exe", content_type="application/x-msdownload", ...)
  ```
- **When**: 调用 `await validate_file(file, rules)`
- **Then**:
  - 魔数检测结果 `application/x-msdownload` 不在白名单中
  - 扩展名 `.exe` 不在白名单中
  - 返回 `FileValidationResult(is_valid=False, error_message="文件类型不允许，仅支持：pdf, jpg, jpeg, png, webp, mp4, doc, docx", detected_mime_type="application/x-msdownload", file_size_bytes=...)`

### 1.11 注意事项与禁止行为（编码层面）

1. **[约束 1 — 严格遵循 Repository 模式]** 所有数据库操作必须通过 `packages/py-db/repositories/` 中的 Repository 类执行。`apps/api-server/` 下的所有模块禁止出现 `session.execute()`、`session.execute(text(...))` 或任何形式的字符串拼接 SQL。此约束为架构级硬性规定，代码审查强制执行。

2. **[易错点 1 — Pydantic `ValidationError` 与自定义 Exception Handler 的注册位置]** 自定义 Exception Handler 必须注册为 `@app.exception_handler(RequestValidationError)` 而非 `@app.exception_handler(ValidationError)`。前者拦截 FastAPI 在路由匹配阶段产生的校验错误；后者拦截 Pydantic 层更低级别的错误。Handler 必须在 FastAPI app 实例上注册，不得在 router 子实例上注册（否则只对部分路由生效）。

3. **[易错点 2 — 安全检测日志中禁止包含用户原始输入]** `SecurityAuditLogEntry.detection_detail` 字段只记录检测到的威胁类型和受影响的字段名，不得包含用户原始输入全文（防止审计日志被攻击者利用为目标信息源）。示例：
   - 正确：`"SQL injection pattern detected in query_param 'sort_by'"`
   - 错误：`"SQL injection pattern detected: name; DROP TABLE users; --"`

4. **[易错点 3 — `html.escape()` 的 `quote` 参数]** 调用 `html.escape(s, quote=True)` 时必须设置 `quote=True`（已包含在默认值中），确保双引号 `"` 和单引号 `'` 都被转义。若误设为 `quote=False`，属性值注入攻击（如 `<img src=x onerror=...>` 中的引号逃逸）可能绕过防护。

5. **[易错点 4 — 魔数检测的 Seek 操作]** `validate_file()` 中读取文件头 256 字节后，必须执行 `await file.seek(0)` 将游标归零，否则后续业务逻辑（如存储到 MinIO）会从偏移位置开始读取，导致数据不完整或为空。

6. **[禁止行为 1]** 禁止在校验 Schema 的 `Field()` 中嵌入业务判断逻辑或调用外部服务。校验层保持纯函数特征——只声明数据规则，不做业务决策。

7. **[禁止行为 2]** 禁止在 Service 层直接调用 `session.execute()`——即使配合 `text()` 和 `bindparams()` 也是禁止的。所有数据库操作必须通过 Repository 类。

8. **[禁止行为 3]** 禁止文件校验仅依赖 HTTP `Content-Type` 头或文件扩展名进行类型判断。必须通过魔数（magic bytes）检测文件的真实类型，配合扩展名双重验证。

9. **[偷懒红线]** 绝对禁止以"FastAPI 框架自带校验"为由省略安全检测步骤（`detect_security_threat`）。Pydantic 校验的是数据格式，安全检测校验的是数据内容——两者职责不同，不可互相替代。

### 1.12 文档详细度自检清单

- [x] 文档自包含：不了解本项目代码的 Agent，仅凭此文档即可完成编码
- [x] 无偷懒表述：全文不包含 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：每个对外类型都有契约引用（§1.3、§1.4）；内部函数参数和返回值均标注精确类型（§1.6）
- [x] 逻辑步骤完整：5 个核心步骤，每个都有操作对象、具体操作、输入来源、输出去向、失败行为（§1.5）
- [x] 异常处理完整：5 种异常场景，每种都有精确触发阈值、逐步处理策略、精确重试参数（§1.9）
- [x] 无隐藏假设：所有默认值（如 `10_485_760` 字节 = 10MB）来源（设计文档 1.1 决策 5）已明确；条件分支（如安全检测返回 `None` 时放行）已显式写出
- [x] 技术栈绑定明确：必须使用的 6 项技术和禁止使用的 3 项均已列出（§1.1），与项目技术栈设计文档保持一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致（§1.15）

### 1.14 外部接口契约清单

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| ValidationErrorResponse | `docs/contracts/SEC-05/ValidationErrorResponse.json` | output | draft | SEC-05 | 所有 API 模块 |
| ValidationErrorItem | `docs/contracts/SEC-05/ValidationErrorItem.json` | shared-model | draft | SEC-05 | — |
| FileValidationRule | `docs/contracts/SEC-05/FileValidationRule.json` | shared-model | draft | SEC-05 | CASE-02 |
| FileValidationResult | `docs/contracts/SEC-05/FileValidationResult.json` | shared-model | draft | SEC-05 | CASE-02 |
| SecurityAuditLogEntry | `docs/contracts/SEC-05/SecurityAuditLogEntry.json` | shared-model | draft | SEC-05 | OBS-01 |
| sanitize_html | `docs/contracts/SEC-05/sanitize_html.json` | shared-model | draft | SEC-05 | 所有 API 模块 |
| validate_file | `docs/contracts/SEC-05/validate_file.json` | shared-model | draft | SEC-05 | CASE-02 |
| SecurityDetectionType | `docs/contracts/SEC-05/SecurityDetectionType.json` | shared-enum | draft | SEC-05 | 所有 API 模块 |

### 1.15 意图一致性声明

- **配套意图文档**：`SEC-05-输入校验防护-意图文档.md`
- **冻结时间**：`2026-05-26 16:54:46`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致
  - [x] 本落地规范中的状态机实现与意图文档中的状态业务定义一致（均声明为无状态流转）
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致（三条异常路径：请求格式不合规、数据库异常数据、文件上传不安全——全部覆盖且更细化）
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准（AC-01 至 AC-08 均有对应测试场景：AC-01→异常测试1、AC-02→异常测试1、AC-03→异常测试1、AC-04→异常测试2、AC-05→异常测试3和正向测试2、AC-06→正向测试1、AC-07→异常测试4、AC-08→异常测试4）
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围（8 项决策已按设计文档 v1.0 的结论锁定，用户已确认采纳 s06 技术决策报告）
- **偏差说明**：无偏差，技术实现与意图文档完全一致。意图文档中 8 项留白的技术决策（§1.12）已通过技术预研（s06）做出选择，用户确认采纳后写入设计文档（s07），本落地规范严格遵循设计文档的决策结论。
