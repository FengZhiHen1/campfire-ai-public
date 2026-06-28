# 1 功能点：CASE-01 案例录入管理 — 设计文档（瘦身版）

> **文档生成时间**：`2026-05-27 09:20:28`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-27 09:20:28 | AI Assistant | 初始版本（基于技术决策报告 v1.0，全量设计） |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `CASE-01-案例录入管理-意图文档.md`（已冻结于 2026-05-27 09:11:39）
> - 本模块的精确编码规格见 `CASE-01-案例录入管理-落地规范.md`

### 1.1 技术实现思路

本模块采用标准的 FastAPI 三层架构（Router → Service → Repository）实现案例录入的 CRUD 操作和状态流转。核心技术决策围绕三个主线展开：数据存储、状态管理、安全校验。

**数据存储采用单表模式**。L1 原始叙事层的 4 个字段（标题、叙事文本、来源类型、作者标识）和 L2 结构化卡片层的 13 个必填字段（行为类型、年龄区间、四段式输出等）均作为 `cases` 表的原生列存储，不使用 JSONB 或双表外键关联。这一决策基于以下判断：意图文档中 L1 和 L2 在录入时作为一个整体提交，不存在一对多关系——一对多关系发生在下游的 CASE-04（向量化入库）和 CASE-05（版本迭代）阶段，它们通过 `case_id` 外键关联扩展，不需要在当前模块的存储层预留复杂关系。原生列存储使数据库约束（NOT NULL、CHECK）和查询索引直接生效，比 JSONB 方案拥有更清晰的查询性能和约束保障。

**编辑冲突采用乐观锁**。更新操作要求客户端传入上次读取时的 `updated_at` 时间戳，服务端与当前值比对——不一致则返回 409 Conflict。选择乐观锁而非悲观锁的理由：项目为 1-3 人小团队，同一案例的并发编辑概率极低；乐观锁无锁开销、无死锁风险，实现复杂度远低于需要 Redis 或数据库锁表维护的悲观锁方案。如果未来并发场景增长，可以在 Repository 层透明切换为悲观锁而不影响 Service 层接口。

**编辑即重置的业务约束在 Service 层实现**。`case_service.update_case()` 在执行字段更新前检查当前 `status`：若为 `pending_review` 或 `rejected`，先将 `status` 置为 `draft`。这一逻辑封装在单一事务中，确保不依赖调用方的自觉行为，也避免路由层漏写重置逻辑。

**PII 检测采用正则表达式方案**。覆盖意图文档要求的 5 类 PII（真实姓名、手机号码、身份证号、家庭住址、学校名称），在提交前作为提示性辅助检测执行——检测到疑似 PII 后以 warning 列表形式返回给前端展示，用户确认已脱敏后可继续提交。选择正则而非 NLP 模型的理由：意图文档 §1.8.2 明确此检测为"辅助提示功能"非强制阻断；正则方案零外部依赖、零模型推理延迟，足以覆盖常见中文 PII 模式；NLP 模型方案作为可后续增强的扩展点预留。

**前端采用单一 Zustand store（caseFormStore）管理表单状态**。集中管理字段值、逐字段校验结果、自动保存状态和提交状态。表单校验执行双层策略：前端 onBlur 逐字段校验 + onSubmit 全量校验（涵盖必填非空、枚举合法、年龄格式等规则），服务端 Pydantic v2 再次强校验——双重校验确保数据质量。选择单 Store 而非多 Slice 是因为案例分析表单存在字段间交叉校验（如 EBP 标签一致性检测需要在循证等级和标签列表之间联动），集中管理比拆分更清晰。

**表单自动保存采用本地存储**。30 秒防抖间隔将表单全部字段 JSON 序列化到 Taro.Storage，应用重启或页面返回时自动检测本地草稿并提示恢复。不上传服务端自动保存的理由：避免频繁的不必要后端写入；草稿数据不需要跨设备同步（专家通常在单设备上完成录入）；简单可靠，零后端成本。业务矛盾方面，当前 MVP 策略为仅保留最新一份草稿且不过期清除——这是意图文档未明确约束下的最小可行选择，未来可根据用户反馈调整为多草稿保留或设置 7 天过期。

**LLM 自动提取（L1→L2）采用异步触发**。用户在完成 L1 叙事输入后点击"自动提取"按钮触发，或系统检测到停止输入 3 秒后自动触发。提取结果在本页面展示供专家微调确认后再提交，不自动覆盖已填写的 L2 字段。提取使用轻量模型以控制延迟在 5 秒内。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：AUTH-04 五级RBAC鉴权-落地规范.md（已冻结）、PROF-05 档案隐私控制-落地规范.md（已冻结）、KNOW-01 科普内容管理-落地规范.md（已冻结）、OBS-01 结构化日志-落地规范.md（已冻结）、OBS-04 健康检查-落地规范.md（已冻结）、SEC-01 传输存储安全-落地规范.md（已冻结）、SEC-04 防刷限流-落地规范.md（已冻结）、SEC-05 输入校验防护-落地规范.md（已冻结）、DEPLOY-01~05 系列落地规范（已冻结）、功能模块全拆解.md、模块依赖关系分析.md、_contracts.md

- **兼容性结论**：
  - **无冲突**：CASE-01 属于 04-真实案例库管理分组的第一模块，该分组尚未有任何其他设计文档或契约文件。前序已完成模块（AUTH/PROF/KNOW/OBS/SEC/DEPLOY 共 6 个分组）均属不同业务域，无业务规则重叠或验收标准冲突。依赖关系分析确认 168 条依赖关系中无循环依赖，CASE-01 的出入度均为单向。
  - **依赖接口就绪状态**：AUTH-04 的 `require_role` 和 `UserRole` 契约已在 AUTH-04 落地规范的 `_module-index.json` 中预登记 CASE-01 为消费者。SEC-03（PII 检测脱敏）和 CASE-02（案例附件管理）尚无落地规范，但在本模块内部，PII 检测逻辑直接通过正则表达式实现（决策 #4），附件引用仅维护 `list[AttachmentRef]` JSON 数组不依赖 CASE-02 的实时服务——这使 CASE-01 在 SEC-03 和 CASE-02 落地前即可独立开发，通过 mock AttachmentRef 结构完成功能验证。

- **复用的已有设计**：
  - AUTH-04 `UserRole` 枚举（family/teacher/expert/admin/maintainer）——用于角色准入校验
  - AUTH-04 `require_role` Depends——路由层注入角色校验
  - DEPLOY-05 `AppSettings`——环境配置读取
  - OBS-01 结构化日志——审计日志记录
  - SEC-05 Pydantic v2 BaseModel 校验——请求体强校验
  - 项目结构 §5 分层架构（Router→Service→Repository）——模块内代码组织

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| PostgreSQL 17.x | 读写 | 通过 `packages/py-db/repositories/case_repository.py` 操作 `cases` 表。索引策略：`status` 普通索引 + `author_id` 普通索引 + `(status, created_at)` 复合索引 + `(behavior_type, status)` 复合索引 |
| AUTH-04 (RBAC鉴权) | 调用 | 路由层通过 `Depends(require_role(min_level=UserRole.TEACHER))` 注入，限制仅老师/专家角色可访问。依赖注入链：`Depends(get_current_user)` → `Depends(require_role(...))` |
| SEC-03 (PII检测) | 调用（本地实现） | 提交时调用 `packages/py-security/pii_detector.py` 中的 `detect_pii(narrative: str)` 执行正则匹配检测。本模块内部实现 PII 检测逻辑，不依赖 SEC-03 的外部服务——SEC-03 落地后可将检测逻辑移入 SEC-03 模块 |
| CASE-02 (附件管理) | 调用（数据结构依赖） | `AttachmentRef` 结构引用自 CASE-02 的契约定义。本模块仅维护 `[{file_name, minio_path, file_type, file_size, uploaded_at, sort_order}]` 引用列表 |
| CASE-03 (审核工作流) | 下游数据消费 | 案例提交后 `status` 变为 `pending_review`；CASE-03 通过读取同一 `cases` 表的 `status=pending_review` 记录获取待审核案例；驳回结论由 CASE-03 写入 `status=rejected` 并填充 `review_comment` |
| packages/py-schemas | 框架依赖 | `CaseCreateRequest`、`CaseResponse`、`CaseUpdate` 等 Pydantic Schema 定义于 `packages/py-schemas/py_schemas/cases.py` |
| packages/py-logger | 框架依赖 | 关键动作（PII 确认、状态变更、提交审核）通过 `packages/py-logger/` 记录结构化审计日志 |
| packages/py-config | 框架依赖 | 数据库连接、JWT 密钥等环境变量通过 `py-config` 读取 |
| packages/ts-shared | 前端契约对齐 | TypeScript 端 `CaseCreateRequest`、`CaseResponse` 接口及枚举定义于 `packages/ts-shared/src/types/cases.ts` 和 `packages/ts-shared/src/enums/cases.ts` |

> 精确的函数签名、类名、API 端点路径见落地规范。

### 1.4 状态机设计（技术实现策略）

案例录入管理涉及 3 个持久化状态，转换规则如下：

```
draft ──[submit]──► pending_review ──[CASE-03 reject]──► rejected
  ▲                                                     │
  └─────────────────[edit]──────────────────────────────┘
                        │
                        └── 从 pending_review 编辑 → 重置为 draft
```

**状态持久化**：`cases.status` 列使用 SQLAlchemy `Enum(CaseStatus)` 类型存储在 PostgreSQL 中。每次状态变更同时更新 `updated_at` 时间戳。

**状态转换幂等策略**：状态转换的统一入口为 `case_repository.update_status()`，在 `case_service` 中包装校验逻辑：
- `submit` 仅在 `status=draft` 时生效 → 否则返回 409 Conflict（含当前状态和允许转换提示）
- `edit` 仅在 `status=pending_review` 或 `rejected` 时重置为 `draft` → 这是"编辑即重置"约束的实现
- 对 `draft` 状态的案例执行 `edit` → 不触发状态变更，仅更新字段
- CASE-03 驳回操作写入 `status=rejected` → 由 CASE-03 模块通过共享 `case_repository` 或调用本模块的接口执行

**CASE-03 边界**：本模块不负责 `pending_review→approved` 的流转。审核通过后的状态（`approved`）由 CASE-03 管理。本模块与 CASE-03 的交互通过共享 `cases` 表的数据契约实现——CASE-03 读取 `status=pending_review` 的案例列表，审核完成后写入 `status` 变更。

### 1.5 设计原则兑现清单（技术视角）

| 原则来源 | 原则内容 | 技术响应 |
|----------|----------|----------|
| 项目结构 §5.3 | Router→Service→Repository 分层 | `apps/api-server/app/api/v1/cases.py` 仅负责路由和参数解析；`case_service.py` 负责业务逻辑（状态转换、校验链、业务规则）；`case_repository.py` 负责数据库操作。层间通过接口调用，不跨层访问 |
| 项目结构 §三 | 前后端契约先行 | 在 `packages/py-schemas` 和 `packages/ts-shared` 中同步定义 Schema 和枚举，保证前后端类型一致性。`CaseCreateRequest` 的字段校验规则在两端对齐 |
| 项目结构 §6.1 | L1a/L1b 硬隔离 | 前端 `views/cases/` 仅接收 Props 渲染 UI，不含 API 调用；`logics/cases/` 通过 `caseFormStore`（Zustand）管理状态和 API Service 调用 |
| ADR-004 | 模块化单体边界纪律 | CASE-01 通过 `case_repository` 访问 `cases` 表，通过 `require_role` Depends 消费 AUTH-04 的鉴权服务。不直接读取其他模块的数据库表，不绕过 Depends 链进行权限校验 |
| 技术栈设计 §5 | Pydantic v2 全量校验 | 所有 API 入参通过 Pydantic v2 BaseModel 强校验，不合法参数返回 422，不进入 Service 层 |
| 技术栈设计 §6.3 | 可观测性 | 关键动作（提交审核、PII 确认、状态变更、异常）通过 `packages/py-logger` 记录结构化日志，包含 `trace_id`、`user_id`、`case_id` |
| ADR-005 | 成本敏感 | LLM 自动提取（L1→L2）使用轻量模型，用户主动触发而非每次录入自动调用；表单自动保存为客户端本地存储，零后端写入成本 |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| L1-L2 物理存储 | 单表（cases 表原生列） | 双表外键关联 / JSONB 聚合字段 | L1 和 L2 在录入时作为整体提交，无不独立的一对多关系；原生列支持数据库级约束和索引，查询效率最优；一对多关系由 CASE-04/CASE-05 通过外键扩展，不影响当前存储设计 |
| 编辑冲突处理 | 乐观锁（updated_at 比对） | 悲观锁（数据库行锁 / Redis 分布式锁） | 1-3 人团队并发编辑概率极低；乐观锁无锁开销、无死锁风险、实现简单；悲观锁引入了不必要的锁管理复杂度 |
| PII 检测算法 | 正则表达式匹配 5 类 PII | NLP 模型 / LLM 意图识别 | 意图文档定为"辅助提示"而非强制阻断；正则覆盖常见中文 PII 模式且零外部依赖；NLP 方案作为后续增强扩展点预留接口 |
| 表单自动保存 | 客户端 localStorage 单草稿 | 服务端自动保存 / 多草稿历史 | MVP 阶段最小可行选择；本地存储避免后端写入开销；不跨设备同步的假设与专家单设备录入场景一致；多草稿和过期清理可通过配置参数后续扩展 |
| LLM 提取触发 | 异步（按钮触发 + 3 秒停止输入） | 同步（提交流程中强制提取） | 异步不阻塞提交流程；用户可主动控制是否使用提取功能；避免同步提取延迟影响提交体验 |
| 案例 ID 格式 | `CASE-YYYY-NNNN` + 数据库序列 | UUID / Snowflake | 意图文档 §1.6.2 明确格式要求；数据库序列保证唯一性；年度重置避免 ID 过长；当前规模（年 <9999 条）5-10 年内无溢出风险 |
| 附件引用存储 | `list[AttachmentRef]` JSON 数组 | 独立附件关联表 | 意图文档明确"仅存储引用路径"；JSON 数组无额外表开销，支持排序和遍历；与 CASE-02 通过 AttachmentRef 结构解耦 |

> 决策 #1 #2（PII 前端展示位置、草稿生命周期）：这 2 项涉及用户体验偏好超过纯技术边界，标记为业务矛盾。当前选择：PII 检测结果以列表形式在提交按钮附近逐条展示（方案简单，不升级编辑器）；草稿仅保留最新一份、不自动过期。这两项在用户反馈后调整成本低，适合 MVP 先行、迭代优化。

### 1.7 注意事项与禁止行为（设计层面）

1. **[Depends 链顺序]** 路由端点声明 Depends 时，`get_current_user` 必须出现在 `require_role` 之前。错误示例：`Depends(require_role(min_level=UserRole.TEACHER)), Depends(get_current_user)`。CASE-01 的案例录入路由必须消费 `request.state.user` 获取 author_id。

2. **[设计边界]** 本模块不负责以下事项，禁止在本模块代码中实现：
   - 审核流程的状态流转判定（归属 CASE-03）——本模块仅管理 draft/pending_review/rejected 三态，approved 后的状态不属于本模块
   - 案例文本的切片与向量化入库（归属 CASE-04）
   - 案例版本的迭代历史管理（归属 CASE-05）
   - 案例的失效标记与强制下架（归属 CASE-06）
   - 从多案例提炼标准化模板（归属 CASE-07）
   - 附件文件的上传与存储（归属 CASE-02）——本模块仅维护引用路径列表

3. **[PII 脱敏硬约束]** 提交审核前必须执行 PII 检测，检测到疑似 PII 时必须向用户展示 warning 列表并等待确认。禁止在检测到 PII 后静默通过或自动脱敏——脱敏决策必须由用户做出，确认操作必须记录到审计日志。

4. **[编辑即重置约束]** `update_case()` 中状态重置逻辑必须在字段更新之前执行（同一事务内）。禁止异步执行状态重置，禁止仅在特定字段变更时才触发重置——意图文档 §1.11 约束 3 要求"任何对案例内容的修改"均触发。

5. **[四段式强绑定约束]** 四个字段（immediate_action、comforting_phrase、observation_metrics、medical_criteria）必须在 Service 层校验全部非空后方可提交。禁止允许部分留空通过——意图文档 §1.11 约束 4 明确"这是案例被 RAG 检索消费的质量底线"。

6. **[禁止绕过权限校验]** 所有 CASE-01 端点必须在路由装饰器或 Depends 中显式声明 `require_role(min_level=UserRole.TEACHER)`。禁止跳过角色校验直接访问 Service 层。

### 1.8 引用：配套意图文档

- **意图文档**：`CASE-01-案例录入管理-意图文档.md`
- **冻结时间**：`2026-05-27 09:11:39`
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。技术决策报告（`.tmp/reports/tech-decision-report-CASE-01.md`）中的 18 项自主决策均已在本文档中转化为设计描述或架构权衡记录。2 项业务矛盾（PII 展示位置、草稿生命周期）按技术决策报告的推荐方案做出最佳推断，标注为 MVP 选择、后续可迭代。如有歧义，以意图文档为准。
