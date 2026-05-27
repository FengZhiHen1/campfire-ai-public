# 1 功能点：CSLT-01 危机分级判定 — 设计文档（瘦身版）

> **文档生成时间**：`2026-05-27 09:15:01`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-27 09:15:01` | AI Assistant | 初始版本，基于技术预研报告全量生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `CSLT-01-危机分级判定-意图文档.md`（已冻结于 `2026-05-27 09:02:28`）
> - 本模块的精确编码规格见 `CSLT-01-危机分级判定-落地规范.md`

### 1.1 技术实现思路

危机分级判定采用**分层 Pipeline 模式**作为核心技术架构，而非传统的条件分支或策略模式。

**为什么选择 Pipeline**：三层判定（前置行为类型选择 → 规则引擎关键词匹配 → LLM 精调复审）天然构成顺序执行的管道。前置选择命中高危后须跳过后续两层，LLM 不可用时规则引擎必须独立运行，LLM 超时后必须回退到规则引擎结果——这些降级路径在 Pipeline 模式中表现为"该层判定后根据结果决定是否继续执行下一层"，与"宁升勿降"合并策略统一收敛在 Pipeline 的 `merge()` 方法中，避免了分散在条件分支中的复杂控制流。

**核心技术实现**：定义 `JudgmentLayer` 抽象接口（`judge(request: CrisisJudgmentRequest) -> JudgmentLayerResult`），三个具体实现类（`PreSelectionLayer`、`RuleEngineLayer`、`LLMReviewLayer`）各自封装判定逻辑。`JudgmentPipeline` 按顺序执行各层，维护 `JudgmentContext` 对象在层间传递判定状态，最终通过二维查找表执行合并。

**关键词匹配选型 AC 自动机**：相较于 Trie 树（需回退扫描）和预编译正则（模式多时退化到 O(n*m)），AC 自动机在多模式中文匹配中保证 O(n) 时间复杂度，与关键词数量无关。匹配引擎启动时将词库编译为 goto/failure/output 三表，运行时纯内存扫描，天然满足意图文档要求的"0 毫秒级别完成"。

**否定词过滤采用前向扫描**：对每条匹配到的关键词，扫描其前向 N 个字符（N = 最长否定词长度 + 2），查找否定词标识（"没有"/"不会"/"以前"/"不是"等）。在 AC 自动机的扫描回调中集成为一步，不增加独立过滤阶段。此方案无需引入 NLP 分词依赖（如 jieba/spaCy），维护成本极低，且能覆盖意图文档 AC-04 要求的核心否定场景。

**LLM 复审并行策略**：LLM 复审与 RAG 建议生成并行执行（使用 `asyncio.gather`），利用 LLM 的网络往返延迟时间。复审通过 `packages/py-llm/client.py` 的 DeepSeek API 客户端调用，设置超时参数（初始 5000ms，上线后根据生产环境 P95 调优至 3000ms），超时时 Pipeline 自动回退到规则引擎结果。

**关键词词库热加载**：采用 Redis Pub/Sub + 本地内存 AC 自动机双重机制。规则引擎启动时从 PostgreSQL 加载关键词列表到本地内存编译为 AC 自动机，同时订阅 Redis channel `keyword_dict:updates`。管理员修改词库后 publish 变更消息，规则引擎在新线程中编译新 AC 自动机，通过 copy-on-write 策略原子替换引用指针，避免编译期间的匹配服务阻塞。

**数据流总览**：`CrisisJudgmentRequest` 进入 Pipeline → PreSelectionLayer 检查高危类型 → (如果重度则直接输出，跳过后续) → RuleEngineLayer 执行 AC 自动机扫描 + 否定词过滤 + 档案叠加规则 → (如果重度则直接输出，跳过 LLM) → LLMReviewLayer 并行复审（带超时降级）→ `merge()` 通过二维查找表执行"宁升勿降"合并 → 输出 `CrisisJudgmentResult`。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：AUTH-01～06 系列落地规范（用户注册/登录/Token续期/RBAC鉴权/UI/会话管理）、PROF-05 落地规范（档案隐私控制）、KNOW-01 落地规范（科普内容管理）、OBS-01/04 落地规范（结构化日志/健康检查）、SEC-01/04/05 落地规范（传输安全/防刷限流/输入校验）、DEPLOY-01～05 落地规范（容器编排/反向代理/CI_CD/数据库迁移/环境配置）
- **兼容性结论**：**无冲突**。CSLT-01 是 02-智能应急咨询分组首个设计模块，其输出类型（CrisisLevel 枚举 mild/moderate/severe）与已有模块的枚举值（HealthStatus healthy/degraded/unhealthy、ArticleStatus published/unpublished、AccessOperation view/create/update/delete 等）领域隔离、命名空间独立。已有模块均不依赖 CSLT-01 的输出，无接口兼容性风险。
- **复用的已有设计**：
  - `packages/py-llm/client.py` — DeepSeek API 客户端（复用其超时控制、重试机制、熔断逻辑）
  - `packages/py-cache/client.py` — Redis 客户端（复用其 Pub/Sub 订阅、连接池管理）
  - `packages/py-db/models/` — SQLAlchemy async ORM（复用其 Base、session 管理、事务控制）
  - `packages/py-config/config.py` — 环境配置加载（复用 pydantic-settings 模式，统一配置管理）
  - `packages/py-logger/` — 结构化日志埋点（复用 trace_id、request_id 注入和 JSON 格式输出）
  - `packages/py-schemas/` — 共享 Pydantic 基础类型（复用 UUID 校验、分页模型等基类）

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| PostgreSQL 17.x + pgvector | 读写 | 关键词词库持久化存储，通过 `packages/py-db/` ORM 模型 `CrisisKeyword` 进行 CRUD。词库加载时执行 `SELECT * FROM crisis_keywords WHERE is_active = true` 全量拉取。档案叠加规则所需的患者历史行为标签和最近事件也通过 PostgreSQL 查询 |
| Redis 7.x | 订阅 + 缓存 | 订阅 channel `keyword_dict:updates` 接收词库变更通知（Pub/Sub）；`packages/py-cache/` 提供 Redis 客户端连接池 |
| DeepSeek API（通过 py-llm） | 外部 API 调用 | LLM 精调复审时调用 DeepSeek Chat API，通过 `packages/py-llm/client.py` 的 `async_chat()` 方法，注入 System Prompt + 患者档案上下文 + 规则引擎结果 |
| PROF-02（档案驱动检索过滤） | 上游数据来源 | 接收 `PatientProfileSnapshot`（含 diagnosis_type、historical_behavior_tags、recent_event_records），由 csLT-08 编排层在调用危机分级前通过 PROF-02 获取并注入 `CrisisJudgmentRequest.patient_profile` |
| CSLT-07（应急咨询界面） | 上游数据来源 | 接收 `behavior_type_selection`（前置行为类型勾选）和 `behavior_description`（行为描述文本），由 csLT-08 编排层组装为 `CrisisJudgmentRequest` 后传入 |
| CSLT-03（应急方案生成） | 下游数据消费 | 输出 `CrisisJudgmentResult.final_level` 和 `CrisisJudgmentResult.block_deep_response`，决定应急方案是深度生成还是仅安全提示 |
| CSLT-05（置信度后校验） | 下游数据消费 | 输出 `CrisisJudgmentResult.manual_review_flag` 和 `CrisisJudgmentResult.review_confidence`，作为工单触发决策的参考因素 |
| TICK-01（工单自动生成） | 下游数据消费 | 输出 `CrisisJudgmentResult.final_level`，驱动工单生成和上下文继承 |
| TICK-02（工单紧急分级） | 下游数据消费 | 输出 `CrisisJudgmentResult.final_level`，决定工单优先级映射（重度→特急、中度→紧急、轻度→不自动生成） |
| SEC-02（AI输出安全护栏） | 共享资源依赖 | 共享高危关键词库（`packages/py-config/` 中定义的公共常量 `CRISIS_KEYWORDS`，双方只读引用，单点维护） |
| KNOW-05（应急场景引导） | 共享资源依赖 | 共享高危关键词库（同上 `CRISIS_KEYWORDS`，用于科普场景中的紧急关键词检测与引导跳转） |
| packages/py-config | 框架依赖 | 读取 `JUDGMENT_LLM_TIMEOUT_MS`、`keyword_dict_path`、`safety_prompt_templates` 等配置项 |
| packages/py-logger | 框架依赖 | 记录每个判定阶段的结构化日志（前置判定结论、规则引擎匹配详情、LLM 复审结果、超时事件、降级事件） |

### 1.4 状态机设计（技术实现策略）

本功能点不涉及持久化状态流转，故无需状态机。

内部处理的运行时阶段流转（不持久化，纯内存中的 Pipeline 顺序执行）：

```
等待输入 → 前置判定（PreSelectionLayer）
  → 高危命中？→ [是] 直接输出重度（后续层跳过）
  → [否] → 规则匹配（RuleEngineLayer）
    → 命中重度？→ [是] 直接输出重度（LLM 层跳过）
    → [否] → 并行复审（LLMReviewLayer，与 RAG 建议生成并行）
      → 超时？→ [是] 回退到规则引擎结果
      → [否] → 合并且输出（merge()，宁升勿降）
```

注意：前端页面状态流转（正常模式 ↔ 应急模式）属于 CSLT-07（应急咨询界面）的职责，本模块仅输出判定结果（`final_level` 和 `block_deep_response`），不控制页面渲染状态。

### 1.5 设计原则兑现清单（技术视角）

对照项目 `DESIGN.md` 中的设计原则，本模块在技术层面如下兑现：

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| 分层架构 | 模块位于 L5（业务能力层） | CSLT-01 作为独立的 `apps/api-server/app/services/crisis_judgment/` 包存在，通过 Service 接口被 L6 层编排。只依赖 L2 共享能力层（py-llm/py-cache/py-db/py-config/py-logger/py-schemas），不依赖 L6 及以上模块 |
| 单一职责 | 一个模块只做一件事 | CSLT-01 仅负责危机等级判定，不包含应急方案生成（归属 CSLT-03）、不包含前端 UI 渲染（归属 CSLT-07）、不包含工单创建（归属 TICK-01/TICK-02）、不包含 AI 输出安全审核（归属 SEC-02） |
| 接口隔离 | 通过 Pipeline 接口解耦 | 三层判定各自实现 `JudgmentLayer` 接口，任一层可被独立测试、mock 或替换。如未来引入新的判定层（如基于传感器数据的行为检测），只需新增一个 `JudgmentLayer` 实现并插入 Pipeline |
| 降级优先 | 宁可降级不可失败 | LLM 复审超时 → 回退规则引擎结果。关键词词库加载失败 → 降级为仅依赖前置行为类型选择。患者档案缺失 → 跳过档案叠加规则但核心判定链路不受影响。系统在任何降级场景下仍然输出有效判定结果 |
| 安全优先 | 安全判定不可被降级覆盖 | 前置选择命中高危后，Pipeline 直接跳出后续层（规则引擎和 LLM 复审完全跳过）。"宁升勿降"合并策略在 `merge()` 中通过查找表编码——任何一层判重度即为重度，LLM 复审不可降低规则引擎判定的等级 |
| 可观测性 | 每个判定步骤可追溯 | 每个判定层输出 `JudgmentLayerResult`（含触发规则编号和判定详情），合并且输出 `judgment_sources` 完整记录各层结论。结构化日志记录每次判定的输入特征、各层耗时、最终等级和降级标记，支持事后审计和词库质量分析 |
| 配置化 | 阈值和策略通过配置管理 | LLM 超时时间、否定词列表、关键词词库路径、安全提示模板、判定矩阵映射均通过 `packages/py-config` 统一管理，支持环境变量覆盖，不硬编码在业务逻辑中 |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 判定架构模式 | **分层 Pipeline 模式**（`JudgmentPipeline` + `JudgmentLayer` 接口） | 条件分支（if-else 链）、策略模式 | Pipeline 模式天然适配三层顺序判定+各层降级路径（前置命中后跳出、规则引擎命中后跳过 LLM）。策略模式更适合可互换的同级策略，而非顺序管道。Pipeline 允许在测试时注入 mock layer 以隔离各层 |
| 关键词匹配算法 | **Aho-Corasick（AC 自动机）** | Trie 树、预编译正则表达式 | AC 自动机 O(n) 时间复杂度与关键词数量无关，在中文字符扫描中性能最优。Trie 树需回退扫描慢于 AC；预编译正则在关键词数量 > 100 后退化到 O(n*m) |
| 否定词过滤 | **否定词前缀规则**（前向 5 字符扫描） | NLP 分词（jieba/spaCy）、机器学习分类器 | 核心否定场景（"没有自伤行为"、"不会伤害自己"）的否定词在关键词前 5 个中文字符以内，前缀规则即可覆盖。NLP 分词引入额外依赖和维护成本，且对多层否定句（"他不是从来没有自伤过"）同样无法完美解决，性价比不成立 |
| 判定矩阵编码 | **二维查找表**（Python dict 嵌套结构） | 条件分支（if-else 树）、决策树（DecisionTree） | 21 种组合（7×3）用查找表表达比 21 个 if-else 更可读且不易遗漏。添加新等级或规则时只需修改查找表条目，不涉及控制流变更。O(1) 时间复杂度 |
| LLM 复审超时阈值 | **初始 5000ms，上线后调优至 3000ms** | 硬编码 3000ms | 意图文档要求 3s 内返回，但生产环境 DeepSeek API 网络延迟 P50/P95 数据缺失。5000ms 提供初始余量（含网络抖动），上线后根据真实 P95 逐步调优至 3000ms。直接设置 3000ms 可能在上线初期导致大量不必要的超时降级。**受意图文档 §1.12.4 约束：精确毫秒值由 P95 基准调优确定** |
| 关键词词库存储 | **PostgreSQL 表**（`crisis_keywords` 表 + ORM 模型） | YAML 配置文件、JSON 文件、Redis 单独存储 | PostgreSQL 与项目数据层统一，支持审计日志（`created_at`/`updated_at`），管理员可通过通用 CRUD API 管理（无需文件系统访问），配合 Redis Pub/Sub 实现热加载。JSON/YAML 文件方案在热加载时需要文件监听或 API 刷新触发，不够实时 |
| 安全提示模板存储 | **代码内常量字符串**（Python `CONSTANT` + Markdown 格式） | 独立 Markdown 文件、数据库字段存储 | 安全提示模板内容极少（4 类 x < 200 字），代码内常量保证版本一致性和不可篡改性（与代码一起受版本控制）。纯文本 Markdown 格式可被 Taro 前端直接渲染。引入文件或数据库存储徒增复杂度。**受意图文档 AC-09 约束：四类提示内容不可混淆** |
| 行为类型可扩展性 | **Python StrEnum + list 多选** | 硬编码 boolean 字段、Bitmask | `BehaviorTypeCategory` 是 Python `StrEnum`（不是 `IntEnum`），直接支持新增枚举值。`behavior_type_selection: list[BehaviorTypeCategory]` 支持多选。前端使用枚举值渲染而非硬编码 checkboxes，新增类型只需后端增加枚举值 + 前端增加渲染模板。**受意图文档 §1.12.10 约束：未来扩展方案由 spec-writer 确定** |
| 模块暴露方式 | **内部 Service 调用**（无独立 HTTP 端点） | 独立 REST API（`POST /api/v1/crisis/judge`） | 危机分级判定是应急咨询全流程的内部步骤，由 csLT-08（咨询编排逻辑）编排调用，无需由前端直接触发。内部 Service 调用减少一次 HTTP 往返（vs 独立端点），且"无状态判定"的特性进一步排除独立端点需求。**受意图文档 §1.7 约束：无状态判定** |

### 1.7 注意事项与禁止行为（设计层面）

1. **[安全底线]** 前置行为类型选择命中高危（SELF_INJURY / AGGRESSION / ELOPEMENT / MEDICATION）后，Pipeline 必须立即输出 severe 并跳过后续规则引擎和 LLM 复审两层。任何情况下不可让规则引擎或 LLM 复审覆盖前置判定的重度结论。

2. **[合并策略]** "宁升勿降"合并策略使用二维查找表编码（non-negotiable）。禁止用任何形式的优先级覆盖逻辑（如"LLM 置信度 > 0.95 时以 LLM 为准"）——LLM 在任何置信度下均不可降低规则引擎的等级。

3. **[降级不可破坏安全]** 关键词词库加载失败时的降级路径（仅依赖前置行为类型选择）必须保持前置选择的四类高危判定完整可用。禁止在降级模式下缩小高危类型的覆盖范围。

4. **[词库原子替换]** AC 自动机热加载时必须使用 copy-on-write 策略（先构建新的 AC 自动机，再原子替换引用指针）。禁止在现有 AC 自动机上直接修改——编译期间的锁定会导致匹配服务短暂阻塞。

5. **[LLM 超时不重试]** LLM 复审超时后禁止重试——安全场景不能让用户无限等待。超时后返回的 LLM 结果仅记入日志供后续分析，绝对不可改变当前展示的判定结果。

6. **[类型安全边界]** CSLT-01 输出的 `CrisisLevel`（mild / moderate / severe）与 TICK-02 的工单优先级枚举（normal / urgent / critical）是两个独立的枚举类型，命名空间隔离。禁止在代码中直接将 CrisisLevel 赋值给工单优先级变量——必须通过显式的映射函数转换。

7. **[设计边界]** 本模块不负责：
   - 应急方案文本的生成（归属 CSLT-03）
   - 前端页面的 UI 渲染与状态切换（归属 CSLT-07）
   - 工单的创建与派发逻辑（归属 TICK-01/TICK-02）
   - AI 输出内容的安全审核（归属 SEC-02）
   - 患者档案数据的获取与管理（归属 PROF-02）

8. **[共享关键词库]** 高危关键词库（`CRISIS_KEYWORDS`）由 CSLT-01、SEC-02、KNOW-05 三方共享。关键词的增删改必须通过标准化的词库管理接口，禁止任一方在本地硬编码关键词列表。修改词库后必须通过 Redis Pub/Sub 通知所有订阅方热加载。

### 1.8 引用：配套意图文档

- **意图文档**：`CSLT-01-危机分级判定-意图文档.md`
- **冻结时间**：`2026-05-27 09:02:28`
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。Pipeline 模式完整兑现三层递进判定流程，AC 自动机满足 0ms 级关键词匹配约束，二维查找表精确实现"宁升勿降"合并策略，所有降级路径均与意图文档 §1.8 的异常策略对齐。业务矛盾标记（§4）已基于技术预研报告的推荐方案进行最佳推断并标注处理方式，等待后续迭代中用户确认。如有歧义，以意图文档为准。
