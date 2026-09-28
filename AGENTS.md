# Campfire-AI — 篝火智答

> 面向孤独症人士及其支持网络的情境支持平台：用户可先取得已审阅的公开帮助，再围绕一件事核对 AI 草案、自主保存私人事项；经过合法核验与逐项授权后才可能共享记录、计划和交接。
> 当前代码仍以旧档案/应急链路为主；`docs/` 中的 v3 设计是迁移目标，不是已落地功能。

## Stack

- Language: Python 3.12+ (strict), TypeScript ~6.0
- Backend: FastAPI + Uvicorn (api-server)，后台 Worker（Redis 队列消费）
- Frontend: React 19 + Vite 8, React Router 7
- Package manager: uv (Python), pnpm 10.x (frontend)
- Database: PostgreSQL 17 (pgvector), Redis 7-alpine
- Storage: MinIO (S3-compatible)
- Infrastructure: Docker Compose (dev + prod)
- Migration: Alembic
- Lint: ruff (Python), oxlint (frontend)
- Test: pytest + pytest-asyncio

## Commands

```bash
# 开发环境
docker compose up -d                           # 启动基础设施（PG + Redis + MinIO）
cd apps/react-web && pnpm dev                  # 前端开发服务器

# 测试
uv run pytest                                  # 后端测试
uv run ruff check .                            # Python 代码检查
cd apps/react-web && pnpm lint                 # 前端代码检查
cd apps/react-web && pnpm build                # 前端类型检查 + 构建

# 数据库迁移
uv run alembic revision --autogenerate         # 生成迁移
uv run alembic upgrade head                    # 执行迁移
```

## Architecture

```
apps/api-server/    — FastAPI REST API 入口
apps/worker/        — 后台任务（Redis 队列消费）
apps/react-web/     — React 前端（主 Web 应用）
apps/mini-program/  — 微信小程序（MVP 期冻结，见 ADR-014）
packages/py-*/      — Python 可复用包（auth/cache/config/db/health/llm/logger/rag/schemas/security/storage；llm 待退役，勿用于新代码）
docs/               — 设计文档与功能设计原始材料
infrastructure/     — Docker、Nginx、部署脚本
scripts/            — 工程脚本（构建、迁移、诊断等）
tests/              — 集成测试
```

> 新目标入口：`docs/README.md`、`docs/技术设计/技术栈设计.md`、`docs/技术设计/项目结构设计.md`；旧 `总体架构.md` 和 `项目结构/` 仅作现状与迁移对照。

## Conventions

### 开发流程：Plan → Do → Verify

1. **Plan** — 先读 `docs/` 相关设计文档；明确成功标准；列出假设；识别影响范围；制定步骤计划。
2. **Do** — 每次只改与任务直接相关的代码；遵循现有代码风格；不顺手重构；不为单一场景建抽象。
3. **Verify** — 运行测试或检查；确认无未使用代码、循环依赖、跨层调用；对照 #Checklist 逐项确认。

### 目标重构与迁移

- 以 `docs/需求/`、`docs/技术设计/技术栈设计.md`、`项目结构设计.md` 和 `目标机制/` 为目标，旧机制文档仅供现状及迁移对照。
- 先盘点实际数据与引用、核实可恢复备份及影响范围，再用迁移文件分阶段替换；数据状态未知时不得以旧 ADR 的“无真实用户数据”推断可以清库。
- ❌ 禁止：执行旧重构计划中的 `docker compose down -v` 或静默删除历史记录；授权撤销与条目停用不得靠异步索引清理充当即时安全边界。
- ❌ 禁止：因迁就旧实现保留与目标冲突的权限模型，也禁止为追求新结构绕过验证和回滚门槛。

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

- 优先用 `alembic revision --autogenerate` 生成迁移
- 迁移文件中必须添加中文注释说明业务意图
- ❌ 禁止：手动修改生产数据库 schema 而不通过迁移文件

### 接口与契约

- 修改 API 接口、数据库 schema、公共函数签名前，先确认影响范围
- 新增模块时考虑是否需要补充或更新契约文档
- ❌ 禁止：在未确认影响范围的情况下破坏性修改已有接口

## Security

- ❌ 禁止：硬编码 API Key、密码、密钥——统一用 `.env` 环境变量
- ❌ 禁止：将 `.env`、`.tmp/`、SSL 证书提交到版本控制
- ❌ 禁止：在回复中完整复述密码或服务器凭证
- ❌ 禁止：把服务器凭证上传给第三方服务
- 服务器操作详见：`docs/运营/远程服务器操作指引.md`

## Git Workflow

- 分支策略：`dev` 日常开发，`master` 仅保留稳定版本
- 推送 `master` 触发 CI/CD 自动部署；`dev` 不触发
- 仓库：`https://github.com/FengZhiHen1/Campfire-AI.git`
- ❌ 禁止：直接在 `master` 上开发或提交
- ❌ 禁止：一个 commit 塞多个无关主题的改动

## Design Docs

新能力实施前按顺序阅读：
1. `docs/README.md` 与 `docs/需求/功能需求与验收.md`（业务/验收）；
2. `docs/技术设计/技术栈设计.md`、`项目结构设计.md` 与相关 `目标机制/`（目标结构、接口、授权和发布）；
3. 涉及 Web 页面时读 `docs/design/README.md`，涉及迁移时再读旧 `技术设计/机制/`、`总体架构.md` 作差异对照。

- ❌ 禁止：把旧 ADR 的“有效”、旧四层档案、行为桶或 `/api/v1` SSE 误认为新目标实现要求。
- ❌ 禁止：发现目标设计与现有代码不一致就静默用旧行为完成新需求；记录差异，按授权范围提出或执行迁移。
- 新增/修改/废弃能力后同步维护拥有该事实的目标文档；旧文档只需标注历史偏差，不另造第二份需求定义。

## Behavioral Guidelines

- 先列可观察完成标准与未验证假设；精准修改，不顺手重构、不为单一场景建抽象；跑与改动相称的检查并报告实际结果。
- ❌ 禁止：未验证就声称安全、专业认可、线上可用，或把设计草案当作真实用户数据处理授权。
- ❌ 禁止：前端跨 Domain/Application/ViewModel/View/Infrastructure 层穿透；新授权只靠角色名、前端隐藏、Agent 扩展或缓存判断。

## When to Stop and Ask

任务未授权或证据不足时先确认范围：需要破坏真实数据、修改跨模块公共契约、引入外部供应商/依赖、进行远程高风险操作或无法恢复的迁移。明确授权的设计裁决可以自主记下理由和证据边界；测试缺环境时如实报告，不编造通过。

## Checklist

- [ ] 改动仅覆盖已授权范围，已读目标文档与必要的旧代码/迁移对照。
- [ ] 已运行相称的检查并报告通过、失败和未测情形；未制造未使用代码。
- [ ] 若更改授权、数据或 API，已验证影响范围与回滚门槛；对应文档已同步。
- [ ] 如需 commit，只包含本次任务文件，中文信息说明做什么及原因。

<!-- Last updated: 2026-09-26 -->
