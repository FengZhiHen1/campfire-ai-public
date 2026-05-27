# 同步问题报告 — CSLT-02 RAG语义检索

---

## 2026-05-27 09:45:00 — 报告周期 #1

### 处理摘要

| 属性 | 值 |
|:---|:---|
| **模块编号** | CSLT-02 |
| **模块名称** | RAG语义检索 |
| **增量场景** | full_design |
| **执行阶段** | 完整设计流程（s01～s09） |
| **完成状态** | ✅ 全部完成 |
| **产出制品** | 意图文档（已冻结）、设计文档、落地规范、契约文件 ×7 |
| **同步矛盾数** | 5 项 |

### 同步矛盾清单

#### #1 — 契约冲突 / high

| 属性 | 值 |
|:---|:---|
| **类型** | `contract-conflict` |
| **严重程度** | `high` |
| **来源** | 契约协调阶段（contract-harmonize-report.json） |
| **描述** | CSLT-02 落地规范 §1.14 和模块契约索引 `_module-index.json` 引用 `CSLT-01/BehaviorTypeCategory.json` 为已复用的可消费契约，用于 `TagFilterDto.behavior_type` 字段的枚举取值。然而 `docs/contracts/CSLT-01/` 目录不存在——CSLT-01 模块尚未进入设计流水线，该契约文件从未被创建。契约协调报告虽标记 match_score=1.0（枚举值与 CSLT-02 字段取值完全一致），但引用的契约文件是"幽灵引用"（phantom reference），在全局契约索引 `_index.json` 中无任何登记记录。 |
| **影响范围** | CSLT-02 的 TagFilterDto 枚举依赖建立在不存在的基础上。若 CSLT-01 后续定义的 BehaviorTypeCategory 枚举值与当前假设不一致（如值变更、增加/删除某些枚举项），则 CSLT-02 需要随之更新接口，影响其消费者（CSLT-03、CSLT-08）。 |
| **建议处理** | 方案 A：CSLT-02 暂时自包含定义 behavior_type 枚举值（与 CSLT-01 设计文档保持一致），待 CSLT-01 进入设计流水线并落地 BehaviorTypeCategory 契约后，再将 CSLT-02 的枚举定义替换为对 CSLT-01 契约的引用。方案 B：由项目管理员协调，优先将 CSLT-01 排入设计流水线以尽早落地 BehaviorTypeCategory 契约。 |

#### #2 — 依赖漂移 / medium

| 属性 | 值 |
|:---|:---|
| **类型** | `dependency-drift` |
| **严重程度** | `medium` |
| **来源** | 契约协调阶段（contract-harmonize-report.json cross_module_notes） |
| **描述** | CSLT-02 定义的 `TagFilterDto` 标注为"临时自包含定义，待 PROF-02 落地后改为引用"。其中 `age_range` 字段的枚举取值由 PROF-02 定义，但 PROF-02 尚未进入设计流水线，也未落地任何契约。CSLT-02 当前自包含定义了此结构，若 PROF-02 后续定义的 `TagFilterDto` 接口（或等价结构）与 CSLT-02 的假设不一致（如字段名不同、类型不同、枚举值集不同），将产生接口不匹配。 |
| **影响范围** | CSLT-02 的输入接口 `TagFilterDto` 需要修改以对齐 PROF-02 的权威定义，届时 CSLT-03、CSLT-08 等消费者可能也需要同步更新。 |
| **建议处理** | 在 PROF-02 设计阶段将 CSLT-02 的 TagFilterDto 使用情况作为输入条件提供给 PROF-02 团队，确保 PROF-02 定义其上游数据接口时兼容 CSLT-02 的使用方式。CSLT-02 落地时保留 TagFilterDto 的自包含定义，但在 PROF-02 落地契约后及时切换为引用。 |

#### #3 — 依赖漂移 / medium

| 属性 | 值 |
|:---|:---|
| **类型** | `dependency-drift` |
| **严重程度** | `medium` |
| **来源** | 契约协调阶段（contract-harmonize-report.json cross_module_notes） |
| **描述** | CSLT-02 的 `CaseSliceDto.slice_id` 字段（UUID 类型）引用了 CASE-04 维护的 `case_chunks` 表主键。CASE-04 尚未进入设计流水线，也未定义任何契约。若 CASE-04 后续定义的主键类型不是 UUID（如使用自增整数或复合主键），则 CSLT-02 的输出类型定义与 CASE-04 的数据模型将不一致。 |
| **影响范围** | CASE-04 的数据模型变更将直接导致 CSLT-02 的输出类型 `CaseSliceDto` 需要适配，影响下游消费者 CSLT-03。 |
| **建议处理** | 在 CASE-04 设计阶段，确保其 case_chunks 表的主键类型与 CSLT-02 的 CaseSliceDto.slice_id 定义（UUID）保持一致。CSLT-02 可在落地规范的字段注释中标注此设计约束，供 CASE-04 参考。 |

#### #4 — 契约冲突 / low

| 属性 | 值 |
|:---|:---|
| **类型** | `contract-conflict` |
| **严重程度** | `low` |
| **来源** | 契约协调阶段（contract-harmonize-report.json recommendations） |
| **描述** | CSLT-02 是 `CSLT-01/BehaviorTypeCategory` 枚举的新增消费者。CSLT-01 模块当前 x-consumers 列表（将来创建时）仅包含 CSLT-07，未登记 CSLT-02。CSLT-02 的 TagsFilterDto 通过 `referenced_enum: CSLT-01/BehaviorTypeCategory` 引用该枚举，但在 CSLT-01 的消费者清单中未被记录。 |
| **影响范围** | 当 CSLT-01 的 BehaviorTypeCategory 需要变更时（如增加/删除枚举项），由于消费者清单缺少 CSLT-02，该变更的影响范围评估将遗漏 CSLT-02。 |
| **建议处理** | CSLT-01 进入设计流水线并落地 BehaviorTypeCategory 契约时，需将 CSLT-02 追加到 x-consumers 列表中。 |

#### #5 — 契约冲突 / low

| 属性 | 值 |
|:---|:---|
| **类型** | `contract-conflict` |
| **严重程度** | `low` |
| **来源** | 设计文档加工制品分析 |
| **描述** | CSLT-02 设计文档和落地规范声明消费 `DEPLOY-05/AppSettings` 中的 4 个字段（EMBEDDING_MODEL、EMBEDDING_DIMENSION、DASHSCOPE_API_KEY、DASHSCOPE_BASE_URL），但 `docs/contracts/DEPLOY-05/AppSettings.json` 的 `x-consumers` 列表中仅登记了 DEPLOY-01/02/04、OBS-01/02/03/04、QUAL-05，未包含 CSLT-02。 |
| **影响范围** | DEPLOY-05 的 AppSettings 配置变更时（如字段名修改、类型变更、废弃某配置项），变更影响评估将遗漏 CSLT-02。 |
| **建议处理** | 将 CSLT-02 追加到 DEPLOY-05/AppSettings.json 的 x-consumers 列表中。 |

---

### 遗留问题（从上周期延续）

无。本模块为首个设计周期，无上周期遗留问题。

---

### 补充说明

契约协调报告（contract-harmonize-report.json）声明 **0 项冲突**，其评估范围是 CSLT-02 的 7 个新类型与 80 个已有契约文件之间的冲突检查。上述 5 项矛盾涉及的是**尚未落地的未来模块**（CSLT-01、PROF-02、CASE-04）的契约引用与消费者登记问题——这些不属于已有契约间的命名/结构冲突，故未被计入协调报告统计。本报告予以补充收录，供上层聚合决策参考。
