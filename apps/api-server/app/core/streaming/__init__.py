"""CSLT-04 流式应答推送 — 模块入口。

提供 SSE 流式推送核心服务：
- StreamSessionManager 管理连接会话生命周期（单例，内存 dict）
- SseStreamingService 封装完整的 6 步骤 SSE 推送逻辑

模块内部依赖 PySchemas 的 streaming 数据模型定义。
"""

from __future__ import annotations

from app.core.streaming.session_manager import StreamSessionManager
from app.core.streaming.sse_service import SseStreamingService

__all__ = [
    "StreamSessionManager",
    "SseStreamingService",
]
