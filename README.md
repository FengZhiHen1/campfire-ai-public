# 篝火智答（Campfire-AI）

面向孤独症谱系人士与其照护者的 AI 情境支持工具：把「专业建议」变成「此刻能做的几步」。

> 篝火智答不把问题回答完就结束。它先把眼前的情境问清楚，再给出当下可执行的步骤，并在情况变化时重新排序——这是它与通用问答最大的不同。

[在线体验](https://campfire.wenran.me) · [文档入口](docs/README.md) · [部署与使用](DEPLOYMENT.md) · [许可与署名](#许可与署名)

> [!IMPORTANT]
> 这是一个自成品的参赛作品级开源项目，不是通用平台：账号为邀请制，线上演示只提供邀请码，不提供开放注册。
> 本项目是软件工具，**不构成医疗建议、诊断或专业意见**；遇到自伤、伤人、走失等风险，请直接联系当地急救与专业机构。

---

## 目录

- [它解决什么问题](#它解决什么问题)
- [能做什么](#能做什么)
- [在线体验](#在线体验)
- [项目从哪来](#项目从哪来)
- [里面有什么是可复用的](#里面有什么是可复用的)
- [仓库结构](#仓库结构)
- [快速开始](#快速开始)
- [质量与验证](#质量与验证)
- [文档导航](#文档导航)
- [已知限制](#已知限制)
- [反馈、安全与贡献](#反馈安全与贡献)
- [许可与署名](#许可与署名)

## 它解决什么问题

孤独症孩子的照护者手上往往不缺知识：指南、课程、家长群里的经验都有。难的是下一步——**这些建议要怎么套到这个孩子、这个场所、此刻这几分钟里**。

「孩子在商场里捂耳哭闹，我一个人带他，他不肯跟我走，我该怎么办」这类问题，通用问答给得出「降低感官刺激、温和沟通、必要时求助」，但给不出「你能腾出的手只有一只、他一步都不肯移动」条件下的取舍。

篝火智答针对的正是这一步：把专业知识、个体差异与现场约束放进同一次判断，输出照护者当下能执行的动作序列，而不是一段正确但落不了地的说明。

三个现实约束决定了它的形态：

- 使用者是手持手机的照护者，常常就在事发现场——所以是移动端优先的 H5，而不是桌面工作台；
- 照护信息持续变化——所以产品记住的是「这次情境 + 历次真正奏效的做法」，不是一次性的问答记录；
- 涉及儿童与家庭信息——所以档案条目必须可见、可确认、可纠正、可删除，推断只进「待确认」层。

## 能做什么

| 能力 | 使用者拿到的结果 |
| --- | --- |
| **日常咨询** | 用自然语言说清困扰，系统多轮澄清、检索专业知识与既往案例、流式给出分步建议并标注来源；刷新后可回到原会话继续。 |
| **应急支持** | 出现当场难以应对的状况时进入专门入口：先按医疗、基线偏离、沟通、环境、既往策略与安全六层做判断，再产出一张分节的现场行动卡——现在做什么、观察什么、什么时候升级求助。 |
| **个体档案** | 把对话中出现过的信息整理成档案条目，区分可直接采信的稳定层与待你确认的候选层；可补充、纠正、归档。 |
| **长期记忆** | 跨会话记住有效做法与偏好，可查看、可删除；删除同时清理检索侧痕迹。 |
| **来源可追溯** | 回答里的知识与案例能回到出处；资料被撤下后，相关引用一并失效。 |
| **明确的边界** | 不做诊断、不给用药建议；触及风险时引导至专业求助渠道，而不是自行处置。 |

配套的工程验证与场景评测在 `evaluation/carebench/`（见[质量与验证](#质量与验证)）。

## 在线体验

产品地址：<https://campfire.wenran.me> —— 手机与桌面浏览器均可打开。

- 账号为邀请制，邀请码由团队成员发放，公开仓库不提供通用体验账号；
- 建议先用一条虚构情境走完「日常咨询 → 补充条件 → 应急入口 → 查看档案与历史会话」这条路径，就能看到产品与通用问答的差别；
- **请只输入虚构信息**：不要填写孩子的真实姓名、诊断、学校、住址或联系方式。演示环境会定期清理数据，但仍请按不可信环境对待。

## 项目从哪来

篝火智答来自 **168 小时公益实践、七组深度访谈与早期产品的真实反馈**，在此之前团队在一线陪伴与家长沟通中反复看到同一个落差：专业知识能被检索到，却很难被落成行动。

这之后产品经历了三代演进，每一代都由同一批真实使用场景推动：

1. **V1 检索问答**：把专业知识做成可检索、可引用的回答；
2. **V2 情境应急支持**：加入现场观察与应急链路，开始输出结构化的行动建议；
3. **V3 领域智能体**：把领域经验沉淀为可激活的 Skill、受服务端约束的工具权限、可信的信息分层与结构化的行动输出。

团队规模很小，靠「自主设计 + AI Agent 辅助实现 + 人工审定与实机验收」的闭环把这条路径走完；产品定位、架构取舍、领域规则与交付验收始终由团队自己把握。

## 里面有什么是可复用的

如果你在做垂直领域的 Agent 应用，这几处比产品界面更值得读：

- **领域 Skill 与工具权限**（`apps/api/skills/`）：四个 Skill —— 日常咨询、应急咨询、建档整理、首次引导 —— 各自声明可用的工具集合；工具白名单在服务端执行，模型说不动它。
- **知识与案例的融合检索**（`apps/api/src/campfire/modules/library/`）：资料库与案例库分治，检索结果带出处，撤下可传播到引用侧。
- **信息分层的个体档案**（`modules/profile/`）：陈述直接进稳定层、推断只进候选层并标注来源，等使用者确认。
- **结构化应急输出**（`tools/emergency_card.py` 与 `skills/emergency-consulting/`）：六层判断 + 七节行动卡；卡片字段由参数模型校验，不靠提示词自觉。
- **可复现的场景评测**（`evaluation/carebench/`）：同一批合成情境在多种系统装配下跑同一套协议，保留轨迹、评分与核验工件。

## 仓库结构

```text
apps/api/                  FastAPI 应用：HTTP 入口、Worker、cli（摄取与运营命令）
  skills/                  领域 Skill 内容（SKILL.md + references，开放标准格式）
  src/campfire/
    agent/                 通用 Agent 基座：运行编排、skill 机制、工具池与权限门
    modules/               业务模块：accounts、library（检索链）、profile、memory
    surfaces/consult/      咨询面：HTTP/SSE 契约与生产装配
    tools/                 产品侧工具（10 个）
apps/web/                  React H5（React 19 + Vite），一期只交付手机端
data/                      冷启动语料：资料库与案例库的摄取入参（含许可结论，见 data/README.md）
docs/                      设计文档：技术栈、技术设计与决策记录、视觉契约
evaluation/carebench/      场景评测工具与协议（合成案例、运行记录、核验）
infrastructure/            生产编排的 Docker/Nginx 产物
scripts/                   仓库级脚本（设计文档一致性检查、部署辅助）
docker-compose.yml         本地开发用数据服务编排（PostgreSQL、Redis、FalkorDB、SuperTokens）
```

## 快速开始

### 环境要求

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Python | ≥ 3.12 | 包管理用 [uv](https://docs.astral.sh/uv/) |
| Node | ≥ 20 | CI 跑 22 |
| pnpm | 见根 `package.json` 的 `packageManager` | 不要另写版本号，必然漂移 |
| Docker | Compose v2 | 本地数据服务 |
| 模型服务 | OpenAI 兼容接口 | 对话与嵌入各需要一个模型名；可用任意兼容网关 |

### 1. 克隆与配置

```bash
git clone https://github.com/FengZhiHen1/campfire-ai-public.git
cd campfire-ai-public
cp .env.example .env
```

`.env` 不入库。至少需要确认三件事：

- `SUPERTOKENS_API_KEY` 必须与容器侧一致（不一致时 SDK 在注册第一步就失败）；
- `TOKENHUB_BASE_URL` / `TOKENHUB_API_KEY` / `MODEL_NAME` 指向一个支持流式与 tool calls 的 OpenAI 兼容端点；
- `EMBEDDING_MODEL_NAME` 的维度是固定的，换模型要整库重建。

本公开仓只维护 `main` 一条分支，克隆即用，无需切换。

### 2. 起数据服务

```bash
docker compose up -d          # PostgreSQL、Redis、FalkorDB、SuperTokens，端口只绑回环
uv sync
uv run alembic upgrade head   # 注册与检索都依赖迁移后的 schema
```

### 3. 起后端与前端

```bash
uv run uvicorn campfire.main:app --reload          # http://localhost:8000
uv run taskiq worker campfire.worker:broker        # 需要队列任务时再起

pnpm install
pnpm --filter @campfire/web dev                    # http://localhost:5173
```

### 4. 验证成功

```bash
curl -s http://localhost:8000/readyz
```

全部探针为 `ok` 时返回 200（否则 503，`/health` 给出同一份诊断，`/livez` 只看进程存活）。浏览器打开 <http://localhost:5173> 应看到登录页。

### 5. 第一个账号与第一批语料

注册需要邀请码，邀请码由 CLI 签发：

```bash
uv run python -m campfire.cli invite issue
```

资料与案例通过同一个 CLI 摄取（一步一个事务，失败整份回滚）：

```bash
uv run python -m campfire.cli ingest data/knowledge/autism-corpus/nhc-0-6-autism-screening-intervention.md
uv run python -m campfire.cli ingest data/cases/2026-11-06_1000_fictional-supermarket-meltdown --library case
```

### 6. 常用门禁

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy apps/api/src/campfire apps/api/tests   # 两个路径必须同时给
uv run pytest
uv run python scripts/check_design_docs.py
pnpm --filter @campfire/web lint && pnpm --filter @campfire/web typecheck
pnpm --filter @campfire/web test && pnpm --filter @campfire/web build
```

页面截图与内容断言要先装浏览器（一次性）：

```bash
pnpm --filter @campfire/web exec playwright install
pnpm --filter @campfire/web shots   # 只出图
pnpm --filter @campfire/web e2e     # 断言图里「有料」，不是空态
```

两条都要跑；落点默认在 `.tmp/screenshots/`，不入库。更细的环境差异与踩坑（缺 `.env` 的连带失败、mypy 双路径、Playwright 首次安装）见 [`apps/web/README.md`](apps/web/README.md) 与 [`docs/development/testing.md`](docs/development/testing.md)。

## 质量与验证

- **CI 三个 job**（`.github/workflows/ci.yml`）：设计文档一致性（相对链接、需求与验收一一对应、视觉契约 token）、后端（ruff + ruff format --check + mypy + `alembic upgrade head` + 迁移漂移检查 + pytest）、前端（oxlint + tsc + vitest + build）。
- **测试规模**（2026-10-30 记录，会随开发漂移，以 CI 当前输出为准）：后端 2,331 项、前端 604 项，另有真实浏览器的端到端验收记录。
- **场景评测 CareBench**（`evaluation/carebench/`）：40 个合成情境、120 组案例—系统组合、138 个预定对话回合，双 AI 独立评分加 18 项分歧裁定，协议与冻结工件随仓发布。**AI 评分不构成专家背书**，工具链自身的局限登记在 [`evaluation/carebench/interactive/HISTORY-LIMITATIONS.md`](evaluation/carebench/interactive/HISTORY-LIMITATIONS.md)。

## 文档导航

| 想了解 | 去哪里 |
| --- | --- |
| 文档总入口与事实归属 | [`docs/README.md`](docs/README.md) |
| 技术选型与版本基线 | [`docs/技术栈设计.md`](docs/技术栈设计.md) |
| 领域机制与接口契约 | [`docs/技术设计/`](docs/技术设计/) |
| 视觉契约与设计令牌 | [`docs/design/DESIGN.md`](docs/design/DESIGN.md) |
| 本地与容器化运行 | [`DEPLOYMENT.md`](DEPLOYMENT.md) |
| 领域 Skill 的写法与约定 | [`apps/api/skills/README.md`](apps/api/skills/README.md) |
| 语料来源、许可结论与重建方式 | [`data/README.md`](data/README.md) |
| 评测协议与运行方式 | [`evaluation/carebench/README.md`](evaluation/carebench/README.md) |
| 维护承诺、安全闸门与已知边界 | [`MAINTENANCE.md`](MAINTENANCE.md) |
| 给 AI Agent 的编码规范 | [`AGENTS.md`](AGENTS.md) |

## 已知限制

如实列出，不隐藏：

- **邀请制**：没有开放注册与公开演示账号；想自己跑起来需要自备模型服务凭据。
- **单机部署**：编排面向单台服务器；没有多副本、限流集群与异地容灾。
- **上下文压缩未接线**：压缩记账端口尚无持久化实现，长会话的窗口会退化为全量历史——方向安全（不丢内容），但成本更高。
- **评测口径有限**：CareBench 的 40 例测的是整理过的单轮输入，未覆盖真实应急入口下的口语与碎片表达；评分由 AI 执行，仍需专业复核。
- **语料不完整**：真实访谈案例与部分第三方语料因授权范围不足不随本仓分发（逐条原因见 [`NOTICE`](NOTICE) 第三节）。
- **面向真实使用者前仍有闸门**：发布前置事项登记在 [`docs/TODO.md`](docs/TODO.md)。

## 反馈、安全与贡献

- **问题与建议**：请开 [Issue](https://github.com/FengZhiHen1/campfire-ai-public/issues)，附上复现步骤、期望与实际结果、环境版本。涉及儿童或家庭的具体信息请先改写为虚构情境。
- **安全漏洞**：**不要**通过公开 Issue 披露，按 [`SECURITY.md`](SECURITY.md) 的方式私下报告。
- **贡献**：欢迎修复与改进，开始前请读 [`CONTRIBUTING.md`](CONTRIBUTING.md)；领域相关的内容改动（Skill 文案、行动卡字段、档案规则）请先开 Issue 说明意图，这类改动涉及专业判断，不接受只改措辞的静默提交。
- **医疗与法律边界**：本项目不提供诊断、治疗或用药建议，也不替代专业机构的评估。

## 许可与署名

| 范围 | 许可 / 声明 | 文件 |
| --- | --- | --- |
| 代码、提示词与文档 | Apache License 2.0 | [`LICENSE`](LICENSE) |
| 语料层（`data/knowledge/`、`data/cases/`） | 分层声明，逐件义务见署名清单 | [`LICENSE-DATA`](LICENSE-DATA)、[`ATTRIBUTION.md`](ATTRIBUTION.md) |
| 第三方组件与分发边界 | 组件许可、弱著佐权声明、不随仓分发的资源 | [`NOTICE`](NOTICE) |

引用或再分发前请分别核对这三处：代码的许可不覆盖语料，语料中标注「可引用」也不等于「可再分发」。

## 致谢

感谢一线公益机构与参与访谈、试用并提出批评的照护者——这个产品的判断标准几乎全部来自他们。

本项目构建在 OpenAI Agents SDK、LlamaIndex、Graphiti、FastAPI、React、PostgreSQL/pgvector、Redis、FalkorDB、SuperTokens、Taskiq 等开放技术之上；开放生态承担了通用能力，团队的工作集中在场景建模、Skill 与工具权限契约、检索与来源治理、个体信息分层与结构化交付。
