---
name: "项目设计流水线"
description: "从技术栈设计到项目结构设计、模块拆解、依赖分析、多模块并行调度、同步矛盾聚合的项目级设计工作流 v3.1.0"
tags: [project-design, tech-stack, project-structure, module-breakdown, dependency-analysis, multi-module-orchestration]
---

# project-design-pipeline@3.1.0

> 技术栈设计 -> 项目结构设计 -> 模块拆解 -> 依赖分析 -> 多模块并行调度 -> 项目级同步矛盾聚合

---

## 工作流概览

- **工作流 ID**：`project-design-pipeline`
- **版本**：`3.1.0`
- **Stage 数量**：11（含 2 个虚拟 stage）
- **确认点数量**：7（由 edges 中 `success` + `choice` 模式隐式定义）
- **最大并发**：10（父工作流阶段串行推进；子工作流并行调度由 wfctl 按 `parallel` + `workflow` 声明机械执行）

### 适用场景

1. 新项目从零开始的技术栈选型、结构设计与模块拆解
2. 已有项目的模块设计补充或增量更新
3. 需要对多个模块并行执行完整设计流水线（意图编写 -> 规格编写 -> 契约协调）
4. 项目级跨模块同步矛盾检测与汇总

### v3.1.0 规范同步更新（2026-05-25）

| 维度 | 变更前 | 变更后 |
|------|--------|--------|
| edges `condition` 值 | 使用已废弃的 `confirmed` / `rejected` | 统一使用 `success` + `choice`（与最新的 WORKFLOW.yaml 字段规范对齐） |
| stage `confirmation_point` 字段 | 每个 stage 显式声明 | 移除（确认现在是 Skill 内部 AskUserQuestion 行为，工作流定义不再声明） |
| s07→s08 edge | `condition: success` | `condition: always`（确认+继续模式，SubAgent 完成并行目标后无条件流转） |
| s08 `retry` | 未设置（默认 0） | `retry: 1`（确保子工作流失败后可触发 `failure` edge 回跳 s07） |

---

## 流程图

```mermaid
flowchart TD
    s00["s00-workflow-start<br/>工作流启动"]
    s99["s99-workflow-end<br/>工作流终止"]

    s01["s01-collect-requirements<br/>收集需求与上下文"]
    s02["s02-architecture-selection<br/>架构关节点选型"]
    s03["s03-tech-stack-output<br/>技术栈方案输出"]
    s04["s04-project-structure-design<br/>项目结构设计"]
    s05["s05-module-breakdown<br/>功能模块拆解"]
    s06["s06-dependency-analysis<br/>模块依赖分析"]
    s07["s07-project-sync-and-dispatch<br/>项目同步与模块调度"]
    s08["s08-dispatch-modules<br/>模块设计子工作流调度"]
    s09["s09-project-sync-check<br/>项目级同步矛盾检查"]

    s00 --> s01

    s01 -->|"success 通过"| s02
    s01 -->|"success 继续完善"| s01
    s01 -->|"success 放弃"| s99
    s01 -->|"loop_exceeded"| s99

    s02 -->|"success 通过"| s03
    s02 -->|"success 继续完善"| s02
    s02 -->|"success 放弃"| s99
    s02 -->|"loop_exceeded"| s99

    s03 -->|"success 通过"| s04
    s03 -->|"success 继续完善"| s03
    s03 -->|"success 放弃"| s99
    s03 -->|"loop_exceeded"| s99

    s04 -->|"success 通过"| s05
    s04 -->|"success 调整结构"| s04
    s04 -->|"success 放弃"| s99
    s04 -->|"loop_exceeded"| s99

    s05 -->|"success 通过"| s06
    s05 -->|"success 继续完善"| s05
    s05 -->|"success 放弃"| s99
    s05 -->|"loop_exceeded"| s99

    s06 --> s07
    s06 -.->|"failure（降级跳过）"| s07

    s07 -->|"always"| s08
    s07 -->|"success 确认调度"| s07
    s07 -->|"success 重新选择"| s07
    s07 -->|"success 终止工作流"| s99
    s07 -->|"loop_exceeded"| s99

    s08 -->|"success"| s09
    s08 -->|"failure"| s07

    s09 -->|"success 修改技术栈"| s02
    s09 -->|"success 调整项目结构"| s04
    s09 -->|"success 调整模块边界"| s05
    s09 -->|"success 继续处理其他模块"| s07
    s09 -->|"success 接受差异"| s99
    s09 -->|"success 终止工作流"| s99
    s09 -->|"success 放弃"| s99
```

---

## Stage 说明

### s00-workflow-start -- 工作流启动

虚拟起始点，无条件流转到下游。

---

### s01-collect-requirements -- 收集需求与上下文

- **Skill**：`design-tech-stack`
- **确认行为**：通过 edges `success` + `choice` 模式实现多轮交互确认
- **描述**：收集技术背景、部署环境、规模、运维等约束。通过多轮问答明确项目需求全景，为后续架构选型提供输入材料。
- **输出**：需求收集记录（注入到下一 stage 上下文）

---

### s02-architecture-selection -- 架构关节点选型

- **Skill**：`design-tech-stack`
- **确认行为**：通过 edges `success` + `choice` 模式实现多轮交互确认
- **描述**：在 8 个关键技术关节点（前端框架、后端语言、数据库、部署方式、认证方案、实时通信、AI 集成、架构模式）逐一提问确认选型，汇总后上报确认。
- **输出**：架构选型汇总

---

### s03-tech-stack-output -- 技术栈方案输出

- **Skill**：`design-tech-stack`
- **确认行为**：通过 edges `success` + `choice` 模式实现多轮交互确认
- **重试**：1 次
- **描述**：呈现完整技术栈概览，用户终审确认后输出 `docs/项目名称-技术栈设计.md`，作为后续所有设计阶段的全局参考。
- **输出**：`docs/项目名称-技术栈设计.md`

---

### s04-project-structure-design -- 项目结构设计

- **Skill**：`project-structure-designer`
- **确认行为**：通过 edges `success` + `choice` 模式实现多轮交互确认
- **重试**：1 次
- **描述**：基于已确认的技术栈方案，设计项目整体结构骨架——分层架构（表示层/应用层/领域层/基础设施层/公共层）、顶层目录骨架（含各目录职责与依赖方向）、层间数据流（2-3 个代表性业务场景）、包/模块组织约定。用户终审确认后输出 `docs/项目名称-项目结构.md`，作为后续模块拆解和依赖分析的架构蓝图。
- **输出**：`docs/项目名称-项目结构.md`

---

### s05-module-breakdown -- 功能模块拆解

- **Skill**：`module-breakdown-designer`
- **确认行为**：通过 edges `success` + `choice` 模式实现多轮交互确认
- **重试**：1 次
- **描述**：基于技术栈方案和项目结构文档，执行模块提取、边界检查、功能分组。输出模块全拆解表，新增 `design_status` 列标记各模块设计进度。
- **输出**：`docs/功能设计/功能模块全拆解.md`

---

### s06-dependency-analysis -- 模块依赖分析

- **Skill**：`module-dependency-analyzer`
- **确认行为**：无确认点（SubAgent 自行完成分析后上报 DONE）
- **重试**：1 次
- **描述**：读取模块全拆解表和项目结构设计文档，逐对扫描推断模块间依赖（数据依赖、调用依赖、时序依赖、共享资源依赖），从项目结构文档中提取架构层面的分层依赖约束，输出多维依赖视图。若执行失败（含重试耗尽），沿 `failure` edge 降级跳过，不阻塞后续模块调度（s07 的 project-dispatch-manager 可在无依赖分析文档时继续运行）。
- **输出**：`docs/功能设计/模块依赖关系分析.md`

---

### s07-project-sync-and-dispatch -- 项目同步与模块调度

- **Skill**：`project-dispatch-manager`
- **确认行为**：通过 edges `success` + `choice` 模式实现多轮交互确认。SubAgent 先呈现选项让用户选择模块（中继确认自循环），用户确认后 SubAgent 继续执行产出 `parallel_targets`，最后上报 DONE → s08
- **描述**：汇报项目级设计状态和所有模块的设计进度。用户选择目标模块（可多选），确认后将模块清单作为 `parallel_targets` 上报，由 wfctl 在 s08 按 `parallel` 声明为每个模块启动独立子工作流。支持以下决策：
  - **确认调度**：将选定模块的 `parallel_targets` 产出，SubAgent 继续执行后 DONE → s08
  - **重新选择**：调整模块选择（最多 3 轮）
  - **终止工作流**：所有模块已完成设计，结束工作流
- **输出**：`parallel_targets`（选定模块清单 + 各模块增量场景参数）

---

### s08-dispatch-modules -- 模块设计子工作流调度

- **类型**：子工作流（`workflow: module-design-pipeline@1.1.0`）+ 并行扇出（`parallel: {source: s07}`）
- **确认行为**：无确认点
- **重试**：1 次
- **描述**：wfctl 读取 s07 上报的 `parallel_targets`（选定模块清单），为每个模块：
  1. 创建独立 git worktree
  2. 启动 `module-design-pipeline@1.1.0` 子工作流实例，注入模块标识和增量场景参数
  3. 等待所有子工作流实例完成
  4. 将各 worktree 变更合并回实例 worktree
  5. 全部成功 → 解锁 s09；任一失败 → 回 s07 让用户重新选择
- **最大并发实例**：10

---

### s09-project-sync-check -- 项目级同步矛盾检查

- **Skill**：`project-sync-aggregator`
- **确认行为**：通过 edges `success` + `choice` 模式实现多轮交互确认
- **描述**：汇总所有已完成模块的同步矛盾报告（各模块子工作流在其 s12 阶段产出的 `_sync-issues.md`），以项目级视角呈现冲突全景。用户决定：
  - **修改技术栈**：回到 s02 重新进行架构选型，级联重置 s02–s08，修正后重新走完整流水线
  - **调整项目结构**：回到 s04 重新设计项目结构，级联重置 s04–s08
  - **调整模块边界**：回到 s05 重新拆解模块，级联重置 s05–s08
  - **继续处理其他模块**：回到 s07 选择下一批模块，级联重置 s07–s08
  - **接受差异**：接受当前所有同步矛盾的差异（标注 `accepted`），结束工作流
  - **终止工作流**：接受当前状态，结束工作流
  - **放弃**：放弃本次同步检查，终止工作流

### s99-workflow-end -- 工作流终止

虚拟终止点，所有退出路径汇聚于此。

---

## Skill 清单

| Skill ID | 名称 | 使用 Stage | 状态 |
|----------|------|-----------|------|
| `design-tech-stack` | 技术栈设计 | s01, s02, s03 | 现有 |
| `project-structure-designer` | 项目结构设计 | s04 | 现有 |
| `module-breakdown-designer` | 功能模块拆解设计 | s05 | 现有 |
| `module-dependency-analyzer` | 模块依赖分析 | s06 | 现有 |
| `project-dispatch-manager` | 项目调度管理器 | s07 | 现有 |
| `project-sync-aggregator` | 项目同步矛盾聚合器 | s09 | 现有 |

---

## 共享资源

以下资源部署在消费者项目的 `.claude/workflows/project-design-pipeline/` 目录下，父工作流和子工作流均可访问（worktree 自动携带 `.claude/` 目录）：

| 路径 | 类型 | 说明 |
|------|------|------|
| `.claude/workflows/project-design-pipeline/references/directory-convention.md` | 规范 | 全局目录结构约定（`docs/` 路径格式为硬性约束） |
| `.claude/workflows/project-design-pipeline/references/sync-issues-format.md` | 规范 | 同步矛盾上报格式 |
| `.claude/workflows/project-design-pipeline/scripts/get_timestamp.py` | 脚本 | 时间戳生成工具 |

---

## 故障与回退机制

### 循环超限（loop_exceeded）

所有确认点的 `success` + `choice` 自循环达到 `max_loop` 上限后，流转到 `s99-workflow-end` 终止工作流。用户可在终止后重新启动新实例。

### 依赖分析失败降级

s06（`module-dependency-analyzer`，`retry: 1`）执行失败且重试耗尽后，沿 `failure` edge 降级跳过，仍进入 s07 继续模块调度。s07 的 `project-dispatch-manager` 设计为在缺少依赖分析文档时仍可正常运行（跳过依赖分层展示）。此降级策略确保单个分析环节的失败不会阻塞整体项目推进。

### 子工作流调度失败

s08（`parallel` + `workflow`，`retry: 1`）中任意子工作流实例进入 FAILED 终态时，wfctl 将 s08 置为 ERROR，重试耗尽后沿 `failure` edge 流转回 s07，让用户重新选择模块或终止。子工作流实例的 worktree 由 wfctl 保留以便排查，已成功完成的模块变更正常合并。

### 跨模块同步矛盾

子工作流在其 s12 阶段上报模块级同步问题。父工作流 s09 汇总所有模块的矛盾报告，由用户逐一裁决。解决后可继续调度剩余模块。

### 回边级联重置

s09 确认点提供四条回边路由（s02/s04/s05/s07），均由 wfctl 自动执行级联重置：目标 Stage 及其下游直到 s09 之前的 Stage 全部折叠为 PENDING，重新调度执行。
