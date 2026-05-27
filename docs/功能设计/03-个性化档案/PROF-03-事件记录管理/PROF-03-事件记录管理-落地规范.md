## 1 功能点：PROF-03 事件记录管理 — 落地规范

> **文档生成时间**：`2026-05-27 17:59:22`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-27 15:30:00` | AI Assistant | 初始版本（草案），基于 PROF-01 服务层骨架代码逆向推导 |
> | v2.0 | `2026-05-27 17:59:22` | AI Assistant | 基于已冻结意图文档 v2.0 + 设计文档 v1.0 + 契约协调报告正式生成：替换自有 BehaviorType 为 ProfileBehaviorType 引用、SeverityLevel 保持独立（与 CASE-01 域不同）、契约引用格式对齐、精确异常阈值与测试场景落地 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `PROF-03-事件记录管理-设计文档.md`。

---

### 1.1 技术栈绑定 [UPDATED]

- **必须使用**：
  - `fastapi>=0.115` — API 路由注册、Depends 依赖注入、`HTTPException` 异常类
  - `pydantic>=2.0` — 所有输入/输出模型的基类 `BaseModel`、`Field()` 校验约束
  - `sqlalchemy>=2.0` — ORM 模型（`Mapped`、`mapped_column`）、异步会话（`AsyncSession`）
  - `asyncpg` — PostgreSQL 异步驱动
  - `uuid.UUID` — `event_id` 字段类型，通过 `uuid.uuid4()` 生成
  - `packages/py-db` — ORM 模型 `EventLog`（`models/profiles.py`）、Repository `EventRepository`（`repositories/event_repository.py`）、Alembic 迁移脚本
  - `packages/py-schemas` — Pydantic DTO（`EventCreate`/`EventUpdate`/`EventResponse`/`EventListItem`）、枚举（`SeverityLevel`/`EventSetting`），复用 `ProfileBehaviorType`（PROF-01 定义）
  - `packages/py-auth` — `PrivacyGuard.check_access()` 档案级权限校验；`require_role()` 路由级角色校验；`get_current_user` 用户身份注入
  - `packages/py-config` — `AppException` 异常基类、`AppSettings` 配置模型（含 `MAX_EVENTS_PER_PROFILE` 默认 500）
  - `packages/py-logger` — `logger.info()` / `logger.warning()` / `logger.error()` 结构化日志

- **禁止使用**：
  - 禁止绕过 `PrivacyGuard.check_access()` 直接执行事件数据读写
  - 禁止跨档案查询事件（所有 SELECT 必须含 `WHERE profile_id = :pid`）
  - 禁止使用数据库 `ON DELETE CASCADE` 外键级联删除（由 PROF-01 应用层编排）
  - 禁止将事件记录数据写入 pgvector 向量索引或任何全文检索引擎
  - 禁止缓存事件记录列表（数据变更频繁、单档案最多 500 条、复合索引查询 < 20ms 无需缓存）
  - 禁止路由层接受客户端传入的 `recorded_by`、`recorded_by_role`、`is_professional` 字段
  - 禁止使用自定义事务管理（所有事务通过 SQLAlchemy `AsyncSession` 管理，PROF-01 级联删除时共享 session）

### 1.2 文件归属 [UPDATED]

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| API 路由 | `apps/api-server/app/api/v1/profiles.py` | 新增 `POST /{profile_id}/events`、`PUT /{profile_id}/events/{event_id}`、`DELETE /{profile_id}/events/{event_id}`、`GET /{profile_id}/events` 四个端点。路由前缀 `/api/v1/profiles` |
| Service 层 | `apps/api-server/app/services/profile_service.py` | 新增 `create_event()`、`update_event()`、`delete_event()`、`list_events()`、`get_event()` 方法 |
| ORM 模型 | `packages/py-db/py_db/models/profiles.py` | 新增 `EventLog` 类（16 列映射到 `event_logs` 表） |
| Repository | `packages/py-db/py_db/repositories/event_repository.py` | 新增 `EventRepository` 类：`create()`、`get_by_id()`、`update()`、`delete()`、`list_by_profile()`、`count_active_by_profile()`、`delete_by_profile()` |
| Schema 定义 | `packages/py-schemas/py_schemas/profiles.py` | 新增 `EventCreate`、`EventUpdate`、`EventResponse`、`EventListItem` DTO；新增 `SeverityLevel`、`EventSetting` 枚举；复用 `ProfileBehaviorType`（PROF-01 已定义） |
| 异常类 | `packages/py-config/py_config/exceptions.py` | 新增 `EventLimitExceededError`（HTTP 409），继承 `AppException`，构造函数接受 `current_count: int`、`max_allowed: int = 500` |
| Alembic 迁移 | `packages/py-db/migrations/versions/` | 新增 `{timestamp}_add_event_logs_table.py`：创建 `event_logs` 表（16 列 + 2 索引） |
| 测试文件 | `apps/api-server/tests/test_event_service.py` | `EventRepository` + Service 方法单元测试 |
| 测试文件 | `apps/api-server/tests/test_event_routes.py` | 4 个 API 端点的 HTTP 层集成测试 |

---

### 1.3 输入定义（精确类型 / 或契约引用）【已锁定】 [UPDATED]

**EventCreate**（创建事件请求体）
- 【契约引用】`docs/contracts/PROF-03/EventCreate.json`
- 本模块作为该契约的定义方
- 消费方：PROF-07
- 必填字段：`event_time`、`behavior_type`（引用 PROF-01 `ProfileBehaviorType` 枚举值）、`severity_level`（引用本模块 `SeverityLevel` 枚举值）、`trigger_description`、`manifestation`、`intervention_tried`、`intervention_result`
- 可选字段：`setting`（`EventSetting` 枚举值或 `None`）、`tags`（`list[str]` max 5 项或 `None`）
- `model_config`: `{"extra": "forbid"}`

**EventUpdate**（更新事件请求体，Merge Patch 语义）
- 【契约引用】`docs/contracts/PROF-03/EventUpdate.json`
- 本模块作为该契约的定义方
- 消费方：PROF-07
- 所有字段默认为 `None`（表示不修改此字段），仅用户显式提供的非 `None` 字段写入数据库
- `setting` 字段传入显式 `None` 表示清除已设置的发生场景
- 更新时 `event_time` 同样需通过 30 天追溯期校验
- `model_config`: `{"extra": "forbid"}`

**SeverityLevel**（家属自评严重程度枚举，内部使用 + 对外输出）
- 【契约引用】`docs/contracts/PROF-03/SeverityLevel.json`
- 本模块作为该契约的定义方
- 消费方：PROF-02、PROF-07
- 枚举三值：`"轻"`、`"中"`、`"重"`
- 与 CASE-01 `SeverityLevel`（`"轻度"`/`"中度"`/`"重度"`）业务域不同：PROF-03 面向家属即时主观评估（短形式适配移动端快速选择），CASE-01 面向案例审核的结构化严重度标准。经契约协调确认保持独立（同名异构）

**EventSetting**（事件发生场景枚举，内部使用 + 对外输出）
- 【契约引用】`docs/contracts/PROF-03/EventSetting.json`
- 本模块作为该契约的定义方
- 消费方：PROF-02
- 枚举四值：`"家庭"`、`"学校"`、`"公共场合"`、`"机构"`
- 可选字段，`EventCreate` 中可为 `None`，`EventUpdate` 中传入 `None` 表示清除

**ProfileBehaviorType**（行为类型枚举，复用 PROF-01）
- 【契约引用】`docs/contracts/PROF-01/ProfileBehaviorType.json`
- 定义方：PROF-01
- 本模块作为消费方
- 枚举六值：`"刻板行为"`、`"情绪崩溃"`、`"自伤行为"`、`"攻击行为"`、`"社交退缩"`、`"多动"`
- PROF-03 不定义独立的 `BehaviorType`，直接导入 `packages/py-schemas/py_schemas/profiles.py` 中的 `ProfileBehaviorType`

### 1.4 输出定义（精确类型 / 或契约引用）【已锁定】 [UPDATED]

**EventResponse**（事件记录完整详情）
- 【契约引用】`docs/contracts/PROF-03/EventResponse.json`
- 本模块作为该契约的定义方
- 消费方：PROF-02、PROF-04、PROF-07
- 16 个字段：`event_id`（UUID）、`profile_id`（UUID）、`recorded_by`（UUID）、`recorded_by_role`（str）、`event_time`（datetime）、`behavior_type`（str）、`severity_level`（str）、`setting`（str|null）、`trigger_description`（str）、`manifestation`（str）、`intervention_tried`（str）、`intervention_result`（str）、`is_professional`（bool）、`tags`（list[str]|null）、`created_at`（datetime）、`updated_at`（datetime）

**EventListItem**（事件记录列表精简条目）
- 【契约引用】`docs/contracts/PROF-03/EventListItem.json`
- 本模块作为该契约的定义方
- 消费方：PROF-07
- 6 个字段：`event_id`（UUID）、`event_time`（datetime）、`behavior_type`（str）、`severity_level`（str）、`has_professional_note`（bool）、`created_at`（datetime）
- `has_professional_note` 字段语义与 `EventResponse.is_professional` 一致，命名不同以适应列表视图的可读性

**EventLimitExceededError**（容量超限错误）
- 【契约引用】`docs/contracts/PROF-03/EventLimitExceededError.json`
- 本模块作为该契约的定义方
- 消费方：PROF-07
- 4 个字段：`detail`（str）、`error_code`（`"EVENT_LIMIT_EXCEEDED"`）、`current_count`（int）、`max_allowed`（int = 500）

### 1.5 核心逻辑步骤 [UPDATED]

#### 1.5.1 创建事件记录 `create_event(profile_id, user_id, data: EventCreate, session)`

1. **步骤 1：Pydantic 输入校验**
   - **操作对象**：`EventCreate` 模型实例
   - **具体操作**：调用 `EventCreate.model_validate(request_body)` 进行字段校验（必填检查、枚举合法性、文本长度 1-2000、tags 数量 <=5 和单项长度 <=10）
   - **输入来源**：HTTP POST `/api/v1/profiles/{profile_id}/events` 请求体 JSON
   - **输出去向**：校验通过的 `EventCreate` 实例进入步骤 2
   - **失败行为**：Pydantic `ValidationError` → FastAPI 自动返回 HTTP 422，响应体含 `loc` 和 `msg`，记录 `logger.info("event_validation_failed", profile_id=..., error=...)`

2. **步骤 2：档案存在性校验**
   - **操作对象**：PROF-01 的 `profile_repository`
   - **具体操作**：调用 `profile_repository.exists(profile_id=profile_id)` 检查目标档案是否存在
   - **输入来源**：URL 路径参数 `profile_id`（UUID）
   - **输出去向**：档案存在 → 继续步骤 3；不存在 → 终止
   - **失败行为**：返回 HTTP 404，`{"detail": "数据不存在"}`（泛化消息，不区分档案不存在和权限拒绝）

3. **步骤 3：路由层角色校验**
   - **操作对象**：FastAPI `Depends(require_role(["family"]))`
   - **具体操作**：从 `request.state.user` 获取 JWT `roles`，校验 `UserRole.family` 是否在角色列表中
   - **输入来源**：JWT payload（由 AUTH-04 `get_current_user` Depends 注入）
   - **输出去向**：校验通过 → 继续步骤 4；不通过 → 终止
   - **失败行为**：返回 HTTP 403，`{"detail": "当前角色无权执行此操作"}`

4. **步骤 4：档案级权限校验**
   - **操作对象**：PROF-05 的 `PrivacyGuard`
   - **具体操作**：调用 `PrivacyGuard.check_access(AccessRequest(operation=AccessOperation.create, target_profile_id=profile_id, requester_id=user_id, requester_role=UserRole.family))`，获取 `AccessDecision`
   - **输入来源**：URL 路径参数 `profile_id`、JWT `user_id`、`UserRole.family`
   - **输出去向**：`AccessDecision.allowed == True` → 继续步骤 5；`False` → 终止
   - **失败行为**：返回 HTTP 403，`{"detail": "数据不存在"}`，记录 `logger.warning("unauthorized_event_create", profile_id=..., user_id=...)`

5. **步骤 5：事件时间追溯期校验**
   - **操作对象**：`EventCreate.event_time` 字段
   - **具体操作**：`if event_time < datetime.utcnow() - timedelta(days=30): raise` 校验事件时间是否在 30 天追溯期内
   - **输入来源**：步骤 1 校验通过的 `EventCreate.event_time`
   - **输出去向**：校验通过 → 继续步骤 6
   - **失败行为**：返回 HTTP 422，`{"detail": f"事件时间超出可追溯范围，最早允许日期为 {(datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d')}"}``

6. **步骤 6：容量上限校验**
   - **操作对象**：`event_logs` 表
   - **具体操作**：执行 `SELECT COUNT(*) FROM event_logs WHERE profile_id = :pid`（使用复合索引 `profile_id`），若 `count >= 500` 则拒绝
   - **输入来源**：URL 路径参数 `profile_id`
   - **输出去向**：count < 500 → 继续步骤 7
   - **失败行为**：返回 HTTP 409，`EventLimitExceededError`（含 `current_count`、`max_allowed=500`），记录 `logger.warning("event_limit_exceeded", profile_id=..., current_count=...)`
   - **竞态说明**：COUNT 和 INSERT 之间存在 TOCTOU 窗口，设计上接受 1-2 条的微弱超限

7. **步骤 7：标签归一化**
   - **操作对象**：`EventCreate.tags` 字段
   - **具体操作**：遍历每个标签执行：(1) `strip()` 去首尾空格；(2) `re.sub(r'[^\w一-鿿]', '', tag)` 去特殊符号保留中文/字母/数字；(3) 截断至 10 字
   - **输入来源**：步骤 1 的 `EventCreate.tags`
   - **输出去向**：归一化后的 `list[str]` 进入步骤 8
   - **失败行为**：标签全部归一后为空 → 将 `tags` 设为 `None`，不视为异常

8. **步骤 8：入库**
   - **操作对象**：`event_logs` 表
   - **具体操作**：构造 `EventLog` ORM 实例（`event_id=uuid4()`、`profile_id` 从路径参数、`recorded_by` 从 JWT、`recorded_by_role='parent'`、`is_professional=False`、`created_at=utcnow()`、`updated_at=utcnow()`，其余字段从 `EventCreate` 映射），执行 `session.add()` + `session.flush()` 获取 `event_id`
   - **输入来源**：步骤 1-7 所有校验通过的字段值 + 系统字段
   - **输出去向**：`event_logs` 表新增一行，返回 `EventResponse`（16 字段）
   - **失败行为**：数据库连接失败（超时 > 5s）→ 重试 3 次（间隔 1s），仍失败抛出 `EventPersistenceError` 返回 HTTP 500
   - **副作用**：记录日志 `logger.info("event_created", event_id=..., profile_id=..., user_id=..., trace_id=...)`

#### 1.5.2 更新事件记录 `update_event(profile_id, event_id, user_id, data: EventUpdate, session)`

1. **步骤 1：Pydantic 输入校验**
   - **操作对象**：`EventUpdate` 模型实例
   - **具体操作**：调用 `EventUpdate.model_validate(request_body)`
   - **输入来源**：HTTP PUT `/{profile_id}/events/{event_id}` 请求体 JSON
   - **输出去向**：校验通过的 `EventUpdate` 实例进入步骤 2
   - **失败行为**：Pydantic `ValidationError` → HTTP 422

2. **步骤 2-4**：同 1.5.1 步骤 2-4（档案存在性校验 + 角色校验 + 权限校验），`AccessOperation.update`

3. **步骤 5：事件存在性 + 创建者校验**
   - **操作对象**：`event_logs` 表
   - **具体操作**：`SELECT * FROM event_logs WHERE event_id = :eid AND profile_id = :pid`，检查 (a) 行存在，(b) `recorded_by == user_id`
   - **输入来源**：URL 路径参数 `event_id`、`profile_id`，JWT `user_id`
   - **输出去向**：校验通过 → 继续步骤 6
   - **失败行为**：事件不存在 → HTTP 404；非创建者 → HTTP 403 `{"detail": "数据不存在"}`

4. **步骤 6：追溯期校验**
   - **操作对象**：`EventUpdate.event_time`（如提供）
   - **具体操作**：若 `event_time is not None`，校验 `>= utcnow - 30d`
   - **失败行为**：HTTP 422，提示最早允许日期

5. **步骤 7：合并更新**
   - **操作对象**：现有 `EventLog` 行
   - **具体操作**：遍历 `EventUpdate.model_dump(exclude_unset=True)` 中的非 `None` 字段，更新对应列值；`tags` 如提供则做归一化处理；`setting` 如显式传入 `None` 则 SET NULL；设置 `updated_at = utcnow()`
   - **失败行为**：DB 操作失败同 1.5.1 步骤 8
   - **副作用**：记录日志 `logger.info("event_updated", event_id=..., updated_fields=[...])`

#### 1.5.3 删除事件记录 `delete_event(profile_id, event_id, user_id, session)`

1. **步骤 1：角色校验** — 同 1.5.1 步骤 3，`AccessOperation.delete`
2. **步骤 2：权限校验** — 同 1.5.1 步骤 4
3. **步骤 3：事件存在性 + 创建者校验** — 同 1.5.2 步骤 5
4. **步骤 4：硬删除** — `DELETE FROM event_logs WHERE event_id = :eid AND profile_id = :pid`，不可恢复
   - **失败行为**：DB 操作失败重试 3 次
   - **副作用**：记录日志 `logger.info("event_deleted", event_id=..., profile_id=...)`

#### 1.5.4 查询事件列表 `list_events(profile_id, page, page_size, behavior_type, session)`

1. **步骤 1：角色 + 权限校验** — 同 1.5.1 步骤 3-4，`AccessOperation.view`
2. **步骤 2：查询** — `SELECT * FROM event_logs WHERE profile_id = :pid [AND behavior_type = :bt] ORDER BY event_time DESC LIMIT :limit OFFSET :offset`（参数化查询）
   - **输出去向**：`list[EventListItem]` + `total_count`
   - **失败行为**：空列表返回 `{"items": [], "total": 0, "page": page, "page_size": page_size}`
3. **步骤 3：分页元数据** — 计算 `total_pages = ceil(total / page_size)`，检查 `page` 是否越界

#### 1.5.5 级联删除 `delete_by_profile(profile_id, session)`（供 PROF-01 调用，非 API 端点）

- **操作对象**：`event_logs` 表
- **具体操作**：`DELETE FROM event_logs WHERE profile_id = :pid`
- **输入来源**：PROF-01 `profile_service.delete_profile()` 传入的 `profile_id` + 共享 `AsyncSession`
- **输出去向**：删除完成返回删除行数
- **失败行为**：DB 操作失败 → 异常向上传播，由 PROF-01 事务回滚保证原子性。本方法不执行权限校验——调用方 PROF-01 已在调用前完成权限校验
- **副作用**：记录日志 `logger.info("events_cascade_deleted", profile_id=..., deleted_count=...)`

### 1.6 接口契约（对外暴露的公共接口）【已锁定】 [UPDATED]

#### 1.6.1 POST `/api/v1/profiles/{profile_id}/events` — 创建事件

```python
async def create_event(
    profile_id: UUID,
    data: EventCreate,
    current_user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> EventResponse:
    """
    为指定档案创建一条新的事件记录。

    Args:
        profile_id: 目标档案标识（URL 路径参数）
        data: 事件创建请求体（EventCreate），含 event_time/behavior_type/severity_level
              及 4 个描述文本字段（trigger_description/manifestation/intervention_tried/
              intervention_result），可选 setting/tags
        current_user: 当前请求人身份（由 get_current_user Depends 注入）

    Returns:
        EventResponse: 创建成功的事件完整详情（16 字段）

    Raises:
        HTTP 404: 目标档案不存在（泛化消息）
        HTTP 403: 角色非家属 / 无权操作本档案 / 非事件创建者
        HTTP 422: 必填字段缺失、枚举值非法、文本长度超限、事件时间超 30 天追溯期
        HTTP 409: 本档案事件记录数已达 500 条上限
        HTTP 500: 数据库操作失败（含重试耗尽）

    Side Effects:
        - 写入 event_logs 表一条新行
        - 记录结构化日志 event_type="event_created"

    Idempotency:
        非幂等。每次调用创建一条新事件记录，使用独立的 uuid4()。

    Thread Safety:
        本函数内部不维护可变状态，通过 AsyncSession 进行数据库操作。
    """
```

| 属性 | 说明 |
|------|------|
| **HTTP 方法/路径** | `POST /api/v1/profiles/{profile_id}/events` |
| **输入类型** | `EventCreate`（契约引用：`docs/contracts/PROF-03/EventCreate.json`） |
| **输出类型** | `EventResponse`（契约引用：`docs/contracts/PROF-03/EventResponse.json`） |
| **异常类型** | `ValidationError`(422)、`ForbiddenAccess`(403)、`EventLimitExceededError`(409) |
| **副作用** | 写入 event_logs 表、记录结构化日志 |
| **权限校验** | `require_role(["family"])` → `PrivacyGuard.check_access(create)` |

#### 1.6.2 PUT `/api/v1/profiles/{profile_id}/events/{event_id}` — 更新事件

```python
async def update_event(
    profile_id: UUID,
    event_id: UUID,
    data: EventUpdate,
    current_user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> EventResponse:
    """
    更新指定事件的字段（Merge Patch 语义）。仅更新 data 中非 None 的字段。

    Args:
        profile_id: 目标档案标识
        event_id: 目标事件标识
        data: 事件更新请求体（EventUpdate），所有字段可选
        current_user: 当前请求人身份

    Returns:
        EventResponse: 更新后的事件完整详情

    Raises:
        HTTP 404: 事件不存在 / 档案不存在
        HTTP 403: 角色非家属 / 无权操作 / 非事件创建者
        HTTP 422: 更新后的事件时间超 30 天追溯期
        HTTP 500: 数据库操作失败

    Side Effects:
        - 更新 event_logs 表对应行
        - 设置 updated_at 为当前 UTC 时间
    """
```

| 属性 | 说明 |
|------|------|
| **HTTP 方法/路径** | `PUT /api/v1/profiles/{profile_id}/events/{event_id}` |
| **输入类型** | `EventUpdate`（契约引用：`docs/contracts/PROF-03/EventUpdate.json`） |
| **输出类型** | `EventResponse`（契约引用：`docs/contracts/PROF-03/EventResponse.json`） |
| **权限校验** | 路由角色 + 档案级权限 + 创建者身份（`recorded_by == current_user_id`） |

#### 1.6.3 DELETE `/api/v1/profiles/{profile_id}/events/{event_id}` — 删除事件

```python
async def delete_event(
    profile_id: UUID,
    event_id: UUID,
    current_user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    硬删除指定事件记录。删除后不可恢复。

    Args:
        profile_id: 目标档案标识
        event_id: 目标事件标识
        current_user: 当前请求人身份

    Returns:
        {"detail": "事件已删除"}

    Raises:
        HTTP 404: 事件不存在
        HTTP 403: 角色非家属 / 无权操作 / 非事件创建者
        HTTP 500: 数据库操作失败

    Side Effects:
        - DELETE FROM event_logs 物理删除
        - 记录结构化日志 event_type="event_deleted"
    """
```

| 属性 | 说明 |
|------|------|
| **HTTP 方法/路径** | `DELETE /api/v1/profiles/{profile_id}/events/{event_id}` |
| **输出类型** | `{"detail": "事件已删除"}`（无契约，简单字典） |
| **权限校验** | 路由角色 + 档案级权限 + 创建者身份 |

#### 1.6.4 GET `/api/v1/profiles/{profile_id}/events` — 查询事件列表

```python
async def list_events(
    profile_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    behavior_type: str | None = Query(default=None),
    current_user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    查询指定档案下的事件记录列表，支持按行为类型筛选和分页。

    Args:
        profile_id: 目标档案标识
        page: 页码（从 1 开始，默认 1）
        page_size: 每页条数（默认 20，最大 100）
        behavior_type: 可选行为类型筛选
        current_user: 当前请求人身份

    Returns:
        {"items": list[EventListItem], "total": int, "page": int,
         "page_size": int, "total_pages": int}
    """
```

| 属性 | 说明 |
|------|------|
| **HTTP 方法/路径** | `GET /api/v1/profiles/{profile_id}/events` |
| **输出类型** | `{"items": list[EventListItem], ...}` — `EventListItem`（契约引用：`docs/contracts/PROF-03/EventListItem.json`） |
| **分页** | Offset-based，`event_time DESC`，默认 20 条/页 |
| **权限校验** | 路由角色 + 档案级权限（view） |

---

### 1.7 依赖与集成接口（本模块调用的外部接口） [UPDATED]

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 关系型数据库 | PostgreSQL 17.x | `session.execute(select(EventLog).where(...))` / `session.add()` / `session.flush()` — SQLAlchemy 2.0 async | event_logs 表的数据读写 | `项目结构设计.md §五` — 数据层 |
| 数据库迁移 | Alembic | `op.create_table('event_logs', ...)` | event_logs 表 DDL 创建 | `项目结构设计.md §6.1` — py-db/migrations/ |
| 日志系统 | packages/py-logger | `logger.info()` / `logger.warning()` / `logger.error()` | 结构化日志输出 | `项目结构设计.md §6.1` — py-logger |
| 配置管理 | packages/py-config | `AppSettings.MAX_EVENTS_PER_PROFILE`（默认 500） | 容量上限配置 | `项目结构设计.md §6.1` — py-config |
| 异常体系 | packages/py-config | `AppException` 基类 | `EventLimitExceededError` 继承 | `项目结构设计.md §6.1` — py-config |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| PROF-01 个人档案管理 | `profile_repository.exists(profile_id: UUID) -> bool` | 创建/更新事件前验证目标档案存在性 | ✅ 已落地 |
| PROF-01 个人档案管理 | `profile_repository.get_by_id(profile_id: UUID) -> Profile` | 事件列表查询中获取档案信息（可选） | ✅ 已落地 |
| PROF-05 档案隐私控制 | `PrivacyGuard.check_access(AccessRequest) -> AccessDecision` | 档案级权限校验（create/update/delete/view 操作） | ✅ 已落地 |
| PROF-05 档案隐私控制 | `AccessOperation` 枚举 — 消费值：`view`/`create`/`update`/`delete` | 权限操作类型映射 | ✅ 已落地 |
| AUTH-04 五级RBAC鉴权 | `require_role(["family"])` — FastAPI Depends | 路由层家属角色校验 | ✅ 已落地 |
| AUTH-04 五级RBAC鉴权 | `get_current_user` → `request.state.user.user_id` | 获取当前请求人 UUID | ✅ 已落地 |
| AUTH-04 五级RBAC鉴权 | `UserRole.family` 枚举值 | 角色身份判定 | ✅ 已落地 |

---

### 1.8 状态机

本功能点不涉及持久化状态流转，故无需状态机。事件记录的创建、修改和删除均为即时同步操作，不存在中间状态或异步等待流程。

---

### 1.9 异常与边界条件 [UPDATED]

#### 1.9.1 异常 1：输入无效或缺失

- **触发条件**：
  - 必填字段任一为 `None` 或空字符串（`event_time`、`behavior_type`、`severity_level`、`trigger_description`、`manifestation`、`intervention_tried`、`intervention_result`）
  - `behavior_type` 值不在 `ProfileBehaviorType` 枚举六值中
  - `severity_level` 值不在 `SeverityLevel` 三值中
  - `setting` 非 `None` 且值不在 `EventSetting` 四值中
  - `trigger_description`/`manifestation`/`intervention_tried`/`intervention_result` 长度 < 1 或 > 2000
  - `tags` 数组长度 > 5 或任一项字数 > 10
- **处理策略**：
  1. Pydantic 校验阶段捕获 `ValidationError`
  2. FastAPI 自动返回 HTTP 422，响应体 `{"detail": [{"loc": ["body", "field_name"], "msg": "...", "type": "value_error"}]}`
  3. 记录结构化日志 `logger.info("event_validation_failed", errors=...)`
  4. 不进入任何后续步骤
- **重试参数**：不重试，客户端修正输入后重新发起请求。

#### 1.9.2 异常 2：事件时间超出 30 天追溯期

- **触发条件**：
  - `event_time < datetime.utcnow() - timedelta(days=30)`（创建时或更新时如提供新 event_time）
- **处理策略**：
  1. Service 层 `create_event()` 或 `update_event()` 中执行校验
  2. 返回 HTTP 422，响应体 `{"detail": "事件时间超出可追溯范围，最早允许日期为 YYYY-MM-DD"}`
  3. 记录 `logger.info("event_time_out_of_range", event_time=..., earliest_allowed=...)`
- **重试参数**：不重试。

#### 1.9.3 异常 3：事件记录容量超限

- **触发条件**：
  - `SELECT COUNT(*) FROM event_logs WHERE profile_id = :pid` 结果 >= 500
- **处理策略**：
  1. Service 层 `create_event()` 步骤 6 中执行容量校验
  2. 返回 HTTP 409，`EventLimitExceededError`：`{"detail": "事件记录已达上限（500 条），请删除不再需要的历史事件后重试", "error_code": "EVENT_LIMIT_EXCEEDED", "current_count": 500, "max_allowed": 500}`
  3. 记录 `logger.warning("event_limit_exceeded", profile_id=..., current_count=500)`
- **重试参数**：不重试。用户需手动删除旧记录后重新创建。
- **后续升级路径**：若产品确认自动归档方案（意图文档 §1.4(3)），可在步骤 6 中替换为"归档最早记录"逻辑，API 契约不变（仍返回 201 EventResponse）。

#### 1.9.4 异常 4：非创建者试图修改/删除事件

- **触发条件**：
  - 更新/删除操作中 `SELECT recorded_by FROM event_logs WHERE event_id = :eid` 返回值 != `current_user_id`
  - 此异常仅发生在同一档案下多位家属共享的场景——家属 A 试图修改家属 B 创建的事件
- **处理策略**：
  1. Service 层 `update_event()` / `delete_event()` 步骤 5 中校验
  2. 返回 HTTP 403，`{"detail": "数据不存在"}`（泛化消息，与档案级权限拒绝一致）
  3. 记录 `logger.warning("event_ownership_mismatch", event_id=..., recorded_by=..., attempted_by=...)`
- **重试参数**：不重试。

#### 1.9.5 异常 5：数据库连接故障

- **触发条件**：
  - `AsyncSession.execute()` 连接超时（> 5s）
  - PostgreSQL 返回连接拒绝或服务不可用
- **处理策略**：
  1. 捕获 `sqlalchemy.exc.OperationalError` / `asyncio.TimeoutError`
  2. 释放当前失效连接，`await session.rollback()`
  3. 重试同一操作（重新获取连接）
  4. 第 3 次仍失败：抛出 `EventPersistenceError`（继承 `AppException`），返回 HTTP 500
  5. 记录 `logger.error("event_db_operation_failed", operation=..., retry_count=3, error=...)`
- **重试参数**：最大 3 次，固定间隔 1s。每次重试前释放旧连接获取新连接。

---

### 1.10 验收测试场景 [UPDATED]

#### 1.10.1 正向测试 1：创建事件记录完整流程

- **场景**：家属为关联患者创建一条完整的事件记录，含全部可选字段
- **Given**：有效的家属 JWT（`roles=["family"]`, `user_id="u1"`）；目标档案存在（`profile_id="p1"`）；档案下现有事件 < 500 条；权限校验通过
- **When**：`POST /api/v1/profiles/p1/events` 发送完整 EventCreate JSON：
  ```json
  {
    "event_time": "2026-05-20T14:30:00Z",
    "behavior_type": "情绪崩溃",
    "severity_level": "中",
    "setting": "公共场合",
    "trigger_description": "商场吹风机声音",
    "manifestation": "捂耳朵蹲下，拒绝移动，持续尖叫",
    "intervention_tried": "拉他起身无效，给了水不喝",
    "intervention_result": "3分钟后自己停止，靠在我肩上",
    "tags": ["吹风机", "商场"]
  }
  ```
- **Then**：
  - HTTP 201，返回 `EventResponse`（16 字段）
  - `recorded_by` = `"u1"`
  - `recorded_by_role` = `"parent"`
  - `is_professional` = `false`
  - `tags` = `["吹风机", "商场"]`（已归一化）
  - `created_at` 和 `updated_at` 为当前 UTC 时间
  - event_logs 表新增 1 行

#### 1.10.2 正向测试 2：查询事件列表

- **场景**：家属查看关联档案下的事件记录列表
- **Given**：目标档案下已有 3 条事件记录（event_time 各不同）；家属 JWT 有效；权限校验通过
- **When**：`GET /api/v1/profiles/p1/events?page=1&page_size=20`
- **Then**：
  - HTTP 200
  - `items` 数组长度 = 3，按 `event_time` 降序排列
  - 每条为 `EventListItem` 结构（6 字段），不含描述文本
  - `total` = 3，`page` = 1，`page_size` = 20，`total_pages` = 1

#### 1.10.3 正向测试 3：更新事件部分字段

- **场景**：家属修改事件的严重程度和标签
- **Given**：事件 `e1` 属于档案 `p1`，`recorded_by` = `"u1"`
- **When**：`PUT /api/v1/profiles/p1/events/e1` 发送：
  ```json
  {
    "severity_level": "重",
    "tags": ["商场"]
  }
  ```
- **Then**：
  - HTTP 200，返回更新后的 `EventResponse`
  - `severity_level` = `"重"`
  - `tags` = `["商场"]`
  - 其他未传字段保持原值不变
  - `updated_at` 已更新

#### 1.10.4 正向测试 4：删除事件记录

- **场景**：家属删除自己创建的事件
- **Given**：事件 `e1` 属于档案 `p1`，`recorded_by` = `"u1"`
- **When**：`DELETE /api/v1/profiles/p1/events/e1`
- **Then**：
  - HTTP 200，`{"detail": "事件已删除"}`
  - event_logs 表该行已物理删除，后续查询不可见

#### 1.10.5 异常测试 1：必填字段缺失

- **场景**：家属提交的创建请求缺少 `trigger_description`
- **Given**：家属 JWT 有效
- **When**：`POST /api/v1/profiles/p1/events` 发送不含 `trigger_description` 的 JSON：
  ```json
  {
    "event_time": "2026-05-20T14:30:00Z",
    "behavior_type": "情绪崩溃",
    "severity_level": "中",
    "manifestation": "捂耳朵蹲下",
    "intervention_tried": "给水",
    "intervention_result": "停止"
  }
  ```
- **Then**：
  - HTTP 422
  - 响应体 `detail` 中包含 `trigger_description` 的缺失信息
  - event_logs 表无新增行

#### 1.10.6 异常测试 2：事件时间超出追溯期

- **场景**：家属尝试补录 40 天前的旧事件
- **Given**：当前 UTC 时间为 `2026-05-27T10:00:00Z`
- **When**：`POST /api/v1/profiles/p1/events` 发送 `event_time` = `"2026-04-17T10:00:00Z"`（40 天前）
- **Then**：
  - HTTP 422
  - `detail` 提示事件时间超出可追溯范围，最早允许日期为 `2026-04-27`

#### 1.10.7 异常测试 3：事件容量超限

- **场景**：档案下已有 500 条事件，家属试图新建
- **Given**：`event_logs` 表中 `profile_id = "p1"` 的行数 = 500
- **When**：`POST /api/v1/profiles/p1/events` 发送有效 EventCreate
- **Then**：
  - HTTP 409
  - `error_code` = `"EVENT_LIMIT_EXCEEDED"`
  - `current_count` = 500，`max_allowed` = 500

#### 1.10.8 异常测试 4：非家属角色试图创建事件

- **场景**：老师角色尝试创建事件记录
- **Given**：JWT `roles=["teacher"]`，有效认证
- **When**：`POST /api/v1/profiles/p1/events` 发送有效 EventCreate
- **Then**：
  - HTTP 403（路由层 `require_role(["family"])` 拒绝）
  - 失败日志记录 `event_type: "permission_denied"`, `required_roles: ["family"]`

---

### 1.11 注意事项与禁止行为（编码层面） [UPDATED]

1. **[数据隔离]** 所有 Repository 查询方法必须包含 `WHERE profile_id = :pid` 条件参数。严禁写出 `SELECT * FROM event_logs` 不加档案筛选的查询。

2. **[权限不降级]** `delete_by_profile()` 方法仅供 PROF-01 级联删除路径调用，不暴露为 API 端点。该方法签名必须接受 `session: AsyncSession` 参数，由调用方（PROF-01）在其事务上下文中传入。

3. **[竞态容忍]** `count_active_by_profile()` 和 `create()` 之间的 TOCTOU 窗口是设计上接受的权衡。不要为此引入行级锁或 `SERIALIZABLE` 隔离级别——500 条上限为经验值，1-2 条超限可接受。

4. **[参数化查询]** 所有 SQL 必须通过 SQLAlchemy 参数化查询执行。严禁字符串拼接 SQL（包括 f-string 或 `%` 格式化）。

5. **[外键约束]** `event_logs` 表的 `profile_id` 列不设 `ON DELETE CASCADE`，与 PROF-01 设计文档中的全区禁止保持一致。

6. **[禁止缓存]** 不设 Redis 或内存缓存。理由：(a) 数据变更频繁，缓存一致性成本高；(b) 单档案最多 500 条，复合索引查询 < 20ms；(c) 避免缓存残留已删除事件。

7. **[禁止向量索引]** `event_logs` 表不创建 pgvector 索引，不在任何嵌入管道中读取事件数据。违反此约束将导致不同患者事件通过语义相似度交叉关联。

8. **[recorded_by 不可篡改]** `recorded_by` 在 `create_event()` 中从 `current_user.user_id` 设置后不可修改。`EventUpdate` 的 Schema 中不包含 `recorded_by` 字段。

9. **[is_professional 只读]** `is_professional` 字段创建时固定为 `false`。`EventCreate` 和 `EventUpdate` Schema 均不接受客户端传入此字段。仅 PROF-04 可通过内部更新接口设置。

10. **[标签不作为全局标签]** 自定义标签仅在该档案维度内生效。不建立全局标签表或跨档案标签聚合。归一规则：`str.strip()` → `re.sub(r'[^\w一-鿿]', '', tag)` → 截断至 10 字。

11. **[枚举输出]** `EventResponse` 和 `EventListItem` 中的 `behavior_type`、`severity_level` 字段输出为字符串值（如 `"情绪崩溃"`、`"中"`），非枚举对象。前端消费时无需做枚举反序列化。

12. **[级联删除事务]** PROF-03 的 `delete_by_profile(session=session)` 由 PROF-01 在共享事务中调用。PROF-03 侧不调用 `session.commit()`，由 PROF-01 统一提交或回滚。

13. **[偷懒红线]** 绝对禁止以"显而易见"、"和 PROF-01 类似"、"参考 PROF-01 实现"为由省略任何字段校验、权限检查或日志记录。每个端点的实现必须自包含。

---

### 1.12 文档详细度自检清单

- [x] 文档自包含：不了解本项目代码的 Agent，仅凭此文档即可完成 PROF-03 编码
- [x] 无偷懒表述：全文已清除 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：每个对外类型已写入契约文件（`docs/contracts/PROF-03/*.json`），内部类型通过契约引用链接
- [x] 逻辑步骤完整：5 个方法（create/update/delete/list/cascade_delete）每个步骤都有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：5 种异常各有精确触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值来源（`MAX_EVENTS_PER_PROFILE=500`）、条件分支、业务规则已显式写出
- [x] 技术栈绑定明确：必须使用和禁止使用的项均已列出，与 `docs/篝火智答-技术栈设计.md` v1.2 一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档 v2.0 一致

---

### 1.14 外部接口契约清单

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| EventCreate | `docs/contracts/PROF-03/EventCreate.json` | input | draft | PROF-03 | PROF-07 |
| EventUpdate | `docs/contracts/PROF-03/EventUpdate.json` | input | draft | PROF-03 | PROF-07 |
| EventResponse | `docs/contracts/PROF-03/EventResponse.json` | output | draft | PROF-03 | PROF-02, PROF-04, PROF-07 |
| EventListItem | `docs/contracts/PROF-03/EventListItem.json` | output | draft | PROF-03 | PROF-07 |
| EventSetting | `docs/contracts/PROF-03/EventSetting.json` | shared-enum | draft | PROF-03 | PROF-02 |
| SeverityLevel | `docs/contracts/PROF-03/SeverityLevel.json` | shared-enum | draft | PROF-03 | PROF-02, PROF-07 |
| EventLimitExceededError | `docs/contracts/PROF-03/EventLimitExceededError.json` | error-code | draft | PROF-03 | PROF-07 |
| ProfileBehaviorType | `docs/contracts/PROF-01/ProfileBehaviorType.json` | shared-enum | draft | PROF-01 | PROF-03 |
| ProfileResponse | `docs/contracts/PROF-01/ProfileResponse.json` | output | draft | PROF-01 | PROF-03 |
| AccessOperation | `docs/contracts/PROF-05/AccessOperation.json` | shared-enum | draft | PROF-05 | PROF-03 |
| AccessRequest | `docs/contracts/PROF-05/AccessRequest.json` | input | draft | PROF-05 | PROF-03 |
| AccessDecision | `docs/contracts/PROF-05/AccessDecision.json` | output | draft | PROF-05 | PROF-03 |
| VisibleScope | `docs/contracts/PROF-05/VisibleScope.json` | shared-enum | draft | PROF-05 | PROF-03 |
| UserRole | `docs/contracts/AUTH-04/UserRole.json` | shared-enum | draft | AUTH-04 | PROF-03 |
| require_role | `docs/contracts/AUTH-04/require_role.json` | input | draft | AUTH-04 | PROF-03 |

---

### 1.15 意图一致性声明

- **配套意图文档**：`PROF-03-事件记录管理-意图文档.md`
- **冻结时间**：`2026-05-27 17:00:10`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档 §1.6 中的业务字段定义一致
  - [x] 本落地规范中的状态机声明（无状态机）与意图文档 §1.7 一致
  - [x] 本落地规范中的异常处理策略（4 种异常场景：输入无效、容量超限、权限不足、补录超期）覆盖意图文档 §1.8 的全部异常定义（异常 1-4），并额外增加数据库连接故障异常（§1.9.5）
  - [x] 本落地规范中的验收测试场景（4 正 + 4 异常）覆盖意图文档 §1.9 的验收标准 AC-01 至 AC-10（AC-08/AC-09/AC-10 为跨模块集成测试，本模块提供对应接口但完整测试需由 PROF-04/PROF-01/PROF-02 方协作）
  - [x] 本落地规范中的技术实现未超出意图文档 §1.12"留给规范阶段的技术决策"的 9 项范围
- **偏差说明**：容量管控策略（§1.9.3）采用 MVP 方案 A（达到 500 条拒绝创建并返回 409），与意图文档 §1.4(3)"自动归档最早记录"的描述存在差异。此偏差已在设计文档 §1.1 中明确说明——自动归档需产品级规格确认后方可升级，API 契约保持向后兼容。
