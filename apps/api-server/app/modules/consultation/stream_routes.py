"""CSLT-04 流式应答推送 — FastAPI 路由注册。

GET /api/v1/consult/stream/{session_id} — SSE 流式推送端点。
接受 CSLT-08 编排层注入的上游 Generator，将 CSLT-03 产出的
GenerationChunk AsyncGenerator 封装为 W3C SSE 标准事件流推送至前端。

端点定位：
  本端点是应流推送流程中的数据输出节点，消费上游 CSLT-03 的流式输出，
  产出 SSE chunk/heartbeat/done/error 事件供前端 CSLT-08 消费。

前置条件（由上游 CSLT-08 编排层确保）：
  1. 已通过 SseStreamingService.register_generator() 注册 session_id 对应的 Generator
  2. 会话处于 CREATED（新连接）或 STREAMING（重连）状态
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.core.streaming import SseStreamingService
from py_schemas.streaming import StreamErrorCode

router = APIRouter(prefix="/api/v1/consult", tags=["consult"])

# session_id 格式：stream-{uuid4}
_SESSION_ID_PATTERN = re.compile(
    r"^stream-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
)


def _get_streaming_service() -> SseStreamingService:
    """依赖注入：提供 SseStreamingService 单例。

    实际应用中应由更上层的依赖容器管理生命周期，此处简单实例化。

    Returns:
        SseStreamingService: SSE 流式推送服务实例。
    """
    return SseStreamingService()


def _validate_session_id(session_id: str) -> str:
    """验证 session_id 格式是否为 stream-{uuid4}。

    Args:
        session_id: 流标识符。

    Returns:
        str: 通过校验的 session_id。

    Raises:
        HTTPException(400): 格式非法时抛出 400 错误。
    """
    if not _SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": StreamErrorCode.INTERNAL_ERROR.value,
                "detail": "无效的会话标识符格式",
            },
        )
    return session_id


@router.get(
    "/stream/{session_id}",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "SSE 事件流（text/event-stream）。包含 chunk/heartbeat/done/error 四种事件类型",
        },
        400: {
            "description": "session_id 格式非法，或未找到对应的上游 Generator",
        },
        404: {
            "description": "重连时流会话不存在或已过期",
        },
        429: {
            "description": "并发连接数超限，当前咨询人数较多",
        },
    },
    summary="SSE 流式应答推送",
    description=(
        "将上游 CSLT-03 应急方案生成服务的流式输出封装为 W3C SSE 标准事件流，"
        "通过 GET 请求建立长连接后持续推送。\n\n"
        "**事件类型**：\n"
        "- ``event: chunk`` → data: {\"text\": \"...\", \"sequence\": n} — 文本增量\n"
        "- ``event: heartbeat`` → data: {} — 连接保活（15s 间隔）\n"
        "- ``event: done`` → data: {\"finish_reason\": \"...\"} — 推送终止\n"
        "- ``event: error`` → data: {\"error_code\": \"...\", \"detail\": \"...\"} — 异常通知\n\n"
        "**断点续传**：重连时在请求头携带 ``Last-Event-Id: n``，服务端从 sequence=n+1 开始续传。\n\n"
        "**前置条件**：上游 CSLT-08 编排层需先通过 register_generator() 注册 Generator。"
    ),
)
async def stream_endpoint(
    request: Request,
    session_id: str = Depends(_validate_session_id),
    streaming_service: SseStreamingService = Depends(_get_streaming_service),
) -> StreamingResponse:
    """SSE 流式应答推送端点。

    依赖注入链：
    1. _validate_session_id — 校验 session_id 格式（stream-{uuid4}）
    2. Request — FastAPI 原生请求对象，从中提取 Last-Event-Id 头
    3. SseStreamingService — SSE 流式推送服务

    Args:
        session_id: 会话标识符。
        request: HTTP 请求对象。
        streaming_service: SSE 流式推送服务实例。

    Returns:
        StreamingResponse: SSE 事件流响应（media_type="text/event-stream"）。
    """
    last_event_id: str | None = request.headers.get("Last-Event-Id")

    return await streaming_service.stream_response(
        session_id=session_id,
        last_event_id=last_event_id,
    )


__all__ = ["router"]
