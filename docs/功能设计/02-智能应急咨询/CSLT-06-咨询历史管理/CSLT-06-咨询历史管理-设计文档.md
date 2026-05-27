## 1 功能点：CSLT-06 咨询历史管理 — 设计文档（瘦身版）

> **文档生成时间**：`2026-05-27 17:42:40`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-27 17:42:40` | AI Assistant | 初始版本，基于 s06 技术预研报告（8 项自主决策）和已冻结意图文档 v2.0 全量生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `CSLT-06-咨询历史管理-意图文档.md`（已冻结于 `2026-05-27 17:02:44`）
> - 本模块的精确编码规格见 `CSLT-06-咨询历史管理-落地规范.md`

### 1.1 技术实现思路

咨询历史管理采用**纯 CRUD + append-only 归档**的核心模式，是应急咨询流程末端的记录存档节点。

**为什么是纯 CRUD 而非事项驱动的复杂服务**：本模块的职责边界非常单一——接收一次完整咨询的上下文数据，将它写入一张表；按用户和时间筛选读取。与工单流转（TICK-01 需要状态机）或危机分级（CSLT-01 需要多层判定流水线）不同，咨询历史既不需要异步流程编排，也不需要跨模块事务协调。引入 Service 层的事件总线或 CQRS 模式在此场景下属于过度设计——一张表 + 两个查询端点足以覆盖全部功能。

**append-only 的设计含义**：咨询记录一旦写入就不再允许修改或删除。这带来三个设计简化：
- 无需实现 UPDATE/DELETE 端点，减少 API 面和权限校验面的暴露
- 无需乐观锁或悲观锁（不会出现并发写入同一条记录的场景，每条记录由独立的 `request_id` 标识）
- 列表查询可稳定使用 `consultation_time DESC` 排序，不受"插入到历史中间"的写入模式干扰——这正是选择 **offset 分页**而非 cursor 分页的技术前提（详见 §1.6）

**幂等写入通过 PostgreSQL UNIQUE 约束实现**：CSLT-08 编排层在每次咨询开始前生成一个 UUID 作为 `request_id`，随归档请求传入。`consultations` 表设置 `request_id UNIQUE NOT NULL`。写入使用 `INSERT ... ON CONFLICT (request_id) DO NOTHING RETURNING *`——若已存在（如前一次写入因网络超时导致前端重试），直接返回已有记录。此方案的优势在于：
- 幂等逻辑由数据库唯一约束天然保障，不依赖应用层分布式锁
- `DO NOTHING` 避免额外 SELECT 查询（若 RETURNING 返回空行，再执行一次 SELECT 获取已有记录）
- 无需在 Redis 中维护"request_id → 归档状态"的映射表

**为什么不用 Redis 缓存详情查询**：单行 PK 索引查询在 PostgreSQL 上的耗时通常 < 5ms（局域网环境），远低于意图文档要求的 200ms。引入 Redis 缓存层会增加缓存失效策略（记录是 append-only、永不修改，缓存失效似乎不是问题——但 `has_feedback` 标记会被 QUAL-03 更新，产生脏缓存风险）、序列化开销（GenerationResult 的 `generated_plan` 字段最大 65536 字符的 Markdown 文本反序列化成本不可忽略）和运维复杂度。在数据量达到每用户数万条记录之前，PK 索引查询是最好的方案。

**Token 消耗数据作为独立 INTEGER 列存储**：`token_input` 和 `token_output` 存储为 INTEGER NULLABLE 列，而非 JSONB 嵌套字段。理由：token 数据是固定类型的标量值（整数），用独立列直接支持 QUAL-04 的 SQL 聚合查询（`SUM(token_input + token_output) WHERE user_id = $1 AND consultation_time BETWEEN ...`），无需在应用层解析 JSONB。阻断场景（重度危机仅输出安全提示，未调用 LLM）下两字段为 NULL，语义清晰。

**设备信息作为可选 JSONB 字段**：`device_info` 列存储 `{platform, device_brand, os_version, app_version}` 四个可选字段，全字段 nullable。选择 JSONB 而非独立列的理由：设备信息的结构可能在迭代中变化（如新增 `network_type` 字段），JSONB 允许 schema-less 扩展无需 ALTER TABLE；且设备信息仅用于偶发的运维排查（如定位仅特定平台出现的问题），不是日常查询的热字段，JSONB 的查询性能劣势可接受。

**核心技术流程**：
1. 鉴权校验：通过 AUTH-04 的 `get_current_user` 验证请求用户身份，确保 `user_id` 与 JWT 中的 `sub` 一致
2. 写入路径：接收 `ConsultationHistoryCreate` 数据 → Pydantic 校验 → `INSERT ... ON CONFLICT DO NOTHING` → 返回已归档记录
3. 列表查询路径：接收分页参数 → `SELECT ... WHERE user_id = $1 ORDER BY consultation_time DESC LIMIT $2 OFFSET $3` → 组装 `PaginatedResponse`
4. 详情查询路径：接收 `record_id` → `SELECT ... WHERE id = $1 AND user_id = $2` → 若行不存在或 user_id 不匹配 → 统一返回 404

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：
  - CSLT-01 危机分级判定-设计文档.md + 落地规范.md（已冻结）
  - CSLT-02 RAG语义检索-设计文档.md + 落地规范.md（已冻结）
  - CSLT-03 应急方案生成-设计文档.md + 落地规范.md（已冻结）
  - AUTH-01~06 认证授权系列-落地规范.md（已冻结）
  - PROF-01/05 个性化档案系列-落地规范.md（已冻结）
  - KNOW-01 科普内容管理-落地规范.md（已冻结）
  - OBS-01/04 结构化日志/健康检查-落地规范.md（已冻结）
  - SEC-01/04/05 安全与合规系列-落地规范.md（已冻结）
  - DEPLOY-01~05 部署运维系列-落地规范.md（已冻结）
  - CASE-01/04 案例管理系列-落地规范.md（已冻结）
  - docs/contracts/CSLT-03/GenerationResult.json（maturity: draft）
  - docs/contracts/CSLT-03/GenerationStatus.json（maturity: draft）
  - docs/contracts/CSLT-01/CrisisLevel.json（maturity: draft）

- **兼容性结论**：**无冲突**。
  - CSLT-06 作为下游消费方，对 CSLT-03 的 `GenerationResult` 契约（含 `text`、`source_list`、`disclaimer`、`confidence_score`、`is_partial`、`referenced_slice_ids`、`finish_reason`、`ttft_ms`、`generation_time_ms`）为只读消费。本模块的 `ConsultationHistoryCreate` 输入字段与 `GenerationResult` 的属性一一对应，不重新定义任何类型——危机等级使用 CSLT-01/CrisisLevel 枚举（mild/moderate/severe），生成状态使用 CSLT-03/GenerationStatus 枚举。
  - 对于 `confidence_score`，CSLT-03 输出类型定义为 `float`，本模块存储时转换为 PostgreSQL `DECIMAL(3,2)` 以确保精度一致性。转换发生在数据持久化层，不影响契约兼容性。
  - CSLT-06 新增的两个 API 端点（`GET /api/v1/consultations` 列表查询、`GET /api/v1/consultations/{id}` 详情查询）不与任何已有模块的 API 路径冲突。权限校验复用 AUTH-04 的 `get_current_user` Depends 和 PROF-05 的 `AccessRequest`/`AccessDecision` 隐私控制模式。
  - 本模块引入的 `request_id` 幂等键由上游 CSLT-08 生成——CSLT-08 在咨询开始前生成 UUID 并在全链路（CSLT-01 → CSLT-02 → CSLT-03 → CSLT-05）中携带，归档时作为去重依据。此设计不要求 CSLT-03 或任何已有模块修改其接口。

- **复用的已有设计**：
  - `CSLT-01/CrisisLevel` 枚举（mild/moderate/severe）— 存储咨询的危机等级标签，透传而非重新定义
  - `CSLT-03/GenerationResult` 数据类型 — 归档数据的核心来源，消费其全部 9 个字段
  - `CSLT-03/GenerationStatus` 枚举 — 存储生成结束原因（COMPLETE/PARTIAL/BLOCKED/TIMEOUT/ERROR）
  - `AUTH-04/get_current_user` Depends — 列表和详情查询的身份校验，确保用户仅能查看自己的历史
  - `AUTH-04/UserRole` 枚举 — 预留管理员运维通道的权限校验
  - `PROF-05/AccessRequest`/`AccessDecision` — 数据隔离的隐私控制模式参考
  - `packages/py-db` — SQLAlchemy ORM 模型、AsyncSession、Alembic 迁移
  - `packages/py-schemas` — Pydantic 基础类型（BaseModel、UUID 校验）
  - `packages/py-logger` — 结构化日志（trace_id 贯穿、异常记录）
  - `packages/py-config` — 统一配置管理（数据库连接、分页参数默认值）
  - `packages/py-infra` — AppException 异常基类（统一错误处理中间件）
  - 项目级共享分页类型 `PaginatedResponse`（已被 PROF-01/KNOW-01 复用）

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| PostgreSQL 17.x（via py-db） | 存储读写 | `consultations` 表：写入归档记录（INSERT ... ON CONFLICT）、按用户分页查询（SELECT + ORDER BY + LIMIT/OFFSET）、按 ID 查详情（SELECT by PK + user_id 过滤）。索引策略：`(user_id, consultation_time DESC)` 复合索引驱动列表查询；`(request_id)` UNIQUE 索引驱动幂等；`(id)` 为 UUID PK 自带索引 |
| CSLT-03（应急方案生成） | 上游数据来源 | 消费 `GenerationResult` 契约的全部字段（text, source_list, disclaimer, generation_time_ms, is_partial, referenced_slice_ids, finish_reason, ttft_ms）。由 CSLT-08 编排层在咨询流程完成后一并传入本模块，本模块不直接调用 CSLT-03 的 API |
| CSLT-08（咨询编排逻辑） | 上游触发写入 | 前端编排层在每次咨询流程完成后，将 CSLT-01 CrisisJudgmentResult + CSLT-02 SemanticSearchResult + CSLT-03 GenerationResult + 用户输入组装为 `ConsultationHistoryCreate`，调用本模块 `POST /api/v1/consultations` 归档。同时负责生成 `request_id`（UUID）并全链路携带 |
| AUTH-04（五级RBAC鉴权） | 权限校验依赖 | 列表查询和详情查询端点使用 `Depends(get_current_user)` 校验身份。`user_id` 从 JWT Token 中提取，确保用户只能查询自己的咨询历史。管理员运维通道（预留）使用 `require_role(["admin", "maintainer"])` 鉴权 |
| QUAL-03（用户反馈收集） | 下游数据消费 + 回写 | 反馈收集以本模块的记录 ID 为锚点。QUAL-03 在用户提交反馈后通过 API 回调更新本模块的 `has_feedback` 标记（具体接口待 QUAL-03 设计时协商）。当前默认 `has_feedback = false` |
| QUAL-04（Token用量追踪） | 下游数据消费 | 读取本模块记录的 `token_input` 和 `token_output` 字段，按 `user_id` + 时间段聚合为 Token 消耗统计。通过 SQL 聚合查询（`SUM(token_input + token_output)`）实现，不通过 API 逐条读取 |
| TICK-01（工单自动生成） | 下游数据消费 | 创建工单时读取本模块存储的咨询上下文（脱敏后的 `behavior_description` + `generated_plan`），继承到工单的「业务背景」字段中 |
| packages/py-db | 框架依赖 | ORM 模型定义（`models/consult.py` 新增 `ConsultationHistory` 类）、Repository 层封装（`repositories/consult_repository.py`）、Alembic 迁移脚本 |
| packages/py-schemas | 框架依赖 | Pydantic DTO 定义（`schemas/consult.py`），输入校验（`ConsultationHistoryCreate`）、输出序列化（`ConsultationHistoryListItem`、`ConsultationHistoryDetail`） |
| packages/py-logger | 框架依赖 | 记录归档写入、详情查询耗时、权限拒绝（内部日志记录实际拒绝原因）、重复归档请求等结构化事件 |
| packages/py-config | 框架依赖 | 读取 `HISTORY_PAGE_SIZE_MAX`（默认 100）、`HISTORY_PAGE_SIZE_DEFAULT`（默认 20）等分页配置参数 |
| Prometheus（via prometheus-fastapi-instrumentator） | 可观测性 | 暴露 `/metrics` 端点指标：写入请求计数、列表/详情查询耗时 Histogram、重复归档请求计数 |

### 1.4 状态机设计

本功能点不涉及状态流转，故无需状态机。

咨询历史记录一旦归档存储即为只读，不支持用户自行修改或删除。记录的生命周期为：

```
归档存储 → [只读查询] → 按数据保留策略清理（由 QUAL-05 统一管理）
```

`has_feedback` 标记不构成状态机——它只是一个布尔属性，由 QUAL-03 在用户提交反馈后更新（false → true 单向变化），不驱动任何后续流程或状态转换。前端可根据此标记在列表摘要中展示"已反馈"/"未反馈"图标，但这属于展示层逻辑，不在本模块的数据层建模为状态。

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| 单一职责 | 模块仅做"归档存储+查询回溯" | 本模块不负责应急方案生成（CSLT-03）、不负责咨询流程编排（CSLT-08）、不负责反馈收集逻辑（QUAL-03）、不负责 Token 聚合统计（QUAL-04）、不负责工单内容生成（TICK-01）、不负责数据保留清理（QUAL-05）。仅聚焦于将咨询上下文持久化并提供高效的按用户按时间查询接口 |
| 数据隔离 | 用户仅能查看自己的数据 | 列表和详情查询的 WHERE 条件中强制包含 `user_id = $current_user_id`（从 JWT 提取），而非依赖前端传入的 user_id 参数。详情查询即使命中 ID，若 user_id 不匹配，统一返回 404「记录不存在或无权查看」，不区分两种情况的 HTTP 状态码 |
| 性能优先 | 详情 ≤ 200ms，列表 ≤ 500ms | 详情查询：UUID PK 索引 + user_id 过滤（Index Only Scan），预期 < 10ms。列表查询：`(user_id, consultation_time DESC)` 复合索引 + LIMIT 20，预期 < 50ms。两者均远低于目标阈值，MVP 阶段无需缓存层 |
| 失败透明 | 异常信息充分暴露 | 写入失败（字段缺失）返回 422 + 字段级错误提示；权限拒绝返回统一 404 + 内部日志记录实际原因；数据库不可用返回 503 + trace_id。所有异常遵循项目统一错误格式 `{"detail": "...", "error_code": "...", "trace_id": "..."}` |
| 幂等保障 | 重复归档请求不产生重复记录 | `request_id` UNIQUE 约束 + `INSERT ... ON CONFLICT DO NOTHING`。同一 request_id 的重复请求直接返回已归档记录，HTTP 200（而非 409），对上游透明的幂等语义 |
| 可观测性 | 查询与写入过程全透明 | 每个请求标记 trace_id 贯穿全链路；归档写入记录 INFO 日志（含 request_id、user_id、consultation_time）；权限拒绝记录 WARNING 日志（含实际原因）；重复归档记录 INFO 日志（含 request_id）；列表/详情查询耗时暴露 Prometheus Histogram |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 分页方式 | offset 分页（page + page_size） | cursor 分页（基于 consultation_time 游标） | 咨询记录为 append-only 数据（无中间插入/删除/更新），offset 分页不存在"翻页过程中新记录插入导致数据重复或遗漏"的经典问题。cursor 分页在此场景下无优势，且需要客户端维护游标状态，增加前端复杂度。与项目现有 PROF-01/KNOW-01 的 offset 分页模式保持一致 |
| 详情查询缓存 | 无缓存（直接 PK 查询） | Redis 缓存近期记录 | 单行 UUID PK 索引查询耗时 < 5ms，远低于 200ms 目标。引入 Redis 增加缓存失效风险（`has_feedback` 被 QUAL-03 更新后缓存成为脏数据）、序列化/反序列化开销和运维复杂度。仅在性能基准测试显示 > 50ms 时再考虑缓存 |
| Token 存储 | 独立 INTEGER 列（token_input, token_output） | JSONB 扩展字段 | INTEGER 列直接支持 QUAL-04 的 SQL 聚合查询（SUM），避免 JSONB 键值查询的性能开销。两字段固定类型，不需要 JSONB 的灵活性。阻断场景下为 NULL，语义清晰 |
| 设备信息存储 | JSONB 列（device_info, nullable） | 独立列（platform VARCHAR, device_brand VARCHAR, …） | 设备信息字段可能在迭代中变化（新增 network_type、screen_size 等），JSONB 允许 schema-less 扩展无需 ALTER TABLE。且设备信息仅用于偶发运维排查，非热查询字段，JSONB 性能劣势可接受。所有子字段 nullable，不影响归档核心流程 |
| 行为描述截取 | 后端返回完整文本，前端截取 50 字 | 后端预计算 snippet 字段 | 截取长度属于展示逻辑，应归属前端控制。后端存储完整数据避免冗余字段，同时为未来不同的截取策略（如小程序 30 字、H5 50 字）保留灵活性。按项目结构 §9.4 的前后端分层原则，展示细节不应侵入数据层 |
| 幂等实现 | PostgreSQL UNIQUE 约束 + ON CONFLICT DO NOTHING | Redis 分布式锁 + SELECT-then-INSERT | 数据库 UNIQUE 约束是单节点写幂等的最简单可靠方案，无需额外基础设施。Redis 锁方案需要处理锁超时、锁释放、Redis 不可用的降级路径——在不需要跨节点并发控制的场景下属于过度设计 |
| has_feedback 标记 | 默认 false + QUAL-03 API 回调更新 | JOIN feedbacks 表实时查询 | 前者实现简单（一个布尔列 + 一个 PATCH 端点），前端列表查询无需 JOIN。后者虽然解耦 CSLT-06 与 QUAL-03 的写入关系，但增加了每次列表查询的 JOIN 开销。当前选择前者，若未来反馈表结构复杂化再改为 JOIN 方案（向后兼容——仅需修改查询 SQL，无需迁移数据） |
| 数据保留策略 | 当前设计永久保留，QUAL-05 后续定义清理策略 | 在 MVP 阶段设定固定保留期（如 180 天） | 意图文档 §1.11 #5 明确将保留周期划归 QUAL-05 管理，本模块不单独定义清理规则。MVP 阶段无物理删除逻辑，避免过早引入清理任务维护负担——所有记录仅通过 SQL 查询的 WHERE 条件过滤（如 QUAL-05 未来提供 `retention_cutoff` 参数），不执行 DELETE |

### 1.7 注意事项与禁止行为（设计层面）

1. **[约束 1 -- 受意图文档§1.11约束]** 咨询记录一旦归档即为只读，不支持用户自行修改或删除。技术实现上不暴露 PUT/PATCH/DELETE 端点。任何数据修正需求仅限系统管理员通过运维通道操作（预留 `/admin/consultations/{id}` 管理端点，受 AUTH-04 `require_role(["admin"])` 保护）。

2. **[约束 2 -- 受意图文档§1.11约束]** 家属仅能查看本人账号下的咨询历史。列表查询和详情查询的 WHERE 条件中必须强制包含 `user_id = $current_user_id`（从 JWT Token 的 `sub` 字段提取），不得接受前端传入的 user_id 作为过滤条件。详情查询即使 ID 存在但 user_id 不匹配，对外统一返回 404「该咨询记录不存在或无权查看」——不得区分「不存在」和「无权查看」两种情况的 HTTP 状态码。

3. **[约束 3 -- 受意图文档§1.11约束]** 单次详情查询响应时间不可超过 200ms。技术实现上不允许在详情查询时执行额外的外部 API 调用——所有数据必须直接从 `consultations` 表读取，单次 SELECT 查询返回完整记录。

4. **[约束 4 -- 受意图文档§1.6.1约束]** 归档时的 `behavior_description` 字段长度约束为 1-2000 汉字符。Pydantic 校验应在 Service 层通过 `Field(min_length=1, max_length=2000)` 实现，数据库层使用 `VARCHAR(2000)` 作为辅助约束。

5. **[约束 5 -- 受意图文档§1.6.1约束]** `disclaimer` 字段的归档值必须与 CSLT-03 输出的 `GenerationResult.disclaimer` 原文完全一致——即固定文本"以上建议由 AI 生成，仅供参考，不构成医疗诊断或治疗建议。如情况紧急，请立即联系专业医疗机构。"。归档写入时应对此字段做等值校验，防止上游传入了被篡改的免责声明文本。

6. **[易错点 1]** `is_partial=true` 的记录在详情查询中应包含明确的标记字段，供前端展示"部分生成"提示。但此记录仍需与其他完整记录一样在列表中可见——不可因为 `is_partial=true` 就将记录从列表中隐藏或降序到末尾。部分生成的结果仍然包含有效的参考信息，用户有权回溯查看。

7. **[易错点 2]** 列表查询的分页参数 `page` 为 1-based。当 `page > total_pages` 时，应返回 `items: []` + 正确的 `total` 和 `total_pages`，而非 400 错误。空列表是正常的分页边界情况，不应作为异常处理。

8. **[易错点 3]** `request_id` 幂等键由 CSLT-08 编排层生成并传入，本模块仅做存储和冲突检测。不得在 Service 层自行生成 `request_id`——这会导致每次重试都产生不同的 request_id，幂等逻辑完全失效。如果上游未传入 `request_id`，应返回 422 字段缺失错误而非静默生成。

9. **[设计边界]** 本模块不负责：
   - 应急方案内容的生成（CSLT-03）
   - 咨询流程的编排和状态管理（CSLT-08）
   - 用户反馈的发起逻辑和问卷展示（QUAL-03）
   - Token 消耗数据的聚合统计和可视化（QUAL-04）
   - 工单内容的生成和业务逻辑（TICK-01）
   - 数据保留策略的定义和清理任务调度（QUAL-05）
   - 行为描述的 PII 脱敏（上游 CSLT-08 / SEC-03 已完成）

10. **[禁止行为]** 禁止在详情查询中对 `generated_plan`（四段式方案全文）做任何二次加工、截断或格式化。必须原样返回归档时的完整 Markdown 文本——即使文本长度超过前端展示区域的合理范围，截取和折叠逻辑属于前端展示层职责。

11. **[禁止行为]** 禁止绕过 `packages/py-db` 的 Repository 层直接操作数据库。所有查询必须通过 `ConsultHistoryRepository` 类封装，确保 `user_id` 的强制注入不遗漏、分页参数校验统一执行、异常转换为项目标准错误格式。

12. **[禁止行为]** 禁止在列表查询中使用 `SELECT *`——列表只需要 4 个字段（id, consultation_time, behavior_description, crisis_level, has_feedback）。返回完整 `generated_plan`（最大 65536 字）到列表中会严重浪费带宽和序列化时间。

### 1.8 引用：配套意图文档

- **意图文档**：`CSLT-06-咨询历史管理-意图文档.md`
- **冻结时间**：`2026-05-27 17:02:44`
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义完全一致。所有 6 项业务约束（数据完整性、隐私隔离、只读约束、性能约束、数据保留、设计边界）均在技术方案中得到兑现。8 项技术决策（意图文档 §1.12）已通过 s06 技术预研确定并在本设计文档各节中落实。2 项业务矛盾（数据保留策略归属 QUAL-05、反馈标记来源待 QUAL-03 定义）已在技术方案中做出合理推断并标注处理方式。如有分歧，以意图文档为准。
