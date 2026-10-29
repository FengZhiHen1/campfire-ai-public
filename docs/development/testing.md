# 检查与测试流程（唯一流程真源）

> **状态**：2026-10-29 建立。本文是**「改完要跑什么、什么时候跑全量、跑完怎么判读」的唯一流程真源**；
> 其他文件只链接到这里，不复制命令清单。
> **它拥有**：检查分层的定义、`scripts/checks.py` 的接口契约、quick/full 各跑哪些命令、全量的触发点、
> 机器读数与失败判读口径、真模型/真栈/材料与门禁的关系。
> **它不拥有**：命令背后的工具配置（`pyproject.toml`、`apps/web/package.json`、`.github/workflows/ci.yml`）、
> 材料与评测证据口径（[materials.md](materials.md)）、泳道环境与清理（[worktree-environment.md](worktree-environment.md)）、
> 生产验收（[../运维/上线验收测试流程.md](../运维/上线验收测试流程.md)）。
> **事实依据**：各命令均取自 `pyproject.toml`（`addopts`/`testpaths`）、`apps/web/package.json`
> （`build` 内含 `tsc --noEmit`）与 `.github/workflows/ci.yml`；本文只规定流程，不新增工具行为。

---

## 1. 一句话规则

**每次提交只跑与改动相称的确定性检查（quick）；全量确定性检查（full）只在集成点与 CI 跑，
不在每个子任务、每个 commit 上跑。**

理由：全量后端测试要带上 PostgreSQL / Redis / FalkorDB 才有意义，一轮是分钟级；
把它挂到每次小改动上，代价是等待，收益接近零——回归应该由**集成点**回答，而不是由
「我刚改了一个文档链接」回答。**但集成点不能省**：省掉的是频次，不是覆盖。

## 2. 三种检查层级

| 层级 | 何时跑 | 跑什么 | 谁跑 |
|---|---|---|---|
| **quick** | 任务内每次提交前 | 与改动面相称的确定性检查（见 §3） | 子任务执行者自己 |
| **full** | 合成到 `dev` 之前、CI、以及改动公共契约/跨模块时 | 全套确定性检查（见 §4） | 集成者（主 agent）与 CI |
| **material** | 只在明确需要材料时（演示、交付、评测运行） | 真模型 + 真栈 + 真库的运行与取证 | 材料/评测任务，**不是门禁** |

三层的关系：**quick 绿不等于可以合入**，full 才是合入判据；**material 红不阻塞合入**，
它回答的是「对外材料是否真实」，由 [materials.md](materials.md) 管。任何一层都不能替代另一层。

## 3. quick：按改动面定向

接口契约（`scripts/checks.py` 由工具任务实现；本文规定语义）：

```bash
uv run python scripts/checks.py quick --base dev      # 相对 dev 的改动面
uv run python scripts/checks.py quick --base dev --dry-run   # 只打印将执行的命令，不执行
```

`--dry-run` 是给集成者复核用的：**先看它打算跑什么，再决定跑不跑**，避免用一条黑箱命令
冒充验证。`--base <ref>` 缺省为 `dev`；工作区已提交与未提交的改动都计入改动面。

| 改动面 | quick 必跑 |
|---|---|
| 后端 Python（`apps/api/src`、`apps/api/tests`） | `uv run ruff check .`；改动模块对应的定向 pytest（至少覆盖被改文件与直接调用方）；改动源码时补 mypy 两路径（§5.1） |
| 前端（`apps/web/src`、`apps/web/tests`） | `pnpm --filter @campfire/web lint`；`pnpm --filter @campfire/web test` 定向到相关文件 |
| 文档（`docs/`、`*.md`、`materials/`） | `uv run --no-project python scripts/check_design_docs.py`（相对链接、需求与验收对应） |
| 忽略/容器清单（`.gitignore`、`.dockerignore`） | `git check-ignore -v -- <新增的落点示例路径>`；`.dockerignore` 的新增项逐个核对锚定范围 |
| 路由或页面新增（`apps/web` 路由表） | 额外跑 `apps/web/tests/routes-coverage.test.ts`，**新路由必须同步加截图配置**，否则永远没有 PNG 而 manifest 仍宣布齐了 |

- **定向 pytest** 指按路径或 `-k` 收窄到受影响面，不是全量；不确定影响面时**升级为 full**，
  不要用「看着不像相关」当理由跳过。
- quick **不跑**前端 `build`（含 `tsc` 与契约 CSS 断言）——它归 full；改动到样式契约类名、
  `docs/design/tokens.css` 时例外，那条对应关系只有 `build` 会把关。

## 4. full：全套确定性检查

```bash
uv run python scripts/checks.py full          # 等价于下表全部命令
```

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy apps/api/src/campfire apps/api/tests
uv run alembic upgrade head && uv run alembic check   # 迁移门禁：模型与迁移不一致即失败
uv run pytest                                  # 需要 docker compose up -d 的数据服务在跑
uv run --no-project python scripts/check_design_docs.py
pnpm --filter @campfire/web lint
pnpm --filter @campfire/web test
pnpm --filter @campfire/web build              # 已内含 tsc --noEmit 与契约 CSS 断言
```

- **不单独跑 `pnpm typecheck`**：`build` 的第一步就是 `tsc --noEmit`，`typecheck` 只是同一份
  检查的第二次执行，不增加证据、只增加时间。**要保住这条**：任何人往 `build` 里加前置步骤
  顺手把 `tsc` 去掉，typecheck 就会静默消失。
- 迁移门禁（`alembic upgrade head` + `alembic check`）需要数据服务在跑，因此不进 quick。
- `full` 与 CI 的 job 划分一致（设计文档一致性 / 后端 / 前端），差别只在 CI 自带三个数据
  service、并在其内部 `uv sync --frozen`——**命令语义必须同源，改一处要检查另一处**。
- `full` 不跑 `shots`、`e2e`、`demo`、`e2e-real`、真实模型调用，也不跑评测运行：
  它们是 material 层，见 §6。

### 4.1 CI 策略

**CI 初期保留完整的确定性检查**（上表全部），不因为有了 `full` 就裁掉 job，也不把材料或
真实模型塞进 CI。理由：CI 是唯一「换人、换机器也照跑」的判据；等 CI 被裁到只跑子集，
本地 `full` 就成了自证。**`scripts/checks.py` 与 CI 命令清单必须同源**——改一处要检查另一处。

## 5. 命令事实与判读口径

### 5.1 mypy 必须同时给两个路径

```bash
uv run mypy apps/api/src/campfire apps/api/tests
```

只传 `apps/api/tests` 会因 `conftest` 被当成两个模块而**中止**
（`Source file found twice under different module names`）。这不是检查通过，是检查没跑成。

### 5.2 计数取机器读数，不数控制台

`pyproject.toml` 已设 `addopts = "-q --import-mode=importlib"` 与 `testpaths = ["apps/api/tests"]`，
控制台行数会随警告与摘要漂移。要计数就加 `--junitxml=<path>` 并从 XML 读
`tests/failures/errors/skipped`；**跑完还要确认这份 XML 真的收集到了用例**（按名字检索一条
本轮新增的用例为阳性对照，再用编造的名字确认检索为 0）。只有「命中真名 + 不命中假名」
同时成立，这次计数才算数。

### 5.3 失败判读

| 现象 | 正确判读 |
|---|---|
| 集成用例成批 `ConnectionRefusedError` | 数据服务没起（`docker compose ps` 核对），是环境失败，不是代码通过 |
| 用例成批 `skip` | 不等于通过；先查 skip 原因，`integration` marker 的用例必须真跑过 |
| 检查命令以「配置缺失」中止（如 `SuperTokensConfigurationError`） | 缺 `.env`（见 [README](../../README.md) 首次起步），不是代码缺陷 |
| 「0 命中 / 不存在」类结论 | 必须配阳性对照；没有对照的 0 命中按未验证处理 |
| 检查永远不可能失败（提取到 0 条也通过） | 是缺陷，按「永远不失败的检查」处理，不许留 |

**如实报告**：跑了哪些、结果如何、哪些没跑。**未跑 ≠ 通过**；不得把未验证写成已验证。

## 6. material 层：真模型、真栈与材料

按需运行，**不进 quick/full、不进 CI、不是门禁**：

| 入口 | 用途 | 前提 | 口径归属 |
|---|---|---|---|
| `pnpm --filter @campfire/web shots` + `e2e` | 页面截图与内容断言（内容断言才证明「图里有料」） | 全新环境先 `playwright install` | 本文（属前端改动检查） |
| `DEMO_INVITE_CODES=... pnpm --filter @campfire/web demo` | 对外展示材料，逐屏截图 | 全真栈稳定、`/readyz` 全 ok | [演示材料生成.md](../运维/演示材料生成.md) |
| 真实模型/真实栈探针（`e2e-real` 等） | 证明关键路径在真实依赖上能跑通 | 同上 | 本文 §6.1 |
| 评测运行（A/B/C 对照） | 效果证据 | 冻结案例集 + 人工评分 | [materials.md](materials.md) |

### 6.1 「改完就跑一遍」被明确禁止

材料只在**明确需要**时生成——即将演示、交付、或用户点名要。把它挂到每次改动之后，代价是
一批 18～40 分钟的真模型运行，而它红的原因多数是外部抖动（模型端点、网络），不是本次改动。
**改动是否可靠由 quick/full 回答，材料不参与这个回答**（2026-10-28 用户裁决）。

### 6.2 真实依赖的验证不能被单测替代

本项目三个 P0 都只在真实运行时暴露（缺 `EmailPassword.init()`、明文 HTTP 下
`crypto.randomUUID` 不存在、产物写死协议导致 mixed content），而单测全绿。因此**面向真实
使用者的改动**（认证、静态资源、SSE、部署形态）在合入前至少要真栈跑一次，并记录跑了什么。

## 7. 必须升级为 full 的情形

- 改动公共契约：API 形状、数据库 schema、公共函数签名、模块边界（`test_layer_boundaries.py` 白名单）。
- 改动跨模块：`agent/`、`core/`、`surfaces/`、多个 `modules/`。
- 改动构建链或依赖：`pyproject.toml`、`uv.lock`、`package.json`、`pnpm-lock.yaml`、CI workflow。
- 改动测试基础设施：`conftest.py`、marker、`addopts`。
- **合成到 `dev` 之前**：不论谁、不论改了什么，一次 full；这是合入判据而非形式。

## 8. 工具落地状态

`scripts/checks.py`（`quick --base dev` / `full` / `--dry-run`）由工具任务实现；本文只固定接口
语义与判据。**实现落地前**，用 §4 的命令逐条手工执行并把命令原文写进报告——不得用
「工具还没做好」当跳过检查的理由，也不得假装跑过。
