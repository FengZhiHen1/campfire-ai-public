# 同步问题报告 — CSLT-05 置信度后校验

---

## 2026-05-27 18:00:00 — 报告周期 #1

### 处理摘要

| 属性 | 值 |
|:---|:---|
| **模块编号** | CSLT-05 |
| **模块名称** | 置信度后校验 |
| **增量场景** | full_design |
| **执行阶段** | 完整设计流程（s01 → s03 → s05 → s06 → s07 → s08 → s09 → s10） |
| **完成状态** | ✅ 全部完成 |
| **产出制品** | 意图文档（已冻结 v2.0）、设计文档（v1.0）、落地规范（v1.0）、契约文件 ×3（ValidationVerdict.json/ConfidenceValidationInput.json/ConfidenceValidationOutput.json）+ 模块索引 |

### 同步矛盾清单

#### #1 — 契约冲突 / high

| 属性 | 值 |
|:---|:---|
| **类型** | `contract-conflict` |
| **严重程度** | `high` |
| **来源** | 契约协调阶段（s08）+ 技术决策报告 §2.2 |
| **描述** | CSLT-05 输入定义 `ConfidenceValidationInput` 将 `high_risk_keyword_hit: boolean` 标记为必填字段（§1.6.1），用于判断是否直接进入 FORCE_BLOCK 路径。但 CSLT-01 的上游契约 `CrisisJudgmentResult.json`（`docs/contracts/CSLT-01/CrisisJudgmentResult.json`）当前定义的 6 个属性（`final_level`、`block_deep_response`、`manual_review_flag`、`review_confidence`、`judgment_sources`、`degradation_note`）中**不包含 `high_risk_keyword_hit` 字段**。两个模块的契约存在字段级间隙——CSLT-05 需要来自 CSLT-01 的高危关键词命中标记，但 CSLT-01 的合约中无此输出字段。 |
| **影响范围** | CSLT-05 无法直接从上游 CSLT-01 获取用户原文的高危关键词命中状态，需要使用降级方案（从 `judgment_sources` 数组反推：检索 `layer_name='RuleEngine'` 且 `trigger_rule_id` 以 `'KW_'` 开头的条目）。降级方案依赖 CSLT-01 的内部实现细节（`JudgmentLayerResult` 的字段命名约定），使 CSLT-05 对 CSLT-01 的耦合从接口级扩展到了实现级，增加了因 CSLT-01 内部重构而破坏 CSLT-05 正确性的风险。 |
| **降级方案** | 在 `validate_confidence()` 前置检查中，若 `input.high_risk_keyword_hit` 字段不存在（被 CSLT-08 编排层传 `undefined`），则扫描 `CrisisJudgmentResult.judgment_sources`：对每个 `JudgmentLayerResult` 检查 `layer_name === 'RuleEngine'` 且 `trigger_rule_id.starts_with('KW_')`，任一匹配则视为 `high_risk_keyword_hit=true`。 |
| **建议处理** | **方案 A（推荐）**：在 CSLT-01 的 `CrisisJudgmentResult.json` 中新增 `high_risk_keyword_hit: boolean` 字段，描述为"规则引擎层在高危关键词匹配中是否命中"，默认 `false`。此字段由 `RuleEngineLayer` 在匹配到高危关键词时设为 `true`。CSLT-01 技术方案中已包含 AC 自动机关键词匹配逻辑（设计文档 §1.1），字段添加成本极低，对 CSLT-01 已有合约无破坏性影响（新增 optional 字段）。**方案 B（备选）**：CSLT-05 完全依赖自身的独立关键词扫描，不接受 CSLT-01 的标记。此方案技术上可行（CSLT-05 扫描对象是方案全文而非用户原文），但弱化了安全纵深防御体系的第一层（用户输入层关键词检测结果无法传递给后续模块）。 |

#### #2 — 依赖漂移 / low（关注点）

| 属性 | 值 |
|:---|:---|
| **类型** | `dependency-drift` |
| **严重程度** | `low` |
| **来源** | 落地规范 §1.7.2 + 模块索引 |
| **描述** | CSLT-05 的 `ConfidenceValidationOutput` 合约在模块索引 `_module-index.json` 中将 `TICK-01` 登记为消费者之一（`consumers: ["CSLT-08", "CSLT-06", "TICK-01"]`），表示 CSLT-05 的输出结果中包含 `ticket_triggered` 和 `ticket_creation_failed` 字段供 TICK-01 引用或核查。但 TICK-01（工单自动生成）模块尚未进入设计流水线，其对外接口和数据模型均未定义。CSLT-05 对 TICK-01 的消费功能目前仅限于内部异步 HTTP 调用 `POST /api/v1/tickets`（由 BackgroundTasks 执行），而非通过 TICK-01 的正式 SDK 或契约。TICK-01 落成后其 API 签名可能与本模块假设的接口不一致。 |
| **影响范围** | 若 TICK-01 后续定义的工单创建接口与 CSLT-05 的假设不一致（如请求体字段不同、认证方式不同、响应格式不同），CSLT-05 的 `trigger_ticket_with_retry()` 内部实现需要适配修改。CSLT-05 的 `ConfidenceValidationOutput.ticket_triggered` 和 `ticket_creation_failed` 字段定义不受影响——这些字段是 CSLT-05 自身输出，TICK-01 引用与否不影响其正确性。 |
| **建议处理** | TICK-01 进入设计流水线后，需将 CSLT-05 的工单创建调用需求作为输入条件提供给 TICK-01 设计团队，确保 `POST /api/v1/tickets` 的接口签名兼容 CSLT-05 的使用方式。CSLT-05 落地规范中已明确标注 TICK-01 的 Mock 策略（`{"id": "mock-uuid", "status": "open"}`），在 TICK-01 落成前不影响本模块的独立开发和测试。 |

#### #3 — 依赖漂移 / low（关注点）

| 属性 | 值 |
|:---|:---|
| **类型** | `dependency-drift` |
| **严重程度** | `low` |
| **来源** | 技术决策报告 §5 矛盾清单 #2 |
| **描述** | 免责提示精确文案（低置信度追加文案和高危阻断文案）标注为"待产品方确认"——当前在 `py-config` 中通过 `LOW_CONFIDENCE_DISCLAIMER` 和 `HIGH_RISK_BLOCK_MESSAGE` 环境变量管理，默认值由技术决策报告提供模板文本。此问题为业务决策（产品方），非技术性同步矛盾，但若产品方最终确认的文案与当前默认模板在语义或长度上差异显著，可能影响：① `modified_plan_text` 的总长度和展示效果（前端 UI 适配）；② 文案的合规审查（SEC-02 安全护栏可能需要对追加文案做额外校验）。 |
| **影响范围** | 影响前端展示效果和文案合规性，不影响 CSLT-05 的技术架构和接口定义。文案变更仅需修改环境变量，无需重新部署代码。 |
| **建议处理** | 在产品方确认文案后，通过 `packages/py-config` 的环境变量部署即可，无需修改 CSLT-05 代码。若最终文案长度超过预期（如超过 500 字），需评估对 `modified_plan_text` 字段长度的影响，并在 `ConfidenceValidationInput.plan_text` 的 `maxLength` 约束中预留足够空间。 |

---

### 遗留问题（从上周期延续）

无。本模块为首个设计周期，CSLT-05 无上周期遗留的 _sync-issues.md 文件。

### 已知风险（来自模块依赖关系分析）

以下风险已由 `docs/功能设计/模块依赖关系分析.md` 记录，非本周期新增，在此汇总供上游聚合参考：

- **CRITICAL关键词库三向共享**（风险项 #1）：CSLT-05 复用 CSLT-01/SEC-02 的高危关键词词库（AC 自动机 + Redis Pub/Sub 热更新）。三模块共享同一词库确保新增高危词无遗漏阻断。不构成契约冲突，但为架构级风险——若词库加载逻辑在某一模块中出现 bug，会影响全部三个模块的关键词检测正确性。推荐方案已在技术决策报告 §4 决策 #5 中明确：提取至 `packages/py-config/` 公共常量 `CRISIS_KEYWORDS` 单点维护。

---

### 扫描来源完整性声明

本报告已扫描以下来源：

| 来源 | 路径 | 状态 |
|:---|:---|:---|
| 运行时产物：artifact-manifest.json | `.tmp/artifact-manifest.json` | ✅ 已读取 |
| 运行时产物：route-decision.json | `.tmp/route-decision.json` | ✅ 已读取 |
| 运行时产物：tech-decision-report | `.tmp/reports/tech-decision-report-CSLT-05.md` | ✅ 已读取 |
| 全局 _sync-issues.md | `docs/功能设计/_sync-issues.md` | ✅ 已读取（含 s05/s07 两阶段一致性记录） |
| CSLT-02 _sync-issues.md | `docs/功能设计/02-智能应急咨询/CSLT-02-RAG语义检索/_sync-issues.md` | ✅ 已读取（无 CSLT-05 相关条目） |
| CSLT-03 _sync-issues.md | `docs/功能设计/02-智能应急咨询/CSLT-03-应急方案生成/_sync-issues.md` | ✅ 已读取（无 CSLT-05 相关条目） |
| 落地规范 | `CSLT-05-置信度后校验-落地规范.md` | ✅ 已读取 |
| 设计文档 | `CSLT-05-置信度后校验-设计文档.md` | ✅ 已读取 |
| 意图文档 | `CSLT-05-置信度后校验-意图文档.md` | ✅ 已读取 |
| 本模块契约文件 | `docs/contracts/CSLT-05/`（×3） | ✅ 已读取 |
| 上游契约：CrisisJudgmentResult | `docs/contracts/CSLT-01/CrisisJudgmentResult.json` | ✅ 已读取（确认缺少 high_risk_keyword_hit） |

**矛盾统计**：
- `contract-conflict` / `high`：1 项（#1 — CrisisJudgmentResult 缺少 high_risk_keyword_hit 字段）
- `dependency-drift` / `low`：2 项（#2 — TICK-01 未设计，#3 — 文案待产品确认）

**总体结论**：CSLT-05 置信度后校验模块设计全流程（s01→s10）完成，1 处契约冲突（high）已在降级方案中覆盖，2 处低风险关注点记录备查。无阻塞性矛盾。
