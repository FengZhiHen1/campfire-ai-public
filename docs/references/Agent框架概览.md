## 一、生产级框架（Tier 1）

2026 年，以下框架占据了绝大多数生产级 Agent 工作负载，各自对应不同的编排范式与部署语境。

### 1. LangGraph — 图状态机范式
| 维度 | 说明 |
|------|------|
| **编排风格** | 有向图状态机（节点 = 处理步骤，边 = 状态转移） |
| **语言** | Python、TypeScript |
| **模型锁定** | 低（支持多厂商） |
| **MCP 支持** | 原生 |
| **核心能力** | 持久化执行（Checkpointing）、时间旅行调试、人工审批断点、循环/分支/重试、并行化 |
| **生产信号** | ~400 家企业部署，包括 Klarna、Uber、LinkedIn、JPMorgan、BlackRock、Cisco、Replit、GitLab；月下载量 3450 万；2025 年 10 月 v1.0 GA；每周多次版本发布（2026 年 4 月已至 v1.1.9） |
| **可观测性** | LangSmith 深度集成——业界最强的 Trace 分析能力；Developer 免费层 5000 traces/月，Plus $39/seat/月含 10000 base traces + Fleet agent 管理 |
| **适用** | 受监管行业、长时工作流、错误成本高于接入成本的场景 |
| **短板** | 学习曲线最陡（团队通常需 1–2 周才能高效产出），简单线性任务会显得过度设计；Python 优先，JS/TS 版功能滞后 |

### 2. CrewAI — 角色扮演范式
| 维度 | 说明 |
|------|------|
| **编排风格** | 角色化 Crew（研究员 → 写手 → 编辑），支持顺序与层级两种工作流模式 |
| **语言** | Python |
| **模型锁定** | 低（25+ LLM 提供商开箱即用） |
| **MCP 支持** | 原生（v1.10+） |
| **核心能力** | 20–50 行代码即可构建多 Agent 协作原型；任务分解与委托；YAML 配置驱动；分层记忆系统；可视化 Studio（CrewAI+ 企业版） |
| **生产信号** | 49,800+ GitHub Stars；约 60% 的 Fortune 500 有使用记录；FedRAMP High 合规认证；从零构建，不依赖 LangChain |
| **适用** | 快速原型、内容生成管线、角色边界清晰的线性工作流 |
| **短板** | 简单工作流的 Token 开销可达 LangGraph 的 3 倍；角色抽象在复杂分支场景下会受限；集成生态和经过实战检验的模式少于 LangChain |

### 3. Microsoft Agent Framework — 企业级图工作流
| 维度 | 说明 |
|------|------|
| **编排风格** | 图工作流（AutoGen 多 Agent 对话抽象 + Semantic Kernel 企业工具的统一体） |
| **语言** | Python、.NET |
| **模型锁定** | 中（Azure 生态） |
| **MCP 支持** | 原生 |
| **核心能力** | 浏览器 DevUI、负责任 AI 原语、人工审批工作流、Cosmos DB 状态持久化、Application Insights 可观测性 |
| **生产信号** | 2026 年 4 月 v1.0 GA；微软将 AutoGen 正式移入维护模式，全面转向此框架 |
| **适用** | .NET / Azure 原生企业、需要治理与合规栈的团队 |
| **短板** | 非微软生态吸引力较弱；AutoGen 0.2 迁移至新图模型有实际工程成本 |

### 4. OpenAI Agents SDK — 交接链范式
| 维度 | 说明 |
|------|------|
| **编排风格** | Handoff 链（显式控制转移，替代早期混乱的多 Agent 对话模式） |
| **语言** | Python、TypeScript |
| **模型锁定** | 低（支持 100+ LLM，但设计明显围绕 GPT 优化） |
| **MCP 支持** | 原生 |
| **核心能力** | Agent / Handoff / Guardrail / Session / Tracing 五大原语；原生沙箱执行（Blaxel、Cloudflare、E2B 等）；子 Agent 模式；语音 Agent（Realtime API 集成） |
| **生产信号** | ~19,000 GitHub Stars；月下载量 1030 万；2026 年 4 月重大改版 |
| **适用** | GPT 中心型部署、需要沙箱工具执行、语音 Agent、追求极简接入 |
| **短板** | 复杂分支逻辑与显式状态管理能力弱于图框架；存在厂商意见锁定 |

### 5. Google ADK — 层级代理范式
| 维度 | 说明 |
|------|------|
| **编排风格** | 层级代理树（父 Agent 编排子 Agent，执行自上而下委托、结果自下而上返回） |
| **语言** | Python |
| **模型锁定** | 中（Gemini 体验最佳） |
| **MCP 支持** | 原生 |
| **核心能力** | 原生多模态（图像、音频、视频统一推理）；Vertex AI 托管部署；A2A 跨框架互操作（50+ 合作伙伴含 Salesforce、ServiceNow）；三种持久化模式（内存/数据库/Vertex AI 托管） |
| **生产信号** | 17,000+ GitHub Stars；2026 年 4 月发布 |
| **适用** | GCP 原生团队、多模态工作流、视觉质检、语音客服 |
| **短板** | 生态仍在形成中；非 Gemini/Vertex AI 环境体验降级 |

### 6. Vercel AI SDK 7 / eve — TypeScript 优先的 Agent 平台
| 维度 | 说明 |
|------|------|
| **编排风格** | 工具循环 Agent + 持久化工作流（ToolLoopAgent / WorkflowAgent） |
| **语言** | TypeScript |
| **模型锁定** | 低（所有主流提供商开箱即用） |
| **MCP 支持** | 原生（MCP Apps：模型可见 vs 应用级工具分离、沙箱 iframe 渲染、JSON-RPC 通信） |
| **核心能力** | AI SDK 7（2026 年 6 月发布）：统一跨厂商 API（流式/工具调用/结构化输出）、WorkflowAgent 持久化执行、终端 TUI 调试器、OpenTelemetry 可观测性、HarnessAgent 统一接口（可运行 Claude Code / Codex / Pi 等 harness）、provider 文件上传与技能上传、多模态（语音/转录/图像/视频生成） |
| **生产信号** | npm 周下载量 1600 万；AI SDK 已成为 TypeScript Web 应用的事实标准 AI 层 |
| **eve 框架** | Vercel 在 Ship 2026 发布的开源 Agent 框架，定位"Next.js for Agents"——每个 Agent 是一个目录，内置持久化执行、沙箱计算、审批、子 Agent、评估；Agent Stack 全栈：AI SDK + AI Gateway + Workflow SDK + Vercel Sandbox + Chat SDK + Vercel Connect（短生命周期凭据替代长期 token） |
| **适用** | TypeScript / Next.js 全栈团队、AI 原生 Web 应用、需要将 Agent 嵌入现有 Web 产品 |
| **短板** | 仅 TypeScript；WorkflowAgent 和 eve 较新，生产验证尚不充分 |

### 7. Strands Agents — AWS 原生模型驱动框架
| 维度 | 说明 |
|------|------|
| **编排风格** | 模型驱动编排（LLM 自主推理规划，开发者只需提供 prompt + 工具列表） |
| **语言** | Python、TypeScript |
| **模型锁定** | 低（Amazon Bedrock、OpenAI、Anthropic、本地模型均支持，切换提供商无需改代码） |
| **MCP 支持** | 原生 |
| **核心能力** | 内置多 Agent 原语（Agent-as-Tool、Swarm、图工作流、Handoff）、A2A 支持；30 行代码构建研究助手；OpenTelemetry 分布式追踪；原生 AWS 服务集成（Bedrock Guardrails、AgentCore Runtime、Lambda、EKS、EC2）；双向语音 Agent（BidiAgent） |
| **生产信号** | Apache 2.0 开源；AWS 内部已用于 Amazon Q、AWS Glue 等产品；Smartsheet、Swisscom、Eightcap（调查时间从 30 分钟降至 45 秒，节省 $5M 运营成本）等企业采用 |
| **适用** | AWS 生态团队、需要企业级安全与可观测性、从 PoC 到生产无缝过渡 |
| **短板** | AWS 生态外的吸引力有限；社区规模小于 LangGraph / CrewAI |

---

## 二、领域强项框架（Tier 2）

这些框架在特定场景下具有不可替代性，但通用性不如 Tier 1。

| 框架 | 语言 | 核心定位 | 编排风格 | 关键差异 |
|------|------|----------|----------|----------|
| **Claude Agent SDK** | Python, TS | Claude Code 基础设施库化 | 工具 + 沙箱 | Anthropic 官方 SDK，与 Claude Code 同一架构；原生 Hooks 系统、MCP、Skills、Subagents；TypeScript 和 Python 双 SDK 功能对等；Claude 模型优化，非模型无关 |
| **Pydantic AI** | Python | 类型安全的可组合 Agent | 可组合原语 | FastAPI 式开发体验，全链路类型安全（输入/工具/输出），支持 YAML/JSON 无代码定义 Agent，原生 MCP + A2A + 持久化执行，~16,600 Stars 且增速极快；2026 年 6 月 v2.1.0 发布 |
| **LlamaIndex** | Python, TS | 检索优先的 Agent 栈 | 检索中心 | RAG 与知识库场景的最佳底座，700+ 数据连接器，LlamaParse v2 文档解析能力突出；但复杂多 Agent 编排需配合其他框架 |
| **Mastra** | TypeScript | TS 原生 Agent 框架 | 工作流 + Agent | 19,000+ Stars，30 万+ 周下载量；Workflow、HITL、Next.js 集成；3300+ 模型支持；内置调试器；TS 全栈团队的首选 |
| **Agno** (原 Phidata) | Python | 高吞吐多 Agent 运行时 | 轻量 Swarm | ~39,000 Stars；比 CrewAI 更少意见约束，比 LangGraph 更易水平扩展；适合大批量内容生成、社媒自动化、分布式研究 squad |
| **Llama Stack** | Python, Kotlin | Meta 官方开放 Agent 运行时 | 服务导向 API | Meta 出品，1.0 GA；REST API 优先设计（Inference/Safety/Memory/Agents/Eval/Telemetry 六大 API）；插件式 Provider 架构（Cerebras/Fireworks/Together/Ollama/vLLM 等）；同一 API 从本地到云到边缘无缝迁移；原生 MCP 支持；Llama 模型最佳适配 |
| **Griptape** | Python | 企业级可控 Agent 框架 | 管道 + 工作流 + Agent | Apache 2.0 开源；Off-Prompt™ 架构（数据不进 prompt，通过 Tool Memory 隔离）；信任边界、Schema 验证、活动级权限控制；Pipeline/Workflow/Agent 三种结构自由组合；2026 年被 Foundry 收购但开源框架持续维护 |

---

## 三、极简 / 工具驱动框架（Tier 2.5）

这类框架以"少即是多"为哲学，用极少的抽象层让 LLM 直接发挥能力，适合需要深度控制和对框架膨胀说"不"的团队。

### Pi (pi-mono) — OpenClaw 背后的极简 Agent 框架
| 维度 | 说明 |
|------|------|
| **编排风格** | 分层 monorepo，每层独立可用 |
| **语言** | TypeScript |
| **模型锁定** | 低（统一 API 支持 Anthropic/OpenAI/Google/xAI/Groq/Cerebras/OpenRouter/Ollama/Mistral/MiniMax/智谱等 2000+ 模型） |
| **MCP 支持** | 通过扩展系统支持 |
| **核心能力** | 4 核心工具（read/write/edit/bash）+ 系统 prompt < 1000 tokens 的极简哲学；分层架构：pi-ai（统一 LLM API）→ pi-agent-core（Agent 循环 + 工具调用 + 状态管理）→ pi-coding-agent（完整编程 Agent 运行时，内置文件工具/JSONL 会话持久化/上下文压缩/Skills/扩展系统）→ pi-tui（差分渲染终端 UI）；4 种运行模式（交互式 / print-JSON / RPC / SDK 嵌入）；AgentSession SDK 可嵌入任意应用 |
| **生产信号** | 18,200+ GitHub Stars；驱动 OpenClaw（145,000+ Stars 多渠道 AI 助手，首周即爆火）；由 Mario Zechner（libGDX 创作者）开发；npm 供应链安全一等公民（精确版本锁定、min-release-age、audit signatures） |
| **适用** | 需要自行扩展的终端编程 Agent、只想用统一 LLM 调用层、想在产品中嵌入通用 Agent 运行时、关注供应链安全 |
| **短板** | 默认无权限沙箱（需自行容器化）；极简设计意味着开箱即用功能少于"大而全"框架；社区较新 |

### OpenClaw — 多渠道 Agent 平台（基于 Pi）
| 维度 | 说明 |
|------|------|
| **编排风格** | 多渠道网关 + 嵌入式 Agent 运行时 |
| **语言** | TypeScript |
| **核心能力** | 29 个聊天渠道（WhatsApp/Telegram/Discord/Slack/iMessage/Signal/Teams/微信等）、64 个模型提供商、142 个官方插件；多 Agent 路由与会话隔离；浏览器自动化、Shell 执行、文件操作；持久记忆；iOS/Android 移动节点；富媒体支持（图片/音频/视频/文档） |
| **生产信号** | 145,000+ GitHub Stars（首周即爆火）；由 Peter Steinberger 创建；v0.8.0（2026 年 3 月）性能提升 40%，全球 20000+ 开发者使用 |
| **适用** | 需要跨多个聊天平台部署 AI 助手、本地优先隐私需求、个人/团队自动化 |
| **短板** | prompt injection 仍是行业级未解问题；快速迭代中稳定性仍在提升 |

---

## 四、专业化与新兴框架（Tier 3）

### 4.1 通用 Agent 框架

| 框架 | 语言 | 核心定位 | 状态与适用场景 |
|------|------|----------|----------------|
| **DSPy** | Python | 提示编译优化 | 斯坦福 NLP 出品，将提示工程视为编译问题而非手工写作；~23,000 Stars；适合将提示质量作为一级成本驱动的研究/生产场景 |
| **Letta** (原 MemGPT) | Python | 持久记忆 Agent | 操作系统式记忆层级；适合跨会话长期记忆、陪伴型 Agent、需要记住数周/数月前事实的系统 |
| **Haystack** | Python | 搜索与文档管线 | 2019 年诞生，确定性流控制优于自主规划；适合受监管、搜索密集、可预测性优先于自主性的部署 |
| **mcp-agent** | Python | MCP 原生架构 | 以 Model Context Protocol 为架构锚点而非功能适配；完整 MCP 实现（工具/资源/提示/通知/OAuth/采样），一行配置接入 Temporal 持久化；适合协议优先的构建 |
| **AG2** (原 AutoGen) | Python | 学术多 Agent 研究 | AutoGen 的社区独立分支；2026 Beta 新增流式、事件驱动架构、多提供商 LLM、依赖注入；适合学术实验，不建议承载面向客户的生产应用 |
| **smolagents** | Python | 代码执行 Agent | Hugging Face 维护，核心能力是"写 Python 并执行"；适合以调用 Python 库为主要价值的场景 |
| **Semantic Kernel** | Python, C#, Java | 企业多语言一致性 | 唯一在 Python/C#/Java 上提供第一方 SDK 的框架；适合已有 .NET/Java 存量代码的企业 |
| **Atomic Agents** | Python (Go 移植) | 极简可控 Agent | BrainBlend AI 出品，基于 Instructor + Pydantic；Atomic Design 方法论——每个组件单一职责、独立可测、可替换；开发者保持完全控制，优先可预测性而非自主性；MIT 许可 |
| **Bee Agent Framework / BeeAI** | TypeScript, Python | 跨框架多 Agent 互操作 | IBM Research 出品，Linux 基金会托管；基于 ACP（Agent Communication Protocol）——让不同框架/语言的 Agent 互相发现、通信、协作；支持 Granite/Llama/OpenAI/Claude/watsonx 等；OpenTelemetry + Arize Phoenix 可观测性；Python 和 TypeScript 双语实现 |

### 4.2 SOP 驱动 / 软件开发专用

| 框架 | 语言 | 核心定位 | 状态与适用场景 |
|------|------|----------|----------------|
| **MetaGPT** | Python | SOP 驱动的软件开发多 Agent | 66,000+ GitHub Stars；DeepWisdom 团队维护；将真实软件团队 SOP（PM → 架构师 → 工程师 → QA）编码为多 Agent 工作流，一行需求产出 PRD/设计文档/API 规范/可运行代码/测试；消息总线架构，结构化制品流转防止幻觉漂移；Data Interpreter 扩展支持数据分析；商业版 Atoms (atoms.dev) 提供托管服务 |
| **CAMEL-AI** | Python | 角色扮演多 Agent 通信 | NeurIPS 2023；自称"第一个多 Agent 框架"；核心创新 Inception Prompting——两个 LLM 分别扮演角色自主对话至任务完成；Workforce 模块支持层级任务分配；OASIS 支持百万级 Agent 社交模拟；100+ 研究者社区；适合多 Agent 通信研究、合成数据生成、世界模拟 |

### 4.3 社交 / Web3 Agent

| 框架 | 语言 | 核心定位 | 状态与适用场景 |
|------|------|----------|----------------|
| **Eliza** (elizaOS) | TypeScript | 社交平台自治 Agent | 18,000+ Stars，MIT 许可；支持 Discord/Telegram/Twitter/Slack 等社交平台；Character 文件驱动（JSON 定义人格/目标/行为）；RAG 记忆、插件生态、多 Agent 协作；Web3 原生支持（区块链读写/智能合约交互）；本地优先 + 可选 Eliza Cloud；定位"AI Agent 操作系统"，覆盖 Web/桌面/移动端 |

---

## 五、低代码 / 可视化 / 平台型

| 平台 | 类型 | Stars | 核心特征 |
|------|------|-------|----------|
| **n8n** | 开源工作流 + AI Agent | 196,377 | 400+ 集成，拖拽式构建，支持自托管，原生 LLM 节点（OpenAI/Claude/Ollama），但本质是工作流平台而非纯 Agent 框架 |
| **Dify** | 企业级 Agent 应用平台 | 148,791 | 可视化 Agent 构建器、内置 RAG 引擎、模型管理、API 发布、RBAC；比纯框架更重，资源消耗更高，但提供完整的生产平台 |
| **AutoGPT** | 自主目标导向 Agent | 185,526 | 2023 年 Agent 热潮的源头，"给定目标即自主执行"；2026 版本更稳定，适合自主研究/数据采集，但复杂工作流可靠性不足 |

---

## 六、按编排范式的分类矩阵

2026 年的生产 Agent 系统，本质上由以下编排模式驱动：

| 编排范式 | 代表框架 | 心智模型 | 适用场景 |
|----------|----------|----------|----------|
| **图状态机** | LangGraph, Microsoft Agent Framework | 节点 + 边，显式状态转移 | 受监管、需审计、长时、需人工审批 |
| **角色扮演** | CrewAI, Agno, CAMEL-AI | "研究员交给写手交给编辑" | 内容管线、快速原型、角色边界清晰 |
| **交接链** | OpenAI Agents SDK, Strands Agents | 显式控制转移，非对话式 | GPT 中心、语音、沙箱工具 |
| **层级代理** | Google ADK | 父 Agent 委托子 Agent | 企业级联、多模态、GCP 原生 |
| **模型驱动** | Strands Agents | LLM 自主推理规划，开发者只给 prompt + 工具 | AWS 生态、快速从 PoC 到生产 |
| **检索中心** | LlamaIndex, Haystack | 数据连接器 + 索引策略 | RAG、知识库、文档搜索 |
| **提示编译** | DSPy | 签名 + 模块 → 自动优化提示 | 提示质量为一级成本驱动 |
| **记忆中心** | Letta | OS 式记忆层级 | 跨会话长期记忆、陪伴 Agent |
| **SOP 驱动** | MetaGPT | 编码真实团队标准操作流程 | 软件开发全流程自动化 |
| **极简工具** | Pi, Atomic Agents | 最少抽象，LLM 直接发挥 | 深度控制、嵌入运行时、反框架膨胀 |
| **服务导向 API** | Llama Stack | REST API 优先，插件式 Provider | Llama 模型生态、本地到云无缝迁移 |
| **跨框架互操作** | BeeAI | ACP 协议统一不同框架的 Agent | 混合框架环境、异构 Agent 协作 |

---

## 七、关键协议与互操作性

2026 年，协议开放性已成为框架选型的核心考量，几乎与框架能力同等重要：

| 协议 | 定位 | 主导方 | 生态状态 |
|------|------|--------|----------|
| **MCP (Model Context Protocol)** | Agent ↔ 工具/数据源 的连接标准 | Anthropic → Linux 基金会 | Anthropic/OpenAI/Google/Microsoft/AWS/Cloudflare 等 backing；2026 年已是"table stakes" |
| **A2A (Agent-to-Agent)** | Agent ↔ Agent 的跨框架通信标准 | Google | 50+ 合作伙伴；ADK 和 Microsoft Agent Framework 原生支持 |
| **ACP (Agent Communication Protocol)** | 跨框架 Agent 发现/执行/共享 | IBM Research → Linux 基金会 | BeeAI 平台核心协议；基于 MCP 构建，预计独立于 MCP；pre-alpha 阶段，正在社区推动标准化 |

**MCP-native 框架**（协议为架构核心，非后期适配）：Pydantic AI、OpenAI Agents SDK、Google ADK、Claude Agent SDK、mcp-agent、Vercel AI SDK 7。这类框架能自动继承 MCP 协议的新能力，无需等待框架更新。

**协议选型建议**：如果你的 Agent 需要连接外部工具/数据源 → MCP 是必选项；如果需要多个 Agent 互相通信 → A2A（Google 生态）或 ACP（IBM 生态）；如果需要混合不同框架的 Agent 协作 → BeeAI 的 ACP 是当前最成熟的方案。

---

## 八、框架选择参考矩阵

| 场景 | 首选 | 强替代 |
|------|------|--------|
| 生产级有状态工作流、受监管行业 | LangGraph | Microsoft Agent Framework |
| 快速多 Agent 原型、利益相关者演示 | CrewAI | Agno |
| .NET / Azure 原生企业 | Microsoft Agent Framework | LangGraph (Python 侧) |
| AWS 原生企业 | Strands Agents | LangGraph |
| GPT 中心 + 沙箱工具 | OpenAI Agents SDK | Pydantic AI |
| GCP 原生 + 多模态 | Google ADK | LangGraph + Gemini |
| Claude 专属自主编码/研究 | Claude Agent SDK | Pydantic AI + Claude |
| Python 类型安全、可组合设计 | Pydantic AI | LangGraph |
| TypeScript / Next.js 全栈 | Vercel AI SDK 7 / eve | Mastra |
| RAG / 知识库 | LlamaIndex | Haystack |
| MCP 协议优先架构 | mcp-agent | Pydantic AI |
| 长期持久记忆 | Letta | LangGraph + 自定义记忆 |
| 学术多 Agent 实验 | AG2 / CAMEL-AI | DSPy（提示优化） |
| 软件开发全流程自动化 | MetaGPT | CrewAI（角色自定义） |
| 跨平台社交 Agent | Eliza (elizaOS) | OpenClaw |
| 跨框架 Agent 互操作 | BeeAI (ACP) | Google ADK (A2A) |
| Llama 模型生态 | Llama Stack | LangChain |
| 极简嵌入运行时 | Pi (pi-mono) | Atomic Agents |
| 企业级可控 + 数据隔离 | Griptape | Semantic Kernel |
| 无代码可视化 | n8n / Dify | — |
| 自主目标执行 | AutoGPT | — |
| 多渠道 AI 助手部署 | OpenClaw | Eliza |

---

## 九、一个关键事实

框架选择对 Agent 性能的影响，可能超过模型本身的选择。普林斯顿 HAL 基准数据显示：同一模型（Claude Opus 4）在不同编排脚手架下的 GAIA 得分差距可达 **64.9% vs 57.6%**——这一差距大于许多前沿模型迭代的提升幅度。

另一个值得注意的趋势：78% 的 2026 年生产 AI Agent 构建在排名前五的框架之上（来源：IBM 2026 Guide to AI Agents）。框架市场正在快速整合——一年前有二十多个竞争者，现在真正重要的大约只有十个。选型时，应优先考虑评估能力、可观测性和集成成熟度，而非单纯比较功能列表。

最后，对于简单场景（单 Agent + 2-3 个工具的线性工作流），社区共识是：**直接用原始 API 调用往往优于任何框架**。框架的价值在多 Agent 协调、预置集成、可观测性和调试工具——如果你的场景不需要这些，框架只会增加不必要的复杂度。
