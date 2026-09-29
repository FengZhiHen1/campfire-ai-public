# Campfire-AI — 篝火智答

> **设计基线已确认；仓库有可运行的骨架，尚无业务实现。** 需求、技术栈与项目结构
> 已于 2026-09-29 经用户确认，真源在 `docs/`。`archive/` 是已废弃的旧实现与旧设计，
> 仅作参考，不构成任何当前依据。
> 当前代码只有骨架：三个运行入口可跑、健康检查逐项如实报告；各业务模块是只带
> 归属与禁令说明的占位包。

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

全部在仓库根执行。

```bash
# 依赖与质量门禁
uv sync                       # 或 uv sync --frozen（lock 必须同步）
uv run ruff check .           # 可加 --fix
uv run ruff format --check .
uv run pytest

# apps/api 的三个运行入口
uv run uvicorn campfire.main:app --reload      # HTTP
uv run taskiq worker campfire.worker:broker    # Worker，需 Redis
uv run python -m campfire.cli                  # 本地摄取，尚未实现（退出码 2）

# 设计文档一致性（与 CI 跑同一份脚本）
uv run python scripts/check_design_docs.py

# 前端与基础设施
pnpm install
docker compose up -d          # PostgreSQL、Redis、FalkorDB、SuperTokens、MinIO
```

测试集中在 `apps/api/tests`；`archive/` 不参与收集。

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
    modules/           — 业务数据与用例：accounts、library、profile、memory
    core/              — 跨切能力：config、db、cache、auth、authz、jobs、retrieval
  tests/
apps/web/              — React H5（当前只有目录占位）
infrastructure/        — docker、nginx（占位）
scripts/               — 仓库级运维脚本（部署等）；资料摄取不在此处
archive/               — 已归档实现与设计，废弃物，仅供参考
docker-compose.yml     — 本地基础设施编排
```

模块边界与依赖方向的真源是 [docs/项目结构设计.md](docs/项目结构设计.md)。其白名单由
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

- 中文 commit message，说明「做了什么」和「为什么」
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
- ❌ 禁止：将 `.env`、`.tmp/`、SSL 证书与私钥提交到版本控制（`archive/` 下遗留 TLS 私钥必须保持忽略）
- ❌ 禁止：在回复中完整复述密码或服务器凭证
- ❌ 禁止：把服务器凭证上传给第三方服务
- ❌ 禁止：健康检查、日志或错误消息复述连接串与凭据（探针只回报异常类型）
- 服务器操作详见：`archive/docs-运营/远程服务器操作指引.md`（历史资料，执行前须重新核实）

## Git Workflow

- 分支策略：`dev` 日常开发，`master` 仅保留稳定版本
- CI 在 push 与 PR 到 `dev`、`main`、`master` 时运行：设计文档一致性 + 后端 lint/测试
- **部署当前已停用**：`deploy.yml` 的作业是 `if: false`，旧链路依赖已归档的 `scripts/deploy-remote.sh`——
  推送 `master` **不会**自动部署；恢复条件见该文件顶部
- 仓库：`https://github.com/FengZhiHen1/Campfire-AI.git`
- ❌ 禁止：直接在 `master` 上开发或提交
- ❌ 禁止：一个 commit 塞多个无关主题的改动

## Design Docs

真源在 `docs/`，入口是 [docs/README.md](docs/README.md)（文档地图与事实所有权）。

- **已确认的定调**：[功能需求与验收](docs/需求/功能需求与验收.md)、[技术栈设计](docs/技术栈设计.md)、[项目结构设计](docs/项目结构设计.md)
- **技术细节初稿，待确认**：`docs/技术设计/technical-details/` 与 `docs/技术设计/面/`
- **待办唯一登记处**：[docs/TODO.md](docs/TODO.md)（可扩展方向、发布前置、待验证事实、待确认事项）
- 未确认内容不得写入权威文档，也不得据此开始实现；发现设计不一致时先提出，不得静默沿用旧行为。
- ❌ 禁止：把 `archive/` 中的「有效」「目标态」等字样当作新目标实现要求。
- ⚠️ 已知缺口：`docs/design/` 视觉契约尚未重建，前端样式层在此之前不得动工；另有若干已确认需求尚无验收行——**数量与清单以 `uv run python scripts/check_design_docs.py` 的当前输出为准**，本文件不写死数字：需求基线仍在演进，写死必然漂移（本条初稿写「9 条」，当天即因需求新增变为 7 条）。

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
- [ ] 如需 commit，只包含本次任务文件，中文信息说明做什么及原因；确认未提交密钥或私钥。

<!-- Last updated: 2026-09-29 -->
