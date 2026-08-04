# py-agent-kernel — 通用 Agent 内核框架

> 内核+扩展架构（[ADR-011](../../../docs/技术设计/决策/ADR-011-Agent内核框架-内核加扩展与PydanticAI路线.md)）：
> harness 层契约仿 [pi](https://pi.dev)，LLM 层委托 pydantic-ai 2.23（版本锁定）。
> 框架契约唯一事实源：[Agent内核框架](../../../docs/技术设计/Agent内核框架.md)。
> **零 Campfire 依赖**——内核不得 import 任何宿主/领域包（tests/test_zero_deps.py CI 断言）。

## 组件地图

| 模块 | 职责 |
|---|---|
| `extension_api.py` | ExtensionAPI（on/register_tool/register_command/contribute_skill_path）、扩展加载器、extension.yaml 兼容性校验 |
| `events/` | 事件总线（pi 语义事件族、链式干预、fail-closed） |
| `tools/` | AgentTool 契约（五参 execute）、ToolResult、KernelToolset 桥接、面白名单 |
| `session/` | Session JSONL 树（branch/fork/clone）、ModelMessagesTypeAdapter 落盘、steering/follow-up 队列 |
| `skills/` | skill-loader（扫描/frontmatter/渐进披露/allowed-tools/metadata 透传） |
| `runtime/` | AgentSession（pydantic-ai 接缝：Hooks 翻译、turn 聚合、消息边界、流式装配）、审计、eval |

## 扩展开发指引

### 扩展形态

```
my-extension/
├── extension.yaml      # 自造契约（偏差清单项）：name/version/kernel 兼容区间
├── extension.py        # 入口：def extension(pi: ExtensionAPI) -> None
└── skills/             # 常规目录，内核自动发现其中 SKILL.md 包（可选）
    └── my-skill/
        ├── SKILL.md    # frontmatter(name/description/metadata/allowed-tools) + 正文
        └── references/ # 再按需加载的引用文件
```

### extension.yaml

```yaml
name: my-extension
version: "0.1.0"
kernel: ">=0.1.0,<0.2.0"   # PEP 440 兼容区间；不兼容拒绝加载
```

### 工厂函数

```python
def extension(pi: ExtensionAPI) -> None:
    pi.on("tool_call", on_tool_call)        # 订阅事件（加载顺序即执行顺序）
    pi.register_tool(my_tool)               # 注册工具（工具名全局唯一）
    pi.register_command("my-cmd", handler)  # 注册命令（宿主侧调用）
    pi.contribute_skill_path(extra_dir)     # 动态贡献 Skill 路径（resources_discover）
```

### 内联阻断 vs HITL（不得混用，§十）

| 场景 | 机制 |
|---|---|
| **内联阻断**（run 内继续：工具不执行、reason 回传模型、循环继续） | `tool_call` handler 返回 `EventResult(block=True, reason=...)`；内核经 `before_tool_execute` 抛 `ModelRetry` 承载 |
| **HITL 人工审批**（run 边界：挂起 run、外部决策、带结果重跑） | pydantic-ai `DeferredToolRequests`——仅人工审批流，宿主显式装配，不经事件总线 |

### 工具实现纪律

- 工具自带校验：实现内必须自行做权限与参数业务校验，不信任调用上下文；
- 失败抛异常：内核捕获后以错误回传模型，禁止把错误伪装成正常 content；
- 白名单按工具名寻址：宿主 `active_tools=[...]` 按面配置，与工具归属扩展无关。

## 接缝映射表（pydantic-ai 2.23，偏差清单落地）

| 内核事件 | pydantic-ai 挂载点 | 说明 |
|---|---|---|
| `turn_start` / `turn_end` | `before_node_run(ModelRequestNode)` / `after_node_run(CallToolsNode)` | 节点对聚合为一 turn |
| `message_start/update/end` | `AgentStreamEvent`（PartStart/PartDelta/PartEnd） | part 流聚合为消息边界 |
| `tool_call`（阻断） | `before_tool_execute` 抛 `ModelRetry` | 内联阻断 |
| `tool_result`（链式修改） | `after_tool_execute` 返回值 | 修改回传模型 |
| `context`（消息改写） | `before_model_request` 的 `ModelRequestContext` | 每次 LLM 调用前 |
| `tool_execution_start/end` | `FunctionToolCallEvent` / `FunctionToolResultEvent` | 并行时按 pydantic-ai 原生事件序（不重排，偏差清单项） |
| `agent_start` / `agent_end` | run 入口/出口（内核编排层） | — |
| `session_start` / `session_shutdown` | 内核 Session 层 | 扩展在此绑定/释放会话级资源 |

**显式偏差**（§十）：并行工具事件序按 pydantic-ai 原生语义；`terminate` 以 `end_strategy` 近似；会话字节不兼容 pi（仅结构同构）；`extension.yaml` 为自造契约；`skills/` 自动发现由扩展吸收。

## 升级检查清单（pydantic-ai 版本变更时）

1. `capabilities.Hooks` 构造参数面是否变更（before/after/wrap/error 族）；
2. `AgentStreamEvent` 事件族是否有新成员需映射（translate_stream_event）；
3. `ModelMessagesTypeAdapter` 序列化格式是否变更（会话 round-trip 测试）；
4. `FilteredToolset` / `FunctionToolset` 接口是否变更（白名单与桥接）；
5. 跑 `pytest packages/py-agent-kernel/tests` 全量回归；
6. 更新本文档版本锁定说明与 [Agent内核框架](../../../docs/技术设计/Agent内核框架.md) §十（如有新偏差）。
