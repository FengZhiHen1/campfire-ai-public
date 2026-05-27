## 1 功能点：CSLT-03 应急方案生成 — 设计文档（瘦身版）

> **文档生成时间**：`2026-05-27 14:45:00`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-27 14:45:00` | AI Assistant | 初始版本，基于 s06 技术预研报告（8 项自主决策）和已冻结意图文档 v2.0 全量生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `CSLT-03-应急方案生成-意图文档.md`（已冻结于 `2026-05-27 14:29:12`）
> - 本模块的精确编码规格见 `CSLT-03-应急方案生成-落地规范.md`

### 1.1 技术实现思路

应急方案生成采用**单次 LLM 调用 + AsyncGenerator 流式输出**的核心模式，而非多轮对话或离线批处理。

**为什么选择单次调用**：本模块的职责是将上游检索到的案例切片和患者档案组装为一次性 Prompt，交由 DeepSeek API 生成四段式应急方案。与多轮对话模式不同，应急咨询场景不需要 Agent 自主规划——用户的问题已明确定义（"我该怎么做"），参考案例已精确检索，四段式输出结构已强制约束。单次调用足够覆盖整个生成任务，降低了 Token 消耗和响应延迟，规避了 Agent 循环中可能产生的幻觉扩散。

**AsyncGenerator 流式输出的选型理由**：采用 Python `async def` 协程函数返回 `AsyncGenerator[GenerationChunk, None]`，将 LLM 返回的每个 Token 即时 yield 给下游 CSLT-04。不使用同步函数的原因是：
- DeepSeek API 的流式调用本身就是 asyncio 协程（`httpx.AsyncClient`），同步包装会导致事件循环阻塞
- 下游 CSLT-04 的 SSE 推送也是异步协程，AsyncGenerator 可以直接用 `async for` 消费，无需在同步/异步间转换
- 首段文本在首个 chunk yield 时即可开始传输，与意图文档要求的 TTFT ≤ 3s 一致——流式管道避免了"等全部生成完再开始传"的批量延迟

**为什么不缓存生成结果**：每份应急方案的输入组合（行为描述 × 案例切片列表 × 档案上下文 × 危机等级）唯一性极强，缓存命中率趋近于零。且方案涉及医疗建议，缓存可能导致同一描述在不同档案上下文中给出相同答复（违背个性化原则）。如果未来发现用户短时间内对同一描述重复请求生成（如网络中断后重试），可在 CSLT-08 编排层做幂等判断（基于 `request_hash` 去重），而非本模块内部缓存。

**Prompt 组装策略：全量切片降序注入**：将上游 CSLT-02 返回的 `case_slices` 按 `composite_score` 降序全部注入 System Prompt 的「参考案例」区域，而非仅注入 Top-N 或做文本压缩。理由是：
- DeepSeek API 的百万 Token 上下文窗口（128K 有效）完全可以容纳全量切片文本（标准检索返回 10 条，每条切片约 500-800 字，总计约 8000 字，约占 12K Token），无需做截断取舍
- 全量注入避免了"如何选择 Top-N"的额外决策逻辑，也消除了因截断导致低分切片中的有用信息丢失的风险
- 切片已按 `composite_score` 降序排列，大模型在注意力机制下天然更容易关注排在前面的高相关切片

**预编号来源引用**：在 System Prompt 中为每条切片预先分配序号（`[1]`、`[2]`、...），而非期望 LLM 在生成过程中自行编号。理由：LLM 自行编号容易漏编、错编或重复编号，事后对来源引用的验证也须解析 LLM 输出文本中的编号再回溯对应——引入不必要的复杂度。预编号将引用映射关系前置到 Prompt 构建阶段，LLM 只需在引用时写 `[序号]` 即可，下游验证时直接用序号查表，引用准确率的自动化校验（AC-04）也因此简化为"检查 LLM 输出中出现的 [N] 是否都在预编号范围内"。

**阻断路径快速短路**：在服务入口处检查 `block_deep_response` 标记。若为 `true`，完全跳过 Prompt 组装和 LLM API 调用，直接返回硬编码的安全提示文本（根据具体的高危行为类型选择对应模板变体）。此路径不涉及任何网络 I/O，耗时 < 10ms，确保重度场景下用户最快获得安全指引。

**硬编码阻断提示基于行为类型变体**：不为所有重度场景使用单一安全提示文本。根据 CSLT-01 行为类型枚举，为 `SELF_INJURY`、`AGGRESSION`、`ELOPEMENT`、`MEDICATION` 四种高危类型各准备一个预设文本变体，变体复用相同的安全声明框架（AI 不能替代急救），但在引导语中针对行为特征做定制化调整（如自伤场景强调移除危险物品，走失场景强调立即报警）。CSLT-08 编排层负责选择对应变体，本模块仅提供字典查找接口。

**Markdown 格式档案摘要**：将上游 PROF-02 传入的档案结构化数据（`diagnosis_type`、`behavior_tags`、`recent_events` 等）格式化为 Markdown 列表段落，注入 System Prompt 的「患者档案」区域。选择 Markdown 而非 JSON 的原因是：大模型对 Markdown 结构化文本的理解力优于裸 JSON 字段列表，且 Markdown 格式与 Prompt 中其他段落（System Instruction、参考案例）保持视觉一致性，减少格式切换带来的 Attention 分散。

**可观测性：Prometheus 埋点**：在本模块的 Service 入口、LLM 调用前、LLM 调用后三个关键点埋入 Prometheus 指标：
- `crisis_generation_requests_total{status="success|blocked|timeout|error"}` — 请求量计数
- `crisis_generation_duration_seconds` — 生成耗时 Histogram（bucket: 0.5, 1, 2, 3, 5, 10, 15）
- `crisis_generation_ttft_seconds` — 首字延迟 Histogram
- `crisis_generation_tokens_total{type="prompt|completion"}` — Token 消耗计数
GraphQL 的 /metrics 端点由 OBS-01 统一暴露，本模块使用 `prometheus-fastapi-instrumentator` 提供的 Counter/Histogram 实例注册指标。

**核心技术流程**：
1. 入口校验：检查 `block_deep_response` → 若 true，短路返回硬编码安全提示（<10ms）
2. Prompt 构建：将 Markdown 档案摘要 + 全量切片（降序预编号）+ 用户行为描述 + 系统指令组装为 messages 列表
3. LLM 流式调用：通过 `packages/py-llm` 的 `async_chat_stream()` 发起 DeepSeek API 流式请求（temperature=0.3, max_tokens=4096）
4. 流式输出：AsyncGenerator yield 每个 chunk，下游 CSLT-04 通过 `async for` 消费并推 SSE
5. 结果汇总：流式完成后，将完整文本 + 来源清单 + 免责声明 + 生成耗时组装为 `GenerationResult`

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：
  - CSLT-01 危机分级判定-设计文档.md + 落地规范.md（已冻结）
  - CSLT-02 RAG语义检索-设计文档.md + 落地规范.md（已冻结）
  - AUTH-01~06 认证授权系列-落地规范.md（已冻结）
  - PROF-05 档案隐私控制-落地规范.md（已冻结）
  - CASE-01/04 案例管理系列-落地规范.md（已冻结）
  - KNOW-01 科普内容管理-落地规范.md（已冻结）
  - OBS-01/04 日志与健康检查-落地规范.md（已冻结）
  - SEC-01/04/05 安全与合规系列-落地规范.md（已冻结）
  - DEPLOY-01~05 部署与运维系列-落地规范.md（已冻结）
  - docs/contracts/CSLT-01/CrisisJudgmentResult.json（maturity: draft）
  - docs/contracts/CSLT-01/CrisisLevel.json（maturity: draft）
  - docs/contracts/CSLT-02/CaseSliceDto.json（maturity: draft）
  - docs/contracts/CSLT-02/SemanticSearchResult.json（maturity: draft）

- **兼容性结论**：**无冲突**。
  - CSLT-03 的上游输入类型（`CrisisJudgmentResult.final_level`、`CrisisJudgmentResult.block_deep_response`、`SemanticSearchResult.results: list[CaseSliceDto]`）与 CSLT-01/CSLT-02 的已锁定契约完全对齐。`CaseSliceDto` 中的所有字段（`slice_id`、`case_id`、`slice_text`、`similarity_score`、`composite_score`、`evidence_level`、`case_title`、`case_created_at`）均被 CSLT-03 的 Prompt 构建逻辑消费，无冗余字段，无缺失字段。
  - 下游 CSLT-04 和 CSLT-05 尚未设计，CSLT-03 在此阶段作为契约定义方，其输出接口不影响已有模块。
  - CSLT-03 的 LLM 调用通过 `packages/py-llm/` 统一客户端封装，与 CSLT-01 复用同一基础设施。复用 `async_chat_stream()` 方法与 CSLT-01 的 `async_chat()` 非流式调用共享同一连接池和重试策略，无冲突。

- **复用的已有设计**：
  - `CSLT-01/CrisisLevel` 枚举（mild/moderate/severe）— 用于阻断判断和 Prompt 上下文注入
  - `CSLT-01/CrisisJudgmentResult` 数据类型 — 消费其 `final_level` 和 `block_deep_response` 字段
  - `CSLT-02/CaseSliceDto` 数据类型 — Prompt 中参考案例的来源；全字段消费
  - `CSLT-02/EvidenceLevel` 枚举 — 在 Prompt 中为每个切片标注循证等级
  - `packages/py-llm/client.py` — DeepSeek API 统一客户端（复用流式调用、超时控制、重试机制）
  - `packages/py-logger/` — 结构化日志埋点（复用 trace_id、request_id 上下文注入）
  - `packages/py-config/` — 统一配置管理（复用 pydantic-settings 模式）
  - `packages/py-schemas/` — Pydantic 基础类型（复用 BaseModel、UUID 校验）
  - `packages/py-infra/` — 异常体系 AppException 基类（复用统一异常处理中间件）

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| DeepSeek API（通过 py-llm） | 外部 API 调用 | 通过 `packages/py-llm/client.py` 的 `async_chat_stream(model="deepseek-chat", messages=[...], temperature=0.3, max_tokens=4096, timeout=15)` 流式调用 DeepSeek API，返回 AsyncGenerator[ChatCompletionChunk]。temperature ≤ 0.3 受意图文档约束 |
| CSLT-01（危机分级判定） | 上游数据来源 | 接收 `CrisisJudgmentResult`，消费其中 `final_level`（决定正常生成或短路返回）和 `block_deep_response`（决定是否跳过 LLM 调用） |
| CSLT-02（RAG语义检索） | 上游数据来源 | 接收 `SemanticSearchResult`，消费其中 `results: list[CaseSliceDto]` 和 `degradation_applied`/`degradation_level` 标记（在 Prompt 中提示用户检索精度可能降低） |
| PROF-02（档案驱动检索过滤） | 间接上游 | 不直接调用 PROF-02，但接收由 CSLT-08 编排层预取并注入的患者档案摘要数据（diagnosis_type、behavior_tags、recent_events），格式化为 Markdown 注入 Prompt |
| CSLT-04（流式应答推送） | 下游数据消费 | 将 AsyncGenerator 产生的每个 text chunk yield 给 CSLT-04，由其负责封装为 SSE 协议推送给前端客户端。CSLT-03 不关心传输协议细节 |
| CSLT-05（置信度后校验） | 下游数据消费 | 流式完成后，将完整的 `GenerationResult`（四段式文本 + 来源清单 + 免责声明 + 耗时 + 被引用的切片 ID 列表）传递给 CSLT-05 用于置信度评估 |
| packages/py-llm | 框架依赖 | 复用 DeepSeek API 客户端封装，包括统一超时控制（15s 全流程超时）、连接池管理、熔断机制和 API Key 注入 |
| packages/py-logger | 框架依赖 | 记录 Prompt 构建耗时、LLM 调用耗时、TTFT、Token 消耗、阻断短路、生成失败等结构化事件 |
| packages/py-config | 框架依赖 | 读取 `DEEPSEEK_MODEL`（默认 deepseek-chat）、`GENERATION_MAX_TOKENS`（默认 4096）、`GENERATION_TEMPERATURE`（默认 0.3）、`GENERATION_TIMEOUT_S`（默认 15.0）|
| packages/py-schemas | 框架依赖 | 复用 BaseSchema、UUID 类型校验 |
| Prometheus（via prometheus-fastapi-instrumentator） | 可观测性 | 暴露 `/metrics` 端点指标：请求计数、生成耗时 Histogram、TTFT Histogram、Token 消耗 Counter |

### 1.4 状态机设计

本功能点不涉及持久化状态流转，故无需状态机。

单次生成的内部处理阶段流转（纯内存，不持久化）：

```
等待输入 → 阻断检查
  → [block_deep_response=True] → 短路输出安全提示 → 完成
  → [block_deep_response=False] → Prompt构建 → LLM流式生成 → 完成
```

- **等待输入**：Service 函数 `generate_emergency_plan()` 被 CSLT-08 编排层调用，接收上游数据
- **短路输出安全提示**：阻断标记激活时，直接返回预设安全提示文本，不进入 Prompt 构建和 LLM 调用
- **Prompt构建**：遍历 `case_slices` 列表，预编号、格式化为 Markdown，组装 messages 列表
- **LLM流式生成**：调用 `async_chat_stream()`，通过 AsyncGenerator 将 chunks yield 给下游

前端交互状态（生成中/已完成/失败/冷却中）由 CSLT-08 管理，本模块仅提供生成服务接口。

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| 单一职责 | 模块只做"Prompt组装+LLM调用" | 本模块不负责案例检索（CSLT-02）、不负责危机判定（CSLT-01）、不负责 SSE 推送协议实现（CSLT-04）、不负责置信度评估（CSLT-05）、不负责冷却期校验（CSLT-08）。仅聚焦于"输入→组装Prompt→调用LLM→输出文本"这一生成环节 |
| 失败透明 | 异常信息充分暴露 | LLM 超时返回已生成的部分文本并标记 `is_partial=True`；API 不可用抛出 `LLMUnavailableException`（含错误上下文）；Prompt 构建阶段发现输入数据不完整时抛出 `GenerationInputError`（含缺失字段列表）。所有异常记录结构化日志并附加 trace_id |
| 性能优先 | TTFT ≤ 3s 硬约束 | 阻断路径短路 < 10ms；Prompt 构建为纯内存字符串操作 < 50ms；LLM 流式调用在首个 token 返回时立即 yield（TTFT 由网络延迟 + LLM 首 token 生成时间决定，设计目标 3s 内） |
| 安全红线 | 零幻觉 + 阻断机制 | System Prompt 强制约束"仅基于提供的案例上下文回答，不得编造"；阻断场景完全跳过 LLM 调用；免责声明以固定文本硬注入而非依赖 LLM 生成 |
| 可观测性 | 生成过程全透明 | 每个请求标记 trace_id 贯穿全链路；TTFT、生成耗时、Token 消耗通过 Prometheus Histogram/Counter 暴露；阻断事件和超时事件记录 WARNING 级别日志 |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| LLM 调用次数 | 单次调用 | 多轮对话（Agent 自主判断是否需要补充信息） | 意图文档已定义单个输出任务（四段式方案），Agent 循环增加延迟和 Token 开销，且应急场景不应让用户等待 Agent 多次"思考" |
| 流式输出方式 | AsyncGenerator yield | 回调函数注册 on_token 回调 | AsyncGenerator 与 asyncio 生态天然集成，下游 CSLT-04 用 `async for` 消费更简洁；回调模式需管理回调注册/注销生命周期，复杂度更高 |
| 切片注入策略 | 全量注入（降序） | Top-N 截断（仅注 Top-5） | DeepSeek 128K 上下文足以容纳全部检测切片（通常 10 条/约 12K Token），全量注入消除截断的决策开销和信息丢失风险 |
| 来源引用方式 | 预编号（Prompt 中固定 [N]） | LLM 自行编号 | 预编号将引用映射关系前置，消除 LLM 错编/漏编风险；下游 AC-04 自动化校验可简化为"检查 [N] 是否在有效范围" |
| 阻断提示 | 四种行为类型变体（硬编码） | 单一通用安全提示 | 自伤/攻击/逃跑/用药的高危场景各需不同的紧急应对指引（如自伤强调移除危险物品、攻击强调隔离冷静、走失强调立即报警），单一文本无法覆盖差异化安全需求 |
| 档案摘要格式 | Markdown 列表段落 | JSON 字段列表 | 大模型对 Markdown 结构化文本的理解力优于裸 JSON；Markdown 与 Prompt 中其他区域保持视觉格式一致性 |
| 缓存策略 | 不缓存 | Redis 缓存生成结果 | 输入组合唯一性极强（行为描述×切片列表×档案上下文），缓存命中率趋近于零；医疗建议不宜缓存；若未来发现重复请求模式，在编排层做幂等判断 |
| 生成超时 | 全流程 15s 硬超时 | 无超时/仅 LLM 超时 | 15s 覆盖 Prompt 构建（< 50ms）+ LLM 生成（DeepSeek 4K Token 约 8-12s） + 网络缓冲。超时后返回已生成部分文本而非完全丢弃，符合意图文档的"部分生成时仍可参考"业务策略 |
| 冷却期实现 | 后端拒绝 + 返回剩余冷却秒数 | 前端纯拦截 | 受意图文档约束。后端校验防止 API 绕过前端直接调用（如 curl/Postman），前端拦截仅作为 UX 优化。冷却期由 Redis Key（`generation_cooldown:{user_id}:{profile_id}`）管理，TTL 30 秒 |

### 1.7 注意事项与禁止行为（设计层面）

1. **[约束 1 -- 受意图文档§1.11约束]** 免责声明必须以固定文本硬注入到 System Prompt 的输出格式要求中，不得依赖 LLM 自主生成。声明文本："以上建议由 AI 生成，仅供参考，不构成医疗诊断或治疗建议。如情况紧急，请立即联系专业医疗机构。"

2. **[约束 2 -- 受意图文档§1.11约束]** 危机等级为重度时（`block_deep_response=True`），必须完全跳过 Prompt 组装和 LLM API 调用。不得以任何理由"轻度生成后再由下游过滤"——LLM 调用既产生 Token 成本又有泄露深度建议的风险。

3. **[约束 3 -- 受意图文档§1.11约束]** `temperature` 参数不得超过 0.3，以确保生成结果的低幻觉和高确定性。此参数通过 `packages/py-config` 读取 `GENERATION_TEMPERATURE` 环境变量，代码中不硬编码。

4. **[易错点 1]** Prompt 构建时对 `case_slices` 的预编号必须在 Prompt 文本中直接写入 `[1]` `[2]` 等标记，而非仅在代码中维护内存映射表。LLM 输出文本中出现的 `[N]` 就是 Prompt 中的预编号——若只在代码层维护映射，LLM 生成文本中不会出现这些标记。

5. **[易错点 2]** 阻断场景下返回的安全提示文本中，不得包含任何"请您稍候，正在为您连接专家"等承诺性语句——专家分配和工单生成由 CSLT-05 和 TICK-01 异步处理，CSLT-03 不应越过自己的职责边界做承诺。

6. **[易错点 3]** 档案摘要中注入的患者事件记录上限为 5 条（受意图文档 §1.6.1 约束）。若上游传入超过 5 条（虽然规范已限制），仍应在 Prompt 构建时截断并记录 WARNING 日志，而不是盲信上游数据。

7. **[易错点 4]** `case_slices` 为空列表时，预编号步骤应生成 0 条引用，而非生成空编号。Prompt 中的"参考案例"区域应替换为"当前暂无与您描述情况相匹配的真实干预案例参考"，并在 System Instruction 中指示 LLM 不生成任何 `[N]` 引用。

8. **[设计边界]** 本模块不负责：
   - 冷却期的前端 UI 展示和倒计时管理（CSLT-08）
   - SSE 协议封装和 HTTP 连接管理（CSLT-04）
   - 生成结果的置信度评估和工单触发（CSLT-05）
   - 用户行为描述的 PII 脱敏（上游 CSLT-08 / SEC-03 已完成）
   - 案例检索和标签过滤（CSLT-02）

9. **[禁止行为]** 禁止绕过 `packages/py-llm/` 统一客户端直接调用 DeepSeek API。统一客户端提供了超时控制、重试策略、熔断机制和 API Key 注入——绕过会导致这些安全机制全部失效。

10. **[禁止行为]** 禁止在 System Prompt 中包含任何用户个人身份信息（姓名、手机号、具体地址）。用户行为描述由上游脱敏后传入，档案摘要仅含诊断标签和行为类型（非 PII），但仍应在 Prompt 构建时做二次检查（正则匹配手机号和身份证格式）并记录 ALERT 级别日志。

### 1.8 引用：配套意图文档

- **意图文档**：`CSLT-03-应急方案生成-意图文档.md`
- **冻结时间**：`2026-05-27 14:29:12`
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义完全一致。所有 6 项业务约束（合规声明、安全阻断、温度 ≤ 0.3、性能 ≤ 3s/10s、30s 冷却期、设计边界）均在技术方案中得到兑现。8 项技术决策（意图文档 §1.12）已通过 s06 技术预研确定并在本设计文档各节中落实。如有分歧，以意图文档为准。
