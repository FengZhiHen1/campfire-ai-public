# `apps/web/e2e-real` —— 真实依赖端到端（真浏览器 + 真 Vite + 真 FastAPI + 真 SuperTokens）

> **本目录不是 mock 基建。** 它是**真实依赖**探针：真浏览器、真 Vite dev server、真 FastAPI
> 后端、真 SuperTokens 登录、真模型（部分链路）。与 `apps/web/e2e/`（`pnpm shots`，mock 基建）
> 是**两套互不影响的装置**。
>
> 本文件是**入库的**运行说明。此前「真栈怎么跑」只存在于 `docs/证据/probes/serve.py`（**`tmp/` 被
> `.gitignore` 忽略**）⇒ 该知识不入库、下次会丢。本文取代它。

---

## 0. 为什么这份说明必须存在（一个实测缺陷）

> **⚠ 2026-10-07 订正：本节描述的缺陷【已修】，下面「必须用启动器」不再是硬要求。**
> 修复是 `apps/api/src/campfire/main.py:42` 的 `apply_no_proxy_normalization()`——
> 它在**模块导入期**执行，且**排在本文件所有 httpx/openai/supertokens import 之前**
> （实测：该调用在第 42 行，`falkordb`/`openai`/`supertokens_python` 的 import 在第 44–48 行）。
> 引入提交为 `75bb866a`（2026-10-06）。**本节的实测结论仍然可复算、且是那条设计决策的
> 判据来源**，故全文保留；但**不要再照它绕路**：直接
> `uv run uvicorn campfire.main:app` 起后端即已受保护（同一次实测：`/readyz` → `ready:true`，
> `POST /api/auth/signup` → 200 而非 500）。
> **为什么当时会写下过期结论**：本节最后修改（`989d6013`，2026-10-07 09:57）只挪了目录，
> 没有同步这个已修好的前提——这正是「文档比代码晚一天」的典型形态。
> **保留本节的理由**：`/readyz` 绿而业务全断这个**形态**仍会以别的根因复发（见下第 ② 例），
> 该判据本身不过期。

**按 `support/real.ts` 旧文件头写的那样直接起后端**：

```bash
uv run uvicorn campfire.main:app --host 127.0.0.1 --port 8000
```

**`POST /api/auth/signup` 必然 500**，而 **`/readyz` 仍然全绿**。实测原文：

```
httpx.InvalidURL: Invalid port: ':1]'
INFO:     127.0.0.1:51785 - "POST /api/auth/signup HTTP/1.1" 500 Internal Server Error
```

同一次运行里 `/readyz`：

```json
{"ready":true,"components":{"auth":{"status":"ok",...},"model":{"status":"ok",...}, ...}}
```

⇒ **「健康检查绿而注册/登录全断」**。排查者会去查 SuperTokens、数据库与凭据，而根因是
**进程环境变量的词法问题**。

**这个形态在本项目已出现两次**：① 本条（`auth` 项绿、注册/登录 500）；② Graphiti embedder
漏传 `encoding_format`（`model` 项绿、记忆写入全坏，见 `docs/TODO.md`）。共同点只有一句：
**探针测的那条链路，与真实业务走的那条链路不重合**。⇒ 看到 `/readyz` 全绿时，先确认它**测的
是不是**你要断言的那条路径。

### 根因

本机环境块里 `NO_PROXY` 与 `no_proxy` **两个键并存**，取值含**带方括号的 IPv6 字面量**：

```
NO_PROXY=127.0.0.1,localhost,::1,[::1]
no_proxy=127.0.0.1,localhost,::1,[::1]
```

`httpx` 的 `get_environment_proxies()` 把 `[::1]` 解析成 `all://*[::1]`，客户端**构造期**即抛
`InvalidURL: Invalid port: ':1]'`（实测代理表含 `'all://*[::1]': None`）。而
`supertokens_python` 的 querier 用 httpx 的**默认客户端**（`trust_env=True`）⇒ 注册/登录在
**第一步**就 500。`/readyz` 的 `auth` 项不受影响，因为它自己的探针是 `trust_env=False`
（`apps/api/src/campfire/core/auth/__init__.py`）。

### 为什么「从 shell 设一下」没用（两种写法都无效，且原因不同）

本机实测（每种写法都从**全新 shell** 出发）：

| 写法 | 子进程 `os.environ` 实际读到 | 有效？ |
| --- | --- | --- |
| `set NO_PROXY=127.0.0.1,localhost,::1`（cmd，大写） | `127.0.0.1,localhost,::1,[::1]` | ❌ 无效 |
| `set no_proxy=127.0.0.1,localhost,::1`（cmd，**小写**） | `127.0.0.1,localhost,::1,[::1]` | ❌ 无效 |
| PowerShell `$env:NO_PROXY = <clean>` | `127.0.0.1,localhost,::1,[::1]` | ❌ 无效 |
| **Python 进程内**写**两个键** | `127.0.0.1,localhost,::1` | ✅ **有效** |

**现象层面的结论（这是我直接观测到的）**：shell 里改写的值**没有**传到 python 子进程
（同一个 shell 里 `cmd /c set` 明明显示已改，python 却仍读到脏值）；而在 python 进程内改
则**立即生效**——实测写任一大小写键后，`os.environ` 里那一项就变成干净值，且
`get_environment_proxies()` 不再含 `all://*[::1]`。

**为什么 shell 那条路无效（机制部分，证据强度：中）**：环境块里 `NO_PROXY` 与 `no_proxy`
**两个键并存**，而两边对「同名」的处理不同——WinAPI 侧大小写不敏感地匹配**块内首个**条目，
Python 侧把环境块折叠进 `os.environ` 时也做大小写不敏感的去重。**两边各自都自洽，却指向不同
的条目**，于是出现「shell 显示改了、python 读到没改」这种看起来矛盾的现象。**⇒ 我没有把这一
层完全隔离验证**（要用 `CreateProcessW` 手工构造有序环境块才能定死），因此只把它写成机制
假说；**但修法不依赖这个假说**——不管机制如何，「在进程内、导入 httpx 之前写两个键」在实测中
稳定有效，这才是本文件要传递的可操作结论。

### ✅ 唯一可靠的做法：**在进程内、导入任何 httpx 消费者之前，大小写两个键都写**

```python
"""真栈后端启动器：在进程内规范化 no_proxy，然后才引导 uvicorn。"""
import os

# ⚠ 必须在导入 httpx / openai / supertokens *之前*；两个键都要写。
os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
os.environ["no_proxy"] = "127.0.0.1,localhost,::1"

import httpx  # noqa: E402  —— 必须在规范化之后导入

# 自检：客户端构造期不再抛 InvalidURL 才继续（这一步就是上面那个缺陷的判据）
httpx.AsyncClient()
print("no_proxy 已规范化，httpx 默认客户端构造成功")

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("campfire.main:app", host="127.0.0.1", port=8000, log_level="info")
```

把这段存成 `.tmp/serve.py`（`.tmp/` 被忽略，属**本地临时装置**，不要指望它入库）再
`uv run python .tmp/serve.py` 即可。
（2026-10-06：落点由 `tmp/` 改为 `.tmp/`——两个临时目录已合并为 `.tmp/` 一个。）

**⚠ 该规范化只对【本进程】有效，不会传给子进程**（实测：子进程继承的是原始环境块，仍会抛
`InvalidURL`）——所以 uvicorn 必须由**这个**进程启动；不要用它去 `subprocess` 拉起别的服务
再指望它们继承豁免。

**修好后的判据**（本机实测）：同一台机器、同一批数据服务，用上面的启动器起后端
⇒ `POST /api/auth/signup` 返回 **HTTP 200 `{"status":"OK","user":{...}}`**，而
`/readyz` 依旧 `ready: true` ⇒ **必须两处都是绿的**，只看 `/readyz` 会把这条缺陷放过去。

---

## 1. 前置：数据服务 + Redis

```bash
docker compose up -d      # postgres / redis / falkordb / supertokens / minio
```

`docker-compose.yml` 声明了**五个**数据服务（一期全量），本机实测端口映射（数据服务都绑 `127.0.0.1`）：

| 服务 | 容器 | 宿主端口 | 本机实测状态（2026-10-07 复核） |
| --- | --- | --- | --- |
| PostgreSQL | `campfire-postgres` | 5432 | Up 11h (healthy) |
| Redis 7 | `campfire-redis` | 6379 | **Up 10h (healthy)** —— 见下方订正 |
| FalkorDB | `campfire-falkordb` | **6380**（容器内 6379） | Up 11h (healthy) |
| SuperTokens core | `campfire-supertokens` | 3567 | Up 11h |
| MinIO | `campfire-minio` | 9000 / 9001 | Up 11h (healthy) |

> **⚠ 2026-10-07 订正：Redis「本机起不来」的结论已不成立。** 实测
> `docker ps` → `campfire-redis  Up 10 hours (healthy)  127.0.0.1:6379->6379/tcp`；
> `docker exec campfire-redis redis-cli PING` → `PONG`；且本机**已无 `memurai` 进程**
> （`Get-Process memurai` 计数 0）⇒ 6379 空闲，容器正常占用。
> 下面那段「只跑 Memurai、不跑 campfire-redis」的原文**保留为 2026-10-04 的现场记录**，
> 换机器时仍可作为「6379 被占用时是什么样」的参照；**但当前本机不需要它**。
> `docker compose up -d` 的退出码判据（不要拿它当「数据服务都没起来」）**仍然成立**。

> **⚠ Redis 曾是唯一一个在本机起不来的服务（实测，2026-10-04）**：compose 把
> redis 映射到 `127.0.0.1:6379:6379`，而本机 **6379 已被原生 Memurai 占着**
> （`memurai.exe`，`PING → True`，`redis_version 7.2.12`）⇒ 容器停在 `Created` 状态，
> 手工 `docker start campfire-redis` 报：
>
> ```
> Error response from daemon: ports are not available: exposing port TCP 127.0.0.1:6379
>  -> 127.0.0.1:0: listen tcp4 127.0.0.1:6379: bind: Only one usage of each socket address
>  ... is normally permitted.
> ```
>
> **⇒ 本机只跑 Memurai，不跑 `campfire-redis`**（两者是同一件事——都是 6379 上的 Redis
> 协议服务，队列/缓存/Taskiq broker 都能用）。**不要**为了让它 healthy 去 `docker compose down`
> 或改端口：Memurai 是可用的。
>
> **⚠ 但要知道 `docker compose up -d` 在本机会【退出码 1】**（实测原文见上）。其余四个服务
> **照常 Running**（实测：报错后 `campfire-postgres`/`falkordb`/`supertokens`/`minio` 仍在跑），
> 即**失败是局限在 redis 那一个服务的**。⇒ **不要拿 `docker compose up -d` 的退出码当
> 「数据服务都没起来」的判据**；要看容器实际状态（`docker ps`）。
> 换机器时若 6379 空闲，则 `campfire-redis` 会正常起、Memurai 不再需要。

> FalkorDB 的宿主端口是 **6380** 不是 6379——`docker-compose.yml` 里明写「端口用 6380，避免与
> Redis 的 6379 撞车」。`core/config.py` 的默认值即 6380；
> `support/real.ts` 的 `seedMemoryEpisode(..., port = 6380)` 也用这个默认值。

`.env` 里 `TOKENHUB_API_KEY` 必须是**非占位符**真值：第 3 条链路会**真调模型**（消耗配额）。

---

## 2. 起后端（8000）

> **⚠ 2026-10-07 订正：不再是「必须」。** 产品侧已在入口导入期规范化 `no_proxy`
> （`main.py:42`，见第 0 节订正），因此下面这条命令**现在可以直接用**：
>
> ```bash
> uv run uvicorn campfire.main:app --host 127.0.0.1 --port 8000   # ✅ 2026-10-07 起可行
> ```
>
> 第 0 节那个「进程内先规范化」的启动器（`.tmp/serve.py`）**仍可使用**，它现在是
> 等价通道而非必要条件。留着它的理由：当**别的** httpx 消费者在**本进程之外**
> （例如某个自己起客户端的小工具）出同类问题时，它是本仓已有的对照装置。

起好后先自检**两处都要绿**（只看 `/readyz` 不够）：

```bash
curl -s http://127.0.0.1:8000/readyz      # 期望 ready:true
```

注册能过才算后端真的可用（第 4 节的邀请码就绪后）。

---

## 3. 起前端（5173）

```bash
pnpm --filter @campfire/web dev
```

Vite dev server 在 **5173**，把 `/api`、`/livez`、`/readyz`、`/health` 代理到
`http://localhost:8000`（见 `apps/web/vite.config.ts` 的 `PROXIED_PREFIXES`）。探针必须打在
**5173** 上（经代理），`t10-real.spec.ts` 会断言 `viaProxy === true`。

### ⚠ `vite preview` 的代理行为（**实测订正一处流传的说法**）

**流传的说法是「`pnpm preview` 不代理，只适合 mock 场景」——本机实测该说法不成立。**
Vite 7.3.6 的实现是 `proxy: preview?.proxy ?? server.proxy`（`vite/dist/node/chunks/config.js`
的 `resolvePreviewOptions`），即 **preview 默认继承 `server.proxy`**。实测（preview 起在 4174）：

| 动作 | 结果 |
| --- | --- |
| `GET /readyz`（后端**已停**） | 500 + 日志 `http proxy error: /readyz` / `ECONNREFUSED` ⇒ **它在尝试代理** |
| `GET /readyz`（后端**在跑**） | **HTTP 200 `ready:true`** ⇒ 代理成功 |
| `POST /api/auth/signup`（经 4174） | **HTTP 200 `{"status":"OK"}`** |

⇒ **`pnpm preview` 能代理**，不是「只适合 mock」。（`pnpm shots` 用的就是 preview——它在
`playwright.config.ts` 里以 `webServer` 起 `pnpm preview --port 4173`，见第 6 节。）

**但本目录仍应打 5173**：`e2e-real` 是**真实依赖**探针，它要测的是开发态前端 + 真后端这条链；
用 preview 还得先 `pnpm build`，且产物是另一套（构建期内联 `VITE_API_DOMAIN` 等）。**结论：
用 dev（5173），别用 preview。** 理由从「preview 不代理」订正为「preview 会代理，但它是产物
形态、不是本探针的被测对象」。

> **⚠ 不要占 4173**：那是 `pnpm shots` 的 preview 端口（`PREVIEW_PORT = 4173`，`--strictPort`）。
> 若要手工起 preview，换端口（如 `--port 4174`）。

---

## 4. 邀请码（**一次性，每次现签**）

```bash
uv run python -m campfire.cli invite issue
```

- **邀请码是一次性的**，用掉即失效；
- **同一批运行里有多处真实注册** ⇒ **只签 1 枚必然假红**：先跑的用例把码用掉，后跑的就以
  「邀请码无效或已不可用」失败，**看起来像产品缺陷，实为夹具不够**；
- 因此运行时用**码池** `T10_INVITE_CODES`（逗号分隔，按下标分配）；`T10_INVITE_CODE` 是单枚回退。

**本目录引用的码池下标（实测 `grep`，2026-10-04）**——按**要跑哪些 tag** 决定需要几枚：

| 文件 | 用例 | 下标 |
| --- | --- | --- |
| `t10-real.spec.ts` | 链路1 注册（`@real`） | **0** |
| ~~`ablation.spec.ts`~~ | ~~`.device` transform 承重性（`@ablation`）~~ | ~~1~~ |
| ~~`ablation.spec.ts`~~ | ~~链路7 控制台分类器（`@ablation`）~~ | ~~2~~ |
| ~~`control.spec.ts`~~ | ~~判据1 非空洞性（`@control`）~~ | ~~3~~ |
| ~~`control.spec.ts`~~ | ~~判据2 非空洞性（`@control`）~~ | ~~4~~ |

⇒ **2026-10-08 起只需 1 枚**（下标 0）。`ablation.spec.ts` 与 `control.spec.ts` 已按用户裁决
删除（「闸门理应只有 pytest 和 vitest」）——上表划掉的行是**当时**的下标分配，留作沿革；
它们的「能红证明」能力随之消失，若日后要恢复，须从 git 历史取回并重新对齐下标。

> **`@capture`（2026-10-07 新增）不在此表里，因为它不占码**：
> `capture-pages.spec.ts` **只登录、从不注册**（实测：全文无 `signup`/`inviteCodeFor` 调用，
> 仅一处注释提到 signup 作为对照说明）⇒ 它**不消耗邀请码池**，与上表下标无耦合。
> 它复刻 `marketing/promo-shotcraft/capture/measure-*.mjs` 的两个量取口径
> （页面滚动容器尺寸、元素位置与滚动落点），产物写 `T10_CAPTURE_OUT`。
> 准确说法是**能力已被本文件收编进产品树**（Playwright，纳入 `pnpm` 入口）。
> **2026-10-08 更新**：原脚本中产出的两个量取脚本（`measure-page-metrics.mjs`、
> `measure-element-positions.mjs`）**仍在**（它们写已跟踪的 `src/*-metrics.json`，
> 属构建链）；本目录下 17 个一次性调试脚本已删除。
> 跑法见该文件头部注释的 `--grep "@capture"` 一行。
> **⚠ 已知的一处产物差异（该文件作者实测并归因）**：`element-metrics` 的
> `profile.marks.pendingGroup.ratio` 与旧产物略有不同，算术定位为页面 ~0.14px 的亚像素
> 布局漂移（两者的 `Math.round` 后 `offsetTop` 均为 1880、`scrollPx` 均为 1728）。
> 该字段**在影片源码里零消费者**，故不影响影片；但要知道它**不是逐字节一致**的那一个数。

> **⚠ 一处按代码推断的夹具陷阱（证据强度：中——由代码与 T11 记录推出，本包未单独执行验证）**：
> `docs/证据/probes/run-real.ps1` 的 `CodeCount` **默认是 4**，而 `inviteCodeFor` 对池取模
> （`pool[index % pool.length]`）⇒ 池只有 4 枚时，下标 **4 会回绕到下标 0**，而码 0 已被链路1
> 用掉。⇒ 要跑 `@control` 请显式给足 5 枚（T11 报告记录其全量运行即「现签 5 枚」，与该推断一致），
> 例如 `pwsh -File docs/证据/probes/run-real.ps1 -CodeCount 5`。
> **为什么值得写下来**：T11 的 R3 记录过一个真实踩坑——复用失效码时 supertokens 返回
> **HTTP 200 + `{"status":"GENERAL_ERROR"}`**，于是「只看 HTTP 200」的断言**恒真**、注册静默
> 失败，最终以别的现象（超时 180s）暴露。夹具已改为断言响应体 `status === 'OK'`（原见
> `ablation.spec.ts` / `control.spec.ts`，两者已于 2026-10-08 删除），**所以现在复用码会如实变红**——看到「邀请码无效」
> 先数一下下标，不要直接判成产品缺陷。

`support/real.ts` 的 `inviteCodeFor(index)`：给了池就 `pool[index % pool.length]`，否则用
`T10_INVITE_CODE`；**池为空时返回空串，调用方必须显式断言非空**（不要让它静默变成空注册）。

---

## 5. 跑

```bash
pnpm --filter @campfire/web exec playwright test \
  --config e2e-real/playwright.real.config.ts \
  --grep "@real" --reporter=list
```

### 环境变量（读自 `support/real.ts`）

| 变量 | 含义 | 默认 |
| --- | --- | --- |
| `T10_BASE_URL` | 被测站点根（**5173**） | `http://localhost:5173` |
| `T10_OUT` | 产物目录（JSON 证据 / trace / 截图 / `.playwright-real/`） | `<repo>/.tmp/T10` |
| `T10_INVITE_CODES` | **邀请码池**（逗号分隔，按下标分配） | 空 |
| `T10_INVITE_CODE` | 单枚邀请码（池为空时的回退） | 空 |
| `T10_ACCOUNT` | 指定账号 | 省略则按时间戳生成 `e2e-<stamp>@example.test` |
| `T10_PASSWORD` | 指定口令 | 省略则按时间戳生成 |

账号名**必须是邮箱格式**（见 `docs/TODO.md` 的 `PROD-01`）；口令 ≥8 字符、含小写字母与数字。

**为什么要重定向 `T10_OUT`**：产物默认写 `.tmp/T10`，而多轮运行写**同一个文件名**会
**同名覆盖**，后一轮盖掉前一轮 ⇒ 「两遍读数逐字相同」这类主张**不可独立复核**。要对比就分目录，
例如 `T10_OUT=.tmp/T11`（T11 就是这么做的）。

### 可发现的标记

`--grep "@real"` 收验收链路；`--grep "@ablation"` 收消融/控制臂（能红证明）。本目录里
**没有 `test.skip` 之类的静默降级**——缺环境时它**失败**，不假装通过。

---

## 6. 为什么它不在 `pnpm shots` 里

- `apps/web/playwright.config.ts` 的 `testDir` 是 **`./e2e`**，本目录是 `apps/web/e2e-real`
  ⇒ **`pnpm shots` 收不到本目录**；
- 本目录用自己的 `e2e-real/playwright.real.config.ts`：其 `testDir` 是 **`.`**（相对**配置文件
  所在目录**解析，写成 `./e2e-real` 会让 Playwright 去找 `e2e-real/e2e-real` 并报
  「No tests found」——一个看起来像「没有用例」的假阴性）；
- 它**不声明 `webServer`**：假设 5173 与 8000 **已在跑**（后端与前端由使用者起），起不来就
  直接用例失败。

---

## 7. ⚠ 硬约束：本目录下**不得**出现 `page.route` / `route.fulfill`

**无 mock 是本目录的定义性约束。** 本目录下**不得**用 `page.route` / `route.fulfill` 替换任何
响应——一旦替换，探针证明的就不再是「真栈可用」，而是「我伪造的响应被页面正确处理了」。

当前实测**零处** `page.route` / `route.fulfill`（只有 `page.on('response')` 这类**只读观察**）。
`real.ts` 里的 `page.on('response')` 采集器**只观察**：原请求照发、原响应原样返回给应用，
一个字节都不改。

**已知的一处需要小心解读的夹具**：`seedMemoryEpisode()` 直连 FalkorDB 写一条 episode。
它是**夹具**（把被测页面置于「已有一条记忆」的前置条件下），**不是响应伪造**——整条链路里
没有任何 `page.route`，页面经 `GET /api/memory/episodes` 真读到它、经 `DELETE` 真删掉。但它
**不能**作为「记忆写入路径可用」的证据：种进去的 episode 来源不是产品写路径。

---

## 8. 报告与证据

本目录的产物（`T10_OUT`）是探针的证据面。跑完**必须如实报告通过、失败与未测**：

- 「`/readyz` 绿」**不等于**「业务可用」——本文件第 0 节就是一个反例；
- 缺环境导致的失败**按失败报**，不要降级成「跳过」；
- 结论强度与被测范围匹配：例如端到端**从 `write_episode` 起**的探针，**不构成**对
  「Worker + 队列投递链可用」的证据。

---

## 9. 怎么验证没改坏：前端门禁**必须带 `--filter @campfire/web`**

**根 `package.json` 的 `scripts` 条目数是 0**（实测：`(Get-Content -Raw package.json |
ConvertFrom-Json).scripts` 为空对象）⇒ **根命令 `pnpm typecheck` / `pnpm lint` / `pnpm test`
必然失败**，实测报错为（pnpm 会用细空格装饰前缀，下面按可读形式转写）：

```
ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL Command "typecheck" not found
```

本仓前端脚本都声明在 `apps/web/package.json` 里（`typecheck` / `lint` / `test` / `build` / `dev` /
`shots` 等），**因此正确形式是显式给 workspace 过滤器**：

```bash
pnpm --filter @campfire/web typecheck    # tsc --noEmit
pnpm --filter @campfire/web lint         # oxlint
pnpm --filter @campfire/web test         # vitest run
```

> **为什么写下来**：这属于「命令形式错会得到看起来像『检查失败』的噪声」——报错文本说的是
> 脚本不存在，而读者容易误读成「检查没过」或「仓库坏了」。`AGENTS.md` 的质量门禁一节用的
> 就是带 `--filter` 的形式，两者口径一致。

**本目录（`e2e-real`）相关的命令另有两条**（见第 5 节）：跑探针用
`pnpm --filter @campfire/web exec playwright test --config e2e-real/playwright.real.config.ts …`；
它**不在** `pnpm --filter @campfire/web shots`（`shots` = `playwright test`，收的是 `apps/web/e2e`）
的范围内。
