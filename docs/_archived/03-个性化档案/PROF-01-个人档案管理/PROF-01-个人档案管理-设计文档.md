# 1 功能点：PROF-01 个人档案管理 -- 设计文档（瘦身版）

> **文档生成时间**：`2026-05-27 14:29:44`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-27 14:29:44` | AI Assistant | 初始版本，基于 s06 技术决策报告（13 项自主决策）生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `PROF-01-个人档案管理-意图文档.md`（已冻结于 2026-05-27 14:20:11）
> - 本模块的精确编码规格见 `PROF-01-个人档案管理-落地规范.md`

### 1.1 技术实现思路

PROF-01 的核心问题是：在模块化单体架构下，如何以最低耦合度提供档案 CRUD 能力，同时确保隐私控制、并发安全、数据隔离三个横切关注点被可靠执行。

**架构定位**：PROF-01 处于项目分层 L4（业务数据层），属于 03-个性化档案分组的入口模块。其职责是纯粹的档案数据管理，不做隐私判定、不做 PII 脱敏、不做标签转换——这些由下游模块（PROF-05/SEC-03/PROF-02）负责。PROF-01 通过调用已冻结的外部接口来编排这些横切关注点，自身保持薄层。

**三层鉴权流水线**：每个档案操作请求经过三层校验后才到达数据层：
1. **路由层角色校验** -- FastAPI `Depends(AUTH-04.require_role(["family"]))`，确认操作者为家属身份。这是全局统一的粗粒度身份校验，与 AUTH-04 完全对齐。
2. **服务层权限校验** -- 调用 `PROF-05.PrivacyGuard.check_access(AccessRequest)`，确认该家属对该档案有相应操作权限。这是档案级的细粒度授权。
3. **业务层规则校验** -- Pydantic v2 输入校验 + 档案数量上限校验（COUNT + 应用层检查） + 昵称长度/用药备注长度等业务约束。这是 PROF-01 自身的业务规则门控。

三层各司其职：角色校验解决"你是谁"，权限校验解决"你能对这个档案做什么"，业务校验解决"你的操作是否符合规则"。层间不交叉，任意一层失败即拒绝整个请求。

**数据存储设计**：采用 PostgreSQL + JSONB 混合存储策略。单值枚举字段（diagnosis_type、language_level 等）使用 VARCHAR 存储枚举值，利用 CHECK 约束和 Pydantic 枚举校验双重保障数据合法性。多选字段（sensory_features、triggers）使用 JSONB 数组存储，利用 GIN 索引支持下游模块（PROF-02）的标签过滤查询。文本字段（nickname、medication_notes）使用 VARCHAR/TEXT 加应用层长度校验。时间字段（birth_date、created_at、updated_at）使用 DATE/TIMESTAMPTZ 类型。

选择 JSONB 而非独立关联表存储多选标签的理由：标签值域固定（6 种感官特征 + 7 种触发因素），不会动态增长，JSONB 避免了额外的 JOIN 开销；下游 PROF-02 的标签过滤查询通过 PostgreSQL GIN 索引在 JSONB 列上高效执行，无需额外表结构。

**并发控制**：使用乐观锁（比较 updated_at 时间戳）。单家属最多 5 个档案，多设备同时修改同一档案的概率极低。乐观锁的实现成本为零（无额外基础设施），通过 `UPDATE ... WHERE id = ? AND updated_at = ?` 的 rowcount 判断冲突，冲突时返回 409 引导用户刷新。

**年龄区间计算**：实时计算，不持久化。`birth_date` 字段存入后几乎不变（仅家属修改出生日期时更新），每次读取时通过 Python 端从出生日期计算年龄后映射到区间枚举（0-3岁/4-6岁/7-12岁/13-18岁/18岁以上）。不持久化的理由：(1) 避免 Created/Updated 时需要更新该字段；(2) 出生日期修改频率极低，实时计算无性能问题；(3) 下游模块始终看到"今天"的年龄区间，而非档案创建时的区间。

**删除级联策略**：应用层编排级联删除。`profile_service.delete_profile()` 在一个数据库事务中顺序执行：(1) 校验 PROF-05 权限；(2) 调用 PROF-03 服务接口清理事件记录；(3) 调用 PROF-04 服务接口清理评估记录；(4) 硬删除本档案行。选择应用层编排而非数据库 CASCADE 的理由：事件记录和评估记录归属不同模块（PROF-03/PROF-04），PROF-01 不应通过 DB 外键硬编码跨模块的数据依赖——应用层编排通过标准化服务接口调用，模块边界清晰，且不引入隐式的 DB 级副作用。

**SEC-03 PII 检测集成策略（业务矛盾 #1 -- 基于最佳推断）**：意图文档 §1.11(7) 明确声明"本模块仅负责在提交时提示用户避免填写敏感信息"。基于此约束，PROF-01 在本阶段**不直接集成 SEC-03 的 PII 检测管道**，而是采用双层防御：(1) 前端提交前提示用户避免填写真实姓名等敏感信息（UX 层面，归属 PROF-07 编排）；(2) 后端 Pydantic validator 对 nickname 和 medication_notes 字段做关键词正则过滤（身份证号格式、手机号格式），命中则拒绝提交并返回 422 提示。同时在 `profile_service.py` 中预留 `_pii_check()` 空方法（No-op），作为 SEC-03 就绪后的扩展点。此推断与意图文档 §1.11(7) 的设计边界声明一致——PII 检测脱敏的具体执行归属 SEC-03。如果产品要求必须通过 SEC-03 管道，则需等待 SEC-03 接口就绪后补入扩展点。

**错误提示交互模式（业务矛盾 #2 -- 基于最佳推断）**：意图文档 §1.12(7) 将错误提示的交互模式留给规范阶段。基于技术可行性分析，本设计推荐**混合模式**：(1) 字段级校验错误（必填缺失、日期非法、长度超限）使用内联逐字段提示 -- 前端在每个输入组件旁展示错误文本，后端返回 422 时在 `detail` 数组中标注每个错误字段的 `loc` 和 `msg`；(2) 业务规则错误（档案数量超限 409、并发冲突 409）使用弹窗/顶部横幅 -- 因为这类错误与单一字段无关，需要向用户传达完整的引导文案；(3) 权限错误（403）使用顶部横幅 -- 不揭示额外信息。此推断基于：(a) 字段校验错误需要精确定位到具体输入控件，内联提示是最自然的映射；(b) 业务规则错误需要引导用户做出决策（如清理旧档案），弹窗提供更大的文案空间。如果用户偏好不同的交互模式，可在前端调整错误消费方式而不改动后端 API 错误响应格式。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：PROF-05-档案隐私控制-设计文档.md、PROF-05-档案隐私控制-落地规范.md、AUTH-04-五级RBAC鉴权-落地规范.md、AUTH-02-用户登录-落地规范.md、KNOW-01-科普内容管理-落地规范.md、CSLT-01/02-危机分级判定/RAG语义检索-落地规范.md、OBS-01/04-结构化日志/健康检查-落地规范.md、SEC-01/04/05-传输存储安全/防刷限流/输入校验防护-落地规范.md、DEPLOY-01~05-容器编排/反向代理/CI_CD/数据库迁移/环境配置-落地规范.md、CASE-01/04-案例录入管理/案例向量化入库-落地规范.md、AUTH-01/03/05/06 系列设计文档及落地规范，`docs/contracts/PROF-05/` 下 4 份契约文件，`docs/contracts/AUTH-04/UserRole.json`，`docs/功能设计/_contracts.md`，`docs/功能设计/功能模块全拆解.md`，`docs/功能设计/模块依赖关系分析.md`
- **兼容性结论**：
  - **无冲突**：PROF-01 的技术方案与全部 22 份已有规格文档完全兼容。
    - **PROF-05**：PROF-01 的 CRUD 操作（view/create/update/delete）与 PROF-05 `AccessOperation` 枚举六值完全对齐。PROF-05 访问矩阵中"家属本人全权"覆盖 PROF-01 所有操作权限。PROF-01 已被注册为 PROF-05 契约的消费者（`x-consumers: ["PROF-01", "PROF-03", "PROF-04"]`）。运行时通过 `PrivacyGuard.check_access(AccessRequest)` 调用 PROF-05 进行权限校验，身份数据复用 AUTH-04 的 `UserRole` 枚举。
    - **AUTH-04**：PROF-01 的路由层角色校验直接复用 `require_role(["family"])` Depends，无需自定义角色或鉴权逻辑。JWT payload 中的 `roles` 字段获取方式与 AUTH-04 标准模式一致。
    - **CSLT-01/02**：PROF-01 与应急咨询模块无直接接口耦合。PROF-02 作为 ARCH 桥梁消费 PROF-01 的档案标签数据后转化为 CSLT-02 的检索过滤条件。PROF-01 自身不感知 CSLT 域的存在。
    - **其他已有模块**：PROF-01 的业务域（个人档案数据管理）与 KNOW-01（科普内容）、CASE-01/04（案例库）、OBS/SEC/DEPLOY 系列（基础设施）完全正交，无任何接口或类型冲突。
  - **零循环依赖**：依赖关系分析确认：入度 3（PROF-02 数据读取、PROF-03 挂载引用、PROF-07 前端调用），出度 3（PROF-05 权限调用、AUTH-04 角色调用、SEC-03 PII 检测预留）。全部为单向，无循环依赖。
- **复用的已有设计**：
  - AUTH-04 的 `require_role()` Depends -- 路由级家属角色校验
  - AUTH-04 的 `UserRole` 枚举（值 `family`）-- 角色身份判定
  - AUTH-04 的 `get_current_user` Depends -- 获取 `request.state.user.user_id`
  - PROF-05 的 `AccessOperation` 枚举 -- CRUD 操作类型映射
  - PROF-05 的 `PrivacyGuard.check_access()` -- Service 层档案权限校验
  - PROF-05 的 `AccessRequest` / `AccessDecision` -- 权限请求/响应模型
  - OBS-01 的结构化日志体系（`py-logger`）-- 所有业务操作日志
  - SEC-05 的 Pydantic v2 Schema 校验体系 -- 路由层入参校验
  - 项目统一异常基类 `AppException`（`packages/py-config/exceptions.py`）-- 异常抛出
  - 项目标准分页模型 `PaginatedResponse` -- 档案列表分页
  - DEPLOY-04 的 Alembic 迁移框架 -- 新增 profiles 表迁移脚本
  - DEPLOY-05 的 `AppSettings` 配置模型 -- 环境变量加载

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|---------|-------------|
| AUTH-04 五级RBAC鉴权 | 上游调用（强） | 路由层：`Depends(require_role(["family"]))` 校验请求人身份为家属角色。通过 `get_current_user` Depends 从 JWT payload 获取 `user_id`（UUID），注入到 `request.state.user` |
| PROF-05 档案隐私控制 | 上游调用（强） | Service 层：每个 CRUD 方法第一步调用 `PrivacyGuard.check_access(AccessRequest(operation=..., target_profile_id=..., requester_id=..., requester_role=UserRole.family))`，返回 `AccessDecision`，若 `allowed=False` 则抛出 `ForbiddenAccess` |
| PostgreSQL 17.x (profiles 表) | 读写 | 新增 `profiles` 表，ORM 模型位于 `packages/py-db/py_db/models/profiles.py`。Repository 提供 `find_by_caregiver()`、`count_active_by_caregiver()`、`get_by_id()`、`save()`、`delete()` 方法。所有查询通过 SQLAlchemy 2.0 async session + 参数化查询，无 SQL 拼接 |
| PostgreSQL 17.x (profiles.sensory_features / triggers) | 只写（供下游读取） | JSONB 列存储多选标签数组，创建 GIN 索引 `(sensory_features, triggers)` 供 PROF-02 标签过滤查询使用。PROF-01 本身不查询这些 JSONB 列的内容 |
| Redis 7.x | 可选 | 预留热点默认档案缓存（`profile_default:{caregiver_id}` -- `profile_id`），TTL 5 分钟。非必须路径 -- 无 Redis 时降级为 DB 查询，不影响核心功能 |
| packages/py-db | 框架依赖 | 新增 ORM 模型 `Profile`（`models/profiles.py`），新增 Repository `profile_repository.py`。数据库迁移脚本通过 Alembic 管理 |
| packages/py-schemas | 框架依赖 | 新增 `ProfileCreate`、`ProfileUpdate`、`ProfileResponse`、`ProfileListItem` Pydantic DTO，以及 `DiagnosisType`、`BehaviorType`、`LanguageLevel`、`SensoryFeature`、`Trigger` 枚举。文件位于 `py_schemas/profiles.py` |
| packages/py-config | 框架依赖 | 新增业务异常类 `ProfileLimitExceededError`、`ProfileConflictError`（409）继承 `AppException`。消费 `AppSettings` 中 `MAX_PROFILES_PER_USER` 配置项（默认 5） |
| packages/py-logger | 调用 | 所有 CRUD 操作输出结构化日志（`event_type: "profile_created"` / `"profile_updated"` / `"profile_deleted"`，含 `profile_id`、`caregiver_id`、`trace_id`） |
| PROF-02 档案驱动检索过滤 | 下游消费方（数据提供） | 通过 `ProfileResponse.age_range`、`primary_behavior`、`sensory_features`、`triggers` 字段消费档案标签数据，转化为 RAG 检索过滤条件。PROF-01 不感知消费逻辑 |
| PROF-03 事件记录管理 | 下游消费方（标识提供） | 事件记录通过 `profile_id` 外键挂载到具体档案。PROF-03 创建事件时通过 `GET /api/v1/profiles/{profile_id}` 验证档案存在性。PROF-01 删除档案时通过应用层调用 PROF-03 服务接口清理关联事件记录 |
| PROF-07 档案数据逻辑 | 下游消费方（API 提供） | 前端逻辑层通过 `/api/v1/profiles` RESTful API 调用本模块，获取 ProfileResponse/ProfileListItem 数据，发送 ProfileCreate/ProfileUpdate 请求。PROF-01 不感知前端的冷启动引导和标签沉淀逻辑 |

> 精确的函数签名、SQL 查询模板、ORM 字段定义等见落地规范。

### 1.4 状态机设计（技术实现策略）

本功能点不涉及持久化状态流转，故无需状态机。意图文档 §1.7 明确声明档案的创建、查看、更新和删除均为家属发起的即时同步操作，不存在中间状态或异步等待流程。

从技术层面，档案行本身存在一个隐式的生命周期，但不构成需要状态机管理的复杂流转：

```
不存在 ──create──▶ 存在（active）──delete──▶ 不存在（hard-deleted）
```

- **创建**：INSERT 新行，`profile_id` 由 UUID v4 生成，`created_at` / `updated_at` 初始化，无中间状态。
- **更新**：UPDATE 通过 `WHERE id = ? AND updated_at = ?` 乐观锁条件更新，原子操作。
- **删除**：应用层编排级联删除（事件记录 + 评估记录 + 本行），硬删除不可恢复，在单个事务中完成。

唯一需要注意的技术点是**默认档案的自动管理**：删除默认档案时，在同一个事务中从剩余档案中选取 `updated_at` 最新者提升为默认档案（`SET is_default = true`）。若删除后无剩余档案（账号下最后一档案被删除），则下次创建时新档案自动成为默认。这不是状态流转，而是数据完整性的保障逻辑。

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| 2.1 | 单一职责 | PROF-01 仅负责档案数据的 CRUD 管理和业务规则校验，不涉隐私判定（归 PROF-05）、标签转换（归 PROF-02）、PII 脱敏（归 SEC-03）、角色定义（归 AUTH-04）。每个 Service 方法聚焦于一种操作类型（create/read/update/delete），不含跨操作的复合逻辑 |
| 3.5 | 可观测性 | 所有 CRUD 操作通过 `py-logger` 输出结构化日志，含 `event_type`、`profile_id`、`caregiver_id`、`trace_id` 和操作耗时。异常操作（越权访问、超限拒绝、并发冲突）额外标记 `warning` 级别 |
| 1.1 | 反脆弱输入 | 所有 API 入参通过 Pydantic v2 BaseModel 严格校验（枚举值域、类型约束、长度限制、必填/可选标记），不合法参数立即返回 422，拒绝进入 Service 层。后端校验不依赖前端校验的正确性 |
| 2.3 | 模块边界清晰 | PROF-01 通过 PROF-05 的标准化接口（`check_access()`）而非直接查询 `teacher_links` 表来判定权限；通过 PROF-03 的服务接口而非直接操作 `event_logs` 表来级联删除。模块间仅通过已冻结的契约接口交互，不共享数据库表 |

> 以上原则编号遵循项目技术栈设计中定义的原则体系。PROF-01 作为一般模块，其核心价值在于数据准确性和模块边界清晰，因此仅相关原则被列出。

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 档案标识生成 | UUID v4（`uuid.uuid4()`） | 方案A：自增 BIGSERIAL；方案B：自定义前缀编号（"PF-20260527-0001"） | 项目技术栈统一使用 UUID PK（全部 21 个已设计模块均采用 UUID）。自增序号在多实例部署时需 SEQUENCE 协调；自定义前缀增加复杂度且意图文档未要求面向用户的编号格式 |
| 多选标签存储 | JSONB 数组 + GIN 索引 | 方案A：独立关联表（profile_sensory_features）；方案B：逗号分隔字符串 | JSONB 方案：(1) 值域固定不增长，无需关联表的灵活性；(2) GIN 索引支持 PROF-02 的高效标签过滤查询；(3) 避免 N+1 JOIN 开销。关联表方案在值域动态增长时更优，但本模块值域已锁定 6+7 项 |
| 并发控制 | 乐观锁（`WHERE updated_at = ?`） | 悲观锁（`SELECT ... FOR UPDATE`） | 单家属最多 5 档案，并发冲突概率极低。乐观锁零基础设施成本，无锁等待。悲观锁会在少见的并发场景下阻塞读取，收益微小 |
| 年龄区间计算 | 实时计算（读取时 Python 端计算），不持久化 | 持久化存储（写入时计算并存储 age_range 字段） | 实时计算：(1) birth_date 修改频率极低，计算开销可忽略（一次算术运算）；(2) 下游模块总是看到"今天"的年龄区间；(3) 无需在 updated_at 更新时同步刷新 age_range。持久化方案在 birth_date 被修改时需额外维护 age_range 一致性 |
| 删除级联 | 应用层编排（Service 事务中顺序调用） | 方案A：数据库 CASCADE（外键 ON DELETE CASCADE）；方案B：软删除（is_deleted 标记） | 应用层编排：(1) 事件/评估记录归属不同模块（PROF-03/04），PROF-01 不应通过 DB 外键硬编码跨模块依赖；(2) 意图文档明确"删除后无法恢复"，软删除不符合业务语义；(3) 硬删除行比维护 is_deleted 标记更简单且不增加存储碎片。受意图文档约束 |
| 档案数量上限校验 | Service 层 `COUNT(*) WHERE caregiver_id = ? AND status = active` + 应用层判断 | 数据库 UNIQUE 约束或触发器 | COUNT + 应用层判断：(1) 上限值可能由配置调整（不硬编码在 DB schema 中）；(2) 当前并发风险可忽略（单家属同时创建多个档案的场景不存在）；(3) 拒绝时返回业务级错误文案而非 DB 异常。DB 触发器方案在错误文案和可配置性上均不如应用层 |
| SEC-03 PII 集成 | 本阶段不直接集成：前端提示 + 后端关键词正则 + 预留扩展点（`_pii_check()` No-op） | 方案A：立即集成 SEC-03 完整管道；方案B：完全不做 PII 校验 | SEC-03 尚无契约文件，接口未定义。立即集成不具可行性。完全不做校验违反意图文档数据最小化要求。本方案平衡了"意图文档要求"和"基础设施现状"的约束。受意图文档 §1.11(7) 约束 |
| 前端校验与后端校验分工 | 双重校验：前端实时校验（实时反馈）+ 后端 Pydantic 严格校验（安全门禁） | 方案A：仅前端校验；方案B：仅后端校验 | 双重校验：(1) 前端校验保障用户体验（即时反馈，无需等待网络往返）；(2) 后端校验是安全底线（防止绕过前端直接调用 API）；(3) 校验逻辑有意重复——安全原则下不信任客户端。无共享校验逻辑（两边独立实现，避免单点故障） |
| API 设计风格 | 标准 RESTful：资源导向 URL + HTTP 动词 + 标准状态码 | 方案A：RPC 风格 `/api/v1/profile/create`；方案B：GraphQL | RESTful 是项目统一风格（已设计的全部模块均采用 `/api/v1/{resource}` 模式）。RPC 在简单 CRUD 场景下无优势；GraphQL 在查询灵活性上有优势但在权限校验复杂性上有劣势（字段级权限需与 PROF-05 协调查询过滤） |

### 1.7 注意事项与禁止行为（设计层面）

1. **[必须通过 PROF-05]** 所有档案数据操作（包括查询列表）必须首先通过 `PrivacyGuard.check_access()` 校验。禁止在 `profile_service.py` 中直接执行数据库操作而不经过权限校验。禁止绕过 PROF-05 的 AccessOperation 枚举——每个操作类型必须映射到正确的枚举值（查看→view，创建→create，更新→update，删除→delete）。

2. **[档案数据绝对隔离]** 所有数据库查询必须限定 `caregiver_id = <当前用户>` 条件。禁止全表扫描或跨用户查询。`profile_id` 是物理隔离的边界——任何跨档案的数据访问都违反业务约束。

3. **[默认档案一致性]** 同一家属账号下必须有且仅有一个默认档案（`is_default = true`），除非账号下无档案。创建新档案后若为唯一档案，必须在同一事务中设置 `is_default = true`。删除默认档案后，必须在同一事务中将另一档案提升为默认。禁止出现"零默认档案但存在档案"的不一致状态。

4. **[不做跨模块直接 DB 访问]** 禁止 PROF-01 直接操作 PROF-03 的 `event_logs` 表、PROF-04 的 `professional_notes` 表、PROF-05 的 `teacher_links` 表。跨模块数据依赖必须通过对方模块的标准化服务接口调用。这是模块化单体架构的核心纪律。

5. **[硬删除不可恢复]** 档案删除是物理删除（`DELETE FROM profiles WHERE ...`），不可恢复。禁止使用软删除标记（`is_deleted` / `deleted_at`）。执行删除前必须在 Service 层校验档案存在性。受意图文档约束。

6. **[输入校验不可跳过]** 禁止绕过 Pydantic Schema 直接操作数据库。所有外部输入（包括来自前端的请求和来自内部模块的调用）必须经过 Pydantic v2 的严格校验后才进入 Service 层。

7. **[设计边界]** 本模块不负责：(a) 档案权限的判定逻辑（归属 PROF-05）；(b) 档案标签到检索条件的转换（归属 PROF-02）；(c) 事件记录的创建和管理（归属 PROF-03）；(d) 专业评估的管理（归属 PROF-04）；(e) PII 检测脱敏的具体执行（归属 SEC-03）；(f) 前端冷启动检测和引导编排（归属 PROF-07）。

8. **[开放技术决策]** 本模块的 8 项开放技术决策已在 s06 技术预研中全部自主确定（§1.6 架构权衡与备选方案中的决策点 1-9）。唯一待确认项为 SEC-03 PII 集成方式（业务矛盾 #1），已通过预留扩展点处理。

### 1.8 引用：配套意图文档

- **意图文档**：`PROF-01-个人档案管理-意图文档.md`
- **冻结时间**：`2026-05-27 14:20:11`
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。13 项自主技术决策均有明确文档依据或行业最佳实践支撑。2 项业务矛盾（SEC-03 PII 集成方式、错误提示交互模式）已基于意图文档约束和技术可行性做出最佳推断并在设计文档中标注处理方式。如有歧义，以意图文档为准。
