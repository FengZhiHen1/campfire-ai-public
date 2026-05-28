#!/usr/bin/env bash
# MVP 种子数据导入 — Unix 一键入口
# 用法: ./scripts/seed.sh [--append] [--count N]

set -e

cd "$(dirname "$0")/.."

echo "=== Campfire-AI MVP 种子数据导入 ==="
uv run scripts/seed.py "$@"
