# 篝火智答 (Campfire-AI) — MVP 差距分析报告

> 生成日期：2026-05-27  
> 评估范围：全项目代码、设计文档、基础设施、测试体系  
> 评估标准：MVP = 微信小程序端用户可完成「注册 → 建档 → 应急咨询 → 接收流式方案 → 查看历史」完整闭环，且后端服务可容器化部署运行

---

## 一、执行摘要

**结论：本项目当前处于「后端核心模块大量实现、前端几乎空白、系统无法启动」的状态，距离 MVP 跑通仍有显著差距。**

| 维度 | 完成度（估） | 关键判断 |
|:---|:---|:---|
| **产品设计与技术规格** | ~90% | 功能模块全拆解、意图文档、设计文档、落地规范、API 契约均已完备 |
| **后端共享能力层 (packages)** | ~65% | 9 个 Python 共享包中，py-rag / py-db / py-auth / py-schemas 实现较深入；py-llm / py-cache / py-storage / py-security 有基础骨架但待扩展 |
| **后端应用层 (api-server)** | ~45% | 大量 Service / Router 文件存在且代码质量较高，但 **FastAPI 入口 `main.py` 为空文件**，系统无法启动；部分路由未注册 |
| **前端小程序 (mini-program)** | ~8% | 仅有 1 个纯 UI 组件（`CaseFormView.tsx`）和少量 Hooks/Service 文件；**无 Taro 框架依赖、无页面路由、无应用入口** |
| **后台异步 Worker** | ~5% | 目录结构存在，但 `case_indexer.py` 为空；任务队列消费循环缺失 |
| **数据库迁移 (Alembic)** | ~20% | 仅 2 个迁移脚本（`case_chunks` / `consultations`）；核心表 `users`、`profiles`、`cases`、`tickets`、`knowledge_articles` 等无迁移 |
| **部署与运维基础设施** | ~55% | Docker Compose（开发+生产）、Dockerfile.api、CI/CD 流水线、基础 nginx.conf 已具备；**nginx 站点配置缺失、Worker Dockerfile 未验证、生产 SSL 配置缺失** |
| **测试与质量保障** | ~15% | 大量对抗性测试已生成但**多数未通过**（存在多轮 `test-defects` 记录）；无根级集成/E2E 测试；无 green-seeking 通过报告 |

**MVP 当前状态：不可运行。** 即便忽略前端，仅后端也无法通过 `uvicorn app.main:app` 启动，因为 `apps/api-server/app/main.py` 是 0 字节空文件。

---

## 二、MVP 关键路径定义

依据 `docs/references/需求分析.md` 与 `docs/篝火智答-技术栈设计.md`，MVP 必须打通以下**最小用户闭环**：

```
[微信小程序端]                              [后端服务]
    │                                           │
    ├─ 1. 用户注册 / 登录 ─────────────────────►├─ AUTH-01 / AUTH-02 / AUTH-04
    │                                           │
    ├─ 2. 创建/编辑个人档案 ───────────────────►├─ PROF-01 / PROF-02
    │                                           │
    ├─ 3. 输入行为描述 → 提交应急咨询 ─────────►├─ CSLT-01 / CSLT-02 / CSLT-03
    │                                           │   → RAG 检索 + LLM 生成
    │◄─ 4. 接收 SSE 流式应急方案 ──────────────├─ CSLT-04 / CSLT-08
    │                                           │
    ├─ 5. 查看咨询历史 ────────────────────────►├─ CSLT-06
    │                                           │
    └─ 6. （专家端）提交案例 → 审核 ───────────►├─ CASE-01 / CASE-03 / CASE-04
                                                │   → Worker 异步索引入库
```

**MVP 外延（P1/P2 可延期）**：
- 人工兜底通道（TICK 全部模块）
- 科普查阅（KNOW 全部模块）
- 案例版本迭代 / 淘汰管理（CASE-05 / CASE-06）
- 模板提炼生成（CASE-07）
- 专业评估补充（PROF-04）
- 完整监控告警体系（Prometheus + Grafana）
- RAG 质量评估流水线（QUAL-02）

---

## 三、逐层差距分析

### 3.1 后端共享能力层 (packages/)

| 包名 | 状态 | 差距说明 |
|:---|:---|:---|
| `py-config` | 🟡 基础可用 | 配置读取、异常层级、安全配置已实现；未覆盖全部环境变量校验（如 MinIO、限流阈值组合校验） |
| `py-db` | 🟡 较完整 | ORM 模型覆盖 User、Profile、Case、Consultation、CaseChunk、Review；**缺少 Ticket、KnowledgeArticle、EventLog 模型**；Repository 层实现较全但缺少事务封装；Alembic 迁移脚本仅 2 个 |
| `py-schemas` | 🟡 较完整 | Pydantic DTO 覆盖 auth、cases、consult、profiles、streaming；**缺少 tickets、knowledge、历史记录 Schema**；安全校验层（file_validator、sanitizer）有实现 |
| `py-rag` | 🟢 核心就绪 | `hybrid_search()` 混合检索引擎（508 行）实现深入，含降级策略、超时保护、时效衰减、循证加权；`embedding.py` 封装 DashScope；索引服务（chunk_builder、index_writer、worker）有骨架 |
| `py-llm` | 🟡 有骨架 | `client.py` 封装 DeepSeek API；**缺少熔断降级、多模型切换（通义千问备用）、Token 用量追踪** |
| `py-auth` | 🟢 核心就绪 | JWT 签发/解析/校验、密码哈希（bcrypt）、五级 RBAC、Token 黑名单均实现；有对抗性测试但未完全通过 |
| `py-cache` | 🟡 有骨架 | `rate_limit.py` 限流实现；**缺少通用缓存封装、Redis 队列任务投递/消费封装** |
| `py-storage` | 🟡 有骨架 | `file_security.py` 文件类型白名单；**缺少 MinIO 预签名 URL 生成、上传下载封装** |
| `py-logger` | 🟢 可用 | 结构化 JSON 日志、trace_id 上下文、FastAPI 中间件均实现 |
| `py-security` | 🟡 有骨架 | `pii_detector.py` PII 检测实现；**缺少自动脱敏替换逻辑、HTML 实体转义（XSS 防护）** |
| `py-infra` | 🟡 有骨架 | 异常定义、模型基类；内容较薄 |
| `py-health` | 🟢 可用 | PostgreSQL / Redis / MinIO 连通性检查、健康状态机、连续失败计数均实现 |
| `ts-shared` | 🟡 起步 | 仅导出 cases / profiles 枚举和类型；**缺少 auth、consult、tickets、knowledge 的共享类型** |

**本层主要缺口**：
1. **模型缺失**：Ticket、KnowledgeArticle、EventLog、ConsultationLog 等 ORM 模型未定义
2. **迁移缺失**：Alembic 仅 2 个脚本，远不足以支撑完整业务 schema
3. **缓存/队列薄弱**：Redis 仅实现了限流，未封装通用缓存读写和任务队列
4. **LLM 客户端单薄**：无熔断、无 Token 追踪、无备用模型切换

### 3.2 后端应用层 (apps/api-server/)

| 模块域 | 文件存在性 | 实现深度 | 差距说明 |
|:---|:---|:---|:---|
| **应用入口** | `app/main.py` | ❌ **空文件（0 字节）** | **致命阻塞**：FastAPI 实例未创建，路由未注册，lifespan 未定义，中间件未挂载 |
| **健康检查** | `api/v1/health.py` | 🟢 完整 | `/health`、`/ready` 及版本化别名均实现，调用 py_health 检查器 |
| **用户认证** | `api/v1/auth.py` | 🟡 有实现 | 注册端点实现，依赖注入链完整；**登录、Token 续期端点未确认是否在同一文件或缺失** |
| **应急咨询** | `api/v1/consult/stream.py` | 🟡 有实现 | SSE 流式端点实现，含 session_id 校验、Last-Event-Id 续传；**缺少主咨询提交端点（触发 RAG + LLM 的 POST 端点）** |
| **档案管理** | `api/v1/profiles.py` | 🟡 有实现 | 文件存在，未深入审阅具体完成度 |
| **案例管理** | `api/v1/cases.py` | 🟡 有实现 | 文件存在；审核相关路由在 `reviews.py` |
| **咨询历史** | `api/v1/consultations.py` | 🟡 有实现 | 文件存在 |
| **Service 层** | `services/` 下多个文件 | 🟡 较深入 | `consult_service`、`auth_service`、`case_service`、`profile_service`、`review_service` 均存在；危机分级、应急方案生成、SSE 流式、置信度校验、关键词扫描等子模块代码量充足 |
| **中间件** | `middleware/` | 🟡 部分 | 限流、校验处理器实现；**CORS、审计日志、PII 检测中间件未实现或未完成** |
| **依赖注入** | `dependencies/` | 🟡 部分 | auth_dependencies 实现；db_deps、consult_deps 未确认 |

**本层主要缺口**：
1. **`main.py` 为空** → 后端完全无法启动（阻塞级）
2. 路由注册状态不明 → 即使 `main.py` 补全，也需确认各 `api/v1/*.py` 是否被正确挂载
3. 缺少若干端点：如 `POST /api/v1/consult`（主咨询触发）、`POST /api/v1/auth/login`、`POST /api/v1/auth/refresh`
4. 全局异常处理器（`app/exceptions.py` 存在但需确认是否被 main.py 引用）

### 3.3 前端小程序 (apps/mini-program/)

| 评估项 | 状态 | 说明 |
|:---|:---|:---|
| **框架依赖** | ❌ 缺失 | `package.json` 中**无 `@tarojs/*` 依赖**，仅有 React / TypeScript / Vitest / Zustand。项目**不是可构建的 Taro 小程序** |
| **应用入口** | ❌ 缺失 | 无 `app.tsx`、无 `app.config.ts`、无 `project.config.json`（微信小程序项目配置） |
| **页面路由** | ❌ 缺失 | `views/*/pages/` 目录存在但**无任何页面文件**（`.tsx` / `.ts`） |
| **UI 组件** | 🟡 极少量 | 仅 `views/cases/CaseFormView.tsx` 一个完整组件；`views/shared/components/` 下有 Button / Input / Loading / Modal / Toast / Empty 目录但**内容未确认** |
| **逻辑层** | 🟡 起步 | `logics/` 下各模块目录结构齐全，有 hooks / services / store / types；`useConsult.ts`、`httpClient.ts`、`tokenManager.ts` 等存在但深度待验证 |
| **状态管理** | 🟡 起步 | Zustand store 文件存在（`consultStore`、`profileStore`、`caseStore`、`userStore`），实现深度待验证 |

**本层主要缺口**：
1. **项目本质上还不是 Taro 工程** → 需要重新初始化或补充全部 Taro 依赖与配置
2. **无任何可路由页面** → 用户无法看到任何界面
3. **前后端联调未开始** → 前端 API Service 是否与实际后端接口对齐未知
4. **缺失小程序特有能力**：微信登录（`wx.login`）、Storage API、订阅消息等均未封装

### 3.4 后台 Worker (apps/worker/)

| 评估项 | 状态 | 说明 |
|:---|:---|:---|
| `main.py` | ❌ 缺失/空 | Worker 入口（Redis 队列消费循环）未实现 |
| `tasks/case_indexer.py` | ❌ 空文件 | 案例切片 + 向量化 + pgvector 入库的核心异步任务为空 |
| `Dockerfile.worker` | 🟡 存在 | 文件存在，未审阅内容 |

**缺口**：Worker 完全不可用。案例审核通过后无法触发向量化入库，RAG 检索将永远命中空库。

### 3.5 数据库迁移 (packages/py-db/migrations/)

| 表/模块 | 迁移脚本存在？ | 说明 |
|:---|:---|:---|
| `case_chunks` | ✅ `20260527_093200_create_case_chunks.py` | 向量切片表 |
| `consultations` | ✅ `20260527_211308_create_consultations.py` | 咨询记录表 |
| `users` | ❌ 缺失 | 认证核心表 |
| `profiles` | ❌ 缺失 | 个性化档案表 |
| `cases` | ❌ 缺失 | 真实案例元数据表 |
| `tickets` | ❌ 缺失 | 工单表 |
| `knowledge_articles` | ❌ 缺失 | 科普文章表 |
| `events` / `event_logs` | ❌ 缺失 | 事件记录表 |
| `teacher_links` | ❌ 缺失 | 家属-老师关联表 |

**缺口**：迁移覆盖率约 20%。新环境 `alembic upgrade head` 后仅能得到 2 张表，远不足以支撑业务运行。

### 3.6 部署与运维基础设施

| 评估项 | 状态 | 说明 |
|:---|:---|:---|
| `docker-compose.yml`（开发） | 🟢 完整 | PostgreSQL + Redis + MinIO 编排合理，健康检查配置齐全 |
| `docker-compose.prod.yml`（生产） | 🟢 较完整 | 含 api-server、worker、nginx、migration 服务，资源限制、依赖条件、健康探针均配置 |
| `Dockerfile.api` | 🟢 完整 | 多阶段构建，uv 包管理，体积控制合理 |
| `Dockerfile.worker` | 🟡 存在 | 未审阅 |
| `nginx.conf` | 🟡 基础 | 主配置存在，JSON 日志格式、Gzip、upstream 配置合理；**缺少 `conf.d/campfire.conf` 站点配置（SSL、API 代理路由、静态资源）** |
| `.github/workflows/ci.yml` | 🟢 完整 | 后端 pytest + ruff，前端 tsc type check，服务容器配置齐全 |
| `.github/workflows/deploy.yml` | 🟡 存在 | 未审阅 |
| `.env.example` | 🟢 完整 | 覆盖全部关键配置项 |

**缺口**：
1. nginx 站点配置缺失 → 生产环境 HTTPS 终端和 API 代理无法工作
2. SSL 证书路径未配置 → 生产部署后无法提供 HTTPS
3. Worker 镜像构建未验证

### 3.7 测试与质量保障

| 评估项 | 状态 | 说明 |
|:---|:---|:---|
| 对抗性测试（盲测） | 🟡 大量生成 | 覆盖 AUTH-01/04/06、CASE-01/03/04/09、CSLT-01/02/03/04/05/06、DEPLOY-01/02/04/05、OBS-01/04、PROF-01/03/05、SEC-01/04/05 等模块；**普遍存在多轮 test-defects（round-1/2/3），说明实现未通过对抗验证** |
| 单元测试 | 🟡 少量 | 各 package `tests/` 目录存在，但内容未深入审阅 |
| 集成测试 | ❌ 缺失 | `tests/`（根级）无任何 `.py` 文件；`apps/api-server/tests/` 目录存在但内容未知 |
| E2E 测试 | ❌ 缺失 | 无 |
| 覆盖率报告 | ❌ 缺失 | CI 中配置了 `--cov`，但因 main.py 为空等原因，当前无法跑通全量测试 |

---

## 四、阻塞性缺口清单（无法启动/运行的致命问题）

以下问题**必须全部解决**才能进入可运行状态：

| # | 问题 | 影响 | 紧急度 |
|:---|:---|:---|:---|
| 1 | **`apps/api-server/app/main.py` 为空** | FastAPI 应用无法实例化，后端服务完全无法启动 | 🔴 P0 |
| 2 | **前端不是 Taro 工程** | 无 `@tarojs` 依赖、无应用入口、无页面，小程序无法编译预览 | 🔴 P0 |
| 3 | **Worker `case_indexer.py` 为空** | 案例无法向量化入库，RAG 检索永为空结果 | 🔴 P0 |
| 4 | **Alembic 迁移脚本严重缺失** | 新环境仅 2 张表，所有业务 CRUD 都会报 `relation does not exist` | 🔴 P0 |
| 5 | **nginx 站点配置 `conf.d/campfire.conf` 缺失** | 生产环境无 API 代理和 HTTPS 终端 | 🟡 P1 |
| 6 | **缺少主咨询触发端点** | 仅实现了 SSE 流式推送端点，缺少用户提交行为描述后触发 RAG+LLM 的 POST 端点 | 🔴 P0 |

---

## 五、非阻塞性但高价值缺口

| # | 问题 | 影响 | 建议优先级 |
|:---|:---|:---|:---|
| 7 | 前端页面全部缺失（仅 1 个组件） | 用户无界面可操作 | P0（与 #2 同步解决） |
| 8 | 对抗性测试大量未通过 | 代码存在边界漏洞，质量未收敛 | P1 |
| 9 | LLM 客户端无熔断/备用模型 | DeepSeek 故障时服务完全不可用 | P1 |
| 10 | Token 用量追踪缺失 | 无法监控成本，超预算无告警 | P1 |
| 11 | 案例库为空时无种子数据/通用模板 | 冷启动用户体验极差 | P1 |
| 12 | 微信小程序登录（wx.login）未实现 | MVP 当前使用用户名密码，与小程序生态割裂 | P2（可后延） |
| 13 | 科普查阅、工单兜底通道 | MVP 可延期功能 | P2 |
| 14 | Prometheus/Grafana 监控未实际部署 | 可观测性不足 | P2 |
| 15 | RAG 质量评估流水线（QUAL-02） | 无自动化基准评估 | P2 |

---

## 六、模块级完成度矩阵（MVP 相关模块）

依据 `docs/功能设计/功能模块全拆解.md` 中的 56 个模块，仅评估 MVP 范围内（P0 + 必要基础设施）的模块：

| 模块编号 | 模块名称 | 设计状态 | 实现状态 | 测试状态 | 评级 |
|:---|:---|:---|:---|:---|:---|
| AUTH-01 | 用户注册 | ✅ 完成 | 🟡 有代码 | 🟡 对抗测有缺陷 | 🟡 |
| AUTH-02 | 用户登录 | ✅ 完成 | ⚪ 未确认 | ⚪ 未开始 | 🔴 |
| AUTH-03 | Token 续期 | ✅ 完成 | ⚪ 未确认 | ⚪ 未开始 | 🔴 |
| AUTH-04 | 五级 RBAC 鉴权 | ✅ 完成 | 🟡 有代码 | 🟡 对抗测有缺陷 | 🟡 |
| AUTH-05 | 登录注册界面 | ✅ 完成 | ❌ 无页面 | ❌ 无 | 🔴 |
| AUTH-06 | 认证会话管理 | ✅ 完成 | 🟡 前端部分 | 🟡 对抗测有缺陷 | 🔴 |
| CSLT-01 | 危机分级判定 | ✅ 完成 | 🟢 较完整 | 🟡 对抗测有缺陷 | 🟡 |
| CSLT-02 | RAG 语义检索 | ✅ 完成 | 🟢 较完整 | 🟡 对抗测有缺陷 | 🟡 |
| CSLT-03 | 应急方案生成 | ✅ 完成 | 🟢 较完整 | 🟡 对抗测有缺陷 | 🟡 |
| CSLT-04 | 流式应答推送 | ✅ 完成 | 🟢 较完整 | 🟡 对抗测有缺陷 | 🟡 |
| CSLT-05 | 置信度后校验 | ✅ 完成 | 🟡 有代码 | 🟡 对抗测有缺陷 | 🟡 |
| CSLT-06 | 咨询历史管理 | ✅ 完成 | 🟡 有代码 | 🟡 对抗测有缺陷 | 🟡 |
| CSLT-07 | 应急咨询界面 | ✅ 完成 | ❌ 无页面 | ❌ 无 | 🔴 |
| CSLT-08 | 咨询编排逻辑 | ✅ 完成 | 🟡 前端部分 | ⚪ 未开始 | 🔴 |
| PROF-01 | 个人档案管理 | ✅ 完成 | 🟡 有代码 | 🟡 对抗测有缺陷 | 🟡 |
| PROF-02 | 档案驱动检索过滤 | ✅ 完成 | 🟡 部分（在 RAG 层） | ⚪ 未开始 | 🟡 |
| PROF-03 | 事件记录管理 | ✅ 完成 | ⚪ 未确认 | 🟡 对抗测有缺陷 | 🔴 |
| PROF-05 | 档案隐私控制 | ✅ 完成 | 🟡 部分（RBAC 层） | 🟡 对抗测有缺陷 | 🟡 |
| PROF-06 | 档案管理界面 | ✅ 完成 | ❌ 无页面 | ❌ 无 | 🔴 |
| PROF-07 | 档案数据逻辑 | ✅ 完成 | 🟡 前端部分 | ⚪ 未开始 | 🔴 |
| CASE-01 | 案例录入管理 | ✅ 完成 | 🟡 有代码 | 🟡 对抗测有缺陷 | 🟡 |
| CASE-03 | 案例审核工作流 | ✅ 完成 | 🟡 有代码 | 🟡 对抗测有缺陷 | 🟡 |
| CASE-04 | 案例向量化入库 | ✅ 完成 | ❌ Worker 为空 | 🟡 对抗测有缺陷 | 🔴 |
| CASE-08 | 案例管理界面 | ✅ 完成 | ❌ 仅 1 个组件 | ❌ 无 | 🔴 |
| CASE-09 | 案例管理逻辑 | ✅ 完成 | 🟡 前端部分 | 🟡 对抗测有缺陷 | 🔴 |
| OBS-01 | 结构化日志 | ✅ 完成 | 🟢 可用 | 🟡 对抗测有缺陷 | 🟡 |
| OBS-04 | 健康检查 | ✅ 完成 | 🟢 可用 | 🟡 对抗测有缺陷 | 🟡 |
| SEC-01 | 传输存储安全 | ✅ 完成 | 🟡 部分 | 🟡 对抗测有缺陷 | 🟡 |
| SEC-04 | 防刷限流 | ✅ 完成 | 🟡 有代码 | 🟡 对抗测有缺陷 | 🟡 |
| SEC-05 | 输入校验防护 | ✅ 完成 | 🟡 有代码 | 🟡 对抗测有缺陷 | 🟡 |
| DEPLOY-01 | 容器编排 | ✅ 完成 | 🟢 较完整 | 🟡 对抗测有缺陷 | 🟡 |
| DEPLOY-02 | 反向代理路由 | ✅ 完成 | 🟡 基础配置 | 🟡 对抗测有缺陷 | 🟡 |
| DEPLOY-04 | 数据库迁移 | ✅ 完成 | ❌ 仅 2 个脚本 | 🟡 对抗测有缺陷 | 🔴 |
| DEPLOY-05 | 环境配置管理 | ✅ 完成 | 🟢 较完整 | 🟡 对抗测有缺陷 | 🟡 |
| QUAL-01 | 自动化测试 | — | ❌ 无集成/E2E | ❌ 无 | 🔴 |

**评级说明**：
- 🟢 模块核心功能已就绪，可进入联调
- 🟡 模块有实质性代码，但存在已知缺陷或待补全边界
- 🔴 模块缺失关键实现，当前不可用
- ⚪ 未开始或无法确认

---

## 七、剩余工作量估算

基于 1-3 人小团队、每日有效编码 4-6 小时的假设：

| 工作包 | 预估工期 | 前置依赖 | 说明 |
|:---|:---|:---|:---|
| 1. 补全 Alembic 迁移脚本（全部核心表） | 1-2 天 | 无 | 基于现有 ORM 模型生成迁移，补充缺失模型 |
| 2. 实现 `api-server/app/main.py` 及路由注册 | 0.5-1 天 | #1 | FastAPI 实例、lifespan、中间件挂载、全局异常处理 |
| 3. 补全缺失的后端 API 端点（login/refresh/consult-post 等） | 2-3 天 | #2 | 连接已有 Service 层 |
| 4. 实现 Worker 案例索引任务 | 2-3 天 | #1 | 切片、向量化、pgvector 写入、失败重试 |
| 5. 前端 Taro 工程初始化 + 核心页面（6-8 个） | 5-7 天 | 无 | 注册/登录、档案、咨询、历史、案例提交、案例列表 |
| 6. 前端 Hooks / Services 对齐后端接口 | 3-4 天 | #5, #3 | httpClient、Token 管理、SSE 消费、状态管理 |
| 7. 前后端联调 + Bug 修复 | 3-5 天 | #3, #6 | 端到端打通注册→建档→咨询→流式输出 |
| 8. 对抗性测试修复（多轮缺陷收敛） | 3-5 天 | #7 | 按 adversarial-test 失败摘要逐条修复 |
| 9. 数据库种子数据 + 通用模板 | 1-2 天 | #1 | 冷启动体验保障 |
| 10. 生产 nginx 站点配置 + SSL | 0.5-1 天 | 无 | 可并行 |
| 11. Docker 全量构建验证 + 部署文档 | 1-2 天 | #1, #4, #10 | 端到端容器编排验证 |
| 12. 集成测试编写（核心路径） | 2-3 天 | #7 | pytest 覆盖注册→咨询→历史 |

**总估算**：约 **24-38 天**（纯工程工作量，不含需求变更、设计评审、微信审核等待时间）。

若团队仅 1 人全职，预计 **6-8 周** 可达 MVP 可演示状态；若 2-3 人并行（前后端分工），预计 **3-5 周**。

---

## 八、推荐优先级与路线图

### Phase 1：让后端先跑起来（第 1-2 周）
1. 补全 Alembic 迁移脚本（所有核心表）
2. 实现 `main.py` + 路由注册 + 全局异常处理
3. 补全缺失 API 端点（login、refresh、consult POST）
4. 实现 Worker 案例索引任务
5. Docker Compose 全量启动验证（`docker compose up` 成功）

### Phase 2：让前端看得见（第 2-4 周）
6. Taro 工程初始化（`pnpm create taro` 或补充依赖）
7. 核心页面开发：登录/注册、档案编辑、应急咨询主界面、咨询历史
8. 前端 SSE 流式消费联调
9. 前后端接口对齐与 Bug 修复

### Phase 3：质量收敛（第 4-5 周）
10. 对抗性测试缺陷修复（至少通过 MVP 模块的 green-seeking）
11. 种子数据导入 + 冷启动体验优化
12. 核心路径集成测试编写

### Phase 4：部署就绪（第 5-6 周）
13. nginx 站点配置 + SSL
14. 生产 Docker Compose 验证
15. CI/CD 跑通（GitHub Actions 绿链）

---

## 九、结论与建议

### 9.1 核心结论

本项目在**设计文档**和**后端核心算法/服务**层面投入了大量高质量工作，尤其是：
- RAG 混合检索引擎（CSLT-02）
- 危机分级判定管道（CSLT-01）
- 应急方案生成与 Prompt 工程（CSLT-03）
- 认证鉴权体系（AUTH 系列）
- 结构化日志与健康检查（OBS 系列）

这些代码体现了良好的工程规范（类型注解、依赖注入、结构化日志、Pydantic 校验）。

然而，项目当前面临**「头重脚轻」**的困境：
- **底层设计重**：文档完备、架构清晰、模块边界明确
- **中层实现偏**：后端 packages 较全，但 api-server 入口断裂
- **上层交付轻**：前端几乎空白，Worker 为空，迁移残缺

**当前项目不可运行，距离 MVP 至少需要 3-6 周的密集工程投入。**

### 9.2 关键建议

1. **立即修复阻塞性问题**：`main.py`、Alembic 迁移、Worker 空文件是首要任务，它们决定了系统是否能从「代码集合」变为「可运行服务」。

2. **前端需要重新评估技术栈落地**：当前 `mini-program` 目录缺少 Taro 核心依赖，建议确认是否计划使用 Taro 4.x 还是已变更方案。若维持 Taro，需尽快初始化工程骨架。

3. **优先打通「咨询闭环」**：在全部功能并行开发前，优先集中资源让「注册 → 建档 → 咨询 → 流式输出」这一核心链路端到端跑通，再向外扩展案例库、历史记录等功能。

4. **利用已完善的对抗性测试资产**：项目中已生成大量对抗性测试用例和缺陷报告（`test-defects-round-N.md`），建议按模块优先级逐条消化修复，而非重新写测试。

5. **冷启动体验需提前准备**：RAG 系统的价值依赖案例库质量，建议在工程开发的同时，并行准备 20-50 条种子案例（即使为专家撰写的模板案例），否则 MVP 上线时 AI 输出将缺乏真实案例支撑。

---

*本报告基于 2026-05-27 的代码库快照生成。随着开发推进，建议每两周更新一次差距评估。*
