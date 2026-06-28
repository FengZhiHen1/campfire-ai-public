## 1 功能点：DEPLOY-02 反向代理路由 — 设计文档（瘦身版）

> **文档生成时间**：2026-05-26 21:05:36
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 21:05:36 | AI Assistant | 初始版本，基于技术预研报告生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `DEPLOY-02-反向代理路由-意图文档.md`（已冻结于 2026-05-26 20:58:45）
> - 本模块的精确编码规格见 `DEPLOY-02-反向代理路由-落地规范.md`

### 1.1 技术实现思路

本模块的核心输出是两个 Nginx 配置文件，围绕"配置即代码"的理念组织：`nginx.conf` 定义 Nginx 引擎层参数，`conf.d/campfire.conf` 定义站点层逻辑。选择纯静态配置文件而非模板引擎（如 Jinja2 `nginx.conf.j2`）或配置管理工具（如 Ansible）的原因有三：

**零运行时依赖，部署即就绪**：Nginx 配置文件由 Dockerfile 的 `COPY` 指令在构建期直接打包进镜像，无需在容器启动时执行模板渲染或变量替换。这避免了多环境变量注入到配置文件的复杂度——所有环境差异（如开发 vs 生产的端口）通过 Docker Compose 的端口映射（`8080:80` vs `80:80`）和卷挂载（证书路径）在容器外部消化，配置文件本身不变。技术栈设计 §6.2 约定生产密钥由 KMS → 部署脚本注入环境变量，Nginx 配置不持有任何运行时变量。

**请求管线分层设计**：入站流量经过 443 端口接收后按以下管线处理：

```
TLS 1.3 终端（ssl_protocols 仅启 TLSv1.3，不设 TLSv1.2 回退）
  → 请求头透传（Host、X-Real-IP、X-Forwarded-For、X-Forwarded-Proto）
  → 路由匹配：
    ├── /api/v1/consult/stream → proxy_pass SSE（关闭缓冲、长超时 3600s）
    ├── /api/v1/*               → proxy_pass API（开启缓冲、常规超时 60s）
    ├── /health                 → proxy_pass 健康检查（短超时 10s）
    └── /static/（预留）         → 静态资源 7 天缓存 + gzip
  → 错误拦截（502/503/504 → Nginx 自定义错误页；后端业务错误透传）
```

管线的每一个阶段独立可调：TLS 参数、代理缓冲策略、超时、缓存头之间无耦合，改动任一阶段不影响其他阶段。SSE 流式请求的关闭缓冲策略与常规 API 请求的开启缓冲策略在同一个 `http` 块下通过不同 `location` 块独立实现，互不干扰。

**开发/生产环境差异仅在外围，核心配置不变**：开发环境监听 8080（HTTP）和 8443（HTTPS），生产环境监听 80 和 443。差异仅通过 Docker Compose 的 `ports` 映射实现，Nginx `server` 块内仍然 `listen 80` 和 `listen 443 ssl`。开发环境无 SSL 证书时，`ssl_certificate` 指令指向一个空的占位文件（由 Dockerfile 生成自签名临时证书），生产环境由 Docker Compose `volumes` 将 `infrastructure/nginx/ssl/` 挂载为真实证书。这种"配置文件常量、环境差异外挂"的策略是 DEPLOY-01 设计的显式约定。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：`docs/功能设计/_contracts.md`、`docs/功能设计/` 下六份已有落地规范（KNOW-01、OBS-01、SEC-01、SEC-05、DEPLOY-04、DEPLOY-05）；`docs/篝火智答-技术栈设计.md` §3.1 架构分层图、§5 安全设计；`docs/篝火智答-项目结构.md` §6.1 `infrastructure/nginx/` 目录骨架

- **兼容性结论**：**无冲突**。详细分析如下：

  - **与 DEPLOY-01（容器编排）**：Nginx upstream 地址 `api-server:8000` 与 DEPLOY-01 设计 §1.3 完全一致。SSL 证书路径 `/etc/nginx/ssl/` 与 DEPLOY-01 设计 §1.7 约定的卷挂载路径对齐。Nginx 容器资源限制 0.25 CPU/256MB 来自 DEPLOY-01 设计 §1.6（B2），`worker_connections 1024` 在此资源限制下安全（单连接约 100KB，1024 连接约 100MB + worker 基础 20MB = 120MB，余 136MB）。

  - **与 DEPLOY-05（环境配置管理）**：DEPLOY-05 设计 §1.3 明确"py-config 不直接向 Nginx 提供配置"，Nginx 的域名、SSL 路径等由部署层静态配置。与 DEPLOY-02 的设计边界一致——Nginx 配置不引用 `py-config` 包，不调用 `get_settings()`。

  - **与 SEC-01（传输存储安全）**：TLS 1.3 由 Nginx 在传输层实施，与 SEC-01 的 JWT 签发/校验（应用层安全）职责正交，无重叠。Nginx 仅做 TLS 加密传输，不做身份认证。

  - **与 OBS-01（结构化日志）**：Nginx 访问日志采用 JSON 格式输出 stdout，由 Docker 日志驱动统一管理，与 OBS-01 的 JSON 结构化日志理念一致。Nginx 日志不经过 `py-logger` 包处理，两者为平行管道。

- **复用的已有设计**：无。Nginx 配置文件为独立资产，不复用任何现有模块的类型、接口或状态定义。

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| Docker Compose 内部 DNS | 基础设施依赖 | 通过服务名 `api-server` 解析至 FastAPI 容器 IP，`upstream api-server { server api-server:8000; }` |
| 宿主机端口 | 基础设施依赖 | 生产：80/443 映射至容器 80/443；开发：8080/8443 映射（避免与开发机已有服务端口冲突） |
| SSL 证书文件系统 | 基础设施依赖 | 证书路径 `/etc/nginx/ssl/fullchain.pem` + `/etc/nginx/ssl/privkey.pem`，由 DEPLOY-01 卷挂载提供 |
| Docker HEALTHCHECK | 基础设施依赖 | `nginx -t` 配置校验 + 端口监听检测，参数由 DEPLOY-01 设计 §1.6（B4）约定：interval 30s、timeout 10s、start-period 5s、retries 3 |
| DEPLOY-01 容器编排 | 上游编排依赖 | Nginx 作为 Docker Compose 中的一个服务被编排管理，容器生命周期、网络配置、卷挂载、资源限制均由 DEPLOY-01 控制 |
| DEPLOY-05 环境配置管理 | 间接配置消费 | 域名信息由部署层静态写入 Nginx `server_name` 指令，SSL 证书路径由部署层环境变量映射为挂载点。py-config 不直接向 Nginx 提供配置 |
| Let's Encrypt | 外部服务依赖 | SSL 证书签发与自动续期，具体工具选型（acme.sh / certbot / companion）待用户裁决确认 |
| FastAPI 应用层 (api-server) | 下游代理目标 | Nginx 将 `/api/v1/*` 和 `/health` 请求代理转发至 `api-server:8000`。SSE 流式请求关闭缓冲保证实时透传 |
| 微信小程序客户端 | 上游流量来源 | 客户端发起 HTTPS 请求经 Nginx TLS 终端解密后路由至后端 |

> 精确的函数签名、Cypher 查询模板见落地规范。本模块输出为 Nginx 配置文件，无运行时类型签名。

### 1.4 状态机设计（技术实现策略）

本功能点不涉及状态流转，故无需状态机。反向代理路由为纯请求-响应模式，每次请求独立处理，Nginx 不维护请求之间的状态关系。意图文档 §1.7 已确认此点。

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| §三.2 | 单向依赖 | Nginx 配置不反向依赖任何 app 或 package。它接收来自 Docker 网络层的流量并转发至 FastAPI，但配置本身是 L3 工程支撑层的独立资产。 |
| §三.5 | 最小化可工作 | 不为远期需求预写配置。静态资源 `/static/` 块在当前 MVP 阶段（微信小程序由微信平台托管）仅预留注释模板，不填充实际路径；不为未被规划的功能预留 Nginx location 块。 |
| 技术栈 §5 | 传输安全 | `ssl_protocols TLSv1.3;` 仅启用 TLS 1.3，不设 TLS 1.2 回退。生产环境 80 端口仅做 HTTP→HTTPS 301 重定向，不接受业务数据。与意图文档 §1.11(1) 强制 HTTPS 的约束一致。 |

### 1.6 架构权衡与备选方案

以下记录本模块的 18 项技术决策，其中 12 项已自主确定（依据明确文档或行业实践），6 项来自意图文档 §1.12 留给规范阶段的技术决策，需用户裁决确认。

#### 已自主确定的决策

| # | 决策点 | 最终方案 | 备选方案 | 选择理由 |
|---|--------|---------|---------|---------|
| 1 | TLS 协议版本 | `ssl_protocols TLSv1.3;` 仅启用 TLS 1.3，不设 TLSv1.2 回退 | 同时启用 TLSv1.2 + TLSv1.3 | 意图文档 §1.4(3) 强制不允许降级至更低版本。TLS 1.3 密码套件由协议固定，无需额外 `ssl_ciphers` 配置 |
| 2 | SSL 证书路径 | `/etc/nginx/ssl/fullchain.pem` + `/etc/nginx/ssl/privkey.pem` | 自定义路径 | 与 DEPLOY-01 设计 §1.7 卷挂载路径对齐；Let's Encrypt 默认输出文件名即为 `fullchain.pem` 和 `privkey.pem` |
| 3 | upstream 地址 | `server api-server:8000` | IP 直连 `server 172.x.x.x:8000` | Docker Compose 内部 DNS 自动解析服务名至容器 IP；IP 直连会在容器重启后失效 |
| 4 | 请求头透传 | 透传 `Host`、`X-Real-IP`、`X-Forwarded-For`、`X-Forwarded-Proto` | 仅透传 `Host` | `X-Real-IP` 客户端真实 IP 供限流模块 SEC-04 使用；`X-Forwarded-Proto` 告知后端原始协议是 HTTPS（若后端需生成绝对 URL） |
| 5 | 502 错误页面 | `proxy_intercept_errors on;` + `error_page 502 /502.html;` 返回精简错误页 | 完全透传后端错误（可能返回空白页或连接重置） | 意图文档 §1.8.1 要求返回 502 Bad Gateway 错误页面，需明确告知用户后端不可达而非静默挂起 |
| 6 | 503 错误处理 | `error_page 503 /503.html;` | 同 502 处理 | 意图文档 §1.8.3 要求过载时返回 503 |
| 7 | Gzip 压缩 | `gzip on; gzip_min_length 256; gzip_types application/json text/css text/plain text/javascript; gzip_comp_level 5;` | `comp_level 6-9` 或更宽的 `gzip_types` | 意图文档 AC-04 要求压缩率 ≥ 60%，`comp_level 5` 在压缩率与 CPU 开销间取得合理平衡。`gzip_types` 仅覆盖文本类响应，不压缩已内置压缩的图片 |
| 8 | 开发环境端口 | 8080（HTTP）/ 8443（HTTPS） | 80/443 | DEPLOY-01 设计 §1.7 易错点 1 明确：避免与开发机已有 Web 服务端口冲突。Docker Compose ports 映射实现，Nginx 配置内仍 `listen 80` 不变 |
| 9 | 健康检查转发 | `location /health { proxy_pass http://api-server:8000; proxy_read_timeout 10s; }` | 转发至静态 `return 200` | 意图文档 AC-06 要求转发至 FastAPI 健康检查端点。10 秒超时确保健康检查快速失败不阻塞 Nginx worker |
| 10 | Nginx 容器健康检查 | `HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 CMD nginx -t` | 端口监听检测（`curl localhost:80`）或无健康检查 | DEPLOY-01 设计 §1.6（B4）已约定参数。`start-period 5s` 覆盖 Nginx 冷启动时间 |
| 11 | 请求体大小限制 | `client_max_body_size 10m;` | 默认 1MB 或无限制 | 与 CASE-02（案例附件管理）单文件上限 10MB 对齐；无限制可能被恶意大请求耗尽内存 |
| 12 | 后端业务错误透传 | `proxy_intercept_errors on` 但仅拦截 502/503/504，后端返回的 422/429 等业务错误正常透传 | 全部透传或全部拦截 | FastAPI 的 422（校验失败）和 429（限流触发）含结构化 JSON 错误体，被 Nginx 通用错误页替换后客户端丢失错误细节。仅在 Nginx 确信后端不可达（502/503/504）时使用自定义错误页 |

#### 需用户裁决的决策（来源：意图文档 §1.12）

以下 6 项来自意图文档明确标记为"留给规范阶段的技术决策"。技术预研已为每项提供推荐方案。设计文档以推荐方案为默认推断写入，最终选择期待用户在此确认。

| # | 决策点 | 推荐方案 | 备选方案 | 推荐理由 |
|---|--------|---------|---------|---------|
| 13 | **Nginx 镜像版本**（待确认） | `nginx:1.26-alpine` | `nginx:1.26`（debian-based） | DEPLOY-01 已引用此标签；Alpine 镜像约 23MB（debian 约 200MB），攻击面更小。如无 glibc 兼容性需求（一般为零），Alpine 为首选 |
| 14 | **SSL 证书续期工具**（待确认） | `acme.sh` + DNS-01 挑战 + Aliyun DNS API，宿主机 cron 每日检查 | (A) certbot + HTTP-01（需 80 端口，Nginx 临时关闭有窗口期）；(B) nginx-proxy-companion sidecar（全自动但增加架构复杂度） | DNS-01 无需占用端口，避免与 Nginx 端口竞争；acme.sh 为纯 Shell 脚本零系统依赖；Aliyun DNS API 适配阿里云部署场景 |
| 15 | **worker_connections**（待确认） | `worker_processes auto; worker_connections 1024; multi_accept on;` | `worker_connections 512`（释放内存但并发容量减半） | 容器 256MB 内存下 1024 连接安全（约 120MB 开销 + 136MB 余量）；MVP 用户量级下单用户限流 30 req/min，1024 覆盖数百倍预期流量 |
| 16 | **代理缓冲与超时参数**（待确认） | 三类 location 差异化：(A) 常规 API — `proxy_read_timeout 60s`、`proxy_connect_timeout 30s`；(B) SSE — `proxy_buffering off; proxy_read_timeout 3600s`；(C) `/health` — `proxy_read_timeout 10s` | 全局统一超时或无限制 | 三类请求时效特性完全不同：常规 API 需覆盖 LLM 调用时间；SSE 无固定上限；健康检查需快速失败 |
| 17 | **静态资源预留**（待确认） | 在 `campfire.conf` 中以注释模板留白 `location /static/` 块（含 `expires 7d` + `Cache-Control: public, immutable`），实际路径待 H5 管理后台（远期规划）引入后填充 | 当前阶段不写任何静态资源相关配置 | 当前 MVP 阶段微信小程序由微信平台托管，Nginx 无静态资源可服务。预留配置零成本，避免未来"在哪加配置"的决策成本 |
| 18 | **日志格式与策略**（待确认） | JSON 格式输出 stdout/stderr；`access_log /dev/stdout json; error_log /dev/stderr warn;` | (A) `combined` 格式（human-readable）；(B) 日志级别 `error` | JSON 与 OBS-01 结构化日志理念一致；stdout 由 Docker 日志驱动统一轮转；`warn` 级别确保运维告警不遗漏 |

> 标注"（待确认）"的决策项：后续落地规范将基于推荐方案编写。若用户在确认阶段选择备选方案，将回退修正对应配置参数。

### 1.7 注意事项与禁止行为（设计层面）

1. **[约束：证书路径不可变]** Nginx 容器内 SSL 证书路径 `/etc/nginx/ssl/` 不得自定义为其他路径——此路径由 DEPLOY-01 设计的 `volumes` 指令静态约定。如果更换路径，需要同步修改 DEPLOY-01 的 `docker-compose.yml` 卷挂载声明。

2. **[约束：upstream 不得使用 IP 地址]** `proxy_pass` 的目标不得使用容器 IP 地址（如 `http://172.17.0.3:8000`）。容器重启后 IP 可能变化，必须使用 Docker Compose 服务名 `api-server`，由 Docker 内部 DNS 负责解析。

3. **[约束：开发环境证书降级策略]** 开发环境无 Let's Encrypt 证书时，Nginx 容器必须仍能启动（否则开发者无法本地调试）。策略：Dockerfile 在构建时生成自签名临时证书（`openssl req -x509 -nodes -days 365 -newkey rsa:2048`），挂载到 `/etc/nginx/ssl/`。生产环境通过 Docker Compose `volumes` 将真实证书覆盖挂载。

4. **[易错点：`proxy_intercept_errors` 的作用域]** `proxy_intercept_errors on;` 使 Nginx 能够拦截上游返回的错误状态码并用自定义 `error_page` 替换。但需求是仅拦截 502/503/504（后端不可达），不应拦截 422/429/500（后端业务错误含有用 JSON 响应体）。配置时需注意 `error_page` 指令只声明需要替换的状态码即可，未声明的自动透传。

5. **[设计边界]** 本模块不负责：SSL 证书的签发和申请（acme.sh / certbot 等外部工具处理）；CDN/WAF 的反向代理链配置（当前无 CDN 规划，不在 MVP 范围）；DDoS 防护和 IP 黑名单（由 SEC-04 防刷限流和云服务商安全组负责）；请求级身份认证和授权（AUTH-04 五级 RBAC 鉴权在应用层处理）；API 级限流控制（SEC-04 Redis 滑动窗口限流在应用层处理）。

6. **[设计边界]** `/static/` 静态资源块当前仅预留位置，不绑定任何具体路径或目录。后续 H5 管理后台引入后，由前端构建流程确定 `root` 路径和缓存策略。

7. **[禁止行为]** 禁止在 Nginx 配置中硬编码任何密钥或凭证（如 SSL 私钥内容、API Key）。证书文件通过文件系统挂载提供，密钥永远不写入配置文件。

8. **[禁止行为]** 禁止在 `nginx.conf` 的 `http` 块中为所有 location 全局关闭代理缓冲（`proxy_buffering off;`）。这会破坏常规 API 响应的效率和错误处理——缓冲关闭是 SSE 流式请求的专属特性。

### 1.8 引用：配套意图文档

- **意图文档**：`DEPLOY-02-反向代理路由-意图文档.md`
- **冻结时间**：2026-05-26 20:58:45
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。所有 8 项验收标准（AC-01 至 AC-08）均有对应的技术实现路径：AC-01（TLS 1.3）→ 决策 #1；AC-02（API 代理）→ 决策 #3；AC-03（缓存）→ 决策 #17；AC-04（Gzip）→ 决策 #7；AC-05（SSL 续期）→ 决策 #14；AC-06（健康检查）→ 决策 #9；AC-07（SSE）→ 决策 #16；AC-08（502 错误）→ 决策 #5。6 项待确认决策均标注在 §1.6 中，确认前不影响设计文档的整体有效性。如有歧义，以意图文档为准。
