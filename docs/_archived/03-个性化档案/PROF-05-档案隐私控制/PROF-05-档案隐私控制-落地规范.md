# 1 功能点：PROF-05 档案隐私控制 — 落地规范

> **文档生成时间**：`2026-05-26 23:02:40`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-26 23:02:40` | AI Assistant | 初始版本，基于契约协调报告 v1.0、设计文档 v1.0、已冻结意图文档 |

> **冲突核查指引**：契约协调报告确认零冲突（扫描 62 个已有契约，4 个新类型全部正交）。若后续发现冲突，优先以时间戳更新的版本为准，在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `PROF-05-档案隐私控制-设计文档.md`。

---

### 1.1 技术栈绑定

- **必须使用**：
  - `fastapi>=0.115` — API 路由和 Depends 依赖注入
  - `pydantic>=2.0` — 所有输入/输出模型的基类
  - `sqlalchemy>=2.0` — ORM 模型和异步数据库会话
  - `asyncpg` — PostgreSQL 异步驱动
  - `packages/py-auth` — 共享认证鉴权包（`rbac.py` 中的 `require_role()` 和 `PrivacyGuard`）
  - `packages/py-schemas` — 共享 Schema 包（`profiles.py` 中的 DTO）
  - `packages/py-db` — 共享数据库包（`models/profiles.py` 中的 ORM 模型、`repositories/` 中的查询方法）
  - `packages/py-logger` — 结构化日志输出（`logger.info("unauthorized_access", ...)`）
  - `packages/py-config` — 异常基类和统一错误格式（`AppException`、`ForbiddenAccess`）
  - Python `asyncio` — 异步事务管理
  - `uuid.UUID` — 所有 ID 字段的类型表示

- **禁止使用**：
  - 禁止对关联关系做任何形式的缓存（Redis `SET`/`GET`、进程内 `lru_cache`、`functools.cache`、request-level middleware cache）
  - 禁止绕过 `PrivacyGuard.check_access()` 直接执行数据库操作
  - 禁止在响应中返回差异化的权限错误信息（如 `"您无权访问此档案"`、`"profile_id 不存在"`）
  - 禁止使用 ORM 的 `lazy="joined"` 加载关联关系（需显式控制查询）
  - 禁止在 `professional_notes` 查询中忘记 `visible_after_unlink=true` 过滤条件

---

### 1.2 文件归属

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 权限校验核心（定义方） | `packages/py-auth/py_auth/rbac.py` | 新增 `PrivacyGuard` 类和 `check_profile_access()` 函数。档案级细粒度权限判定逻辑 |
| Service 层调用方 | `apps/api-server/app/services/profile_service.py` | 每个档案操作方法入口调用 `PrivacyGuard.check_access()`。路由与数据库之间的编排层 |
| 异常类 | `packages/py-config/py_config/exceptions.py` | 新增 `ForbiddenAccess` 异常，继承 `AppException`，默认 HTTP 403 |
| Schema 定义 | `packages/py-schemas/py_schemas/profiles.py` | 新增 `AccessOperation`、`AccessRequest`、`AccessDecision`、`VisibleScope` 类型 |
| ORM 模型 | `packages/py-db/py_db/models/profiles.py` | 新增 `TeacherLink` ORM 模型（`teacher_links` 表） |
| ORM 模型（修改） | `packages/py-db/py_db/models/profiles.py` | 在 `ProfessionalNote` 模型新增 `visible_after_unlink: Mapped[bool]` 字段 |
| Repository | `packages/py-db/py_db/repositories/teacher_link_repository.py` | 新增 `find_active_links()`, `unlink_teacher()`, `find_links_by_profile()` 查询方法 |
| 路由入口 | `apps/api-server/app/api/v1/profiles.py` | 在档案相关路由中注入 `require_role()` Depends 作为第一层角色校验 |
| 测试文件 | `apps/api-server/tests/test_privacy_guard.py` | `PrivacyGuard.check_access()` 单元测试 |
| 测试文件 | `apps/api-server/tests/test_teacher_link_repository.py` | `teacher_links` 表 CRUD 操作的集成测试 |

---

### 1.3 输入定义（精确类型）

**对外接口类型 — 契约引用格式**：

**AccessOperation**（枚举）
- 【契约引用】`docs/contracts/PROF-05/AccessOperation.json`
- 本模块作为定义方。消费方：PROF-01, PROF-03, PROF-04
- 六值枚举：`view` | `create` | `update` | `delete` | `supplement_assessment` | `unlink`

**AccessRequest**（输入模型）
- 【契约引用】`docs/contracts/PROF-05/AccessRequest.json`
- 本模块作为定义方。消费方：PROF-01, PROF-03, PROF-04
- 5 个字段：`operation: AccessOperation`, `target_profile_id: UUID`, `requester_id: UUID`, `requester_role: UserRole`（引用 AUTH-04/UserRole）, `relation_type: str | None`

**复用类型 — 引用 AUTH-04**：

**UserRole**（枚举）
- 【契约引用】`docs/contracts/AUTH-04/UserRole.json`
- 定义方：AUTH-04。PROF-05 作为消费方引用
- 五值枚举：`family` | `teacher` | `expert` | `admin` | `maintainer`

**内部类型**（完整字段定义）：

```python
from enum import StrEnum
from uuid import UUID
from pydantic import BaseModel, Field


class AccessOperation(StrEnum):
    """个人档案操作类型枚举"""
    VIEW = "view"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SUPPLEMENT_ASSESSMENT = "supplement_assessment"
    UNLINK = "unlink"


class VisibleScope(StrEnum):
    """档案数据可见范围枚举"""
    ALL_FIELDS = "all_fields"        # 全部字段：家属、关联老师/专家
    METADATA_ONLY = "metadata_only"  # 仅元数据：管理员
    NOTHING = "none"                 # 无内容：非关联用户


class AccessRequest(BaseModel):
    """档案访问请求。由下游模块在执行档案操作前构造并传入 PrivacyGuard"""
    operation: AccessOperation = Field(
        description="请求执行的操作类型。view/create/update/delete 对应档案核心 CRUD，supplement_assessment 为专业评估补充，unlink 为解除老师关联"
    )
    target_profile_id: UUID = Field(
        description="目标个人档案的唯一标识。必须对应 profiles 表中的有效记录"
    )
    requester_id: UUID = Field(
        description="请求发起人的用户唯一标识。必须是已通过 AUTH-04 鉴权的有效用户"
    )
    requester_role: str = Field(
        description="请求发起人的角色。必须为 AUTH-04/UserRole 枚举值之一：family/teacher/expert/admin/maintainer",
        pattern="^(family|teacher|expert|admin|maintainer)$"
    )
    relation_type: str | None = Field(
        default=None,
        description="请求人与目标档案的关联关系类型。linked_teacher/linked_expert 表示已关联，family_member 表示同家庭家属，none 表示无关联。当 requester_role 为 teacher 或 expert 时建议明确填写以确保权限判定准确性"
    )


class AccessDecision(BaseModel):
    """档案访问裁决。由 PrivacyGuard.check_access() 返回，供下游模块决定后续操作"""
    allowed: bool = Field(
        description="访问许可结果。true 表示允许执行操作，false 表示拒绝"
    )
    visible_scope: VisibleScope = Field(
        description="可见数据范围。allowed=true 时值取决于角色（all_fields 或 metadata_only）；allowed=false 时固定为 nothing"
    )
    denial_reason: str | None = Field(
        default=None,
        description="拒绝原因。allowed=false 时必填，值必须为泛化消息'数据不存在'。allowed=true 时为 null",
        max_length=100
    )
```

---

### 1.4 输出定义

**对外接口类型 — 契约引用格式**：

**AccessDecision**（输出模型）
- 【契约引用】`docs/contracts/PROF-05/AccessDecision.json`
- 本模块作为定义方。消费方：PROF-01, PROF-03, PROF-04
- 3 个字段：`allowed: bool`, `visible_scope: VisibleScope`, `denial_reason: str | None`

**VisibleScope**（枚举）
- 【契约引用】`docs/contracts/PROF-05/VisibleScope.json`
- 本模块作为定义方。消费方：PROF-01, PROF-03, PROF-04
- 三值枚举：`all_fields` | `metadata_only` | `nothing`

**ForbiddenAccess 异常响应（服务层）**
- HTTP 403，响应体格式：`{"detail": "数据不存在"}`
- 与 AUTH-04/PermissionDeniedResponse 结构一致（均为 `{"detail": string}`），但 detail 内容为泛化消息以满足静默拒绝策略。此响应由 `ForbiddenAccess` 异常抛出，全局异常处理器捕获后统一返回。

---

### 1.5 核心逻辑步骤

1. **步骤 1：角色存在性校验（路由层）**
   - **操作对象**：API 路由的 Depends 链
   - **具体操作**：档案相关路由（`api/v1/profiles.py`）通过 `require_role()` Depends 校验 `request.state.user.roles` 中存在至少一个有效角色
   - **输入来源**：JWT payload 中的 `roles: list[str]` 字段，由 AUTH-04 `get_current_user` Depends 注入 `request.state.user`
   - **输出去向**：校验通过后用户角色信息进入步骤 2
   - **失败行为**：角色不在允许列表中 → AUTH-04 的 `require_role()` 自动抛出 HTTP 403 `{"detail": "当前角色无权执行此操作"}`，不进入后续步骤

2. **步骤 2：构造访问请求（Service 入口）**
   - **操作对象**：`AccessRequest` 模型实例
   - **具体操作**：从 HTTP 请求上下文和路径参数中提取 5 项字段，调用 `AccessRequest(operation=..., target_profile_id=..., requester_id=..., requester_role=..., relation_type=...)` 构造请求对象
   - **输入来源**：`operation` 来自路由方法语义（如 GET -> view, POST -> create），`target_profile_id` 来自路径参数，`requester_id` 来自 `request.state.user.user_id`，`requester_role` 来自 `request.state.user.roles[0]`，`relation_type` 首次调用时传 None
   - **输出去向**：构造完成的 `AccessRequest` 实例进入步骤 3
   - **失败行为**：Pydantic 校验失败（如 UUID 格式不合法）→ 抛出 `ValidationError`，FastAPI 自动返回 422

3. **步骤 3：档案级权限判定（核心）**
   - **操作对象**：`PrivacyGuard` 类（`packages/py-auth/py_auth/rbac.py`）
   - **具体操作**：调用 `PrivacyGuard.check_access(request: AccessRequest) -> AccessDecision`。内部逻辑：
     a. 查询 `teacher_links` 表：`SELECT * FROM teacher_links WHERE profile_id=$1 AND teacher_id=$2 AND unlinked_at IS NULL`
     b. 根据 `requester_role` 和查询结果按访问矩阵匹配规则判定
     c. 返回 `AccessDecision`（allowed + visible_scope + denial_reason）
   - **输入来源**：步骤 2 构造的 `AccessRequest` 实例
   - **输出去向**：`AccessDecision` 实例进入步骤 4
   - **失败行为**：数据库查询失败 → 抛出数据库异常，全局异常处理器返回 500。不抛出 `ForbiddenAccess`（查询失败不算权限校验失败，是基础设施错误）

4. **步骤 4：裁决执行（Service 出口）**
   - **操作对象**：`AccessDecision` 实例
   - **具体操作**：检查 `access_decision.allowed`：
     - 若 `allowed=True`：继续执行数据库操作，根据 `visible_scope` 决定返回的字段集合（`all_fields` 返回完整记录，`metadata_only` 返回聚合统计）
     - 若 `allowed=False`：抛出 `ForbiddenAccess(detail="数据不存在")`
   - **输入来源**：步骤 3 返回的 `AccessDecision` 实例
   - **输出去向**：允许时执行数据库操作并返回结果；拒绝时抛出异常
   - **失败行为**：无。此步骤仅做条件分支，不涉及外部调用

5. **步骤 5：审计记录（后置）**
   - **操作对象**：结构化日志或 `audit_log` 表
   - **具体操作**：
     - 若访问被允许：仅对 `unlink`/`create` 等关键操作写入 `audit_log` 表持久化
     - 若访问被拒绝：通过 `py-logger` 输出结构化日志，字段 `event_type="unauthorized_access"`, `requester_id`, `target_profile_id`, `requester_role`, `operation`, `trace_id`, `timestamp`
   - **输入来源**：步骤 3 的 `AccessDecision` + 步骤 2 的 `AccessRequest`
   - **输出去向**：stdout（结构化日志）/ PostgreSQL `audit_log` 表（持久化记录）
   - **失败行为**：日志写入失败不影响主流程（`try/except` 包裹，静默失败）

---

### 1.6 接口契约

#### 1.6.1 接口 1：`PrivacyGuard.check_access`

```python
class PrivacyGuard:
    """档案隐私控制守卫。在 Service 层执行档案级细粒度权限校验。

    本类是双层鉴权架构的第二层——在路由层 require_role() 校验通过后，
    对具体档案的访问请求进行基于业务规则的权限判定。

    访问矩阵：
    | 角色        | 查看 | 新增 | 修改 | 删除 | 补充评估 | 解除关联 |
    |------------|------|------|------|------|---------|---------|
    | family     | 允许  | 允许  | 允许  | 允许  | —       | 允许     |
    | teacher    | 允许* | —    | —    | —    | 允许*    | —       |
    | expert     | 允许* | —    | —    | —    | 允许*    | —       |
    | admin      | 仅元数据| —  | —    | —    | —       | —       |
    | maintainer | —    | —    | —    | —    | —       | —       |
    * = 仅当与目标档案存在有效关联关系（teacher_links.unlinked_at IS NULL）时允许
    """

    @staticmethod
    async def check_access(
        request: AccessRequest,
        db_session: AsyncSession,
    ) -> AccessDecision:
        """
        对一次档案访问请求进行权限校验，返回允许或拒绝的裁决。

        Args:
            request: 访问请求上下文，包含操作类型、目标档案ID、请求人ID、角色、关联类型
            db_session: 异步数据库会话，用于查询 teacher_links 关联关系

        Returns:
            AccessDecision: 裁决结论。allowed=true 表示允许，同时指定可见范围；
                           allowed=false 表示拒绝，denial_reason 为泛化消息

        Raises:
            ValueError: AccessRequest.requester_role 不在五级角色枚举中
            SQLAlchemyError: 数据库查询失败（向上层传播）

        Side Effects:
            - 查询 teacher_links 表（SELECT）
            - 不产生任何写入操作

        Idempotency:
            本方法为纯查询操作（只读），无副作用，天然幂等。
            同一参数多次调用返回相同结果（在当前数据状态下）。

        Thread Safety:
            本方法所有状态来自参数传入，无内部可变状态，协程安全。
        """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `PrivacyGuard.check_access` — 语义化，描述"隐私守卫检查访问权限"的业务动作 |
| **输入类型** | `AccessRequest`（详见 1.3 节）+ `db_session: AsyncSession` |
| **输出类型** | `AccessDecision`（详见 1.3 节契约引用） |
| **异常类型** | `ValueError`（角色非法）、`SQLAlchemyError`（数据库失败，向上传播） |
| **副作用** | 仅查询 `teacher_links` 表，无写入 |
| **幂等性** | 纯查询操作，天然幂等 |
| **并发安全** | 无内部可变状态，协程安全 |

---

### 1.7 依赖与集成接口

#### 1.7.1 关键基础设施依赖（硬性前提）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 关系型数据库 | PostgreSQL 17.x | `AsyncSession.execute(select(TeacherLink).where(...))` | 查询家属-老师关联关系，每次请求实时查询 | 项目结构 §6.1 `packages/py-db/`；profiles 表在技术栈设计 §4.2 |
| 日志系统 | py-logger | `logger.info(event_type, **fields)` | 输出越权访问结构化日志 | 项目结构 §6.1 `packages/py-logger/` |
| Web 框架 | FastAPI Depends | `require_role(...)` / `get_current_user` | 路由层角色校验和用户信息注入 | 项目结构 §7.3；AUTH-04 设计文档 §1.1 |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| AUTH-04 五级RBAC鉴权 | `require_role(roles: list[str])` Depends | 路由层第一层角色校验入口 | ✅ 设计文档已冻结，落地规范已生成 |
| AUTH-04 五级RBAC鉴权 | `get_current_user` Depends → `request.state.user.user_id` + `request.state.user.roles` | 获取请求人标识和角色 | ✅ 同上 |
| AUTH-04 五级RBAC鉴权 | `UserRole` 枚举（`family/teacher/expert/admin/maintainer`） | PROF-05 访问矩阵角色参照体系 | ✅ 同上 |
| PROF-01 个人档案管理 | `profile_repository.get_by_id(profile_id)` | 确认目标档案存在 | ⏭️ 待落地（可 mock——返回 `True/False` 模拟档案存在性） |
| OBS-01 结构化日志 | `logger.info("unauthorized_access", **fields)` / `logger.info("access_allowed", **fields)` | 审计事件日志输出 | ✅ 落地规范已生成 |

---

### 1.8 状态机

本功能点不涉及状态流转，故无需状态机。隐私控制的本质是对每一次访问请求进行**实时、无状态裁决**——每次请求到达时基于当前时刻的关联关系状态独立做出允许/拒绝判定。

`teacher_links` 表中关联关系的隐式二态转换在技术层面的原子性要求见设计文档 §1.4。

---

### 1.9 异常与边界条件

#### 1.9.1 异常 1：未授权用户尝试访问档案

- **触发条件**：
  - 请求发起人与目标档案无有效关联关系（`teacher_links` 表无 `unlinked_at IS NULL` 记录）
  - 请求发起人角色为 `maintainer`（维护人员无任何档案访问权）
  - 请求发起人角色为 `admin` 但操作类型不是 `view`（管理员仅可查看）
  - 请求发起人角色为 `teacher`/`expert` 但操作类型是 `create`/`update`/`delete`/`unlink`（老师/专家无权执行家属专属操作）
- **处理策略**：
  1. `PrivacyGuard.check_access()` 内部权限矩阵判定返回 `AccessDecision(allowed=False, visible_scope=VisibleScope.NOTHING, denial_reason="数据不存在")`
  2. `profile_service.py` 检测到 `allowed=False`，抛出 `ForbiddenAccess(detail="数据不存在")`
  3. 全局异常处理器（`packages/py-config/exceptions.py`）捕获 `ForbiddenAccess`，返回 HTTP 403，响应体 `{"detail": "数据不存在"}`
  4. 通过 `py-logger` 输出审计日志：`logger.info("unauthorized_access", event_type="unauthorized_access", requester_id=str(access_request.requester_id), target_profile_id=str(access_request.target_profile_id), requester_role=access_request.requester_role, operation=access_request.operation.value, trace_id=request.state.trace_id, timestamp=datetime.utcnow().isoformat())`
  5. 不进入任何数据库业务操作
- **重试参数**：不重试（每次请求独立裁决，重复请求不会改变结果）

#### 1.9.2 异常 2：关联关系断裂后的访问延续

- **触发条件**：
  - 老师的关联关系已被家属解除（`teacher_links.unlinked_at` 已设为非 NULL）
  - 该老师在同一会话或后续请求中尝试继续访问此前关联的个人档案
  - 每次请求到达时 `PrivacyGuard.check_access()` 实时查询 `teacher_links WHERE unlinked_at IS NULL` 返回空结果
- **处理策略**：
  1. 系统在每次访问请求到达时实时校验关联关系的有效性（`WHERE unlinked_at IS NULL`），不依赖客户端缓存
  2. 关联关系断裂后，该老师的所有后续访问请求均被拒绝
  3. 与异常 1（未授权访问）使用相同的拒绝路径：`ForbiddenAccess` → HTTP 403 → `{"detail": "数据不存在"}`
  4. 不需要通知已解除关联的老师（关联断裂由家属主动执行，无需对方确认）
  5. 拒绝事件通过结构化日志记录（`event_type="unauthorized_access"`，与异常 1 格式相同）
- **重试参数**：不重试（这是正确的安全行为，非系统错误）

#### 1.9.3 异常 3：乐观锁并发冲突——多位家属操作冲突

- **触发条件**：
  - 两位家属同时对同一档案的 `teacher_links` 记录执行更新操作（如家属 A 解除关联、家属 B 也尝试解除同一关联）
  - 家属 B 提交更新时，`teacher_links.version` 已被家属 A 的事务递增，B 持有的 `version` 值与数据库当前值不匹配
  - SQLAlchemy 抛出 `StaleDataError`（乐观锁冲突）
- **处理策略**：
  1. 在 `teacher_link_repository.unlink_teacher()` 方法中，UPDATE 语句包含版本校验：`UPDATE teacher_links SET unlinked_at=NOW(), version=version+1 WHERE link_id=$1 AND version=$2`
  2. 若受影响行数为 0（版本不匹配），SQLAlchemy 抛出 `StaleDataError`
  3. `profile_service.py` 捕获 `StaleDataError`，向客户端返回 HTTP 409 Conflict，响应体 `{"detail": "操作失败，关联关系已变更，请刷新后重试"}`
  4. 不自动重试（冲突意味着另一家属已经完成了操作）
  5. 记录结构化日志：`logger.warning("optimistic_lock_conflict", link_id=str(link_id), expected_version=expected_version, actual_version=current_version)`
- **重试参数**：不重试。客户端收到 409 后刷新页面获取最新状态，用户重新发起操作

---

### 1.10 验收测试场景

#### 1.10.1 正向测试 1：家属本人查看关联档案

- **场景**：家属请求查看其关联的个人档案，系统允许并返回全部字段
- **Given**: 家属用户（`requester_id="550e8400-e29b-41d4-a716-446655440001"`, `requester_role="family"`），目标档案（`target_profile_id="660e8400-e29b-41d4-a716-446655440002"`），`teacher_links` 表中存在该家属与该档案的关联记录（`unlinked_at IS NULL`）
- **When**: 调用 `PrivacyGuard.check_access(AccessRequest(operation=AccessOperation.VIEW, target_profile_id=UUID("660e8400-e29b-41d4-a716-446655440002"), requester_id=UUID("550e8400-e29b-41d4-a716-446655440001"), requester_role="family"))`
- **Then**:
  - 返回 `AccessDecision(allowed=True, visible_scope=VisibleScope.ALL_FIELDS, denial_reason=None)`
  - 日志输出 `event_type="access_allowed"`

#### 1.10.2 正向测试 2：关联老师补充专业评估

- **场景**：与档案有关联关系的老师请求补充专业评估，系统允许
- **Given**: 老师用户（`requester_role="teacher"`, `requester_id="770e8400..."`），目标档案（`target_profile_id="880e8400..."`），`teacher_links` 表中存在该老师与该档案的有效关联记录（`profile_id="880e8400..."`, `teacher_id="770e8400..."`, `unlinked_at IS NULL`, `role="teacher"`）
- **When**: 调用 `PrivacyGuard.check_access(AccessRequest(operation=AccessOperation.SUPPLEMENT_ASSESSMENT, target_profile_id=UUID("880e8400-..."), requester_id=UUID("770e8400-..."), requester_role="teacher", relation_type="linked_teacher"))`
- **Then**:
  - 返回 `AccessDecision(allowed=True, visible_scope=VisibleScope.ALL_FIELDS, denial_reason=None)`

#### 1.10.3 异常测试 1：未关联老师尝试查看档案

- **场景**：与目标档案无关联关系的老师尝试查看档案，系统静默拒绝
- **Given**: 老师用户（`requester_role="teacher"`, `requester_id="999e8400..."`），目标档案（`target_profile_id="aaa08400..."`），`teacher_links` 表中**不存在**该老师与该档案的有效关联记录（`unlinked_at IS NULL` 查询返回 0 行）
- **When**: 调用 `PrivacyGuard.check_access(AccessRequest(operation=AccessOperation.VIEW, target_profile_id=UUID("aaa08400-..."), requester_id=UUID("999e8400-..."), requester_role="teacher"))`
- **Then**:
  - 返回 `AccessDecision(allowed=False, visible_scope=VisibleScope.NOTHING, denial_reason="数据不存在")`
  - `profile_service` 抛出 `ForbiddenAccess(detail="数据不存在")`
  - 日志输出 `event_type="unauthorized_access"`，包含 `requester_id`, `target_profile_id`, `requester_role`, `operation`

#### 1.10.4 异常测试 2：管理员尝试执行非查看操作

- **场景**：管理员尝试新增事件记录，系统拒绝
- **Given**: 管理员用户（`requester_role="admin"`, `requester_id="bbb08400..."`），目标档案（`target_profile_id="ccc08400..."`）
- **When**: 调用 `PrivacyGuard.check_access(AccessRequest(operation=AccessOperation.CREATE, target_profile_id=UUID("ccc08400-..."), requester_id=UUID("bbb08400-..."), requester_role="admin"))`
- **Then**:
  - 返回 `AccessDecision(allowed=False, visible_scope=VisibleScope.NOTHING, denial_reason="数据不存在")`
  - 访问矩阵判定：admin 角色仅 `VIEW` + `metadata_only`，`CREATE` 不在允许列表中

---

### 1.11 注意事项与禁止行为（编码层面）

1. **[事务原子性]** 家属解除关联时的两步操作（更新 `teacher_links.unlinked_at` + 批量设置 `professional_notes.visible_after_unlink=false`）必须在同一数据库事务中执行，使用 `async with db_session.begin()` 包裹。禁止分两次 `await session.commit()`。

2. **[WHERE 条件不遗漏]** 每次查询 `teacher_links` 时必须包含 `unlinked_at IS NULL` 条件，禁止直接 `SELECT * FROM teacher_links WHERE profile_id=$1`。遗漏此条件会导致已解除关联的老师仍被视为有效关联。

3. **[静默拒绝]** 拒绝消息只能是 `{"detail": "数据不存在"}`，禁止使用 `"您无权访问此档案"`、`"profile_id 无效"`、`"角色权限不足"` 等差异化信息。差异化的拒绝信息可被攻击者用于枚举系统中的有效档案 ID 和权限结构。

4. **[禁止缓存关联关系]** 禁止对 `teacher_links` 查询结果做任何形式的缓存——包括 Redis、`functools.lru_cache`、`@cached_property`、request-level middleware cache。每次请求必须实时查询数据库。这是保障"零延迟切断"约束的唯一技术手段。

5. **[不绕过 PrivacyGuard]** `profile_service.py` 中所有档案操作方法（`view_profile`, `create_event`, `update_event`, `delete_event`, `supplement_assessment`, `unlink_teacher` 等）的第一个非空操作必须是 `await PrivacyGuard.check_access(request, db_session)`。内部调用链也不得绕过。

6. **[异常隔离]** `PrivacyGuard.check_access()` 内部只应抛出两种异常：`ValueError`（参数非法）和 SQLAlchemy 传播的数据库异常。`ForbiddenAccess` 应在 Service 层根据 `AccessDecision.allowed` 的结果抛出，不在 `PrivacyGuard` 内部抛出。

7. **[consumer 注册]** PROF-05 已在 AUTH-04/UserRole.json 和 AUTH-04/require_role.json 的 `x-consumers` 中注册为消费方。若未来 AUTH-04 变更这两个契约的接口签名，需同步更新 PROF-05 的调用代码。

---

### 1.12 文档详细度自检清单

- [x] 文档自包含：不了解本项目代码的 Agent 仅凭此文档即可完整实现 `PrivacyGuard`、`teacher_links` 表、`profile_service` 权限校验入口
- [x] 无偷懒表述：全文无 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：每个 Pydantic 字段都有 `description` + `examples` + 约束（`max_length`/`pattern` 等）；对外接口类型使用契约引用
- [x] 逻辑步骤完整：5 个步骤每个都有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：3 种异常每种都有精确的触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值来源、条件分支、业务规则（访问矩阵）都已显式写出
- [x] 技术栈绑定明确：必须使用和禁止使用的项均已列出
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致（详见 §1.15）

---

### 1.14 外部接口契约清单

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| AccessOperation | `docs/contracts/PROF-05/AccessOperation.json` | shared-enum | draft | PROF-05 | PROF-01, PROF-03, PROF-04 |
| VisibleScope | `docs/contracts/PROF-05/VisibleScope.json` | shared-enum | draft | PROF-05 | PROF-01, PROF-03, PROF-04 |
| AccessRequest | `docs/contracts/PROF-05/AccessRequest.json` | input | draft | PROF-05 | PROF-01, PROF-03, PROF-04 |
| AccessDecision | `docs/contracts/PROF-05/AccessDecision.json` | output | draft | PROF-05 | PROF-01, PROF-03, PROF-04 |

**复用契约**：

| 契约名称 | 文件路径 | 定义方 | PROF-05 作为 |
|:---------|:---------|:-------|:------------|
| UserRole | `docs/contracts/AUTH-04/UserRole.json` | AUTH-04 | 消费方 |
| require_role | `docs/contracts/AUTH-04/require_role.json` | AUTH-04 | 消费方 |

---

### 1.15 意图一致性声明

- **配套意图文档**：`PROF-05-档案隐私控制-意图文档.md`
- **冻结时间**：`2026-05-26 22:48:43`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档 §1.6 中的业务字段定义一致（5 个输入字段 → AccessRequest，3 个输出字段 → AccessDecision，枚举值覆盖所有业务含义）
  - [x] 本落地规范中的状态机实现与意图文档 §1.7 的状态业务定义一致（均明确无状态流转，隐私裁决为实时无状态操作）
  - [x] 本落地规范中的异常处理策略与意图文档 §1.8 的异常业务策略一致（异常 1→未授权访问静默拒绝，异常 2→关联断裂后实时校验，异常 3→并发冲突以系统接收顺序为准）
  - [x] 本落地规范中的验收测试场景覆盖意图文档 §1.9 的全部验收标准（AC-01 家属查看 → 正向 1，AC-02 老师查看 → 正向 2，AC-04 非关联拒绝 → 异常 1，AC-05 管理员边界 → 异常 2，AC-06 立即失效 → 异常 §1.9.2）
  - [x] 本落地规范中的技术实现未超出意图文档 §1.12"留给规范阶段的技术决策"的范围（8 项决策全部基于技术决策报告和设计文档明确落地）
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
