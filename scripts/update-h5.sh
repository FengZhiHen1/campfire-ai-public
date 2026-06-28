#!/usr/bin/env bash
# =============================================================================
# Campfire-AI H5 前端热更新脚本
#
# 用于已部署环境下，仅更新前端而不重启后端服务。
#
# 用法：
#   1. 在本地/CI 执行：bash scripts/build-h5.sh
#   2. 将 apps/mini-program/dist/h5 同步到服务器项目目录
#   3. 在服务器执行：bash scripts/update-h5.sh
# =============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.prod.yml"
H5_DIST_DIR="${PROJECT_ROOT}/apps/mini-program/dist"

if [[ ! -f "${H5_DIST_DIR}/index.html" ]]; then
    echo "[ERROR] 未找到 H5 构建产物：${H5_DIST_DIR}"
    echo "[INFO] 请先执行：bash scripts/build-h5.sh"
    exit 1
fi

echo "[INFO] 重启 Nginx 以加载最新 H5 静态资源..."
cd "$PROJECT_ROOT"
docker compose -f "$COMPOSE_FILE" restart nginx

echo "[OK] H5 已更新，访问 https://你的域名/ 查看效果"
