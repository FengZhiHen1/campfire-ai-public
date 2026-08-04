# 技术决策记录

> **目标**：记录重大技术取舍的真实备选、选择依据、后果与重访条件。
> **状态**：ADR-001～005 源自原技术栈设计文档（2026-05-23 决策）；DSR-001～006 源自原项目结构文档 v2.0 重构（2026-05-24 决策）。

## 决策索引

| 编号 | 决策 | 状态 |
|------|------|------|
| [ADR-001](./ADR-001-后端框架-FastAPI.md) | 后端框架选择 Python/FastAPI | 有效 |
| [ADR-002](./ADR-002-前端-Taro-微信小程序.md) | 前端选择 Taro + 微信小程序 | 已由 ADR-006 关闭重访 |
| [ADR-003](./ADR-003-向量检索-pgvector.md) | 向量检索选择 pgvector 而非独立向量库 | 有效 |
| [ADR-004](./ADR-004-模块化单体.md) | 架构模式选择模块化单体 | 有效（已由 DSR-001 演进为 Hybrid Monorepo） |
| [ADR-005](./ADR-005-LLM-DeepSeek.md) | LLM 选择 DeepSeek API | 有效 |
| [ADR-006](./ADR-006-平台分工-小程序与Web.md) | 平台分工：小程序=需求侧，Web=供给侧 | 有效 |
| [ADR-007](./ADR-007-Agent化-统一基座与分面自治.md) | 应用 Agent 化：统一基座（Pydantic AI）+ 分面自治 | 有效（安全约束中的「危机分级三层判定」已由 ADR-008 演进为二元安全门；基座实现已由 ADR-011 演进为 py-agent-kernel 内核框架） |
| [ADR-008](./ADR-008-二元安全门取代三级危机分级.md) | 二元安全门取代三级危机分级 + LLM 复审 | 有效（部分语义已由 ADR-009 演进） |
| [ADR-009](./ADR-009-应急链路时刻分层重构.md) | 应急链路时刻分层重构（此刻安全层 + 完整方案层） | 有效 |
| [ADR-010](./ADR-010-档案四层结构与事件记录ABC标准化.md) | 档案四层结构与事件记录 ABC 标准化 | 有效 |
| [ADR-011](./ADR-011-Agent内核框架-内核加扩展与PydanticAI路线.md) | Agent 内核框架：内核+扩展架构与「基于 Pydantic AI、契约仿 pi」路线 | 有效 |
| [DSR-001](./DSR-001-Hybrid-Monorepo.md) | 采用 Hybrid Monorepo（厚 package、薄 app） | 有效 |
| [DSR-002](./DSR-002-模型与Schema集中管理.md) | ORM 模型与 Pydantic Schema 集中管理 | 有效 |
| [DSR-003](./DSR-003-基础设施拆包.md) | 基础设施能力拆分为独立 package | 有效 |
| [DSR-004](./DSR-004-Worker独立应用.md) | Worker 独立为应用 | 有效 |
| [DSR-005](./DSR-005-前端分层与ts-shared.md) | 前端保持 views/logics 分层，引入 ts-shared | ⚠️ 部分被实施偏离（react-web 采用 views/logics，见该文） |

## 沿用的早期决策（原 DSR-006）

以下 v1.0 结构决策在 v2.0 重构中确认保持不变：

| 原决策 | 内容 | 保留原因 |
|:---|:---|:---|
| DS-003 | 前端 Feature-Based + 表现/逻辑分层 | 5 个功能模块边界清晰，views/logics 分离是核心优势 |
| DS-004 | api-server 和 mini-program 分离为独立 app | 技术栈异构、构建独立、部署独立 |
| DS-005 | 后端 flat-layout | 仅作为应用运行，Docker 容器内直接执行，不需要 pip install |

## 待重访事项

- 暂无。（ADR-002 前端形态偏离已由 [ADR-006](./ADR-006-平台分工-小程序与Web.md) 于 2026-06-30 正式收束。）
