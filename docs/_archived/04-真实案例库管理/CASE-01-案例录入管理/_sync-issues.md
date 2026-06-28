# 同步问题报告 — CASE-01 案例录入管理

---

## 2026-05-27T09:51:00 MODULE: CASE-01 案例录入管理

### 处理摘要
- **场景**: full_design
- **执行阶段**: s01, s03, s05, s06, s07, s08, s09
- **状态**: completed
- **产物**:
  - docs/功能设计/04-真实案例库管理/CASE-01-案例录入管理/CASE-01-案例录入管理-意图文档.md
  - docs/功能设计/04-真实案例库管理/CASE-01-案例录入管理/CASE-01-案例录入管理-设计文档.md
  - docs/功能设计/04-真实案例库管理/CASE-01-案例录入管理/CASE-01-案例录入管理-落地规范.md
  - docs/contracts/CASE-01/CaseStatus.json
  - docs/contracts/CASE-01/SourceType.json
  - docs/contracts/CASE-01/BehaviorType.json
  - docs/contracts/CASE-01/SeverityLevel.json
  - docs/contracts/CASE-01/SceneType.json
  - docs/contracts/CASE-01/EvidenceLevel.json
  - docs/contracts/CASE-01/FamilyDisplayCategory.json
  - docs/contracts/CASE-01/CaseCreateRequest.json
  - docs/contracts/CASE-01/CaseUpdate.json
  - docs/contracts/CASE-01/CaseResponse.json
  - docs/contracts/CASE-01/CaseListItem.json
  - docs/contracts/CASE-01/PiiWarning.json
  - docs/contracts/CASE-01/PiiDetectionResult.json

### 同步矛盾

#### [medium] dependency-drift: 消费者注册缺失

- **描述**: CASE-01 在落地规范中声明了对 DEPLOY-05/AppSettings（环境配置读取）、OBS-01/LogLevel（日志级别枚举）、OBS-01/Logger-interface（结构化日志接口）的消费依赖，但未被登记为这三个契约的 consumers 列表成员：
  1. DEPLOY-05/AppSettings 当前 consumers：["DEPLOY-01", "DEPLOY-02", "DEPLOY-04", "OBS-01", "OBS-02", "OBS-03", "OBS-04", "QUAL-05"]，缺少 CASE-01
  2. OBS-01/LogLevel 当前 consumers：[]，缺少 CASE-01
  3. OBS-01/Logger-interface 当前 consumers：[]，缺少 CASE-01
- **来源阶段**: s08-contract-harmonize
- **影响模块**: CASE-01, DEPLOY-05, OBS-01
- **建议方案**: 将 CASE-01 添加至 DEPLOY-05/AppSettings、OBS-01/LogLevel、OBS-01/Logger-interface 三份契约的 consumers 列表中。OBS-01 的 LogLevel 和 Logger-interface 为框架级基础设施，所有业务模块均应注册为消费者。

#### [medium] boundary-ambiguity: AttachmentRef 类型归属边界待定

- **描述**: CASE-01 的 CaseCreateRequest、CaseUpdate、CaseResponse 模型中包含 attachment_refs 字段，其元素类型 AttachmentRef（{file_name, minio_path, file_type, file_size, uploaded_at, sort_order}）在业务逻辑上属于 CASE-02（案例附件管理）的职责范围。但 CASE-02 尚无设计文档和契约文件，CASE-01 需在当前版本中临时内联定义此结构。CASE-02 落地后可能产生 AttachmentRef 定义漂移的风险。
- **来源阶段**: s08-contract-harmonize
- **影响模块**: CASE-01, CASE-02
- **建议方案**: 方案 A：在当前阶段将 AttachmentRef 定义为临时共享类型写入 docs/contracts/CASE-02/（在 CASE-02 目录下预创建），待 CASE-02 设计时正式接管。方案 B：CASE-01 当前版本内联定义，CASE-02 落地后通过契约升级迁移。

#### [low] intent-defect: PII 检测结果前端展示方式未定

- **描述**: 意图文档 §1.8.2 要求"展示检测到的疑似 PII 字段列表及在文本中的位置"，但未明确前端展示方式——是在叙事文本输入框中直接高亮标记疑似 PII 位置（需要富文本编辑器支持），还是在提交按钮附近以列表形式逐条展示。此决策影响前端编辑器组件选型。
- **来源阶段**: s07-design-doc
- **影响模块**: CASE-01
- **建议方案**: 在规格阶段由用户确认展示方案。MVP 阶段可暂用列表展示形式降低前端复杂度。

#### [low] intent-defect: 表单自动保存生命周期未定

- **描述**: 意图文档 §1.12 第 6 项将表单自动保存策略完全交由 spec-writer 确定。技术决策报告中选择本地自动保存方案（30 秒防抖，localStorage），但草稿的最大存储数量（保留最近 N 次还是仅保留最新）和存储有效期（永久保留还是 X 天后自动清理）涉及用户体验与存储空间的权衡，技术上未确定具体阈值。
- **来源阶段**: s07-design-doc
- **影响模块**: CASE-01
- **建议方案**: MVP 阶段暂定仅保留最新一份草稿且不清除，后续迭代根据用户反馈调整。

### 遗留问题（从上周期延续）

本周期为 CASE-01 首次进入设计流程，无上周期遗留问题。
