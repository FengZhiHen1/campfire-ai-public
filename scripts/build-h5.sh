#!/usr/bin/env bash
# =============================================================================
# Campfire-AI H5 前端构建脚本
#
# 用法：
#   bash scripts/build-h5.sh          # 生产构建
#   bash scripts/build-h5.sh --mock   # 使用 Mock 数据构建（无后端也可预览）
# =============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
H5_DIST_DIR="${PROJECT_ROOT}/apps/mini-program/dist"

USE_MOCK=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mock)
            USE_MOCK=true
            shift
            ;;
        --help|-h)
            echo "用法: $0 [--mock]"
            echo "  --mock  使用本地 Mock 数据构建，无需后端服务"
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

echo "[INFO] 安装依赖..."
cd "$PROJECT_ROOT"
pnpm install

echo "[INFO] 构建 H5..."
if [[ "$USE_MOCK" == true ]]; then
    pnpm --filter mini-program build:h5:mock
else
    pnpm --filter mini-program build:h5
fi

if [[ ! -f "${H5_DIST_DIR}/index.html" ]]; then
    echo "[ERROR] H5 构建失败，未找到 ${H5_DIST_DIR}/index.html"
    exit 1
fi

echo "[OK] H5 构建成功：${H5_DIST_DIR}"
echo "[INFO] 文件大小统计："
du -sh "$H5_DIST_DIR" || true
