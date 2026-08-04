# ADR-011：Agent 内核框架——内核+扩展架构与"基于 Pydantic AI、契约仿 pi"路线

> **状态**：有效（2026-08-04 决策）
>
> **关联**：演进 [ADR-007](./ADR-007-Agent化-统一基座与分面自治.md)——统一基座的定位从"Campfire 内部基座"升级为"面向多项目复用的通用内核框架"；分面自治、安全不让渡、Skill 标准等约束全部继承不变。架构细节见[技术设计/Agent内核框架](../Agent内核框架.md)。2026-08-04 术语对齐：「插件」统一为「扩展」（pi extension 语义），标题与正文已同步。

## 上下文

ADR-007 确立统一 Agent 基座（Pydantic AI）后，出现新的设计动机：**为后续多个项目沉淀一个可复用的 Agent 框架**，甚至未来可抽离为独立项目。决策者欣赏 pi（pi-mono）的设计——极简内核 + 扩展系统 + Skills 渐进披露，要求框架按"内核+扩展"组织：核心 Agent 运行时为通用内核，项目功能为扩展；且**契约不自行发明，仿照 pi**。

三个已固定的事实约束：

1. **契约溯源 pi**：内核设计完全按照 pi，所有契约仿照 pi，不自定义；
2. **安全不让渡**（ADR-007 继承）：红线门、PII、权限校验永远在 Agent 之外的代码层——由第一方安全扩展承接（扩展即代码层），安全保证锚定在受控加载，不设内核安全专属机制；
3. **孵化策略**：先在 Campfire monorepo 内按框架标准孵化（零 Campfire 依赖的独立包），出现第二个消费者时再抽离，不为尚不存在的第三方构建扩展市场/热加载基础设施。

## 备选与评价

| 方案 | 评价 |
|---|---|
| **A：完全复刻 pi** | Python 逐层复刻 pi-ai/pi-agent-core/pi-coding-agent 全部契约（官方 vendor SDK 打底 + conformance 测试控制偏差）。契约纯度 100%、零翻译层；但 LLM 统一层（wire 协议适配、provider 边角行为）是最高成本、最低差异化的商品层，自研后即背上永久的 provider 维护跑步机；Campfire 的 Pydantic 输出契约需绕道实现，工期显著拉长。仅当"复刻 pi 本身即是目标"（如发布开源 Python pi）时占优 |
| **B：基于 Pydantic AI，参考 pi 设计** | LLM 层（消息模型、流式、provider 矩阵、结构化输出）委托 Pydantic AI；harness 层（ExtensionAPI、事件总线、Session 树、skill-loader）自研且契约仿 pi。pi 的设计精华几乎全在 harness 层，可完整保留；商品层外包给活跃维护的上游。代价：存在一条 pi 语义 ↔ Pydantic AI 消息模型的接缝需维护，并引入上游依赖风险（版本锁定 + 接缝隔离管理） |
| **C：仅概念纪律** | 不建框架包，只在 api-server 内按内核+扩展的模块化纪律组织代码。成本最低，但 api-server 与 worker 的复用边界靠约定而非包结构保证，"为多项目沉淀"的动机完全落空 |

关键证据：对 Pydantic AI 2.22 的源码审计表明，其 Hooks/Capabilities/DeferredToolRequests/PendingMessage/FilteredToolset 等接缝机制已能忠实承载几乎全部 pi harness 语义（审计结论见[Agent内核框架](../Agent内核框架.md) §十），方案 B 的保真度风险远低于立项时的预期。

## 决定

1. **采用方案 B**：Agent 内核框架基于 Pydantic AI 构建，harness 层契约仿照 pi；
2. **内核收敛为单包** `packages/py-agent-kernel`：ExtensionAPI + 事件总线 + Session（JSONL 树）+ skill-loader；pi 三层中的 pi-ai、pi-agent-core 两层由 pydantic-ai 承包，无拆分对象；
3. **扩展按领域组织**：每个扩展目录自带工具与 Skill（skills/ 常规目录自动发现，吸收 pi package 行为），白名单按工具名寻址（pi 语义）；
4. **安全即扩展**：内核零安全专属机制（pi 原生「一切皆可扩展」哲学）；安全保证锚定在受控加载——全部第一方、显式注册清单、安全扩展首位注册、启动断言；fail-closed 作为事件总线通用策略；
5. **裁剪**：不做 TUI/themes/包管理/MCP 内置/sub-agent/plan mode（沿袭 pi 哲学）；
6. **Pydantic AI 的双重副用**：作为 provider 边角行为的实现参考；其 HITL/审批原语作为内核 `tool_call` 阻断挂钩的承载机制。

## 后果

- 正面：harness 契约（框架的真正差异化资产）完整保真 pi；LLM 商品层零自建、provider 维护由上游吸收；Campfire 输出契约（四段式/L2 卡片）经 `output_type` 原生落地；框架未来抽离时 LLM 层无自研包袱；
- 负面：引入 pydantic-ai 上游依赖（大版本升级冲击内核，以版本锁定 + 接缝层隔离管理）；pi 语义与 Pydantic AI 消息模型之间存在一条接缝层需长期维护；两项边缘语义存在显式偏差（并行工具 preflight 事件序、工具级 `terminate`），已记录偏差清单；
- 对 ADR-007 的影响：原"自研薄 skill-loader（约 150 行）"上收为内核框架组件，不再是 Campfire 私有件；"统一基座（Pydantic AI）"演进为"py-agent-kernel（基于 pydantic-ai）"，Campfire 的工具/Skill 改以领域扩展形态组织；"安全不让渡"由"安全扩展即代码层 + 受控加载"承接，实质约束不变。

## 重访条件

- pydantic-ai 停止维护、演进方向偏离（如放弃模型无关性或 Hooks 能力退化）→ 重估方案 A（自研复刻全部三层）；
- 接缝层维护成本实测超过预期（如连续两个大版本需要重写映射）→ 重估方案 A；
- 出现第二个框架消费者 → 执行抽离（搬仓库 + API 冻结），届时重审扩展契约的向后兼容承诺；
- pi 发布 Python 官方实现 → 评估直接采用以取代自研 harness 层。
