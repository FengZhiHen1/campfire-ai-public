# 篝火智答 · Campfire-AI

**让专业知识走进真实照护情境，让每一步支持更加清晰、可执行。**

篝火智答是一款面向孤独症人士及其家庭、教师和支持者的**开源领域智能体应用**。项目围绕真实照护中的情境差异和行动困难，将 AI 对话、专业资料、个体信息与任务化工具结合，提供日常咨询、应急情境支持和持续信息管理。

**[在线体验](https://campfire.wenran.me)** · **[快速开始](#本地运行)** · **[核心技术](#核心技术与自主实现)** · **[开源许可](#开源与数据许可)**

> 项目参加第八届全球校园人工智能算法精英大赛「AI+开源」主题赛。在线产品采用赛事体验邀请码注册和登录；体验时请只使用虚构信息，不要输入孩子的真实姓名、诊断、学校或联系方式。

## 从真实需求出发

孤独症照护中的很多问题都有鲜明的现场条件：孩子当时的沟通方式、环境中的刺激、照护者是否能够离开、周围能否获得其他支持。这些差异会影响建议能否真正执行。

团队与一家孤独症障碍者综合服务中心（下称合作机构）持续开展需求研究和产品交流：

- **2026 年 1 月**，依托「化身篝火，伴你观星」实践团开展课程支持、陪伴与现场观察，实践团累计服务 **168 小时**。
- 通过 **P1—P7 七组深度访谈**，了解机构工作人员、专业教师、家庭照护者与公益参与者在信息获取、临场行动和持续记录方面的需求。
- **2026 年 5 月**，项目团队与合作机构签署《公益合作意向确认函》，围绕专业场景输入、AI 工具试用反馈及公益应用探索建立书面合作基础。
- **2026 年 5 月**，团队在合作机构开展 V2 产品线下体验，**7 位教师与家长参与**。关于首次使用引导、家庭描述中的主观判断等反馈，推动了 V3 的任务化入口与情境澄清机制。

项目沿着 **V1 检索增强问答 → V2 情境应急支持 → V3 领域 Agent** 的路径迭代。真实场景的需求持续进入产品设计和工程实现。

## 可以用篝火智答做什么

| 场景 | 产品能力 |
| --- | --- |
| **日常咨询** | 用自然语言描述照护问题，进行连续对话，结合现场条件获得分步建议 |
| **应急支持** | 通过任务化入口整理关键现场信息，生成包含行动、观察和求助条件的结构化行动卡 |
| **专业资料与案例** | 检索专业知识与案例，记录来源和资料有效状态，为回答组织提供依据 |
| **个体档案与长期记忆** | 区分已确认事实与候选信息，支持确认、纠正和持续会话中的背景使用 |
| **移动端使用** | 通过 React H5 访问，支持流式响应、历史会话与状态恢复 |

### 一段实际的连续咨询

在 **2026 年 10 月 29 日**的历史浏览器验收中，团队使用虚构商场情境测试连续咨询：一位照护者独自陪伴孩子，现场嘈杂，孩子捂耳哭闹且不愿移动。

首轮回答提出了现场减刺激、陪伴和观察建议。第二轮用户进一步补充：

> 我没法离开孩子去找工作人员，他也不肯走到安静处。请把建议缩成我留在他身边就能做的两三步。

系统的实际回答以 **「好，就三步，全部原地做」** 开头，将建议调整为原地减少刺激、简化沟通和持续观察，并保留求助说明。该次验收还完成了两轮流式交互和刷新后的历史恢复。

这一例子体现了篝火智答对**新增现场约束的跨轮响应和行动组织**。应急入口另有独立的结构化行动卡流程。

## 核心技术与自主实现

篝火智答建立在成熟开源基础设施之上，团队围绕照护场景研发了四组相互衔接的业务机制。

| 自主工程机制 | 实现重点 |
| --- | --- |
| **领域 Skill 与服务端工具授权** | 按任务激活领域 Skill，维护能力与工具范围；服务端根据实际激活状态决定工具能否执行 |
| **知识／案例融合检索与来源治理** | 综合向量和字面检索，管理资料来源、适用范围、撤下状态及引用索引 |
| **可信个体档案与长期记忆** | 将稳定事实与待确认信息分层管理，支持用户确认、纠错和跨轮背景使用 |
| **六层情境检查与七节行动卡** | 围绕风险、个体基线、沟通、环境、既往策略和安全支持收集关键条件，由业务工具生成并校验结构化行动结果 |

在运行链路中，**Agent 负责理解与规划，领域 Skill 组织专业能力，服务端执行工具权限和数据契约，移动端交付可阅读的任务结果**。

### 技术组成

| 层次 | 主要技术 |
| --- | --- |
| 前端 | React、TypeScript、Vite、React Router、Zustand |
| 后端 | Python、FastAPI、Pydantic、Taskiq |
| Agent 运行 | OpenAI Agents SDK 与团队开发的 Skill、工具派发和任务集成机制 |
| 检索与记忆 | LlamaIndex、PostgreSQL / pgvector、Graphiti、FalkorDB |
| 认证与缓存 | SuperTokens、Redis |
| 部署 | Docker Compose、Nginx |
| 模型服务 | 通过 OpenAI 兼容接口连接远程对话和嵌入模型服务 |

项目的技术贡献集中在**领域能力激活、受控工具执行、可信数据使用与结构化交付**的协同实现。开发者可以从[领域 Skill 内容](apps/api/skills/README.md)、[设计文档索引](docs/README.md)与 [Agent 开发约定](AGENTS.md) 进一步了解接口和工程组织。

## 工程实现与验证

项目具备后端单元／集成测试、前端组件及交互测试、浏览器验收与生产链路记录。

**2026 年 10 月 29 日冻结的工程验收结果：**

| 项目 | 结果 |
| --- | ---: |
| Python 自动化测试 | **2,331 项通过** |
| 前端自动化测试 | **604 项通过**，覆盖 **58 个测试文件** |
| 确定性工程验收 | **10 项完成** |

上述统计取自内部开发仓当日冻结的验收批次（该提交不在本公开仓的历史中，无法直接 checkout 复核），其中包含未授权工具拒绝、撤下资料过滤、行动卡参数校验、流式对话和历史恢复等具有明确业务含义的检查点。**本仓当前的实际测试状态，以重新执行测试与 CI 结果为准。**

项目同时提供 [CareBench 场景评测工具](evaluation/carebench/README.md)，用于组织合成案例、运行轨迹和评价记录，支持研发过程中的情境测试与问题复盘。评测由两套 AI 独立评分并做分歧裁定，**AI 评分不构成专业背书**。

## 本地运行

仓库包含完整的前后端应用、领域 Skill、数据库与部署配置。以下是开发环境的最短路径。

### 运行环境

- Python **3.12 或更新版本**，使用 [uv](https://docs.astral.sh/uv/) 管理依赖。
- Node.js **≥ 20**（CI 固定 22）与 [pnpm](https://pnpm.io/)（仓库固定为 `pnpm@10.33.0`）。
- Docker 与 Docker Compose v2。
- 可用的对话及嵌入模型服务凭据，按[环境变量模板](.env.example)配置。

### 1. 获取项目并准备配置

```bash
git clone https://github.com/FengZhiHen1/campfire-ai-public.git
cd campfire-ai-public
cp .env.example .env
```

编辑 `.env`，填写模型接口、数据库及认证所需配置。`.env` 已由 Git 忽略，真实凭据只保留在本地或部署环境。

### 2. 启动基础设施

```bash
docker compose config
docker compose up -d postgres redis falkordb supertokens
uv run alembic upgrade head
```

这四项是本地开发使用的数据及认证服务；迁移是注册与检索的前置。前后端应用在宿主机启动；附件对象存储是单独的扩展组件，一期默认不启动。

### 3. 启动后端

```bash
uv sync
uv run uvicorn campfire.main:app --reload
```

需要运行异步任务时，可在另一终端启动：

```bash
uv run taskiq worker campfire.worker:broker
```

首次注册需要邀请码，由 CLI 签发：

```bash
uv run python -m campfire.cli invite issue
```

### 4. 启动前端

```bash
pnpm install
pnpm --filter @campfire/web dev
```

随后按终端输出访问本地 H5 页面（默认 <http://localhost:5173>，后端在 <http://localhost:8000>，就绪判据是 `/readyz` 返回 200）。数据库迁移的更多方式、生产配置与运行环境要求详见[部署与使用说明](DEPLOYMENT.md)和[生产部署产物](infrastructure/README.md)。

## 运行测试

在仓库根目录执行：

```bash
# Python：静态检查、类型检查、测试
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api/src/campfire apps/api/tests
uv run pytest

# 前端：代码质量、类型、测试与构建
pnpm --filter @campfire/web lint
pnpm --filter @campfire/web typecheck
pnpm --filter @campfire/web test
pnpm --filter @campfire/web build

# 设计与验收文档的一致性检查
uv run python scripts/check_design_docs.py
```

部分集成测试需要本地基础设施和有效环境变量；`mypy` 必须同时给出源码与测试两个路径，否则会因 `conftest` 模块重名而中止。浏览器验证使用 Playwright：

```bash
pnpm --filter @campfire/web exec playwright install
pnpm --filter @campfire/web shots
pnpm --filter @campfire/web e2e
```

`shots` 只出图，`e2e` 才验内容——两条都要跑。CI 的工作流见 [CI 配置](.github/workflows/ci.yml)。

## 仓库导航

| 路径 | 内容 |
| --- | --- |
| [`apps/api/`](apps/api/) | FastAPI 服务、Agent 运行时、业务模块、Worker 与测试 |
| [`apps/web/`](apps/web/) | React H5、界面组件和前端测试 |
| [`apps/api/skills/`](apps/api/skills/) | 日常咨询、应急支持、个体资料整理与首次引导 Skill |
| [`data/`](data/) | 可公开分发的资料、合成示例及其来源记录 |
| [`evaluation/carebench/`](evaluation/carebench/) | 情境评测工具与相关工程资料 |
| [`docs/`](docs/README.md) | 技术栈、领域机制与接口契约、视觉契约、设计决策（需求基线不在本仓） |
| [`infrastructure/`](infrastructure/README.md) | 镜像、Nginx 与部署产物 |
| [`scripts/`](scripts/) | 工程检查、辅助验证及维护脚本 |

开发协作与约定请阅读 [AGENTS.md](AGENTS.md)；部署细节请阅读 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 已知限制

- **邀请制**：没有开放注册与通用演示账号，自己部署时需要自备模型服务凭据；
- **单机部署**：可用性取决于单台服务器，没有多副本、集群限流与异地容灾；
- **上下文压缩未接线**：长会话的上下文窗口会退化为全量历史，成本更高（方向安全，不丢内容）；
- **评测与语料有边界**：CareBench 的 40 例是整理过的单轮输入，评分由 AI 执行；真实访谈案例与部分第三方语料因授权范围不足不随仓分发（逐条原因见 [NOTICE](NOTICE)）。

完整清单与发布前置见[设计待办](docs/TODO.md)。

## 开源与数据许可

本项目的代码及相应授权内容以 **[Apache License 2.0](LICENSE)** 发布。语料、案例与第三方材料按其各自的来源及授权范围管理：

- [LICENSE](LICENSE)：项目代码许可；
- [LICENSE-DATA](LICENSE-DATA)：语料层授权说明；
- [ATTRIBUTION.md](ATTRIBUTION.md)：已分发第三方材料的来源与署名；
- [NOTICE](NOTICE)：第三方组件声明与分发边界；
- [MAINTENANCE.md](MAINTENANCE.md)：项目维护方式与已知边界。

公开仓库包含可分发的源代码、工程文档及合成演示资料。真实家庭、访谈对象和儿童相关信息按实际授权范围管理，不随本仓分发。

**使用说明：** 篝火智答提供照护信息整理和情境支持，**不构成医疗建议、诊断或专业意见**。涉及医疗诊断、紧急安全风险或需要专业干预的情形，请联系相应专业人员及当地紧急服务。

## 参与交流

欢迎开发者围绕领域 Skill、受控工具、可信检索、个体信息管理和移动端体验进行交流，也欢迎通过 [GitHub Issues](https://github.com/FengZhiHen1/campfire-ai-public/issues) 反馈问题、提出改进建议。开始前请阅读[参与指南](CONTRIBUTING.md)；安全问题请按[安全策略](SECURITY.md)私下报告，不要开公开 Issue。

**[体验篝火智答](https://campfire.wenran.me)** · **[查看源代码](https://github.com/FengZhiHen1/campfire-ai-public)**

---

*Campfire-AI / 篝火智答*
