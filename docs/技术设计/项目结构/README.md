# 项目结构

> **本文档组唯一拥有**：仓库形态、分层架构、目录骨架、层间数据流、命名与模块边界约定。各子文档的事实归属见文末「文档地图」。
> **状态**：v3.0 目标态基线（2026-08-04 收束，[DSR-006](../决策/DSR-006-项目结构v3目标态.md)）。按 Agent 化（[ADR-007](../决策/ADR-007-Agent化-统一基座与分面自治.md)、[ADR-011](../决策/ADR-011-Agent内核框架-内核加扩展与PydanticAI路线.md)）、时刻分层（[ADR-009](../决策/ADR-009-应急链路时刻分层重构.md)）、档案四层（[ADR-010](../决策/ADR-010-档案四层结构与事件记录ABC标准化.md)）、平台分工与内测（[ADR-006](../决策/ADR-006-平台分工-小程序与Web.md)、[ADR-012](../决策/ADR-012-内测期Web承载需求侧服务.md)）、认证重构（[ADR-013](../决策/ADR-013-用户认证体系重构.md)）全面重订。未落地部分在[目录骨架](./目录骨架.md)以状态标注，实施进度以代码库为准。
> **架构模式**：Hybrid Monorepo（厚 package、薄 app，[DSR-001](../决策/DSR-001-Hybrid-Monorepo.md)）

## 一、项目基本信息

- **项目名称**：篝火智答 (Campfire-AI)
- **项目类型**：全栈 Hybrid Monorepo
- **核心功能**：智能应急咨询、个性化档案库、真实案例库管理、人工兜底通道、事件趋势复盘、协作照护、科普查阅
- **目标平台**：微信小程序（需求侧终态）+ Web（供给侧工作台 + 内测期需求侧入口，[ADR-006](../决策/ADR-006-平台分工-小程序与Web.md)/[ADR-012](../决策/ADR-012-内测期Web承载需求侧服务.md)）
- **预期规模**：垂直领域中小规模（初期 < 10 万案例切片，用户量级为领域内精准群体）
- **团队规模**：1-3 人，无专职运维
- **代码组织风格**：Hybrid Monorepo — 单一边界轴贯穿后端模块、Agent 扩展与前端特性；领域能力集中在 packages，apps 仅含运行时入口与编排

---

## 二、技术栈回顾

> 以[总体架构](../总体架构.md)为技术选型权威，本表仅摘要结构设计所需的选型上下文。

| 维度 | 选型 | 对结构的影响 |
|:---|:---|:---|
| 前端框架 | React 19 + Vite（react-web）/ Taro 4.x（mini-program） | 双前端统一五层分层（domain/application/viewModel/view/infrastructure，DSR-006） |
| 前端状态管理 | Zustand 5.x | store 归 viewModel 层，经 Hooks 暴露 |
| 后端语言/框架 | Python / FastAPI 0.115+ | api-server 模块与机制模块 1:1；模块内 routes → service → contract 三段式 |
| 异步任务 | Redis 队列 + 独立 Worker（框架选型归[总体架构](../总体架构.md)） | `apps/worker/` 为异步面编排宿主 |
| 数据校验 | Pydantic 2.x | `packages/py-schemas/` 集中 DTO 与 Agent 输出契约（[DSR-002](../决策/DSR-002-模型与Schema集中管理.md)） |
| Agent 框架 | Pydantic AI 2.x + 自研内核（ADR-011） | `packages/py-agent-kernel/`（通用内核，零领域知识）+ `packages/py-agent-extensions/`（Campfire 领域扩展，单包多子包） |
| LLM 服务 | DeepSeek API v3 | 经 pydantic-ai provider 接入；无独立 LLM 客户端包（py-llm 已移除，DSR-006） |
| RAG 检索与嵌入 | pgvector + 阿里 text-embedding-v4 | `packages/py-rag/` 为工具实现底座（检索/切片/嵌入/索引）；编排角色移交内核，LangChain 已退出 |
| 关系型数据库 | PostgreSQL 17.x + pgvector 0.7+ | ORM 模型与 Alembic 迁移集中在 `packages/py-db/` |
| 缓存与队列 | Redis 7.x | `packages/py-cache/` |
| 对象存储 | MinIO | `packages/py-storage/` |
| 认证鉴权 | 身份-凭证分离 + JWT 双 token + 显式 RBAC（[ADR-013](../决策/ADR-013-用户认证体系重构.md)） | `packages/py-auth/` 承载 Token 家族、密码哈希、角色→能力映射；机制归[认证与访问](../机制/认证与访问.md) |
| 安全原语 | PII 检测、红线词规则 | `packages/py-security/`，由 crisis 模块与 security 扩展共同消费 |
| 部署方式 | Docker Compose v2 + Nginx 1.26+ | `infrastructure/` 集中管理部署资产 |
| 包管理器 | uv（Python）+ pnpm（Node.js） | 双工作空间 `pyproject.toml` + `pnpm-workspace.yaml` |
| 日志监控 | structlog + Prometheus + Grafana | `packages/py-logger/`；`infrastructure/monitoring/` |

---

## 三、设计原则

1. **厚 package、薄 app**：领域模型、契约、基础设施适配集中在 `packages/`；app 仅包含 HTTP 路由、依赖注入、业务编排与启动装配；
2. **单一边界轴**：模块边界只有一条划分轴——机制模块边界。api-server 模块、Agent 扩展、前端特性、`py-db`/`py-schemas` 文件域均与机制模块 1:1，不发明第二套分组规则；
3. **内核零领域知识**：`py-agent-kernel` 不 import 任何 Campfire 包，领域能力一律以扩展形态注册（[Agent内核框架](../Agent内核框架.md)）；
4. **单向依赖**：应用层 → 共享能力层 → 工程支撑层；禁止反向依赖，禁止 app 之间直接 import；
5. **契约先行**：`py-schemas`（后端 DTO + Agent 输出契约）与 `ts-shared`（前端类型）为跨端数据契约；
6. **前端五层硬隔离**：view 只经 viewModel 的 Hooks 获取能力；infrastructure 只实现 application 端口；禁止跨层穿透（见[组织与工程约定](./组织与工程约定.md) §十二）；
7. **最小化可工作**：不为未规划的功能预留代码实现；规划中的目录仅在文档标注，不创建空目录。

---

## 四、选定的结构模式

| 维度 | 选定模式 | 选择理由 |
|:---|:---|:---|
| 前端 | 五层分层（domain/application/viewModel/view/infrastructure），层内按特性组织 | 与 AGENTS.md 防穿透规则及前端工具体系对齐（DSR-006，取代 DSR-005 的 views/logics 两层） |
| 后端 | api-server 模块 1:1 镜像机制模块，模块内 routes → service → contract | 单一边界轴；模块即机制的可执行入口 |
| Agent | 内核 + 扩展（kernel 通用、扩展承载全部领域能力） | ADR-011；安全能力同为扩展（security 首位加载 + 启动断言） |
| Monorepo | Hybrid Monorepo（厚 package、薄 app） | DSR-001；uv + pnpm 双工作空间 |
| Python 包 | flat-layout（各 package 内） | 仅作为应用运行（Docker 容器内），不需 pip install 或发布 |

---

## 五、分层架构

### 5.1 分层总览

| 层级 | 层名 | 职责 | 典型内容 |
|:---:|:---|:---|:---|
| L1 | 应用层 | 可独立构建运行的业务入口 | `apps/api-server/`、`apps/worker/`、`apps/react-web/`、`apps/mini-program/` |
| L2 | 共享能力层 | 跨应用复用的领域逻辑、Agent 内核与扩展、基础设施适配 | `packages/py-*`、`packages/ts-shared/` |
| L3 | 工程支撑层 | 部署、运维、配置、文档 | `infrastructure/`、`scripts/`、`docs/` |

### 5.2 后端应用内部（api-server / worker）

| 子层 | 职责 | 对应位置 |
|:---|:---|:---|
| 接口层 | 请求校验、路由分发、响应封装 | `app/modules/<模块>/routes.py` |
| 业务层 | 用例编排、流程控制（应急面代码持有控制流） | `app/modules/<模块>/` `*_service.py` |
| 启动装配 | 扩展清单与加载顺序（security 首位 + 断言）、面白名单注入 | `app/core/agent_bootstrap.py` |
| 领域/契约层 | 实体、枚举、DTO、仓储、Agent 输出契约 | `packages/py-db/`、`packages/py-schemas/` |
| Agent 层 | 内核运行时 + 领域扩展（工具/Skill/事件 handler） | `packages/py-agent-kernel/`、`packages/py-agent-extensions/` |
| 基础设施层 | 外部系统适配 | `packages/py-rag/`、`py-cache/`、`py-storage/`、`py-auth/`、`py-security/` |

### 5.3 前端应用内部（react-web / mini-program，五层）

| 子层 | 职责 | 依赖方向 |
|:---|:---|:---|
| `view/` | 纯 UI：页面、组件、Props 契约 | → viewModel |
| `viewModel/` | Hooks + store：跨介质 UI 状态与编排 | → application |
| `application/` | 用例与端口（`ports/IXxxRepository`） | → domain |
| `domain/` | 实体、枚举、领域规则（零框架依赖） | —（最内层） |
| `infrastructure/` | 端口实现（HTTP 仓储、token 管理、Mapper） | → application（实现端口）、→ domain（仅 Mapper） |

### 5.4 层间依赖规则

```
mini-program ──┐
               ├─→ ts-shared ──→ HTTP/SSE ──→ api-server ──→ packages/py-*
react-web ─────┘                                    │
                                                    ├─→ py-agent-extensions ──→ py-agent-kernel ──→ pydantic-ai
                                                    ├─→ py-db / py-schemas / py-auth / py-rag / py-security / py-cache / py-storage
                                                    └─→ Redis（任务投递）──→ worker ──→ packages/py-*
```

**硬性约束**：

1. 依赖方向：应用层 → 共享能力层 → 工程支撑层（单向）；
2. 应用间禁止直接 import；api-server 与 worker 经 Redis 队列解耦，禁止 RPC；
3. **内核禁令**：`py-agent-kernel` 不得 import 任何 Campfire 包（零领域知识）；扩展不得反向依赖 apps；扩展不得绕过事件总线直调 pydantic-ai Agent 循环；
4. 扩展消费能力包（py-rag/py-db/py-schemas/py-security）实现工具，扩展间零 import（复用下沉内核或抽公共扩展）；
5. 领域层（`py-db/models`、`py-schemas`）不可引用基础设施具体实现；
6. 公共层（`py-config`、`py-logger`）可被任意层引用，不形成循环。

---

## 文档地图

| 文档 | 唯一拥有的事实 |
|------|----------------|
| 本 README | 项目基本信息、技术栈回顾、设计原则、结构模式、分层架构与层间依赖规则 |
| [目录骨架](./目录骨架.md) | 完整目录树（含实施状态标注）、目录职责速查表 |
| [层间数据流与依赖](./层间数据流与依赖.md) | 端到端数据流场景（应急咨询时刻分层 / 案例 Agent 化生产与索引 / 认证授权）、模块间依赖关系（Mermaid） |
| [组织与工程约定](./组织与工程约定.md) | 命名规范、文件组织规则、模块边界、前端五层规则、内核与扩展工程纪律、特殊文件说明、测试规划、扩展预留 |

> v3.0 前的结构决策索引与 v1.0→v2.0 迁移对照已随附录废止（DSR-006），历史见 Git；现行决策索引归[决策](../决策/README.md)。
