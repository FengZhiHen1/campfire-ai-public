# 生产部署

本目录是生产部署产物。README 说明**怎么用**，以及**哪些输入必须由运维提供**。

## 文件

| 文件 | 作用 |
|---|---|
| `docker/Dockerfile.api` | 后端镜像（HTTP 与 Worker 共用，启动命令不同） |
| `docker/Dockerfile.web` | 前端镜像（Node 构建 → Nginx 静态托管） |
| `docker/nginx.conf` | 反代 + SPA 托管 + SSE 支持 |
| `docker/entrypoint-api.sh` | API 容器入口（可选跑迁移） |
| `../docker-compose.prod.yml` | 生产编排（数据服务不暴露宿主端口，仅 web 对外） |
| `../.dockerignore` | 构建上下文排除（**含凭据排除**，见下） |
| `../.env.example.prod` | 生产环境变量模板 |

## 部署步骤

```bash
# 1. 准备凭据（不得提交；.gitignore 已忽略 .env.* 并放行 .example）
cp .env.example.prod .env.prod
#    逐项填入真实值。所有 CHANGE_ME_* 都必须替换。

# 2. 构建并启动
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build

# 3. 迁移（api 容器默认 RUN_MIGRATIONS=1 会自己跑；发布流程通常想先迁移再切流量）
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm api alembic upgrade head

# 4. 验证（必须用 /readyz，不要用 /livez）
curl -fsS https://<你的域名>/readyz
```

### 为什么验证必须用 `/readyz` 而不是 `/health` 或 `/livez`

三个端点的分工是这次为「消灭假健康」特意拆开的：

- `/livez`：进程活着即 200，**不探依赖**。依赖挂了重启进程没有意义，所以它只用于容器
  liveness（`web` 的 healthcheck 用它）。
- `/readyz`：七项全通才 200 —— `auth`、`database`、`queue`、`model`、`falkordb`、
  `agent_assembly`、`skills`。**这是给部署系统、Nginx upstream 与 CD 用的判据。**
- `/health`：与 `/readyz` 同一份探针清单（结论不会漂移），面向人排查。

拆开的直接原因：此前只有一个 `/health`，四项依赖全通就 200，而 **Agent 装配不在检查
范围内**。于是存在这种状态——

```
GET /health   → 200 OK
POST /consult → 503        # 运行器没装配
```

部署系统会认为一个核心咨询功能必然失败的版本已经健康。`agent_assembly` 项就是为堵这一点。

**`api` 容器的 healthcheck 用的是 `/readyz`**：若用 `/livez`，上述假健康会原样复现。

## 需要运维提供的输入（仓库中不存在任何事实）

以下四项在仓库里**没有任何事实依据**——`docs/服务器选型事实基线.md` 与 `docs/TODO.md`
都明确写「未定」。因此本目录不填任何看似合理的默认值：

| 输入 | 用在哪 | 现状 |
|---|---|---|
| 域名 | `.env.prod` 的 `SUPERTOKENS_API_DOMAIN` / `SUPERTOKENS_WEBSITE_DOMAIN` / `PUBLIC_BASE_URL`，以及 `nginx.conf` 的 `server_name` | 不存在。占位符是 `_`（匹配任意 Host） |
| TLS 证书 | `infrastructure/nginx/ssl/`（挂载到容器 `/etc/nginx/ssl`） | 仓库内**无证书**；`nginx.conf` 的 TLS server 块**默认整段注释** |
| 服务器 | CD 的 Secrets（见 `.github/workflows/deploy.yml`） | 不存在 |
| 生产凭据 | `.env.prod` 全部 `CHANGE_ME_*` | 只有模板；dev 的 `.env` 是**占位值**（实测 `changeme`、`change-me-to-a-random-secret`、`minioadmin`），**不得用于生产** |

`docker-compose.prod.yml` 对关键凭据用了 `${VAR:?}` 语法，**缺值即启动失败**。这是刻意的：
默认值会静默生效，而缺值会立刻报错。

### TLS 启用步骤

`nginx.conf` 里 HTTPS 的 `server` 块是注释状态，因为仓库里没有证书，默认启用会让镜像在
无证书环境启动即崩。证书就位后：

1. 把 `fullchain.pem` 与 `privkey.pem` 放到 `infrastructure/nginx/ssl/`；
2. 取消 `nginx.conf` 中 `listen 443 ssl` 那个 `server` 块的注释，填 `server_name`；
3. 复制 80 端口 server 里的四个 `location`（不要在那里重新设计路由表）；
4. `docker compose -f docker-compose.prod.yml restart web`。

## 几条关键取舍（改动前请先读）

### 数据服务不暴露任何宿主端口

`docker-compose.prod.yml` 里 postgres/redis/falkordb/supertokens 都只写 `expose`，
**不写 `ports`**。dev 那份绑回环（`127.0.0.1:`）对本地开发是对的，但生产不需要宿主访问
——只有 api/worker 经容器内网连它们。完全不写端口比写回环更安全：回环也仍是宿主上的
一个开放端口，任何能在宿主上执行命令的进程都能直连数据库。

### api 必须单 worker

取消路径的索引在**进程内**（`apps/api/src/campfire/surfaces/consult/runbus.py` 明写
「一期是单进程 uvicorn，这个边界不成立；多进程部署时需要把取消改成走共享信道」）。
`uvicorn --workers N`（N>1）会让取消端点返回 **409 假阴性**——请求落在没有该运行状态的
那个进程上。需要横向扩容时，应先实现共享取消信道，而不是直接加 worker 数。

### 镜像内保持仓库目录层级

`Dockerfile.api` **不把包安装进 site-packages**，而是复制目录树。原因：
`apps/api/src/campfire/core/config.py` 用 `Path(__file__).resolve().parents[5]` 当仓库根、
`parents[3]` 当 apps/api，据此定位 `.env` 与 `skill_root`。装进 site-packages 后这两个下标
会指向 `/usr/local/lib/python3.12` 与 `/usr/local`，`.env` 与 skill 目录全错。
镜像内实测：`_REPO_ROOT=/app`、`_APP_ROOT=/app/apps/api`、`skill_root=/app/apps/api/skills`
（4 个 skill 齐全）。

`apps/api/skills/` 在 `src/campfire` 之外，而 hatch 的 wheel 只打包 `src/campfire`，
因此它**必须单独 COPY**——漏了会让 `/readyz` 的 `skills` 项报不可用，且模型没有技能可依。

### SSE 反代不能开 buffering

契约要求 `: ping` 心跳每 15 秒（原文「仅防代理超时」），单次运行上限 180 秒
（`docs/技术设计/面/consult/HTTP与SSE契约.md`）。Nginx 默认 `proxy_buffering on` 会把事件
攒在缓冲区里，客户端变成「很久没反应、然后一次收到一大段」，心跳也失去意义；默认
`proxy_read_timeout 60s` 会在运行中途切断长回答。因此 `nginx.conf` 为 SSE 路径单独设了
`proxy_buffering off` 与 `proxy_read_timeout 3600s`。

### Nginx 用变量式 upstream

`nginx.conf` 用 `set $campfire_api "api:8000"` + `resolver 127.0.0.11` 而不是
`upstream { server api:8000; }`。静态 upstream 在 **nginx 启动时只解析一次**并缓存 IP，
而发布时 api 容器会被重建、IP 变化——那时 nginx 若没一起重启就会持续 502，直到有人手动
reload。用变量后按 `valid=10s` 重新解析，最多 10 秒自愈。代价是失去 upstream 的连接复用，
对本应用可接受（SSE 是长连接，普通 API 请求在容器网络内建连成本可忽略）。

## 构建上下文与凭据

`.dockerignore` 存在的主要理由之一是**凭据**：仓库根的 `.env` 装的是可用的数据库口令与
API key。上下文一旦送出，任何 `COPY . .` 都会把它带进镜像层，而那一层即使后续删除也留在
构建缓存与镜像历史里。实测确认：构建出的 api 镜像内 `/app/.env` **不存在**。

它同时排除了 `.venv`（372 MB）、`node_modules`（536 MB）、`.mypy_cache`（88 MB）、
`.tmp`（110 MB）、`archive`（103 MB）——仓库根约 1.3 GB。

## 镜像大小（如实记录）

实测：`campfire-web` 约 75 MB，`campfire-api` 约 **1.6 GB**。后者偏大，主要来自
llama-index / graphiti-core / openai-agents 等依赖闭包。这是一个可优化的项（多阶段裁剪、
`--no-install-project` 之外的精简），但没有阻塞部署，故未在本轮处理——如实记录而不是
声称已优化。
