# Campfire-AI（篝火智答）

面向孤独症家庭的 AI 咨询助手：FastAPI 后端 + React H5 前端。

> **设计真源在 [`docs/`](docs/README.md)** —— 需求、技术栈、项目结构、视觉契约都在那里。
> 本文件**只讲怎么把它跑起来**，不复述任何设计结论；设计有冲突时以 `docs/` 为准。
> 给 AI Agent 的编码规范与完整命令表见 [`AGENTS.md`](AGENTS.md)。

## 环境要求

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Python | ≥ 3.12 | 包管理用 [uv](https://docs.astral.sh/uv/) |
| Node | ≥ 20 | CI 跑 22（LTS 线） |
| pnpm | 见根 `package.json` 的 `packageManager` | 不要另写版本号，必然漂移 |
| Docker | Compose v2 | 本地数据服务（PostgreSQL / Redis / FalkorDB / SuperTokens） |

## 首次起步（全新环境）

### 1. 克隆

```bash
git clone https://github.com/FengZhiHen1/Campfire-AI.git
cd Campfire-AI
git switch dev          # 日常开发在 dev 上
```

分支策略（见 [AGENTS.md](AGENTS.md)）：**`dev` 日常开发，`master` 仅保留稳定版本** ——
发布时把 `dev` 快进到 `master`。因此 `master` 在两次发布之间会落后 `dev`。
默认分支是 `master`，直接 `clone` 不会报错；**要继续开发就切到 `dev`**。
并行任务不直接改这里，而是用 `.worktrees/<任务名>/` 的 `task/*` 分支（见本文
「开发泳道」一节），由主 agent 合入 `dev`。

### 2. 建本地配置（**必须**，否则测试不会全绿）

```bash
cp .env.example .env
```

⚠ 缺 `.env` 时 `pytest` 会多挂一条并报
`SuperTokensConfigurationError: 未配置 SUPERTOKENS_API_KEY`。
CI 里这些变量由 [`.github/workflows/ci.yml`](.github/workflows/ci.yml) 显式提供，本地靠 `.env` 补。
`.env` 不入库（见 `.gitignore`）；真实凭据只放在本地与服务器。

### 3. 后端

```bash
uv sync                     # 本地开发用这个（会按需更新 lock）
                            # CI 用 uv sync --frozen：lock 与 pyproject 不一致即失败
docker compose up -d        # 本地数据服务
uv run uvicorn campfire.main:app --reload          # HTTP 入口
uv run taskiq worker campfire.worker:broker        # 队列 Worker（需要时）
```

**集成测试需要上面这些服务在跑**；Docker 没起时，带 `integration` marker 的用例会失败或 skip
（本地表现为一批 `ConnectionRefusedError`），这是环境问题，不是代码问题。

### 4. 前端

```bash
pnpm install
pnpm --filter @campfire/web dev      # 含 token 同步（docs/design/tokens.css → src）
```

### 5. 装浏览器（**只在第一次，或 Playwright 升级后**）

```bash
pnpm --filter @campfire/web exec playwright install
```

⚠ 不装的话 `shots` / `e2e` 会失败。报错本身会提示这条命令，但**仓库其它地方没写**，先装上省事。

## 检查（提交前 quick；合入前 full）

**流程真源：[docs/development/testing.md](docs/development/testing.md)**（分层、清单、失败判读）。

```bash
uv run python scripts/checks.py quick --base dev   # 每次提交前：按改动面定向
uv run python scripts/checks.py full               # 合入 dev 前与 CI：全套确定性检查
```

**全量检查不在每个 commit 上跑**——日常提交用 quick，集成点与 CI 用 full。

`scripts/checks.py` 由工具任务实现；**落地前**用下面的等价手工命令（`--dry-run` 也只是打印这些）：

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy apps/api/src/campfire apps/api/tests   # 两个路径必须同时给
uv run alembic upgrade head && uv run alembic check  # 迁移门禁：需要数据服务在跑
uv run pytest
uv run --no-project python scripts/check_design_docs.py   # 纯标准库，不依赖项目环境
pnpm --filter @campfire/web lint
pnpm --filter @campfire/web test
pnpm --filter @campfire/web build                  # 已内含 tsc --noEmit 与契约 CSS 断言
```

- `mypy` 只传 `apps/api/tests` 会因 `conftest` 被当成两个模块而**中止**
  （`Source file found twice under different module names`）——两个路径始终一起给。
- 不再单独跑 `pnpm typecheck`：`build` 的第一步就是 `tsc --noEmit`，重复跑不增加证据。
- 需求与验收行的一一对应由 `scripts/check_design_docs.py` 机械检查（未覆盖需求是**失败**）。
  具体条数以脚本当前输出为准，不要在这里写死数字。

## 页面截图（评测与验收用，不是门禁）

```bash
pnpm --filter @campfire/web shots   # 出图：多页 × 视口 × 图种
pnpm --filter @campfire/web e2e     # 内容断言：证明每张图「有料」而不是空态
```

**两条都要跑**：`shots` 只出图，`e2e` 才验内容；跑完 `shots` 不等于验收通过。
落点默认 `.tmp/screenshots/`（`SHOTS_OUT` 可改），在 `.gitignore` 的 `.tmp/` 之下，不入库。
**加了新路由就要加新截图配置**，否则那条路由永远没有 PNG —— 这层对应关系由
`apps/web/tests/routes-coverage.test.ts` 守着，`pnpm test` 会红。

## 演示材料（对外展示用，`demo/`）

```bash
# 本机全真栈（后端、Vite、Worker）要先起；邀请码每轮现签
uv run python -m campfire.cli invite issue
DEMO_INVITE_CODES=<码> pnpm --filter @campfire/web demo
```

在真浏览器 + 真模型 + 真库上把典型场景走一遍并逐屏截图，产物落 `demo/`（位置固定、
整目录被 `.gitignore` 与 `.dockerignore` 排除、**每轮覆盖**）。它是**展示材料**，
按需运行、不是门禁、不在 CI 里跑。前提、产物结构与已知边界见
[docs/运维/演示材料生成.md](docs/运维/演示材料生成.md)。

⚠ `demo/` **每轮覆盖**，因此**不能承担正式运行证据**：要留存的原始输出、截图、评分表放
**原始仓库根**的 `deliverables/2026-ai-opensource/<run-id>/`（整目录忽略、不随泳道清理）。

## 材料与证据（`materials/`、`deliverables/`）

| 落点 | 版本控制 | 放什么 |
|---|---|---|
| `materials/2026-ai-opensource/` | **入库** | 文本、配置、许可与归属说明、**脱敏**证据索引、报告草稿 |
| `deliverables/2026-ai-opensource/<run-id>/` | 忽略（在**原始仓库根**） | 正式运行的原始件：输出、截图、录屏、评分表、日志 |
| `.tmp/` | 忽略 | 可丢弃的过程产物 |
| `demo/` | 忽略 | 可再生预览，每轮覆盖 |

事实状态（verified / partial / unverified / contradicted）、正式评分必须人工独立盲评与风险
专业审核、未完成写 pending、工程单测不等于效果或安全证明——全部口径见
**[docs/development/materials.md](docs/development/materials.md)**。

## 影片（`marketing/promo-shotcraft/`，独立工具链）

```bash
cd marketing/promo-shotcraft
pnpm install        # 有独立的 pnpm-workspace.yaml 与 pnpm-lock.yaml
pnpm dev            # remotion studio
```

该目录**刻意不并入**仓库根那个只含 `apps/web` 的 pnpm 工作空间（影片工具链体积大，
并进去会让 CI 每次多拉整套 Remotion + puppeteer）。它有**自己的**工作空间根与 lockfile，
所以**必须在本目录里安装**。

## 临时文件

**只有 `.tmp/` 一个落点**（整个被 gitignore），不要新建 `tmp/`、`reports/` 这类并列目录。
判据只有一条：`git ls-files .tmp` 必须为空。细节见
[`AGENTS.md`](AGENTS.md) 的「工作区与留档」一节。

## 目录速览

```text
docs/                 设计根，真源
docs/development/     开发流程真源：检查分层、泳道环境、材料与证据口径
materials/            可入库的正式材料（文本、配置、许可、脱敏证据索引）
deliverables/         正式运行的本地大文件（原始仓库根，整目录忽略）
apps/api/             唯一的 Python 应用（HTTP 与 Worker 两个入口）
apps/web/             React H5（唯一的 pnpm 工作空间包）
marketing/            影片制作（独立工具链，不参与产品构建）
infrastructure/       生产 docker/nginx 产物
scripts/              仓库级运维脚本
archive/              已归档的旧实现与旧设计，仅供参考
```

模块边界与依赖方向的真源是 [`docs/项目结构设计.md`](docs/项目结构设计.md)，
由 `apps/api/tests/test_layer_boundaries.py` 机械检查。

## 开发泳道（worktree）

日常开发在**主工作区**的 `dev` 上进行；并行任务各自在**原始仓库根**的 `.worktrees/<任务名>/`
里、从 `dev` 切出的 `task/<主题>` 分支上做，**由主 agent 合入 `dev`**。
❌ 不在 `main` / `master` 上开发。泳道的创建、隔离（`.venv`/`node_modules` 各自一份、包缓存
可共享）、就绪核验、数据测试串行规则与清理判据见
[docs/development/worktree-environment.md](docs/development/worktree-environment.md)。

## 部署

**默认不在云端开发**；部署只在明确要求时进行，且必须两步（推送等 CI 绿 → 显式触发 `deploy.yml`）。
判据、回滚与验收流程见 [`docs/运维/发布与回滚.md`](docs/运维/发布与回滚.md) 与
[`docs/运维/上线验收测试流程.md`](docs/运维/上线验收测试流程.md)。
