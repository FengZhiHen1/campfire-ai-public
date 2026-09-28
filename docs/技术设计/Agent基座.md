# Agent 基座

> **本文唯一拥有**：Campfire 的分面执行策略（应急面/异步面编排）、领域工具与 Skill 清单、Campfire 侧安全规则与扩展约定、编排开销门禁。
> **状态**：旧应急中心执行基线，仅供代码与历史方案对照；当前 AI 业务边界、授权和结果发布由[目标机制](./目标机制/README.md)与[ADR-016](./决策/ADR-016-授权与发布由业务代码强制执行.md)拥有。内核通用接口可继续复用，但安全扩展首位加载不构成当前业务授权证明。
> **依据**：Agent 内核框架文档（内核契约）、存档 references/Agent框架概览.md（框架选型输入）、Agent Skills 标准 https://agentskills.io/specification（Skill 格式）。

## 一、设计原则

1. **统一内核**：全部 Agent 能力面运行在同一份 Agent 内核（`py-agent-kernel`，契约由 Agent 内核框架文档拥有）之上，Campfire 能力以领域扩展形态组织，不为单模块另建 Agent；
2. **分面自治**：内核统一，自治级别按面划分——应急面受限（代码持有控制流），异步面自主（Agent 持有控制流）；
3. **Skill 即工作流**：平台能力以 Agent Skills 标准（SKILL.md 能力包）定义，渐进披露，与运行时解耦；
4. **安全不让渡**：红线安全门、权限校验、PII 脱敏、免责声明注入由 Campfire 的 `security` 扩展以代码实现，经内核事件总线挂载（首位注册 + 启动断言），永远在 Agent 之外、LLM 不可触碰；
5. **契约驱动**：Agent 的结构化输出（四段式、L2 卡片、复盘报告）一律由 Pydantic 模型约束，与 `py-schemas` 契约体系同构。

## 二、架构总览

```
┌─────────────────────────────────────────────────────────┐
│ 表层编排（代码持有控制流，FastAPI / Worker）                 │
│  应急面：预取并行 → 预注入 → 强制加载 Skill → 单轮生成       │
│  异步面：任务触发 → Agent 自主执行                          │
├─────────────────────────────────────────────────────────┤
│ Campfire 领域扩展（内核扩展形态：工具 + Skill + 输出契约）   │
│  emergency 扩展 · case 扩展 · knowledge 扩展 …            │
├─────────────────────────────────────────────────────────┤
│ Agent 内核 py-agent-kernel（契约见 Agent内核框架.md）       │
│  ExtensionAPI · 事件总线 · Session · skill-loader            │
│  （安全能力 = security 扩展，首位注册 + 启动断言）              │
├─────────────────────────────────────────────────────────┤
│ pydantic-ai（Agent 循环 · 消息模型 · 流式 · provider）      │
├─────────────────────────────────────────────────────────┤
│ py-rag（检索/切片/嵌入） · py-db · py-cache · py-auth 等    │
└─────────────────────────────────────────────────────────┘
```

## 三、领域工具清单

工具是领域能力的原子封装，按领域扩展组织（工具契约与注册机制由 Agent 内核框架文档 §五 拥有）。**扩展边界 = 机制模块边界**（1:1 镜像，不发明新分组规则）；扩展归属仅声明所有权，运行期寻址与白名单一律按工具名（pi 语义）。初版扩展划分：

| 扩展 | 对应机制模块 | 工具 | Skill | 输出契约（py-schemas 拥有） |
|---|---|---|---|---|
| `emergency` | 智能应急咨询 | —（经白名单消费他扩展工具） | `emergency-consult` | 四段式 |
| `case` | 标准案例库 | `rag_search`、`ebp_suggest` | `case-extraction`、`review-assist` | L2 卡片、预审报告 |
| `profile` | 个性化档案库 | `profile_get`、`event_add` | `trend-report` | 复盘报告 |
| `ticket` | 人工兜底通道 | `ticket_create` | `ticket-enrich` | 工单摘要 |
| `knowledge` | 科普查阅 | `knowledge_search` | `knowledge-qa` | — |
| `security` | 红线安全门与兜底策略 | `pii_scan` | — | 脱敏建议 |

要点：emergency 扩展不持有工具（应急面工具分属 profile/case/ticket，经白名单消费，扩展间零 import）；`trend-report` 归 profile（输入是档案事件流，所有权跟数据走）；`pii_scan` 归 security（消费者横跨预审/工单多个异步场景，与红线门同模块）；输出契约不进扩展目录，统一由 `py-schemas` 拥有（DSR-002），扩展经 Skill metadata `output-schema` 声明引用。

扩展物理形态：`packages/py-agent-extensions/` 单包多子包（`py_agent_extensions/emergency/` 等）；api-server 与 worker 启动时显式声明扩展清单与加载顺序（`security` 首位），并注入面白名单配置。

初版工具清单（按面白名单）：

| 工具 | 职责 | 应急面 | 异步面 |
|---|---|---|---|
| `rag_search` | pgvector 混合检索案例切片（语义 + 标签过滤） | 代码预取 + 追问轮自主调用（ADR-009） | ✅ |
| `profile_get` | 读取指定档案（含权限校验） | 仅代码预取 | ✅ |
| `event_add` | 添加档案事件记录 | ❌ | ✅（复盘/协作场景） |
| `ticket_create` | 创建人工工单 | ✅（由确定性兜底信号触发，ADR-009） | ✅ |
| `pii_scan` | PII 检测与脱敏建议 | 代码层必检 | ✅ |
| `ebp_suggest` | NCAEP EBP 标签建议 | ❌ | ✅（案例提取） |
| `knowledge_search` | 科普知识库检索 | ❌ | ✅（科普面） |

约束：工具实现内必须自带权限与参数校验（不信任 Agent 传入的调用上下文）；工具的读写范围遵循安全扩展在事件总线上的校验规则。

## 四、Skill 目录

Skill 采用 Agent Skills 标准（https://agentskills.io/specification）：每个 Skill 是一个目录，含 `SKILL.md`（frontmatter + 工作流指令），可附 `scripts/`、`references/`（发现与渐进披露机制由 Agent 内核框架文档 §七 拥有）。初版 Skill 清单：

| Skill | 触发情境 | 执行面 |
|---|---|---|
| `emergency-consult` | 应急咨询生成 | 应急面（强制加载） |
| `case-extraction` | L1 叙事 → L2 卡片提取 | 异步面 |
| `review-assist` | 案例 AI 预审（格式/PII/循证一致性） | 异步面 |
| `ticket-enrich` | 工单预组装（上下文 + 兜底信号分析 + 专家匹配建议） | 异步面 |
| `trend-report` | 事件趋势复盘生成 | 异步面 |
| `knowledge-qa` | 科普问答（含案例关联推荐） | 异步面 |

**Campfire Skill 扩展约定**（写入各 SKILL.md 的 `metadata`，经内核 metadata 透传机制传递，不破坏标准）：

- `output-schema`：指向 `py-schemas` 中的 Pydantic 输出契约（结构化输出强制校验）；
- `surface`：`emergency` / `async`，声明该 Skill 允许的执行面；
- `eval-set`：指向该 Skill 的评测集路径（质量门禁用）。

**Skill 与运行时的可移植性**：Skill 包为标准格式，生产侧由内核加载；同一批包可被 Pi、Claude Code 等 harness 在运营/开发侧直接复用（如本地批量处理机构脱敏案例、测试应急话术）。

## 五、分面执行策略

### 5.1 应急面（P0 同步链路，受限自治）

> 按 ADR-009 演进：链路前置确定性「此刻安全层」，首轮生成后为会话内多轮。

```
家属点选行为桶（可附文字）→ 红线安全门判定（代码层纯规则，规则由机制红线安全门文档拥有）
  ├─ 命中红线：高危桶卡 + 就医指引（不经 Agent；M4 后追加特急工单）
  └─ 未命中：
      ⓪ 此刻安全层（代码层）：通用卡 → 桶卡 → 阶段单点问题，零 LLM
      ① 编排代码并行预取：profile_get + rag_search（确定顺序与参数）
      ② 预注入上下文（≤5 事件 + Top-K 3-5 案例 + 会话记录：桶/阶段/已展示卡内容）
      ③ 强制加载 emergency-consult Skill（不依赖模型自主选择）
      ④ Agent 单轮生成首份方案，输出受四段式 Pydantic 契约校验
      ⑤ 追问轮：通用 Agent 会话（自由回复，不套契约），放行 rag_search 自主调用
      ⑥ 确定性兜底信号后校验（代码层）：检索质量不足/未解决标记/连续追问 → ticket_create（M4 后）
```

- 工具白名单：`ticket_create` + `rag_search`（仅追问轮）；首份方案 max_steps = 1；硬超时；
- 红线关键词门对每条用户输入（含追问）生效；
- TTFT 工程前提：注入精选、DeepSeek 上下文缓存命中静态部分、首字前零工具调用；
- **实测门禁**：staging 环境对比实测——Agent 面相对纯管线的**编排开销 ≤ 1s**，超标则本面回退纯管线方案。TTFT 绝对值为需求侧设计目标（P50 ≤ 3s，P95 > 5s 告警，归需求文档非功能需求），供应商侧延迟不作为架构回退依据。

### 5.2 异步面（案例/预审/复盘/工单/科普，完整自主）

- Agent 按任务描述自主发现、加载、链式执行 Skill；
- 多轮工具调用允许，步骤顺序由 SKILL.md 工作流指令引导；
- 结构化产出（L2 卡片、预审报告、复盘报告、工单摘要）同样受 Pydantic 契约校验；
- 失败语义：工具异常进入重试（≤3 次），最终失败落库标记并通知，不允许静默吞错。

## 六、可观测与评测

| 维度 | 方案 |
|---|---|
| **工具调用审计** | 每次工具调用落审计日志（trace_id 贯通，沿用 py-logger） |
| **Token 追踪** | 按 Skill/面维度统计 Token 消耗，对接成本告警 |
| **Skill 评测集** | 每个 Skill 维护 eval-set（验收用例），Prompt/模型变更后必须全量回归 |
| **输出校验** | 结构化输出一律经 Pydantic 契约校验，不合格输出阻断并记录 |

## 七、对现有代码资产的影响（重构方向）

| 现有资产 | 处置 |
|---|---|
| `py-rag`（hybrid_search、切片、嵌入） | **保留**，作为 `rag_search` 等工具的实现底座；LangChain 依赖逐步退出 |
| `py-llm`（DeepSeek 封装） | **由 pydantic-ai 模型层取代**，随内核落地后退役 |
| `py-schemas` | **强化**，新增 Agent 输出契约（四段式、L2 卡片、复盘报告等） |
| 红线安全门管道 | **保留在代码层**，改由 `security` 扩展经事件总线挂载（应急面的安全前置） |
| SSE 流式链路 | **保留**，改由内核事件总线的流式输出驱动 |
| 自研 skill-loader（ADR-007） | **上收**为 `py-agent-kernel` 组件，不再是 Campfire 私有件 |

> 具体重构计划与迁移顺序属于增量实施规划，不在本文范围。
