# Campfire-AI — 篝火智答

> 为孤独症人士家庭提供智能应急咨询与干预支持服务的全栈平台。
> 基于 RAG 检索增强生成与案例库管理，帮助家属在突发危机时获得结构化、可溯源的应急建议。

<!-- Last updated: 2026-06-30 -->

## Stack

- Language: Python 3.12+ (strict), TypeScript ~6.0
- Backend: FastAPI + Uvicorn (api-server), Celery (worker)
- Frontend: React 19 + Vite 8, React Router 7
- Package manager: uv (Python), pnpm 9.x (frontend)
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
apps/worker/        — Celery 后台任务
apps/react-web/     — React 前端（主 Web 应用）
apps/mini-program/  — 微信小程序
packages/py-*/      — Python 可复用包（auth/cache/config/db/health/llm/logger/rag/schemas/security/storage）
docs/               — 设计文档与功能设计原始材料
infrastructure/     — Docker、Nginx、部署脚本
scripts/            — 工程脚本（构建、迁移、诊断等）
tests/              — 集成测试
```

> 详细架构见：`docs/篝火智答-技术栈设计.md`、`docs/篝火智答-项目结构.md`

## Conventions

### 开发流程：Plan → Do → Verify

1. **Plan** — 先读 `docs/` 相关设计文档；明确成功标准；列出假设；识别影响范围；制定步骤计划。
2. **Do** — 每次只改与任务直接相关的代码；遵循现有代码风格；不顺手重构；不为单一场景建抽象。
3. **Verify** — 运行测试或检查；确认无未使用代码、循环依赖、跨层调用；对照 #Checklist 逐项确认。

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
- 服务器操作详见：`docs/远程服务器操作指引.md`

## Git Workflow

- 分支策略：`master` 主干开发，推送后自动触发 GitHub Actions CI/CD
- 仓库：`https://github.com/FengZhiHen1/Campfire-AI.git`
- ❌ 禁止：一个 commit 塞多个无关主题的改动

## Design Docs

新功能/模块/重大改动前必读：
1. `docs/篝火智答-技术栈设计.md`
2. `docs/篝火智答-项目结构.md`
3. 与任务相关的 `docs/功能设计/原始材料/` 文件

- ❌ 禁止：未读相关设计文档就直接开始编码
- 发现设计文档与代码现状不一致时，停止编码并告知用户
- 新增/修改/废弃功能点后，同步更新对应设计文档或原始材料

## Anti-patterns

遇到以下行为必须停下来重新审视：顺手重构、过度设计（为单一场景建抽象）、未验证就声称完成、前端跨层穿透（违反 Domain/Application/ViewModel/View/Infrastructure 依赖方向）、文档与代码脱节、静默做决策、扩大范围（把用户没要求的"相关优化"一起提交）。

## When to Stop and Ask

出现以下情况停止编码，先向用户确认：
- 需求与设计文档/接口契约/代码实现矛盾
- 需要修改数据库 schema、公共 API 契约或跨模块接口
- 发现架构债务但修复它不在本次任务范围内
- 测试无法运行、环境缺失
- 需要引入新的外部依赖或修改基础设施配置
- 需要在远程服务器上执行高风险操作（详见 `docs/远程服务器操作指引.md`）

## Checklist

每次任务完成前逐项确认：

- [ ] 每行改动都能追溯到用户请求，没有无关改动
- [ ] 已阅读并遵循相关设计文档
- [ ] 已运行测试或检查，且结果通过
- [ ] 注释为中文，变量/函数/类名为英文
- [ ] 已清理自己造成的未使用 import、变量或函数
- [ ] commit 只包含本次修改的文件
- [ ] 若涉及 schema、接口或架构变更，已确认影响范围
- [ ] 若相关设计文档已过时，已告知用户或已同步更新
