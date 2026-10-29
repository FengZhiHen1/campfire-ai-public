# Campfire-AI — 篝火智答

面向孤独症家庭的情境支持平台：FastAPI 后端 + React H5 前端。

> **设计真源在 `docs/`**（入口 [docs/README.md](docs/README.md)，含文档地图与事实所有权）；
> `archive/` 是已废弃的旧实现与旧设计，**不构成任何当前依据**。
> **状态**：业务实现与生产装配已落地并上线 <https://campfire.wenran.me>；未闭合项
> （压缩记账无持久化实现、发布闸门 `EVID-A`～`EVID-D`）唯一登记在 [docs/TODO.md](docs/TODO.md)。

## Stack

**真源：[docs/技术栈设计.md](docs/技术栈设计.md)**（选型理由、版本基线、重访条件）。要点：

- Python ≥3.12 + FastAPI + Pydantic 2，包管理 uv（单应用、两个运行入口）；前端 React 19 + Vite +
  React Router + Zustand（一期只交付手机端 H5）
- Agent 运行时 OpenAI Agents SDK；skill 注册表与工具范围控制由本项目实现
- 模型：全应用单一对话模型；**对话端点与嵌入端点可以不是同一个**（`EMBEDDING_BASE_URL` 留空时回落
  对话那一套，换对话网关必须显式分家）。向量模型与维度**绑死**，换家要整库重建——而检索失败在
  产品里只表现为「没有资料」
- RAG LlamaIndex；Data PostgreSQL 17 + pgvector + pg_trgm、Redis 7、FalkorDB、MinIO（一期不用）；
  认证 SuperTokens（Java core + Python SDK）；队列 Taskiq + Redis
- Infra Docker Compose v2 单机 + Nginx，Alembic 迁移；ruff（行宽 120）、oxlint、pytest、vitest

## Commands

全部在仓库根执行；**全新环境先看 [README.md](README.md) 的「首次起步」**（`.env`、
`playwright install` 等一次性步骤在那里）。

```bash
# --- 本地开发闭环（默认在这里做完，不要碰云端）---
cp .env.example .env          # 新环境一次性；缺它 pytest 会多挂一条
uv sync                       # 或 uv sync --frozen（lock 必须同步）
docker compose up -d          # 本地数据服务：PostgreSQL、Redis、FalkorDB、SuperTokens
uv run uvicorn campfire.main:app --reload       # HTTP
uv run taskiq worker campfire.worker:broker     # Worker，需 Redis
pnpm install && pnpm --filter @campfire/web dev # 前端（含 token 同步）

# --- 检查（分层与判读口径见 docs/development/testing.md）---
uv run python scripts/checks.py quick --base dev   # 每次提交前：按改动面定向
uv run python scripts/checks.py full               # 集成点与 CI：全套确定性检查

# --- 本地摄取（不连生产库；CLI 不暴露成服务端点）---
uv run python -m campfire.cli convert <x.html>  # HTML → 可摄取 Markdown（不连库）
uv run python -m campfire.cli ingest <x.md>     # 摄取到资料库（条目与节点同事务）
```

- **全量检查不在每个子任务、每个 commit 上跑**；由集成点（合入 `dev` 前）与 CI 承担。清单、
  `--dry-run`、失败判读见 **[docs/development/testing.md](docs/development/testing.md)**。
- 材料层（`shots`/`e2e`、`demo`、`e2e-real`、评测运行）**按需运行，不进 quick/full、不进 CI**；
  它们回答「材料是否真实」，口径见 **[docs/development/materials.md](docs/development/materials.md)**。
- ❌ 禁止：把「改完就跑一遍 demo/评测」当回归；外部抖动后的重试成功不算模型可靠性证据。

`scripts/checks.py` 与 `scripts/worktree.py` 由工具任务实现；落地前按 testing.md §4 逐条手工执行，
不得以「工具没做好」为由跳过检查。

## 开发与部署的边界

**默认在本地完成开发闭环；部署只在用户明确要求时进行。** 展开前自检：检查全绿（quick 日常、
full 集成点）＋关键路径已在真实依赖上跑通＋已想清回滚。**「真实依赖上跑通」不是形式要求**：
三个 P0（缺 `EmailPassword.init()`、明文 HTTP 下 `crypto.randomUUID` 不存在、产物写死协议
导致 mixed content）都只在真实运行时暴露，而那时单测全绿。

部署是**真实生产变更**，必须两步：push 等 CI 绿（push `master` 只触发 CI，不部署）→
`gh workflow run deploy.yml --ref master -f deploy=true`。**人工闸门是刻意保留的**：合并可回退，
发布要动生产。❌ 禁止绕过它 ssh 上服务器改文件——那会让「生产在跑哪个版本」失去确定答案。

部署后验收：`curl -fsS https://campfire.wenran.me/readyz`（用 `/readyz`，不是 `/livez`）＋
`uv run --no-project python scripts/acceptance_probe.py`（静态资源、9 条页面深链、未登录 401）；
登录之后的链路必须用真实浏览器测。**看到「发布验证失败」先判断是不是误报再回滚**：曾发生部署
成功而验证步骤因漏 `--env-file` 报失败，回滚正常版本会把小事变成事故。流程真源：
[docs/运维/发布与回滚.md](docs/运维/发布与回滚.md)、[docs/运维/上线验收测试流程.md](docs/运维/上线验收测试流程.md)。

## Architecture

```text
docs/                  设计根，真源（入口 docs/README.md）
docs/development/      开发流程真源：检查分层、泳道环境、材料口径
apps/api/              唯一的 Python 应用（main.py / worker.py 两个入口）
  skills/              开放标准 skill 的内容产物（不是 Python 代码）
  src/campfire/
    agent/             通用 Agent 基座：产品无关，不含领域术语
    surfaces/          面：产品入口与运行装配
    tools/             产品侧工具，注册进基座工具池
    modules/           业务数据与用例：accounts、library（含检索链）、profile、memory
    core/              跨切能力：config、db、cache、auth、authz、jobs
    cli/               本地摄取入口，不暴露成服务端点
  tests/
apps/web/              React H5（唯一的 pnpm 工作空间包）
materials/             可入库的正式材料（文本、配置、许可、脱敏证据索引）
deliverables/          正式运行的本地大文件（原始仓库根，整目录忽略）
infrastructure/        生产 docker/nginx 产物
scripts/               仓库级运维脚本（部署、备份、回滚、检查）
marketing/             影片制作，独立工具链，不参与产品构建
archive/               已归档实现与设计，废弃物，仅供参考
```

模块边界与依赖方向的真源是 [docs/项目结构设计.md](docs/项目结构设计.md)；白名单由
`apps/api/tests/test_layer_boundaries.py` 机械检查——**新增层必须同步加入该测试**。

## Conventions

### 开发流程：Plan → Do → Verify

1. **Plan** — 先读相关 `docs/`；写清可观察完成标准与未验证假设；识别影响范围。
2. **Do** — 只改与任务直接相关的内容；遵循已有风格；不顺手重构；不为单一场景建抽象。
3. **Verify** — 跑与改动相称的检查（[testing.md](docs/development/testing.md)）；报告通过、
   失败与未测情形，不把未跑写成通过。

### 工作区与留档

- 主工作区的 `dev` 是集成基线；任务在 `.worktrees/<任务名>/` 的 `task/*` 分支上做，**由主 agent
  合入 `dev`**。❌ 禁止直接在 `main`/`master` 上开发或提交。泳道规则见
  [docs/development/worktree-environment.md](docs/development/worktree-environment.md)。
- 临时文件只有一个落点 `.tmp/`，用完即删（判据 `git ls-files .tmp` 为空）；**不要把成果留在
  `.tmp/` 等下次再搬**——该入库的当次入库，否则视为过程产物。
- 可入库的正式材料在 `materials/`；原始大文件在**原始仓库根**的 `deliverables/<run-id>/`
  （整目录忽略、不随泳道清理）。状态机与边界见 [docs/development/materials.md](docs/development/materials.md)。
- 环境与踩坑经验记在已有的 [docs/运维/Agent执行环境构造经验.md](docs/运维/Agent执行环境构造经验.md)
  （按需检索，不新增平行体系）；稳定且普适的约束才提升进本文件。

### 代码风格

- 注释用中文，变量/函数/类/文件命名用英文；Python ruff format + check（行宽 120），TypeScript oxlint
- ❌ 禁止：引入与本次任务无关的第三方依赖；为自己造成的未使用 import/变量/函数不清理

### 提交规范

**自 2026-10-01 起生效，只约束此后的提交**；历史提交保持原样，不重写、不 amend、不 rebase。

- 类型前缀用**英文** Conventional Commits（`feat`/`fix`/`refactor`/`perf`/`test`/`docs`/`chore`/
  `build`/`ci`/`style`），可选英文作用域；标题与正文用**中文**，正文说明「为什么」。
  例：`fix(library): 展开命中越界 limit 时改为拒绝`。
- ❌ 禁止：`update`、`fix bug`、`changes` 这类无类型无信息的标题；一个 commit 塞多个无关主题。

### 数据库迁移与契约

- 迁移用 `alembic revision --autogenerate` 生成，文件带中文注释说明业务意图；
  ❌ 禁止手动改生产 schema 而不通过迁移；❌ 禁止让 `--autogenerate` 把 SuperTokens core
  自建的表当成待删对象。
- 契约真源在 `docs/技术设计/` 与各面文档（v3.0 的 `/api/v2` 契约已随基线归档，不得沿用）。
  改 API、schema、公共函数签名前先确认影响范围；❌ 禁止未确认影响范围就破坏性修改接口。

## Security

- ❌ 禁止：硬编码 API Key、密码、密钥——统一用环境变量（模板 `.env.example`，按消费者分段标注）
- ❌ 禁止：提交 `.env`、`.tmp/`、SSL 证书与私钥（`archive/` 下遗留 TLS 私钥必须保持忽略）
- ❌ 禁止：在回复中完整复述密码或服务器凭证；把服务器凭证上传给第三方服务
- ❌ 禁止：健康检查、日志或错误消息复述连接串与凭据（探针只回报异常类型）
- 服务器操作默认不做；确需运维时见 [docs/运维/发布与回滚.md](docs/运维/发布与回滚.md)
- 材料与证据：真实家庭/儿童资料、凭据、未授权第三方素材不得入 Git；截图须匿名（无学校/导师
  信息）。见 [materials.md](docs/development/materials.md) §8

## Git Workflow

- `dev` 日常开发，`master` 仅保留稳定版本；任务分支 `task/<主题>` 从 `dev` 起
- CI（`.github/workflows/ci.yml`）在 push 与 PR 到 `dev`、`main`、`master` 时跑三个 job：设计
  文档一致性、后端（ruff + mypy + 迁移门禁 + pytest，带三个数据服务）、前端（oxlint + tsc +
  vitest + build）。**初期保留完整的确定性检查**，不裁成子集
- 备份/恢复/回滚：`scripts/{backup,restore,rollback}.sh`；仓库 <https://github.com/FengZhiHen1/Campfire-AI.git>
- ❌ 禁止：未经用户明确要求执行 `deploy.yml` 的发布（`deploy=true`）、push、发 PR——那是生产变更

## Design Docs

真源在 `docs/`，入口 [docs/README.md](docs/README.md)（文档地图与事实所有权）。

- **已确认定调**：[功能需求与验收](docs/需求/功能需求与验收.md)、[技术栈设计](docs/技术栈设计.md)、
  [项目结构设计](docs/项目结构设计.md)；技术细节初稿待确认在 `docs/技术设计/`
- **待办唯一登记处**：[docs/TODO.md](docs/TODO.md)
- **开发流程三件套**：[检查与测试](docs/development/testing.md)、[泳道环境](docs/development/worktree-environment.md)、
  [材料与证据](docs/development/materials.md)
- 未确认内容不得写入权威文档，也不得据此开始实现；发现设计不一致先提出，不得静默沿用旧行为
- ❌ 禁止：把 `archive/` 中的「有效」「目标态」等字样当作新目标实现要求
- 视觉契约以 `docs/design/` 三件套与页面设计文档为准；不要绕过 token 写死颜色与间距
  （`apps/web` 的 `build` 有契约类名断言把关）
- 需求与验收行的一一对应由 `scripts/check_design_docs.py` 机械检查，未覆盖需求是**失败**而非
  告警；**具体条数以该脚本当前输出为准**，本文件不写死数字

## Behavioral Guidelines

- 先列可观察完成标准与未验证假设；精准修改，不顺手重构、不为单一场景建抽象；跑与改动相称的
  检查并报告实际结果
- ❌ 禁止：未验证就声称安全、专业认可、线上可用，或把设计草案当作真实用户数据处理授权
- ❌ 禁止：跨层穿透（Domain/Application/ViewModel/View/Infrastructure）；授权只靠角色名、
  前端隐藏、Agent 扩展或缓存判断
- ❌ 禁止：留下永远不会失败的检查、闸门或测试（提取到 0 条即应失败，而不是静默通过）

## When to Stop and Ask

任务未授权或证据不足时先确认范围：需要破坏真实数据、修改跨模块公共契约、引入外部供应商/依赖、
进行远程高风险操作或无法恢复的迁移。明确授权的设计裁决可自主记下理由与证据边界；测试缺环境时
如实报告，不编造通过。

## Checklist

- [ ] 改动仅覆盖已授权范围，已读目标文档与实际存在的代码
- [ ] 已运行可运行的检查并报告通过、失败和未测情形；未制造未使用代码
- [ ] 若更改授权、数据或 API，已验证影响范围与回滚门槛；对应文档已同步
- [ ] 如需 commit，只含本次任务文件，**英文** `type(scope):` 前缀 + **中文**标题与正文；确认未提交密钥

<!-- Last updated: 2026-10-29 -->
