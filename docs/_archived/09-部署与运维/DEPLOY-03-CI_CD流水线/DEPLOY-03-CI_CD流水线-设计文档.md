## 1 功能点：DEPLOY-03 CI/CD流水线 — 设计文档（瘦身版）

> **文档生成时间**：2026-05-26 22:55:00
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 22:55:00 | AI Assistant | 初始版本：基于技术决策预研报告（.tmp/reports/tech-decision-report-DEPLOY-03.md）和已冻结的意图文档生成，整合 15 项已确定决策和 6 项待裁决矛盾 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `DEPLOY-03-CI_CD流水线-意图文档.md`（已冻结于 2026-05-26 22:48:42）
> - 本模块的精确编码规格见 `DEPLOY-03-CI_CD流水线-落地规范.md`

### 1.1 技术实现思路

本模块的核心任务是将项目的代码变更通过 GitHub Actions 自动化执行质量检查（lint + test + type check）、镜像构建和部署触发，形成从代码提交到可部署制品的完整交付流水线。

**为什么使用 GitHub Actions 而非 Jenkins 或 GitLab CI**：项目的代码仓库托管于 GitHub，技术栈设计文档 §2 已明确指定 CI/CD 平台为 GitHub Actions。GitHub Actions 的 Service Container 机制（在 Job 中启动 PostgreSQL/Redis 临时容器）天然满足 CI 测试对数据库和缓存的需求，无需额外维护独立的 CI 测试环境服务器。与 GitLab CI 相比无平台迁移成本；与 Jenkins 相比零运维负担——无需管理 Jenkins Master/Agent 节点。此决策直接受技术栈设计约束。

**两工作流文件的分段流水线设计**：`ci.yml` 和 `deploy.yml` 是两个独立的工作流文件，通过 `workflow_run` 事件串联而非单文件多 Job。这种分离设计有三重考量：(1) 职责分离——CI 负责质量验证，Deploy 负责制品产出，两个阶段的失败原因和排查路径完全不同；(2) 安全隔离——Deploy 工作流需要访问镜像仓库凭据和生产环境密钥，通过 GitHub Environment Protection Rules 可以限制 Deploy 仅在有有效 CI 结果时执行，且需要特定审批者批准；(3) 触发独立性——`workflow_dispatch` 允许开发者在 CI 意外跳过时手动触发部署，两个工作流各自拥有独立的失败重试入口。

**CI 内 lint-before-test 的串行设计**：后端 Job 中 `ruff check .` 在前、`pytest --cov` 在后是刻意为之的串行设计，非并行。原因是 lint 失败（3-5 秒即可完成）意味着代码风格违规，此时执行测试（1-3 分钟）是浪费 CI 分钟数。将 lint 和 test 放在同一 Job 而非两个 Job 的另一个原因：避免为 lint Job 单独启动服务容器——PostgreSQL 和 Redis 服务容器在 `services` 中定义，被整个 Job 的步骤共享，拆分会导致 lint 步骤要么多耗一个 runner（启动服务容器但不使用），要么需要额外的 if 条件跳过服务容器定义。

**前后端并行 Job 的独立失败策略**：前端和后端 Job 在 `ci.yml` 中平级定义（`jobs.backend` 和 `jobs.frontend`），GitHub Actions 自动并行执行。前端 TypeScript 类型检查失败不影响后端 Job 的结果，反之亦然。这种设计选择基于项目技术栈的现实：前端（Taro mini-program）和后端（FastAPI + Python）是完全异构的技术栈，各自的语言强类型系统已经提供了足够的编译期保障。强制耦合（如"前端失败则终止后端 Job"）反而引入不必要的串行等待。

**Deploy 的防护门控 `if` 条件**：Deploy 工作流中的 `if: github.event.workflow_run.conclusion == 'success' || github.event_name == 'workflow_dispatch'` 是双重防护：对自动触发（`workflow_run`），仅当 CI 结论为 `success` 时才执行；对手动触发（`workflow_dispatch`），允许绕过 CI 结论直接部署，用于紧急热修复和回滚场景。这是一个"安全默认 + 紧急逃生"的组合策略。

**镜像标签策略的改进方向**：当前 `deploy.yml` 使用默认标签 `latest`，但 `latest` 是可变指针（每次推送覆盖），无法追溯某次部署对应的代码提交。技术决策报告建议使用 `${GITHUB_SHA::7}` 短哈希作为镜像标签，这提供确定性的 commit-to-image 映射——一旦知道生产环境出现问题时的 commit，就可以立即定位到对应镜像并执行回滚。镜像标签格式的具体选择（SHA vs 语义版本号 vs 日期）取决于部署目标环境，在业务矛盾标记中作为待裁决项。

**Docker 构建复用 DEPLOY-01 的编排配置**：Deploy 工作流执行 `docker compose -f docker-compose.prod.yml build`，而非独立定义 `docker build` 命令序列。这种复用确保 CI/CD 中构建的镜像与本地开发和 DEPLOY-01 中定义的编排完全一致——Dockerfile 路径、构建上下文、构建参数（`--no-dev`、环境变量注入）均由 Compose 文件统一管理，CI/CD 流水线不重复定义，也不应绕过 Compose 文件直接执行 `docker build`。

**CI 测试环境隔离的保证机制**：后端 CI Job 通过 GitHub Actions `services` 声明启动临时 PostgreSQL 和 Redis 容器。这些容器随 Job 生命期创建和销毁——Job 开始前启动、Job 结束后自动回收。每次 CI 运行得到一个完全干净、可复现的测试环境，无跨运行状态污染。`DATABASE_URL` 和 `REDIS_URL` 环境变量通过 Job 级 `env` 注入，使用 `localhost` 端口映射（5432/6379）连接到服务容器。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：`docs/篝火智答-技术栈设计.md` §2（CI/CD 选型）、§6（部署与运维）；`docs/篝火智答-项目结构.md` §5.3（层间依赖规则）、§6.1（.github/workflows/ 目录骨架）；`docs/功能设计/09-部署与运维/DEPLOY-01-容器编排/DEPLOY-01-容器编排-设计文档.md`（v1.0）；`docs/功能设计/09-部署与运维/DEPLOY-02-反向代理路由/DEPLOY-02-反向代理路由-设计文档.md`（v1.0）；`docs/功能设计/09-部署与运维/DEPLOY-04-数据库迁移/DEPLOY-04-数据库迁移-设计文档.md`（v1.0）；`docs/功能设计/09-部署与运维/DEPLOY-05-环境配置管理/DEPLOY-05-环境配置管理-设计文档.md`（v1.0）；`docs/功能设计/_contracts.md`；`docs/功能设计/_sync-issues.md`。

- **兼容性结论**：
  - **无冲突**：本模块使用的工具链（uv 0.9.x、pnpm 10、ruff、pytest、Docker Compose）与技术栈设计 §2 完全一致。DEPLOY-01 设计文档 §1.2 已明确声明"本模块不负责镜像的构建时机和推送策略（归属 DEPLOY-03 CI/CD 流水线）"，两者职责边界清晰无重叠。Deploy 工作流引用 `docker-compose.prod.yml` 的路径与 DEPLOY-01 定义的编排文件位置一致。CI 中的迁移验证（alembic upgrade head）不重复编排——DEPLOY-01 的 `migration` 一次性服务已在 `docker-compose.prod.yml` 中处理 PostgreSQL 就绪 → 迁移执行 → 应用启动的依赖链。
  - **检查的存量规格**：已扫描 12 份已有落地规范（AUTH-01、AUTH-04、KNOW-01、OBS-01、SEC-01、SEC-04、SEC-05、DEPLOY-01、DEPLOY-02、DEPLOY-03、DEPLOY-04、DEPLOY-05），未发现与本模块的类型/接口/状态定义冲突。`_sync-issues.md` 中已追加 DEPLOY-03 一致性检查条目，标注"无冲突"。

- **复用的已有设计**：
  - DEPLOY-01 容器编排：`docker-compose.prod.yml`（镜像构建的编排配置源）、Dockerfile（各服务的多阶段构建定义）
  - DEPLOY-04 数据库迁移：`alembic upgrade head`（在 docker-compose.prod.yml migration 服务中编排）
  - QUAL-01 自动化测试：`pytest --cov` 命令约定和测试文件组织
  - 技术栈设计 §2：CI/CD 平台选型（GitHub Actions）、包管理器选型（uv/pnpm）

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| GitHub Actions | 平台依赖 | CI/CD 流程的编排与执行引擎。依赖其 workflow 定义语法、Job 调度器、Service Container 管理、Check Run 状态 API |
| Docker 引擎 | 工具依赖 | Deploy Job 在 runner 上调用 `docker compose build` 构建镜像。镜像构建过程和最终镜像均依赖 Docker 引擎 |
| DEPLOY-01 容器编排 | 配置源依赖 | 通过 `docker-compose.prod.yml` 获取镜像构建指令。不直接 import 或调用 DEPLOY-01 的代码——仅消费其产物（Compose 文件） |
| DEPLOY-04 数据库迁移 | 验证依赖 | CI 中通过包含 migration 服务的 Compose 编排间接验证迁移可执行性。不直接调用 Alembic CLI |
| QUAL-01 自动化测试 | 命令依赖 | CI 后端 Job 执行 `pytest --cov` 命令，依赖 QUAL-01 定义的测试文件和测试约定 |
| astral-sh/setup-uv@v3 | GitHub Action 依赖 | 在 runner 上安装 uv 0.9.x 包管理器，用于后续的 `uv sync` 和 `uv run` 命令 |
| pnpm/action-setup@v3 | GitHub Action 依赖 | 在 runner 上安装 pnpm 10 包管理器，用于后续的 `pnpm install` 和 `pnpm exec` 命令 |
| pgvector/pgvector:pg17 | CI 服务容器 | 后端 CI 测试的临时数据库，通过 Docker Hub 拉取，版本 pg17 与生产环境一致 |
| redis:7-alpine | CI 服务容器 | 后端 CI 测试的临时缓存，通过 Docker Hub 拉取，7-alpine 轻量镜像 |
| actions/checkout@v4 | GitHub Action 依赖 | 检出触发 CI/Deploy 的代码提交，Workflow Run 的代码入口 |

> 精确的 workflow YAML 结构、环境变量注入值、Docker Compose 命令参数见落地规范。

### 1.4 状态机设计（技术实现策略，如适用）

本功能点不涉及自定义状态机。

CI/CD 流水线的执行状态由 GitHub Actions 原生状态机管理：每个 Workflow Run 经历 `queued` → `in_progress` → `completed`（conclusion 为 `success`/`failure`/`cancelled`/`skipped`）。Deploy 工作流通过 `workflow_run` 事件的 `conclusion` 字段读取上游 CI 的最终状态，作为自身的门控条件。

流水线内的阶段顺序（lint → test → build）由 Job 内 `steps` 的线性执行顺序保证，非显式状态机——每个步骤的退出码决定后续步骤是否执行。这种"失败即止"的隐式状态管理在 CI/CD 领域是标准实践，无需引入业务状态层的额外复杂度。

### 1.5 设计原则兑现清单（技术视角）

| 原则 | 来源 | 技术响应 |
|------|------|----------|
| 单向依赖 | 项目结构 §3 设计原则第 2 条：应用层 → 共享能力层 → 工程支撑层，禁止反向依赖 | DEPLOY-03 作为 L3 工程支撑层（位于模块依赖分析的分层表 L3），出度依赖 DEPLOY-01（L2）和 DEPLOY-04（L1），均为向较低编号层的依赖。入度 0——没有业务模块依赖 CI/CD 流水线。不存在反向依赖。 |
| 最小化可工作 | 项目结构 §3 设计原则第 5 条：不为未规划的功能预留代码实现 | 当前 `ci.yml` 和 `deploy.yml` 仅包含已明确规划的 CI 阶段（lint + test + type check）和构建阶段。不为远期规划的部署策略（如蓝绿部署、金丝雀发布、K8s Helm Chart）预置步骤。部署占位符（`echo "Deployment step"`）明确标注"待配置"，不伪装成已有功能。 |
| 厚 package、薄 app | 项目结构 §3 设计原则第 1 条：领域逻辑集中 packages，app 仅含运行时入口 | 不直接适用——CI/CD 流水线是基础设施配置（YAML），不含 Python/TypeScript 代码。但其设计理念与此原则共鸣：流水线定义是"编排层"，实际测试逻辑在 QUAL-01、实际镜像构建逻辑在 DEPLOY-01 的 Dockerfile 中——流水线本身是薄编排而非厚实现。 |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| CI/CD 平台 | GitHub Actions（保持现状） | Jenkins（自托管）、GitLab CI（需迁移仓库） | 技术栈设计 §2 已锁定。无平台迁移成本，Service Container 机制原生支持 CI 测试环境 |
| CI 工作流文件结构 | **单文件双 Job**（`ci.yml` 含 backend + frontend） | 双文件（`ci-backend.yml` + `ci-frontend.yml`） | 前后端共享相同的触发条件（push/PR → main/master），单一文件减少配置重复。两个 Job 的并行执行由 GitHub Actions 自动管理，无需显式编排 |
| Deploy 触发方式 | **`workflow_run`（CI 完成） + `workflow_dispatch`（手动）** | `workflow_call`（可复用工作流）、仅 `push` 触发 | `workflow_dispatch` 提供紧急热修复和回滚的绕过路径。`workflow_call` 更适合 CI 内部步骤复用而非跨工作流触发 |
| lint 与 test 的位置 | **同一 Job 内串行步骤** | 两个独立 Job 并行执行 | lint 3-5 秒即可完成，失败后执行 test 浪费 CI 分钟数。同一 Job 共享服务容器避免为 lint 单独启动 PostgreSQL/Redis |
| 前端 CI 检查范围 | **`tsc --noEmit` + 建议增加 `Taro build --typecheck`**（待裁决） | 仅 `tsc --noEmit`、增加 ESLint、增加前端测试 | 仅类型检查能发现类型错误但无法暴露构建兼容性问题（webpack 打包、资源引用）。Taro 构建验证能弥补此缺口，但增加 CI 时间约 1-2 分钟 |
| 镜像标签策略 | **待裁决**（建议 `${GITHUB_SHA::7}`） | `latest`（当前）、语义版本号（Git Tag）、日期格式 | SHA 短哈希提供确定的 commit-to-image 映射，支持精确回滚。`latest` 无法追溯部署来源。语义版本号需要额外的 Git Tag 管理流程 |
| 镜像推送与部署 | **当前占位符（echo），待裁决部署目标** | SSH + docker-compose pull && up -d、K8s kubectl apply、Webhook 触发远程 | 部署方案取决于基础设施选择。在目标环境确定前，保留占位符而非预设特定方案，避免引入无效配置。受意图文档约束——意图文档 §实现观察 1/2 标记为 [推测] [待确认] |
| Docker 构建命令 | **`docker compose -f docker-compose.prod.yml build`** | `docker build -f Dockerfile.api .`（逐个构建） | 复用 DEPLOY-01 的 Compose 文件，确保 CI 构建的镜像与本地开发和生产部署的镜像构建参数完全一致。逐个 `docker build` 命令会绕开 Compose 的上下文和参数管理 |
| CI 缓存策略 | **当前无缓存，待裁决是否引入** | `actions/cache@v4`（缓存 pip/pnpm 依赖） | 无缓存方案简单可靠——每次 CI 都是干净的依赖安装，无缓存失效调试成本。引入缓存可显著缩短 CI 时间（3-5 分钟降至 1-2 分钟），但需维护 cache key 策略（基于 lock 文件哈希） |

### 1.7 注意事项与禁止行为（设计层面）

1. **[约束 1]** CI 服务容器的 PostgreSQL 镜像必须是 `pgvector/pgvector:pg17`——项目使用 pgvector 扩展，纯 `postgres:17` 镜像不包含向量检索能力，测试中的 pgvector 相关查询会失败。此约束由技术栈设计 §2 PostgreSQL 选型决定。

2. **[约束 2]** `DATABASE_URL` 必须使用 `postgresql+asyncpg://` 协议前缀（SQLAlchemy 2.0 async 驱动），使用同步前缀 `postgresql://` 会导致测试连接失败。此易错点已在落地规范中标注。

3. **[约束 3]** Docker 构建命令必须使用 `-f docker-compose.prod.yml` 指定生产编排文件——`docker compose build`（无 `-f`）会使用默认的 `docker-compose.yml`（dev 配置），导致镜像构建参数不一致。

4. **[设计边界 1]** 本模块不负责 Docker 镜像的 Dockerfile 内容——Dockerfile 归 DEPLOY-01 容器编排模块定义。CI/CD 流水线仅调用构建命令，不修改 Dockerfile 中的构建步骤、基础镜像版本或依赖安装命令。

5. **[设计边界 2]** 本模块不负责数据库迁移逻辑——迁移执行由 DEPLOY-04 的 Alembic 脚本和 migration 服务编排负责。CI/CD 仅在需要时通过包含 migration 服务的 Compose 编排间接验证迁移可执行性。

6. **[设计边界 3]** 本模块不负责测试内容的定义——测试文件、覆盖率目标、测试策略归 QUAL-01 自动化测试模块定义。CI 仅执行 `pytest --cov` 命令。

7. **[设计边界 4]** 本模块不负责部署目标环境的服务器配置——部署目标的基础设施（云服务器、域名、SSL 证书、防火墙、负载均衡）归运维层面而非 CI/CD 模块。CI/CD 仅产出可部署制品（Docker 镜像），部署动作的具体实现待基础设施确定后对接。

8. **[禁止行为 1]** 禁止在 `.github/workflows/*.yml` 中硬编码生产环境凭据（镜像仓库密码、SSH 私钥、API Token）。所有凭据必须通过 GitHub Secrets（`${{ secrets.* }}`）注入，机密引用不得出现在 Workflow 日志中（使用 `mask` 或日志过滤）。

9. **[禁止行为 2]** 禁止绕过 Compose 文件直接执行 `docker build` 或 `docker push`——这会绕开 DEPLOY-01 定义的构建上下文和构建参数，导致 CI 构建的镜像与生产环境不一致。

10. **[禁止行为 3]** 禁止在 CI 工作流中执行生产环境部署动作（如 `docker compose up -d` 到生产服务器）。CI runner 是临时执行环境，不应具有生产服务器的 SSH 访问权限。部署动作应在 Deploy 工作流中通过安全凭据和环境隔离后执行。

11. **[禁止行为 4]** 禁止以"部署目标后续再配置"为由长期保留部署占位符而不推进镜像推送目标（registry）和生产部署目标的确定。当前占位符是临时状态——建议在业务矛盾标记 #1 和 #2 得到裁决后的首次交付中移除。

### 1.8 引用：配套意图文档

- **意图文档**：`DEPLOY-03-CI_CD流水线-意图文档.md`
- **冻结时间**：`2026-05-26 22:48:42`
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。意图文档中标注为 [推测][待确认] 的 5 项部署目标相关项，本设计文档未做技术假设，均在"架构权衡与备选方案"中标记为待裁决。已确定的 CI 流程（push/PR 触发、lint + test + type check、Docker 构建）与意图文档的验收标准 AC-01 至 AC-08 完全对齐。如有歧义，以意图文档为准。

---

**待裁决矛盾提醒**（来自技术决策报告，需用户确认）：

1. **镜像推送目标**：当前 `docker push` 被注释。需确定镜像仓库（Docker Hub / 阿里云 ACR / 腾讯云 TCR）
2. **部署目标环境**：当前部署步骤为占位符。需确定目标（云服务器 Docker Compose / K8s / 暂保留）
3. **覆盖率门禁阈值**：当前 `--cov` 已配置但无 `--cov-fail-under`。建议 70%
4. **前端 ESLint 检查**：是否增加 ESLint。当前仅 `tsc --noEmit`
5. **镜像标签格式**：`${GITHUB_SHA::7}` vs 语义版本号 vs 日期格式
6. **CI 缓存策略**：是否使用 `actions/cache` 加速依赖安装
