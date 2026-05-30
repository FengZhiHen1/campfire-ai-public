"""Worker — Campfire-AI 独立后台任务消费进程。

复用 py-rag 索引管线契约与实现，作为独立容器部署的进程壳。
提供 Redis 队列消费 → 委托 IndexPipeline 处理 → 状态更新的完整异步管线。

核心类：
  - （无公开类，本包为进程入口，索引逻辑委托 py_rag.indexing.IndexPipeline）

外部接口：
  - main() — CLI 入口，启动 Worker 主循环

Usage:
    python -m worker.main
"""

from worker.main import main

__all__ = [
    # CLI 入口
    "main",
]
