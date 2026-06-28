# 功能点：DEPLOY-03 CI/CD流水线 — 落地规范

> **文档生成时间**：2026-05-26 23:05:08
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 22:34:57 | AI Assistant（code-reverse-engineering-writer） | 初始版本（从代码逆向推导） |
> | v2.0 | 2026-05-26 23:05:08 | AI Assistant（module-spec-writer） | 基于已确认设计文档v1.0和契约协调报告（0冲突），重组为对外接口/对内实现章节，新增契约消费声明 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `DEPLOY-03-CI_CD流水线-设计文档.md`（v1.0，用户已确认通过）。

---

## 1.1 技术栈绑定 【对内实现】

- **必须使用**：
  - `ubuntu-latest` — CI runner 操作系统
  - `actions/checkout@v4` — GitHub 官方 checkout Action
  - `astral-sh/setup-uv@v3` — uv 包管理器安装，版本 `0.9.x`
  - `pnpm/action-setup@v3` — pnpm 包管理器安装，版本 `10`
  - `pgvector/pgvector:pg17` — CI 测试用 PostgreSQL 服务容器
  - `redis:7-alpine` — CI 测试用 Redis 服务容器
  - `python:3.12` — 后端运行时基础镜像（Docker 构建）
  - `python:3.12-slim` — 后端运行时最小化镜像（Docker 运行）
  - `nginx:1.26-alpine` — Nginx 反向代理基础镜像
  - `minio/minio:RELEASE.2024-11-07T00-52-20Z` — 生产 MinIO 镜像
  - `docker compose` — 容器编排工具
  - `uv sync --all-packages` — 后端依赖安装
  - `uv run ruff check .` — Python lint（v2.0确认：lint 在 test 之前串行执行，lint 失败则跳过 test）
  - `uv run pytest --cov --cov-report=xml` — 后端测试命令
  - `pnpm install` + `pnpm --filter mini-program exec tsc --noEmit` — 前端类型检查
  - `docker compose -f docker-compose.prod.yml build` — Docker 镜像构建命令（必传 `-f` 指定生产编排文件）
  - JSON-file 日志驱动 — 所有容器日志驱动
- **禁止使用**：
  - 非 GitHub Actions 的 CI/CD 平台（设计文档确认绑定）
  - 非 Docker 的容器引擎（设计文档确认绑定）
  - 非 `postgres:17` 的 PostgreSQL 版本
  - 非 `redis:7` 的 Redis 版本
  - 在 CI 工作流 YAML 中硬编码生产环境凭据
  - 绕过 `docker-compose.prod.yml` 直接执行 `docker build` 或 `docker push`
  - 在 CI 工作流中直接执行生产环境部署动作

## 1.2 文件归属 【对内实现】

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| CI 工作流 | `.github/workflows/ci.yml` | 前端和后端 CI 定义，包含 lint、测试和类型检查 |
| 部署工作流 | `.github/workflows/deploy.yml` | CI 通过后触发，镜像构建与部署 |
| API 服务器 Dockerfile | `apps/api-server/Dockerfile.api` | 多阶段构建，python:3.12 → python:3.12-slim |
| Worker Dockerfile | `apps/worker/Dockerfile.worker` | 多阶段构建，python:3.12 → python:3.12-slim |
| Nginx Dockerfile | `infrastructure/nginx/Dockerfile` | nginx:1.26-alpine 基础，自签证书生成 |
| Nginx 引擎配置 | `infrastructure/nginx/nginx.conf` | 连接数、日志格式、gzip、upstream 定义 |
| Nginx 站点配置 | `infrastructure/nginx/conf.d/campfire.conf` | HTTP/HTTPS 虚拟主机，代理规则 |
| 开发编排 | `docker-compose.yml` | 开发环境数据服务（postgres/redis/minio） |
| 生产编排 | `docker-compose.prod.yml` | 生产环境全服务编排 |
| 环境检查脚本 | `infrastructure/scripts/check_env.sh` | 部署前置检查：校验 .env 文件存在 |
| 环境变量模板 | `.env.example` | 所有必需环境变量的模板 |

## 1.3 输入定义 【已锁定】 [UPDATED]

### 触发事件（GitHub Actions）

```yaml
# CI 触发条件
on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

# Deploy 触发条件
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
    branches: [main, master]
  workflow_dispatch:
```

| 触发方式 | 事件类型 | 分支约束 | 说明 |
|---------|---------|---------|------|
| 代码推送 | `push` | `main`, `master` | 开发者 push 代码到主分支时触发 CI |
| PR 创建/更新 | `pull_request` | `main`, `master` | 向主分支发起 PR 时触发 CI |
| CI 完成 | `workflow_run`（completed） | `main`, `master` | CI 成功完成后自动触发 Deploy |
| 手动触发 | `workflow_dispatch` | 无 | 手动触发部署，允许绕过 CI 结论（紧急热修复/回滚） |

### 环境变量注入

后端 CI 测试阶段需设置以下环境变量（由 GitHub Actions `env` 注入）：

```yaml
# CI Job 环境变量
env:
  DATABASE_URL: postgresql+asyncpg://campfire:test@localhost:5432/campfire_test
  REDIS_URL: redis://localhost:6379/0
```

> **v2.0 契约消费声明**：`DATABASE_URL` 格式与 DEPLOY-04 定义的 `DATABASE_URL` 契约一致（`postgresql+asyncpg://` 协议前缀，asyncpg 异步驱动，host=localhost 对应 CI 服务容器映射）。详见 `docs/contracts/DEPLOY-04/DATABASE_URL.json`。

### 服务容器

后端 Job 依赖两个服务容器：

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg17
    env:
      POSTGRES_USER: campfire
      POSTGRES_PASSWORD: test
      POSTGRES_DB: campfire_test
    ports:
      - 5432:5432
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5
  redis:
    image: redis:7-alpine
    ports:
      - 6379:6379
    options: >-
      --health-cmd "redis-cli ping"
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5
```

> **v2.0 契约消费声明**：容器服务名称（`postgres`、`redis`）与 DEPLOY-01 定义的 `ContainerServiceName` 枚举一致。详见 `docs/contracts/DEPLOY-01/ContainerServiceName.json`。

## 1.4 输出定义 【已锁定】 [UPDATED]

### CI 工作流输出

| 输出项 | 格式 | 产生条件 | 用途 |
|-------|------|---------|------|
| CI 状态（成功/失败） | GitHub Actions Check Run | CI 运行完成 | 触发或阻止 Deploy 工作流 |
| 覆盖率报告 | XML（Cobertura 格式） | `pytest --cov-report=xml` 执行完成 | 代码覆盖率追踪 |
| 测试结果报告 | stdout + 退出码 | pytest 执行完成 | 测试失败详情 |

### Deploy 工作流输出

| 输出项 | 格式 | 产生条件 | 用途 |
|-------|------|---------|------|
| Docker 镜像 | Docker 容器镜像 | `docker compose build` 成功 | 本地 CI runner 可用的镜像 |
| 部署状态 | stdout 文本 | `echo "Deployment step"` 执行 | 当前为占位符 |

> **v2.0 契约消费声明**：Deploy 工作流通过 `-f docker-compose.prod.yml` 引用 DEPLOY-01 定义的 `ComposeFileReference` 契约。详见 `docs/contracts/DEPLOY-01/ComposeFileReference.json`。

## 1.5 核心逻辑步骤 【对内实现】 [UPDATED]

### CI 工作流（ci.yml）

#### 步骤 1：工作流触发

- **操作对象**：GitHub Actions Workflow `CI`
- **具体操作**：当 `push` 或 `pull_request` 事件在 `main`/`master` 分支上发生时，GitHub Actions 自动创建 Workflow Run，启动 `backend` 和 `frontend` 两个并行 Job
- **输入来源**：GitHub 仓库事件
- **输出去向**：backend + frontend 两个并行 Job 实例
- **失败行为**：事件不匹配触发条件时不产生任何运行

#### 步骤 2：启动后端 Job 服务容器

- **操作对象**：GitHub Actions runner 上的 Docker 引擎
- **具体操作**：自动启动 `services` 中定义的 PostgreSQL（pgvector/pgvector:pg17）和 Redis（redis:7-alpine）服务容器，端口 5432/6372 映射到 localhost
- **输入来源**：`ci.yml` 中 `jobs.backend.services` 定义
- **输出去向**：就绪的 PostgreSQL 和 Redis 服务（通过 localhost 端口访问）
- **失败行为**：服务容器健康检查在 50 秒内（10s 间隔 × 5 次重试）未通过 → Job 标记为失败，不执行任何步骤

#### 步骤 3：Checkout 代码

- **操作对象**：Git 仓库
- **具体操作**：执行 `actions/checkout@v4` 检出当前分支代码
- **输入来源**：触发 CI 的代码提交
- **输出去向**：工作目录中的源代码文件
- **失败行为**：Checkout 失败 → Job 标记为失败

#### 步骤 4：安装 uv 并同步依赖

- **操作对象**：Python 包管理环境
- **具体操作**：`astral-sh/setup-uv@v3` 安装 `uv 0.9.x`，然后执行 `uv sync --all-packages`
- **输入来源**：`pyproject.toml`、`uv.lock`、`packages/` 目录
- **输出去向**：包含所有包依赖的虚拟环境（.venv）
- **失败行为**：依赖安装失败 → Job 标记为失败

#### 步骤 5：执行 Ruff 代码检查

- **操作对象**：所有 Python 源代码文件
- **具体操作**：执行 `uv run ruff check .`
- **输入来源**：工作目录中的所有 Python 文件
- **输出去向**：lint 结果（stdout + 退出码）
- **失败行为**：存在 lint 错误 → 退出码非 0 → Job 标记为失败，不执行后续测试步骤（lint-before-test 串行设计）

#### 步骤 6：执行 pytest 测试

- **操作对象**：所有测试文件
- **具体操作**：执行 `uv run pytest --cov --cov-report=xml`，注入 `DATABASE_URL` 和 `REDIS_URL` 环境变量
- **输入来源**：`tests/` 目录下的测试文件 + 步骤 2 的服务容器
- **输出去向**：测试结果（stdout）+ 覆盖率报告（`coverage.xml`）
- **失败行为**：任一测试失败 → 退出码非 0 → Job 标记为失败

#### 步骤 7：前端依赖安装

- **操作对象**：Node.js 包管理环境
- **具体操作**：`pnpm/action-setup@v3` 安装 pnpm 10，然后执行 `pnpm install`
- **输入来源**：`package.json`、`pnpm-lock.yaml`、`pnpm-workspace.yaml`
- **输出去向**：`node_modules/` 目录
- **失败行为**：依赖安装失败 → Job 标记为失败

#### 步骤 8：前端 TypeScript 类型检查

- **操作对象**：mini-program 包的 TypeScript 源文件
- **具体操作**：执行 `pnpm --filter mini-program exec tsc --noEmit`
- **输入来源**：`apps/mini-program/` 的 TypeScript 文件
- **输出去向**：类型检查结果（stdout + 退出码）
- **失败行为**：存在类型错误 → 退出码非 0 → Job 标记为失败

### Deploy 工作流（deploy.yml）

#### 步骤 9：校验 CI 结果

- **操作对象**：GitHub Actions `CI` Workflow Run 状态
- **具体操作**：判断 `github.event.workflow_run.conclusion == 'success'` 或 `github.event_name == 'workflow_dispatch'`
- **输入来源**：`github.event.workflow_run.conclusion`
- **输出去向**：满足条件则继续执行后续步骤，否则跳过
- **失败行为**：CI 结论不为 `success` 且非手动触发 → Job 被 `if` 条件跳过

#### 步骤 10：Checkout 代码

- **操作对象**：Git 仓库
- **具体操作**：执行 `actions/checkout@v4` 检出当前分支代码
- **输入来源**：触发部署的代码提交
- **输出去向**：工作目录中的源代码文件
- **失败行为**：Checkout 失败 → Job 标记为失败

#### 步骤 11：构建 Docker 镜像

- **操作对象**：Docker 引擎
- **具体操作**：执行 `docker compose -f docker-compose.prod.yml build`
- **输入来源**：各服务的 Dockerfile + 源代码文件 + `docker-compose.prod.yml`（DEPLOY-01 定义）
- **输出去向**：本地 Docker 镜像仓库中的容器镜像
- **失败行为**：
  - Dockerfile 语法错误 → `docker compose build` 退出码非 0
  - 基础镜像拉取失败（网络问题）→ 构建失败
  - 依赖安装失败（`uv sync --no-dev` 出错）→ 构建失败

#### 步骤 12：部署（占位符）

- **操作对象**：部署目标环境（待确定）
- **具体操作**：执行 `echo "Deployment step — configure per target environment"`
- **输入来源**：无（占位符）
- **输出去向**：stdout 输出字符串
- **失败行为**：无失败可能（仅输出字符串）

> **[v2.0 确认]** 当前 `docker push` 被注释，部署步骤为 echo 占位符。镜像推送目标和部署目标为设计文档 1.6 节中的待裁决矛盾项 #1 和 #2。

## 1.6 接口契约（对外暴露的公共接口） 【已锁定】

CI/CD 流水线不暴露传统的函数接口或 API 端点。其"接口"是 GitHub Actions 工作流的触发条件和执行结果。

### 1.6.1 接口 1：CI 工作流

| 属性 | 说明 |
|------|------|
| **接口名称** | `CI` — GitHub Actions Workflow |
| **文件路径** | `.github/workflows/ci.yml` |
| **触发方式** | `push` / `pull_request` → `main`/`master` |
| **执行内容** | backend job: lint (ruff) + test (pytest --cov) \| frontend job: type check (tsc --noEmit) |
| **输出** | Check Run 状态（success/failure）+ 覆盖率报告（coverage.xml） |
| **副作用** | 无（运行在临时 runner 上，不修改仓库状态） |
| **幂等性** | 相同代码多次触发产生相同结果 |
| **并发安全** | 每次运行在独立 runner 上，无共享状态 |

### 1.6.2 接口 2：Deploy 工作流

| 属性 | 说明 |
|------|------|
| **接口名称** | `Deploy` — GitHub Actions Workflow |
| **文件路径** | `.github/workflows/deploy.yml` |
| **触发方式** | CI 成功完成（workflow_run）或手动触发（workflow_dispatch） |
| **执行内容** | Docker 镜像构建（当前无实际部署逻辑） |
| **输出** | 本地 Docker 镜像 |
| **副作用** | 无（镜像未推送） |
| **幂等性** | 相同代码多次构建产生功能等效的镜像 |
| **并发安全** | 每次运行在独立 runner 上 |
| **成熟度** | draft（部署步骤为占位符，待确定部署目标后提升为 stable） |

## 1.7 依赖与集成接口（本模块调用的外部接口） 【已锁定】 [UPDATED]

### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 |
|:---|:---|:---|:---|
| CI 平台 | GitHub Actions | Workflow 定义、Job 调度、Service Container 管理 | CI/CD 流程编排与执行 |
| 容器引擎 | Docker | `docker compose -f docker-compose.prod.yml build` | 容器镜像构建 |
| 包管理器 | uv（astral-sh） | `uv sync --all-packages`、`uv run` | Python 依赖安装与命令执行 |
| 包管理器 | pnpm | `pnpm install`、`pnpm exec` | 前端依赖安装与命令执行 |
| PostgreSQL | pgvector/pgvector:pg17 | 作为服务容器启动，端口 5432 | CI 测试数据库 |
| Redis | redis:7-alpine | 作为服务容器启动，端口 6379 | CI 测试缓存 |
| 部署目标环境 | 未配置 | 无 | 当前未对接任何部署目标（设计文档待裁决矛盾 #2） |

### 1.7.2 核心功能依赖（其他模块，可 mock）

| 依赖模块 | 具体接口/文件 | 用途 | 契约消费 | 落地状态 |
|:---|:---|:---|:---|:---|
| DEPLOY-01 容器编排 | `docker-compose.prod.yml` | 镜像构建的编排配置 | `ContainerServiceName`、`ComposeFileReference` | ✅ 已落地 |
| DEPLOY-04 数据库迁移 | `alembic upgrade head`（在 docker-compose.prod.yml 中编排） | 部署时自动执行 Schema 迁移 | `DATABASE_URL`、`MigrationErrorCode`、`MigrationScript` | ✅ 已落地 |
| QUAL-01 自动化测试 | `pytest --cov` 命令和测试文件 | CI 中的测试阶段 | 无（仅命令约定） | ✅ 已落地 |

> **v2.0 契约消费说明**：DEPLOY-03 作为消费方使用以下 5 份已有契约，经 s08 契约协调报告确认字段级完全一致：
> - `ContainerServiceName`（`docs/contracts/DEPLOY-01/ContainerServiceName.json`，服务容器名称枚举）
> - `ComposeFileReference`（`docs/contracts/DEPLOY-01/ComposeFileReference.json`，生产编排文件引用）
> - `DATABASE_URL`（`docs/contracts/DEPLOY-04/DATABASE_URL.json`，数据库连接串格式）
> - `MigrationErrorCode`（`docs/contracts/DEPLOY-04/MigrationErrorCode.json`，迁移错误码透传）
> - `MigrationScript`（`docs/contracts/DEPLOY-04/MigrationScript.json`，迁移脚本编排环境）

## 1.8 状态机 【对内实现】

本功能点不涉及自定义状态机。

CI/CD 流水线的执行状态由 GitHub Actions 原生状态机管理：每个 Workflow Run 经历 `queued` → `in_progress` → `completed`（conclusion 为 `success`/`failure`/`cancelled`/`skipped`）。Deploy 工作流通过 `workflow_run` 事件的 `conclusion` 字段读取上游 CI 的最终状态，作为自身的门控条件。

## 1.9 异常与边界条件 【对内实现】

### 1.9.1 异常 1：CI 代码检查未通过

- **触发条件**：
  - `ruff check .` 发现代码风格或语法错误（退出码非 0）
  - `tsc --noEmit` 发现 TypeScript 类型错误（退出码非 0）
- **处理策略**：
  1. 相应 Job 立即失败，不执行后续步骤
  2. GitHub Actions 在 Check Run 中显示具体错误行和消息
  3. 失败的 Check Run 会阻止仓库合并（受 GitHub 分支保护规则控制）
  4. 开发者需修正代码后重新推送
- **重试参数**：不自动重试。开发者修正后重新触发

### 1.9.2 异常 2：测试失败

- **触发条件**：
  - `pytest` 运行中任一测试用例失败（退出码非 0）
  - 测试环境服务容器未就绪导致测试无法执行
- **处理策略**：
  1. pytest 执行完所有测试用例后汇总显示失败详情
  2. Job 标记为失败
  3. 覆盖率报告即使存在也随 Job 失败不可访问
- **重试参数**：不自动重试。开发者修正后重新推送

### 1.9.3 异常 3：测试环境服务不可用

- **触发条件**：CI runner 中 PostgreSQL 或 Redis 服务容器健康检查在 50 秒内（10s 间隔 × 5 次重试）未通过
- **处理策略**：
  1. Job 标记为失败，不执行任何步骤
  2. GitHub Actions 日志显示服务容器启动错误
  3. 下次 CI 运行在全新 runner 上重新启动服务容器
- **重试参数**：不自动重试。每次 CI 运行在独立 runner 上，服务容器随 Job 创建和销毁

### 1.9.4 异常 4：Docker 镜像构建失败

- **触发条件**：
  - `docker compose -f docker-compose.prod.yml build` 退出码非 0
  - 基础镜像（`python:3.12`、`python:3.12-slim`、`nginx:1.26-alpine`）拉取失败
  - `uv sync --no-dev` 因网络或依赖问题安装失败
  - Dockerfile 语法错误
- **处理策略**：
  1. Deploy 工作流标记为失败
  2. GitHub Actions 日志输出构建错误详情
  3. 开发者查看日志定位问题并修正
- **重试参数**：不自动重试。开发者修正后通过 `workflow_dispatch` 手动重新触发

### 1.9.5 异常 5：CI 未通过时部署被触发（防御）

- **触发条件**：理论上不应发生，但需防御
- **保护策略**：
  - Deploy 工作流的 `if` 条件：`github.event.workflow_run.conclusion == 'success' || github.event_name == 'workflow_dispatch'`
  - 对 `workflow_run` 事件：仅当 CI `conclusion == 'success'` 时才执行
  - 对 `workflow_dispatch`：手动触发不受此限制（紧急修复与回滚的逃生路径）
- **重试参数**：无重试，条件不满足则跳过 Job

## 1.10 验收测试场景 【对内实现】

### 1.10.1 正向测试 1：正常 push 触发 CI 全部通过

- **场景**：代码 push 到 main 分支，所有检查通过
- **Given**：代码格式正确、测试通过、类型检查通过
- **When**：推送到 main 分支
- **Then**：
  - `ruff check .` 退出码为 0
  - `pytest --cov --cov-report=xml` 退出码为 0，覆盖率报告 `coverage.xml` 已生成
  - `tsc --noEmit` 退出码为 0
  - CI Workflow Run 状态为 `success`

### 1.10.2 正向测试 2：CI 通过后自动触发部署

- **场景**：CI 在 main 分支成功完成后，Deploy 工作流自动触发
- **Given**：CI 在 main 分支运行成功完成（conclusion = `success`）
- **When**：GitHub Actions 自动调度 Deploy 工作流
- **Then**：
  - Deploy 工作流在 CI 完成后自动启动
  - `docker compose -f docker-compose.prod.yml build` 成功执行
  - 所有服务的 Docker 镜像构建完成

### 1.10.3 正向测试 3：手动触发部署

- **场景**：通过 GitHub 界面手动触发 Deploy 工作流（绕过 CI 结论）
- **Given**：任何仓库状态（即使没有最近的 CI 运行）
- **When**：通过 GitHub Actions UI 执行 `workflow_dispatch`
- **Then**：
  - Deploy 工作流启动（绕过 `workflow_run` 的 `conclusion == 'success'` 条件）
  - Docker 镜像成功构建

### 1.10.4 异常测试 1：lint 失败阻止 CI

- **场景**：后端代码包含 ruff 格式错误
- **Given**：推送一个包含格式错误的 Python 文件
- **When**：CI 自动触发
- **Then**：
  - `backend` Job 在 ruff 步骤失败
  - 错误行号和信息在 CI 日志中可见
  - 测试步骤未执行（lint-before-test 串行保护）
  - `frontend` Job 仍独立执行（两个 Job 并行）

### 1.10.5 异常测试 2：测试失败阻止 CI

- **场景**：后端测试用例失败
- **Given**：推送一个会导致测试失败的代码变更
- **When**：CI 自动触发
- **Then**：
  - ruff 检查通过
  - `backend` Job 在 pytest 步骤失败
  - 失败的测试用例名称和断言信息在日志中可见

### 1.10.6 异常测试 3：CI 失败后部署不被触发

- **场景**：CI 运行失败，Deploy 不应自动运行
- **Given**：CI 结论为 `failure`（如 lint 失败）
- **When**：GitHub Actions 评估 Deploy 工作流触发条件
- **Then**：
  - Deploy 工作流的 `if` 条件不满足
  - Deploy Job 被跳过，不执行任何步骤

### 1.10.7 异常测试 4：Dockerfile 错误导致构建失败

- **场景**：Dockerfile 中存在语法错误
- **Given**：`Dockerfile.api` 中包含无效指令
- **When**：手动触发 `workflow_dispatch` 部署
- **Then**：
  - Deploy 工作流失败
  - 构建错误在日志中可见

## 1.11 注意事项与禁止行为（编码层面） 【对内实现】

1. **[约束 1]** CI 服务容器的端口必须与服务容器内部端口一致（PostgreSQL: 5432, Redis: 6379），并且映射到 runner 的 localhost 供测试连接
2. **[约束 2]** Docker 镜像构建必须使用 `docker compose -f docker-compose.prod.yml build`，不可直接使用普通 `docker build`，以保持与 DEPLOY-01 的编排一致性
3. **[约束 3]** CI 和 Deploy 必须使用各自独立的 runner 环境，禁止跨工作流共享文件系统状态
4. **[约束 4]** 前端 CI 的 `tsc --noEmit` 必须在 `pnpm install` 之后执行，不可跳过依赖安装直接执行类型检查
5. **[约束 5]** CI 服务容器的 PostgreSQL 镜像必须是 `pgvector/pgvector:pg17`——纯 `postgres:17` 不包含 pgvector 扩展，测试中的向量查询会失败
6. **[易错点 1]** `DATABASE_URL` 必须是 `postgresql+asyncpg://` 格式（SQLAlchemy 2.0 async 异步驱动），非 `postgresql://`（同步驱动）。使用同步前缀会导致测试连接失败
7. **[易错点 2]** Docker 镜像构建时的 `--no-dev` 标志确保生产镜像不包含开发依赖，如果在 CI 中误用 `--dev` 会导致镜像体积过大
8. **[易错点 3]** Deploy 工作流中 `-f docker-compose.prod.yml` 标志不可省略——省略后使用默认 `docker-compose.yml`（dev 配置），导致镜像构建参数不一致
9. **[设计边界 1]** 本模块不负责 Dockerfile 内容——Dockerfile 归 DEPLOY-01 定义。CI/CD 仅调用构建命令，不修改 Dockerfile
10. **[设计边界 2]** 本模块不负责数据库迁移逻辑——迁移执行由 DEPLOY-04 的 Alembic 脚本和 DEPLOY-01 的 migration 服务编排负责
11. **[设计边界 3]** 本模块不负责测试内容定义——测试文件、覆盖率目标、测试策略归 QUAL-01 定义
12. **[设计边界 4]** 本模块不负责部署目标环境的服务器配置——部署目标基础设施归运维层面，CI/CD 仅产出可部署制品
13. **[禁止行为 1]** 禁止在 `.github/workflows/*.yml` 中硬编码生产环境凭据（镜像仓库密码、SSH 私钥、API Token）。所有凭据必须通过 GitHub Secrets（`${{ secrets.* }}`）注入
14. **[禁止行为 2]** 禁止绕过 Compose 文件直接执行 `docker build` 或 `docker push`——这会绕开 DEPLOY-01 定义的构建上下文和构建参数
15. **[禁止行为 3]** 禁止在 CI 工作流中执行生产环境部署动作。CI runner 是临时执行环境，不应具有生产服务器的 SSH 访问权限
16. **[禁止行为 4]** 禁止以"部署目标后续再配置"为由长期保留占位符部署步骤而不对接实际部署环境

## 1.12 文档详细度自检清单 【对内实现】

- [x] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可理解 CI/CD 流水线的结构与行为
- [x] 无偷懒表述：全文无 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`
- [x] 逻辑步骤完整：12 个步骤，每个都有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：5 种异常，每种都有精确的触发条件、处理策略、重试参数
- [x] 无隐藏假设：所有触发条件、环境变量、端口映射均已显式写出
- [x] 技术栈绑定明确：必须使用和禁止使用的项均已列出，与设计文档 v1.0 保持一致
- [x] 意图一致性：技术实现与已冻结的意图文档一致（见 §1.14）

## 1.13 外部接口契约清单 【已锁定】 [UPDATED]

> DEPLOY-03 属于基础设施配置模块（GitHub Actions YAML），不产生结构化 JSON Schema 契约文件。本模块的对外接口为两个 GitHub Actions Workflow 配置文件。
>
> 经 s08 契约协调确认：契约冲突 0，无需创建 `docs/contracts/DEPLOY-03/` 目录或 JSON Schema 文件。

### 本模块定义的工作流接口

| 接口名称 | 文件路径 | 接口类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| CI | `.github/workflows/ci.yml` | github-actions-workflow | stable | DEPLOY-03 | —（由 GitHub 仓库事件直接消费） |
| Deploy | `.github/workflows/deploy.yml` | github-actions-workflow | draft | DEPLOY-03 | — |

### 本模块消费的已有契约

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 |
|:---------|:---------|:---------|:-------|:-------|
| ContainerServiceName | `docs/contracts/DEPLOY-01/ContainerServiceName.json` | shared-enum | draft | DEPLOY-01 |
| ComposeFileReference | `docs/contracts/DEPLOY-01/ComposeFileReference.json` | shared | draft | DEPLOY-01 |
| DATABASE_URL | `docs/contracts/DEPLOY-04/DATABASE_URL.json` | shared | draft | DEPLOY-04 |
| MigrationErrorCode | `docs/contracts/DEPLOY-04/MigrationErrorCode.json` | shared-enum | draft | DEPLOY-04 |
| MigrationScript | `docs/contracts/DEPLOY-04/MigrationScript.json` | shared | draft | DEPLOY-04 |

## 1.14 意图一致性声明 【对内实现】 [UPDATED]

- **配套意图文档**：`DEPLOY-03-CI_CD流水线-意图文档.md`
- **冻结时间**：`2026-05-26 22:48:42`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出定义与意图文档中的业务字段定义一致
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致（异常 1-5 完全覆盖意图文档 §1.8.1-1.8.4）
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准（AC-01 至 AC-08，4 正 + 3 异常场景）
  - [x] 本落地规范的技术实现基于已确认的设计文档 v1.0，设计文档与意图文档一致性已确认
  - [x] 本落地规范中的技术实现未超出意图文档中"实现观察"章节的范围——6 项实现观察均在设计文档和落地规范中对应处理
- **偏差说明**：无偏差。本落地规范 v2.0 基于设计文档 v1.0（用户已确认通过）和 s08 契约协调报告（0 冲突），技术实现与已冻结意图文档完全一致。
- **设计文档一致性**：本落地规范的技术实现与 `DEPLOY-03-CI_CD流水线-设计文档.md` v1.0 保持一致。设计文档中 6 项待裁决矛盾不影响当前落地规范 v2.0 的完备性——当待裁决项经用户裁定后，在下个版本更新。

---

*本文档 v2.0 基于已确认设计文档和契约协调报告生成，对外接口章节标记【已锁定】，内部实现章节标记【对内实现】。*
