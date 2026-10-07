# 隔离 worktree 环境指南

> **状态**：**已合回**（2026-10-07）。由 dev-orchestrator run `20261006-001` 的 env-ready
> 执行者在 integration worktree 内产出，经独立审查 PASS 后合回主分支；
> 合回时按该审查的 P2#4 订正了 §4 一处机制表述。
> **权威范围**：本仓「隔离泳道里怎么把环境准备好、怎么核验它真的就绪」的可复用配方。
> **它不拥有**：命令集真源在 [AGENTS.md](../../AGENTS.md)；隔离与调度的语义与判据在
> dev-orchestrator skill（`references/isolation-method.md`、`references/stage-contract.md`）；
> 数据服务编排在 [docker-compose.yml](../../docker-compose.yml)。冲突时以拥有者为准。
> **本文件不写**：凭证、密钥、当前 PID、临时端口占用——理由见 [§4 就绪判据](#4-就绪判据)。

---

## 1. 前置条件

在本仓准备一条隔离泳道前，以下前提必须成立；任一不成立就先补齐，不要带着可疑环境开工。

| # | 前提 | 判据 | 取证方式 |
|---|---|---|---|
| 1 | Python ≥ 3.12 | `python -V` 为 3.12.x | 实测 3.12.12 |
| 2 | `uv` 可用且 lock 同步 | `uv --version` 有输出；`uv.lock` 存在 | 仓库根有 `uv.lock` |
| 3 | 数据服务在跑 | `docker compose ps` 中 postgres / falkordb / supertokens 为 `Up` | 见 [§4](#4-就绪判据) 与 §7 的既有事实 |
| 4 | 泳道路径合规 | `worktree_env.py check-path` 返回 `ok: true` | 流水线化判定，不靠肉眼 |
| 5 | 仓库根 `.env` 存在 | 新泳道需要它作配置来源 | 本仓 `.env` 被 `.gitignore` 忽略，不会随 worktree 创建带入 |

**路径约束（最高优先级）**：所有泳道必须位于**原始项目根**的 `.worktrees/<run-id>/` 下。
无法满足时**停止并报告**，不放宽到其他目录，也不要把泳道自身再解释成「项目根」
（那会形成嵌套 `.worktrees`）。

## 2. 初始化

本仓是 **uv 单应用工作空间**（根 `pyproject.toml` 的 `[tool.uv.workspace]`
`members = ["apps/api"]`），依赖清单属于 `apps/api`。配方即三步：

### 2.1 建本泳道自己的虚拟环境

**必须在泳道内执行**，因为 `.venv` 属于「必须隔离」的那一类
（isolation-method §3.2：可共享缓存，不共享可变安装状态）。

```bash
# 在本泳道根目录执行
uv sync --frozen
```

- `--frozen` 让依赖严格取自 `uv.lock`，不因解析漂移而与其它泳道产生差异。
- 该命令同时把 `apps/api` 以 **editable** 方式装进本泳道的 `.venv`，
  于是 `campfire` 包由**本泳道**的源码提供——这正是 [§4](#4-就绪判据) 第 1 条要证伪的串线点。
- 包下载缓存（`UV_CACHE_DIR`）是**可共享**的缓存，无需隔离；实测第二次建环境约 4 秒。

### 2.2 提供配置来源

`apps/api/src/campfire/core/config.py` 以 `_REPO_ROOT / ".env"` 定位配置，
而 `_REPO_ROOT` 是该文件向上 `parents[5]`——**在泳道里它就指向泳道根**。
由于 `.env` 被 `.gitignore` 忽略，新泳道默认**没有**这个文件，配置会全部落到无默认值
（密钥类字段变为 `None`）或代码默认值上。因此需要：

```powershell
# 从主工作区复制（该路径同样被忽略，不会进入版本库）
Copy-Item <原始项目根>\.env <泳道根>\.env
```

**纪律**：只复制，不把任何值写进受版本控制或被提交的文件；核验时只报**脱敏身份**
（主机、端口、库名、键名清单），不报值。

### 2.3 数据服务

数据服务是**既有共享服务**，用 `docker compose up -d` 起的那些**不在泳道内**，
本泳道不重复编排、不改端口、不建新卷。

## 3. 隔离规则

| 维度 | 规则 | 理由 |
|---|---|---|
| 源码 | 每条泳道一个 `.venv`，editable 安装指向本泳道 `apps/api` | editable 安装串线**不会**让门禁变红，只能独立核验 |
| 配置 | 每条泳道一份 `.env`（被忽略），来源为主工作区副本 | 配置来源必须显式约束，不能让泳道静默读到别处配置 |
| 数据 | **共享** PostgreSQL 库 `campfire`、Redis、FalkorDB 图 `campfire` | 见 §7 的既有共享事实与其风险 |
| 卷 | 不创建、不删除任何卷；只用既有 `campfire-ai_*_dev` | 卷删除不可逆 |
| 端口 | 不改动既有回环绑定；不新占宿主端口 | 编排里端口一律绑 `127.0.0.1`，不得省略 |
| 测试清理 | 按 `account_id` / id 前缀过滤删除，**禁止**整表删除与 `FLUSHDB`/`FLUSHALL` | 共享库下无过滤删除会删掉并发泳道刚写入的行（本仓 2026-09-30 实测过该缺陷） |
| Git | 不切主工作区分支、不覆盖用户未提交改动、不改主工作区源码 | worktree 创建本身会改变共享 Git 元数据 |

**可共享 / 必须隔离的分界**（isolation-method §3.2）：包下载缓存、Docker 镜像、
经验证安全的基础服务、只读参考材料可共享；`.venv`、项目安装目录、editable 安装状态、
数据库/schema/graph/键命名空间的可写状态、端口、容器可写卷必须隔离。

## 4. 就绪判据

**核心纪律：创建目录、安装 exit 0、容器 running —— 三者任一都不能单独等价于就绪。**

每一步都必须跑机械核验，且**读 `JSON_RESULT` 的字段**，不只看 exit code：

| # | 判据 | 命令 | 通过条件 |
|---|---|---|---|
| 1 | 源码来自**本泳道** | `worktree_env.py source-origin --worktree <泳道> --package campfire --python <泳道解释器>` | `ok:true` 且 `verified:true` |
| 2 | 资源归属声明合规 | `worktree_env.py resources --declared <控制目录>/env/<task-id>.json --run-id <run-id>` | `ok:true` 且 `verified:true` |
| 3 | 配置来源属于本泳道 | 读 `core/config._ENV_FILE` 并经 `Settings` 取值 | 指向**泳道根**的 `.env` |
| 4 | **实际连接目标**可信 | 只读连接探针（身份查询，不写） | 库名/实例身份与声明一致——**核验连接目标，不只检查配置字符串** |
| 5 | 迁移/初始化后的实际结构 | 按项目迁移门禁 | 结构符合预期，不只依赖 exit code |
| 6 | 最小冒烟跑通 | `uv run --frozen pytest <定向子集> --junitxml=<path>` | 取 **XML 机器读数**（`tests/failures/errors/skipped`），不数控制台行数 |

**关于 `--python`（不可省略）**：`source-origin` 不传 `--python` 时只代表脚本自身的解释器，
结果无意义；本仓把它判 FAIL。这是**唯一能证伪源码串线**的门禁。

**关于证据强度**：`readinessEvidence` 三项必须是**结构化实证**
`{"command": 命令原文, "output": 输出原文关键行}`。写「ok」「已通过」「正常」不算证据。

**关于「0 命中 / 不存在」类结论**：必须配**阳性对照**（canary）——证明探测通道确实能检出
该形态。本仓已实测一个静默失败源：pwsh 的 `Select-String -Path '**'` **不是递归通配**
（只按**单层**匹配，等价于 `*`）——**同层**文件会命中，**跨层**才静默变成 0 匹配且**不报错**；
所以「0 命中」可能只是「没递归到」，不能当作「不存在」。全仓内容检索用 `grep` 工具。

## 5. 退出与恢复

### 5.1 出场清理

- **只清自己创建的资源**，按 run-id 前缀定位；**不按端口或模糊进程名清理**他人资源。
- 本指南的配方**不创建**容器、卷、库或网络——建环境只产生泳道内 `.venv` 与 `.env`，
  因此正常出场的清理面很小。
- **禁止**：`docker compose down -v`、删除任何卷、清空数据库。核验一律只读。

### 5.2 出场复核

对照入场读数，逐项确认现场未被改变：

```bash
git -C <泳道> status --porcelain -uall    # 与入场对比
docker compose ps                          # 与入场对比
```

### 5.3 中断恢复

临时产物统一用可识别前缀命名（如 `T01-envready-`），便于中断后清点续跑。
返工**沿用同一条泳道**，不要新建目录重做——原上下文与已装环境要保留。

### 5.4 失败处理

任一关键隔离核验失败 → **停止该任务派发，记为环境失败**。
不得伪装成「代码验收通过」，不得改写证据使其变绿，也不得记为产品缺陷。
**未验到 ≠ 隔离成功**：探测没跑起来、包不存在、解释器不可执行，一律按失败处理。

## 6. 更新条件

本指南在下列条件成立时**失效，必须重新实证**（「上次成功」不能替代本次就绪证据）：

- `uv.lock` 或 `pyproject.toml` 变更（依赖集合变化）；
- `.gitignore` 对 `.env` 的忽略策略变更（配置来源假设失效）；
- `core/config.py` 的 `_ENV_FILE` 定位方式变更（`parents[N]` 层级移动）；
- `docker-compose.yml` 的服务、端口或卷定义变更；
- 泳道路径规则或 `worktree_env.py` 的判据变更；
- 平台或 PowerShell 版本变更（可能改变 §4 提到的 `Select-String -Path` glob 语义）。

## 7. 本仓既有共享事实（**如实登记，不美化**）

以下为实测事实，属「本次运行记录」性质；它们**共用**给所有泳道，是
isolation-method §3.2 点名的高危项，任何新泳道都必须知道：

| 项 | 实测读数 | 影响 |
|---|---|---|
| PostgreSQL | 库 `campfire`、schema `public`，全部泳道共用 | 测试必须按账号/id 前缀清理 |
| FalkorDB | 图 `campfire`（6380），共用 | 记忆侧的图数据跨泳道可见 |
| Redis | `127.0.0.1:6379/0`，由 **compose 的 `campfire-redis`** 提供（`Up (healthy)`） | 按前缀定位，禁止 `FLUSHDB`；键空间**非空**（见下） |
| `campfire-redis` 容器 | **`Up (healthy)`**（2026-10-07 起） | 见下 |

**关于 `campfire-redis` 与宿主机 Memurai（环境已变更，两段都记）**：

**旧状态（2026-10-06 实测，已不再成立）**：该容器长期停在 `Created`、从未运行；应用配置的
`REDIS_URL` 指向 `127.0.0.1:6379`，而该端口实际由**宿主机原生 Redis 服务 Memurai**
（Windows 服务 `Memurai`，启动类型 `Automatic`）占用 ⇒ **应用连到的不是 compose 里那份 Redis**。
这正是「配置字符串正确」掩盖「连接目标另有其人」的现成例子，也是 §4 要求核验连接目标的原因。

**根因（2026-10-07 实证，此前只能推断）**：compose 把 redis 绑定到 `127.0.0.1:6379`，与 Memurai
争同一地址端口 ⇒ 容器创建成功但**启动失败**，compose 把它留在 `Created`（无日志、`ExitCode 0`）。
**停用 Memurai 后该容器立刻 `Started` 且 `Up (healthy)`** ⇒ 端口冲突这一因果由此坐实。

**现状态（2026-10-07 用户裁决：本项目采用 compose 里的 redis）**：

- `Memurai` 服务已 **`Stopped` + `StartupType Disabled`**（重启后不再占用 6379）；
- `campfire-redis`：`Up (healthy)`、`127.0.0.1:6379->6379/tcp`、`redis_version 7.4.8`、`restart: unless-stopped`；
- **可回退**：Memurai 的数据仍在 `C:\Program Files\Memurai\dump.rdb`（含停用前 db0 的 7 个键，
  其中有本仓 **70 条未消费的 Taskiq 任务**与 Smart-Academy-Pivot 的 Celery/Kombu 绑定）。
  回退须**先停 compose redis** 再启用 Memurai，否则端口再次冲突。
- **⚠ 键空间不是空的**：卷 `campfire-ai_redis_data_dev` 创建于 2026-08-04，容器首次启动即从其旧
  `dump.rdb` 载入 2 个键（日志 `keys loaded: 2`），现存 1 个业务外残留键 `ratelimit:counter`。
  ⇒ 实测「容器起来了」**不等于**「键空间干净」；清理残留键属环境变更，需单独授权。

本指南不推断成因、也不建议在核验任务里顺手 `docker compose up` 起容器——那是环境变更，需要单独授权。
