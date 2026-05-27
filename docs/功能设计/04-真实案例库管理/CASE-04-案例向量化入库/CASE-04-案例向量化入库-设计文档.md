## 1 功能点：CASE-04 案例向量化入库 — 设计文档（瘦身版）

> **文档生成时间**：2026-05-27 09:24:46
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-27 09:24:46 | AI Assistant | 初始版本，基于已冻结的意图文档 v2.0 生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `CASE-04-案例向量化入库-意图文档.md`（已冻结，2026-05-27 09:13:07）
> - 本模块的精确编码规格见 `CASE-04-案例向量化入库-落地规范.md`

### 1.1 技术实现思路

本模块实现一条三阶段异步流水线：**投递 → 消费-处理 → 写入**，将审核通过的案例卡片转化为可供 RAG 检索的向量化知识单元。

**为何选择 Redis List + 内嵌 Worker 的异步架构，而非同步写入或独立消息队列**

同步写入（在 CASE-03 审核通过的路由中直接调用向量化逻辑）会阻塞 HTTP 响应导致超时，且审核与索引耦合增加故障面。独立消息队列（Celery + RabbitMQ/Redis）对于 1-3 人团队运维负担过重，且项目已在多处使用 Redis（缓存、Session、限流），无需引入新组件。因此采用 Redis List 作为轻量任务队列：LPUSH 投递、BRPOP 阻塞消费，Worker 作为 asyncio 协程运行在 FastAPI 进程内，通过 lifespan 事件启停。这符合项目模块化单体架构零额外运维负担的设计约束。

**为何采用规则拼接策略而非语义分块器（SemanticChunker）或 LLM 智能分段**

四个文本字段（场景描述、行为表现、干预动作、结果反馈）在案例提交时已作为独立字段存储于 PostgreSQL cases 表，天然分离且语义边界清晰。规则拼接策略直接按 "场景: {}\n行为: {}\n干预: {}\n结果: {}" 模板组装为单个文本块，零计算开销、100% 确定性保证四要素在同一向量切片中。SemanticChunker 基于文本相似度自动分割，可能在"干预动作"和"结果反馈"之间误切；LLM 智能分段引入额外 API 调用成本且存在幻觉风险。两种备选方案均无法满足意图文档对四要素完整性的硬性约束。

**数据流设计**

```
CASE-03 审核通过 → 调用 enqueue_index_task(case_id)
  → 校验案例状态为 approved
  → 校验四段式字段非空
  → 生成 trace_id + 投递任务到 Redis List (LPUSH "index:queue:case_chunks")
  → 返回投递确认（HTTP 同步，< 50ms）

[后台 Worker 异步消费]
Worker 协程 BRPOP 取出任务
  → 阶段1 文本组装：从 cases 表读取四字段 → 模板拼接 → PII 最终校验
  → 阶段2 向量嵌入：调用阿里 text-embedding-v4 → 获取 1024 维向量
  → 阶段3 索引写入：INSERT INTO case_chunks (embedding, chunk_text, metadata)
  → 状态更新：UPDATE cases SET index_status = 'indexed'
```

每个阶段失败均触发独立重试（线性退避：1s → 3s，共 3 次尝试），所有尝试耗尽后状态标记为 indexing_failed。

**降级与容错策略**

当嵌入服务持续不可用时，Worker 不无限阻塞——通过熔断器在连续 5 次失败后暂停消费 30 秒，期间新任务继续入队但不被处理。暂停结束后优先消费最早入队的任务（BRPOP 天然保证 FIFO）。此设计避免了雪崩效应（大量失败任务不断重试耗尽 CPU/网络资源）。

**PII 最终防线**

尽管意图文档声明依赖 SEC-03 的事前脱敏，本模块在文本组装后执行最后一道 PII 校验：利用正则扫描身份证号、手机号、家庭住址模式的残留。命中则拒绝入库并记录告警日志——保证即使上游脱敏遗漏，隐私数据也不进入可被全文检索的向量索引（pgvector 的 chunk_text 字段在检索时会作为上下文返回给 LLM）。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：18 份已有规格文档（AUTH-01~06、PROF-05、KNOW-01、OBS-01、OBS-04、SEC-01、SEC-04、SEC-05、DEPLOY-01~05）、`功能模块全拆解.md`、`模块依赖关系分析.md`、`_contracts.md`、`篝火智答-技术栈设计.md`
- **兼容性结论**：✅ 无冲突。本模块不与任何已有模块共享状态空间、接口命名空间或类型定义。CASE-04 在依赖关系分析中被确认为 L5 业务能力层模块，依赖方向全部为单向（CASE-04 → CASE-01/CASE-03，CSLT-02/CASE-05/CASE-06 → CASE-04）。
- **2 项对齐注意点**（非冲突，已记录至 `_sync-issues.md`）：
  1. 技术栈设计 §4.3 的 case_chunks 表包含 `chunk_type ENUM('scene','behavior','intervention','result')` 字段，该设计预设每个四要素独立为一条切片。本模块采用单一切片策略（四要素合并为一条记录），因此 `chunk_type` 字段在本模块实现中不适用——改为使用 `chunk_text` 包含全部四要素文本，不使用 `chunk_type` 枚举列。若后续有其他模块需要区分切片类型，可重新启用此字段，当前不作为本模块约束。
  2. 技术栈设计 case_chunks 的 `metadata` 字段定义为 `{age_range, behavior_type, emotion_level}`，意图文档要求包含 4 个维度（行为类型、年龄区间、严重程度、循证等级）。本模块采用意图文档的 4 维结构，新增 `severity` 和 `evidence_level` 两个 metadata 键，不影响 pgvector 检索兼容性（JSONB 字段对键名无约束）。
- **复用的已有设计**：
  - CASE-01 定义的 cases 表结构（四段式文本字段、behavior_type 枚举、emotion_level 枚举）
  - CSLT-02 将要使用的 pgvector HNSW 索引基础设施（同库同插件，仅不同表）
  - OBS-01 的结构化日志格式（trace_id 注入、JSON 日志输出到 stdout）
  - SEC-03 的 PII 检测模式（复用正则规则集作为最终防线校验）

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| PostgreSQL (cases 表) | 只读查询 | `SELECT scene_description, behavior_manifestation, intervention_action, result_feedback, behavior_type, emotion_level, applicable_population FROM cases WHERE id = $1 AND status = 'approved'` |
| PostgreSQL + pgvector (case_chunks 表) | 写入 | `INSERT INTO case_chunks (id, case_id, chunk_text, embedding, metadata) VALUES ($1, $2, $3, $4::vector(1024), $5::jsonb)`；表需在建表迁移中创建 HNSW 索引 `CREATE INDEX ON case_chunks USING hnsw (embedding vector_cosine_ops)` |
| Redis 7.x | 异步队列读写 | LPUSH 投递任务 JSON `{"case_id": "...", "trace_id": "...", "enqueued_at": "..."}` 到 `index:queue:case_chunks`；Worker BRPOP 阻塞消费 |
| CASE-01 (案例录入管理) | 上游数据来源 | 消费 cases 表中的四段式文本字段、behavior_type 枚举、emotion_level 枚举、applicable_population JSONB |
| CASE-03 (案例审核工作流) | 上游时序触发 | 审核通过后调用 `indexing_service.enqueue(case_id: UUID) -> None`；本模块提供 Python 函数接口，不暴露独立 HTTP 端点 |
| 阿里 text-embedding-v4 | 外部 API 调用 | `POST /embeddings`，请求体 `{"input": chunk_text, "model": "text-embedding-v4"}`，响应体提取 `data[0].embedding`（1024 维 float32 数组）。超时 5s，使用 httpx AsyncClient with connection pool |
| CSLT-02 (RAG语义检索) | 下游数据消费 | 消费 case_chunks 表的 HNSW 索引执行语义检索；约定 metadata JSONB 中键名 `behavior_type`, `age_range`, `severity`, `evidence_level` 作为过滤字段名 |
| OBS-01 (结构化日志) | 下游横切 | 每个阶段通过 OBS-01 的 `json_logger.info()` 输出结构化日志，自动注入 trace_id；异常场景使用 `json_logger.error()` 并附加 case_id 和 retry_count |
| CASE-05 (案例版本迭代) | 下游时序依赖 | 新版本审核通过后触发本模块重新索引；旧版本索引保留不删除（由 CASE-05 自行管理旧 chunk 的检索排除逻辑） |
| CASE-06 (案例淘汰管理) | 下游数据依赖 | 案例被标记为过时/有误/争议后，CSLT-02 检索时需结合本模块产出的索引数据与 CASE-06 的淘汰标记联合过滤 |

> 精确的函数签名、SQL 查询模板、Pydantic 模型等见落地规范。

### 1.4 状态机设计（技术实现策略）

本模块管理的索引状态是案例 card 粒度（一个案例对应一条索引记录），而非 request 粒度。状态持久化于 cases 表的 `index_status` 列（ENUM 类型，由本模块和数据库迁移脚本共同定义）。

**4 个状态**：
- `pending`（队列等待）：任务已投递至 Redis List，等待 Worker 消费。对应管理端显示 "索引中"（黄色）。
- `processing`（处理中）：Worker 正在执行文本组装、向量嵌入或索引写入。对应管理端显示 "索引中"（黄色）。
- `indexed`（已入库）：索引写入成功并确认可被检索。对应管理端显示 "已入库"（绿色）。
- `indexing_failed`（索引异常）：3 次尝试全部失败后标记。对应管理端显示 "索引异常"（红色）。

```
审核通过(approved)
       │
       ▼
   ┌─────────┐  enqueue   ┌──────────┐  brpop    ┌────────────┐  all_ok   ┌──────────┐
   │ (idle)  │───────────▶│ pending  │──────────▶│ processing │──────────▶│ indexed  │
   └─────────┘            └──────────┘           └────────────┘           └──────────┘
                                │                      │
                                │                      │ retry_exhausted
                                │                      ▼
                                │               ┌─────────────────┐   manual_retry   ┌──────────┐
                                │               │ indexing_failed │────────────────▶│ pending  │
                                │               └─────────────────┘                  └──────────┘
                                │
                                └──── (circuit_breaker: 连续 5 次嵌入服务失败 → 直接标记 indexing_failed，跳过剩余重试)
```

**幂等性策略**：同一 `case_id` 被重复投递时（例如 CASE-03 误操作或手动重试），检查当前索引状态：
- 若为 `pending` 或 `processing`：跳过投递，返回 `{"status": "already_queued"}`。
- 若为 `indexed`：跳过投递，返回 `{"status": "already_indexed"}`。
- 若为 `indexing_failed`：允许重新入队（对应手动重试场景）。

**技术实现上**，状态转换在数据库事务中完成：`UPDATE cases SET index_status = $new_status WHERE id = $case_id AND index_status = $expected_old_status`，利用 PostgreSQL 行级锁和 CAS（Compare-And-Swap）语义防止并发状态覆盖。

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| ADR-004 | 模块化单体 | 索引逻辑封装在独立 package `packages/py-indexing/` 中，通过明确的函数签名（`enqueue()`、`process_task()`、`build_chunk_text()`、`generate_embedding()`、`write_index()`）与 API 层解耦，后续可独立拆出为微服务 |
| ADR-003 | pgvector 统一数据层 | 不引入独立向量数据库，索引写入与 CSLT-02 检索共享同一 pgvector 实例，利用 SQL + 向量混合查询能力 |
| 1.1 意图对齐 | 四要素完整性 | 采用规则拼接策略，通过 `build_chunk_text()` 函数硬编码拼接模板，确保场景-行为-干预-结果永远在同一文本块中，不受 Splitter 策略或模型行为影响 |
| 2.1 单一职责 | 仅负责索引入库 | 本模块不包含以下职责：案例审核判断、RAG 检索策略调优、案例淘汰标记管理、PII 主动脱敏（仅做最终防线校验） |
| 3.5 可观测性 | 全链路追踪 | 每个任务从投递到完成的各阶段均记录结构化日志（含 trace_id、case_id、phase、duration_ms）；队列深度、失败率、处理延迟作为 Prometheus metrics 暴露 |
| 5 安全第一 | PII 最终防线 | 入库前执行 PII 模式正则校验（复用 SEC-03 的检测规则），命中则拒绝入库并写入告警日志，保证即使上游脱敏遗漏，隐私数据也不进入向量索引 |
| ADR-005 | 成本敏感 | 嵌入 API 调用仅针对单个 chunk（每案例一次），不反复调用；失败重试使用线性退避（1s→3s）而非指数退避，避免无意义等待累计延迟 |

> 原则编号未在总设计中显式编号的，以设计文档中出现的约束/ADR 编号为准。

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 异步队列选型 | Redis List (LPUSH/BRPOP) | Redis Stream / Celery + RabbitMQ / 同步写入 | Redis List 已在项目中使用，无需新增运维组件。Stream 提供消费组和 ACK 机制，但对本场景过剩（单 Worker、单消费者、任务无需回溯）。Celery 引入额外的 beat/worker 进程管理，与"零运维负担"约束冲突。同步写入阻塞 HTTP 响应且耦合审核与索引 |
| 文本切片策略 | 规则拼接（模板硬编码） | LangChain SemanticChunker / LLM 智能分段 | 四要素已在 cases 表中独立存储，语义边界天然清晰。规则拼接零计算开销、100% 确定性。SemanticChunker 可能将"干预动作"和"结果反馈"错误合并/分割；LLM 分段引入 API 调用成本和幻觉风险。两种备选方案均无法满足意图文档的四要素不可拆分硬约束 |
| 索引写入策略 | 逐条写入（单次 INSERT） | 批量写入（batch INSERT） | 本模块处理粒度为每条案例独立触发（审核通过即入队），而非批量导入场景。逐条写入保证单条失败不影响其他案例，且 pgvector INSERT 单条延迟 < 10ms 在可接受范围。批量写入适用于初始数据迁移或补录历史数据的独立脚本 |
| 重试退避策略 | 线性退避（1s → 3s） | 指数退避（1s → 2s → 4s）/ 固定间隔 / 无重试 | 嵌入服务和 pgvector 均为本机或内网组件，延迟主要来自瞬时抖动而非持续不可用。线性退避总等待时间更短（4s vs 7s），减少队列积压。指数退避更适合外部 API 限流恢复场景。注：意图文档约束"最多重试 2 次（共 3 次尝试）"，无退避策略具体指定 |
| Worker 并发控制 | 单 Worker 串行消费 | 多 Worker 并发池 / 独立 Worker 进程 | 嵌入 API 调用有速率限制（阿里 text-embedding-v4 默认 QPS 限制），并发请求可能触发限流。单 Worker 串行自然限速，简化并发控制逻辑。若后期案例量增加，可通过增加 BRPOP 的 timeout 参数和协程数逐步升级为有界并发池（semaphore 控制） |
| Task 数据传递方式 | Redis List 存储 JSON 仅含 case_id | 存储完整案例数据 | 仅传 case_id 再到 PostgreSQL 查询，避免 Redis 中存储大文本（案例四段式字段合计可能数千字），且保证 Worker 始终读到最新数据（若审核后案例被编辑，依赖数据一致性由 CASE-05 版本管理机制保证） |
| 嵌入服务熔断 | 连续 5 次失败暂停消费 30s | 无熔断 / 立即标记失败 | 无熔断时大量失败任务不断重试耗尽 CPU 和网络资源（雪崩效应）。连续 5 次失败通常意味服务不可用，暂停等待恢复比继续失败更合理。30s 后自动恢复，避免人工介入 |

### 1.7 注意事项与禁止行为（设计层面）

1. **（设计约束）四要素不可拆分**：无论采用何种文本拼接策略，四要素（场景、行为、干预、结果）必须在同一切片文本中完整保留。禁止因文本长度或性能优化原因将任一要素移出切片或拆分为多条记录。

2. **（设计约束）不修改案例审核状态**：索引流程的成败不影响 cases.status 的审核结果（approved 状态不可被回退）。本模块仅写入 case_chunks 表和更新 cases.index_status 列。禁止在索引失败时修改 cases.status。

3. **（易错点）metadata JSONB 键名一致性**：metadata 中使用的 JSONB 键名（如 `behavior_type`, `age_range`, `severity`, `evidence_level`）必须与 CSLT-02 RAG 检索模块中的过滤条件键名完全一致。任何键名变更需同步通知 CSLT-02 模块维护者。建议将键名定义为常量 `INDEX_METADATA_KEYS` 并纳入契约管理。

4. **（易错点）Redis List 键名命名空间**：使用 `index:queue:case_chunks` 而非简写如 `idx_q`，避免与项目中其他 Redis 键名（如 `token_blacklist:*`、`rate_limit:*`）冲突。所有本模块的 Redis 键统一以 `index:` 为前缀。

5. **（设计边界）本模块不负责的技术事项**：
   - 案例审核决策逻辑（归属 CASE-03）
   - RAG 检索策略调优与 Top-K 选择（归属 CSLT-02）
   - 案例淘汰标记管理与过期策略（归属 CASE-06）
   - 案例版本迭代后的旧版本检索排除（由 CASE-05 和 CSLT-02 协作完成，本模块仅负责为每个新版本生成独立索引条目）
   - PII 主动脱敏（归属 SEC-03，本模块仅做最终防线校验）

6. **（禁止行为）禁止在主请求线程中执行向量化**：enqueue_index_task() 必须是轻量操作（仅状态校验 + LPUSH），禁止在其中调用嵌入 API 或执行 pgvector INSERT。违反此条将导致 CASE-03 的审核接口响应超时。

7. **（禁止行为）禁止在未通过文本完整性校验时入库**：若四段式字段中有任一字段为空字符串或 null，必须拒绝入库并标记为 indexing_failed。禁止生成只有 3 个或更少要素的切片文本。

### 1.8 引用：配套意图文档

- **意图文档**：`CASE-04-案例向量化入库-意图文档.md`
- **冻结时间**：2026-05-27 09:13:07
- **一致性声明**：本设计文档的技术实现方案与上述意图文档中的业务定义一致。具体对齐如下：
  - 四要素绑定：规则拼接策略保证场景-行为-干预-结果在同一向量切片中（对应意图文档 §1.11 约束 1）
  - 审核通过为唯一触发源：enqueue 入口校验 cases.status = 'approved'（对应意图文档 §1.11 约束 2）
  - 索引失败不影响审核结果：仅更新 index_status，不修改 cases.status（对应意图文档 §1.11 约束 3）
  - 3 次尝试限制：1 次主尝试 + 2 次重试（对应意图文档 §1.8 异常策略）
  - 免责声明完整性：文本组装阶段校验免责声明字段存在且非空（对应意图文档 §1.11 约束 5）
  - 如有歧义，以意图文档为准。
