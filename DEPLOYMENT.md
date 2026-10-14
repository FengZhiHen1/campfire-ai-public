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
  开发编排目前只含基础设施服务（falkordb、minio、postgres、redis、supertokens），
  不含 api / web / nginx；应用在本地开发时直接跑（uv / pnpm）。

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

  记录时间：2026-10-14 20:34—20:36（本机 Docker client/server 29.8.2）

  1. `docker compose -f docker-compose.yml config --quiet`
     → 退出码 0 ✓（编排文件语法与变量解析通过）

  2. `docker compose -f docker-compose.yml up -d --wait --wait-timeout 600`（全服务）
     → **失败** ✗：拉取 `minio/minio` 被拒
       `pull access denied for minio/minio, repository does not exist or may require 'docker login'`
     原因（仓侧）：开发编排引用的是**未钉 tag** 的 `minio/minio`；MinIO 在一期没有消费者，
     本就只保留在开发编排里。**这是本仓的已知缺陷**：照现状 `up` 起不来。

  3. 排除 MinIO 后 `up -d --wait`（falkordb、postgres、redis、supertokens）
     → **失败** ✗：容器名冲突
       `Conflict. The container name "/campfire-falkordb" is already in use`
     原因（环境侧）：本机已有同名容器在跑（既有开发栈），与仓无关。

  4. 端点探活：/livez、/readyz、:5173、:8080、:3000 → 均无响应 ✗。
     说明：开发编排本就不含 api / web / nginx，这四个端口不在开发编排的预期内。

  结论：**部署未验证通过** ✗。要满足"部署可复现"这一判据，需：
    (a) 修掉开发编排里未钉 tag 的 MinIO 镜像引用（或明确标为可选 profile）；
    (b) 在一个没有同名容器的干净 Docker 环境里重跑；
    (c) 起应用层（api/web）并实际登录、跑通一次应急链路。
  在此之前，本仓不声称"部署已验证"。
