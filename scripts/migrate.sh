#!/usr/bin/env bash
# ============================================================================
# DEPLOY-04 数据库迁移 — 部署时执行脚本
#
# 用法：
#   ./scripts/migrate.sh              # 执行 upgrade head
#   ./scripts/migrate.sh upgrade      # 同上
#   ./scripts/migrate.sh downgrade -1 # 回滚一个版本
#   ./scripts/migrate.sh current      # 查看当前版本
#   ./scripts/migrate.sh check        # 检测未记录的 Schema 变更
#
# 前置条件：
#   - PostgreSQL 服务已就绪（由 docker-compose depends_on + healthcheck 保证）
#   - DATABASE_URL 环境变量已设置
#   - uv 已安装且依赖已同步（uv sync --package py-db）
#
# 行为：
#   - 默认执行 alembic upgrade head
#   - 退出码 0 = 成功（无待执行迁移或全部执行完成）
#   - 退出码非 0 = 失败（应用容器不应启动）
#   - 由 DEPLOY-01（容器编排）在 PostgreSQL 就绪后、应用容器启动前调用
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# 颜色输出（可选）
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[migrate]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[migrate]${NC} $*" >&2
}

log_error() {
    echo -e "${RED}[migrate]${NC} $*" >&2
}

# ---------------------------------------------------------------------------
# 前置检查
# ---------------------------------------------------------------------------
check_prerequisites() {
    # 检查 DATABASE_URL
    if [ -z "${DATABASE_URL:-}" ]; then
        log_error "DATABASE_URL is not set. Cannot run migrations."
        exit 3
    fi

    # 检查 alembic 可用性
    if ! uv run alembic --version > /dev/null 2>&1; then
        log_warn "alembic not found via 'uv run', attempting direct check..."
        if ! command -v alembic > /dev/null 2>&1; then
            log_error "alembic is not installed. Run: uv sync --package py-db"
            exit 3
        fi
    fi
}

# ---------------------------------------------------------------------------
# 切换到正确的目录（alembic.ini 所在目录）
# ---------------------------------------------------------------------------
ALEMBIC_DIR="$(cd "$(dirname "$0")/../packages/py-db" && pwd)"

# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------
main() {
    local action="${1:-upgrade}"
    local target="${2:-head}"

    check_prerequisites

    log_info "Starting migration: action=${action}, target=${target}"
    log_info "Database URL (masked): ${DATABASE_URL%%@*}@***"

    cd "${ALEMBIC_DIR}"

    case "${action}" in
        upgrade)
            log_info "Running: alembic upgrade ${target}"
            if uv run alembic upgrade "${target}"; then
                log_info "Migration completed successfully."
                exit 0
            else
                log_error "Migration upgrade failed. Check logs above."
                exit 1
            fi
            ;;
        downgrade)
            log_info "Running: alembic downgrade ${target}"
            if uv run alembic downgrade "${target}"; then
                log_info "Rollback completed successfully."
                exit 0
            else
                log_error "Migration downgrade failed. Check logs above."
                exit 2
            fi
            ;;
        current)
            log_info "Checking current database version..."
            uv run alembic current
            exit 0
            ;;
        heads)
            log_info "Showing available heads..."
            uv run alembic heads
            exit 0
            ;;
        history)
            log_info "Showing migration history..."
            uv run alembic history
            exit 0
            ;;
        check)
            log_info "Running: alembic check"
            if uv run alembic check; then
                log_info "No unrecorded schema changes detected."
                exit 0
            else
                log_error "Unrecorded schema changes detected!"
                exit 3
            fi
            ;;
        *)
            log_error "Unknown action: ${action}"
            echo "Usage: $0 {upgrade|downgrade|current|heads|history|check} [target]"
            exit 1
            ;;
    esac
}

main "$@"
