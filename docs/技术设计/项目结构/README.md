# 项目结构

> **本文档组唯一拥有**：仓库形态、分层架构、目录骨架、层间数据流、命名与模块边界约定。各子文档的事实归属见文末「文档地图」。
> **来源**：原 `docs/篝火智答-项目结构.md`（v2.0，2026-05-24），2026-06-30 起按唯一事实所有权拆分为文档组。原版本记录表与自检清单为编写过程元信息，已移除（历史见 Git）；原 §13 设计决策记录已拆分至[决策](../决策/README.md)。
> **架构模式**：Hybrid Monorepo（厚 package、薄 app）
>
> ⚠️ **已知偏差**：(1) 本文目录骨架按「Taro 小程序为唯一前端」设计，实施中已新增 `apps/react-web`（React + Vite）；双端分工已由 [ADR-006](../决策/ADR-006-平台分工-小程序与Web.md) 收束（小程序=需求侧，Web=供给侧），本文目录树尚未纳入 react-web 的结构描述；(2) 本文描述 9 个 Python 共享包，代码实际为 11 个（新增 `py-health`、`py-security`），增量同步未进行，以 `packages/` 目录为准；(3) 按 [ADR-007](../决策/ADR-007-Agent化-统一基座与分面自治.md)，将新增 `packages/py-agent/`（统一 Agent 基座）与顶层 `skills/`（Agent Skills 标准能力包目录），`py-llm` 将随基座落地退役——标注为「Agent 化新增（规划）」，以实施落地为准。

## 一、项目基本信息

- **项目名称**：篝火智答 (Campfire-AI)
- **项目类型**：全栈 Hybrid Monorepo
- **核心功能**：智能应急咨询、个性化档案库、真实案例库管理、人工兜底通道、科普查阅
- **目标平台**：微信小程序（一期优先）+ H5 管理后台（远期预留）
- **预期规模**：垂直领域中小规模（初期 < 10 万案例切片，用户量级为领域内精准群体）
- **团队规模**：1-3 人，无专职运维
- **代码组织风格**：Hybrid Monorepo — 前端 Feature-Based + views/logics 分层；后端按应用边界拆分 app，领域能力集中在 packages

---

## 二、技术栈回顾

> 以[总体架构](../总体架构.md)为权威输入，摘要结构设计所需的关键选型上下文。

| 维度 | 选型 | 对结构的影响 |
|:---|:---|:---|
| 前端框架 | Taro 4.x（React 语法）+ Taro UI 3.x | 遵循 Taro 小程序目录范式；前端内部表现层（views/）与逻辑层（logics/）严格分离 |
| 前端状态管理 | Zustand 5.x | 轻量 store slice，归属逻辑层，按 feature 拆分 |
| 后端语言/框架 | Python / FastAPI 0.115+ | Router → Service → Repository 三层；`apps/api-server/` 仅含运行时入口与业务编排 |
| 数据校验 | Pydantic 2.x | 请求/响应 Schema 集中在 `packages/py-schemas/`，作为跨应用数据契约 |
| RAG 编排与检索 | LangChain 0.3+ | `packages/py-rag/` 封装检索、嵌入、切片；编排角色已按 ADR-007 移交 Pydantic AI，依赖逐步退出 |
| Agent 框架 | Pydantic AI 2.x（ADR-007） | `packages/py-agent/`（规划）承载统一 Agent 基座：运行时、工具注册中心、skill-loader |
| LLM 服务 | DeepSeek API v3 | 现状由 `packages/py-llm/` 封装；按 ADR-007 将由 `py-agent` 的模型层取代（py-llm 退役） |
| 嵌入模型 | 阿里 text-embedding-v4 | `packages/py-rag/embedding.py` 封装，输出 1024 维向量 |
| 关系型数据库 | PostgreSQL 17.x + pgvector 0.7+ | ORM 模型集中在 `packages/py-db/models/`；Alembic 迁移在 `packages/py-db/migrations/` |
| 缓存与队列 | Redis 7.x | `packages/py-cache/` 统一管理缓存/限流/轻量任务队列 |
| 对象存储 | MinIO | `packages/py-storage/` 封装 S3 兼容接口 |
| 认证鉴权 | JWT + RBAC + bcrypt | `packages/py-auth/` 提供 JWT 签发/校验、密码哈希、五级 RBAC |
| 部署方式 | Docker Compose v2 + Nginx 1.26+ | `infrastructure/` 集中管理部署资产；各 app 独立 Dockerfile |
| 包管理器 | **uv** (Python) + **pnpm** (Node.js) | **v2.0 新增**：双工作空间 `pyproject.toml` + `pnpm-workspace.yaml` |
| CI/CD | GitHub Actions | `.github/workflows/` |
| 后端测试 | pytest 8.x | 各 package 内 `tests/` + 根级集成测试 |
| 日志监控 | Prometheus + Grafana（可选 Loki） | `infrastructure/monitoring/` |
| 架构模式 | **Hybrid Monorepo（厚 package、薄 app）** | **v2.0 重构**：`packages/` 承载领域能力，`apps/` 仅含运行时入口与编排 |

---

## 三、设计原则

- **厚 package、薄 app**：领域模型、DTO、基础设施适配器集中在 `packages/`；app 仅包含 HTTP 路由、依赖注入、业务编排与中间件。新应用（如未来的 admin-web、独立 worker）可零成本复用已有能力包。
- **单向依赖**：应用层 → 共享能力层 → 工程支撑层。禁止反向依赖，禁止 app 之间直接 import。
- **前后端契约先行**：Pydantic Schema（`py-schemas`）与 TypeScript 类型（`ts-shared`）作为前后端数据契约，通过 workspace 协议引用。
- **前端表现/逻辑硬隔离**：views/ 禁止直接调用 API Service 或读写 Store，必须通过 Hooks 桥接；logics/ 禁止 import views/。这是整个前端架构中最严格、最有价值的解耦约束。
- **最小化可工作**：不为未规划的功能预留代码实现，仅在 `packages/` 和 `apps/` 中为明确规划的能力预留目录位置。

---

## 四、选定的结构模式

| 维度 | 选定模式 | 选择理由 | 参考来源 |
|:---|:---|:---|:---|
| 前端 | Taro Feature-Based + views/logics 分层 | 5 个业务功能模块边界清晰；views/logics 硬隔离保证组件可测试性与逻辑复用性（DS-006 决策维持） | patterns-by-stack.md §1 模式 A + 自订扩展 |
| 后端 | FastAPI Router → Service → Repository 三层 | 标准 Web 项目，领域复杂度适中；Service 编排 packages 能力，Repository 封装数据访问 | patterns-by-stack.md §3 模式 A |
| Monorepo | **Hybrid Monorepo（厚 package、薄 app）** | **v2.0 重构**：参考 SAP 项目结构，将领域模型、DTO、基础设施适配器抽入 `packages/`，apps 仅含运行时入口与编排；uv + pnpm 双工作空间管理双生态依赖 | patterns-by-stack.md §6 模式 A + SAP 实践 |
| Python 包 | flat-layout（各 package 内） | 仅作为应用运行（Docker 容器内），不需要 pip install 或发布到 PyPI | patterns-by-stack.md §7 |

> 模式组合：**"Taro Feature-Based（views/logics 分层） + FastAPI 三层 + Hybrid Monorepo（厚 package、薄 app）"**

---

## 五、分层架构

### 5.1 分层总览

本项目采用 **Hybrid Monorepo 三层架构**：顶层按构建与复用边界划分为三大横向层，应用内部再纵向分层。

| 层级 | 层名 | 职责 | 典型内容 | 技术组件 |
|:---:|:---|:---|:---|:---|
| L1 | 应用层 | 可独立构建运行的业务入口 | `apps/api-server/`、`apps/worker/`、`apps/mini-program/` | FastAPI, Taro + React, Celery（远期） |
| L2 | 共享能力层 | 跨应用复用的领域逻辑与基础设施适配 | `packages/py-*`、`packages/ts-shared/` | SQLAlchemy, Pydantic, Pydantic AI, LangChain, JWT, Redis, MinIO |
| L3 | 工程支撑层 | 部署、运维、配置、文档 | `infrastructure/`、`scripts/`、`docs/`、`docker-compose.yml` | Docker, Nginx, GitHub Actions |

### 5.2 应用内部分层（以 api-server 为例）

| 子层 | 子层名 | 职责 | 对应目录 |
|:---:|:---|:---|:---|
| L1-sub | 接口层 | 请求校验、路由分发、响应封装 | `apps/api-server/app/api/v1/`、`apps/api-server/app/dependencies/` |
| L2-sub | 业务层 | 用例编排、流程控制、权限校验 | `apps/api-server/app/services/` |
| — | 领域层 | 跨应用共享的实体、枚举、DTO、仓储 | `packages/py-db/models/`、`packages/py-db/repositories/`、`packages/py-schemas/` |
| — | 基础设施层 | 外部系统适配（Agent、RAG、Cache、Storage、Auth） | `packages/py-agent/`（规划）、`packages/py-rag/`、`packages/py-cache/`、`packages/py-storage/`、`packages/py-auth/` |

### 5.3 层间依赖规则

```
应用层 (L1)
  ├── mini-program ──── ts-shared (L2) ──► api-server (L1) ──► packages/py-* (L2)
  │                                                            ├── py-auth
  │                                                            ├── py-db
  │                                                            ├── py-schemas
  │                                                            ├── py-rag
  │                                                            ├── py-agent（规划，ADR-007）
  │                                                            ├── py-cache
  │                                                            ├── py-storage
  │                                                            ├── py-config
  │                                                            └── py-logger
  └── worker ───────── packages/py-* (L2) ──► Redis ◄── api-server
                           ├── py-rag
                           ├── py-agent（规划，ADR-007）
                           ├── py-db
                           ├── py-cache
                           └── py-config
```

**硬性约束**：

1. 依赖方向：应用层 → 共享能力层 → 工程支撑层（单向，禁止反向依赖）
2. 应用间禁止直接 import，必须通过 `packages/` 共享代码
3. `api-server` 和 `worker` 通过 Redis 队列实现异步解耦，禁止应用间直接 RPC 调用
4. 领域层（`py-db/models`、`py-schemas`）仅可被 L2 其他包和应用层引用，不可引用基础设施具体实现
5. 公共层（`py-config`、`py-logger`）可被任意层引用，不形成循环

---

## 文档地图

| 文档 | 唯一拥有的事实 |
|------|----------------|
| 本 README（§一~§五） | 项目基本信息、技术栈回顾、设计原则、结构模式、分层架构与层间依赖规则 |
| [目录骨架](./目录骨架.md)（§六） | 完整目录树、目录职责速查表 |
| [层间数据流与依赖](./层间数据流与依赖.md)（§七、§八） | 端到端数据流场景（应急咨询 SSE / 案例异步索引 / 认证授权）、模块间依赖关系（Mermaid） |
| [组织与工程约定](./组织与工程约定.md)（§九~§十二） | 命名规范、文件组织规则、模块边界、前端 views/logics 分层规则、特殊文件说明、测试与文档规划、扩展预留 |
| [附录](./附录.md)（§十三、§十四、附录 A/B） | 设计决策索引、最佳实践说明、技术栈映射速查、v1.0 → v2.0 迁移对照 |

