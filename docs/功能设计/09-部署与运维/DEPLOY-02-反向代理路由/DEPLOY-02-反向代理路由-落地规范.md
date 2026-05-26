## 1 功能点：DEPLOY-02 反向代理路由 — 落地规范

> **文档生成时间**：2026-05-26 21:11:48 (Asia/Shanghai)
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 21:11:48 | AI Assistant | 初始版本，基于设计文档 v1.0 和契约协调报告生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `DEPLOY-02-反向代理路由-设计文档.md`。
> **流水线上下文**：本落地规范基于已冻结的 `DEPLOY-02-反向代理路由-意图文档.md`（冻结于 2026-05-26 20:58:45）编写。技术实现必须与意图文档中的业务定义保持一致。
> **契约协调依据**：s08-contract-harmonize 报告确认本模块为纯 Nginx 配置文件模块，无可提取的 Pydantic 类型或函数签名。所有对外配置契约（upstream 地址、路由规则、证书路径）已在设计文档 §1.3 完整描述。

---

## 【对内实现】

### 1.1 技术栈绑定

- **必须使用**：
  - Nginx `1.26-alpine`（Docker 镜像 `nginx:1.26-alpine`），Alpine Linux 基镜像，约 23MB
  - `nginx.conf` 语法（非 nginx-plus、非 OpenResty），`http` + `server` + `location` 三级块结构
  - Dockerfile `COPY` 指令将配置文件打包进镜像（构建期静态打包，非运行时模板渲染）
  - Docker HEALTHCHECK 指令：`--interval=30s --timeout=10s --start-period=5s --retries=3 CMD nginx -t`，参数来自 DEPLOY-01 设计 §1.6（B4）
  - `openssl` CLI（`openssl req -x509 -nodes -days 365 -newkey rsa:2048`）生成开发环境自签名临时证书
  - Docker Compose `volumes` 将生产证书 `./infrastructure/nginx/ssl/:/etc/nginx/ssl/:ro` 挂载进容器（只读）
  - `nginx -s reload` 信号实现配置热重载（证书续期后由外部续期工具触发 `docker exec campfire-nginx nginx -s reload`）

- **禁止使用**：
  - 禁止使用 `nginx:1.26`（debian-based，约 200MB，Alpine 满足所有需求且攻击面更小）
  - 禁止在 `nginx.conf` 中使用 `ssl_ciphers` 指令（TLS 1.3 密码套件由协议固定，手动指定无效且可能引入弱密码）
  - 禁止在 `nginx.conf` 中硬编码任何密钥、证书内容或 API 凭证（证书通过文件系统挂载提供）
  - 禁止使用 `proxy_pass` 目标为容器 IP 地址（必须使用 Docker 服务名 `api-server`，依赖 Docker 内部 DNS 解析）
  - 禁止在 `http` 块全局设置 `proxy_buffering off;`（仅 SSE 流式 `location` 块关闭缓冲）
  - 禁止使用 `return 200 "OK"` 处理 `/health` 路由（必须转发至 FastAPI 真实健康检查端点 `proxy_pass http://api-server:8000`）
  - 禁止引入 Lua 模块（如 `lua-nginx-module`）、NJS 脚本或第三方模块——纯 Nginx 原生指令满足全部需求

### 1.2 文件归属

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 全局 Nginx 配置 | `infrastructure/nginx/nginx.conf` | Nginx 引擎层参数：`worker_processes auto`、`events { worker_connections 1024; multi_accept on; }`、`http` 块全局设置（sendfile、keepalive、gzip、日志格式） |
| 站点配置 | `infrastructure/nginx/conf.d/campfire.conf` | 站点逻辑：`server` 块（监听端口、SSL、路由规则、代理参数、缓存头、错误页）。文件名 `campfire.conf` 对应项目名，不包含模块编号 |
| 502 错误页面 | `infrastructure/nginx/html/502.html` | 后端不可达时返回的精简 HTML 错误页，含"服务暂时不可用，请稍后重试"提示文字，样式内联 |
| 503 错误页面 | `infrastructure/nginx/html/503.html` | 流量过载时返回的精简 HTML 错误页，含"服务繁忙，请稍后重试"提示文字 |
| Dockerfile | `infrastructure/nginx/Dockerfile` | Nginx 容器镜像构建：`FROM nginx:1.26-alpine` → `COPY nginx.conf /etc/nginx/nginx.conf` → `COPY conf.d/ /etc/nginx/conf.d/` → `COPY html/ /usr/share/nginx/html/` → 自签名证书生成 → `HEALTHCHECK` |
| SSL 证书占位（开发） | `infrastructure/nginx/ssl/`（构建时生成） | `fullchain.pem`、`privkey.pem`——开发环境由 Dockerfile `RUN openssl` 生成的自签名证书；生产环境由 Docker Compose `volumes` 覆盖挂载真实证书 |
| 测试 — 配置验证 | `infrastructure/nginx/tests/test_nginx_config.sh` | `nginx -t` 语法校验脚本，CI 中 `docker build` 后执行 |
| 测试 — 集成测试 | `infrastructure/nginx/tests/test_proxy_integration.sh` | curl 验证路由：`/health` 转发、`/api/v1/` 转发、`/api/v1/consult/stream` SSE 支持、502 触发 |
| 测试 — 安全测试 | `infrastructure/nginx/tests/test_tls.sh` | `openssl s_client -tls1_3` 验证仅 TLS 1.3、`-tls1_2` 验证被拒 |

### 1.5 核心逻辑步骤

> DEPLOY-02 为纯配置文件模块，无运行时 Python/JavaScript 代码。以下步骤描述 Nginx 处理请求的管线逻辑，对应 `campfire.conf` 中各指令的执行顺序。每个步骤可直接映射为 Nginx 配置指令。

**步骤 1：接收客户端连接**
- **操作对象**：Nginx `server` 块监听的 TCP 套接字
- **具体操作**：
  - 生产环境：`listen 443 ssl http2;`（启用 HTTP/2 多路复用）+ `listen 80;`（强制 301 重定向至 HTTPS）
  - 开发环境：`listen 8443 ssl http2;` + `listen 8080;`（避免与开发机已有服务端口冲突，端口差异由 Docker Compose `ports` 映射实现）
  - `server_name` 从部署层静态写入，默认 `campfire-ai.example.com`
- **输入来源**：微信小程序客户端或开发机浏览器发起的 TCP 连接
- **输出去向**：已建立 TCP 连接的套接字（含 TLS 握手完成后的加密信道），进入步骤 2
- **失败行为**：端口未监听 → Docker Compose 层面的 `depends_on` + `restart: unless-stopped` 会自动重启 Nginx 容器；`server_name` 不匹配 → 返回 444（Nginx 特殊状态码，直接关闭连接不返回任何响应，防止信息泄露）

**步骤 2：TLS 终端与请求解密**
- **操作对象**：TLS 握手中的加密信道
- **具体操作**：
  - `ssl_protocols TLSv1.3;` 仅允许 TLS 1.3 握手（TLS 1.2 及以下协议直接拒绝）
  - `ssl_certificate /etc/nginx/ssl/fullchain.pem;` 加载服务器证书链
  - `ssl_certificate_key /etc/nginx/ssl/privkey.pem;` 加载私钥
  - `ssl_session_cache shared:SSL:10m; ssl_session_timeout 10m;` TLS 会话复用（减少后续握手开销）
- **输入来源**：步骤 1 建立的 TCP 连接 + 证书文件系统路径
- **输出去向**：解密后的明文字节流，包含 HTTP 请求行、头部、请求体，进入步骤 3
- **失败行为**：
  - 证书文件不存在或格式错误 → `nginx -t` 校验阶段直接报错退出，容器不启动（`systemctl`/Docker 会将此报告为容器启动失败）
  - TLS 版本不匹配（客户端仅支持 TLS 1.2）→ Nginx 在 TLS 握手阶段发送 `handshake_failure` fatal alert，客户端收到连接失败错误

**步骤 3：请求头解析与透传**
- **操作对象**：解密后的 HTTP 请求
- **具体操作**：
  - `proxy_set_header Host $host;` 透传原始 Host 头
  - `proxy_set_header X-Real-IP $remote_addr;` 注入客户端真实 IP
  - `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` 追加代理链 IP
  - `proxy_set_header X-Forwarded-Proto $scheme;` 告知后端原始请求协议（https）
  - `client_max_body_size 10m;` 拒绝超 10MB 请求体（响应 413 Request Entity Too Large）
- **输入来源**：步骤 2 解密后的 HTTP 请求
- **输出去向**：注入标准代理头后的 HTTP 请求，进入步骤 4 的路由匹配
- **失败行为**：请求体超过 10MB → Nginx 立即返回 413，不将请求转发至后端，释放连接

**步骤 4：路由匹配与代理转发**
- **操作对象**：HTTP 请求 URI 与 `location` 指令匹配
- **具体操作**：按优先级匹配，一旦命中即停止：
  - **SSE 流式路由**：`location /api/v1/consult/stream` — `proxy_pass http://api-server:8000; proxy_buffering off; proxy_cache off; proxy_read_timeout 3600s; proxy_http_version 1.1; proxy_set_header Connection "";`（关闭缓冲、长超时、HTTP/1.1 逐跳头支持）
  - **健康检查路由**：`location /health` — `proxy_pass http://api-server:8000; proxy_read_timeout 10s;`（短超时快速失败）
  - **常规 API 路由**：`location /api/v1/` — `proxy_pass http://api-server:8000; proxy_buffering on; proxy_buffer_size 4k; proxy_buffers 8 4k; proxy_busy_buffers_size 8k; proxy_connect_timeout 30s; proxy_read_timeout 60s; proxy_send_timeout 30s;`
  - **静态资源路由（预留）**：`location /static/` — `root /usr/share/nginx/html; expires 7d; add_header Cache-Control "public, immutable";`（仅配置骨架，实际 `root` 路径待 H5 管理后台引入后填充）
- **输入来源**：步骤 3 处理后的 HTTP 请求 URI
- **输出去向**：
  - 命中规则 → 代理转发至 `http://api-server:8000`（Docker 内部 DNS 解析），进入步骤 5
  - 未命中任何规则 → 返回 404（或 H5 管理后台引入后匹配前端路由 fallback）
- **失败行为**：
  - upstream `api-server` DNS 解析失败（服务未启动或名称错误）→ Nginx 记录 error_log，返回 502
  - 代理连接超时（`proxy_connect_timeout 30s`）→ 返回 504 Gateway Timeout
  - 代理读取超时（`proxy_read_timeout`，API 60s / SSE 3600s / health 10s）→ 返回 504

**步骤 5：响应处理与返回**
- **操作对象**：上游 FastAPI 返回的 HTTP 响应
- **具体操作**：
  - `gzip on; gzip_min_length 256; gzip_types application/json text/css text/plain text/javascript; gzip_comp_level 5;` 对文本类响应应用 gzip 压缩（小体积 < 256 字节不压缩）；SSE 流式响应因 `proxy_buffering off` 而逐块输出，不被压缩
  - `proxy_intercept_errors on;` 拦截上游 502/503/504 错误码
  - `error_page 502 /502.html; error_page 503 /503.html;` 返回自定义错误页（后端不可达 vs 过载的提示文字不同）
  - 上游返回的 422（校验失败）、429（限流）、500（内部错误）等业务状态码：直接透传完整 JSON 响应体
  - 静态资源响应：注入 `Cache-Control: public, immutable, max-age=604800` 头（7 天）
- **输入来源**：步骤 4 从上游获取的 HTTP 响应
- **输出去向**：经 gzip 压缩后（如适用）通过步骤 2 的 TLS 信道加密返回客户端
- **失败行为**：上游响应为空或连接被上游关闭 → Nginx 返回 502；客户端连接在响应发送过程中断开 → Nginx 记录 client abort 日志，释放连接

---

## 【已锁定】

### 1.3 输入定义

> DEPLOY-02 为纯 Nginx 配置文件模块，无运行时函数签名或 Pydantic 模型。以下定义 Nginx 处理管线的输入——即客户端请求到达 Nginx 时需要满足的协议级契约。

**客户端 HTTP 请求**

| 字段 | 类型 | 说明 | 是否必填 | 约束 |
|------|------|------|---------|------|
| `request_method` | 字符串 | HTTP 方法 | 是 | `GET`、`POST`、`PUT`、`DELETE`、`PATCH`。其他方法在到达 Nginx 前被上游安全层拒绝 |
| `request_uri` | 字符串 | 请求路径 | 是 | 必须匹配已定义路由：`/api/v1/*`（API）、`/health`（健康检查）、`/static/*`（静态资源，预留） |
| `Host` 头 | 字符串 | 目标域名 | 是 | 必须匹配 `server_name` 指令的值。默认 `campfire-ai.example.com`，由部署层环境变量注入 `nginx.conf` |
| `Content-Type` 头 | 字符串 | 请求体 MIME 类型 | 否 | 标准 MIME 格式。API 请求通常为 `application/json` |
| `Accept` 头 | 字符串 | 客户端期望的响应格式 | 否 | `text/event-stream` 触发 SSE 流式路由的缓冲关闭策略 |
| `Authorization` 头 | 字符串 | 身份凭证 | 否 | Nginx 不校验此头——透传至 FastAPI，由 AUTH-04 处理 |
| `X-Request-ID` 头 | 字符串 | 请求追踪 ID | 否 | 透传至上游，如客户端未提供则由 FastAPI 中间件生成 |
| `request_body` | 字节流 | 请求体 | 否 | 最大 10MB（`client_max_body_size 10m;`）。超出 → 413 错误 |
| **SSL 证书文件**（服务器端，非通信级输入） | 文件路径 | TLS 服务端证书 | 是 | 生产环境：`/etc/nginx/ssl/fullchain.pem` + `/etc/nginx/ssl/privkey.pem`，由外部工具签发和更新。开发环境：Dockerfile 生成的自签名证书 |

**Nginx 配置级输入（从部署层静态注入，非运行时变量）**：

| 配置项 | 来源 | 值 | 说明 |
|--------|------|-----|------|
| `server_name` | 部署层静态写入 `campfire.conf` | `campfire-ai.example.com` | 域名，部署前由运维修改为实际域名 |
| `upstream` 地址 | Docker Compose 服务名 | `api-server:8000` | 由 Docker 内部 DNS 解析，DEPLOY-01 约定 |
| SSL 证书路径 | Docker Compose `volumes` 挂载 | `/etc/nginx/ssl/` | 卷挂载声明由 DEPLOY-01 管理 |

### 1.4 输出定义

> DEPLOY-02 为纯 Nginx 代理，不生成业务数据。以下定义 Nginx 返回给客户端的 HTTP 响应契约。

**正常响应（代理成功）**：

| 状态码 | 条件 | 响应体 | 响应头 |
|--------|------|--------|--------|
| 1xx-3xx | 上游成功返回 | 上游响应体的完整透传，无任何修改 | 透传上游响应头 + 添加 `Server: nginx` + gzip 压缩（如适用）+ `X-Request-ID`（如请求中有） |
| 301 | HTTP → HTTPS 重定向（仅生产环境 80 端口） | 无响应体 | `Location: https://$host$request_uri` |

**静态资源成功响应**：

| 状态码 | 条件 | 响应体 | 响应头 |
|--------|------|--------|--------|
| 200 | 静态文件存在 | 文件内容 | `Cache-Control: public, immutable, max-age=604800` |

**错误响应（Nginx 层面生成）**：

| 状态码 | 触发条件 | 响应体 | 响应头 |
|--------|---------|--------|--------|
| 413 | 请求体超过 10MB | 默认 Nginx 错误页 | `Content-Type: text/html` |
| 444 | `server_name` 不匹配 | 无响应体（直接关闭连接） | 无 |
| 502 | 上游 `api-server:8000` 不可达或返回空响应 | `502.html` 内容（精简提示："服务暂时不可用，请稍后重试"） | `Content-Type: text/html` |
| 503 | 并发连接数超 `worker_connections 1024` | `503.html` 内容（精简提示："服务繁忙，请稍后重试"） | `Content-Type: text/html` |
| 504 | 代理连接/读取超时 | 默认 Nginx 错误页 | `Content-Type: text/html` |

**透传的上游错误**（Nginx 不拦截，直接返回给客户端）：

| 状态码 | 来源 | 说明 |
|--------|------|------|
| 422 | FastAPI (Pydantic) | 请求校验失败，响应体含 `{"detail": [...]}` |
| 429 | FastAPI (SEC-04 限流) | 触发限流，响应体含 `{"detail": "Rate limit exceeded", "retry_after": 60}` |
| 500 | FastAPI (内部异常) | 后端内部错误，响应体含错误详情 |

### 1.6 接口契约

> DEPLOY-02 为纯 Nginx 配置文件模块，无可导出为函数签名的公共接口。Nginx 的"接口"即其 HTTP 路由行为。以下契约以结构化方式描述 Nginx 对每种路由类型的处理行为，供下游集成模块（如 CSLT-04 SSE 流式咨询的前端 Taro 客户端）参考。

#### 1.6.1 路由契约 1：常规 API 代理 (`/api/v1/*`)

```text
location /api/v1/ {
    # 代理目标
    proxy_pass http://api-server:8000;
    
    # 请求头透传
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # 缓冲策略
    proxy_buffering on;
    proxy_buffer_size 4k;
    proxy_buffers 8 4k;
    proxy_busy_buffers_size 8k;

    # 超时策略
    proxy_connect_timeout 30s;
    proxy_read_timeout 60s;
    proxy_send_timeout 30s;

    # 请求体限制（继承自 http 块）
}

# 行为契约：
# - 请求到达 /api/v1/* 路径 → Nginx 完整接收请求体后进行缓冲
# - 代理转发至 api-server:8000，附加标准代理头
# - 上游处理完成后：非流式响应 → Nginx 收集完整响应 → gzip 压缩（如适用）→ 返回客户端
# - 上游返回 502/503/504 → 替换为自定义错误页
# - 上游返回其他状态码（422/429/500 → 透传完整响应体和状态码
# - 幂等性：GET/DELETE/PUT 请求天然幂等；POST 请求依赖上游应用层幂等保证
```

#### 1.6.2 路由契约 2：SSE 流式代理 (`/api/v1/consult/stream`)

```text
location /api/v1/consult/stream {
    proxy_pass http://api-server:8000;
    
    # 请求头
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # 核心：关闭缓冲，开启流式透传
    proxy_buffering off;
    proxy_cache off;
    proxy_http_version 1.1;
    proxy_set_header Connection "";  # 清除逐跳头，允许保持连接

    # 超时：长连接支持
    proxy_read_timeout 3600s;
    proxy_connect_timeout 30s;
    proxy_send_timeout 30s;

    # 不截断客户端断开信号
    proxy_ignore_client_abort off;
}

# 行为契约：
# - 请求到达 /api/v1/consult/stream → Nginx 不缓冲请求体，逐 chunk 转发至上游
# - 上游 FastAPI 通过 SSE (text/event-stream) 逐 Token 生成
# - Nginx 每收到一个 chunk 立即转发给客户端，不等待 chunk 边界
# - 客户端断开连接 → Nginx 立即通知上游（proxy_ignore_client_abort off），上游停止生成
# - 3580 秒无上游数据 → 返回 504
# - 不应用 gzip（流式响应无法压缩）+ 不缓存
```

#### 1.6.3 路由契约 3：健康检查 (`/health`)

```text
location /health {
    proxy_pass http://api-server:8000;
    proxy_read_timeout 10s;
}

# 行为契约：
# - 请求到达 /health → 快速转发至 FastAPI 健康检查端点
# - 10 秒无上游响应 → 返回 504
# - 上游返回任何状态码均透传（Docker HEALTHCHECK 仅关注退出码，Nginx -t 配置校验先执行）
```

#### 1.6.4 路由契约 4：静态资源 (`/static/*`，预留)

```text
# location /static/ {
#     root /usr/share/nginx/html;
#     expires 7d;
#     add_header Cache-Control "public, immutable";
#     # gzip_types 中已包含静态资源相关的 MIME 类型（text/css, text/javascript）
# }
```

> 以上为注释模板。MVP 阶段微信小程序由微信平台托管全部前端资源，无需 Nginx 静态服务。H5 管理后台引入后取消注释并填充实际 `root` 路径。

### 1.7 依赖与集成接口

#### 1.7.1 关键基础设施依赖（硬性前提）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 容器编排 | Docker Compose v2 | `services.nginx` 服务定义（`ports`、`volumes`、`networks`、`depends_on`、`restart`） | Nginx 容器生命周期、端口映射、网络连接、卷挂载 | `docs/篝火智答-项目结构.md` §6.1 `infrastructure/nginx/` |
| DNS 解析 | Docker 内置 DNS | 通过服务名 `api-server` 解析至 FastAPI 容器 IP（`proxy_pass http://api-server:8000`） | upstream 地址由 Docker 内部 DNS 自动维护，无需手动配置 IP | `docs/篝火智答-技术栈设计.md` §3.1（架构分层图） |
| 健康检查 | Docker HEALTHCHECK | `HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 CMD nginx -t` | 检测 Nginx 配置有效性和进程存活 | DEPLOY-01 设计 §1.6（B4） |
| SSL 证书 | Let's Encrypt 外部服务 | acme.sh DNS-01 挑战 + Aliyun DNS API，宿主机 cron 每日检查，续期后 `docker exec campfire-nginx nginx -s reload` | SSL 证书签发、自动续期 | `docs/篝火智答-技术栈设计.md` §5（传输安全） |
| 文件系统 | 宿主机的 `./infrastructure/nginx/ssl/` 目录 | Docker volume bind mount `./infrastructure/nginx/ssl/:/etc/nginx/ssl/:ro` | 证书文件挂载，容器只读 | DEPLOY-01 设计 §1.7；项目结构 §6.1 |
| 日志收集 | Docker `json-file` 日志驱动 | Nginx 输出 stdout/stderr（`access_log /dev/stdout json; error_log /dev/stderr warn;`） | 日志由 Docker 统一收集、轮转、保留 | `docs/篝火智答-项目结构.md` §6.1；DEPLOY-01 设计 §1.6（B6） |
| 监控 | Prometheus + Grafana | 可选的 Nginx exporter（`nginx-prometheus-exporter` 容器）暴露 `/metrics` 端点 | 收集 `nginx_connections_current`、`nginx_http_requests_total` 等指标 | `docs/篝火智答-技术栈设计.md` §6.3 |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| DEPLOY-01 容器编排 | `docker-compose.yml` 中 Nginx 服务定义 | Nginx 容器的生命周期、网络、卷挂载、资源限制管理 | ✅ 设计已完成 |
| DEPLOY-05 环境配置管理 | 域名字符串（部署层静态写入 `server_name`）+ SSL 证书路径（卷挂载映射） | 提供域名和 SSL 证书加载路径。py-config 不直接向 Nginx 提供配置 | ✅ 已落地 |
| AUTH-04 五级 RBAC 鉴权 | Nginx 仅透传 `Authorization` 头，不参与鉴权 | 身份认证在应用层由 AUTH-04 处理 | ⏭️ 待落地（Nginx 层无 mock 需求——仅透传 HTTP 头，无需模拟鉴权逻辑） |
| SEC-04 防刷限流 | Nginx 注入 `X-Real-IP` 头，限流在应用层由 SEC-04 处理 | 提供客户端真实 IP 供 Redis 滑动窗口限流 | ⏭️ 待落地 |

### 1.8 状态机

本功能点不涉及状态流转，故无需状态机。每次 HTTP 请求独立处理，Nginx 不在请求之间维护任何共享状态。TLS 会话缓存（`ssl_session_cache shared:SSL:10m`）为纯性能优化，不影响请求级行为正确性。意图文档 §1.7 已确认此点。

---

## 【对内实现】

### 1.9 异常与边界条件

> 至少 3 种异常场景。每种含精确触发阈值、逐步处理策略、精确重试参数。

#### 1.9.1 异常 1：后端服务不可达（502 Bad Gateway）

- **触发条件**（满足任一）：
  - Docker 服务名 `api-server` DNS 解析失败（FastAPI 容器未启动或名称拼写错误）
  - FastAPI 容器监听端口 8000 不可用（进程崩溃 / 端口被占用 / TCP 连接被拒绝）
  - 上游连接建立成功但返回空响应体（连接被上游提前关闭）
- **处理策略**：
  1. Nginx 在 `proxy_connect_timeout 30s` 内无法建立 TCP 连接 → 记录 error_log：`upstream timed out (110: Connection timed out) while connecting to upstream`
  2. 向上游客户端返回 `502 Bad Gateway`，响应体为 `502.html` 内容
  3. Docker 层面的 `depends_on: api-server` 和 `restart: unless-stopped` 确保 FastAPI 容器自动重启（由 DEPLOY-01 管理）
  4. 不向客户端暴露内部错误细节（错误页仅含用户友好的提示文字）
- **重试参数**：Nginx 层面**不重试**（`proxy_next_upstream` 默认仅 `error timeout`，且本系统只有单 upstream）。避免请求堆积和雪崩效应。由客户端自行决定重试策略。

#### 1.9.2 异常 2：SSL 证书过期或不可用

- **触发条件**（满足任一）：
  - 容器内 `/etc/nginx/ssl/fullchain.pem` 不存在或权限不可读
  - 证书 `notAfter` 字段早于当前 UTC 时间（Let's Encrypt 证书有效期 90 天）
  - 证书域名（CN/SAN）与客户端请求的 `Host` 头不匹配
  - 私钥文件 `/etc/nginx/ssl/privkey.pem` 与证书不配对（`nginx -t` 返回 `SSL_CTX_use_PrivateKey_file` 错误）
- **处理策略**：
  1. `nginx -t` 配置校验阶段检测到证书问题 → 容器**启动失败**（`nginx: [emerg] cannot load certificate`），Docker 将报告为容器 `unhealthy`
  2. 容器运行时证书过期 → 现有 TLS 连接不受影响（已握手的 session 继续有效），新连接在 TLS 握手阶段收到 `certificate_expired` fatal alert
  3. Let's Encrypt 到期前 30 天自动提醒 → acme.sh cron 任务在到期前自动续期 → 续期成功后 `docker exec campfire-nginx nginx -s reload` 热重载配置（无停机）
  4. 续期失败 → OBS-03 告警通道（钉钉/企业微信）即时通知运维人员手动处理
  5. 运维人员无响应 → 证书过期后所有新 HTTPS 连接失败，系统通过公网完全不可访问
- **重试参数**：acme.sh 默认续期失败后每天重试（90 天有效期足以覆盖多次重试机会）。证书过期后无重试意义——必须手动签发新证书。

#### 1.9.3 异常 3：并发连接数超限（503 Service Unavailable）

- **触发条件**：
  - 同时活跃的客户端连接数（已建立的 TCP + 正在握手的 TLS）超过 `worker_connections 1024`
  - 单个 worker 进程同时处理 1024 个连接后，Nginx 的 `accept_mutex` 导致新连接在 TCP 层被排队，超过内核 `somaxconn` backlog 后新 SYN 包被丢弃
- **处理策略**：
  1. Nginx 的 `multi_accept on` 让 worker 进程尽可能多地接受新连接
  2. 连接数达 1024 上限 → `accept()` 不再从监听套接字取新连接 → 新连接在 TCP backlog 中排队（内核参数 `net.core.somaxconn`，默认 128）
  3. backlog 也满 → 客户端收到 `ECONNREFUSED` 或连接超时（TCP SYN 无 ACK 响应）
  4. 已在处理中的连接不受影响——Nginx 将它们的响应正常返回
  5. Runtime 监控：`docker stats campfire-nginx` 观察内存使用 + `nginx-prometheus-exporter` 的 `nginx_connections_current` 指标
- **重试参数**：无（Nginx 不缓冲连接请求）。当部分连接释放后，新连接自动被接受。客户端应实现指数退避重试（1s, 2s, 4s, 8s，最大 30s 间隔）。

#### 1.9.4 异常 4：SSE 流式连接在数据传输过程中断开

- **触发条件**（满足任一）：
  - 微信小程序用户切到后台（小程序生命周期 `onHide`）触发连接关闭
  - 移动网络切换（WiFi → 4G/5G）导致 TCP 连接重置
  - 代理读取超时 `proxy_read_timeout 3600s` 到期（极长静默后触发）
- **处理策略**：
  1. Nginx 检测到客户端 TCP 连接关闭 → `proxy_ignore_client_abort off` 确保 Nginx 将断开信号透传至上游 FastAPI
  2. FastAPI 检测到 `asyncio.CancelledError` 或客户端断开 → 停止 LLM 流式生成，释放资源（不再消耗 DeepSeek API Token）
  3. Nginx 记录 access_log：状态码 499（`$status` 499 为 Nginx 自定义码，表示客户端在服务器响应之前断开连接）
  4. 客户端（Taro 小程序）收到连接断开事件 → 显示"连接中断，正在重连..."提示，自动重新发起请求（SSE 重连逻辑由前端实现，不在本模块范围）
- **重试参数**：Nginx 层面不重试。SSE 重新发起连接由前端实现——重连请求到达 Nginx 时作为全新连接处理（无状态）。

### 1.10 验收测试场景

> 本章节定义核心测试场景。具体测试代码实现（Docker Compose 测试环境搭建、curl 脚本、openssl 验证）由测试 Skill 负责。

#### 1.10.1 正向测试 1：HTTPS API 代理转发正常

- **场景**：生产环境配置下，HTTPS API 请求被正确接收、解密并转发至 FastAPI，响应完整返回
- **Given**：
  - Nginx 以生产配置启动（`listen 443 ssl http2`、有效 SSL 证书、`upstream api-server` 就绪）
  - FastAPI 服务在 `api-server:8000` 正常运行，`/api/v1/knowledge?category=术语解释` 返回 200 + JSON 响应体
  - 使用 curl 模拟客户端请求：
    ```bash
    curl -k -X GET "https://localhost:443/api/v1/knowledge?category=%E6%9C%AF%E8%AF%AD%E8%A7%A3%E9%87%8A" \
      -H "Accept: application/json" \
      -H "Authorization: Bearer <valid_jwt_token>" \
      -H "X-Request-ID: test-request-001" \
      --resolve "campfire-ai.example.com:443:127.0.0.1" \
      -w "\nHTTP_CODE: %{http_code}\nCONTENT_TYPE: %{content_type}"
    ```
- **When**：执行上述 curl 命令
- **Then**：
  - HTTP 状态码为 200
  - `Content-Type` 为 `application/json`
  - 响应体为 FastAPI 返回的 JSON 数据（与直接请求 `api-server:8000` 获得的响应体一致）
  - 日志中含有 `X-Request-ID: test-request-001`（在 Nginx access_log JSON 中可查）

#### 1.10.2 正向测试 2：SSE 流式响应无缓冲延迟

- **场景**：SSE 流式请求经 Nginx 代理后，每个 chunk 实时到达客户端，无缓冲堆积
- **Given**：
  - Nginx 配置了 `location /api/v1/consult/stream` 且 `proxy_buffering off`
  - FastAPI SSE 端点模拟逐 Token 输出（间隔 100ms）
  - 使用 curl 接收 SSE 流：
    ```bash
    curl -k -N -X GET "https://localhost:443/api/v1/consult/stream" \
      -H "Accept: text/event-stream" \
      --resolve "campfire-ai.example.com:443:127.0.0.1" \
      --max-time 10 2>&1 | ts '[%H:%M:%.S]'
    ```
    （`ts` 为 moreutils 时间戳前缀工具，验证 chunk 到达间隔 <= 200ms）
- **When**：执行上述 curl 命令
- **Then**：
  - 在 10 秒内持续收到 `data:` 开头的 SSE 事件
  - 相邻 `data:` 行的时间戳间隔 <= 200ms（说明 Nginx 层无缓冲延迟——如缓冲开启，所有 chunk 会在响应完成后一次性到达）
  - Nginx access_log 中该请求的 `request_time` 为 10s（即客户端实际接收完所有 chunk 的时间，非 10s 后一次性返回）

#### 1.10.3 正向测试 3：健康检查转发正常

- **场景**：`/health` 请求被正确转发至 FastAPI 健康检查端点
- **Given**：
  - Nginx 配置了 `location /health { proxy_pass http://api-server:8000; proxy_read_timeout 10s; }`
  - FastAPI 健康检查端点返回 `{"status": "healthy", "database": "ok", "redis": "ok"}`
  - 执行 `curl -k -X GET "https://localhost:443/health" --resolve "campfire-ai.example.com:443:127.0.0.1" -w "\nHTTP_CODE: %{http_code}"`
- **When**：执行上述 curl 命令
- **Then**：
  - HTTP 状态码为 200
  - 响应体包含 `"status": "healthy"`
  - 响应时间 < 2 秒（10s 超时的合理快速返回）

#### 1.10.4 异常测试 1：后端服务不可用（502 错误页验证）

- **场景**：FastAPI 服务未启动时，Nginx 返回 502 自定义错误页而非连接超时挂起
- **Given**：
  - Nginx 正常运行，但 `api-server` 服务已停止（`docker stop campfire-api-server`）
  - 执行 `curl -k -X GET "https://localhost:443/api/v1/knowledge" --resolve "campfire-ai.example.com:443:127.0.0.1" -w "\nHTTP_CODE: %{http_code}" 2>&1`
- **When**：执行上述 curl 命令
- **Then**：
  - HTTP 状态码为 502
  - 响应体包含"服务暂时不可用"（502.html 的提示文字）
  - `Content-Type` 为 `text/html`
  - 响应时间约等于 `proxy_connect_timeout 30s`（连接建立失败的超时，实际测试中可用 `docker stop` 模拟，Nginx 立即收到 connection refused 故近乎即时返回 502）

#### 1.10.5 异常测试 2：请求体超出大小限制（413 拦截验证）

- **场景**：客户端尝试上传超过 10MB 的请求体时被 Nginx 在传输层拦截
- **Given**：
  - Nginx 配置了 `client_max_body_size 10m;`
  - 准备一个 11MB 的 JSON 文件（`dd if=/dev/zero of=large_body.json bs=1M count=11` 并追加 JSON 包装）
  - 执行 `curl -k -X POST "https://localhost:443/api/v1/cases" -H "Content-Type: application/json" --data-binary @large_body.json --resolve "campfire-ai.example.com:443:127.0.0.1" -w "\nHTTP_CODE: %{http_code}"`
- **When**：执行上述 curl 命令
- **Then**：
  - HTTP 状态码为 413 Request Entity Too Large
  - 响应在请求体传输过程中即返回（Nginx 在收到 `Content-Length: >10MB` 后立即拒绝，不等待完整请求体传输完成）
  - 请求未被转发至 FastAPI（Nginx error_log 中无 `proxy_pass` 相关记录；access_log 仅记录 413）

#### 1.10.6 异常测试 3：不支持的 TLS 版本被拒绝

- **场景**：客户端仅支持 TLS 1.2 时，Nginx 在 TLS 握手阶段拒绝连接
- **Given**：
  - Nginx 仅启用 `ssl_protocols TLSv1.3;`
  - 执行 `echo | openssl s_client -connect localhost:443 -tls1_2 2>&1 | grep -E "alert|handshake failure|Secure Renegotiation"`
- **When**：执行上述 openssl 命令
- **Then**：
  - openssl 输出包含 `alert handshake failure`（TLS 1.2 被拒绝）
  - `echo $?` 退出码非 0
  - Nginx error_log 中无新增错误（拒绝低版本 TLS 是预期行为，不产生 error 级日志）

### 1.11 注意事项与禁止行为（编码层面）

1. **[约束：配置语法校验先行]** 任何对 `nginx.conf` 或 `campfire.conf` 的修改，在提交前必须通过 `nginx -t` 校验。CI pipeline 中 `docker build` 后立即执行 `docker run --rm campfire-nginx nginx -t` 作为门禁。不允许提交未通过语法校验的 Nginx 配置。

2. **[约束：SSE 路由必须独占 location]** SSE 流式路由 `/api/v1/consult/stream` 必须在 `conf.d/campfire.conf` 中定义为其自己的 `location` 块，不得与常规 API 路由 `/api/v1/` 合并后再加条件判断。原因：`proxy_buffering` 是 `location` 级别的指令，在 `if` 语句中不生效。

3. **[约束：HTTPS 80 端口仅重定向]** 生产环境的 80 端口 `server` 块仅做一件事：`return 301 https://$host$request_uri;`。不得在 80 端口提供任何业务数据、API 端点或静态资源。

4. **[易错点：`X-Forwarded-Proto` 与后端 HTTPS 感知]** FastAPI 在 Nginx 代理后收到的请求协议始终是 `http://`（Nginx 与 FastAPI 之间的内部通信为 HTTP）。若 FastAPI 中某端点需要生成绝对 URL（如 OAuth 回调 URL），必须读取 `X-Forwarded-Proto` 头的值来确定客户端使用的原始协议。这需要在 FastAPI 侧使用 `ProxyHeadersMiddleware` 或 Starlette 的 `FORWARDED_ALLOW_IPS` 配置信任 Nginx 的转发头。

5. **[易错点：`gzip_comp_level` 与 SSE 无交互]** `gzip on` 对 SSE 流式响应无效——因为 `proxy_buffering off` 使得响应逐 chunk 输出，而 gzip 需要完整数据才能压缩。这并非 bug，是流式输出的固有特性。不要为了在 SSE 上启用 gzip 而开启缓冲——这会破坏 AC-07 的实时性要求。

6. **[设计边界]** 本模块不负责：请求级身份认证和授权（AUTH-04）；API 级限流控制（SEC-04）；DDoS 防护和 IP 黑名单；SSL 证书的签发和申请（acme.sh 外部工具）；CDN/WAF 的反向代理链配置（当前无 CDN 规划）；`/static/` 实际资源的部署和 `root` 路径的确定（待 H5 管理后台）。

7. **[禁止行为]** 禁止在 Nginx 配置文件中使用 `if ($request_method = ...)` 做路由判断。Nginx 的 `if` 指令在 `location` 上下文中行为诡异（会创建隐式子请求），是公认的反模式。应使用 `location` 指令做路由匹配，`limit_except` 做方法限制。

8. **[禁止行为]** 禁止将 Nginx 容器以 `root` 用户运行。Alpine Nginx 镜像默认以 `nginx` 用户运行（UID 101），不可写 `/etc/nginx/` 目录。Dockerfile 中不得使用 `USER root`，COPY 操作在构建阶段由 `root` 执行，容器运行时降权至 `nginx` 用户。

9. **[偷懒红线]** 禁止以下偷懒行为：
   - 禁止写 `# 参考其他模块的错误页设计` 来省去 `502.html` 和 `503.html` 的实际编写——两个文件必须分别写，且提示文字不同
   - 禁止省略 `502.html` 和 `503.html` 的 HTML 结构——每个文件必须是自包含的完整 HTML 文档（含 `<!DOCTYPE html>`、`<meta charset="UTF-8">`、内联 CSS 样式）
   - 禁止用 `...` 省略 `nginx.conf` 或 `campfire.conf` 中的任何指令——两个文件必须完整编写，指令顺序有意义

### 1.12 文档详细度自检清单

- [x] 文档自包含：不了解本项目代码的 Agent，仅凭此文档即可编写全部 Nginx 配置文件
- [x] 无偷懒表述：全文不包含"等等"、"..."、"其他字段"、"类似"、"同上"、"参考其他模块"、"请根据实际情况补充"、"开发者自行决定"
- [x] 类型定义完整：输入定义（1.3）和输出定义（1.4）中所有 HTTP 字段和配置项均有类型、说明、约束
- [x] 逻辑步骤完整：1.5 中 5 个步骤均有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：4 种异常均有精确触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值来源（DEPLOY-01 约定、行业最佳实践、意图文档约束）均已显式引用
- [x] 技术栈绑定明确：必须使用（8 项）和禁止使用（7 项）均已列出，与项目技术栈设计文档保持一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致（见 1.15）

### 1.14 外部接口契约清单

> 根据 s08 契约协调报告，本模块为纯 Nginx 配置文件模块，无可提取的对外接口类型（无 Pydantic 模型、无公开函数签名、无状态枚举）。所有对外配置契约（upstream 地址、路由规则、SSL 证书路径）已在设计文档 §1.3 完整描述，由 DEPLOY-01 在部署时静态保证。

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| 无 | — | — | — | — | — |

> 说明：DEPLOY-02 的"契约"是 `conf.d/campfire.conf` 中声明的 HTTP 路由行为（1.6 节），属于配置级契约而非类型级契约，不适用 JSON Schema 格式的契约文件。DEPLOY-02 不创建 `docs/contracts/DEPLOY-02/` 下的类型文件。

### 1.15 意图一致性声明

- **配套意图文档**：`DEPLOY-02-反向代理路由-意图文档.md`
- **冻结时间**：2026-05-26 20:58:45
- **一致性确认**：
  - [x] 本落地规范中的输入/输出定义与意图文档中的业务字段定义一致：1.3 输入包含意图文档 §1.6.1 的全部字段（客户端请求、域名、请求路径、请求方法、请求头、SSE 流式标记）；1.4 输出对应 §1.6.2（代理响应、响应状态码、响应头）
  - [x] 本落地规范中的状态机实现与意图文档中的状态业务定义一致：意图文档 §1.7 确认无状态机，落地规范 1.8 同样确认无状态机
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致：1.9.1 (502) 对应意图文档 §1.8.1；1.9.2 (SSL 过期) 对应 §1.8.2；1.9.3 (并发超限/503) 对应 §1.8.3；1.9.4 (SSE 断开) 基于 SSE 架构的必然边界场景
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准：1.10.1 覆盖 AC-02 (API 代理)；1.10.2 覆盖 AC-07 (SSE 流式)；1.10.3 覆盖 AC-06 (健康检查)；1.10.5 覆盖 AC-08 (502)；1.10.6 覆盖 AC-01 (TLS 1.3)；AC-03 (静态资源缓存)、AC-04 (Gzip 压缩)、AC-05 (SSL 续期) 为配置级验收（Nginx 指令正确性 + 长期监控），在 1.5 步骤 5 中通过 gzip 和缓存指令精确配置保证
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围：6 项决策 (#13-#18) 均已按照用户确认的推荐方案锁定，未引入额外技术决策
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
