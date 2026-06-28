# 1 功能点：PROF-05 档案隐私控制 -- 设计文档（瘦身版）

> **文档生成时间**：`2026-05-26 22:53:43`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-26 22:53:43` | AI Assistant | 初始版本，基于 s06 技术决策报告和用户4项澄清生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `PROF-05-档案隐私控制-意图文档.md`（已冻结于 2026-05-26 22:48:43）
> - 本模块的精确编码规格见 `PROF-05-档案隐私控制-落地规范.md`

### 1.1 技术实现思路

档案隐私控制的核心问题是：每次档案访问请求到达时，如何在不信任客户端的前提下，实时判定发起人是否有权执行所请求的操作。本模块采用**双层鉴权架构**解决此问题。

**第一层：路由级粗粒度角色校验。** 所有涉及档案操作的 API 路由通过 `require_role()` Depends 做角色存在性检查。这一步仅确认发起人是已认证的有效角色（家属/老师/专家/管理员/维护人员之一），以及角色是否可以访问档案相关路由。这一步与 AUTH-04 的鉴权机制完全一致，复用 `packages/py-auth/rbac.py` 中已有的 `require_role()` 函数。

**第二层：Service 级细粒度档案权限校验。** 路由层通过角色校验后，请求进入 `profile_service.py` 的 Service 方法。每个 Service 方法在执行业务逻辑前，调用 `PrivacyGuard.check_access()` 进行档案级权限判定。该函数接收 `AccessRequest`（含操作类型、目标档案ID、请求人ID、请求人角色、关联关系类型），返回 `AccessDecision`（允许/拒绝 + 可见范围）。这一步是 PROF-05 的核心差异化逻辑：同一角色对不同档案有不同的权限（如家属只能访问自己关联的档案），这是路由层无法区分的。

**选择双层而非单层的原因**：路由层 `require_role()` 解决"你是谁"（身份校验），Service 层 `PrivacyGuard` 解决"你能对这个档案做什么"（档案级授权）。两层关注点正交，各自职责清晰。将档案级授权单独封装在 `PrivacyGuard` 中也使得其可被单元测试独立验证。

**数据流设计**：请求到达 API 路由 -> `require_role()` 角色校验 -> `profile_service` 方法 -> `PrivacyGuard.check_access()` 档案级权限判定 -> 若允许则执行数据库操作，若拒绝则抛出 `ForbiddenAccess` 异常，全局异常处理器捕获后返回 403 + 通用提示。

**关联关系查询策略**：每次请求实时查询 PostgreSQL `teacher_links` 表（`WHERE unlinked_at IS NULL`）获取有效关联关系。不做 Redis 缓存。原因是意图文档要求"零延迟切断"（§1.11 约束 1）-- 家属解除老师关联后，被解除者必须在下一请求前失去全部访问权限。引入任何缓存都会引入延迟窗口。中低频率的档案访问场景下，每次请求一次关系表查询的性能开销完全可接受（主键索引查询 <5ms）。

**降级策略**：无。隐私控制是安全关键路径，不允许降级。如果 `teacher_links` 表查询失败，向上层抛出数据库异常，由全局异常处理器返回 500，不允许绕过权限校验执行数据操作。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：AUTH-04-五级RBAC鉴权-设计文档.md、AUTH-04-五级RBAC鉴权-落地规范.md、KNOW-01-科普内容管理-落地规范.md、OBS-01-结构化日志-落地规范.md、SEC-01-传输存储安全-落地规范.md、SEC-05-输入校验防护-落地规范.md、DEPLOY-01~05 系列落地规范、SEC-04-防刷限流-落地规范.md、AUTH-01-用户注册-落地规范.md、_contracts.md、模块依赖关系分析.md
- **兼容性结论**：
  - **无冲突**：PROF-05 的业务域（档案隐私/访问控制）与所有已有规格文档完全正交。
    - 与 AUTH-04 已对齐：AUTH-04 设计文档明确声明 PROF-05 为其下游消费方。PROF-05 的双层鉴权架构中，第一层直接复用 AUTH-04 的 `require_role()` Depends 和 `UserRole` 枚举，角色命名体系（英文枚举值 + `display_name`）保持一致。第二层档案级权限校验是 AUTH-04 的自然扩展，不对已有接口进行任何修改。
    - 与 KNOW-01 无冲突：两个模块业务域正交（科普文章 vs 个人档案）。
    - 与 SEC-01/04/05 无冲突：PROF-05 使用 SEC-05 的 Pydantic Schema 校验作为请求入口，使用 OBS-01 的结构化日志体系记录审计事件。
  - **零循环依赖**：依赖关系分析确认 PROF-05 仅依赖 AUTH-04（上游），被 PROF-01/03/04 依赖（下游），依赖方向全为单向。
- **复用的已有设计**：
  - AUTH-04 的 `require_role()` Depends（路由级角色校验入口）
  - AUTH-04 的 `UserRole` 枚举和角色层级体系
  - AUTH-04 的 `get_current_user` Depends（获取 `request.state.user`）
  - OBS-01 的结构化日志体系（`py-logger`）用于审计日志输出
  - SEC-05 的 Pydantic 入参校验体系
  - 项目统一异常基类 `AppException`（`packages/py-config/exceptions.py`）

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|---------|-------------|
| AUTH-04 五级RBAC鉴权 | 上游数据来源 | 通过 `require_role()` Depends 获取 `UserRole` 枚举值；通过 `get_current_user` Depends 获取 `request.state.user.roles` 和 `request.state.user.user_id`。JWT payload 中的 `roles: list[str]` 字段是 PROF-05 角色判定的唯一数据来源 |
| AUTH-02 用户登录 | 上游间接依赖 | JWT Token 的签发和验证由 AUTH-02 负责，PROF-05 通过 `get_current_user` 间接依赖 |
| PostgreSQL (profiles 表) | 读写 | 查询档案是否存在（`profile_repository.get_by_id()`），确认目标档案标识的有效性 |
| PostgreSQL (teacher_links 表) | 读写 | 新建表，查询家属-老师-专家关联关系（`WHERE unlinked_at IS NULL`），写入关联关系变更（解除关联时设置 `unlinked_at`） |
| PostgreSQL (professional_notes 表) | 只读 | 已有表，增加 `visible_after_unlink BOOLEAN DEFAULT true` 字段，查询时过滤被隐藏的评估记录 |
| packages/py-auth | 框架依赖 | 新增 `PrivacyGuard` 类和 `check_profile_access()` 函数于 `rbac.py` 中 |
| packages/py-schemas | 框架依赖 | 新增 `AccessRequest`、`AccessDecision`、`AccessOperation`、`AccessResult`、`VisibleScope` 类型于 `profiles.py` 中 |
| packages/py-db | 框架依赖 | 新增 `teacher_links` 表 ORM 模型于 `models/profiles.py`；新增 `teacher_link_repository` 查询方法 |
| packages/py-logger | 调用 | 越权访问时输出 `event_type: "unauthorized_access"` 结构化日志 |
| PROF-01 个人档案管理 | 下游消费方 | 档案 CRUD 操作前调用 `PrivacyGuard.check_access()` 进行权限校验 |
| PROF-03 事件记录管理 | 下游消费方 | 事件记录的查看/新增/修改/删除权限由 PROF-05 约束 |
| PROF-04 专业评估补充 | 下游消费方 | 专业评估的提交和可见性由 PROF-05 约束 |

> 精确的函数签名、Cypher 查询模板、类名等见落地规范。

### 1.4 状态机设计（技术实现策略）

本功能点不涉及状态流转，故无需状态机。隐私控制的本质是对每一次访问请求进行**实时、无状态裁决** -- 每次请求到达时，基于当前时刻的关联关系状态独立做出允许/拒绝判定，裁决结果不产生持久化状态变更。

不过，`teacher_links` 表中的关联关系本身存在一个隐式的二态生命周期，在技术层面需要注意这些转换的原子性保障：

```
关联活跃 ──unlink──▶ 关联断裂
关联断裂 ──relink──▶ 关联活跃
```

- **unlink 操作**：家属调用解除关联时，在一个事务中完成：(1) 更新 `teacher_links.unlinked_at = NOW()`；(2) 批量设置 `professional_notes.visible_after_unlink = false`（该老师在目标档案下的所有评估记录）。两步在同一事务中执行，要么全部成功要么全部回滚。
- **relink 语义**：如果家属未来重新关联同一老师（即创建新的 `teacher_links` 记录），历史评估的 `visible_after_unlink` 是否需要批量恢复？此行为由用户裁定确定：**如果重新关联，历史评估不自动恢复**，需要老师重新提交。

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| 2.1 | 单一职责 | PROF-05 仅负责档案级访问控制判定，不负责角色定义（归 AUTH-04）、档案 CRUD（归 PROF-01/03/04）、用户认证（归 AUTH-02/06）。`PrivacyGuard.check_access()` 是纯函数（输入 AccessRequest，输出 AccessDecision），无副作用 |
| 3.5 | 可观测性 | 越权访问事件通过 `py-logger` 输出结构化日志（含 `event_type`, `requester_id`, `target_profile_id`, `requester_role`, `operation`, `trace_id`）；关联关系变更（解除/建立）写入独立 `audit_log` 表持久化 |

> 以上原则编号遵循项目技术栈设计中定义的原则体系。PROF-05 作为安全横切节点，其核心价值在于正确性而非性能或可扩展性，因此仅相关的原则被列出。

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 权限校验实现方式 | 双层架构：路由级 `require_role()` + Service 级 `PrivacyGuard.check_access()` | 方案A：单层路由级（所有逻辑在 Depends 中）；方案B：单层 Service 级（路由不做任何校验） | 方案A无法区分同一角色对不同档案的不同权限（家属只能访问自己关联的档案）；方案B路由层零校验意味着未认证请求也能进入 Service 层，增加攻击面。双层各司其职：路由层做身份确认（快、通用），Service 层做档案级授权（细、专用） |
| 关联关系存储 | PostgreSQL `teacher_links` 关系表，每次请求实时查询 | 方案A：Redis 缓存（TTL 60s）；方案B：JWT payload 内嵌关联关系列表 | 方案A与意图文档"零延迟切断"约束矛盾（缓存窗口期内被解除者仍可访问）；方案B在关联关系变更时需强制用户重新登录才能刷新 JWT，且 JWT payload 膨胀。关系表实时查询确保零延迟，性能开销可接受（<5ms 主键索引） |
| 隐藏策略实现 | `professional_notes.visible_after_unlink` 布尔标记 + `teacher_links.unlinked_at` 时间戳双重机制 | 方案A：软删除标记（is_deleted 字段）；方案B：查询时动态 JOIN 排除 | 双重机制：`unlinked_at` 标记关联关系断裂时间点，`visible_after_unlink` 控制该老师评估的可见性。方案A单一字段无法区分"关联断裂导致的隐藏"与"内容本身被删除"；方案B的每次查询动态计算在大数据量下性能恶化 |
| 并发控制策略 | 乐观锁（`teacher_links.version` 整型字段） | 悲观锁（`SELECT ... FOR UPDATE`） | 关联关系变更频率极低（家属手动操作），乐观锁冲突概率低。悲观锁会阻塞并发档案读取操作（SELECT 被写锁阻塞），影响正常访问。乐观锁提供失败-重试语义，正好满足意图文档"后到达请求基于最新状态裁决"的描述（受意图文档约束） |
| 异常响应策略 | 越权统一返回 403 + `{"detail": "数据不存在"}` | 返回 404（资源不存在） | 403 语义准确（已认证但无权限），而 404 会在前后端日志中混淆"档案不存在"和"无权访问"。通用提示"数据不存在"满足意图文档"静默拒绝、不泄露档案存在性"的约束（受意图文档约束） |
| 代码归属 | `packages/py-auth/rbac.py` 新增 `PrivacyGuard` + `apps/api-server/app/services/profile_service.py` 调用 | 方案A：全部放在 `profile_service.py`；方案B：独立文件 `privacy_guard.py` | `packages/py-auth` 是认证鉴权的唯一共享包，PROF-05 的权限判定属于鉴权范畴。放在 `rbac.py` 中与 `require_role()` 相邻，形成完整的鉴权能力梯队。Service 层仅做编排调用，不含权限决策逻辑 |
| 缓存关联关系 | 不做缓存，每次请求实时查询 DB | Redis 缓存关联关系（TTL 60s） | 意图文档明确"零延迟切断"，缓存引入的延迟窗口（最大60s）违反此约束。且档案操作是中低频场景，实时查询性能完全可接受（受意图文档约束） |

### 1.7 注意事项与禁止行为（设计层面）

1. **[零延迟切断]** 家属解除老师关联时，必须在同一事务中更新 `teacher_links.unlinked_at` 和 `professional_notes.visible_after_unlink`，禁止分两步提交。任何异步处理都会引入权限窗口。

2. **[静默拒绝不得泄露信息]** 拒绝访问时，响应体只能是 `{"detail": "数据不存在"}`，禁止返回 `"您无权访问此档案"`、`"profile_id 不存在"` 等差异化信息。攻击者可通过差异化错误信息枚举有效档案 ID。

3. **[不做缓存]** 禁止对关联关系做任何形式的缓存（Redis、进程内 cache、request-level cache 等），每次请求必须实时查询数据库。这是"零延迟切断"约束的技术保障。

4. **[不绕过校验]** 禁止在 `profile_service.py` 的任何方法中直接执行数据库操作而不先调用 `PrivacyGuard.check_access()`。`profile_service.py` 是路由和数据库之间的唯一业务编排层，每个方法必须以权限校验为第一步。内部调用链也不得绕过。

5. **[设计边界]** 本模块不负责：(a) 角色层级的定义和维护（归属 AUTH-04）；(b) 档案数据的 CRUD 业务逻辑（归属 PROF-01/PROF-03/PROF-04）；(c) 用户认证与会话管理（归属 AUTH-02/AUTH-06）；(d) 数据加密与传输安全（归属 SEC-01）。

6. **[审计追踪]** 关键操作（解除关联、建立关联）必须写入 `audit_log` 表持久化，记录 `operation`, `operator_id`, `target_profile_id`, `affected_teacher_id`, `timestamp`。越权尝试（拒绝的访问请求）通过结构化日志输出但不需要持久化到业务表。

7. **[不含向量索引]** 个人档案数据绝对不以任何形式进入向量索引或语义检索库（pgvector）。PROF-05 的职责之一就是保障这条边界的严格执行 -- 任何涉及档案数据的查询都不应经过向量检索路径。

### 1.8 引用：配套意图文档

- **意图文档**：`PROF-05-档案隐私控制-意图文档.md`
- **冻结时间**：`2026-05-26 22:48:43`
- **用户澄清（已裁决）**：
  1. Q1（隐藏数据可恢复性）：解除关联后的历史评估数据为"软删除" -- 标记不可见但不物理删除。若老师重新获得关联，历史评估不自动恢复，需重新提交。
  2. Q2（管理员元数据边界）：管理员仅可查看聚合统计数据（档案数量、存储大小、创建时间），不可查看任何业务内容字段（包括 `diagnosis_type` 等分类字段）。
  3. Q3（关联数据完全可见）：关联老师和专家可见档案的全部业务内容，与家属可见范围一致。
  4. Q4（家属权限一致性）：同一家庭下的多位家属账号权限完全一致，均可执行全部家属职能操作（查看档案、新增事件、解除关联等）。
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。双层鉴权架构精确映射了五类角色的访问矩阵，乐观锁策略对应了意图文档的并发操作描述，实时查询保证零延迟切断。如有歧义，以意图文档为准。
