# 同步矛盾上报格式

> 本文件为工作流级共享规范。父工作流 `project-design-pipeline@3.0.0` 和子工作流 `module-design-pipeline@1.1.0` 均需遵守。
> 子工作流 s12（module-sync-reporter）按此格式**追加**写入，父工作流 s08（project-sync-aggregator）按此格式**解析**。

---

## 1. 文件位置

`docs/功能设计/[序号]-[分组]/[编号]-[名称]/_sync-issues.md`

子工作流在独立 worktree 中运行，写入各自模块目录下的 `_sync-issues.md`，由父工作流 s07 merge 回主仓库。父工作流 s08 逐个扫描各模块的 `_sync-issues.md` 汇总处理。

---

## 2. 写入规则

- **仅追加**（append-only），绝不覆盖已有条目
- 每次写入一条完整的模块同步报告
- 每条条目以 `## [timestamp] MODULE: [编号] [名称]` 开头
- 时间戳格式：ISO 8601（`2026-05-19T16:00:00`）

---

## 3. 条目结构

```markdown
## [2026-05-19T16:00:00] MODULE: USR-01 订单系统

### 处理摘要
- **场景**: full_design
- **执行阶段**: s03, s04, s05, s06, s07, s08, s09, s10, s11
- **状态**: completed
- **产物**:
  - docs/功能设计/01-用户域/USR-01-订单系统/USR-01-订单系统-意图文档.md
  - docs/功能设计/01-用户域/USR-01-订单系统/USR-01-订单系统-设计文档.md
  - docs/功能设计/01-用户域/USR-01-订单系统/USR-01-订单系统-落地规范.md

### 同步矛盾

#### [high] contract-conflict: UserProfile 类型定义冲突
- **描述**: 本模块定义的 UserProfile 与 AUTH-01 认证模块的 UserProfile 存在字段差异
  - USR-01: \{id, name, email, phone\}
  - AUTH-01: \{id, username, email, avatar\}
- **来源阶段**: s10-contract-harmonize
- **影响模块**: USR-01, AUTH-01
- **建议方案**: 提取公共字段 \{id, email\} 到共享类型 UserProfileBase，各模块扩展自己的版本

#### [low] dependency-drift: 新发现对通知模块的依赖
- **描述**: 订单状态变更时需要发送通知，但依赖分析未标注对 NOTIFY-01 的依赖
- **来源阶段**: s09-spec-design-doc
- **影响模块**: USR-01, NOTIFY-01
- **建议方案**: 更新依赖分析文档，增加 USR-01 → NOTIFY-01 的调用依赖
```

---

## 4. 字段说明

### 处理摘要

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| 场景 | string | 是 | `full_design` / `design_docs_only_intent_frozen` / `design_docs_only_all_complete` / `design_docs_only_intent_draft` / `code_only` / `both_exist` |
| 执行阶段 | string[] | 是 | 实际执行的 stage_id 列表 |
| 状态 | string | 是 | `completed` / `failed` / `abandoned` / `incomplete` |
| 产物 | string[] | 否 | 生成的文件路径列表（相对于项目根目录） |

### 同步矛盾

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| 严重程度 | string | 是 | `critical` / `high` / `medium` / `low` |
| 冲突类型 | string | 是 | `intent-defect` / `tech-stack-conflict` / `contract-conflict` / `dependency-drift` / `boundary-ambiguity` |
| 描述 | string | 是 | 冲突的详细描述，含具体的字段/类型/路径对比 |
| 来源阶段 | string | 是 | 发现此冲突的 sub-workflow stage_id |
| 影响模块 | string[] | 否 | 受此冲突影响的其他模块编号列表 |
| 建议方案 | string | 否 | 推荐的解决方案 |

---

## 5. 冲突类型定义

| 类型 | 说明 | 示例 |
|------|------|------|
| `intent-defect` | 意图文档中的业务规则技术上不可行 | 要求的性能指标在当前技术栈下无法达成 |
| `tech-stack-conflict` | 模块设计需要技术栈不支持的能力 | 模块需要 WebSocket 但技术栈仅支持 REST |
| `contract-conflict` | 模块接口与已有契约冲突 | 同名类型定义不一致 |
| `dependency-drift` | 实际依赖与依赖分析文档不一致 | 发现新的跨模块依赖或已有依赖消除 |
| `boundary-ambiguity` | 模块边界模糊 | 与其他模块有 >30% 功能重叠 |

---

## 6. 严重程度定义

| 级别 | 定义 | 父工作流处理 |
|------|------|------------|
| `critical` | 阻塞多个下游模块，必须立即解决 | 建议回退到对应项目级 Stage 修复 |
| `high` | 阻塞当前模块或一个依赖模块 | 标记受影响模块"待复核" |
| `medium` | 影响设计质量但不阻塞 | 记录，用户可选择接受差异 |
| `low` | 文档级别或修饰性问题 | 自动接受，仅记录 |
