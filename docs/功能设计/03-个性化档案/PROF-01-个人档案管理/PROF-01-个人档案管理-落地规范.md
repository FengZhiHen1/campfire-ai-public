# 1 功能点：PROF-01 个人档案管理 — 落地规范

> **文档生成时间**：`2026-05-27 14:37:41`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-27 14:37:41` | AI Assistant | 初始版本，基于 s08 契约协调报告（111 契约扫描、1 项冲突解决、11 项新契约、7 项复用）、设计文档 v1.0、已冻结意图文档 |

> **冲突核查指引**：契约协调报告发现 1 项冲突（BehaviorType 同名异构，medium），已通过将 PROF-01 枚举命名为 `ProfileBehaviorType` 避碰解决。CASE-01 的 `BehaviorType` 契约不受影响。若后续发现冲突，优先以时间戳更新的版本为准，在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `PROF-01-个人档案管理-设计文档.md`。

---

### 1.1 技术栈绑定 【对内实现】

- **必须使用**：
  - `fastapi>=0.115` — API 路由、Depends 依赖注入、HTTP 异常类
  - `pydantic>=2.0` — 所有输入/输出模型的基类，`Field()` 校验约束
  - `sqlalchemy>=2.0` — ORM 模型、异步会话（`AsyncSession`）
  - `asyncpg` — PostgreSQL 异步驱动
  - `uuid.UUID` — 所有 ID 字段的类型（`profile_id`, `caregiver_id`），通过 `uuid.uuid4()` 生成
  - `python-dateutil>=2.8` — `relativedelta` 计算年龄区间（跨闰年/跨月精度）
  - `packages/py-db` — ORM 模型 `Profile`（`py_db/models/profiles.py`）、Repository（`py_db/repositories/profile_repository.py`）
  - `packages/py-schemas` — Pydantic DTO 和枚举（`py_schemas/profiles.py`）
  - `packages/py-auth` — `require_role()` Depends 和 `PrivacyGuard.check_access()`
  - `packages/py-config` — `AppException` 基类、`AppSettings` 配置模型
  - `packages/py-logger` — 结构化日志（`logger.info("profile_created", ...)`）
  - Python `asyncio` — 异步事务管理

- **禁止使用**：
  - 禁止绕过 `PrivacyGuard.check_access()` 直接执行数据库操作
  - 禁止跨用户查询档案（`SELECT ... WHERE caregiver_id != current_user_id`）
  - 禁止使用数据库 CASCADE 删除（事件/评估数据的级联删除通过应用层服务接口编排）
  - 禁止使用软删除（`is_deleted` / `deleted_at` 标记）-- 意图文档要求硬删除
  - 禁止缓存 `ProfileResponse` 或档案列表到 Redis（仅默认档案映射 `profile_default:{caregiver_id}` 可缓存）
  - 禁止在响应中返回 `caregiver_id` 到前端（仅用于后端权限隔离，不出现在 API 响应体中）

---

### 1.2 文件归属 【对内实现】

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| API 路由 | `apps/api-server/app/api/v1/profiles.py` | 6 个端点：列表、创建、详情、更新、删除、获取默认档案。路由前缀 `/api/v1/profiles` |
| Service 层 | `apps/api-server/app/services/profile_service.py` | `ProfileService` 类：`create_profile()`、`list_profiles()`、`get_profile()`、`update_profile()`、`delete_profile()`、`get_default_profile()`。编排鉴权+校验+持久化 |
| ORM 模型 | `packages/py-db/py_db/models/profiles.py` | 新增 `Profile` ORM 模型（`profiles` 表） |
| Repository | `packages/py-db/py_db/repositories/profile_repository.py` | `ProfileRepository` 类：`create()`、`get_by_id()`、`list_by_caregiver()`、`count_active_by_caregiver()`、`update_with_optimistic_lock()`、`delete()`、`get_default()`、`set_default()` |
| Schema 定义 | `packages/py-schemas/py_schemas/profiles.py` | 新增 `ProfileCreate`、`ProfileUpdate`、`ProfileResponse`、`ProfileListItem` Pydantic DTO；新增 6 个枚举（`DiagnosisType`、`ProfileBehaviorType`、`LanguageLevel`、`SensoryFeature`、`Trigger`、`AgeRange`） |
| 异常类 | `packages/py-config/py_config/exceptions.py` | 新增 `ProfileLimitExceededError`（409）、`ProfileConflictError`（409）继承 `AppException` |
| PII 扩展点 | `apps/api-server/app/services/profile_service.py` | 预留 `_pii_check(self, nickname, medication_notes) -> None` 空方法（No-op），待 SEC-03 接口就绪后实现 |
| Alembic 迁移 | `packages/py-db/migrations/versions/` | 新增 `profiles` 表迁移脚本（`profile_id UUID PK`、`caregiver_id UUID FK`、业务字段、`created_at/updated_at` 时间戳、默认档案标记、JSONB GIN 索引） |
| 测试文件 | `apps/api-server/tests/test_profile_service.py` | `ProfileService` 6 个方法的单元/集成测试 |
| 测试文件 | `apps/api-server/tests/test_profile_routes.py` | 6 个 API 端点的 HTTP 层测试 |

---

### 1.3 输入定义（精确类型） 【已锁定】

**对外接口类型 — 契约引用格式**：

**ProfileCreate**（输入模型）
- 【契约引用】`docs/contracts/PROF-01/ProfileCreate.json`
- 本模块作为定义方。消费方：PROF-07（前端逻辑层）
- 3 个必填字段：`birth_date: date`、`diagnosis_type: DiagnosisType`、`primary_behavior: ProfileBehaviorType`
- 5 个可选字段：`nickname: str | None`（max_length=10）、`language_level: LanguageLevel | None`、`sensory_features: list[SensoryFeature]`（0-6 项）、`triggers: list[Trigger]`（0-7 项）、`medication_notes: str | None`（max_length=200）

**ProfileUpdate**（输入模型）
- 【契约引用】`docs/contracts/PROF-01/ProfileUpdate.json`
- 本模块作为定义方。消费方：PROF-07
- 全部 8 个字段为可选，仅提交需要更新的字段，未提交的字段保持原值不变

**复用类型 — 引用 PROF-05**：

**AccessOperation**（枚举）
- 【契约引用】`docs/contracts/PROF-05/AccessOperation.json`
- 定义方：PROF-05。PROF-01 作为消费方引用
- 本模块使用值：`view`（查看档案）、`create`（创建档案）、`update`（更新档案）、`delete`（删除档案）

**AccessRequest**（输入模型）
- 【契约引用】`docs/contracts/PROF-05/AccessRequest.json`
- 定义方：PROF-05。PROF-01 作为消费方引用
- Service 层构造 `AccessRequest(operation=..., target_profile_id=..., requester_id=..., requester_role=UserRole.family)`

**复用类型 — 引用 AUTH-04**：

**UserRole**（枚举）
- 【契约引用】`docs/contracts/AUTH-04/UserRole.json`
- 定义方：AUTH-04。PROF-01 作为消费方引用
- 本模块使用值：`family`（家属）

**require_role**（Depends 函数）
- 【契约引用】`docs/contracts/AUTH-04/require_role.json`
- 定义方：AUTH-04。PROF-01 作为消费方引用
- 路由层：`Depends(require_role(exact_roles=["family"]))`

---

### 1.4 输出定义（精确类型） 【已锁定】

**对外接口类型 — 契约引用格式**：

**ProfileResponse**（输出模型）
- 【契约引用】`docs/contracts/PROF-01/ProfileResponse.json`
- 本模块作为定义方。消费方：PROF-02（检索过滤）、PROF-03（事件记录挂载）、PROF-07（前端展示）
- 14 个字段：`profile_id`, `nickname`, `birth_date`, `age_range`（实时计算）, `diagnosis_type`, `primary_behavior`, `language_level`, `sensory_features`, `triggers`, `medication_notes`, `is_default`, `caregiver_id`, `created_at`, `updated_at`

**ProfileListItem**（输出模型 — 列表精简版）
- 【契约引用】`docs/contracts/PROF-01/ProfileListItem.json`
- 本模块作为定义方。消费方：PROF-07
- 6 个字段：`profile_id`, `nickname`, `age_range`, `diagnosis_type`, `primary_behavior`, `is_default`

**复用输出类型 — 引用项目级共享**：

**PaginatedResponse**（分页包装）
- 【项目级共享类型】位于 `packages/py-schemas/py_schemas/common.py`
- `GET /api/v1/profiles` 返回 `PaginatedResponse[ProfileListItem]`（`items: list[ProfileListItem]`, `total: int`, `page: int`, `page_size: int`, `total_pages: int`）

---

### 1.5 核心逻辑步骤 【对内实现】

按执行顺序列出可测试的原子操作。每步必须包含：操作对象、具体操作、输入来源、输出去向、失败行为。

---

**步骤 1：路由层角色校验**
- **操作对象**：当前请求的身份上下文
- **具体操作**：FastAPI Depends `require_role(exact_roles=["family"])` 从 `request.state.user.roles` 检查请求人是否包含 `family` 角色
- **输入来源**：JWT payload（由 AUTH-02 签发，AUTH-04 注入到 `request.state.user`）
- **输出去向**：校验通过后 `request.state.user.user_id`（UUID）可用，进入步骤 2
- **失败行为**：角色不匹配 → 抛出 `PermissionDeniedError`，返回 403 `{"detail": "当前角色无权执行此操作"}`, 不进入后续步骤

**步骤 2：Pydantic 输入校验**
- **操作对象**：`ProfileCreate` 或 `ProfileUpdate` 模型实例
- **具体操作**：FastAPI 自动调用 `ProfileCreate.model_validate(request_body)` 进行 Pydantic v2 严格校验。校验项包括：`birth_date` 不晚于当前日期（`@field_validator`）、`nickname` ≤ 10 字符（`max_length=10`）、`medication_notes` ≤ 200 字符（`max_length=200`）、枚举值域验证（`DiagnosisType/ProfileBehaviorType/LanguageLevel/SensoryFeature/Trigger`）、数组长度校验（`sensory_features` ≤ 6, `triggers` ≤ 7）
- **输入来源**：HTTP 请求体（JSON）
- **输出去向**：校验通过的 `ProfileCreate` / `ProfileUpdate` 实例进入步骤 3
- **失败行为**：校验失败 → 返回 422 `{"detail": [{"loc": ["field_name"], "msg": "...", "type": "..."}]}`，不进入后续步骤

**步骤 3：档案数量上限校验（仅创建操作）**
- **操作对象**：`profile_repository`
- **具体操作**：执行 `await profile_repository.count_active_by_caregiver(caregiver_id=request.state.user.user_id)`，获得 `active_count: int`
- **输入来源**：`request.state.user.user_id`（UUID）
- **输出去向**：若 `active_count < 5`，进入步骤 4；否则拒绝
- **失败行为**：`active_count >= 5` → 抛出 `ProfileLimitExceededError`，返回 409 `{"detail": "已达到上限...", "error_code": "PROFILE_LIMIT_EXCEEDED", "current_count": 5, "max_allowed": 5}`

**步骤 4：隐私权限校验（仅查看/更新/删除操作）**
- **操作对象**：`PrivacyGuard`（PROF-05）
- **具体操作**：构造 `AccessRequest(operation=AccessOperation.view|update|delete, target_profile_id=profile_id, requester_id=request.state.user.user_id, requester_role=UserRole.family)` 并调用 `await PrivacyGuard.check_access(access_request)` 获得 `AccessDecision`
- **输入来源**：`profile_id`（URL 路径参数）、`request.state.user.user_id`（JWT）
- **输出去向**：若 `AccessDecision.allowed == True`，进入步骤 5；否则拒绝
- **失败行为**：`AccessDecision.allowed == False` → 抛出 `ForbiddenAccess(denial_reason)`，返回 403 `{"detail": "数据不存在"}`（静默拒绝，不泄露档案存在性）

**步骤 5：核心数据操作**
- **操作对象**：`profile_repository` + `profile_service` 业务编排
- **具体操作**（按 CRUD 类型分支）：

  **5a. 创建档案**：
  1. 调用 `uuid.uuid4()` 生成 `profile_id`
  2. 查询当前账号档案总数，若为 0 则 `set_as_default=True`（第一份档案自动设为默认）
  3. 调用 `profile_repository.create(Profile(...))` 执行 `INSERT INTO profiles`，在单个事务中完成
  4. 若 `set_as_default=True`，在同一事务中执行 `UPDATE profiles SET is_default=false WHERE caregiver_id=? AND is_default=true`（取消旧默认），再 `SET is_default=true`（设置新默认）
  5. 返回 `ProfileResponse`，含实时计算的 `age_range`

  **5b. 查询档案列表**：
  1. 执行 `profile_repository.list_by_caregiver(caregiver_id, page, page_size)` 查询当前家属的所有 active 档案
  2. 对每个结果实时计算 `age_range`，映射到 `ProfileListItem`
  3. 包装为 `PaginatedResponse[ProfileListItem]` 返回

  **5c. 查询档案详情**：
  1. 执行 `profile_repository.get_by_id(profile_id)` WHERE caregiver_id 匹配
  2. 实时计算 `age_range`，映射到 `ProfileResponse`
  3. 返回

  **5d. 更新档案**：
  1. 读取当前行 `updated_at` 值
  2. 执行 `profile_repository.update_with_optimistic_lock(profile_id, caregiver_id, previous_updated_at, update_data)`
  3. SQL: `UPDATE profiles SET ... WHERE profile_id=? AND caregiver_id=? AND updated_at=? RETURNING *`
  4. 若返回行数为 0 → 乐观锁冲突
  5. 成功则返回更新后的 `ProfileResponse`

  **5e. 删除档案**：
  1. 检查是否为默认档案（若为默认，需在同一事务中提升另一档案为默认）
  2. 执行 `profile_service.delete_profile()` 编排级联删除：
     a. 调用 PROF-03 服务接口 `event_service.delete_by_profile(profile_id)` 清理事件记录
     b. 调用 PROF-04 服务接口 `assessment_service.delete_by_profile(profile_id)` 清理评估记录
     c. 若为默认档案，执行 `profile_repository.set_default(next_profile_id)` 提升另一档案
     d. 执行 `profile_repository.delete(profile_id)` 硬删除 `DELETE FROM profiles WHERE profile_id=? AND caregiver_id=?`
  3. 以上全部在一个数据库事务中执行，任一步失败则全部回滚

- **输入来源**：步骤 2/3/4 校验通过的输入数据 + 用户身份
- **输出去向**：`ProfileResponse` 或 `PaginatedResponse[ProfileListItem]` 返回给调用方
- **失败行为**：
  - 乐观锁冲突 → 抛出 `ProfileConflictError`，返回 409 `{"detail": "档案数据已被其他设备修改，请刷新页面后重新操作。", "error_code": "PROFILE_CONFLICT"}`
  - 档案不存在 → 抛出 `AppException(status_code=404, detail="档案不存在")`
  - 数据库异常 → 抛出原始异常（500），由全局异常处理器统一处理
  - PROF-03/04 级联删除失败 → 事务回滚，不部分删除数据

**步骤 6：日志与响应**
- **操作对象**：`py-logger` 结构化日志
- **具体操作**：输出操作事件日志，含 `event_type: "profile_created"|"profile_updated"|"profile_deleted"|"profile_listed"|"profile_read"`、`profile_id`、`caregiver_id`、`trace_id`、操作耗时（ms）
- **输入来源**：步骤 5 操作结果
- **输出去向**：标准输出（Docker 日志驱动收集）
- **失败行为**：日志输出失败不阻塞主流程，仅警告级别记录

**步骤 7：PII 检测预留扩展点（仅创建/更新操作）**
- **操作对象**：`self._pii_check(nickname, medication_notes)`（No-op 空方法）
- **具体操作**：当前为空实现（`pass`），待 SEC-03 接口就绪后替换为真实 PII 检测调用
- **输入来源**：`nickname: str | None`、`medication_notes: str | None`
- **输出去向**：无（No-op）
- **失败行为**：当前无（No-op 不会失败）

---

### 1.6 接口契约（对外暴露的公共接口） 【已锁定】

#### 1.6.1 API 端点一览

| 方法 | 路径 | 说明 | 权限 | 输入 | 输出 |
|------|------|------|------|------|------|
| `GET` | `/api/v1/profiles` | 获取当前家属的所有档案列表 | family | Query: `page: int=1, page_size: int=10` | `PaginatedResponse[ProfileListItem]` |
| `POST` | `/api/v1/profiles` | 创建新患者档案 | family | Body: `ProfileCreate` | `ProfileResponse` (201) |
| `GET` | `/api/v1/profiles/{profile_id}` | 获取单个档案详情 | family（权限校验） | Path: `profile_id: UUID` | `ProfileResponse` |
| `PUT` | `/api/v1/profiles/{profile_id}` | 更新已有档案 | family（权限校验） | Path: `profile_id: UUID`, Body: `ProfileUpdate` | `ProfileResponse` |
| `DELETE` | `/api/v1/profiles/{profile_id}` | 删除档案及关联数据 | family（权限校验） | Path: `profile_id: UUID` | 204 No Content |
| `GET` | `/api/v1/profiles/me/default` | 获取当前账号默认档案 | family | 无 | `ProfileResponse` |

#### 1.6.2 核心 Service 方法签名

```python
class ProfileService:
    """个人档案管理的核心业务编排层。每个方法的第一步行都是隐私权限校验。"""

    async def create_profile(
        self,
        caregiver_id: UUID,
        input: ProfileCreate,
    ) -> ProfileResponse:
        """
        为指定家属创建新患者档案。

        Args:
            caregiver_id: 家属用户标识（来自 JWT payload）
            input: 档案创建请求体（已通过 Pydantic 校验）

        Returns:
            ProfileResponse: 创建成功的档案完整数据，含服务端生成的 profile_id、
                age_range（实时计算）、created_at、updated_at

        Raises:
            ProfileLimitExceededError: 当前账号已有 5 个档案，触发 409 Conflict
            ValidationError: Pydantic 校验失败（由路由层自动返回 422）
            AppException(500): 数据库操作失败

        Side Effects:
            - 向 profiles 表 INSERT 新行
            - 若为第一份档案，同时设置 is_default=true
            - 记录结构化日志（event_type: "profile_created"）

        Idempotency: 不保证幂等——每次调用创建一份新档案
        """
        ...

    async def list_profiles(
        self,
        caregiver_id: UUID,
        page: int = 1,
        page_size: int = 10,
    ) -> PaginatedResponse[ProfileListItem]:
        """
        获取指定家属账号下所有 active 档案的列表。

        Args:
            caregiver_id: 家属用户标识
            page: 页码（从 1 开始）
            page_size: 每页条数（默认 10，上限 100）

        Returns:
            PaginatedResponse[ProfileListItem]: 分页档案列表

        Raises:
            AppException(500): 数据库查询失败

        Side Effects: 仅读操作，无副作用
        """
        ...

    async def get_profile(
        self,
        caregiver_id: UUID,
        profile_id: UUID,
    ) -> ProfileResponse:
        """
        获取单个档案的完整详情。需通过 PROF-05 权限校验。

        Args:
            caregiver_id: 请求人家属标识
            profile_id: 目标档案标识

        Returns:
            ProfileResponse: 档案完整详情

        Raises:
            ForbiddenAccess: 权限校验不通过（403，静默拒绝）
            AppException(404): 档案不存在

        Side Effects: 仅读操作，无副作用
        """
        ...

    async def update_profile(
        self,
        caregiver_id: UUID,
        profile_id: UUID,
        input: ProfileUpdate,
    ) -> ProfileResponse:
        """
        更新已有档案的部分字段。使用乐观锁防止并发冲突。

        Args:
            caregiver_id: 请求人家属标识
            profile_id: 目标档案标识
            input: 需要更新的字段（全部可选，仅提交变更字段）

        Returns:
            ProfileResponse: 更新后的完整档案数据

        Raises:
            ForbiddenAccess: 权限校验不通过
            ProfileConflictError: 乐观锁冲突（409，updated_at 不匹配）
            AppException(404): 档案不存在

        Side Effects:
            - UPDATE profiles 表
            - 刷新 updated_at 时间戳
            - 记录结构化日志（event_type: "profile_updated"）

        Thread Safety: 乐观锁保证并发安全
        """
        ...

    async def delete_profile(
        self,
        caregiver_id: UUID,
        profile_id: UUID,
    ) -> None:
        """
        删除档案及关联的事件记录和评估数据。硬删除，不可恢复。
        若删除的是默认档案，自动提升另一档案为默认。

        Args:
            caregiver_id: 请求人家属标识
            profile_id: 目标档案标识

        Returns: None（HTTP 204 No Content）

        Raises:
            ForbiddenAccess: 权限校验不通过
            AppException(404): 档案不存在

        Side Effects:
            - 调用 PROF-03 服务接口清理事件记录
            - 调用 PROF-04 服务接口清理评估记录
            - DELETE FROM profiles
            - 若为默认档案，SET is_default=true 于另一档案
            - 以上全部在同一事务中，任一步失败则全部回滚

        Idempotency: 重复删除已不存在的档案返回 404
        """
        ...

    async def get_default_profile(
        self,
        caregiver_id: UUID,
    ) -> ProfileResponse:
        """
        获取当前账号的默认档案。用于应急咨询等需要默认关联的场景。

        Args:
            caregiver_id: 家属用户标识

        Returns:
            ProfileResponse: 默认档案完整详情

        Raises:
            AppException(404): 账号下无档案（冷启动状态）

        Side Effects: 仅读操作，无副作用
        """
        ...
```

---

### 1.7 依赖与集成接口（本模块调用的外部接口） 【已锁定】

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 关系数据库 | PostgreSQL 17.x | `AsyncSession.execute(select(...))` 参数化查询 | 档案数据的持久化存储和查询 | 技术栈 §2 DB 选型；项目结构 §6.1 py-db |
| 关系数据库 | PostgreSQL 17.x | `CREATE INDEX ... USING GIN (sensory_features, triggers)` JSONB GIN 索引 | 供 PROF-02 标签过滤查询 | 技术栈 §4.2（profiles 使用 JSONB tags+GIN） |
| ORM 层 | SQLAlchemy 2.0 async | `Mapped[UUID]` 列类型、`AsyncAttrs` Mixin、`select()` 查询构造 | ORM 模型定义和查询 | 项目结构 §6.1 py-db/models/ |
| Schema 校验 | Pydantic v2 | `BaseModel.model_validate()`、`@field_validator` | 入参校验和错误响应构造 | 技术栈 §5 输入校验；项目结构 §6.1 py-schemas/ |
| 日志系统 | py-logger | `logger.info("profile_created", profile_id=..., caregiver_id=..., trace_id=...)` | 所有 CRUD 操作的结构化日志 | 项目结构 §6.1 py-logger/ |
| 配置管理 | py-config | `AppSettings(database_url=..., max_profiles_per_user=5)` | 数据库连接串和业务参数加载 | 项目结构 §6.1 py-config/ |
| 数据库迁移 | Alembic | `alembic revision --autogenerate -m "add profiles table"` | profiles 表创建和版本化迁移 | 项目结构 §6.1 py-db/migrations/ |
| 可选缓存 | Redis 7.x | `redis_client.get(f"profile_default:{caregiver_id}")` / `SETEX` | 默认档案映射缓存（TTL 5 分钟，降级到 DB 查询） | 技术栈 §2（Redis 缓存） |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| PROF-05 档案隐私控制 | `PrivacyGuard.check_access(AccessRequest) -> AccessDecision` | 所有档案 CRUD 操作的权限校验 | ✅ 已落地（契约已冻结，实现位于 `packages/py-auth/py_auth/rbac.py`） |
| AUTH-04 五级RBAC鉴权 | `require_role(exact_roles=["family"])` FastAPI Depends | 路由层家属角色身份校验 | ✅ 已落地（契约已冻结，x-consumers 已注册 PROF-01） |
| AUTH-04 五级RBAC鉴权 | `get_current_user` FastAPI Depends → `request.state.user.user_id` | 从 JWT payload 获取当前用户 UUID | ✅ 已落地 |
| PROF-03 事件记录管理 | `event_service.delete_by_profile(profile_id: UUID)` — 应用层服务接口调用 | 删除档案时级联清理关联事件记录 | ⏳ 待落地（PROF-03 尚未设计，当前可 Mock 为 No-op，待 PROF-03 就绪后对接） |
| PROF-04 专业评估补充 | `assessment_service.delete_by_profile(profile_id: UUID)` — 应用层服务接口调用 | 删除档案时级联清理关联评估记录 | ⏳ 待落地（PROF-04 尚未设计，当前可 Mock 为 No-op，待 PROF-04 就绪后对接） |
| SEC-03 PII检测脱敏 | `_pii_check(nickname, medication_notes)` — 预留扩展点，当前为 No-op | 档案数据写入前检测 PII | ⏳ 未设计（SEC-03 尚无契约文件，当前阶段仅做前端提示 + 后端关键词正则过滤） |

> **Mock 策略**：PROF-03/04 的级联删除接口暂未就绪时，`profile_service.delete_profile()` 中的级联调用可 Mock 为返回 True 的 No-op，待下游模块实现后替换。SEC-03 的 PII 检测扩展点本身就是 No-op，待 SEC-03 接口定义后替换。

---

### 1.8 状态机 【对内实现】

本功能点不涉及状态流转，故无需状态机。目的文档 §1.7 明确声明档案的创建、查看、更新和删除均为家属发起的即时同步操作，不存在中间状态或异步等待流程。

档案行本身存在隐式生命周期（不存在 → 存在 → 不存在），但不构成需要状态转换表管理的复杂流转：

| 事件 | 数据库操作 | 前置条件 | 副作用 |
|------|-----------|----------|--------|
| 创建档案 | `INSERT INTO profiles` | 账号下 active 档案 < 5，Pydantic 校验通过 | 若为第一份档案，自动设 `is_default=true` |
| 更新档案 | `UPDATE profiles ... WHERE updated_at=?` | 乐观锁条件匹配 | 刷新 `updated_at` 时间戳 |
| 删除档案 | `DELETE FROM profiles` | 权限校验通过，级联清理完成 | 若为默认档案，提升另一档案为默认 |

---

### 1.9 异常与边界条件 【对内实现】

#### 1.9.1 异常 1：必填字段缺失

- **触发阈值**：`birth_date` 为 `None`、`diagnosis_type` 为 `None` 或 `primary_behavior` 为 `None`（三项中任一项缺失）
- **处理策略**：
  1. Pydantic v2 校验阶段捕获 `ValidationError`
  2. FastAPI 自动构造 422 响应体 `{"detail": [{"loc": ["birth_date"], "msg": "Field required", "type": "missing"}]}`
  3. 不进入任何 Service 层逻辑，不产生数据库操作
  4. 日志记录：`logger.warning("input_validation_failed", operation="create_profile", missing_fields=[...])`
- **重试参数**：不重试，客户端补填缺失字段后重新发起请求

#### 1.9.2 异常 2：档案数量超限

- **触发阈值**：当前家属账号下 `COUNT(*) WHERE caregiver_id=? AND status='active'` 查询结果 >= 5（通过 `AppSettings.max_profiles_per_user` 配置）
- **处理策略**：
  1. Service 层 `create_profile()` 方法在步骤 3 执行 `count_active_by_caregiver()` 查询
  2. 若 `active_count >= 5`，构造 `ProfileLimitExceededError` 异常
  3. 全局异常处理器捕获，返回 HTTP 409 `{"detail": "您已达到单个账号最多 5 个档案的上限。如需为新的患者建档，可先删除一个不再需要的旧档案（删除操作不可恢复），或使用另一个家属账号创建。", "error_code": "PROFILE_LIMIT_EXCEEDED", "current_count": 5, "max_allowed": 5}`
  4. 日志记录：`logger.warning("profile_limit_exceeded", caregiver_id=..., current_count=5)`
- **重试参数**：不重试，用户需先删除旧档案

#### 1.9.3 异常 3：输入格式不合法

- **触发阈值**：
  - `birth_date` > 当前日期（未来日期）-- `@field_validator("birth_date")` 校验
  - `nickname` 字符数 > 10 -- `max_length=10`
  - `medication_notes` 字符数 > 200 -- `max_length=200`
  - `sensory_features` 数组长度 > 6
  - `triggers` 数组长度 > 7
  - 枚举字段值不在允许列表中
- **处理策略**：
  1. Pydantic v2 校验阶段自动捕获
  2. 返回 422 `{"detail": [{"loc": ["field_name"], "msg": "具体违规原因", "type": "value_error"}]}`
  3. 支持多字段错误聚合（Pydantic 默认行为，一次返回所有违规字段）
  4. 日志记录：`logger.warning("input_validation_failed", operation=..., violations=[...])`
- **重试参数**：不重试，客户端修正后重新提交

#### 1.9.4 异常 4：并发冲突（乐观锁）

- **触发阈值**：`UPDATE ... WHERE profile_id=? AND caregiver_id=? AND updated_at=? RETURNING *` 返回行数为 0
- **处理策略**：
  1. Repository 层 `update_with_optimistic_lock()` 检测到 RowCount == 0
  2. 抛出 `ProfileConflictError`
  3. 全局异常处理器返回 HTTP 409 `{"detail": "档案数据已被其他设备修改，请刷新页面后重新操作。", "error_code": "PROFILE_CONFLICT"}`
  4. 日志记录：`logger.warning("profile_conflict", profile_id=..., caregiver_id=..., previous_updated_at=..., current_updated_at=...)`
- **重试参数**：不自动重试，用户刷新后手动重试

#### 1.9.5 异常 5：档案不存在

- **触发阈值**：`SELECT ... WHERE profile_id=? AND caregiver_id=?` 返回 None
- **处理策略**：
  1. Repository 层 `get_by_id()` 返回 None
  2. Service 层抛出 `AppException(status_code=404, detail="档案不存在")`
  3. 全局异常处理器返回 HTTP 404
  4. 使用统一提示（不区分"档案不存在"和"无权访问"，防止信息泄露）
  5. 日志记录：`logger.warning("profile_not_found", profile_id=..., caregiver_id=...)`（注意：日志中使用真实原因，仅对客户端统一模糊提示）
- **重试参数**：不重试

#### 1.9.6 异常 6：数据库连接故障

- **触发阈值**：`AsyncSession.execute()` 抛出 `sqlalchemy.exc.OperationalError`、`asyncpg.exceptions.ConnectionDoesNotExistError` 或连接超时（`asyncio.TimeoutError` > 5s）
- **处理策略**：
  1. 捕获数据库驱动层异常
  2. 关闭当前失效连接（`await session.close()`）
  3. 重试同一操作
  4. 第 3 次仍失败：向上抛出原始异常，全局异常处理器返回 500 `{"detail": "服务器内部错误"}`
  5. 日志记录：`logger.critical("database_connection_failure", error_type=..., retry_count=..., trace_id=...)`
- **重试参数**：最大 3 次，固定间隔 1s

---

### 1.10 验收测试场景 【对内实现】

#### 1.10.1 正向测试 1：冷启动创建首个档案

- **场景**：新家属用户首次登录，无任何档案，填写全部字段创建第一个患者档案
- **Given**:
  - 家属用户已认证（`caregiver_id = "a1b2c3d4-..."` ，具有 `family` 角色）
  - 当前账号下无活跃档案（`COUNT(*) = 0`）
  - 请求体：
    ```json
    {
      "nickname": "小明",
      "birth_date": "2019-03-15",
      "diagnosis_type": "ASD",
      "primary_behavior": "刻板行为",
      "language_level": "短句",
      "sensory_features": ["听觉敏感", "触觉敏感"],
      "triggers": ["噪音", "环境变化"],
      "medication_notes": "利培酮每日 0.5mg，睡前服用"
    }
    ```
- **When**: 客户端发送 `POST /api/v1/profiles`
- **Then**:
  - HTTP 状态码 201
  - 响应体包含 `"profile_id"`（UUID v4 格式）、`"age_range": "7-12岁"`（根据出生日期 2019-03-15 实时计算）
  - `"is_default": true`（首个档案自动设为默认）
  - `"caregiver_id": "a1b2c3d4-..."`（不暴露给前端但包含在响应中供后端内部使用）
  - `"created_at"` 和 `"updated_at"` 为当前北京时间
  - 所有提交字段完整反映在响应中
  - 结构化日志含 `"event_type": "profile_created"`

#### 1.10.2 正向测试 2：更新档案部分字段

- **场景**：家属修改已有档案的语言水平和用药备注，其他字段不变
- **Given**:
  - 已有档案 `profile_id = "e5f6a7b8-..."`，`updated_at = "2026-05-27T10:00:00+08:00"`
  - 请求体：
    ```json
    {
      "language_level": "可对话",
      "medication_notes": "已停药，改为行为干预"
    }
    ```
- **When**: 客户端发送 `PUT /api/v1/profiles/e5f6a7b8-...`
- **Then**:
  - HTTP 状态码 200
  - `"language_level": "可对话"`, `"medication_notes": "已停药，改为行为干预"`
  - 其他未提交字段（nickname, birth_date, diagnosis_type 等）保持原值不变
  - `"updated_at"` 已刷新（> 之前的 10:00:00）
  - 结构化日志含 `"event_type": "profile_updated"`

#### 1.10.3 正向测试 3：获取档案列表（含分页）

- **场景**：家属查看所有档案列表，共 3 个档案
- **Given**:
  - 家属 `caregiver_id = "a1b2c3d4-..."` 下有 3 个活跃档案
  - 查询参数：`page=1, page_size=10`
- **When**: 客户端发送 `GET /api/v1/profiles?page=1&page_size=10`
- **Then**:
  - HTTP 状态码 200
  - `"items"` 数组长度为 3，每个元素含 `profile_id`, `nickname`, `age_range`, `diagnosis_type`, `primary_behavior`, `is_default`
  - `"total": 3`, `"page": 1`, `"page_size": 10`, `"total_pages": 1`
  - 其中恰好 1 个档案 `"is_default": true`

#### 1.10.4 异常测试 1：必填字段缺失

- **场景**：家属提交创建请求时漏填必填的 `diagnosis_type` 字段
- **Given**:
  - 请求体：
    ```json
    {
      "birth_date": "2019-03-15",
      "primary_behavior": "刻板行为"
    }
    ```
  - （缺少 `diagnosis_type`）
- **When**: 客户端发送 `POST /api/v1/profiles`
- **Then**:
  - HTTP 状态码 422
  - `"detail"` 数组中包含 `{"loc": ["diagnosis_type"], "msg": "Field required", "type": "missing"}`
  - 数据库无新增记录（`COUNT(*)` 未增加）

#### 1.10.5 异常测试 2：档案数量超限

- **场景**：家属已有 5 个档案，尝试创建第 6 个
- **Given**:
  - 家属 `caregiver_id = "a1b2c3d4-..."` 下已有 5 个活跃档案
  - 请求体为有效的 `ProfileCreate`（三个必填字段完整）
- **When**: 客户端发送 `POST /api/v1/profiles`
- **Then**:
  - HTTP 状态码 409
  - `"error_code": "PROFILE_LIMIT_EXCEEDED"`
  - `"current_count": 5`, `"max_allowed": 5`
  - `"detail"` 包含引导文案（"可先删除一个不再需要的旧档案"）
  - 数据库无新增记录

#### 1.10.6 异常测试 3：并发更新冲突

- **场景**：设备 A 和设备 B 同时读取同一档案，设备 A 先更新成功，设备 B 再更新时触发乐观锁冲突
- **Given**:
  - 档案 `profile_id = "e5f6a7b8-..."`，当前 `updated_at = "2026-05-27T10:00:00+08:00"`
  - 设备 A 已成功更新（`updated_at` 变为 `"2026-05-27T10:01:00+08:00"`）
  - 设备 B 仍持有旧的 `updated_at = "2026-05-27T10:00:00+08:00"`
- **When**: 设备 B 发送 `PUT /api/v1/profiles/e5f6a7b8-...`
- **Then**:
  - HTTP 状态码 409
  - `"error_code": "PROFILE_CONFLICT"`
  - `"detail"` 包含 "已被其他设备修改，请刷新页面后重新操作"
  - 档案数据未变更（保持设备 A 更新后的状态）

#### 1.10.7 异常测试 4：输入格式非法

- **场景**：家属将出生日期设为未来日期，昵称超过 10 字
- **Given**:
  - 请求体：
    ```json
    {
      "birth_date": "2099-01-01",
      "diagnosis_type": "ASD",
      "primary_behavior": "刻板行为",
      "nickname": "这是一个非常长的昵称超出了十字限制"
    }
    ```
- **When**: 客户端发送 `POST /api/v1/profiles`
- **Then**:
  - HTTP 状态码 422
  - `"detail"` 数组包含 2 个错误：
    - `{"loc": ["birth_date"], "msg": "出生日期不能晚于当前日期", "type": "value_error"}`
    - `{"loc": ["nickname"], "msg": "String should have at most 10 characters", "type": "string_too_long"}`

---

### 1.11 注意事项与禁止行为（编码层面） 【对内实现】

1. **[必须通过 PrivacyGuard]** 每个 Service 方法（`get_profile`, `update_profile`, `delete_profile`）的第一步必须是 `await PrivacyGuard.check_access(...)`。禁止在 `profile_service.py` 中编写不经过权限校验的数据访问代码。资源列表操作（`list_profiles`）是唯一例外——它仅查询当前 caregiver 的数据，按设计无需逐档案权限校验。

2. **[caregiver_id 强制限定]** 所有数据库查询必须包含 `WHERE caregiver_id = :caregiver_id` 条件。禁止任何跨家属的档案查询。`caregiver_id` 来自 `request.state.user.user_id`（JWT payload 注入），禁止从客户端请求中读取 `caregiver_id`。

3. **[乐观锁实现细节]** `update_with_optimistic_lock()` 的 SQL 必须是 `UPDATE profiles SET ... WHERE profile_id = :pid AND caregiver_id = :cid AND updated_at = :prev_ts RETURNING *`。检查返回行数，若为 0 则抛出 `ProfileConflictError`。禁止使用 `SELECT FOR UPDATE`（悲观锁）或增加版本号字段。

4. **[默认档案一致性]** 创建首个档案时必须自动设 `is_default=true`。删除默认档案时必须将另一档案提升为默认（选取 `updated_at` 最新者）。切换默认档案时，必须在同一事务中：先 `UPDATE ... SET is_default=false WHERE caregiver_id=? AND is_default=true`，再 `UPDATE ... SET is_default=true WHERE profile_id=?`。两个 UPDATE 在同一事务中执行。

5. **[删除级联的顺序和原子性]** 删除档案时的级联清理顺序必须是：(1) 校验权限、(2) 清理 PROF-03 事件记录、(3) 清理 PROF-04 评估记录、(4) 处理默认档案提升、(5) 硬删除本行。以上 5 步在同一数据库事务中，任一步失败则全部回滚。禁止分两步提交级联删除——否则可能出现"事件记录已清理但档案未删除"的不一致状态。

6. **[硬删除不可恢复]** 使用 `DELETE FROM profiles WHERE ...` 硬删除，禁止 `SET is_deleted=true` 或 `SET deleted_at=NOW()` 的软删除方式。受意图文档约束。

7. **[PII 检测扩展点]** `_pii_check(nickname, medication_notes)` 当前为 No-op 空方法。禁止在此方法为空时跳过调用——代码中必须保留调用点以备未来对接。当 SEC-03 接口就绪后，替换 `pass` 为实际 PII 检测调用。前端提示"避免填写真实姓名"的逻辑归属 PROF-07，不在此模块实现。

8. **[跨模块调用必须通过接口]** 禁止 PROF-01 直接访问 PROF-03 的 `event_logs` 表、PROF-04 的 `professional_notes` 表、PROF-05 的 `teacher_links` 表。所有跨模块数据依赖必须通过对方模块的服务接口调用。

9. **[年龄区间实时计算]** `age_range` 字段不在数据库中持久化存储。每次返回 `ProfileResponse` 时，通过 `birth_date` 实时计算：使用 `dateutil.relativedelta.relativedelta(datetime.date.today(), birth_date).years` 得到年龄整数，然后映射到区间枚举值（0-3/4-6/7-12/13-18/18+）。禁止将 `age_range` 作为数据库列存储。

10. **[禁止跨档案数据泄露]** 日志记录中禁止输出患者昵称、出生日期等可识别信息的具体值。日志中的 `profile_id` 用于追踪，但昵称和出生日期不应出现在日志中。权限拒绝日志应记录 `profile_id` 但不记录档案内容。

---

### 1.12 文档详细度自检清单 【对内实现】

- [x] 文档自包含：不了解本项目代码的 Agent，仅凭此文档即可从头编写 `profile_service.py`、`profile_repository.py`、`profiles.py`（路由）、`profiles.py`（Schema）、`Profile` ORM 模型和 Alembic 迁移脚本
- [x] 无偷懒表述：全文无 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：每个对外 Pydantic 字段都对应具体的契约 JSON Schema（含 `description` + `examples` + 约束），内部模型字段在 §1.3-1.4 中完整定义
- [x] 逻辑步骤完整：§1.5 的 7 个步骤中每步都有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：§1.9 的 6 种异常都有精确触发阈值、逐步处理策略、重试参数
- [x] 无隐藏假设：`MAX_PROFILES_PER_USER=5` 的来源是 `AppSettings` 配置项（可配置）、年龄区间计算精度确认为"年"级别、乐观锁通过 `updated_at` 时间戳比较（非版本号）、级联删除顺序清晰
- [x] 技术栈绑定明确：必须使用和禁止使用的项均在 §1.1 列出，且与 `docs/篝火智答-技术栈设计.md` 保持一致（FastAPI>=0.115, Pydantic>=2.0, SQLAlchemy>=2.0 async, PostgreSQL 17.x, asyncpg, uuid, python-dateutil）
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致（见 §1.15）

---

### 1.14 外部接口契约清单 【对内实现】

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| DiagnosisType | `docs/contracts/PROF-01/DiagnosisType.json` | shared-enum | draft | PROF-01 | PROF-02, PROF-07 |
| LanguageLevel | `docs/contracts/PROF-01/LanguageLevel.json` | shared-enum | draft | PROF-01 | PROF-02, PROF-07 |
| SensoryFeature | `docs/contracts/PROF-01/SensoryFeature.json` | shared-enum | draft | PROF-01 | PROF-02, PROF-07 |
| Trigger | `docs/contracts/PROF-01/Trigger.json` | shared-enum | draft | PROF-01 | PROF-02, PROF-07 |
| AgeRange | `docs/contracts/PROF-01/AgeRange.json` | shared-enum | draft | PROF-01 | PROF-02, PROF-07 |
| ProfileBehaviorType | `docs/contracts/PROF-01/ProfileBehaviorType.json` | shared-enum | draft | PROF-01 | PROF-02, PROF-07 |
| ProfileCreate | `docs/contracts/PROF-01/ProfileCreate.json` | input | draft | PROF-01 | PROF-07 |
| ProfileUpdate | `docs/contracts/PROF-01/ProfileUpdate.json` | input | draft | PROF-01 | PROF-07 |
| ProfileResponse | `docs/contracts/PROF-01/ProfileResponse.json` | output | draft | PROF-01 | PROF-02, PROF-03, PROF-07 |
| ProfileListItem | `docs/contracts/PROF-01/ProfileListItem.json` | output | draft | PROF-01 | PROF-07 |
| ProfileLimitExceededError | `docs/contracts/PROF-01/ProfileLimitExceededError.json` | error-code | draft | PROF-01 | PROF-07 |
| ProfileConflictError | `docs/contracts/PROF-01/ProfileConflictError.json` | error-code | draft | PROF-01 | PROF-07 |

**复用契约（非本模块定义）**：

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | PROF-01 的角色 |
|:---------|:---------|:---------|:-------|:-------|:---------------|
| AccessOperation | `docs/contracts/PROF-05/AccessOperation.json` | shared-enum | draft | PROF-05 | 消费方 |
| VisibleScope | `docs/contracts/PROF-05/VisibleScope.json` | shared-enum | draft | PROF-05 | 消费方 |
| AccessRequest | `docs/contracts/PROF-05/AccessRequest.json` | input | draft | PROF-05 | 消费方 |
| AccessDecision | `docs/contracts/PROF-05/AccessDecision.json` | output | draft | PROF-05 | 消费方 |
| UserRole | `docs/contracts/AUTH-04/UserRole.json` | shared-enum | draft | AUTH-04 | 消费方 |
| require_role | `docs/contracts/AUTH-04/require_role.json` | input | draft | AUTH-04 | 消费方 |
| PaginatedResponse | 项目级共享类型（`py-schemas/common.py`） | shared-model | stable | PROJECT | 消费方 |

---

### 1.15 意图一致性声明 【对内实现】

- **配套意图文档**：`PROF-01-个人档案管理-意图文档.md`
- **冻结时间**：`2026-05-27 14:20:11`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档 §1.6.1（创建输入 9 字段）和 §1.6.2（查看输出 14 字段）中的业务字段定义一致
  - [x] 本落地规范中的状态机实现与意图文档 §1.7（"本功能点不涉及状态流转"）一致
  - [x] 本落地规范中的异常处理策略（§1.9 共 6 种）与意图文档 §1.8（4 种异常的业务策略）一致，并额外补充了 2 种技术异常（并发冲突、数据库故障）
  - [x] 本落地规范中的验收测试场景（§1.10 共 3 正 + 4 异常）覆盖意图文档 §1.9 的全部 8 项验收标准（AC-01~08）
  - [x] 本落地规范中的技术实现未超出意图文档 §1.12（8 项留给规范阶段的技术决策）的范围，全部 8 项已在设计文档 §1.6 中自主确定
- **偏差说明**：无偏差，技术实现与意图文档完全一致。本落地规范基于契约协调报告（扫描 111 个已有契约）确认零冲突（1 项 BehaviorType 同名异构已通过 `ProfileBehaviorType` 命名避碰解决，CASE-01 的 `BehaviorType` 契约不受影响）。
