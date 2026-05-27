"""CSLT-04 流式应答推送 — SseStreamingService SSE 推送服务。

实现 6 步骤 + 心跳并行的核心 SSE 推送逻辑：

1. 并发限流检查 — asyncio.Semaphore 控制全局并发连接数
2. 会话创建或恢复 — 通过 StreamSessionManager 管理内存会话
3. 启动上游 Generator 消费 — 配置 SSE 响应头，Last-Event-Id 断点续传
4. 逐 chunk 消费与 SSE 事件推送循环 — 主循环处理 GenerationChunk
5. 异常终端处理 — 确保 DoneEvent/ErrorEvent 在异常时必达
6. 正常完成终端处理 — 发送 DoneEvent 并释放信号量

心跳调度 — 独立 asyncio.Task，通过 asyncio.Queue 与主推送循环合并。
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator, ClassVar

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse

from py_config.config import AppSettings
from py_logger import logger
from py_schemas.streaming import (
    ChunkEvent,
    DoneEvent,
    ErrorEvent,
    HeartbeatEvent,
    StreamErrorCode,
    StreamSession,
)

from app.services.emergency_plan_generation.models import GenerationChunk

from .session_manager import StreamSessionManager

# ============================================================================
# 常量
# ============================================================================

SEQUENCE_START: int = 1
"""SSE 事件 sequence 号的起始值。每个 chunk 事件的 sequence 从 1 开始递增。"""

_SENTINEL: object = object()
"""Queue 哨兵值，用于通知消费者循环结束。"""


class SseStreamingService:
    """SSE 流式推送服务。

    单例服务，通过 ``__init__`` 注入 ``StreamSessionManager`` 和 ``AppSettings``。
    使用 ``asyncio.Semaphore`` 控制全局并发连接数（每个 Uvicorn worker 进程独立）。

    核心入口为 ``stream_response()``，返回 ``FastAPI StreamingResponse``。
    """

    _semaphore: ClassVar[asyncio.Semaphore] = asyncio.Semaphore(1)
    """模块级信号量，所有实例共享。实际容量由 _init_semaphore 在 __init__ 中设置。"""

    _semaphore_initialized: ClassVar[bool] = False

    def __init__(
        self,
        settings: AppSettings | None = None,
        session_manager: StreamSessionManager | None = None,
    ) -> None:
        self._settings = settings or AppSettings()
        self._session_manager = session_manager or StreamSessionManager()

        # 初始化信号量容量（首次初始化后不再变更）
        if not SseStreamingService._semaphore_initialized:
            max_connections = self._settings.SSE_MAX_CONCURRENT_CONNECTIONS
            SseStreamingService._semaphore = asyncio.Semaphore(max_connections)
            SseStreamingService._semaphore_initialized = True

        # session_id -> generator 的映射，由 register_generator() 注册
        self._generators: dict[str, AsyncGenerator[GenerationChunk, None]] = {}

    # ------------------------------------------------------------------
    # Generator 注册（由 CSLT-08 编排层调用）
    # ------------------------------------------------------------------

    def register_generator(
        self,
        session_id: str,
        generator: AsyncGenerator[GenerationChunk, None],
    ) -> None:
        """注册 session_id 对应的上游 Generator，供 SSE 路由消费。

        由 CSLT-08 编排层在启动生成后调用，在 SSE 连接建立前完成注册。

        Args:
            session_id: 流标识符，格式 stream-{uuid4}。
            generator: 上游 CSLT-03 产出的 ``AsyncGenerator[GenerationChunk, None]``。
        """
        self._generators[session_id] = generator

    # ------------------------------------------------------------------
    # 外部公共接口
    # ------------------------------------------------------------------

    async def stream_response(
        self,
        session_id: str,
        last_event_id: str | None = None,
    ) -> StreamingResponse:
        """将上游 CSLT-03 产出的 GenerationChunk AsyncGenerator 封装为
        W3C SSE 标准的事件流，通过 FastAPI StreamingResponse 实时推送至客户端。

        完整包含 6 步骤执行流程（见模块 docstring），返回的 ``StreamingResponse``
        在客户端连接期间持续推送 chunk/heartbeat/done/error 事件。

        Args:
            session_id: 流标识符，格式 stream-{uuid4}，用于断点续传和日志追踪。
            last_event_id: 可选，重连时前端通过 ``Last-Event-Id`` 请求头发送，
                           值为最后成功接收的 sequence 号（正整数）。

        Returns:
            StreamingResponse: FastAPI 流式响应对象，media_type="text/event-stream"。

        Raises:
            HTTPException(429): 并发连接数超限，信号量耗尽。
            HTTPException(404): 重连时流会话不存在或已过期。
            HTTPException(400): session_id 对应会话无注册的 Generator。
        """
        # ==================================================================
        # 步骤 1: 并发限流检查
        # ==================================================================
        if SseStreamingService._semaphore.locked():
            current_connections = self._session_manager.active_count
            logger.warning(
                "concurrency_limit_reached",
                current_connections=current_connections,
                rejected_session=session_id,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error_code": "CONCURRENCY_LIMIT_EXCEEDED",
                    "detail": "当前咨询人数较多，请稍后重试",
                },
            )

        await SseStreamingService._semaphore.acquire()

        # ==================================================================
        # 步骤 2: 会话创建或恢复
        # ==================================================================
        session = self._session_manager.get_session(session_id)

        if session is None:
            # ==== 新会话 ====
            try:
                session = self._session_manager.create_session(session_id)
            except ValueError:
                SseStreamingService._semaphore.release()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error_code": "INTERNAL_ERROR",
                        "detail": "无效的会话标识符格式",
                    },
                )

        elif session.status == "EXPIRED":
            SseStreamingService._semaphore.release()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error_code": "SESSION_NOT_FOUND",
                    "detail": "当前推送会话不存在或已过期",
                },
            )

        elif session.status in ("COMPLETED", "ABORTED"):
            # 已完成/已中止：返回仅包含 DoneEvent 的即时响应
            SseStreamingService._semaphore.release()
            return await self._build_done_only_response(session)

        # session.status 为 CREATED 或 STREAMING — 继续或续传

        # 获取上游 Generator
        generator = self._generators.pop(session_id, None)
        if generator is None:
            SseStreamingService._semaphore.release()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "GENERATION_FAILED",
                    "detail": "未找到对应的上游生成器",
                },
            )

        # ==================================================================
        # 构建响应头
        # ==================================================================
        response_headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Stream-Id": session_id,
        }

        return StreamingResponse(
            content=self._event_generator(
                session=session,
                chunk_generator=generator,
                last_event_id=last_event_id,
            ),
            media_type="text/event-stream",
            headers=response_headers,
        )

    async def _event_generator(
        self,
        session: StreamSession,
        chunk_generator: AsyncGenerator[GenerationChunk, None],
        last_event_id: str | None,
    ) -> AsyncGenerator[str, None]:
        """内部 SSE 事件异步生成器。

        使用 ``asyncio.Queue`` 合并主推送循环和心跳任务的输出。

        Args:
            session: StreamSession 会话上下文。
            chunk_generator: 上游 CSLT-03 的 AsyncGenerator。
            last_event_id: 前端 ``Last-Event-Id`` 请求头值（可选）。
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        full_timeout = self._settings.SSE_FULL_TIMEOUT_SECONDS
        first_chunk_timeout = self._settings.SSE_FIRST_CHUNK_TIMEOUT_SECONDS
        heartbeat_interval = self._settings.SSE_HEARTBEAT_INTERVAL_SECONDS

        # 解析 Last-Event-Id，确定续传起点
        resume_from: int | None = None
        if last_event_id is not None and last_event_id.isdigit():
            resume_from = int(last_event_id)

        # ================================================================
        # 心跳循环（独立 asyncio.Task，与主推送循环并行运行）
        # ================================================================

        async def _heartbeat_loop() -> None:
            """心跳保活循环。

            每 ``heartbeat_interval`` 秒向 queue 写入一个 SSE heartbeat 事件帧。
            通过 ``asyncio.CancelledError`` 在推送结束时被取消。
            """
            try:
                while True:
                    await asyncio.sleep(heartbeat_interval)
                    sse_frame = (
                        f"event: heartbeat\n"
                        f"data: {HeartbeatEvent().model_dump_json()}\n\n"
                    )
                    await queue.put(sse_frame)
            except asyncio.CancelledError:
                pass

        # ================================================================
        # 主推送循环（消费上游 Generator，产出 SSE chunk/done/error 事件）
        # ================================================================

        async def _chunk_consumer() -> None:
            """消费上游 Generator 并产出 chunk/done/error SSE 事件到 queue。"""
            try:
                # 步骤 3: 启动上游 Generator 消费与 SSE 推送
                session.status = "STREAMING"
                self._session_manager.update_session(session)

                it = chunk_generator.__aiter__()
                # 若为断点续传，跳过已推送的 chunk
                skip_count = (resume_from or 0)

                # 记录当前已跳过的 chunk 数，用于 continue 场景
                skipped = 0

                while True:
                    # ==================================================
                    # 硬超时检测（步骤 4 第 8 项）
                    # ==================================================
                    elapsed = time.monotonic() - session.created_at
                    if elapsed >= full_timeout:
                        await chunk_generator.aclose()
                        session.finish_reason = "TIMEOUT"
                        done_event = DoneEvent(
                            finish_reason="TIMEOUT",
                            sequence=session.sequence if session.sequence > 0 else None,
                        )
                        sse_frame = (
                            f"event: done\n"
                            f"data: {done_event.model_dump_json()}\n\n"
                        )
                        await queue.put(sse_frame)
                        logger.info(
                            service="streaming",
                            message="stream_timeout",
                            op_type="stream_timeout",
                            extra={
                                "stream_id": session.stream_id,
                                "finish_reason": "TIMEOUT",
                                "chunks_sent": session.total_chunks,
                            },
                        )
                        return

                    # ==================================================
                    # 获取下一个 chunk
                    # ==================================================
                    try:
                        if session.first_chunk_sent_at is None:
                            # 首 chunk 软超时检测（步骤 4 第 2 项）
                            chunk = await asyncio.wait_for(
                                it.__anext__(),
                                timeout=first_chunk_timeout,
                            )
                        else:
                            chunk = await it.__anext__()
                    except asyncio.TimeoutError:
                        # 软超时：发送进度提示，不终止流
                        error_event = ErrorEvent(
                            error_code=StreamErrorCode.STREAM_TIMEOUT,
                            detail="正在生成中，请耐心等待",
                        )
                        sse_frame = (
                            f"event: error\n"
                            f"data: {error_event.model_dump_json()}\n\n"
                        )
                        await queue.put(sse_frame)
                        continue
                    except StopAsyncIteration:
                        # Generator 正常结束但未产出 is_final=True 的 chunk
                        if session.total_chunks == 0:
                            # 从未收到任何 chunk，视为异常
                            error_event = ErrorEvent(
                                error_code=StreamErrorCode.GENERATION_FAILED,
                                detail="方案生成失败，请稍后重试",
                            )
                            sse_frame = (
                                f"event: error\n"
                                f"data: {error_event.model_dump_json()}\n\n"
                            )
                            await queue.put(sse_frame)
                            session.finish_reason = "ERROR"
                        else:
                            # 已推送部分内容但缺少最终标记，视为正常完成
                            session.finish_reason = "COMPLETE"
                            done_event = DoneEvent(
                                finish_reason="COMPLETE",
                                sequence=session.sequence,
                            )
                            sse_frame = (
                                f"event: done\n"
                                f"data: {done_event.model_dump_json()}\n\n"
                            )
                            await queue.put(sse_frame)
                        return
                    except Exception as exc:
                        # 步骤 5: 异常终端处理
                        await self._handle_generator_error(
                            session=session,
                            queue=queue,
                            error=exc,
                        )
                        return

                    # ==================================================
                    # 断点续传：跳过已推送的 chunk（步骤 3 第 3 项）
                    # ==================================================
                    if skipped < skip_count:
                        skipped += 1
                        continue

                    # ==================================================
                    # 步骤 4: 逐 chunk 消费与 SSE 事件推送
                    # ==================================================

                    # 记录首个 chunk 时间（步骤 4 第 1 项）
                    if session.first_chunk_sent_at is None:
                        session.first_chunk_sent_at = time.monotonic()
                        session.ttft_ms = (
                            (session.first_chunk_sent_at - session.created_at) * 1000.0
                        )

                    # 递增 sequence（步骤 4 第 3 项）
                    session.sequence += 1

                    # 构建 chunk 事件（步骤 4 第 4 项）
                    chunk_event = ChunkEvent(
                        text=chunk.text,
                        sequence=session.sequence,
                    )

                    # 写入 SSE 帧（步骤 4 第 5 项）
                    sse_frame = (
                        f"id: {session.sequence}\n"
                        f"event: chunk\n"
                        f"data: {chunk_event.model_dump_json()}\n\n"
                    )
                    await queue.put(sse_frame)

                    # 缓存文本（步骤 4 第 6 项）
                    session.chunk_buffer[session.sequence] = chunk.text
                    session.total_chunks += 1

                    # 检查是否为最终 chunk（步骤 4 第 7 项）
                    if chunk.is_final:
                        # 步骤 6: 正常完成终端处理
                        finish_reason = self._map_finish_reason(chunk.finish_reason)
                        session.status = "COMPLETED"
                        session.finish_reason = finish_reason

                        done_event = DoneEvent(
                            finish_reason=finish_reason,
                            sequence=session.sequence,
                        )
                        sse_frame = (
                            f"event: done\n"
                            f"data: {done_event.model_dump_json()}\n\n"
                        )
                        await queue.put(sse_frame)

                        logger.info(
                            service="streaming",
                            message="stream_completed",
                            op_type="stream_complete",
                            extra={
                                "stream_id": session.stream_id,
                                "chunks_total": session.total_chunks,
                                "ttft_ms": session.ttft_ms,
                                "finish_reason": finish_reason,
                            },
                        )
                        return

            except asyncio.CancelledError:
                # 主循环被取消（客户端断开等情况）
                pass
            finally:
                # try/finally 保证 done/error 事件必达
                # 如果上述逻辑未发送任何终止事件，在此补发 ERROR
                if session.status not in ("COMPLETED", "ABORTED"):
                    session.status = "ABORTED"
                    session.finish_reason = "ERROR"
                    done_event = DoneEvent(
                        finish_reason="ERROR",
                        sequence=session.sequence if session.sequence > 0 else None,
                    )
                    sse_frame = (
                        f"event: done\n"
                        f"data: {done_event.model_dump_json()}\n\n"
                    )
                    await queue.put(sse_frame)

                # 确保 session 状态同步到管理器
                self._session_manager.update_session(session)
                # 标记生成器结束
                await queue.put(_SENTINEL)

        # ====================================================================
        # 启动消费者任务和心跳任务
        # ====================================================================
        consumer_task = asyncio.create_task(_chunk_consumer())
        heartbeat_task = asyncio.create_task(_heartbeat_loop())

        try:
            # 从 queue 中读取并逐个 yield 给 StreamingResponse
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    break
                yield item
        finally:
            # 清理：取消两个后台任务
            consumer_task.cancel()
            heartbeat_task.cancel()
            for t in (consumer_task, heartbeat_task):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

            # 释放信号量
            SseStreamingService._semaphore.release()

            # 定期清理过期会话
            self._session_manager.cleanup_expired(
                self._settings.SSE_SESSION_TTL_SECONDS,
            )

    async def _handle_generator_error(
        self,
        session: StreamSession,
        queue: asyncio.Queue,
        error: Exception,
    ) -> None:
        """处理上游 Generator 异常（步骤 5）。

        根据异常类型设置 finish_reason，发送 DoneEvent 或 ErrorEvent。

        Args:
            session: StreamSession 会话上下文。
            queue: SSE 事件队列。
            error: 捕获的异常实例。
        """
        session.status = "ABORTED"

        # 根据是否已推送内容决定发 DoneEvent 还是 ErrorEvent
        if session.sequence > 0:
            # 已推送部分内容，发送 DoneEvent
            session.finish_reason = "ERROR"
            done_event = DoneEvent(
                finish_reason="ERROR",
                sequence=session.sequence,
            )
            sse_frame = (
                f"event: done\n"
                f"data: {done_event.model_dump_json()}\n\n"
            )
            await queue.put(sse_frame)
        else:
            # 未推送任何 chunk，发送 ErrorEvent
            session.finish_reason = "ERROR"
            error_event = ErrorEvent(
                error_code=StreamErrorCode.GENERATION_FAILED,
                detail="方案生成失败，请稍后重试",
            )
            sse_frame = (
                f"event: error\n"
                f"data: {error_event.model_dump_json()}\n\n"
            )
            await queue.put(sse_frame)

        logger.error(
            service="streaming",
            message="upstream_generator_failed",
            op_type="generator_error",
            extra={
                "stream_id": session.stream_id,
                "finish_reason": "ERROR",
                "chunks_sent": session.total_chunks,
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
        )

        self._session_manager.update_session(session)

    async def _build_done_only_response(
        self,
        session: StreamSession,
    ) -> StreamingResponse:
        """对已完成/已中止会话返回直接包含 DoneEvent 的 StreamingResponse。

        当重连时发现会话处于最终状态时，返回一个立即完成的事件流。

        Args:
            session: 已处于最终状态的 StreamSession。

        Returns:
            StreamingResponse: 包含单个 done 事件的 SSE 响应。
        """
        finish_reason = session.finish_reason or "COMPLETE"
        done_event = DoneEvent(
            finish_reason=finish_reason,
            sequence=session.sequence if session.sequence > 0 else None,
        )

        async def _done_only() -> AsyncGenerator[str, None]:
            sse_frame = f"event: done\ndata: {done_event.model_dump_json()}\n\n"
            yield sse_frame

        return StreamingResponse(
            content=_done_only(),
            media_type="text/event-stream",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @staticmethod
    def _map_finish_reason(reason: str | None) -> str:
        """将 CSLT-03 GenerationChunk.finish_reason 映射为 GenerationStatus 枚举值。

        Mapping:
            "stop"   -> "COMPLETE"
            "length" -> "PARTIAL"
            "timeout" -> "TIMEOUT"
            "BLOCKED" -> "BLOCKED"
            None     -> "COMPLETE"

        Args:
            reason: CSLT-03 的 finish_reason。

        Returns:
            str: GenerationStatus 对应的枚举值。
        """
        mapping = {
            "stop": "COMPLETE",
            "length": "PARTIAL",
            "timeout": "TIMEOUT",
            "BLOCKED": "BLOCKED",
            None: "COMPLETE",
        }
        return mapping.get(reason, "COMPLETE")
