# ADR-007：应用 Agent 化——统一基座（Pydantic AI）+ 分面自治

> **状态**：有效（2026-06-30 决策）
>
> **关联**：本文安全约束中的「危机分级三层判定」已由 [ADR-008](./ADR-008-二元安全门取代三级危机分级.md) 演进为二元安全门（2026-07-02），「规则引擎 0ms 硬拦截、代码持有控制流」的实质约束不变。

## 上下文

原有 RAG 实现为简单检索-生成管线。需求基线 v2.0 确立后，决定将整个应用 Agent 化：平台各功能转化为 Skill（Agent Skills 标准，SKILL.md 能力包）与工具，由统一 Agent 基座承载。三个硬约束：

1. **安全约束**：危机分级三层判定（规则引擎 0ms 硬拦截、LLM 无权降级）、TTFT ≤ 3s、零幻觉验收——P0 应急同步链路的控制流必须由代码持有；
2. **工程约束**：不在 Agent 底座上自造轮子，通用 Agent 框架即可；不拘泥于现有代码实现，允许重构；
3. **成本约束**：DeepSeek 为主模型（ADR-005），框架必须模型无关。

## 备选与评价

| 框架 | 评价 |
|---|---|
| **LangGraph** | 图状态机能力最强，但学习曲线最陡，其价值（显式状态机、时间旅行调试）本项目仅应急面需要一小块，而该块用普通 FastAPI 编排代码即可表达；与「不为底座造轮子」约束相悖 |
| **OpenAI Agents SDK** | 接入极简，Handoff/Guardrail 原语贴合「应急→工单」场景；但设计围绕 GPT 优化，DeepSeek 下部分原生能力闲置，存在厂商意见锁定 |
| **Pi SDK** | 原生支持 Agent Skills 标准、极简完整；但为 TypeScript 编码 Agent 框架，采用它意味着整个后端换语言或引入 Node 边车（工具调用需跨进程访问 PostgreSQL），双语言运维成本远超其省下的 skill-loader 工作量 |
| **Claude Agent SDK** | 原生 Skills，但 Claude 模型优化、非模型无关，与 ADR-005 冲突 |
| **Dify 等平台型** | 可视化范式无法表达分面自治与危机分级精确控制流 |
| **Pydantic AI** | Python 原生、FastAPI 式 DX、全链路类型安全；DeepSeek 一等支持；结构化输出由 Pydantic 模型约束，与项目契约驱动文化（py-schemas、contract-driven-dev）同构；Agent 循环/工具/MCP/持久化执行开箱即用，底座零自建 |

## 决定

1. **统一 Agent 基座采用 Pydantic AI**：运行时 + 工具注册中心 + Skill 目录 + 可观测，一份基座承载全部 Agent 能力面；
2. **Skill 采用 Agent Skills 标准**（SKILL.md 能力包，渐进披露），与运行时解耦——生产侧由基座加载，运营/开发侧可被 Pi、Claude Code 等 harness 复用；
3. **分面自治策略**：
   - **应急面**（P0 同步链路）：编排代码并行预取档案/案例并预注入 → 强制加载应急 Skill → Agent 单轮生成；工具白名单仅 `ticket_create`；硬超时；危机分级三层判定在 Agent 之外的代码层；
   - **异步面**（案例提取、AI 预审、工单预组装、趋势复盘、科普问答）：Agent 自主发现、加载、链式执行 Skill；
4. **自研薄 skill-loader**（约 150 行：扫描发现 → frontmatter 提取 → description 注入 → 按需加载 → allowed-tools 过滤）；
5. **TTFT 实测门禁**：staging 环境 P95 TTFT ≤ 3s 实测达标，不达标则应急面回退纯管线。

详细架构见[技术设计/Agent基座](../Agent基座.md)。

## 后果

- 正面：Agent 底座零自建；结构化输出契约原生满足零幻觉验收的输出校验；Skill 生态与 Pi/Claude Code 互通；Python 单语言栈保持；
- 负面：skill-loader 为自研件需维护（约 150 行，Agent Skills 标准演进时需跟进）；LangChain 的编排角色由 Pydantic AI 接管，`py-rag` 保留检索/切片/嵌入职能，LangChain 依赖逐步退出；`py-llm` 的 DeepSeek 封装由 Pydantic AI 模型层取代；Agent 行为引入非确定性，需为各 Skill 建立评测集（evals）作为质量门禁。

## 重访条件

- Pydantic AI 停止维护或演进方向偏离（如放弃模型无关性）；
- 应急面实测 TTFT 持续不达标且优化无效，回退纯管线后重新评估；
- Agent Skills 标准出现官方 Python 运行时且成熟，替换自研 skill-loader。
