# 阶段 2 · Agent 内核（py-agent-kernel）

> **目标态依据**：[ADR-011](./决策/ADR-011-Agent内核框架-内核加扩展与PydanticAI路线.md)（路线与裁剪）、[Agent内核框架](../Agent内核框架.md)（本文唯一拥有内核契约——ExtensionAPI/事件总线/工具契约/Session/skill-loader/安全扩展约定/偏差清单）
> **状态**：【未开始】。`packages/py-agent-kernel/` 为全新包，**不触碰任何现有代码**。

## 一、目标态

1. **通用内核包** `packages/py-agent-kernel`（零 Campfire 依赖，仅依赖 pydantic-ai 2.x 及通用库），孵化期纪律：API 变更须同步[Agent内核框架](../Agent内核框架.md)与 ADR；
2. **组件**（目录骨架见[项目结构/目录骨架](../项目结构/目录骨架.md) §一）：
   - `extension_api.py`：`ExtensionAPI`（on/register_tool/register_command/resources_discover），扩展生命周期（加载→session_start→session_shutdown），`extension.yaml` 兼容性校验（偏差项）；
   - `events/`：事件总线（事件表：session_start/shutdown、input、before_agent_start、agent_start/end、turn_start/end、message_start/update/end、context、tool_call、tool_result、tool_execution_start/update/end）；链式干预（可干预事件按扩展加载顺序传递）；fail-closed（可阻断事件 handler 抛异常一律视为 block）；
   - `tools/`：`AgentTool` 契约（name/label/description/parameters/execution_mode/execute 五参签名）、`ToolResult`（content blocks + details）、`FilteredToolset`（面白名单，按工具名寻址）；
   - `session/`：Session JSONL 树（entry id/parentId、branch/fork/clone、compaction 只影响上下文窗口、完整历史保留）；消息经 `ModelMessagesTypeAdapter` 落盘；steering/follow-up（PendingMessage asap/when_idle 映射）；
   - `skills/`：skill-loader（扫描发现 → frontmatter 解析 → name+description 注入系统提示 → 按需加载正文 → allowed-tools 过滤；metadata 原样透传）；
   - `runtime/`：pydantic-ai 接缝（Hooks 翻译：before_run/after_run/node_run/tool_execute/output_validate → 统一事件面；节点对→turn 聚合、part 流→消息边界聚合；AgentStreamEvent 装配；内联阻断 = before_tool_execute 抛 ModelRetry / wrapper toolset 短路；HITL = DeferredToolRequests 仅用于人工审批流）；
3. **安全即扩展**：内核无安全专属机制，安全保证锚定受控加载（全第一方、显式清单、启动断言、fail-closed）；
4. **显式偏差落地**：按[Agent内核框架](../Agent内核框架.md) §十偏差清单实现——并行工具事件序按 Pydantic AI 原生语义、`terminate` 以 `end_strategy` 近似、会话字节不兼容仅结构同构、extension.yaml 自造契约、skills/ 自动发现由扩展吸收；
5. **独立测试与文档**：`tests/` 覆盖全部组件；`docs/` 为框架自有文档（随包维护）。

## 二、任务清单（按序执行）

### T2.1 包脚手架

- [ ] `packages/py-agent-kernel/pyproject.toml`（flat-layout、pydantic-ai 版本锁定、dev 组 pytest/ruff/mypy）
- [ ] 加入根 `pyproject.toml` workspace members 与 sources
- [ ] 包骨架目录 + `__init__.py` + 类型导出面
- [ ] 根级验证：`uv run ruff check packages/py-agent-kernel` 通过

### T2.2 ExtensionAPI 与生命周期

- [ ] `ExtensionAPI`：事件订阅（on）、工具注册（register_tool）、命令注册（register_command）、resources_discover
- [ ] 扩展加载器：目录/单文件形态、默认导出工厂函数约定、加载顺序即优先级、`extension.yaml` 名称/版本/内核兼容校验（不符合拒绝加载）
- [ ] 会话生命周期：session_start/session_shutdown 通知与资源清理契约
- [ ] 测试：加载顺序、yaml 校验失败拒绝、shutdown 清理调用

### T2.3 事件总线

- [ ] 事件表实现（§一.2 events 全事件族）+ 事件上下文数据结构
- [ ] 链式干预语义：可干预事件（input/context/tool_call/tool_result/message_end）handler 链式传递；tool_call 任一 block 即阻断（reason 回传）
- [ ] fail-closed：可阻断事件 handler 抛异常 → block；通知事件抛异常 → 记录后继续
- [ ] 测试：链式修改顺序、双 handler 阻断、异常语义

### T2.4 工具契约与白名单

- [ ] `AgentTool`（含 execute 五参签名：tool_call_id/params/signal/on_update/ctx）+ `ToolResult`（content: text/image 块、details）
- [ ] 错误语义：工具抛异常 → 内核捕获 → isError 回传模型，禁止伪装正常 content
- [ ] `FilteredToolset` / `set_active_tools`：按工具名寻址的白名单
- [ ] 测试：工具注册/执行/异常语义/白名单过滤

### T2.5 Session 与上下文

- [ ] JSONL 树：entry（id/parentId）、branch/fork/clone、持久化路径管理
- [ ] 消息序列化：`ModelMessagesTypeAdapter` 落盘；自定义 part 扩展机制
- [ ] steering/follow-up：PendingMessage asap/when_idle 映射
- [ ] compaction：触发策略（手动/阈值）+ `session_before_compact` 钩子 + 摘要生成（provider 压缩优先，否则模型摘要）；完整历史保留
- [ ] 测试：树结构、序列化往返、steering 注入时机、compaction 不丢历史

### T2.6 skill-loader

- [ ] 扫描发现（扩展 skills/ 目录 + resources_discover 动态贡献）
- [ ] frontmatter 解析（name/description/metadata 原样透传/allowed-tools）
- [ ] 渐进披露：description 常驻 → 正文按需 → references 再按需
- [ ] 测试：发现、披露层级、allowed-tools 过滤、metadata 透传

### T2.7 runtime 接缝（最大工作量）

- [ ] Hooks 翻译层：before_run/after_run/node_run/model_request/tool_validate/tool_execute/output_validate → 统一事件面
- [ ] turn 聚合：ModelRequestNode+CallToolsNode 节点对 → turn_start/turn_end
- [ ] 消息边界聚合：PartStart/Delta/End 流 → message_start/message_update/message_end；工具事件族（tool_execution_start/update/end）
- [ ] 内联阻断承载：before_tool_execute 抛 ModelRetry / wrapper toolset 短路；HITL 用 DeferredToolRequests 分离实现（不混用）
- [ ] 流式装配：AgentStreamEvent → 内核流式输出（供宿主 SSE 使用，S3 消费）
- [ ] 输出校验挂钩：output_type 结构化契约校验 + before_output_validate 阻断
- [ ] 测试：节点对→turn、part 流→消息边界、内联阻断回传、流式事件序（对齐偏差清单记录）

### T2.8 可观测与文档

- [ ] 工具调用审计钩子（每次调用含阻断记录，trace_id 透传宿主）
- [ ] Token/成本聚合接口（按扩展/Skill/面维度）
- [ ] eval 批量运行入口（宿主 eval-set 回归用，S5 消费）
- [ ] `docs/`：内核自有文档（契约说明、接缝映射表、偏差清单落地说明、扩展开发指引——含内联阻断 vs HITL 用法区分）
- [ ] 内核零依赖断言测试：`grep` 检查无 Campfire 包 import（CI 化）

## 三、接口契约（内核 API 面，S3/S5 消费方）

- 宿主装配：`create_agent_session(extensions=[...], tools=..., skills_dir=...)` → session；`session.run()` / 流式
- 扩展侧：`def extension(pi: ExtensionAPI) -> None`；`pi.on(event, handler)` / `pi.register_tool(AgentTool)` / `pi.register_command(name, fn)`
- 事件 handler 签名与可干预性按[Agent内核框架](../Agent内核框架.md) §四事件表
- 白名单：`set_active_tools(["rag_search", ...])`（面级，S3/S5 注入）

## 四、成功标准

```bash
uv run ruff check packages/py-agent-kernel
uv run pytest packages/py-agent-kernel/tests
grep -rn "campfire\|py_schemas\|py_db\|py_rag" packages/py-agent-kernel/py_agent_kernel --include="*.py"   # 无结果（零领域知识断言）
```

- [ ] 全部组件测试绿（事件总线/工具/会话/skill-loader/接缝）
- [ ] 接缝层 turn 聚合、消息边界、内联阻断、流式事件序有专项测试覆盖（对应偏差清单）
- [ ] 内核 docs 齐备（扩展开发指引可指导 S5 扩展开发）

## 五、风险与注意

- **pydantic-ai 版本锁定**：接缝层强依赖上游 Hooks/Capabilities API，锁定精确版本并在 `docs/` 记录升级检查清单；
- 偏差清单项必须按[Agent内核框架](../Agent内核框架.md) §十「处置」列实现并测试，**禁止悄悄走样**；
- 本阶段不实现任何 Campfire 业务；业务扩展在 S5 落地；
- 若实现中发现「pi 语义 ↔ Pydantic AI 接缝」存在文档未覆盖的偏差，**停止并确认**（可能触发 ADR-011 重访条件评估）。
