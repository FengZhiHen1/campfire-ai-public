# Campfire-AI — 篝火智答

> 面向孤独症人士及其支持网络的情境支持平台：用户可先取得已审阅的公开帮助，再围绕一件事核对 AI 草案、自主保存私人事项；经过合法核验与逐项授权后才可能共享记录、计划和交接。
> 当前仓库**只有设计，没有实现**：`docs/` 是唯一有效的设计来源；旧实现与旧设计已整体移入 `archive/`，仅作参考，不构成任何当前依据。

## Stack

目标选型（尚未落地，详见 `docs/技术设计/技术栈设计.md`）：

- Language: Python ≥3.12, TypeScript ~6.0
- Backend: FastAPI + Pydantic 2，uv 工作空间；独立 Worker
- Frontend: React 19 + Vite 8 + React Router 7 + Zustand 5；pnpm 工作空间
- Data: PostgreSQL 17 (pgvector)、Redis 7、MinIO (S3 兼容)
- Infrastructure: Docker Compose v2 + Nginx；Alembic 迁移
- Lint/Test: ruff、oxlint；pytest + pytest-asyncio

> ⚠️ 工程配置尚未按新结构重写：`pyproject.toml`、`pnpm-workspace.yaml`、`uv.lock`、
> `pnpm-lock.yaml`、`docker-compose*.yml` 仍指向已归档的 `apps/`、`packages/` 路径。
> 在这些配置更新前，下述构建/测试/迁移命令都不会成功，这是预期状态而非缺陷。

## Commands

```bash
docker compose up -d          # 仅基础设施（PG + Redis + MinIO），此命令当前仍可用
```

前端、后端与迁移命令需在新代码结构落地并更新工作空间配置后重新确定；不要照抄归档前的旧命令。

## Architecture

```
docs/               — 唯一有效设计（需求 / 技术设计 / design 视觉契约 / TODO）
archive/            — 旧实现与旧设计，废弃物，仅供参考
docker-compose.yml  — 仅本地基础设施编排
AGENTS.md           — 本文件
```

新目标结构（未落地）见 `docs/技术设计/项目结构设计.md`：后端模块 `auth`、`public_support`、`assist`、`matters`、`spaces`、`records`、`handoffs`、`plans`、`evidence`、`practice`；前端沿用 domain/application/viewModel/view/infrastructure 单向五层。

## Conventions

### 开发流程：Plan → Do → Verify

1. **Plan** — 先读 `docs/` 相关设计文档；明确成功标准；列出假设；识别影响范围；制定步骤计划。
2. **Do** — 每次只改与任务直接相关的内容；遵循已有风格；不顺手重构；不为单一场景建抽象。
3. **Verify** — 运行可运行的检查；明确报告通过、失败与未测情况。

### 目标重构与迁移

- 以 `docs/需求/`、`docs/技术设计/技术栈设计.md`、`项目结构设计.md` 和 `目标机制/` 为目标；`archive/` 只用于辨认遗留实现与历史决策。
- 先盘点实际数据与引用、核实可恢复备份及影响范围，再分阶段建设；数据状态未知时不得以旧 ADR 的“无真实用户数据”推断可以清库。
- ❌ 禁止：从 `archive/` 复制权限模型、四层档案、行为桶或 `/api/v1` SSE 契约到新实现。
- ❌ 禁止：执行归档 `scripts/` 中的部署/重建脚本或 `docker compose down -v`；授权撤销与条目停用不得靠异步清理充当即时安全边界。

### 代码风格

- 注释用中文，变量/函数/类/文件命名用英文
- Python: ruff format + ruff check，行宽 120
- TypeScript: oxlint
- ❌ 禁止：引入与本次任务无关的第三方依赖
- ❌ 禁止：为自己造成的未使用 import/变量/函数不清理

### 提交规范

- 中文 commit message，说明"做了什么"和"为什么"
- 每次 commit 只包含本次修改的文件
- ❌ 禁止：把多个无关主题改动塞进同一个 commit

### 数据库迁移

- 目标实现落地后用 `alembic revision --autogenerate` 生成迁移
- 迁移文件中必须添加中文注释说明业务意图
- ❌ 禁止：手动修改生产数据库 schema 而不通过迁移文件

### 接口与契约

- 以 `docs/技术设计/目标机制/接口契约.md` 的 `/api/v2` 为目标；旧 `/api/v1` 已归档
- 修改 API 接口、数据库 schema、公共函数签名前，先确认影响范围
- ❌ 禁止：在未确认影响范围的情况下破坏性修改已有接口

## Security

- ❌ 禁止：硬编码 API Key、密码、密钥——统一用 `.env` 环境变量
- ❌ 禁止：将 `.env`、`.tmp/`、SSL 证书与私钥提交到版本控制（`archive/` 下遗留 TLS 私钥必须保持忽略）
- ❌ 禁止：在回复中完整复述密码或服务器凭证
- ❌ 禁止：把服务器凭证上传给第三方服务
- 服务器操作详见：`archive/docs-运营/远程服务器操作指引.md`（历史资料，执行前须重新核实）

## Git Workflow

- 分支策略：`dev` 日常开发，`master` 仅保留稳定版本
- 推送 `master` 触发 CI/CD 自动部署；`dev` 不触发
- 仓库：`https://github.com/FengZhiHen1/Campfire-AI.git`
- ❌ 禁止：直接在 `master` 上开发或提交
- ❌ 禁止：一个 commit 塞多个无关主题的改动
- ⚠️ 注意：`.github/workflows/` 中的 CI 与部署流程仍引用已归档的 `apps/`、`packages/` 与 `scripts/`；在按新结构重写前它们会失败。

## Design Docs

设计或实施前按顺序阅读：
1. `docs/README.md` 与 `docs/需求/功能需求与验收.md`（业务/验收）；
2. `docs/技术设计/技术栈设计.md`、`项目结构设计.md` 与相关 `目标机制/`（目标结构、接口、授权和发布）；
3. 涉及 Web 页面时读 `docs/design/README.md`。

- ❌ 禁止：把 `archive/` 中的“有效”“目标态”等字样当作新目标实现要求。
- ❌ 禁止：未读相关设计文档就开始实现，或发现设计与目标不一致时静默沿用旧行为。
- 新增/修改/废弃能力后同步维护拥有该事实的目标文档。

## Behavioral Guidelines

- 先列可观察完成标准与未验证假设；精准修改，不顺手重构、不为单一场景建抽象；跑与改动相称的检查并报告实际结果。
- ❌ 禁止：未验证就声称安全、专业认可、线上可用，或把设计草案当作真实用户数据处理授权。
- ❌ 禁止：跨层穿透（Domain/Application/ViewModel/View/Infrastructure）；授权只靠角色名、前端隐藏、Agent 扩展或缓存判断。

## When to Stop and Ask

任务未授权或证据不足时先确认范围：需要破坏真实数据、修改跨模块公共契约、引入外部供应商/依赖、进行远程高风险操作或无法恢复的迁移。明确授权的设计裁决可以自主记下理由和证据边界；测试缺环境时如实报告，不编造通过。

## Checklist

- [ ] 改动仅覆盖已授权范围，已读目标文档与实际存在的代码。
- [ ] 已运行可运行的检查并报告通过、失败和未测情形；未制造未使用代码。
- [ ] 若更改授权、数据或 API，已验证影响范围与回滚门槛；对应文档已同步。
- [ ] 如需 commit，只包含本次任务文件，中文信息说明做什么及原因；确认未提交密钥或私钥。

<!-- Last updated: 2026-09-26 -->
