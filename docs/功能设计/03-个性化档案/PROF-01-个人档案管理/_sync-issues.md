# 同步问题报告 — PROF-01 个人档案管理

---

## 2026-05-27T14:46:56 MODULE: PROF-01 个人档案管理

### 处理摘要
- **场景**: full_design
- **执行阶段**: s01, s03, s05, s06, s07, s08, s09, s10
- **状态**: completed
- **产物**:
  - docs/功能设计/03-个性化档案/PROF-01-个人档案管理/PROF-01-个人档案管理-意图文档.md
  - docs/功能设计/03-个性化档案/PROF-01-个人档案管理/PROF-01-个人档案管理-设计文档.md
  - docs/功能设计/03-个性化档案/PROF-01-个人档案管理/PROF-01-个人档案管理-落地规范.md
  - docs/contracts/PROF-01/ProfileBehaviorType.json
  - docs/contracts/PROF-01/DiagnosisType.json
  - docs/contracts/PROF-01/LanguageLevel.json
  - docs/contracts/PROF-01/SensoryFeature.json
  - docs/contracts/PROF-01/Trigger.json
  - docs/contracts/PROF-01/AgeRange.json
  - docs/contracts/PROF-01/ProfileCreate.json
  - docs/contracts/PROF-01/ProfileUpdate.json
  - docs/contracts/PROF-01/ProfileResponse.json
  - docs/contracts/PROF-01/ProfileListItem.json
  - docs/contracts/PROF-01/ProfileLimitExceededError.json
  - docs/contracts/PROF-01/ProfileConflictError.json
  - docs/contracts/PROF-01/_module-index.json

### 同步矛盾

#### [medium] contract-conflict: BehaviorType 同名异构
- **描述**: PROF-01 定义的 BehaviorType 枚举（`[刻板行为, 情绪崩溃, 自伤行为, 攻击行为, 社交退缩, 多动]`，面向个体患者行为特征分类）与 CASE-01 已有契约 BehaviorType.json（`[自伤, 攻击, 刻板, 逃跑, 情绪崩溃, 其他]`，面向案例核心行为问题分类/模板聚类）同名异构。语义重叠约 67%（4/6 项相似），但业务域不同——PROF-01 为单值个体分类，CASE-01 为多选案例分类。CASE-01 契约为 `draft` 状态，已有 3 个消费者（CASE-03、CASE-07、CASE-09）。
- **来源阶段**: s08-contract-harmonize
- **影响模块**: PROF-01, CASE-01
- **解决状态**: 已解决。PROF-01 采用 `ProfileBehaviorType` 命名避碰，CASE-01 契约不受影响。两枚举保持独立，通过命名空间隔离消除冲突。

#### [low] dependency-drift: AUTH-04 消费者未注册
- **描述**: 设计文档和落地规范声明 PROF-01 需要消费 AUTH-04 的 `UserRole` 和 `require_role` 两项契约，但 PROF-01 尚未在 AUTH-04/UserRole.json 和 AUTH-04/require_role.json 的 `x-consumers` 中注册。这是首次设计过程中的遗漏，不影响技术可行性。
- **来源阶段**: s08-contract-harmonize
- **影响模块**: PROF-01, AUTH-04
- **解决状态**: 已解决。s09-spec-final 阶段已补充注册，PROF-01 已加入 AUTH-04/UserRole.json 和 AUTH-04/require_role.json 的 `x-consumers` 列表。

#### [low] boundary-ambiguity: SEC-03 PII 检测集成方式不确定
- **描述**: s06 技术预研阶段发现 PROF-01 需要 PII 检测能力（档案 nick name 禁止真实姓名），但 SEC-03（传输存储安全/PII 处理）尚无可用契约或接口。集成方式（实时调用 SEC-03 检测接口 vs 仅前端提示+后端正则）为不确定性业务矛盾，阻塞规范阶段的技术选型。
- **来源阶段**: s06-spec-research
- **影响模块**: PROF-01, SEC-03
- **解决状态**: 已解决。s07 设计文档阶段确认采用「前端提示 + 后端关键词正则 + 预留 `_pii_check()` No-op 扩展点」方案，待 SEC-03 契约就绪后激活完整检测。

#### [low] intent-defect: 错误提示交互模式待产品确认
- **描述**: s06 技术预研阶段发现错误提示文案和交互模式（字段内联提示 vs 业务弹窗 vs 权限横幅）为 UX 产品决策，非技术自主决策范围，标记为待确认业务矛盾。
- **来源阶段**: s06-spec-research
- **影响模块**: PROF-01
- **解决状态**: 已解决。s07 设计文档阶段确认采用「混合模式」——字段内联 + 业务弹窗 + 权限横幅，根据错误类型分级使用。

---

### 无活跃矛盾声明

本周期共发现 4 项同步矛盾（1 medium + 3 low），全部在设计流程中已解决。无活跃矛盾待裁决。

✅ 本周期所有同步矛盾已处理完毕，PROF-01 模块设计流程完成，可正常交付。
