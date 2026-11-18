# Campfire-AI — 篝火智答

> **设计基线已确认，业务实现与生产装配均已落地。** 需求、技术栈与项目结构真源在
> `docs/`（2026-09-29 经用户确认）；历史归档树（`archive/**`，旧实现与旧设计）
> **不随本公开仓分发**（原因见 `NOTICE` 第三节），本文件中出现的 `archive/` 一律只是
> 历史指称，仓内无对应文件，也不构成任何当前依据。
>
> **已实现**（按模块，细节见 `docs/`，此处不复制）：`agent/` 通用 Agent 基座（运行编排、
> skill 机制、工具池与权限门、注入项与引用索引、模型网关、上下文压缩、运行记录）；
> `modules/` 四个业务模块（`library` RAG 检索链与案例库、`memory` Graphiti 记忆、
> `accounts` 邀请码与账号、`profile` 支持对象与档案分层）；`core/` 跨切能力；
> `surfaces/consult` 咨询面（HTTP/SSE 契约与生产组合根）；`tools/` 10 个产品工具；
> `cli/` 运营命令；`apps/web/` React H5；`infrastructure/` 生产 Docker/Compose/Nginx。
>
> **仍未闭合**：压缩记账端口 `CompactionJournal` 尚无持久化实现（不接线的后果是窗口
> 退化为全量历史——安全方向，不丢内容）；发布闸门 `EVID-A`～`EVID-D` 未处理（面向真实
> 使用者前必须逐项关闭），见 [docs/TODO.md](docs/TODO.md)。
>
> **已上线**：<https://campfire.wenran.me>（HTTP 会 301 跳转），七个容器 healthy，
> Let's Encrypt 证书自动续期已配置（systemd timer）。**但默认不在云端开发**——见下方
> 「开发与部署的边界」。

## Stack

**真源：[docs/技术栈设计.md](docs/技术栈设计.md)**（选型理由、版本基线、重访条件与未核实项）。
要点如下，不复制全文：

- Language: Python ≥3.12；Backend: FastAPI + Pydantic 2；包管理 uv（单应用、两个运行入口）
- Agent 运行时: OpenAI Agents SDK；skill 注册表与工具范围控制由本项目实现
- 模型: 腾讯云 TokenHub，**全应用单一模型** DeepSeek-V4.1-Flash；向量 `Kinfra-Text-Embedding-4b`（2560 维）
- RAG: LlamaIndex 全量引入（摄取、分块、嵌入适配、向量存储、融合检索）
- Data: PostgreSQL 17 + pgvector + pg_trgm、Redis 7、FalkorDB（Graphiti 通用记忆）、MinIO（一期不用）
- 认证: SuperTokens（Java core 容器 + Python SDK）；队列: Taskiq + Redis，独立 Worker
- Frontend: React 19 + Vite + React Router + Zustand（一期只交付手机端 H5）
- Infra: Docker Compose v2 单机 + Nginx；Alembic 迁移
- Lint/Test: ruff（行宽 120）、oxlint；pytest + pytest-asyncio、vitest

## Commands

全部在仓库根执行。**全新环境（刚 clone）先看 [README.md](README.md) 的「首次起步」**——
那里有 `.env`、`playwright install` 等一次性步骤；本文件只列日常命令。

```bash
# --- 本地开发闭环（默认就在这里做完，不要碰云端）---
cp .env.example .env          # 新环境一次性：缺它 pytest 会多挂一条（见 README）
uv sync                       # 或 uv sync --frozen（lock 必须同步）
docker compose up -d          # 本地数据服务：PostgreSQL、Redis、FalkorDB、SuperTokens

uv run uvicorn campfire.main:app --reload      # HTTP
uv run taskiq worker campfire.worker:broker    # Worker，需 Redis
pnpm install && pnpm --filter @campfire/web dev # 前端（含 token 同步）

# --- 质量门禁（提交前必跑；与 CI 同一组）---
uv run ruff check . && uv run ruff format --check .
uv run mypy apps/api/src/campfire apps/api/tests   # 两个路径必须同时给，见下方说明
uv run pytest
uv run python scripts/check_design_docs.py
pnpm --filter @campfire/web lint && pnpm --filter @campfire/web typecheck
pnpm --filter @campfire/web test && pnpm --filter @campfire/web build

# --- 本地摄取（不连生产库；CLI 不暴露成服务端点）---
uv run python -m campfire.cli convert <x.html> # HTML → 可摄取 Markdown（不连库）
uv run python -m campfire.cli ingest <x.md>    # 摄取到资料库（条目与节点同事务）
```

### 页面截图（评测与验收用；落点不入 git）

```bash
# 全新环境先装浏览器（一次性；不装则下面两条都会失败，报错会提示这条命令）
pnpm --filter @campfire/web exec playwright install

pnpm --filter @campfire/web shots   # 截图：10 页 × 2 视口 × 2 图种 = 40 张 PNG + manifest.json
pnpm --filter @campfire/web e2e     # 内容断言：证明每张图「有料」而不是空态
```

**两条入口都必须跑**：`shots` 只出图，`e2e` 才验内容；**跑完 `shots` 不等于验收通过**。
落点默认 `.tmp/screenshots/`（`SHOTS_OUT` 可改），已在 `.gitignore` 的 `.tmp/` 之下。

- 删掉内容断言不影响出图（两者按 project 隔离），反之亦然——这是刻意的：
  让「图有没有截到」与「图里有没有内容」两种失败各自可见，不互相掩盖。
- **加了新路由就要加新截图配置**，否则那条路由永远不会有 PNG，
  而 `manifest` 仍会宣布「40 张」（它只验矩阵内部自洽）。
  这条对应关系由 `apps/web/tests/routes-coverage.test.ts` 机械守着，`pnpm test` 会红。

### 临时文件：只有 `.tmp/` 一个落点

**临时文件一律写 `.tmp/`**，不要新建 `tmp/`、`_tmp_test/`、`reports/` 这类并列目录，
也不要写到被 git 跟踪的目录里。理由与沿革见 `.gitignore` 开头的「单一临时目录规则」。
`.tmp/` 整个被忽略，所以**里面没有版本控制兜底**——这正是「该入库的当次入库」的压力来源。

- 过程产物（截图、trace、逐次 CI 报告、ffmpeg 分析转储）用完即弃，属**可再生**，
  清理时不需留档。
- **判据只有一条：`git ls-files .tmp` 必须为空**（该目录整个被忽略，非空即异常）。
  满足后可直接整目录清理——**`.tmp/` 里没有任何需要留档的东西**。
- **2026-10-08 用户裁决（收紧，取代此前的三条判据）**：**只有 git 库中的内容算数**，
  `.tmp/` 内的手写源码、旧修订快照、别处无副本的图片一律**不构成保留理由**。
  此前那套「含手写源码一律不删」「唯一副本要留」的判断是在系统外另立标准，
  与「唯 git 库为准」冲突，已废弃。**推论**：不要把成果留在 `.tmp/` 里等下次清理——
  该入库的当次入库，否则视为过程产物。
- 过程记录**不再单独留档**（此前的 `docs/证据/` 证物树已随同批清理删除）：
  需要复现的判据一律写进测试、脚本或 `docs/` 正文，不靠过程物证承载。


`mypy` 只传 `apps/api/tests` 会因 `conftest` 被当成两个模块而中止（
`Source file found twice under different module names`）——**始终同时传 src 与 tests 两个路径**。

测试集中在 `apps/api/tests`；历史归档树不参与收集。

**生产镜像的构建参数**（仅部署链路需要，本地不需要）：`VITE_API_DOMAIN` 是**构建期内联**
的，不是运行期环境变量。它在生产由 `PUBLIC_BASE_URL` 提供；前端会把它与当前页面
host 比较后改用 `location.origin`，因此协议跟随页面、切 HTTPS 不需要重新构建。

## 开发与部署的边界

**默认在本地完成开发闭环。部署到云端只在用户明确要求时进行。**

展开前的自检（任一不过就先补，不要拿云当验证环境）：

- [ ] 门禁全绿（上面那一组）；新行为有能失败的回归测试
- [ ] 关键路径**已用真实依赖端到端跑通**——本地起数据服务 + 真实浏览器/HTTP 走一遍，
      而不是只跑 mock 单测。**这条不是形式要求**：本项目三个 P0 都只在真实运行时暴露
      （缺 `EmailPassword.init()`、明文 HTTP 下 `crypto.randomUUID` 不存在、
      产物写死协议导致 mixed content），而单测全绿。
- [ ] 已想清回滚：改动是否可逆、是否需要迁移（迁移是唯一不可逆动作）

部署是**真实的生产变更**。发布编排（`.github/workflows/deploy.yml`）**不随本公开仓分发**：
本仓只有 CI（`ci.yml`），推送 `main` 只跑 CI、不会部署。发布与回滚的判据、命令与人工闸门
在内仓维护，需要时另取，**执行前重新核实**。

**为什么默认不自动部署**：合并代码与发布到生产风险等级不同——合并可回退，发布要动生产。
人工闸门是刻意保留的，不是没接完。**也不要绕过它手工 ssh 到服务器改文件**：那会让
「生产在跑哪个版本」失去确定答案（这条路我走过，代价是服务器源码与仓库产生漂移）。

部署后必须验收（发布流程自身已轮询 `/readyz`，这里补业务面）：

```bash
curl -fsS https://campfire.wenran.me/readyz    # 判据用 /readyz，不要用 /livez
uv run --no-project python scripts/acceptance_probe.py
```

`acceptance_probe.py` 覆盖静态资源、9 条页面**深链**、未登录 401 边界（退出码非 0 即失败）。
它只覆盖第 1 节——**登录之后的链路必须用真实浏览器**（依赖 httpOnly cookie），
完整清单（登录之后的链路）见 `docs/运维/上线验收测试流程.md`——该文件仅内部开发仓提供，
不随本公开仓分发；本仓只保留上面这条未登录可跑的探针。

**看到「发布验证失败」先判断是不是误报**，再决定回滚：曾发生「部署其实成功、
验证步骤因漏 `--env-file` 而报失败」，回滚一个正常版本会把小事变成事故。

服务端事实：`https://campfire.wenran.me`（腾讯云 HK），部署目录 `/opt/campfire`，
凭据在服务器 `.env.prod`（**不入库**，也不由发布流程上传）。CORS、域名与 TLS 的
运维脚本见 `scripts/tls-*.sh`；操作说明见 `docs/运维/发布与回滚.md`（仅内部开发仓提供，
不随本公开仓分发）。

## Architecture

```text
docs/                  — 设计根，真源（见下方 Design Docs）
apps/api/              — 唯一的 Python 应用
  skills/              — 开放标准 skill 的内容产物（不是 Python 代码）
  src/campfire/
    main.py worker.py  — HTTP 与 Worker 入口
    cli/               — 本地摄取入口，不暴露成服务端点
    agent/             — 通用 Agent 基座：产品无关，不含任何领域术语
    surfaces/          — 面：产品入口与运行装配
    tools/             — 产品侧工具，注册进基座工具池
    modules/           — 业务数据与用例：accounts、library（含检索链）、profile、memory
    core/              — 跨切能力：config、db、cache、auth、authz、jobs
  tests/
apps/web/              — React H5（React 19 + Vite + React Router + Zustand）
infrastructure/        — 生产 docker/nginx 产物（见 infrastructure/README.md）
scripts/               — 仓库级运维脚本（部署、备份、回滚）；资料摄取不在此处
docker-compose.yml     — 本地基础设施编排
docker-compose.prod.yml — 生产编排（数据服务不暴露宿主端口，仅 web 对外）
```

模块边界与依赖方向的真源是项目结构设计（`docs/项目结构设计.md`，仅内部开发仓提供、
不随本公开仓分发）。其白名单由
`apps/api/tests/test_layer_boundaries.py` 机械检查——**新增层必须同步加入该测试**，
否则检查会因「层未覆盖」而失败。

## Conventions

### 开发流程：Plan → Do → Verify

1. **Plan** — 先读 `docs/` 相关设计文档；明确成功标准；列出假设；识别影响范围；制定步骤计划。
2. **Do** — 每次只改与任务直接相关的内容；遵循已有风格；不顺手重构；不为单一场景建抽象。
3. **Verify** — 运行可运行的检查；明确报告通过、失败与未测情况。

### 目标重构与迁移

- 设计已确认，新实现按 `docs/` 落地；`archive/` 只用于辨认遗留实现与历史决策。
- 先盘点实际数据与引用、核实可恢复备份及影响范围，再分阶段建设；数据状态未知时不得以旧 ADR 的「无真实用户数据」推断可以清库。
- ❌ 禁止：从 `archive/` 复制权限模型、四层档案、行为桶或 `/api/v1` SSE 契约到新实现。
- ❌ 禁止：执行归档 `scripts/` 中的部署/重建脚本或 `docker compose down -v`；授权撤销与条目停用不得靠异步清理充当即时安全边界。

### 代码风格

- 注释用中文，变量/函数/类/文件命名用英文
- Python: ruff format + ruff check，行宽 120；TypeScript: oxlint
- ❌ 禁止：引入与本次任务无关的第三方依赖（没有消费者的依赖不预先声明）
- ❌ 禁止：为自己造成的未使用 import/变量/函数不清理

### 提交规范

**本规范自 2026-10-01 起生效，只约束此后的提交。** 历史提交保持原样——不重写、不
amend、不 rebase，即使它们的写法与本规范不符。

- commit message 的**类型前缀用英文**（Conventional Commits 标准），标题与正文仍用中文：
  `feat` / `fix` / `refactor` / `perf` / `test` / `docs` / `chore` / `build` / `ci` /
  `style`，可选**英文**作用域，如 `fix(library): 展开命中越界 limit 时改为拒绝`。
  ❌ 禁止：`update`、`fix bug`、`changes` 这类无类型、无信息的标题。
- 前缀之后的标题说明「做了什么」，正文说明「为什么」——两者都用中文。正文可写多行，
  段落之间空一行；「为什么」是给人看的判据来源，不是复述 diff。
- 每次 commit 只包含本次修改的文件
- ❌ 禁止：把多个无关主题改动塞进同一个 commit

### 数据库迁移

- 实现落地后用 `alembic revision --autogenerate` 生成迁移；迁移文件必须带中文注释说明业务意图
- ❌ 禁止：手动修改生产数据库 schema 而不通过迁移文件
- ❌ 禁止：让 `--autogenerate` 把 SuperTokens core 在自己库里建的表当成待删对象——接入迁移前必须先为其排除

### 接口与契约

- 契约真源在 `docs/技术设计/` 与各面文档；v3.0 的 `/api/v2` 契约已随基线归档，不得沿用
- 修改 API 接口、数据库 schema、公共函数签名前，先确认影响范围
- ❌ 禁止：在未确认影响范围的情况下破坏性修改已有接口

## Security

- ❌ 禁止：硬编码 API Key、密码、密钥——统一用环境变量（模板 `.env.example`，按消费者分三段标注）
- ❌ 禁止：将 `.env`、`.tmp/`、SSL 证书与私钥提交到版本控制
- ❌ 禁止：在回复中完整复述密码或服务器凭证
- ❌ 禁止：把服务器凭证上传给第三方服务
- ❌ 禁止：健康检查、日志或错误消息复述连接串与凭据（探针只回报异常类型）
- 服务器操作：**默认不做**（见上方「开发与部署的边界」）。确需运维时，脚本与判据见
  `docs/运维/发布与回滚.md`——历史服务器操作指引不随本公开仓分发，需另取内仓，
  **执行前须重新核实**，不要照抄。

## Git Workflow

- 分支策略：本公开仓只维护 `main`（唯一远端分支）；内仓的 `dev`/`master` 流程不随本仓分发
- CI（`.github/workflows/ci.yml`）在 push 与 PR 到 `main` 时跑三个 job：
  设计文档一致性、后端（ruff + mypy + 迁移门禁 + pytest，**带 PostgreSQL/Redis/FalkorDB
  三个 service**）、前端（oxlint + tsc + vitest + build）
- **部署见上方「开发与部署的边界」**——默认本地闭环，云端只在用户明确要求时发布
- 备份/恢复/回滚：`scripts/{backup,restore,rollback}.sh`（脚本在本仓；操作说明见
  `docs/运维/发布与回滚.md`，该文件仅内部开发仓提供）
- 仓库：`https://github.com/FengZhiHen1/campfire-ai-public.git`
- ❌ 禁止：把未复核的改动直接推上 `main`（本公开仓远端只有 `main`，没有 `dev` 供先行集成）
- ❌ 禁止：一个 commit 塞多个无关主题的改动
- ❌ 禁止：未经用户明确要求就触发发布（内仓的 `deploy.yml`）——那是生产变更

## Design Docs

真源在 `docs/`，入口是 [docs/README.md](docs/README.md)（文档地图与事实所有权）。

- **已确认的定调**：[技术栈设计](docs/技术栈设计.md)。需求基线（`docs/需求/功能需求与验收.md`）与项目结构设计（`docs/项目结构设计.md`）仅在内部开发仓提供，不随本公开仓分发
- **技术细节初稿，待确认**：`docs/技术设计/technical-details/` 与 `docs/技术设计/面/`
- **待办唯一登记处**：[docs/TODO.md](docs/TODO.md)（可扩展方向、发布前置、待验证事实、待确认事项）
- 未确认内容不得写入权威文档，也不得据此开始实现；发现设计不一致时先提出，不得静默沿用旧行为。
- ❌ 禁止：把历史 v3.0 设计稿（`archive/**`，不随本公开仓分发）中的「有效」「目标态」等字样当作新目标实现要求。
- ✅ 视觉契约已重建：`docs/design/` 三件套（`tokens.css` / `components.html` / `DESIGN.md`）
  与页面设计文档齐备，前端样式层以此为准（不要绕过 token 直接写死颜色与间距——`apps/web`
  的 `build` 里有契约类名断言会把关）。
- 需求与验收行的一一对应由 `scripts/check_design_docs.py` 机械检查（当前：需求 38 项、
  验收行 32 条，全部通过；脚本对「未覆盖需求」是**失败**而非告警）。**具体数字以该脚本的
  当前输出为准**，本文件不写死数字：需求基线仍在演进，写死必然漂移（本条初稿写「9 条」，
  当天即因需求新增变为 7 条）。

## Behavioral Guidelines

- 先列可观察完成标准与未验证假设；精准修改，不顺手重构、不为单一场景建抽象；跑与改动相称的检查并报告实际结果。
- ❌ 禁止：未验证就声称安全、专业认可、线上可用，或把设计草案当作真实用户数据处理授权。
- ❌ 禁止：跨层穿透（Domain/Application/ViewModel/View/Infrastructure）；授权只靠角色名、前端隐藏、Agent 扩展或缓存判断。
- ❌ 禁止：留下永远不会失败的检查、闸门或测试（提取到 0 条即应失败，而不是静默通过）。

## When to Stop and Ask

任务未授权或证据不足时先确认范围：需要破坏真实数据、修改跨模块公共契约、引入外部供应商/依赖、进行远程高风险操作或无法恢复的迁移。明确授权的设计裁决可以自主记下理由和证据边界；测试缺环境时如实报告，不编造通过。

## Checklist

- [ ] 改动仅覆盖已授权范围，已读目标文档与实际存在的代码。
- [ ] 已运行可运行的检查并报告通过、失败和未测情形；未制造未使用代码。
- [ ] 若更改授权、数据或 API，已验证影响范围与回滚门槛；对应文档已同步。
- [ ] 如需 commit，只包含本次任务文件，**英文** `type(scope):` 前缀 + **中文**标题与正文说明原因；确认未提交密钥或私钥。

<!-- Last updated: 2026-10-01 -->
