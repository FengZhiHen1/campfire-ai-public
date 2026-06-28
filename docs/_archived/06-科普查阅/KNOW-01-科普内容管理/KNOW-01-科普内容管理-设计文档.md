## 1 功能点：KNOW-01 科普内容管理 — 设计文档（瘦身版）

> **文档生成时间**：2026-05-26 17:05:58 (Asia/Shanghai)
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 17:05:58 | AI Assistant | 初始版本，基于技术决策报告（s06）和意图文档 v2.0 生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `KNOW-01-科普内容管理-意图文档.md`（已冻结于 2026-05-26 16:54:49）
> - 本模块的精确编码规格见 `KNOW-01-科普内容管理-落地规范.md`

### 1.1 技术实现思路

科普内容管理是一个典型的 CRUD 型后台管理模块，其技术实现的核心理念是"薄服务层 + 标准基础设施"——不引入额外框架或复杂抽象，充分利用项目已有的 PostgreSQL、FastAPI 和项目结构规范完成任务。

**数据层设计**：数据模型采用单表 `knowledge_articles` 承载文章的全部字段。关联案例编号使用 PostgreSQL 原生数组列 `VARCHAR(20)[]` 存储（上限 5 条），而非 JSONB 或独立关联表——因为关联案例上限固定且仅需简单存在性校验，数组列比 JSONB 语义更清晰，比关联表更轻量。文章状态使用 `VARCHAR(20)` 字符串存储 Python Enum 值，而非数据库 ENUM 类型——这是项目既有实践，避免跨数据库迁移的 ENUM 兼容性问题。全文检索使用 PostgreSQL ts_vector 列 + GIN 索引，而非引入 Elasticsearch 等独立搜索引擎——项目数据量级为垂直领域中小规模，PostgreSQL 内置全文检索性能完全满足需求，且保持"统一数据层"的模块化单体架构承诺（ADR-004）。

**服务层设计**：核心逻辑为薄服务层（Service Layer），仅负责编排 Repository 调用和输入校验流程，不含复杂的业务规则。状态切换设计为两个独立端点 `POST /api/v1/knowledge/{id}/publish` 和 `POST /api/v1/knowledge/{id}/unpublish`，而非通用 PATCH status 端点——显式语义端点降低了 API 的误用风险，且便于在单个端点内集中处理发布时的时间戳写入、审计日志和缓存失效逻辑。

**MVP 降级策略**：以下能力在 MVP 阶段不做代码实现，但设计上预留扩展点：
- 缓存：文章列表和详情直查数据库，不引入 Redis 缓存层。但 Service 层方法签名设计为可注入可选的 CacheManager 参数（MVP 阶段传入 None）。
- 运营审核：MVP 阶段仅含 published/unpublished 二态，审核由运营管理员在系统外人工完成。设计中不预留 review 状态机的数据库字段——若未来引入审核流程，通过 Alembic 迁移增量添加。
- 关联案例失效清理：采用"实时查询"策略——每次展示文章详情时查询 CASE 模块确认案例有效性，不引入定时任务或缓存快照。惰性标记——仅在案例已失效时标注 `_stale: true`，不自动删除关联。

**全文检索策略**：使用 PostgreSQL ts_vector 列 + zhparser 中文分词扩展。GIN 索引确保查询效率。MVP 阶段使用等权重（title 和 content 权重均为 1.0），预留 A/B/C/D 权重调优接口。搜索关键词高亮由后端在 `content_snippet` 字段中返回 `<mark>` 标记的文本片段，前端直接解析渲染。

**数据一致性保障**：关联案例有效性校验在创建/更新文章时实时查询 `case_repository`，确保"悬空引用"在入库时就已被拦截。对于已有的已发布文章，若其关联案例被删除，文章仍可正常展示，但详情接口返回的 `related_case_ids` 中标注 `_stale: true`。这避免了跨模块的级联删除或数据不一致问题。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：`docs/篝火智答-技术栈设计.md`（v1.2）、`docs/篝火智答-项目结构.md`（v2.0）、`docs/功能设计/原始材料/篝火智答-科普查阅-原始设计意图_v0.md`
- **兼容性结论**：经扫描 `docs/功能设计/` 目录，本项目尚无已落地的规格文档（*-落地规范.md）或契约文件（_contracts.md），KNOW-01 为项目首个进入设计流程的模块，不存在与已有规格的兼容性问题。
  - 技术栈设计 §4.5 中提供的参考 `knowledge_articles` 数据模型与本模块字段定义一致。
  - 项目结构设计 v2.0 预留的目录位置（`apps/api-server/app/api/v1/knowledge.py`、`packages/py-db/py_db/models/knowledge.py`、`packages/py-schemas/py_schemas/knowledge.py`）与本模块的文件归属方案完全匹配。
  - 模块依赖关系分析 §2.6 中识别的 KNOW-01 依赖关系（对 AUTH-04 的权限依赖、对 CASE-01/CASE-03 的校验依赖，被 KNOW-03/KNOW-04/KNOW-06/KNOW-07 消费）均为单向依赖，无循环依赖风险。
- **复用的已有设计**：
  - 项目 `py_db/models/base.py` 的 UUID PK Mixin（含 `id`、`created_at`、`updated_at`）
  - 项目 `py_schemas/common.py` 的通用分页 Schema（`PaginatedResponse`）
  - 项目 `py_db/models/enums.py` 的 Python Enum 枚举存储策略（VARCHAR 存储枚举字符串值）

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| PostgreSQL 17.x + pgvector | 读写 | 唯一直读直写的数据存储。`knowledge_articles` 表通过 SQLAlchemy 2.0 async 操作。ts_vector 列使用 zhparser 中文分词扩展，GIN 索引加速全文检索 |
| Redis 7.x | 预留 | MVP 阶段不引入缓存，不作为运行时依赖。Service 层方法签名预留 `cache_manager: CacheManager | None = None` 参数，未来注入时启用 |
| AUTH-04 五级RBAC鉴权 | 调用 | 所有管理类端点（创建/编辑/下架/发布）需通过 FastAPI Depends `require_role(["admin", "maintainer"])` 注入权限校验。终端用户查询端点（列表/详情/搜索）调用方需自行过滤 `status=published` |
| CASE-01 案例录入管理 | 调用 | 创建/更新文章时，通过 `case_repository.exists(case_ids)` 批量校验关联案例编号是否存在。校验失败时拒绝本次操作并返回无效编号列表 |
| CASE-03 案例审核工作流 | 数据依赖 | 创建/更新文章时，通过 `case_repository.find_approved_ids(case_ids)` 确认关联案例为 `approved` 状态。仅 approved 状态的案例允许关联 |
| KNOW-03 全文检索 | 下游数据消费 | 本模块维护 `knowledge_articles.search_vector` ts_vector 列，KNOW-03 直接查询此列执行中文分词检索 |
| KNOW-04 案例关联推荐 | 下游数据消费 | 本模块返回文章中的 `related_case_ids` 字段，KNOW-04 基于此列表查询 CASE-01 获取关联案例的标题和循证等级 |
| KNOW-06 科普查阅界面 | 下游数据消费 | 消费本模块的 `GET /api/v1/knowledge`（分类列表+分页）和 `GET /api/v1/knowledge/{id}`（文章详情） |
| KNOW-07 科普交互逻辑 | 下游数据消费 | 消费本模块的 `GET /api/v1/knowledge/search?q={keyword}`（全文检索） |

精确的函数签名、SQLAlchemy 查询和接口参数见落地规范。

### 1.4 状态机设计（技术实现策略）

KNOW-01 文章状态为简单的二态模型，无复杂状态流转：

```
unpublished ────publish───▶ published
    ◀──unpublish─────────────
```

**状态定义**：
- **unpublished（下架）**：文章创建时的默认状态。对终端用户不可见，仅管理员在管理端可查看和编辑。出现在管理端的全部文章列表中。
- **published（公开）**：文章对全部用户（家属、老师、专家）可见，出现在分类列表和搜索结果中。

**技术实现策略**：

| 维度 | 决策 |
|------|------|
| 持久化方案 | `KnowledgeArticle.status` 列：`VARCHAR(20)`，NOT NULL，默认值 `"unpublished"`。应用层使用 Python `ArticleStatus` Enum 约束取值 |
| 切换操作 | 提供两个独立端点 `POST /api/v1/knowledge/{id}/publish` 和 `POST /api/v1/knowledge/{id}/unpublish`，非通用 PATCH status 端点——显式语义降低误用风险 |
| 幂等策略 | 当前已是目标状态时返回 200 OK，不做错误处理（如已 published 再次 publish 不报错） |
| 发布时间 | 首次 publish 操作写入 `published_at` 为当前时间戳（`TIMESTAMPTZ`），后续 unpublish→publish 的重新发布不更新此字段。语义为"首次公开时间"，与意图文档定义一致 |
| 查询过滤 | 面向终端用户的列表和搜索接口在 Service 层自动追加 `status=published` 过滤条件。管理端接口通过 `status` 参数控制查询范围（默认不限制，允许管理员查看全部状态） |
| 审计记录 | 状态变更操作记录结构化日志（`py-logger`，含 `trace_id`、操作人 ID、变更前后状态、时间戳） |

### 1.5 设计原则兑现清单（技术视角）

| 原则来源 | 原则说明 | 技术响应 |
|----------|----------|----------|
| ADR-004 模块化单体 | 按 Python package 划分模块边界，模块间通过标准化接口通信 | KNOW-01 作为独立 package，仅通过 `case_repository` 接口访问 CASE 模块，不直接操作 CASE 模块的数据库表。对外暴露的 API 由下游模块通过 HTTP 调用消费 |
| ADR-004 统一数据层 | 所有模块共享 PostgreSQL 数据源 | KNOW-01 的 `knowledge_articles` 表与项目其他表位于同一 PostgreSQL 数据库，共享连接池和事务管理。ts_vector 全文检索同样复用 PostgreSQL 内置能力 |
| 技术栈设计 §5 输入校验 | Pydantic v2 全量校验 + PostgreSQL 参数化查询 | 所有 API 请求体通过 Pydantic BaseModel 强校验（ArticleCreate/ArticleUpdate/ArticleSearchParams），数据库查询全部使用 SQLAlchemy 参数化查询 |
| 项目结构 §5.3 层间依赖规则 | L1b → L1 → L2 的严格单向依赖 | KNOW-01 的后端代码仅依赖 L2 共享能力层（packages/py-db、packages/py-schemas、packages/py-cache），不反向依赖 L1b 前端逻辑或 L1a 表现层 |
| 意图文档 §1.11 约束 5 设计边界 | 本模块不负责 AI 生成、搜索算法调优、案例推荐排序 | 全文检索仅提供 ts_vector 基础设施，搜索排序和分词权重调优归属 KNOW-03。案例推荐排序逻辑归属 KNOW-04，本模块仅提供 `related_case_ids` 原始数据 |
| 意图文档 §1.11 约束 6 无外部链接依赖 | 文章内容自包含 | 正文字段为纯文本（TEXT 类型），不解析也不存储外部 URL 或嵌入资源。若未来引入配图，通过 MinIO 预签名 URL 管理，不直接嵌入 Base64 |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 全文检索引擎 | PostgreSQL ts_vector + zhparser 扩展 | Elasticsearch 独立搜索引擎 | 项目数据量级为垂直领域中小规模（非百万级文档），PostgreSQL ts_vector 性能足够（查询 < 500ms）。保持"统一数据层"的模块化单体承诺，不引入独立运维组件 |
| 关联案例编号存储 | PostgreSQL 原生数组 `VARCHAR(20)[]` | JSONB / 独立关联表（junction table） | 关联数量上限固定为 5，数组列比 JSONB 语义更清晰（明确告诉数据库这是数组而非结构化 JSON），比关联表更轻量（无额外 JOIN）。GIN 索引可加速 `ANY()` 查询 |
| 状态切换 API 设计 | 独立端点 `publish` / `unpublish` | 通用 `PATCH /{id}` status 字段更新 | 显式端点降低 API 误用风险（在 publish 端点集中处理 published_at 写入、审计日志、缓存失效逻辑）。发布和下架是两种不同业务语义的操作，不应共用同一端点 |
| 关联案例失效处理 | 实时查询 CASE 模块 | 缓存快照 + 定时同步 | 实时查询避免了跨模块数据一致性维护的复杂性（无需缓存失效策略、无需定时同步任务）。关联案例查询是低频操作（仅文章详情页触发），不会造成性能瓶颈 |
| MVP 缓存策略 | 不引入缓存，直查数据库 | Redis 缓存文章列表和详情 | MVP 阶段数据量小（运营人员手动录入，非高并发读取场景），直查 PostgreSQL 性能足够（P95 < 300ms）。缓存作为性能优化项可后延，Service 层预留 CacheManager 注入点 |
| MVP 审核流程 | 无系统内审核，管理员人工审核 | 系统内 review 状态机（draft→pending_review→approved） | 意图文档 §1.8.3 明确要求"发布前由运营管理员人工审核内容合规性"，这表明审核是人工流程而非系统自动化流程。MVP 阶段不引入 review 状态机以保持实现简洁。受意图文档约束 |

### 1.7 注意事项与禁止行为（设计层面）

1. **[约束] 不实现 AI 生成能力**：本模块是科普文章的后台管理 CRUD 节点，不涉及大模型调用或 AI 内容生成。科普问答（KNOW-02）的 RAG 生成能力由 KNOW-02 独立实现。
2. **[约束] 不实现搜索排序算法调优**：本模块仅维护 ts_vector 列作为搜索基础设施。搜索结果的排序权重调优、分词词典选择等策略由 KNOW-03 全文检索模块负责。
3. **[易错点] published_at 不应随重新发布而更新**：`published_at` 语义为"首次公开时间"（意图文档 §1.6.2），重新发布时应保持首次发布时间不变。如需"最近一次发布"信息，应在单独的 `last_published_at` 字段中记录。
4. **[易错点] 同分类下标题唯一性非强制**：意图文档表述为"建议保持唯一"，本模块仅在应用层（Service 层）做非阻塞检查——若同分类下标题已存在，返回 200 OK 并附带警告信息，不拒绝保存。不做数据库 UNIQUE 约束。
5. **[设计边界] 本模块不负责以下事项**：
   - 科普答案的 AI 生成（归属 KNOW-02 科普问答服务）
   - 全文检索的搜索排序算法调优（归属 KNOW-03 全文检索）
   - 案例推荐排序逻辑（归属 KNOW-04 案例关联推荐）
   - 紧急关键词检测与应急引导（归属 KNOW-05 应急场景引导）
   - 科普阅览界面的 UI 渲染（归属 KNOW-06 科普查阅界面）
   - 前端的搜索防抖和 SSE 流式消费（归属 KNOW-07 科普交互逻辑）
6. **[禁止行为] 禁止在正文中嵌入外部链接或资源**：文章正文为纯文本字段，不解析 URL。若未来需要配图或附件，由独立文件管理模块通过 MinIO 预签名 URL 处理。
7. **[禁止行为] 禁止不经过关联案例有效性校验直接写入**：创建/更新文章时必须通过 `case_repository` 校验关联案例的存在性和审批状态，不可绕过校验层直接写入数据库。

### 1.8 引用：配套意图文档

- **意图文档**：`KNOW-01-科普内容管理-意图文档.md`
- **冻结时间**：2026-05-26 16:54:49 (Asia/Shanghai)
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。本模块仅负责科普文章的 CRUD 管理和全文检索基础设施，不越界实现 AI 生成、搜索排序优化或案例推荐算法。如有歧义，以意图文档为准。

---

## 附录：业务矛盾处理记录

以下 8 项来自技术决策报告 §5 的业务矛盾标记，本设计文档按"最佳推断"原则做出处理决策。若用户否决任一决策，该项将回退至下一轮循环中修正。

| # | 矛盾点 | 处理决策 | 理由 |
|---|--------|----------|------|
| 1 | 全文检索权重调优 | MVP 使用等权重（title 和 content 均为 A 权重，值 1.0），zhparser 默认词典，GIN 索引 | 等权重满足 MVP 基本搜索需求，上线后根据实际搜索日志和用户反馈逐步调优。默认词典覆盖通用中文分词，领域词典作为优化项 |
| 2 | 文章列表分页参数 | 默认 `page_size=20`，上限 `page_size<=100`，使用 offset/limit 分页 | 20 条是列表页面的通用默认值，上限 100 防止单次查询数据量过大。offset/limit 分页满足当前数据规模，keyset pagination 作为未来扩展项 |
| 3 | 文章缓存策略 | MVP 不引入缓存，直查数据库。Service 层预留 `cache_manager: CacheManager | None` 参数 | 文章列表和详情为低频读取操作（非高并发场景），直查数据库性能足够。缓存策略待上线后基于实际访问模式分析再引入 |
| 4 | 数据模型技术实现 | ORM 字段类型从技术决策报告 §3.1 类型签名直接推导 | 意图文档的业务字段定义足够精确，类型推导不存在歧义。title→VARCHAR(200)、content→TEXT、related_case_ids→VARCHAR(20)[]、status→VARCHAR(20) |
| 5 | 关联案例失效处理机制 | 实时查询策略：每次展示时通过 `case_repository` 确认案例有效性。惰性标记：失效的关联在响应中标注 `_stale: true` | 避免了缓存快照的数据一致性问题，实现简单。关联案例查询为低频操作（仅详情页触发），不会造成性能压力。定期清理作为未来扩展 |
| 6 | 异常处理技术实现 | 使用 FastAPI HTTPException + 基础 AppException 类。错误响应格式沿用 FastAPI 默认 JSON `{detail: "..."}` | FastAPI 原生异常处理满足 MVP 需求。全局错误处理规范待项目级统一制定后增量对齐，迁移成本低 |
| 7 | 运营审核流程 | MVP 仅含 published/unpublished 二态，审核为管理员人工流程。不预留 review 状态机数据库字段 | 意图文档明确要求"人工审核"，无需系统内审核状态机。若未来引入审核流程，通过 Alembic 迁移增量添加 review 相关字段，不修改现有二态模型 |
| 8 | 响应时间性能目标 | 列表查询 P95 < 300ms，详情查询 P95 < 200ms，全文检索 P95 < 500ms | 参考技术栈设计通用性能指标并结合模块特性细化。列表和详情为单表简单查询（有索引），目标低于通用指标。搜索涉及 ts_vector GIN 索引查询和 rank 排序，预留较大余量 |
