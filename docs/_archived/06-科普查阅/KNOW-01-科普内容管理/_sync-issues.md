# 同步问题记录 — KNOW-01 科普内容管理

---

## [2026-05-26T17:28:30] MODULE: KNOW-01 科普内容管理

### 处理摘要
- **场景**: full_design
- **执行阶段**: s01-detect-existing-artifacts, s03-intent-clarify-authorize, s04-intent-generate-freeze, s05-spec-prepare, s06-spec-research, s07-spec-design-doc, s08-contract-harmonize, s09-spec-final, s10-module-sync-report
- **状态**: completed
- **产物**:
  - docs/功能设计/06-科普查阅/KNOW-01-科普内容管理/KNOW-01-科普内容管理-意图文档.md
  - docs/功能设计/06-科普查阅/KNOW-01-科普内容管理/KNOW-01-科普内容管理-设计文档.md
  - docs/功能设计/06-科普查阅/KNOW-01-科普内容管理/KNOW-01-科普内容管理-落地规范.md
  - docs/contracts/KNOW-01/ArticleCategory.json
  - docs/contracts/KNOW-01/ArticleStatus.json
  - docs/contracts/KNOW-01/ArticleCreate.json
  - docs/contracts/KNOW-01/ArticleUpdate.json
  - docs/contracts/KNOW-01/ArticleSearchParams.json
  - docs/contracts/KNOW-01/ArticleResponse.json
  - docs/contracts/KNOW-01/ArticleListItem.json
  - docs/contracts/KNOW-01/ArticleSearchResult.json
  - docs/contracts/_index.json
  - docs/contracts/KNOW-01/_module-index.json
  - docs/功能设计/_contracts.md

### 同步矛盾

#### [medium] dependency-drift: CASE-01/CASE-03 调用依赖未在依赖分析文档中记录

- **描述**: 模块设计文档声明 KNOW-01 对 CASE-01（案例录入管理）和 CASE-03（案例审核工作流）存在调用依赖：创建/更新文章时通过 `case_repository.exists()` 批量校验关联案例编号是否存在，通过 `case_repository.find_approved_ids()` 确认关联案例为 `approved` 状态。但模块依赖关系分析文档中 KNOW-01 的依赖清单仅包含 AUTH-04（✅）和 SEC-03（⚠️），未列出 CASE-01 和 CASE-03。此外，KNOW-01 在分层方案（§4.3）中被归入 L1 基础层，标注"无上游依赖"，但实际存在对 L4（业务数据层）模块 CASE-01、CASE-03 以及 L2 模块 AUTH-04 的调用依赖，分层定位与实际不符。
- **来源阶段**: s07-spec-design-doc
- **影响模块**: CASE-01, CASE-03
- **建议方案**: (1) 在模块依赖关系分析文档中新增 KNOW-01 → CASE-01（调用依赖，强，✅）和 KNOW-01 → CASE-03（调用依赖，强，✅）两条依赖边；(2) 重新评估 KNOW-01 的分层归属——当前对 AUTH-04、CASE-01、CASE-03 的上游依赖使其不满足 L1"无上游依赖"的定义，建议移至 L3 或 L4 层。

#### [low] dependency-drift: SEC-03 不确定依赖项已确认为不适用

- **描述**: 模块依赖关系分析文档将 KNOW-01 → SEC-03（PII 脱敏）标记为不确定依赖（⚠️），待确认项为"科普文章属于公开发布内容，是否仍需执行 PII 检测"。经 s07 设计阶段确认：科普文章为公开发布内容，正文不含个人身份信息，不适用 PII 检测。设计文档 §1.7 明确禁止在正文中嵌入外部链接或资源，运营管理员人工审核内容合规性，系统层面不执行自动脱敏。
- **来源阶段**: s07-spec-design-doc
- **影响模块**: SEC-03
- **建议方案**: 在模块依赖关系分析文档中将 KNOW-01 → SEC-03 的待定依赖标记为"不适用"并从 KNOW-01 的活跃依赖清单中移除，保留注释说明原因。

---

### 遗留问题（从上周期延续）

（无 — 本模块为首个进入设计流程的模块，无前期遗留问题）
