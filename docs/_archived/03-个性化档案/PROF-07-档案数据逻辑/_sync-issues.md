# 同步问题报告 — PROF-07 档案数据逻辑

---

## [2026-05-27T21:55:00] MODULE: PROF-07 档案数据逻辑

### 处理摘要
- **场景**: full_design
- **执行阶段**: s01, s03, s05, s06, s07, s08, s09, s10
- **状态**: completed
- **产物**:
  - docs/功能设计/03-个性化档案/PROF-07-档案数据逻辑/PROF-07-档案数据逻辑-意图文档.md
  - docs/功能设计/03-个性化档案/PROF-07-档案数据逻辑/PROF-07-档案数据逻辑-设计文档.md
  - docs/功能设计/03-个性化档案/PROF-07-档案数据逻辑/PROF-07-档案数据逻辑-落地规范.md
  - docs/contracts/PROF-07/_module-index.json

### 同步矛盾

#### [high] dependency-drift: PROF-02 缓存失效 API 未定义（GAP-01）
- **描述**: PROF-07 档案变更后需通知 PROF-02 进行缓存失效。本模块设计文档推测使用 `POST /api/v1/profiles/{profileId}/invalidate-cache` 接口并携带 `{profileId, changedFields}` 请求体，但 PROF-02（档案驱动检索过滤）尚未启动设计，其缓存失效机制（HTTP API vs Redis pub/sub vs 后端自动监听）未确定。本模块实现时带 null-guard：接口 404 或网络错误时降级为 console.warn，不阻断用户操作。
- **来源阶段**: s08-contract-harmonize（契约协调阶段）；s06-spec-research（技术预研阶段亦标记为业务矛盾 #1）
- **影响模块**: PROF-07, PROF-02
- **建议方案**: (1) PROF-02 启动设计时优先确定缓存失效通知机制；(2) 若采用 HTTP API，验证本模块推测的 `POST /api/v1/profiles/{profileId}/invalidate-cache` 接口路径和 `{profileId, changedFields}` 参数格式；(3) PROF-07 实现时保留通知抽象层，允许后续切换实现方式。

#### [medium] dependency-drift: CSLT-08 ProfileCoordination 协作接口未定义（GAP-02）
- **描述**: PROF-07 定义了 3 个与 CSLT-08（咨询编排逻辑）的协作方法——`checkProfileExists()`（冷启动检测）、`triggerMicroSurvey(consultationId)`（微问卷触发）、`onProfileChanged(callback)`（档案变更订阅）。CSLT-08 尚未启动设计，无对应契约。本模块设计文档采用「方法调用 + 回调订阅」的双向互动模式，待 CSLT-08 设计启动后接口签名可能需调整。
- **来源阶段**: s08-contract-harmonize（契约协调阶段）；s06-spec-research（技术预研阶段关联业务矛盾 #1/#4）
- **影响模块**: PROF-07, CSLT-08
- **建议方案**: (1) CSLT-08 启动设计时以本模块定义的 `ProfileCoordination` 接口（见设计文档 §3.1-B）作为基线协商；(2) 采用 ESM import 方式避免循环 import——CSLT-08 通过 `import { ProfileCoordination } from '@/logics/profiles/types'` 引用；(3) 本模块实现时对外暴露类型化接口，便于 CSLT-08 集成时按签名调用。

#### [low] intent-defect: 微问卷题目选择算法待确认（已解决）
- **描述**: 意图文档 §1.6.3 定义了两种微问卷问题类型（触发因素确认、干预有效性反馈），但未指定每次弹出题数（1 或 2）、题目顺序（固定/随机/按优先级）以及同一用户重复咨询时题目内容是否轮换。s06 技术预研阶段标记为业务矛盾 #2。
- **来源阶段**: s06-spec-research（技术预研阶段）
- **影响模块**: PROF-07（仅限内部实现）
- **解决状态**: 已解决。s09-spec-final 阶段裁决采用「每次弹出 2 题全覆盖，题目固定不变」作为最小可行实现，后续可由产品方按需调整。

#### [low] intent-defect: 冷启动跳过后的触发频率上限待确认（已解决）
- **描述**: 意图文档 §1.11(1) 规定"用户可跳过引导但每次进入咨询前会重新检测并提示"，但未设定高频跳过（如一天内 10 次）的频率上限。s06 技术预研阶段标记为业务矛盾 #3。设计边界声明不强制用户必须立即完成冷启动引导，但未设定跳过频率上限。
- **来源阶段**: s06-spec-research（技术预研阶段）
- **影响模块**: PROF-07（仅限内部实现）
- **解决状态**: 已解决。s09-spec-final 阶段裁决采用「每次检测，无频率上限」策略。理由：意图文档未指定上限，且强制限制可能阻止有紧急需求的用户进入咨询。

#### [low] boundary-ambiguity: 微问卷数据沉淀到 PROF-03 的边界待确认（已解决）
- **描述**: 意图文档 §1.2 提到微问卷中触发因素回答"在必要时自动沉淀为事件记录"，但 §1.11(7) 声明事件记录的详细规则校验归属 PROF-03。沉淀方式不明确：是 PROF-07 直接调用 PROF-03 的事件创建 API，还是先将数据写入档案标签后由 PROF-03 异步处理。s06 技术预研阶段标记为业务矛盾 #4。
- **来源阶段**: s06-spec-research（技术预研阶段）
- **影响模块**: PROF-07, PROF-03
- **解决状态**: 已解决。s09-spec-final 阶段裁决：PROF-07 直接调用 PROF-03 `POST /api/v1/events` 创建事件记录，仅当用户显式填写触发因素时才触发写入（非必调路径）。

---

### 遗留问题（从上周期延续）

本周期为 PROF-07 首次完整设计流程，无上周期遗留问题。

---

### 无活跃矛盾声明

本周期共发现 5 项同步矛盾（1 high + 1 medium + 3 low）。其中：
- **3 项已解决**（低严重度，s09 落地规范阶段已明确裁决方案）
- **2 项活跃**（依赖缺口 GAP-01 PROF-02 缓存失效 API、GAP-02 CSLT-08 ProfileCoordination 接口），需对应模块启动设计后验证一致性

PROF-07 模块本身已完成全流程设计（意图冻结/设计文档/落地规范/契约注册），2 项依赖缺口不影响本模块独立实现和交付。
