# Campfire-AI 部署脚本说明

本目录包含用于短期公网演示的一键部署脚本。

## 文件说明

| 脚本 | 用途 | 运行位置 |
|------|------|----------|
| `deploy.sh` | 服务器初始化、Docker 安装、拉取/构建镜像、启动全量服务、执行迁移 | 服务器 |
| `build-h5.sh` | 本地或 CI 中编译 H5 前端 | 本地/CI |
| `update-h5.sh` | 服务器上仅更新前端静态资源（不重启后端） | 服务器 |
| `seed_cases.sh` | 在 api-server 容器内导入种子案例并生成向量索引 | 服务器 |
| `seed_cases.py` | 种子案例导入核心脚本 | 容器内/本地 |

## 快速部署流程

### 1. 准备服务器

- 购买香港/新加坡/日本节点云服务器（推荐阿里云 ECS 2C4G 或腾讯云 Lighthouse）
- 安全组开放：22（SSH）、80（HTTP）、443（HTTPS）
- 操作系统：Ubuntu 22.04 LTS

### 2. 上传项目

将项目上传到服务器，例如：

```bash
scp -r . root@你的服务器IP:/opt/campfire-ai
```

### 3. 在服务器上执行部署

```bash
ssh root@你的服务器IP
cd /opt/campfire-ai
bash scripts/deploy.sh
```

脚本会：
1. 安装 Docker 和 Docker Compose
2. 生成 `.env` 文件（首次运行）
3. 生成自签名 SSL 证书（如需真实证书，替换 `infrastructure/nginx/ssl/` 下文件）
4. 构建并启动所有容器
5. 执行数据库迁移
6. 检查 API 健康状态

### 4. 配置域名（推荐 Cloudflare）

1. 域名 DNS A 记录指向服务器 IP
2. Cloudflare 开启代理（橙色云）
3. SSL/TLS 模式设为 **Full** 或 **Full (strict)**
4. 等待 DNS 生效后访问 `https://你的域名/`

### 5. 替换 API Key

部署脚本生成的 `.env` 中 `DEEPSEEK_API_KEY` 和 `DASHSCOPE_API_KEY` 为占位符，必须替换为真实密钥：

```bash
nano /opt/campfire-ai/.env
# 修改后重启
docker compose -f docker-compose.prod.yml restart api-server worker
```

## 导入种子案例

演示前必须导入种子案例，否则 RAG 检索为空：

```bash
# 在服务器上执行（会直接调用 DashScope 生成向量索引）
ssh root@你的服务器IP "cd /opt/campfire-ai && bash scripts/seed_cases.sh"

# 或者在 deploy.sh 中自动导入
CAMPFIRE_SEED_DATA=true bash scripts/deploy.sh
```

如果希望由 Worker 异步处理索引：

```bash
bash scripts/seed_cases.sh --enqueue
```

导入完成后，可以通过 API 测试检索：

```bash
curl -X POST https://你的域名/api/v1/consult/search \
  -H "Content-Type: application/json" \
  -d '{"query_text": "孩子在商场捂耳朵尖叫怎么办", "top_k": 5}'
```

## 更新前端

修改前端代码后：

```bash
# 本地构建
bash scripts/build-h5.sh

# 上传 dist 目录到服务器
rsync -avz --delete apps/mini-program/dist/ root@你的服务器IP:/opt/campfire-ai/apps/mini-program/dist/

# 在服务器上刷新 Nginx
ssh root@你的服务器IP "cd /opt/campfire-ai && bash scripts/update-h5.sh"
```

## 常用命令

```bash
# 查看服务状态
docker compose -f docker-compose.prod.yml ps

# 查看 API 日志
docker compose -f docker-compose.prod.yml logs -f api-server

# 查看 Worker 日志
docker compose -f docker-compose.prod.yml logs -f worker

# 重启服务
docker compose -f docker-compose.prod.yml restart

# 停止服务
docker compose -f docker-compose.prod.yml down

# 进入数据库
docker compose -f docker-compose.prod.yml exec postgres psql -U campfire -d campfire
```

## 注意事项

- 本脚本生成的自签名证书仅用于临时演示，浏览器会提示不安全。
- 如需真实 HTTPS，建议使用 Cloudflare 代理，或上传 Let's Encrypt 证书到 `infrastructure/nginx/ssl/`。
- 中国大陆服务器部署 80/443 端口需要 ICP 备案，建议使用香港/新加坡/日本节点。
- 演示前请确保导入种子案例，否则 RAG 检索为空。
