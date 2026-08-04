# Agent 内核框架

> **本文唯一拥有**：通用 Agent 内核（`py-agent-kernel`）的架构与契约——扩展契约（ExtensionAPI）、事件总线、工具契约、Session 与上下文、Skill 目录、安全扩展约定、保真度审计与偏差清单。
> **状态**：架构基线（2026-08-04，[ADR-011](./决策/ADR-011-Agent内核框架-内核加扩展与PydanticAI路线.md)）。本文描述的是面向多项目复用的通用框架，Campfire 仅为第一个消费者；Campfire 的面编排与安全规则归 [Agent基座](./Agent基座.md)。2026-08-04 经保真度审查修订：会话格式目标降级为结构同构、并行工具偏差归因修正、内联阻断与 HITL 审批挂载点拆分、事件粒度近似与 extension.yaml 自造契约补入偏差清单；术语严格对齐 pi——「插件」统一为「扩展」（pi extension），组织轴表述修正为 extension 语义、package 层裁剪及其 skills/ 自动发现的吸收记入偏差清单（均见 §十）。
> **依据**：[pi](https://pi.dev) 三层架构与扩展哲学（harness 层契约源头）、[Agent Skills 标准](https://agentskills.io/specification)（Skill 格式）、Pydantic AI 2.22 源码能力审计（LLM 层与接缝机制，审计结论见 §十）。

## 一、定位与设计原则

**定位**：通用 Agent 框架，为未来多个项目沉淀稳定契约；以"内核 + 扩展"组织——核心 Agent 运行时作为通用内核，宿主项目的一切领域能力作为扩展。在 Campfire monorepo 内按框架标准孵化（`packages/py-agent-kernel`，零 Campfire 依赖、独立文档与测试），出现第二个消费者时抽离为独立项目。

设计原则：

1. **内核零领域知识**：内核不含任何业务概念；领域工具、Skill、输出契约全部以扩展形式注册；
2. **契约溯源，不自行发明**：harness 层契约（ExtensionAPI、事件名、工具接口、Session 格式）仿照 pi 设计移植；LLM 层契约（消息模型、流式事件、provider 接入）委托 Pydantic AI，自定义面只剩两者之间的接缝；
3. **极简内核**：沿袭 pi 哲学——内核只提供循环承载、扩展机制与 Skill 渐进披露；sub-agent、plan mode、MCP 等不作为内核能力，需要时以扩展实现；
4. **一切都是扩展**：安全能力同样是扩展（pi 原生哲学——权限门用扩展实现）。内核无任何安全专属机制；安全保证锚定在受控加载上（全部第一方、显式注册、无热加载），见 §八；
5. **孵化期纪律**：扩展 API 是框架级契约，变更须同步本文与 ADR；但孵化期不承诺跨项目向后兼容，抽离时再冻结版本。

## 二、分层架构

```
┌─────────────────────────────────────────────────┐
│ 宿主应用（Campfire：api-server / worker）          │
│  编排层（代码持有控制流）+ 领域扩展                 │
├─────────────────────────────────────────────────┤
│ py-agent-kernel（本框架，唯一内核包）              │
│  ExtensionAPI · 事件总线 · 工具契约               │
│  Session（JSONL 树）· skill-loader                │
├─────────────────────────────────────────────────┤
│ pydantic-ai（外部依赖）                           │
│  Agent 循环 · 消息模型 · 流式 · provider 矩阵     │
│  Hooks/Toolsets/Capabilities（内核的挂载接缝）     │
└─────────────────────────────────────────────────┘
```

依赖方向严格向下：宿主扩展 → 内核 → pydantic-ai。禁令：

- 内核不得 import 任何宿主/领域包；
- 扩展不得反向依赖宿主应用（扩展间复用须下沉内核或抽公共扩展）；
- 扩展不得直接调用 pydantic-ai 的 Agent 循环 API 绕过事件总线（结构化能力经内核暴露）。

## 三、扩展契约（ExtensionAPI）

pi 的扩展体系有两个正交的轴，本框架原样继承：

- **能力轴（细粒度）**：工具、命令、事件 handler、Skill——各自独立注册/发现、独立寻址；
- **组织轴（粗粒度）**：扩展——对应 pi 的 extension 语义（单文件或目录 + 默认导出工厂函数）。pi 的 package 层（npm/git 分发机械、单容器多扩展归拢、trust）整体裁剪，其 `skills/` 目录自动发现行为由扩展吸收（见 §十偏差清单）。

扩展是宿主领域能力的组织单位，物理形态为目录（能力多时）或单文件（能力少时，沿袭 pi directory / single-file extension 约定）：

```
<extension>/
├── __init__.py 或 extension.py   # 入口：默认导出工厂函数
└── skills/                        # 常规目录，内核自动发现其中的 SKILL.md 包（可选）
```

入口为工厂函数，接收 `ExtensionAPI`（命名与形态仿 pi）：

```python
def extension(pi: ExtensionAPI) -> None:
    pi.on("tool_call", on_tool_call)          # 订阅事件
    pi.register_tool(rag_search_tool)          # 注册工具
    pi.register_command("case-stats", handler) # 注册命令（宿主侧调用）
```

- **Skill 不走 API 注册**：内核加载扩展时自动发现其常规 `skills/` 目录（吸收 pi package 无 manifest 时的行为，见 §十偏差清单），保持 Skill 与代码解耦、可被 pi/Claude Code 等 harness 原样复用；扩展也可经 `resources_discover` 事件动态贡献额外 skill 路径（pi extension 原生能力）；
- **生命周期**：加载（导入并执行工厂）→ 会话绑定（`session_start`）→ 卸载（`session_shutdown`）。第一方扩展，不支持热加载与第三方市场；
- **加载顺序即优先级**：事件 handler 按扩展加载顺序执行，链式修改语义见 §四；宿主显式声明加载清单，顺序可控可断言；
- **资源清理**：会话级资源必须在 `session_shutdown` 释放（沿袭 pi 约定）；
- **声明式元数据**：扩展目录含 `extension.yaml`（名称、版本、依赖的内核版本），内核启动时校验兼容性（自造契约，非 pi 原生——pi 扩展无 manifest，package 用 `package.json` + `pi` 键，均无版本校验；纳入 §十偏差清单）。

## 四、事件总线

事件名与语义仿 pi，内核负责将 Pydantic AI 的运行时接缝翻译成统一事件面：

| 事件 | 时机 | 可干预性 | Pydantic AI 挂载点 |
|---|---|---|---|
| `session_start` / `session_shutdown` | 会话建立/卸载 | 通知 | 内核 Session 层 |
| `input` | 收到用户输入，进入循环前 | 可 transform / handled | 内核入口 |
| `before_agent_start` | 每次 agent 运行前 | 可注入消息、改系统提示 | `Hooks.on.before_run` + 动态 instructions |
| `agent_start` / `agent_end` | 单次运行起止 | 通知 | `before_run` / `after_run` |
| `turn_start` / `turn_end` | 每轮 LLM 调用+工具执行 | 通知 | `before_node_run` / `after_node_run`（接缝层聚合节点对为一 turn，见 §十） |
| `message_start` / `message_update` / `message_end` | 消息生命周期（流式增量经 `message_update`） | `message_end` 可替换消息 | `AgentStreamEvent` 事件族（part 级事件组装为消息边界，见 §十） |
| `context` | 每次 LLM 调用前 | 可修改消息列表（非破坏） | `ProcessHistory` capability |
| `tool_call` | 工具执行前 | **可阻断**（返回 block+reason） | `before_tool_execute`（内联 block）/ `DeferredToolRequests`（HITL 审批） |
| `tool_result` | 工具执行后 | **可修改**（链式补丁） | `after_tool_execute` |
| `tool_execution_start` / `tool_execution_update` / `tool_execution_end` | 工具执行生命周期（并行时 start 按源序、end 按完成序） | 通知 | `AgentStreamEvent` 工具事件族 |

规则（沿袭 pi 语义）：

- handler 按扩展加载顺序依次执行；可干预事件的修改在 handler 间链式传递，后者看到前者的结果；
- `tool_call` 任一 handler 返回 block 即阻断，reason 回传给模型作为工具错误；**内联阻断（run 内继续）由 `before_tool_execute` hook 抛 `ModelRetry` 或 wrapper toolset 短路承载**；`DeferredToolRequests` 是 run 边界语义（挂起 run、外部决策、带结果重跑），仅用于人工审批流，两者不得混用（见 §十）；
- handler 抛异常：通知类事件记录后继续（pi 原生默认）；可阻断类事件一律视为 block（fail-closed——pi 对 `tool_call` 的原生语义推广为事件总线通用策略，见 §八）。

未纳入的 pi 事件（显式裁剪，需要时按本表同规则补入）：`agent_settled`、`model_select`、`thinking_level_select`、`session_before_switch` / `session_before_fork` / `session_before_tree` 族、`user_bash`、provider 三钩子（`before_provider_headers` / `before_provider_request` / `after_provider_response`）、`project_trust`——多为 TUI/交互模式与 trust 机制裁剪的自然结果。

## 五、工具契约

工具接口仿 pi 的 `AgentTool`：

```python
class AgentTool(BaseModel):
    name: str                      # 蛇形命名
    label: str                     # 展示名
    description: str
    parameters: type[BaseModel]    # Pydantic 模型，生成 JSON Schema（TypeBox 的等价物）
    execution_mode: Literal["parallel", "sequential"] | None = None

    async def execute(
        self,
        tool_call_id: str,
        params: BaseModel,
        signal: CancellationToken,
        on_update: Callable[[ToolResult], None] | None,
        ctx: ToolContext,
    ) -> ToolResult: ...
```

- `ToolResult = { content: list[ContentBlock], details: dict }`；content 支持 text/image 块（与 pi 同构）；
- `ctx` 对应 pi `execute` 的第 5 参（`ExtensionContext` 子集）：内核暴露会话只读访问与工作目录，供审计、状态类工具使用；
- `execution_mode` 由 Pydantic AI 的 per-tool `sequential=True` 屏障承载（run 级 `parallel_execution_mode('sequential')` 可全局串行化）；
- **错误语义**：工具失败抛异常，内核捕获后以 `isError: true` 回传模型；不允许把错误信息伪装成正常 content 返回（pi 约定）；
- **工具自带校验**：工具实现内必须自行做权限与参数业务校验，不信任调用上下文（安全原则，与 [Agent基座](./Agent基座.md) §三一致）；
- **按面白名单**：宿主为不同执行面配置可用工具子集（`FilteredToolset` 机制，内核暴露 `set_active_tools` 等价 API）；**白名单按工具名寻址**（pi 语义——跨扩展来源一视同仁，工具归属哪个扩展仅是所有权维度，不影响寻址）。

## 六、Session 与上下文

- **存储格式**：JSONL 树，每条 entry 含 `id`/`parentId`，entry 类型族与上下文构建规则**结构同构 pi**（branch/fork/clone、compaction 只影响上下文窗口、完整历史始终保留）；**不追求与 pi 会话文件字节兼容**——消息负载以 Pydantic AI schema 落盘，与 pi 生态工具互换须另做导出器，不进内核（2026-08-04 决策，见 §十偏差清单）；
- **消息序列化**：经 Pydantic AI 的 `ModelMessagesTypeAdapter` 落盘；自定义消息类型（通知、审计标记等）以自定义 part 扩展，序列化规则归内核；
- **steering / follow-up**：队列语义仿 pi——`asap`（当前 turn 工具执行完后注入，对应 steering）、`when_idle`（agent 将终止时注入，对应 follow-up）；直接映射 Pydantic AI 的 `PendingMessage` 优先级；
- **compaction**：触发策略（手动/阈值/溢出恢复）与钩子（`session_before_compact` 可取消或提供自定义摘要）仿 pi；provider 侧压缩能力（`CompactionPart`）可用时优先，否则内核调用模型生成摘要；完整历史始终保留在 JSONL 中，压缩只影响上下文窗口。

## 七、Skill 目录

- 遵循 [Agent Skills 标准](https://agentskills.io/specification)：每个 Skill 是一个目录，含 `SKILL.md`（frontmatter + 工作流指令），可附 `scripts/`、`references/`；
- **skill-loader 流程**（内核自研薄层）：扫描发现 → frontmatter 解析 → name+description 注入系统提示 → 模型选定后按需加载完整指令 → `allowed-tools` 过滤；
- **渐进披露**：description 常驻、正文按需、引用文件再按需，三层披露与 pi 一致；
- **metadata 透传**：frontmatter `metadata` 键原样透传给宿主，内核不解释其内容（Campfire 的 `output-schema`/`surface`/`eval-set` 约定即挂在此处，归 [Agent基座](./Agent基座.md) 拥有）；
- 扩展经 `skills/` 目录贡献 Skill，内核统一汇总成目录。

## 八、安全即扩展

内核**没有任何安全专属机制**——沿袭 pi「一切皆可扩展，权限门用扩展实现」的哲学，安全能力以普通第一方扩展（如 Campfire 的 `security` 扩展）经事件总线挂载：

| 挂载事件 | 典型用途（宿主安全扩展实现） |
|---|---|
| `input` | 红线关键词门（对每条用户输入生效） |
| `before_agent_start` | 上下文注入白名单校验、免责声明注入 |
| `tool_call` | 权限校验、危险操作阻断 |
| `tool_result` | PII 检测与脱敏 |
| `message_end` | 输出合规检查（契约校验失败阻断） |

安全保证不依赖内核特殊设计，全部锚定在**受控加载**上：

1. **全部扩展第一方**：无第三方市场、无热加载、无动态发现，加载清单由宿主启动代码显式声明——恶意/越权扩展没有进入路径；
2. **加载顺序即执行顺序**（pi 原生语义）：宿主将安全扩展排在加载清单首位，其 handler 即在链式执行中最先运行；
3. **启动断言**：宿主启动时断言安全扩展已加载且位于首位（一段自检代码 + 一条测试），缺失即拒绝启动；
4. **fail-closed 是事件总线的通用策略**：可阻断事件（`tool_call` 等）的任一 handler 抛异常一律视为 block——对所有扩展一视同仁，非安全特例。

规则本身（红线词表、PII 策略、RBAC）归宿主应用拥有；「安全规则在 Agent 之外的代码层」由扩展即代码层天然满足——LLM 看不见、控制不了任何事件 handler。

## 九、可观测与评测

- **工具调用审计**：每次工具调用（含阻断记录）落审计日志，trace_id 贯通宿主日志体系；
- **Token/成本追踪**：按扩展/Skill/执行面维度聚合，对接宿主成本告警；
- **输出校验**：结构化输出经 Pydantic 契约校验，不合格输出阻断并记录（`before_output_validate` 挂钩）；
- **eval-set 回归**：Skill 的评测集由宿主维护（metadata `eval-set` 指向），内核提供批量运行入口，Prompt/模型变更后全量回归作为质量门。

## 十、保真度审计与偏差清单

审计方法：对照 pi 三层（pi-ai / pi-agent-core / pi-coding-agent）文档与 Pydantic AI 2.22.0 源码逐项核对（2026-08-04 执行）。

**可忠实承载的 pi 语义**：`tool_call` 内联阻断（`before_tool_execute` hook 抛 `ModelRetry` / wrapper toolset 短路；Pydantic AI 另提供 `DeferredToolRequests` HITL 原语，能力上超 pi，但与内联 block 分工不同，见下表）、`tool_result` 链式修改、`context` 消息改写、steering/follow-up（`PendingMessage` `asap`/`when_idle` 与 pi 语义一一对应）、全生命周期事件（Hooks 的 run/node_run/model_request/tool_validate/tool_execute/output_validate 族 + `AgentStreamEvent` 流事件族）、工具白名单（`FilteredToolset`）、结构化输出校验（`output_type` 原生，优于 pi 的工具调用约束方案）。

**偏差项**（显式记录，不悄悄走样）：

| pi 语义 | 偏差 | 处置 |
|---|---|---|
| 并行工具"顺序 preflight、并发执行、按完成序发 `tool_execution_end`、toolResult 按助手源序持久化" | Pydantic AI 默认并行执行同批工具（per-tool `sequential=True` 屏障 / run 级 `parallel_execution_mode('sequential')` 控制串行化），事件序与持久化序语义与 pi 不同 | 初版按 Pydantic AI 原生语义实现并记录事件序差异；仅当宿主场景依赖该顺序时（`missing evidence`：目前无）才在事件总线层重排 |
| 工具返回 `terminate: true` 跳过后续 LLM 调用 | Pydantic AI 以 `end_strategy` 表达，粒度为 agent 级而非工具结果级 | 以 `end_strategy` + 输出工具模式近似；语义差异记入扩展开发指引 |
| pi 会话格式字节兼容（会话文件与 pi 生态工具互换） | 消息负载经 `ModelMessagesTypeAdapter` 落盘，schema 与 pi（role+content blocks 族）不同构；entry 语义对齐但字节不兼容 | 放弃字节兼容目标，仅保结构同构（树形 JSONL、entry 类型族、compaction 语义）；需要互换时另做导出器，不进内核（2026-08-04 决策） |
| `turn_start`/`turn_end` 每 turn 一次（一 turn = 一次 LLM 响应 + 工具调用）；`message_*` 为整消息生命周期事件 | pydantic-graph 节点为 `ModelRequestNode`/`CallToolsNode` 级，一 turn 跨两个节点；`AgentStreamEvent` 为 part 级（PartStart/Delta/End） | 接缝层负责聚合（节点对→turn、part 流→消息边界）；聚合规则属内核契约，随实现固化并补测试 |
| `tool_call` block 为 run 内联语义（工具不执行、reason 回传模型、循环继续） | `DeferredToolRequests` 为 run 边界语义（挂起 run、外部决策、带 `DeferredToolResults` 重跑），不能直接承载内联 block | 内联 block 由 `before_tool_execute` hook 抛 `ModelRetry` 或 wrapper toolset 短路承载；`DeferredToolRequests` 仅用于人工审批流；两者在扩展开发指引中分开说明 |
| 扩展无声明式元数据与版本兼容校验（pi 扩展无 manifest；package 用 `package.json` + `pi` 键，均无内核版本校验） | 本框架自造 `extension.yaml`（名称、版本、内核版本兼容校验） | 有意新增：npm 包管理裁剪后需要替代物；记入偏差，抽离冻结 API 时重审 |
| `skills/` 目录自动发现是 pi package 层行为（裸 extension 不携带 skill 发现） | package 层整体裁剪，该行为由扩展吸收 | 记入偏差；发现规则与 pi package 无 manifest 时的自动发现保持一致 |

**裁剪清单**（pi 有而本框架不做）：TUI/`ctx.ui`、themes、keybindings、npm 包管理与热加载、项目 trust 机制、RPC 模式（SDK 嵌入优先，需要时再补）。

## 十一、非目标

- 不做第三方扩展生态（动态发现、热加载、市场）——扩展全部第一方；
- 不内置 MCP、sub-agent、plan mode、后台任务（沿袭 pi 哲学，需要时以扩展实现）；
- 不重复实现 LLM 统一层、provider 接入、流式协议（pydantic-ai 已有）；
- 不承诺孵化期的跨项目 API 稳定性（抽离时再冻结）；
- 不拥有任何宿主业务规则（安全规则、领域契约、面编排策略归宿主文档）。
