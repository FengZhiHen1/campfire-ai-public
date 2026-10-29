# 隔离泳道（worktree）与环境指南

> **状态**：2026-10-29 重写（原版 2026-10-07 合回，本版按当前 Linux 开发环境与「主 agent 集成」
> 的工作方式改写）。
> **本版删除了两类已不适用内容**：Windows / PowerShell / Memurai 时期的环境记录（当前环境是
> Linux + compose 自带的 Redis），以及对 dev-orchestrator skill 与 `worktree_env.py` 的硬依赖
> （那个脚本在本仓不可用，判据改为用仓库自带命令机械复核）。需要追溯旧记录时用
> `git log --follow -- docs/development/worktree-environment.md`。
> **它拥有**：泳道的落点、创建/使用/集成/清理的规则，源码与依赖的隔离边界，数据与测试能否
> 并行的判据，就绪与出场的机械核验。
> **它不拥有**：检查分层的命令（[testing.md](testing.md)）、材料与证据落点（[materials.md](materials.md)）、
> 数据服务编排（[docker-compose.yml](../../docker-compose.yml)）、生产发布（[../运维/发布与回滚.md](../运维/发布与回滚.md)）。
> 冲突时以拥有者为准。

---

## 1. 基线与分支

| 项 | 规则 |
|---|---|
| 基线 | **主工作区（原始仓库根）的 `dev` 是唯一集成基线**。所有任务分支从 `dev` 起，合回 `dev` |
| 任务分支 | `task/<主题>`（如 `task/dev-standards`），一个任务一条，不共用 |
| ❌ 禁止 | 在 `main` / `master` 上直接开发或提交；把 `master` 当开发分支；不经 review 直接改主工作区 `dev` |
| 本地提交 | 任务分支上**局部提交**（可以多个小 commit）；提交前只跑 quick（[testing.md](testing.md) §3） |
| 集成 | 由**主 agent**把任务分支合入 `dev`；**集成完成后在 `dev` 上跑一次 full**（不跑两遍） |
| 推送 | 未经用户明确要求，不 push、不发 PR、不触发部署（见 [AGENTS.md](../../AGENTS.md)） |

**为什么主工作区不直写**：主工作区的 `dev` 是所有泳道的基线。被就地改动后，任何泳道的
「相对 dev 的改动面」都不再可信，`quick --base dev` 也会把别人的改动算进你的范围。

## 2. 泳道落点与创建

**路径约束（最高优先级）**：所有泳道必须位于**原始仓库根**的 `.worktrees/<任务名>/` 下。
无法满足时停止并报告，不放宽到其他目录，也不要把泳道自身再解释成「项目根」（会形成嵌套
`.worktrees`）。

```bash
# 接口契约（scripts/worktree.py 由工具任务实现；落地前用 §2.2 的等价 git 命令）
uv run python scripts/worktree.py create <任务名> --base dev   # 建 .worktrees/<任务名>/ 与分支 task/<任务名>
uv run python scripts/worktree.py list                         # 泳道、分支、dirty/未合并状态
uv run python scripts/worktree.py remove <任务名>              # 清理前检查见 §7.2
```

- `create` **必须**从 `dev` 起分支；`list` 要能直接看出「哪些泳道脏、哪些有未合提交」——
  这两个字段是清理判据，不是装饰。
- `remove` 在脏工作区或有未合提交时必须**拒绝**；`--force` 才能越过，默认行为不得静默丢弃。

### 2.1 落点已被忽略，且规则属于仓库

该路径由仓库根 `.gitignore` 的 `/.worktrees/` 排除，写法**锚定仓库根**：这样违反规范的嵌套
`.worktrees` 仍以未跟踪形式暴露，不被规则藏起来。

这条规则**必须留在受版本控制的 `.gitignore` 里**，不能只靠 `.git/info/exclude`——它不随克隆
传播，CI、协作者与服务器上的新克隆都没有它。缺失后果是静默的：泳道内的 `.git` 是指向 gitdir
的**文件**，git 视其为嵌入仓库，`git status` 只把它折叠成一条 `?? .worktrees/<任务名>/`，而
`git add .` 会以 **mode 160000（gitlink）** 收进索引并警告 `adding embedded git repository`。

### 2.2 实现落地前的等价命令

```bash
git worktree add .worktrees/<任务名> -b task/<任务名> dev
git worktree list
git -C .worktrees/<任务名> status --porcelain -uall
git -C .worktrees/<任务名> log --oneline dev..HEAD
git worktree remove .worktrees/<任务名>      # 脏工作区它会自己拒绝
git branch -d task/<任务名>                  # 仅在确认已合入 dev 后
```

## 3. 隔离规则：什么必须隔离，什么可以共享

| 维度 | 规则 | 理由 |
|---|---|---|
| 源码 | 每个泳道一份检出的源码；editable 安装指向**本泳道** `apps/api` | 串线**不会**让门禁变红，只能独立核验（§5 第 1 条） |
| Python 环境 | 每个泳道自己的 `.venv`（泳道内 `uv sync --frozen`） | 可变安装状态不可共享；共享会让 A 泳道的改动在 B 泳道生效 |
| `node_modules` | 每个泳道自己的 `node_modules`（泳道内 `pnpm install --frozen-lockfile`） | pnpm 的 workspace 链接是**相对路径**，跨泳道复用会指向另一个泳道的包 |
| 包下载缓存 | **可共享**：uv 缓存（`UV_CACHE_DIR`）、pnpm store（`pnpm store path`） | 纯内容寻址的只读缓存，不承载可变安装状态；重复下载没有收益 |
| Docker 镜像 | 可共享（同一台机同一镜像） | 无项目内可变状态 |
| 配置 | 每个泳道一份 `.env`（被忽略），从主工作区复制 | `core/config.py` 用 `parents[5] / ".env"` 定位，**在泳道里它指向泳道根** |
| 数据服务 | **共享**主工作区 `docker compose up -d` 起的那一套（PG / Redis / FalkorDB / SuperTokens） | 见 §3.1 与 §6；泳道**不得**自己 `docker compose up` |
| 端口 | 不改既有回环绑定（一律 `127.0.0.1:`），不新占宿主端口 | 编排放 `0.0.0.0` 等于把无密码的 FalkorDB/Redis 暴露到同网段 |
| 卷 | 不创建、不删除任何卷 | 卷删除不可逆，`down -v` 会连别人的数据一起删 |
| Git 元数据 | 不切主工作区分支、不动主工作区未提交改动 | worktree 与主工作区共享同一个 `.git` |

### 3.1 为什么数据服务只能由主工作区起

`docker-compose.yml` 用**固定** `container_name`（`campfire-postgres` 等）与命名卷。泳道里执行
`docker compose up -d` 会以泳道目录名作 compose project，卷名随之变成 `<泳道名>_pgdata_dev`，
容器名却与既有容器**冲突**——结果是一批「起来了但连的不是同一份数据」的假环境。因此：

```bash
# 只在原始仓库根执行
docker compose up -d
docker compose ps            # 在泳道里执行会显示空表，因为 project 名不同
```

## 4. 初始化一条泳道

```bash
# 在泳道根目录执行
uv sync --frozen                       # 建本泳道 .venv；editable 安装 apps/api
pnpm install --frozen-lockfile         # 建本泳道 node_modules（改前端的任务才需要）

# 配置来源：只复制，不把任何值写进受版本控制或被提交的文件
cp <原始仓库根>/.env ./.env
```

- `--frozen` 让依赖严格取自 `uv.lock` / `pnpm-lock.yaml`，不因解析漂移而在泳道间产生差异。
- `.env` 被忽略，新泳道默认**没有**它；缺失时配置落到无默认值（密钥类变 `None`）或代码默认值，
  典型表现是 `pytest` 多挂一条 `SuperTokensConfigurationError`（见 [README](../../README.md)）。
- 核验时只报**脱敏身份**（主机、端口、库名、键名清单），不报值。
- 建环境**不会让泳道变脏**（2026-10-29 实测）：`uv` 会写 `.venv/.gitignore`（内容 `*`），
  `node_modules/` 由根 `.gitignore` 忽略，因此 `git status --porcelain -uall` 仍只有你自己的改动。
  若泳道里出现了成批未跟踪文件，先查是不是漏了这条自带的忽略，而不是急着删目录。

## 5. 就绪判据：机械核验，不看「目录建好了」

**创建目录、`uv sync` exit 0、容器 running —— 三者任一都不能单独等价于就绪。**

| # | 判据 | 命令（泳道内执行） | 通过条件 |
|---|---|---|---|
| 1 | 源码来自**本泳道** | `uv run --frozen python -c "import campfire, pathlib; print(pathlib.Path(campfire.__file__).resolve())"` | 路径在**本泳道** `apps/api/src/` 下 |
| 2 | 配置来源属于本泳道 | `uv run --frozen python -c "from campfire.core.config import _ENV_FILE; print(_ENV_FILE.resolve(), _ENV_FILE.exists())"` | 路径指向**泳道根** `.env` 且 `exists=True`（`exists=False` 就是漏了 §4 的复制） |
| 3 | 连接目标身份（脱敏） | 读 `Settings` 打印 db/redis/falkordb 的 host/port/库名 | 与预期一致；**不打印口令** |
| 4 | 实际被连的那份数据在服务 | 在原始仓库根执行 `docker compose exec -T postgres psql -U campfire -d campfire -tAc "select current_database()"` | 库名与第 3 条一致——**核验连接目标，不只检查配置字符串** |
| 5 | 最小冒烟 | `uv run --frozen pytest <定向子集> --junitxml=<path>` | 读 XML 的 `tests/failures/errors/skipped`，不数控制台行数 |

第 3、4 条是同一个坑的两半：**配置字符串正确 ≠ 连到的是那份服务**。本仓就发生过
「`REDIS_URL` 指向 6379，实际占用该端口的是另一个 Redis 进程，容器一直没起来」，而所有配置
看起来都对。现环境由 compose Redis 唯一提供，但核验方式不变。

**证据强度**：写「ok」「已通过」「正常」不算证据；要写命令原文与关键输出行。
「0 命中 / 不存在」类结论必须配**阳性对照**——用一条已知存在的内容验证通道本身能命中。

## 6. 数据与测试：默认真串行，隔离可验证才并行

共享的数据服务是**可写状态**：PostgreSQL 库 `campfire`、Redis `127.0.0.1:6379/0`、
FalkorDB 图 `campfire`，所有泳道共用同一份。

**默认规则：写数据的测试集中串行，不并行。**

| 情形 | 允许 | 判据 |
|---|---|---|
| 没有任何命名空间隔离 | **串行**：同一时段只允许一处跑集成测试，其余泳道只跑不碰库的用例 | 默认情形 |
| 声称有隔离 | 才可并行 | 必须**可机械验证**：并发单元各有独立命名空间（PG 独立 database 或 schema、Redis 独立 db index 或键前缀、FalkorDB 独立图名），并证明写入落在该命名空间且对另一命名空间不可见 |

- 「我们用了不同前缀」不是隔离证明。验证方式：在命名空间 A 写入一条带唯一标识的行，
  用 A 读回（命中）、用 B 读（不命中）——**两条同时成立才算隔离**。
- 清理**只按命名空间**：`DELETE ... WHERE account_id/前缀`。**禁止**整表删除、`FLUSHDB`/`FLUSHALL`、
  删图：共享库下无过滤删除会删掉并发泳道刚写入的行（本仓实测过该缺陷）。
- 串行化的具体做法：在**原始仓库根**的 `.tmp/integration-test.lock` 上取锁（主工作区 `.tmp`
  是所有泳道看得见的同一份，且已被忽略）：

```bash
flock <原始仓库根>/.tmp/integration-test.lock uv run --frozen pytest <定向子集> --junitxml=<path>
```

- 集成的那一次 full（在 `dev` 上、集成完成后）由**主 agent 串行安排**，不与其他泳道的数据
  测试重叠。

## 7. 集成与清理

### 7.1 集成（主 agent 执行）

1. 任务分支在泳道内已 commit（局部提交即可，允许拆细），提交前只跑 quick。
2. 主 agent 把任务分支合入主工作区 `dev`（如 `git -C <原始仓库根> merge --no-ff task/<主题>`），
   同一组集成**串行**做。
3. **集成完成后在 `dev` 上跑一次 full**（`scripts/checks.py full`，可先 `--dry-run` 复核将跑的
   命令）。这就是合入判据：**不为合并前的分支再单独跑一遍**——分支状态不是发布事实，跑两遍是
   把同一风险付两次代价（2026-10-29 用户统一口径）。失败就修或回退，并记录失败原因。
4. 方向单向：`task/*` → `dev`；`dev` → `master` 只在发布时。

### 7.2 清理前必须核的三件事

| # | 检查（泳道内） | 通过条件 |
|---|---|---|
| 1 | `git status --porcelain -uall` | **空**——没有未提交改动，也没有未跟踪文件 |
| 2 | `git log --oneline dev..HEAD` | **空**——所有提交都已进 `dev`；非空说明还有没进基线的成果 |
| 3 | 本地成果清点：`git stash list`、被忽略但有价值的东西 | 无 stash；**`deliverables/` 不在泳道内**（见下）；`.tmp/` 里没有唯一副本 |

三条全过才 `scripts/worktree.py remove <任务名>`；任一条不满足就先补齐或明确报告，
**不得用 `--force` 了事**。清理范围仅限本泳道目录与自己的分支：不删卷、不删库、
不跑 `docker compose down -v`、不清别人泳道。

**泳道不是仓库**：`deliverables/`（正式运行的大文件）与 `materials/`（正式材料的文本部分）
都固定在**原始仓库根**，理由与判据见 [materials.md](materials.md)。泳道被 `remove` 时它们
不受影响——这正是「不要把成果留在泳道里等下次再搬」的原因。

## 8. 本指南何时失效（需重新实证）

- `uv.lock` / `pyproject.toml` / `pnpm-lock.yaml` 变更（依赖集合或 workspace 形状变化）。
- `.gitignore` 对 `.worktrees/`、`.env`、`deliverables/` 的规则变更（落点与配置来源假设失效）。
- `core/config.py` 的 `_ENV_FILE` 定位方式变更（`parents[N]` 层级移动）。
- `docker-compose.yml` 的服务、`container_name`、端口或卷定义变更。
- 泳道路径规则或 `scripts/worktree.py` 的判据变更。
- 主线分支策略变更（例如 `dev` 不再是集成基线）。
