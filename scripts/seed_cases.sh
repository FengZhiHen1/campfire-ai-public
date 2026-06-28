#!/usr/bin/env bash
# =============================================================================
# Campfire-AI 种子案例导入脚本（Docker 包装器）
#
# 在运行中的 api-server 容器内执行 seed_cases.py，自动处理依赖。
#
# 用法：
#   bash scripts/seed_cases.sh              # 直接生成向量索引
#   bash scripts/seed_cases.sh --enqueue    # 投递到 Redis 队列由 Worker 处理
#   bash scripts/seed_cases.sh --clear      # 先清空已有种子数据
# =============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.prod.yml"

# 检查容器是否运行
if ! docker compose -f "$COMPOSE_FILE" ps api-server | grep -q "Up"; then
    echo "[ERROR] api-server 容器未运行，请先启动服务："
    echo "  docker compose -f ${COMPOSE_FILE} up -d"
    exit 1
fi

echo "[INFO] 在 api-server 容器内执行种子案例导入..."
docker compose -f "$COMPOSE_FILE" exec -T api-server python /app/scripts/seed_cases.py "$@"

echo "[OK] 种子案例导入完成"
