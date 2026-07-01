#!/usr/bin/env bash
# =============================================================================
# Campfire-AI 远程部署脚本（在服务器上执行）
#
# 触发方式：
#   - GitHub Actions 通过 SSH 调用
#   - 手动在服务器上执行：bash scripts/deploy-remote.sh [VERSION_TAG]
#
# 功能：
#   1. 从 origin/master 同步代码
#   2. 使用指定 VERSION_TAG 本地构建 Docker 镜像
#   3. 执行数据库迁移
#   4. 健康检查，失败时自动回滚到上一次镜像
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
PROJECT_NAME="campfire-ai"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${APP_DIR}/.env"
COMPOSE_FILE="${APP_DIR}/docker-compose.prod.yml"
VERSION_TAG="${1:-latest}"
LOCK_FILE="${APP_DIR}/.deploy.lock"
BACKUP_TAG="rollback"
HEALTH_TIMEOUT=60
HEALTH_INTERVAL=2

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
log_info() {
    echo -e "${BLUE}[deploy]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[deploy]${NC} $1"
}

log_error() {
    echo -e "${RED}[deploy]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[deploy]${NC} $1"
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# 锁与并发控制
# ---------------------------------------------------------------------------
acquire_lock() {
    if command_exists flock; then
        exec 200>"${LOCK_FILE}"
        if ! flock -n 200; then
            log_error "已有其他部署进程在运行，请等待完成后再试"
            exit 1
        fi
    else
        if [[ -e "${LOCK_FILE}" ]]; then
            local pid
            pid="$(cat "${LOCK_FILE}" 2>/dev/null || echo "")"
            if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
                log_error "部署进程 ${pid} 正在运行，跳过本次部署"
                exit 1
            fi
        fi
        echo "$$" > "${LOCK_FILE}"
    fi
}

release_lock() {
    rm -f "${LOCK_FILE}"
    if command_exists flock; then
        exec 200>&- || true
    fi
}

# ---------------------------------------------------------------------------
# 错误处理与回滚
# ---------------------------------------------------------------------------
ROLLBACK_NEEDED=false

rollback() {
    # 避免回滚过程中再次失败时重复进入回滚逻辑
    ROLLBACK_NEEDED=false
    # 回滚期间禁用 ERR trap，防止单条命令失败导致无限递归
    set +e

    log_warn "开始回滚到上一次镜像..."

    local api_rollback_exists=false
    local worker_rollback_exists=false

    if docker image inspect "campfire-api-server:${BACKUP_TAG}" >/dev/null 2>&1; then
        api_rollback_exists=true
    fi
    if docker image inspect "campfire-worker:${BACKUP_TAG}" >/dev/null 2>&1; then
        worker_rollback_exists=true
    fi

    if [[ "${api_rollback_exists}" == "false" && "${worker_rollback_exists}" == "false" ]]; then
        log_error "未找到回滚镜像（${BACKUP_TAG} 标签不存在），无法自动回滚"
        log_error "请手动检查服务状态并修复"
        set -e
        return 1
    fi

    if [[ "${api_rollback_exists}" == "true" ]]; then
        docker tag "campfire-api-server:${BACKUP_TAG}" "campfire-api-server:${VERSION_TAG}"
    fi
    if [[ "${worker_rollback_exists}" == "true" ]]; then
        docker tag "campfire-worker:${BACKUP_TAG}" "campfire-worker:${VERSION_TAG}"
    fi

    VERSION_TAG="${VERSION_TAG}" docker compose -f "${COMPOSE_FILE}" up -d
    local up_status=$?

    set -e

    if [[ "${up_status}" -ne 0 ]]; then
        log_error "回滚启动失败，请人工介入"
        return 1
    fi

    log_success "已使用 ${BACKUP_TAG} 镜像重新启动服务"
    docker compose -f "${COMPOSE_FILE}" ps
}

on_error() {
    local line=$1
    log_error "部署脚本在第 ${line} 行失败"
    if [[ "${ROLLBACK_NEEDED}" == "true" ]]; then
        rollback || log_error "回滚失败，请人工介入"
    fi
    release_lock
    exit 1
}

trap 'on_error ${LINENO}' ERR

# ---------------------------------------------------------------------------
# 前置检查
# ---------------------------------------------------------------------------
acquire_lock

if [[ ! -f "${ENV_FILE}" ]]; then
    log_error "环境文件 ${ENV_FILE} 不存在，请先配置 .env"
    release_lock
    exit 1
fi

if ! command_exists docker; then
    log_error "服务器上未安装 Docker"
    release_lock
    exit 1
fi

log_info "开始部署 ${PROJECT_NAME}，VERSION_TAG=${VERSION_TAG}"
log_info "项目目录：${APP_DIR}"

# ---------------------------------------------------------------------------
# 同步代码
# ---------------------------------------------------------------------------
cd "${APP_DIR}"
log_info "同步代码..."
git fetch origin
git reset --hard origin/master
log_success "代码已同步到 origin/master"

# ---------------------------------------------------------------------------
# 备份当前镜像（用于回滚）
# ---------------------------------------------------------------------------
log_info "备份当前运行镜像..."
backup_api=false
backup_worker=false

if docker image inspect "campfire-api-server:${VERSION_TAG}" >/dev/null 2>&1; then
    docker tag "campfire-api-server:${VERSION_TAG}" "campfire-api-server:${BACKUP_TAG}"
    backup_api=true
fi
if docker image inspect "campfire-worker:${VERSION_TAG}" >/dev/null 2>&1; then
    docker tag "campfire-worker:${VERSION_TAG}" "campfire-worker:${BACKUP_TAG}"
    backup_worker=true
fi

if [[ "${backup_api}" == "true" || "${backup_worker}" == "true" ]]; then
    log_success "已备份当前镜像到 ${BACKUP_TAG} 标签"
else
    log_warn "当前不存在 ${VERSION_TAG} 标签的镜像，首次部署将无法回滚"
fi

# ---------------------------------------------------------------------------
# 构建并启动服务
# ---------------------------------------------------------------------------
ROLLBACK_NEEDED=true

log_info "构建 Docker 镜像..."
VERSION_TAG="${VERSION_TAG}" docker compose -f "${COMPOSE_FILE}" build --no-cache api-server worker migration

log_info "启动服务..."
VERSION_TAG="${VERSION_TAG}" docker compose -f "${COMPOSE_FILE}" up -d

log_info "执行数据库迁移..."
VERSION_TAG="${VERSION_TAG}" docker compose -f "${COMPOSE_FILE}" run --rm migration

# ---------------------------------------------------------------------------
# 重置数据库并注入种子数据
# ---------------------------------------------------------------------------
# 警告：每次部署都会清空案例库（L1 叙事、L2 卡片、向量切片）与咨询历史，
# 然后重新注入 scripts/seed.py 中的种子数据。用户账号与默认患者档案会被保留。
log_warn "开始重置数据库并注入种子数据（将清空案例与咨询历史）..."
for i in $(seq 1 30); do
    if docker compose -f "${COMPOSE_FILE}" ps api-server | grep -q "Up"; then
        break
    fi
    sleep 2
    if [[ $i -eq 30 ]]; then
        log_error "api-server 容器未就绪，无法执行数据库重置"
        exit 1
    fi
done
docker compose -f "${COMPOSE_FILE}" exec -T api-server python scripts/seed.py --reset --yes
log_success "数据库重置并注入种子数据完成"

# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------
log_info "等待 API 服务健康检查..."
api_healthy=false
for i in $(seq 1 $((HEALTH_TIMEOUT / HEALTH_INTERVAL))); do
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        api_healthy=true
        break
    fi
    sleep "${HEALTH_INTERVAL}"
done

if [[ "${api_healthy}" != "true" ]]; then
    log_error "API 服务健康检查未通过"
    exit 1
fi
log_success "API 服务健康检查通过"

log_info "等待 Worker 健康检查..."
worker_healthy=false
for i in $(seq 1 $((HEALTH_TIMEOUT / HEALTH_INTERVAL))); do
    if docker compose -f "${COMPOSE_FILE}" exec -T worker pgrep -f 'python -m worker.main' >/dev/null 2>&1; then
        worker_healthy=true
        break
    fi
    sleep "${HEALTH_INTERVAL}"
done

if [[ "${worker_healthy}" != "true" ]]; then
    log_error "Worker 健康检查未通过"
    exit 1
fi
log_success "Worker 健康检查通过"

ROLLBACK_NEEDED=false

# ---------------------------------------------------------------------------
# 清理与收尾
# ---------------------------------------------------------------------------
log_info "清理过期镜像..."
# 保留当前 VERSION_TAG、latest 与 rollback 标签，删除其他悬空镜像
docker image prune -f >/dev/null 2>&1 || true

docker compose -f "${COMPOSE_FILE}" ps

log_success "部署完成！VERSION_TAG=${VERSION_TAG}"

release_lock
