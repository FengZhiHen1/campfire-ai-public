篝火智答（Campfire-AI）· 部署与使用说明
==========================================

本文件说明如何在本地把「篝火智答」跑起来，以及如何使用它的两条主链路。
命令与端口以本仓的 compose 文件、Dockerfile 与运维文档为准。

--------------------------------------------------------------------------------
一、组成

  后端  apps/api         FastAPI + Worker（Taskiq），Python 3.12，依赖用 uv 管理
  前端  apps/web         React 19 + Vite，依赖用 pnpm 管理
  数据  PostgreSQL+pgvector（主库与向量）、Redis（缓存/限流/队列）、FalkorDB（记忆层图库）
  认证  SuperTokens core（+ postgres 存储）
  入口  Nginx（生产编排里是唯一对外入口）

  注意：开发编排（docker-compose.yml）与生产编排（docker-compose.prod.yml）**不是一套**。
  开发编排默认只含四个基础设施服务（falkordb、postgres、redis、supertokens），
  不含 api / web / nginx；应用在本地开发时直接跑（uv / pnpm）。
  MinIO 在本仓**已无消费者**，默认不启动：在 `attachments` profile 下，
  用 Chainguard 的社区构建（上游官方镜像已下架，见第六节第 5 条）。

--------------------------------------------------------------------------------
二、前置条件

  * Docker 与 Docker Compose v2
  * 若要本地开发（不经容器）：Python 3.12 + uv、Node 24 + pnpm
  * 一个可用的模型服务凭据（对话模型与嵌入模型，经 OpenAI 兼容接口调用）

--------------------------------------------------------------------------------
三、起服务（本地开发编排）

  1) 准备环境变量
       复制 .env.example 为 .env，填写数据库口令、模型服务地址与凭据等。
       **.env 不在版本控制内**（见 .gitignore），也不要提交任何真实凭据。

  2) 校验编排文件
       docker compose -f docker-compose.yml config

  3) 起服务
       docker compose -f docker-compose.yml up -d

  4) 数据库迁移
       迁移脚本在 apps/api/migrations/；容器/本地两种执行方式与运维细节见 docs/运维/。

  5) 应用
       后端与前端在本地以 uv / pnpm 启动；后端存活与就绪探针为 /livez 与 /readyz。

--------------------------------------------------------------------------------
四、使用

  两条主链路（工作流与 Skill 内容见 apps/api/skills/ 与 docs/技术设计/面/consult/）：

  * 日常咨询：提交一段情境描述，系统检索资料库并给出分步建议，附引用来源；
  * 应急链路：从应急入口发起一次运行，系统按优先级给出「先做什么」的行动卡。

  资料库与记忆层的写入受"待确认写入"机制约束：模型提出的写操作需人工确认后落库。

--------------------------------------------------------------------------------
五、许可与边界

  * 代码与提示词：Apache License 2.0（见 LICENSE）；
  * 语料层：见 LICENSE-DATA；逐件署名与义务见 ATTRIBUTION.md；
  * 本作品是软件工具，不构成医疗建议或专业意见；
  * 真实访谈案例语料与部分第三方语料不随本仓分发（原因见 NOTICE 第三节）。

--------------------------------------------------------------------------------
六、验证状态（只写实际跑过的事实）

  记录时间：2026-10-15（本机 Docker client/server 29.8.2）

  1. `docker compose -f docker-compose.yml config --quiet`
     → 退出码 0 ✓（编排文件语法与变量解析通过）

  2. 默认服务集 `docker compose -f docker-compose.yml config --services`
     → falkordb、postgres、redis、supertokens ✓
     （MinIO 在 `attachments` profile 下，默认 `up` 不引用它；
       `--profile attachments config --services` 才列出 minio）

  3. `docker compose ... up -d --wait --wait-timeout 300`（默认服务集）
     → 退出码 0 ✓，四个服务全部 Healthy ✓
     做法说明：本机已有同名容器在跑（compose 项目 `campfire-ai`，
     工作目录 `E:\Project\Web_Development\Campfire-AI`，已运行 14 小时），
     且 5432/6379 等回环端口被占用；为不动既有开发栈，验证在隔离项目名
     `campfire-verify` 下进行：临时 override 改容器名并 `!reset` 掉宿主端口。
     验证后 `down -v` 已回收全部临时容器、卷与网络（实测既有四个容器未受影响）。

  4. `docker compose ... --profile attachments up -d --wait --wait-timeout 300`（含 MinIO）
     → 退出码 0 ✓，**五个服务全部 Healthy** ✓（含 `campfire-verify-minio`）
     进容器内实测：`:9000/minio/health/live` → `HTTP/1.1 200 OK` ✓；`:9001` console → `200` ✓

  5. 历史缺陷（已修）：2026-10-14 20:34 实测 `up` 失败，报
     `pull access denied for minio/minio, repository does not exist or may require 'docker login'`。
     当时的归因「未钉 tag」**不完整**：2026-10-15 复测 `docker pull minio/minio`、
     `minio/minio:RELEASE.2025-04-22T22-12-26Z`、`quay.io/minio/minio:<同 tag>`、
     `ghcr.io/minio/minio` 全部失败——上游已下架公开镜像，**不存在可钉的 tag**。
     现修法（两步）：
       (a) minio 移入 `attachments` profile，默认 `up` 不再引用它（见第 2、3 条）；
       (b) 镜像改用社区构建 `cgr.dev/chainguard/minio@sha256:2136d593…fee0c8`
           （Chainguard，Wolfi 基底，内含上游 MinIO `RELEASE.2026-09-22T19-25-18Z`，
            构建于 2026-10-13，仍在持续重建），并按 digest 钉版（多架构索引）。
           该镜像内**没有 curl/wget**，因此 healthcheck 改用镜像自带 bash 的
           `/dev/tcp` 探测 9000 端口连通性（非 HTTP 语义探测）。
     未采纳的候选：`bitnamilegacy/minio`（实测按本编排启动参数直接 FATAL，且属停更遗留快照）、
     `pgsty/silo`、`rustfs/rustfs`（同为社区/派生实现，未在本编排实测）。

  6. 应用层（api / web）按本仓约定在宿主机以 uv / pnpm 运行，不在本开发编排内；
     生产编排 `docker-compose.prod.yml` 是另一份产物（见 `infrastructure/README.md`
     与 `docs/运维/`）。

  结论：**部署已验证通过** ✓ —— 开发编排 `docker compose -f docker-compose.yml up -d`
  （四个数据服务）与 `--profile attachments`（含 MinIO）两条路径**都已在本机实测跑通**：
  配置解析通过、服务全部拉起并 healthy、MinIO 的 S3 API 与 console 均返回 200。
  （2026-10-14 记的 ✗ 系 MinIO 上游下架公开镜像所致，已按第 5 条修掉。）
