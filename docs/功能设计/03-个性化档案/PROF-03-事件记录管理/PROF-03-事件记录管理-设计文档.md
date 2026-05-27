# 1 功能点：PROF-03 事件记录管理 -- 设计文档（瘦身版）

> **文档生成时间**：`2026-05-27 17:44:47`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-27 17:44:47` | AI Assistant | 初始版本，基于 s06 技术决策报告（23 项自主决策 + 9 项矛盾标记）生成，全部矛盾项采用报告推荐方案 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `PROF-03-事件记录管理-意图文档.md`（已冻结于 2026-05-27 17:00:10）
> - 本模块的精确编码规格见 `PROF-03-事件记录管理-落地规范.md`

### 1.1 技术实现思路

PROF-03 事件记录管理的核心问题是：在以家属为主体的档案数据体系中，如何提供安全、清晰、无歧义的事件 CRUD 能力，同时精确执行三层权限校验、容量管控、追溯期约束这些横切关注点。

**架构定位**：PROF-03 位于项目分层 L4（业务数据层），属于 03-个性化档案分组的数据生产节点。其上游消费 PROF-01（档案存在性验证）和 PROF-05（权限裁决），下游供给 PROF-04（专业评估挂载）、PROF-02（档案驱动检索过滤）和 CSLT-03（个性化上下文注入）。PROF-03 自身不定义权限模型、不执行隐私判定——这些由 PROF-05 在每次 CRUD 操作前裁决。

**三层权限校验流水线**：借鉴 PROF-01 已稳定的三层鉴权模式，PROF-03 的每个事件操作经过：
1. **路由层角色校验** -- `Depends(require_role(["family"]))`。确认操作者身份为家属（AUTH-04 统一角色枚举 `UserRole.family`）。这是粗粒度身份校验，老师/专家在此层即被拒绝。
2. **Service 层档案权限校验** -- 调用 `PrivacyGuard.check_access(AccessRequest)`。确认该家属对该档案有对应操作权限。权限校验返回的 `AccessDecision` 中若 `allowed=False`，抛出 `ForbiddenAccess` 并泛化消息为"数据不存在"（不暴露档案存在性）。
3. **Service 层事件操作者校验** -- 修改/删除操作额外校验 `recorded_by == current_user_id`。即使同档案下的家属通过权限校验，也只有事件创建者本人可修改或删除该事件。此层为 PROF-03 特有——档案管理中存在"多位家属共享同一档案"的场景（意图文档 §1.11.2），不同家属对同一档案下各自创建的事件应有独立操作权。

**选择三层而非两层的原因**：前两层（路由 + 档案）与 PROF-01 模式一致，确保 PROF 域内统一的权限感知。第三层（操作者）是事件记录特有的需求——档案是家属共有的抽象实体，但事件是特定家属个人记录的具象产物。PROF-05 的档案级权限不区分"档案 A 下谁创建的事件"，因此需要 PROF-03 自身在 Service 层做创建者校验。

**数据存储设计**：采用 PostgreSQL event_logs 单表，16 个字段映射意图文档 §1.6.2 全部输出字段。字段设计遵循项目存储惯例：
- 枚举字段（behavior_type、severity_level、setting、recorded_by_role）使用 VARCHAR 存储枚举值的 `name`（如 `"情绪崩溃"`），同时在 Pydantic 层做枚举校验，双重保障。
- 需要自由检索的标签字段（tags）使用 JSONB 数组，利用 GIN 索引支持按标签筛选。选择 JSONB 而非关联表的理由与 PROF-01 的档案标签一致：标签值受限于 5 个/事件且总量可控，JSONB 避免关联表 JOIN，并复用 PROF-01 已成型的 JSONB 标签查询模式。
- 4 个描述文本字段使用 TEXT（不设 DB 长度约束），由 Pydantic `max_length=2000` 在应用层控制。不做全文索引——意图文档 §1.11.6 明确"不做全文检索"。

**容量管控策略（业务矛盾 B-01）**：意图文档 §1.4(3) 描述"超过 500 条自动归档最早记录"，但"自动归档"涉及"哪些字段属于基础元数据"的产品级定义，目前尚无明确规格。技术决策报告推荐 MVP 阶段采用**方案 A：达到 500 条后拒绝创建并返回 409 EventLimitExceededError**，待后续迭代增加自动归档能力。本设计采纳此推荐——创建事件前 `SELECT COUNT(*) FROM event_logs WHERE profile_id = :pid`，若 >= 500 则拒绝。不为此提前实现压缩存储逻辑。

**30 天追溯期校验**：在 Service 层动态校验 `event_time >= utcnow - timedelta(days=30)`。不采用数据库 CHECK 约束——因为 CHECK 约束是静态的（建表时写入），而追溯窗随当前时间滑动。校验位于 Pydantic 校验之后、权限校验之后、实际 INSERT 之前。

**更新语义**：采用合并更新（Merge Patch）。EventUpdate 中所有字段默认为 `None`（表示"不修改此字段"），仅用户显式提供的字段才会写入数据库。当用户将 `setting` 传为 `None` 时表示"清除已设置的发生场景"。此设计与主流 REST PATCH 实践一致。

**删除语义**：硬删除（`DELETE FROM event_logs WHERE event_id = :eid AND profile_id = :pid`）。意图文档明确要求"事件数据不可恢复"。不存在软删除状态标记、"回收站"过渡状态或延迟清理机制。

**级联删除**：档案删除时 PROF-01 通过应用层调用本模块的 `delete_by_profile(profile_id, session=session)` 方法，在同一数据库事务中先删除所有关联事件再删除档案。本模块 `delete_by_profile` 方法不执行权限校验（由 PROF-01 调用方保证调用合法性），不设外键 CASCADE（PROF-01 已约定禁止 DB 层级联删除）。

**BehaviorType 对齐方案（业务矛盾 B-02）**：直接复用 PROF-01 的 `ProfileBehaviorType` 枚举（6 值：刻板行为、情绪崩溃、自伤行为、攻击行为、社交退缩、多动）。PROF-03 不独立定义 `BehaviorType`。技术上，事件记录的 `behavior_type` 字段存储 `ProfileBehaviorType` 的字符串值，Pydantic 校验使用 `ProfileBehaviorType` 枚举（从 `packages/py-schemas/py_schemas/profiles.py` 导入）。PROF-01 的 `ProfileBehaviorType` 契约需在 consumers 中增加 `"PROF-03"`。

**分页与查询**：Offset-based 分页（`OFFSET / LIMIT`），按 `event_time DESC` 排序，默认 20 条/页。支持 `?page=` 和 `?page_size=` 查询参数。不设最大查询深度限制——单档案最多 500 条、扣去历史记录后分页总数受限，性能可控。复合索引 `(profile_id, event_time DESC)` 支撑列表查询。按行为类型筛选通过 WHERE 子句追加 `behavior_type = :bt` 过滤。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：PROF-01-个人档案管理-设计文档.md + 落地规范.md（已冻结）、PROF-05-档案隐私控制-设计文档.md + 落地规范.md（已冻结）、AUTH-04-五级RBAC鉴权-落地规范.md（已冻结）、CSLT-01/02/03-危机分级判定/RAG语义检索/应急方案生成-落地规范.md（已冻结）、KNOW-01-科普内容管理-落地规范.md（已冻结）、CASE-01/04-案例录入管理/案例向量化入库-落地规范.md（已冻结）、OBS-01/04-结构化日志/健康检查-落地规范.md（已冻结）、SEC-01/04/05-传输存储安全/防刷限流/输入校验防护-落地规范.md（已冻结）、DEPLOY-01~05 系列落地规范（已冻结）、AUTH-01~06 系列落地规范（已冻结）、`docs/contracts/PROF-01/ProfileBehaviorType.json` / `ProfileResponse.json`、`docs/contracts/PROF-05/AccessOperation.json` / `AccessRequest.json` / `AccessDecision.json` / `VisibleScope.json`、`docs/contracts/_index.json`、`docs/功能设计/_contracts.md`、`docs/功能设计/功能模块全拆解.md`、`docs/功能设计/模块依赖关系分析.md`。

- **兼容性结论**：
  - **无冲突**：PROF-03 的技术方案与全部 25 份已有规格文档完全兼容。
    - **PROF-01**：PROF-03 通过 `profile_repository.exists(profile_id)` 验证档案存在性，复用 PROF-01 的 Repository 方法而非直接查询 profiles 表。级联删除通过 PROF-03 的 `delete_by_profile()` 事务内调用，与 PROF-01 设计文档中已预留的 `event_service.delete_by_profile()` 骨架一致。`ProfileBehaviorType` 直接复用 PROF-01 枚举定义（已确认 consumers 中增加 PROF-03）。`ProfileResponse` 已在契约索引中注册 PROF-03 为消费者。✅ 无冲突。
    - **PROF-05**：PROF-03 的 CRUD 操作（create/update/delete）与 PROF-05 `AccessOperation` 六值映射准确。PROF-03 已注册为 PROF-05 四份契约（AccessOperation/AccessRequest/AccessDecision/VisibleScope）的消费者。权限校验调用链复用 PROF-01 已验证的 `PrivacyGuard.check_access()` 模式。✅ 无冲突。
    - **AUTH-04**：路由层 `require_role(["family"])` 与 AUTH-04 标准模式一致。JWT payload 角色获取方式复用 `get_current_user` Depends。✅ 无冲突。
    - **CSLT-03**：PROF-03 通过 PROF-02 间接供给 CSLT-03 事件数据作为个性化上下文，PROF-03 自身不感知 CSLT 域的存在。无直接接口耦合。✅ 无冲突。
    - **CASE-01**：CASE-01 已定义 `BehaviorType`（值集 `["自伤","攻击","刻板","逃跑","情绪崩溃","其他"]`）。PROF-03 复用 PROF-01 的 `ProfileBehaviorType`（值集 `["刻板行为","情绪崩溃","自伤行为","攻击行为","社交退缩","多动"]`），与 CASE-01 无命名冲突。已在 s05 阶段的 _sync-issues.md 中记录此风险并确认推荐方案。✅ 无冲突。
    - **零循环依赖**：入度 3（PROF-01 档案存在验证/级联删除触发、PROF-05 权限裁决、AUTH-04 角色校验），出度 3（PROF-04 专业评估挂载、PROF-02 事件数据消费、CSLT-03 个性化上下文注入）。全部为单向依赖，模块依赖关系分析确认零循环依赖。

- **复用的已有设计**：
  - PROF-01 的 `ProfileBehaviorType` 枚举（行为类型字段的定义源）
  - PROF-01 的 `ProfileResponse` 契约（档案存在性验证消费）
  - PROF-01 的 `profile_repository.exists()` 方法（档案存在性校验入口）
  - PROF-05 的 `AccessOperation` 枚举（CRUD 操作类型映射）
  - PROF-05 的 `PrivacyGuard.check_access()`（Service 层档案权限校验）
  - PROF-05 的 `AccessRequest` / `AccessDecision` DTO
  - AUTH-04 的 `require_role(["family"])` Depends（路由级角色校验）
  - AUTH-04 的 `get_current_user` Depends（获取 user_id）
  - AUTH-04 的 `UserRole` 枚举（family 角色标识）
  - OBS-01 的结构化日志体系（`py-logger`）
  - SEC-05 的 Pydantic v2 Schema 校验体系
  - 项目统一异常基类 `AppException`（`packages/py-config/exceptions.py`）
  - DEPLOY-04 的 Alembic 迁移框架
  - DEPLOY-05 的 `AppSettings` 配置模型
  - 项目共享契约 `PROF-05/AccessOperation` / `PROF-05/AccessRequest` / `PROF-05/AccessDecision` / `PROF-01/ProfileResponse`（已在 _index.json 中注册 PROF-03 为消费者）

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|---------|-------------|
| AUTH-04 五级RBAC鉴权 | 上游调用（强） | 路由层：`Depends(require_role(["family"]))` 校验请求人身份为家属。通过 `get_current_user` Depends 从 JWT payload 获取 `user_id`（UUID），注入 `request.state.user` |
| PROF-05 档案隐私控制 | 上游调用（强） | Service 层：每个 CRUD 方法第一步调用 `PrivacyGuard.check_access(AccessRequest(operation=..., target_profile_id=..., requester_id=..., requester_role=UserRole.family))`，返回 `AccessDecision`，若 `allowed=False` 抛出 `ForbiddenAccess`（泛化消息） |
| PROF-01 个人档案管理 | 上游调用（强） | 创建事件前通过 `profile_repository.exists(profile_id)` 验证目标档案存在性。级联删除场景：PROF-01 调用本模块的 `delete_by_profile(profile_id, session)` 方法在共享事务中清理关联事件记录 |
| PostgreSQL 17.x (event_logs 表) | 读写 | 新增 `event_logs` 表（16 列），ORM 模型位于 `packages/py-db/py_db/models/profiles.py`。复合索引 `(profile_id, event_time DESC)` 用于列表查询，单列索引 `profile_id` 用于容量计数。所有查询通过 SQLAlchemy 2.0 async session + 参数化查询 |
| packages/py-db | 框架依赖 | 新增 ORM 模型 `EventLog`（`models/profiles.py`），新增 Repository `event_repository.py`（提供 `create_event()`、`find_events_by_profile()`、`get_event_by_id()`、`update_event()`、`delete_event()`、`count_active_by_profile()`、`delete_by_profile()` 方法）。迁移脚本通过 Alembic 管理 |
| packages/py-schemas | 框架依赖 | 新增 `EventCreate`、`EventUpdate`、`EventResponse`、`EventListItem` Pydantic DTO，以及 `SeverityLevel`、`EventSetting` 枚举。复用 `ProfileBehaviorType`（PROF-01 定义）。文件位于 `packages/py-schemas/py_schemas/profiles.py` |
| packages/py-config | 框架依赖 | 新增业务异常类 `EventLimitExceededError`（409）继承 `AppException`。消费 `AppSettings` 中 `MAX_EVENTS_PER_PROFILE` 配置项（默认 500） |
| packages/py-logger | 调用 | 所有 CRUD 操作输出结构化日志（`event_type: "event_created"` / `"event_updated"` / `"event_deleted"` / `"event_limit_exceeded"`，含 `event_id`、`profile_id`、`user_id`、`trace_id`） |
| PROF-04 专业评估补充 | 下游消费方（数据挂载） | 事件记录的 `is_professional` 标记默认为 `false`，仅 PROF-04 补充评估后设为 `true`。PROF-03 不自行修改此标记值，PROF-04 通过更新事件记录设置该字段（需权限校验） |
| PROF-02 档案驱动检索过滤 | 下游消费方（数据消费） | 读取事件记录的 `behavior_type`、`event_time`、`tags`、`is_professional` 等字段，按时间范围和行为类型筛选后注入 RAG 检索上下文。PROF-03 不感知消费逻辑 |
| CSLT-03 应急方案生成 | 间接消费（链式） | 通过 PROF-02 筛选后的事件记录作为个性化干预历史注入 Prompt 第一轮。PROF-03 不直接与 CSLT-03 耦合 |

### 1.4 状态机设计

本功能点不涉及持久化状态流转，故无需状态机。事件记录的创建、修改和删除均为家属发起的即时同步操作，不存在中间状态或异步等待流程。

从数据生命周期角度，事件记录存在隐式的"存在→删除"二态，但这是数据库行的基本属性而非业务状态机。事件创建后即处于可查询状态，删除后从数据库中物理移除——两个操作之间无业务意义的持久化中间态。

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| 厚 package、薄 app | 领域模型集中在 packages | 事件记录的 ORM 模型（`EventLog`）归属 `packages/py-db/models/profiles.py`，Pydantic DTO 归属 `packages/py-schemas/profiles.py`。`apps/api-server/` 仅包含路由注册和 Service 编排逻辑，不含领域模型定义。事件业务逻辑可由 worker 或其他应用零成本复用 |
| 单向依赖 | 依赖方向不可逆 | PROF-03 → PROF-01（档案存在性验证、级联删除）、PROF-03 → PROF-05（权限裁决）、PROF-03 → AUTH-04（角色校验）。所有依赖方向自上而下（应用→共享能力→基础设施），无反向依赖或跨 app 直接 import。PROF-02 和 CSLT-03 作为下游消费方不反向依赖 PROF-03 |
| 前后端契约先行 | Pydantic Schema 为唯一数据契约 | 事件记录的输入/输出模型以 Pydantic v2 BaseModel 定义在 `packages/py-schemas/` 中，同时作为 API 文档（FastAPI 自动生成 OpenAPI Schema）和前端类型契约（可通过 workspace 协议映射到 TypeScript）。所有字段的校验约束通过 `Field()` 声明，不散落在 Service 代码中 |
| 最小化可工作 | 不为远期需求预留代码 | MVP 阶段容量管控采用"达到上限拒绝创建"（方案 A），不为"自动归档"（意图文档描述但无明确产品规格）预建压缩存储逻辑。文本字段统一 `max_length=2000`，不为个别字段预扩上限。`is_professional` 字段仅设默认 `false`，待 PROF-04 就绪后通过更新接口设置 |
| 安全红线 | 数据隔离零妥协 | 三条安全线：(1) 路由层 `require_role(["family"])` 拒绝非家属角色的所有请求；(2) PROF-05 `PrivacyGuard` 保证跨档案数据隔离——即使同角色也无法访问未关联档案的事件；(3) Service 层创建者校验保证同一档案内不同家属的事件相互隔离。所有查询加 `profile_id` WHERE 条件，杜绝跨档案数据泄露。权限拒绝统一泛化消息为"数据不存在" |
| 可观测性 | CRUD 全链路追踪 | 每个事件操作记录一条结构化日志（`event_type` 含 `event_created`/`event_updated`/`event_deleted`），字段含 `event_id`、`profile_id`、`recorded_by`、`trace_id`、`timestamp`。容量超限拒绝和越权访问记录 WARNING 级别日志。复用 OBS-01 的 `py-logger` 体系 |
| 失败透明 | 异常信息充分暴露给调用方 | 必填字段缺失 → Pydantic 422 含 `loc` 和 `msg`；容量超限 → 409 `EventLimitExceededError` 含当前计数和上限；越权 → 403 泛化消息；事件不存在 → 404；追溯期超限 → 422 含允许的最早日期；DB 连接故障 → 500 含重试信息 |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| BehaviorType 枚举 | 复用 PROF-01 `ProfileBehaviorType` | PROF-03 独立定义 `BehaviorType(StrEnum)` | 取值完全一致（6 值），独立定义将造成与 CASE-01 `BehaviorType` 的第二处同名异构冲突。复用消除维护负担，且与意图文档 §1.3"与基础档案枚举保持一致"的兼容性要求完全对齐 |
| 容量超限策略（MVP） | 达到 500 条拒绝创建（409） | 自动归档最早记录（意图文档 §1.4(3) 描述） | "自动归档"需明确产品级定义——哪些字段属于"基础元数据"、压缩存储格式、前端交互设计。在无明确产品规格下，拒绝创建是最安全、可逆的 MVP 方案。后续可通过修改 Service 层（不改 API）升级为自动归档模式 |
| 操作者校验 | PROF-03 Service 层自行校验 `recorded_by` | 扩展 PROF-05 访问矩阵增加"事件创建者"维度 | PROF-05 的档案级权限已稳定，为其增加"事件创建者"细粒度维度将复杂化访问矩阵（需支持 `AccessOperation.event_update_own_only` 等新枚举值），且该需求仅 PROF-03 一台模块需要。在 PROF-03 Service 层做校验将复杂度隔离在本模块内，不波及其他 3 个 PROF-05 消费者 |
| 标签存储 | JSONB 数组（行内存储） | 独立标签关联表（`event_tags`） | 标签上限 5 个/事件，数据量极小（500 事件 × 5 标签 = 2500 条/档案）。JSONB 避免关联表 JOIN，搜索模式为简单数组包含（`tags @> ARRAY['吹风机']`），GIN 索引高效。与 PROF-01 档案标签的 JSONB 模式保持一致 |
| 级联删除事务 | 共享 `AsyncSession`（PROF-01 传入） | DB 层 `ON DELETE CASCADE` 外键 | 应用层编排方式使模块边界清晰——PROF-01 通过 Service 接口调用而非隐式 DB 约束。已在 PROF-01 设计文档中明确"禁止 DB 层 CASCADE"，本模块保持一致 |
| 删除语义 | 硬删除（`DELETE FROM`） | 软删除（`marked_as_deleted` 标记） | 意图文档 §1.5 场景二明确"执行硬删除操作，事件数据不可恢复"。事件记录为个人日常笔记性质数据，不需合规留存或审计回滚，硬删除降低维护复杂度 |
| 权限拒绝消息 | 泛化消息"数据不存在" | 具体原因"您无权访问此档案" | 暴露权限细节可能泄露档案存在性信息（攻击者可枚举档案 ID 通过错误消息差异推断）。泛化消息与 PROF-01/PROF-05 的泛化策略一致 |
| 级联删除权限校验 | `delete_by_profile()` 不执行权限校验 | 逐条校验每条事件的操作权限 | 级联删除由 PROF-01 档案删除操作触发——PROF-01 已执行权限校验。在级联路径上重复校验每条事件 (1) 冗余，(2) 增加 N+1 次查询开销，(3) 事务中校验失败后的回滚语义复杂。由调用方（PROF-01）保证调用安全性 |

### 1.7 注意事项与禁止行为（设计层面）

1. **[数据隔离]** 所有事件查询必须包含 `WHERE profile_id = :pid` 条件。严禁跨档案查询事件。API 路由设计中 `profile_id` 作为 URL 路径参数是唯一合法的档案上下文来源，不可从请求体或查询参数中获取。
2. **[权限不降低]** `delete_by_profile()` 方法仅供 PROF-01 的级联删除路径调用，不可暴露为 API 端点。该方法的调用方（PROF-01）已在其上下文中执行权限校验。禁止在其他场景（如用户直接调用删除接口）中绕过权限校验。
3. **[容量检查的竞态]** 500 条上限的 `COUNT` 检查和 `INSERT` 操作之间存在 TOCTOU 窗口。在极少情况下（如两个并发请求同时通过 COUNT 检查后执行 INSERT），可能导致实际记录数略超 500。设计上接受此 1-2 条的微弱超限——引入 `SERIALIZABLE` 隔离级别或行级锁的成本远大于边际收益，且意图文档的 500 条上限为经验值非硬性法律合规要求。
4. **[禁止向量索引]** 事件记录数据绝对不得写入 pgvector 索引或任何全文检索引擎。意图文档 §1.11.5 明确声明"事件记录数据绝对不以任何形式进入向量索引，避免语义检索导致的交叉污染"。违反此约束将导致不同患者的事件记录通过语义相似度被交叉关联。
5. **[禁止缓存]** 事件记录列表不设 Redis 或其他形式缓存。理由是：(1) 数据变更频繁（家属不断添加事件），缓存一致性问题成本高；(2) 单档案最多 500 条，复合索引查询 < 20ms，无需缓存优化；(3) 避免缓存中残留已删除事件的数据。
6. **[外键约束]** event_logs 表不设 `ON DELETE CASCADE` 外键。级联删除通过应用层统一编排。此约束与 PROF-01 设计文档中"禁止 DB 层 CASCADE"的全区禁令一致。
7. **[标签不作为全局标签]** 自定义标签仅在该档案的事件维度内生效。不建立全局标签表或跨档案标签聚合功能。标签归一规则仅限于去特殊符号 + 去首尾空格 + 限制 10 字，不引入 NLP 分词。
8. **[is_professional 标记只读]** 本模块的创建和修改接口**不得接受客户端传入的 `is_professional` 值**——该字段由 PROF-04 在补充专业评估后通过内部更新接口设置。在 EventCreate/EventUpdate 的 Schema 定义中，`is_professional` 字段**不出现在客户端可传字段列表中**。
9. **[recorded_by 不可篡改]** `recorded_by`（记录人标识）在事件创建时从 JWT payload 获取并写入，创建后不可修改。EventUpdate 的 Schema 中不包含 `recorded_by` 字段。

### 1.8 引用：配套意图文档

- **意图文档**：`PROF-03-事件记录管理-意图文档.md`
- **冻结时间**：`2026-05-27 17:00:10`
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。容量管控策略（方案 A：达到上限拒绝创建）为基于 MVP 阶段可行性的技术推断——意图文档 §1.4(3) 描述的"自动归档最早记录"需产品级规格确认后方可升级实现。如有歧义，以意图文档为准。
