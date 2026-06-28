#!/usr/bin/env bash
# =============================================================================
# Campfire-AI 生产环境一键部署脚本
#
# 适用场景：
#   - 短期（如 10 天）公网演示
#   - 无 ICP 备案需求（推荐香港/新加坡/日本服务器）
#   - 域名通过 Cloudflare 代理获取免费 HTTPS
#
# 使用方法：
#   1. 将项目上传到服务器（如 /opt/campfire-ai）
#   2. cd /opt/campfire-ai
#   3. bash scripts/deploy.sh
#
# 前置要求：
#   - Ubuntu 22.04+（其他 Debian 系可兼容）
#   - 服务器安全组已开放 22、80、443
#   - 如需 HTTPS，请准备证书文件放到 infrastructure/nginx/ssl/ 下
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
PROJECT_NAME="campfire-ai"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${APP_DIR}/.env"
NGINX_SSL_DIR="${APP_DIR}/infrastructure/nginx/ssl"
H5_DIST_DIR="${APP_DIR}/apps/mini-program/dist"
COMPOSE_FILE="${APP_DIR}/docker-compose.prod.yml"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# 检查 root 权限
# ---------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    log_warn "当前未以 root 运行，部分操作可能需要 sudo 密码"
fi

# ---------------------------------------------------------------------------
# 安装 Docker
# ---------------------------------------------------------------------------
install_docker() {
    if command_exists docker && command_exists docker-compose; then
        log_success "Docker 和 docker-compose 已安装"
        return 0
    fi

    log_info "正在安装 Docker..."

    if command_exists apt-get; then
        apt-get update
        apt-get install -y ca-certificates curl gnupg lsb-release

        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
        chmod a+r /etc/apt/keyrings/docker.asc

        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
            https://download.docker.com/linux/ubuntu \
            $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

        apt-get update
        apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    elif command_exists yum; then
        yum install -y yum-utils
        yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
        yum install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        systemctl start docker
        systemctl enable docker
    else
        log_error "不支持的包管理器，请手动安装 Docker"
        exit 1
    fi

    # 启动 Docker
    systemctl start docker || true
    systemctl enable docker || true

    log_success "Docker 安装完成"
}

# ---------------------------------------------------------------------------
# 生成随机密码
# ---------------------------------------------------------------------------
generate_secret() {
    openssl rand -base64 32 | tr -d "=+/" | cut -c1-32
}

# ---------------------------------------------------------------------------
# 生成 .env 文件
# ---------------------------------------------------------------------------
setup_env() {
    if [[ -f "$ENV_FILE" ]]; then
        log_warn ".env 文件已存在，跳过生成"
        log_warn "如需重新生成，请先备份并删除 ${ENV_FILE}"
        return 0
    fi

    log_info "生成 .env 配置文件..."

    local postgres_password jwt_secret minio_access_key minio_secret_key
    postgres_password=$(generate_secret)
    jwt_secret=$(openssl rand -base64 48)
    minio_access_key=$(generate_secret | cut -c1-20)
    minio_secret_key=$(generate_secret)

    cat > "$ENV_FILE" <<EOF
# ============================================================
# 篝火智答 (Campfire-AI) — 生产环境变量
# 由 scripts/deploy.sh 自动生成于 $(date -Iseconds)
# ============================================================

# --- 数据库 (PostgreSQL 17.x + pgvector) ---
# 注意：容器内使用服务名连接，宿主机调试时改为 localhost
DATABASE_URL=postgresql+asyncpg://campfire:${postgres_password}@postgres:5432/campfire
POSTGRES_USER=campfire
POSTGRES_PASSWORD=${postgres_password}
POSTGRES_DB=campfire

# --- Redis 7.x ---
REDIS_URL=redis://redis:6379/0

# --- DeepSeek API (LLM) ---
# TODO: 替换为真实 API Key
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# --- 阿里 DashScope (嵌入模型 text-embedding-v4) ---
# TODO: 替换为真实 API Key
DASHSCOPE_API_KEY=sk-your-dashscope-api-key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# --- MinIO 对象存储 ---
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=${minio_access_key}
MINIO_SECRET_KEY=${minio_secret_key}

# --- JWT 认证 ---
JWT_SECRET_KEY=${jwt_secret}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# --- API 限流 ---
RATE_LIMIT_USER_PER_MINUTE=30
RATE_LIMIT_IP_PER_MINUTE=100

# --- 应用 ---
APP_ENV=production
ENVIRONMENT=production
LOG_LEVEL=INFO
EOF

    log_success ".env 文件已生成：${ENV_FILE}"
    log_warn "请编辑 ${ENV_FILE}，填入真实的 DEEPSEEK_API_KEY 和 DASHSCOPE_API_KEY"
}

# ---------------------------------------------------------------------------
# 检查证书
# ---------------------------------------------------------------------------
setup_ssl() {
    if [[ -f "${NGINX_SSL_DIR}/fullchain.pem" && -f "${NGINX_SSL_DIR}/privkey.pem" ]]; then
        log_success "检测到 SSL 证书文件"
        return 0
    fi

    log_warn "未找到 SSL 证书，将生成自签名证书用于临时访问"
    log_warn "建议：使用 Cloudflare 代理 + Origin CA 证书，或上传 Let's Encrypt 证书"

    mkdir -p "$NGINX_SSL_DIR"

    openssl req -x509 -nodes -days 30 -newkey rsa:2048 \
        -keyout "${NGINX_SSL_DIR}/privkey.pem" \
        -out "${NGINX_SSL_DIR}/fullchain.pem" \
        -subj "/CN=campfire-ai-demo" \
        -addext "subjectAltName=DNS:campfire-ai-demo,IP:127.0.0.1"

    log_success "自签名证书已生成（30 天有效期）"
}

# ---------------------------------------------------------------------------
# 检查 H5 构建产物
# ---------------------------------------------------------------------------
check_h5_build() {
    if [[ -d "$H5_DIST_DIR" && -f "${H5_DIST_DIR}/index.html" ]]; then
        log_success "检测到 H5 构建产物：${H5_DIST_DIR}"
        return 0
    fi

    log_warn "未检测到 H5 构建产物"
    log_warn "请在本地或服务器上执行：pnpm --filter mini-program build:h5"
    log_warn "然后重新运行此脚本，或手动上传 apps/mini-program/dist 目录"

    # 创建一个占位 index.html，避免 nginx 启动失败
    mkdir -p "$H5_DIST_DIR"
    cat > "${H5_DIST_DIR}/index.html" <<'EOF'
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Campfire-AI 演示</title>
    <style>
        body { font-family: system-ui, sans-serif; max-width: 600px; margin: 80px auto; padding: 20px; }
        h1 { color: #333; }
        .tip { background: #fff3cd; padding: 12px; border-radius: 6px; }
    </style>
</head>
<body>
    <h1>Campfire-AI</h1>
    <p>篝火智答 — 孤独症家属智能应急咨询平台</p>
    <div class="tip">
        <strong>提示：</strong>H5 前端尚未构建。请执行
        <code>pnpm --filter mini-program build:h5</code>
        后重新部署。
    </div>
    <p>后端 API 文档：<a href="/docs">/docs</a></p>
</body>
</html>
EOF
}

# ---------------------------------------------------------------------------
# 主部署流程
# ---------------------------------------------------------------------------
main() {
    log_info "开始部署 ${PROJECT_NAME}..."
    log_info "项目目录：${APP_DIR}"

    # 1. 安装 Docker
    install_docker

    # 2. 配置环境变量
    setup_env

    # 3. 检查关键配置
    if ! grep -q "DEEPSEEK_API_KEY=sk-your" "$ENV_FILE"; then
        log_success "DEEPSEEK_API_KEY 已配置"
    else
        log_warn "DEEPSEEK_API_KEY 仍为占位符，请在部署前替换"
    fi

    if ! grep -q "DASHSCOPE_API_KEY=sk-your" "$ENV_FILE"; then
        log_success "DASHSCOPE_API_KEY 已配置"
    else
        log_warn "DASHSCOPE_API_KEY 仍为占位符，请在部署前替换"
    fi

    # 4. SSL 证书
    setup_ssl

    # 5. H5 构建产物
    check_h5_build

    # 6. 登录 Docker Hub（可选）
    if [[ -n "${DOCKERHUB_USERNAME:-}" && -n "${DOCKERHUB_PASSWORD:-}" ]]; then
        log_info "使用 DOCKERHUB_USERNAME/PASSWORD 登录..."
        echo "$DOCKERHUB_PASSWORD" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin
    fi

    # 7. 构建并启动服务
    log_info "构建并启动 Docker 服务..."
    cd "$APP_DIR"
    docker compose -f "$COMPOSE_FILE" pull || true
    docker compose -f "$COMPOSE_FILE" build --no-cache
    docker compose -f "$COMPOSE_FILE" up -d

    # 8. 等待 PostgreSQL 就绪
    log_info "等待 PostgreSQL 就绪..."
    for i in {1..30}; do
        if docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U campfire >/dev/null 2>&1; then
            log_success "PostgreSQL 已就绪"
            break
        fi
        sleep 2
        if [[ $i -eq 30 ]]; then
            log_error "PostgreSQL 启动超时，请检查日志：docker compose -f ${COMPOSE_FILE} logs postgres"
            exit 1
        fi
    done

    # 9. 执行数据库迁移
    # 注意：migration 服务已随 docker compose up -d 自动运行并完成
    # 此处显式再执行一次，确保最新迁移已应用（幂等操作）
    log_info "执行数据库迁移..."
    docker compose -f "$COMPOSE_FILE" run --rm migration

    # 10. 健康检查
    log_info "等待 API 服务健康检查..."
    for i in {1..30}; do
        if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
            log_success "API 服务健康检查通过"
            break
        fi
        sleep 2
        if [[ $i -eq 30 ]]; then
            log_error "API 服务启动超时，请检查日志：docker compose -f ${COMPOSE_FILE} logs api-server"
            exit 1
        fi
    done

    # 11. 导入种子案例（可选）
    if [[ "${CAMPFIRE_SEED_DATA:-false}" == "true" ]]; then
        log_info "导入种子案例数据..."
        bash "${APP_DIR}/scripts/seed_cases.sh"
    else
        log_warn "跳过种子数据导入。如需导入，请设置环境变量 CAMPFIRE_SEED_DATA=true 后重新运行"
    fi

    # 12. 输出访问信息
    echo ""
    log_success "部署完成！"
    echo ""
    echo -e "${GREEN}访问地址：${NC}"
    echo -e "  H5 前端（浏览器打开）：https://你的域名/"
    echo -e "  API 文档：            https://你的域名/docs"
    echo -e "  健康检查：            https://你的域名/health"
    echo -e "  后端直连（调试用）：  http://服务器IP:8000/health"
    echo ""
    echo -e "${YELLOW}重要提醒：${NC}"
    echo "  1. 如果使用 Cloudflare，请将域名 A 记录指向服务器 IP，并开启代理（橙色云）"
    echo "  2. Cloudflare SSL/TLS 模式建议设为 'Full' 或 'Full (strict)'"
    echo "  3. 自签名证书会被浏览器警告，仅供临时调试"
    echo "  4. 请尽快替换 .env 中的 DEEPSEEK_API_KEY 和 DASHSCOPE_API_KEY 为真实密钥"
    echo ""
    echo -e "${BLUE}常用命令：${NC}"
    echo "  查看日志：  docker compose -f ${COMPOSE_FILE} logs -f api-server"
    echo "  查看状态：  docker compose -f ${COMPOSE_FILE} ps"
    echo "  重启服务：  docker compose -f ${COMPOSE_FILE} restart"
    echo "  停止服务：  docker compose -f ${COMPOSE_FILE} down"
}

# 捕获错误
trap 'log_error "部署脚本在第 ${LINENO} 行失败"' ERR

main "$@"
