# 同步问题报告 — CSLT-06 咨询历史管理

---

## 2026-05-27 18:04:00 — 报告周期 #1

### 处理摘要

| 属性 | 值 |
|:---|:---|
| **模块编号** | CSLT-06 |
| **模块名称** | 咨询历史管理 |
| **增量场景** | full_design |
| **执行阶段** | 完整设计流程（s01→s10） |
| **完成状态** | ✅ 全部完成 |
| **产出制品** | 意图文档 v2.0（已冻结）、设计文档 v1.0、落地规范 v1.0、契约文件 ×3（ConsultationHistoryCreate / ConsultationHistoryListItem / ConsultationHistoryDetail）|

### 同步矛盾清单

#### #1 — 契约冲突 / medium

| 属性 | 值 |
|:---|:---|
| **类型** | `contract-conflict` |
| **严重程度** | `medium` |
| **来源** | 设计文档 v1.0 §1.2（s07 设计文档生成阶段 → s08 契约协调阶段检出） |
| **描述** | 设计文档 v1.0 兼容性分析节（§1.2）错误地将 `confidence_score` 列为 CSLT-03/GenerationResult 的第 9 个字段，声称 GenerationResult 含 9 个字段"text、source_list、disclaimer、confidence_score、is_partial、referenced_slice_ids、finish_reason、ttft_ms、generation_time_ms"。实际 `docs/contracts/CSLT-03/GenerationResult.json` 仅有 8 个字段，不支持 `confidence_score`。根源：`confidence_score` 的真实来源为 CSLT-05（置信度后校验），非 CSLT-03——设计文档此处为笔误。该笔误在设计文档中共计 2 处（§1.2 line 59 列字段清单含 confidence_score、§1.2 line 66 称"消费其全部 9 个字段"），与同文档 §1.3 line 83 正确列出的 8 个字段自相矛盾。 |
| **影响范围** | 本模块内部设计一致性。下游 CSLT-08 若按设计文档所述的 9 个字段组装归档请求，会缺失 `confidence_score` 来源。 |
| **当前处理** | **已在落地规范 v1.0（§1.3）中更正**。确认 confidence_score 来源于 CSLT-05，推迟至 CSLT-05 设计完成并定义输出契约后，通过 Alembic 迁移追加到 consultations 表。ConsultationHistoryCreate.json 契约不含此字段。CSLT-06/_module-index.json 已添加注释说明"GenerationResult 不包含 confidence_score 字段"。设计文档 v1.0 未同步修正（设计文档自 v1.0 后冻结）。 |

#### #2 — 意图缺陷 / low

| 属性 | 值 |
|:---|:---|
| **类型** | `intent-defect` |
| **严重程度** | `low` |
| **来源** | 意图文档 v2.0 §1.6.1 / AC-01 vs. 落地规范 v1.0 / ConsultationHistoryCreate.json 契约 |
| **描述** | 已冻结的意图文档 v2.0 将"置信度评估分数"列为必填输入字段（§1.6.1 输入表第 7 行），AC-01 要求"全部 9 个必填字段"包含置信度分数。但落地规范 v1.0 的 ConsultationHistoryCreate.json 契约**不含此字段**——因 CSLT-05（置信度后校验）尚未设计，无法确定字段的数据来源和输出格式。此偏差已在落地规范 §1.15"偏差说明"中明确记录。 |
| **影响范围** | 冻结的意图文档与最终契约存在字段级不一致。当 CSLT-05 设计完成后需追加此字段，届时需解冻意图文档或追溯性确认偏差合理。 |
| **当前处理** | 落地规范 §1.15 已记录偏差。CSLT-06/_module-index.json GenerationResult 条目已添加注意事项。两处文档配合可清晰溯源，但意图文档本身未更新。 |

#### #3 — 边界歧义 / low

| 属性 | 值 |
|:---|:---|
| **类型** | `boundary-ambiguity` |
| **严重程度** | `low` |
| **来源** | 设计文档 §1.3 / 落地规范 §1.3 |
| **描述** | `has_feedback` 标记的写入机制依赖 QUAL-03（用户反馈收集）的接口定义。当前 QUAL-03 尚未设计，CSLT-06 落地规范 §1.3 定义了内部类型 `ConsultationHistoryFeedbackUpdate` 作为占位，并预留了 `PATCH /api/v1/consultations/{id}/feedback` 端点，但精确的请求格式、认证方式、错误码映射等均有待 QUAL-03 设计时协商。 |
| **影响范围** | 下限：到达 QUAL-03 设计阶段时需协商接口，不影响 MVP 期间的核心归档功能（`has_feedback` 默认 false 开箱可用）。上限：若 QUAL-03 与 CSLT-06 设计周期交叉，可能导致双方架构师重复沟通。 |
| **当前处理** | 已标注"待协商接口"。非阻塞。 |

#### #4 — 边界歧义 / low

| 属性 | 值 |
|:---|:---|
| **类型** | `boundary-ambiguity` |
| **严重程度** | `low` |
| **来源** | 意图文档 §1.11 #5 / 设计文档 §1.4 / 技术决策报告 §5 #1 |
| **描述** | 数据保留策略通过意图文档 §1.11 #5 委托给 QUAL-05（数据备份恢复）管理，但 QUAL-05 尚未设计。当前设计采用"永久保留 + QUAL-05 后续定义清理策略"方案，MVP 阶段无物理删除逻辑。如果 QUAL-05 在 MVP 阶段未实现，实际运行中档案数据将持续累积无清理，可能影响查询性能或合规审查。 |
| **影响范围** | 若 QUAL-05 长期缺位，consultations 表数据量持续增长至单用户数万条记录后列表查询性能可能衰减。当前索引策略（`(user_id, consultation_time DESC)`）可应对至少数十万量级，风险可控。 |
| **当前处理** | 已标注"非阻塞"。实施阶段需确认 QUAL-05 的时间表。 |

#### #5 — 契约冲突 / low

| 属性 | 值 |
|:---|:---|
| **类型** | `contract-conflict` |
| **严重程度** | `low` |
| **来源** | 设计文档 §3.1 vs. ConsultationHistoryCreate.json 契约 |
| **描述** | 设计文档 §3.1 定义了 `retrieved_case_ids: list[str]`（检索案例标识列表，格式 "CASE-NNN-sliceNN"，必需可空），但 ConsultationHistoryCreate.json 契约未包含此字段。该字段在意图文档 §1.6.1 中以"检索案例标识列表"出现，设计文档将其保留，但在从设计到契约的转化过程中丢失（既未被纳入 contract，也未在 landing spec 中提及删除理由）。当前契约中仅含 `source_list`（格式化引用字符串）和 `referenced_slice_ids`（GenerationResult 引用的 UUID 列表），两者可以覆盖该字段拟承载的信息，但显式丢失设计溯源。 |
| **影响范围** | 若上游 CSLT-08 按设计文档 §3.1 组装归档数据，会尝试传入 `retrieved_case_ids` 字段，但契约不识别该字段（`additionalProperties: false`），导致校验拒绝。 |
| **当前处理** | 落地规范和契约中均未包含。建议：若 `referenced_slice_ids` + `source_list` 已覆盖下游需求，应在设计文档 §3.1 中删除 `retrieved_case_ids`；若因合规审计等原因需要保留原始检索标识与引用标识的分离，需在 ConsultationHistoryCreate.json 中追加该字段。 |

---

### 统计汇总

| 维度 | 统计 |
|:---|:---|
| **矛盾总数** | 5 |
| **按类型** | contract-conflict ×2、intent-defect ×1、boundary-ambiguity ×2 |
| **按严重程度** | medium ×1、low ×4 |
| **已解决（当前周期）** | 2（#1 契约冲突已在落地规范中修正；#2 意图缺陷已在落地规范中记录偏差说明） |
| **待解决（遗留）** | 3（#3 QUAL-03 接口待协商；#4 QUAL-05 策略待确认；#5 retrieved_case_ids 字段需决定保留或删除） |

---

### 遗留问题（从上周期延续）

无。CSLT-06 为首次进入设计流程的模块，无上周期遗留问题。

---

### 全局同步问题关联

现有 `docs/功能设计/_sync-issues.md` 中已登记 CSLT-06 相关条目（2026-05-27 17:12 材料准备一致性检查、2026-05-27 17:42 设计文档生成阶段复查），均报告"✅ 无冲突"。本报告周期为首次系统性地收集全设计生命周期中发现的同步矛盾，与全局记录不冲突。
