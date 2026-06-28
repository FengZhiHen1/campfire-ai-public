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
import uuid
from typing import Any, AsyncGenerator, ClassVar, Literal, cast

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

from app.modules.consultation.plan_generation.models import GenerationChunk
from app.modules.consultation.plan_generation.streaming import parse_json_sections

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

    单例服务，通过 ``__new__`` 确保全局唯一实例。
    使用 ``asyncio.Semaphore`` 控制全局并发连接数（每个 Uvicorn worker 进程独立）。

    核心入口为 ``stream_response()``，返回 ``FastAPI StreamingResponse``。
    """

    _instance: SseStreamingService | None = None
    _semaphore: ClassVar[asyncio.Semaphore] = asyncio.Semaphore(1)
    """模块级信号量，所有实例共享。实际容量由 _init_semaphore 在 __init__ 中设置。"""

    _semaphore_initialized: ClassVar[bool] = False
    _generators: dict[str, AsyncGenerator[GenerationChunk, None]]
    _generation_meta: dict[str, dict]
    _initialized: bool

    def __new__(cls, *args, **kwargs) -> SseStreamingService:
        """确保全局只有一个 SseStreamingService 实例。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._generators = {}
            cls._instance._generation_meta = {}
        return cls._instance

    def __init__(
        self,
        settings: AppSettings | None = None,
        session_manager: StreamSessionManager | None = None,
    ) -> None:
        # 避免重复初始化
        if hasattr(self, "_initialized") and self._initialized:
            return

        self._settings = settings or AppSettings.model_validate({})
        self._session_manager = session_manager or StreamSessionManager()

        # 初始化信号量容量（首次初始化后不再变更）
        if not SseStreamingService._semaphore_initialized:
            max_connections = self._settings.SSE_MAX_CONCURRENT_CONNECTIONS
            SseStreamingService._semaphore = asyncio.Semaphore(max_connections)
            SseStreamingService._semaphore_initialized = True

        self._initialized = True

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

    def store_generation_meta(
        self,
        session_id: str,
        prenumbered_slices: dict[str, str],
        crisis_level: str,
        search_result: Any = None,
        plan_input: Any = None,
        block_deep_response: bool = False,
        behavior_description: str = "",
        request_id: str = "",
        user_id: str = "",
    ) -> None:
        """存储生成元数据，供 SSE DoneEvent 构造时注入。

        Args:
            session_id: 流标识符。
            prenumbered_slices: 预编号切片映射 {编号: slice_id}。
            crisis_level: 危机分级结果字符串。
            search_result: RAG 检索结果（可选）。
            plan_input: EmergencyPlanInput（可选）。
            block_deep_response: 是否阻断深度回答。
            behavior_description: 用户行为描述。
            request_id: 追踪 ID。
            user_id: 发起咨询的用户 UUID 字符串，供归档写入使用。
        """
        self._generation_meta[session_id] = {
            "prenumbered_slices": prenumbered_slices,
            "crisis_level": crisis_level,
            "search_result": search_result,
            "plan_input": plan_input,
            "block_deep_response": block_deep_response,
            "behavior_description": behavior_description,
            "request_id": request_id,
            "user_id": user_id,
        }

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
                service="streaming",
                message="concurrency_limit_reached",
                extra={
                    "current_connections": current_connections,
                    "rejected_session": session_id,
                },
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
            if last_event_id is not None:
                # 仅当 last_event_id 是合法正整数格式时才视为重连
                if (
                    last_event_id.isdigit()
                    and 0 < int(last_event_id) <= 2_147_483_647
                ):
                    SseStreamingService._semaphore.release()
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={
                            "error_code": "SESSION_NOT_FOUND",
                            "detail": "当前推送会话不存在或已过期",
                        },
                    )
                # 非法格式的 last_event_id：忽略，视为新连接
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

        # 类型检查：必须是 AsyncGenerator
        if not hasattr(generator, "__aiter__"):
            SseStreamingService._semaphore.release()
            raise TypeError(
                "chunk_generator 必须是异步生成器 (AsyncGenerator)，"
                f"实际类型为 {type(generator).__name__}"
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
                # 首 chunk 超时已触发过的标记——避免循环重试 wait_for 导致
                # __anext__ 被反复取消、chunk 计数错乱
                first_chunk_timeout_fired = False

                while True:
                    # ==================================================
                    # 硬超时检测（步骤 4 第 8 项）
                    # ==================================================
                    elapsed = time.monotonic() - session.created_at
                    if elapsed >= full_timeout:
                        await chunk_generator.aclose()
                        session.status = "COMPLETED"
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
                        await self._try_archive(session)
                        return

                    # ==================================================
                    # 获取下一个 chunk
                    # ==================================================
                    try:
                        if session.first_chunk_sent_at is None and not first_chunk_timeout_fired:
                            # 首 chunk 软超时检测：shield 防止取消破坏 generator 内部状态
                            chunk = await asyncio.wait_for(
                                asyncio.shield(it.__anext__()),
                                timeout=first_chunk_timeout,
                            )
                        else:
                            chunk = await it.__anext__()
                    except asyncio.TimeoutError:
                        first_chunk_timeout_fired = True
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
                            session.status = "ABORTED"
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
                        else:
                            # 已推送部分内容但缺少最终标记，视为正常完成
                            session.status = "COMPLETED"
                            session.finish_reason = "COMPLETE"
                            done_meta = await self._build_done_meta(session)
                            done_event = DoneEvent(
                                finish_reason="COMPLETE",
                                sequence=session.sequence,
                                referenced_slice_ids=done_meta.get("referenced_slice_ids", []),
                                crisis_level=done_meta.get("crisis_level"),
                                confidence_score=done_meta.get("confidence_score"),
                                verdict=done_meta.get("verdict"),
                                ticket_triggered=done_meta.get("ticket_triggered", False),
                                sections=done_meta.get("sections", {}),
                            )
                            sse_frame = (
                                f"event: done\n"
                                f"data: {done_event.model_dump_json()}\n\n"
                            )
                            await queue.put(sse_frame)
                            await self._try_archive(session)
                        return
                    except Exception as exc:
                        # 步骤 5: 异常终端处理
                        await self._handle_generator_error(
                            session=session,
                            queue=queue,
                            error=exc,
                        )
                        await self._try_archive(session)
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
                        section=chunk.section,
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

                        done_meta = await self._build_done_meta(session, raw_full_text=chunk.raw_full_text)
                        done_event = DoneEvent(
                            finish_reason=finish_reason,
                            sequence=session.sequence,
                            referenced_slice_ids=done_meta.get("referenced_slice_ids", []),
                            crisis_level=done_meta.get("crisis_level"),
                            referenced_cases=done_meta.get("referenced_cases", []),
                            confidence_score=done_meta.get("confidence_score"),
                            verdict=done_meta.get("verdict"),
                            ticket_triggered=done_meta.get("ticket_triggered", False),
                            sections=done_meta.get("sections", {}),
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
                        await self._try_archive(session)
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
                    await self._try_archive(session)

                # 清理生成元数据
                self._generation_meta.pop(session.stream_id, None)

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

    async def _try_archive(self, session: StreamSession) -> None:
        """流完成后将咨询记录归档写入数据库。

        从 generation_meta 和 session 中提取归档所需全部字段，
        直接调用 ConsultHistoryRepository 写入 consultations 表。
        写入失败仅记录日志，不阻塞 SSE 流的正常结束。

        仅在 generation_meta 中存在有效 user_id 时执行归档。
        """
        meta = self._generation_meta.get(session.stream_id)
        if meta is None:
            return

        user_id = meta.get("user_id", "")
        if not user_id:
            return

        crisis_level: str = meta.get("crisis_level", "mild")
        behavior_description: str = meta.get("behavior_description", "")
        prenumbered_slices: dict[str, str] = meta.get("prenumbered_slices", {})

        # 拼接生成全文
        if session.chunk_buffer:
            full_text = "".join(
                session.chunk_buffer[i]
                for i in sorted(session.chunk_buffer.keys())
            )
        else:
            full_text = ""

        if not full_text.strip():
            return

        # 从全文解析四段式结构化数据
        sections = parse_json_sections(full_text)

        # 从全文提取引用的 slice IDs
        import re
        ref_pattern = re.compile(r"\[(\d+)\]")
        referenced_slice_ids: list[str] = []
        seen: set[str] = set()
        for tag in ref_pattern.findall(full_text):
            key = f"[{tag}]"
            if key in prenumbered_slices and prenumbered_slices[key] not in seen:
                referenced_slice_ids.append(prenumbered_slices[key])
                seen.add(prenumbered_slices[key])

        # 构建 source_list
        search_result = meta.get("search_result")
        referenced_cases = self._build_referenced_cases(
            referenced_slice_ids, search_result,
        )
        source_list: list[str] = [
            f"[{i + 1}] {c['case_title']}"
            for i, c in enumerate(referenced_cases)
        ]

        finish_reason = session.finish_reason or "COMPLETE"
        generation_time_ms = (time.monotonic() - session.created_at) * 1000.0

        archive_request_id = str(uuid.uuid4())
        archive_data: dict[str, object] = {
            "id": uuid.uuid4(),
            "request_id": archive_request_id,
            "user_id": user_id,
            "crisis_level": crisis_level,
            "behavior_description": behavior_description,
            "generated_plan": full_text,
            "plan_sections": sections,
            "source_list": source_list,
            "disclaimer": (
                "以上建议由 AI 生成，仅供参考，不构成医疗诊断或治疗建议。"
                "如情况紧急，请立即联系专业医疗机构。"
            ),
            "generation_time_ms": generation_time_ms,
            "is_partial": finish_reason in ("PARTIAL", "TIMEOUT"),
            "referenced_slice_ids": referenced_slice_ids,
            "finish_reason": finish_reason,
            "ttft_ms": session.ttft_ms or 0.0,
            "has_feedback": False,
            "token_input": None,
            "token_output": None,
            "device_info": None,
        }

        try:
            from app.core.dependencies.auth_dependencies import _get_session_factory
            from py_db.repositories.consult_history_repository import ConsultHistoryRepository

            factory = _get_session_factory()
            async with factory() as db:
                repository = ConsultHistoryRepository()
                record = await repository.archive(db, archive_data)
                if record is not None:
                    await db.flush()
                    await db.refresh(record)
                    logger.info(
                        service="streaming",
                        message="archive_success",
                        extra={
                            "record_id": str(record.id),
                            "stream_id": session.stream_id,
                            "finish_reason": finish_reason,
                        },
                    )
                else:
                    logger.info(
                        service="streaming",
                        message="duplicate_archive_skipped",
                        extra={"stream_id": session.stream_id},
                    )
                await db.commit()
        except Exception:
            logger.error(
                service="streaming",
                message="archive_failed_in_sse",
                extra={
                    "stream_id": session.stream_id,
                    "finish_reason": finish_reason,
                },
            )

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
    def _build_referenced_cases(
        referenced_slice_ids: list[str],
        search_result: Any,
    ) -> list[dict[str, str]]:
        """根据 referenced_slice_ids 从 RAG 检索结果中提取可读的案例摘要。"""
        if not referenced_slice_ids or search_result is None:
            return []

        slice_map: dict[str, dict[str, str]] = {}
        try:
            results = getattr(search_result, "results", []) or []
            for item in results:
                sid = getattr(item, "slice_id", "")
                if sid:
                    text = getattr(item, "slice_text", "") or ""
                    slice_map[sid] = {
                        "card_id": getattr(item, "card_id", ""),
                        "case_title": getattr(item, "case_title", ""),
                        "slice_text": text[:200],
                    }
        except Exception:
            return []

        cases: list[dict[str, str]] = []
        seen: set[str] = set()
        for sid in referenced_slice_ids:
            if sid in slice_map and sid not in seen:
                info = slice_map[sid]
                cases.append({
                    "slice_id": sid,
                    "case_id": info["card_id"],
                    "case_title": info["case_title"] or "无标题",
                    "slice_text": info["slice_text"],
                })
                seen.add(sid)
        return cases

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

    async def _build_done_meta(self, session: StreamSession, raw_full_text: str | None = None) -> dict:
        """从 generation_meta 和 chunk_buffer 提取 DoneEvent 扩展元数据。

        包含置信度校验调用（非阻塞——失败时降级）。

        Args:
            session: 当前 StreamSession。
            raw_full_text: LLM 返回的原始完整 JSON 文本。优先使用此参数；
                          为 None 时回退到从 chunk_buffer 拼接。

        Returns:
            包含 referenced_slice_ids, crisis_level, confidence 等字段的 dict。
        """
        import re
        meta = self._generation_meta.get(session.stream_id)
        if meta is None:
            return {}

        prenumbered_slices: dict[str, str] = meta.get("prenumbered_slices", {})
        crisis_level: str = meta.get("crisis_level", "mild")
        block_deep_response: bool = meta.get("block_deep_response", False)

        # 使用上游传入的原始 JSON 文本（优先），回退到 chunk_buffer 拼接
        if raw_full_text:
            full_text = raw_full_text
        else:
            full_text = "".join(
                session.chunk_buffer[i]
                for i in sorted(session.chunk_buffer.keys())
            )

        # 提取 [N] 引用标记
        ref_pattern = re.compile(r"\[(\d+)\]")
        referenced_slice_ids: list[str] = []
        seen: set[str] = set()
        for tag in ref_pattern.findall(full_text):
            key = f"[{tag}]"
            if key in prenumbered_slices and prenumbered_slices[key] not in seen:
                referenced_slice_ids.append(prenumbered_slices[key])
                seen.add(prenumbered_slices[key])

        # === 从 JSON 文本解析四段式 sections ===
        sections = parse_json_sections(full_text) if full_text else {}

        logger.info(
            service="streaming",
            message="done_meta_built",
            op_type=None,
            extra={
                "stream_id": session.stream_id,
                "prenumbered_keys": list(prenumbered_slices.keys()),
                "tags_found": ref_pattern.findall(full_text),
                "referenced_slice_ids": referenced_slice_ids,
                "full_text_len": len(full_text),
                "has_search_result": meta.get("search_result") is not None,
                "sections_keys": list(sections.keys()),
                "sections_sizes": {k: len(v) for k, v in sections.items()},
                "raw_text_preview": full_text[:200] if full_text else "",
            },
        )

        result: dict = {
            "referenced_slice_ids": referenced_slice_ids,
            "crisis_level": crisis_level,
            "sections": sections,
            "referenced_cases": self._build_referenced_cases(
                referenced_slice_ids, meta.get("search_result")
            ),
        }

        # === 置信度校验（仅在正常生成时执行） ===
        if full_text and not block_deep_response:
            try:
                from py_schemas.consult.confidence import ConfidenceValidationInput
                from app.modules.consultation.consult.confidence_validator import validate_confidence

                validation_input = ConfidenceValidationInput(
                    plan_text=full_text,
                    source_list=[],
                    disclaimer=(
                        "以上建议由 AI 生成，仅供参考，不构成医疗诊断或治疗建议。"
                        "如情况紧急，请立即联系专业医疗机构。"
                    ),
                    crisis_level=cast(Literal["mild", "moderate", "severe"], crisis_level),
                    block_deep_response=block_deep_response,
                    behavior_description=meta.get("behavior_description", ""),
                    request_id=meta.get("request_id", ""),
                )
                validation_output = await validate_confidence(validation_input, None)
                result["confidence_score"] = validation_output.confidence_score
                result["verdict"] = validation_output.verdict.value if hasattr(validation_output.verdict, "value") else str(validation_output.verdict)
                result["ticket_triggered"] = validation_output.ticket_triggered
            except Exception:
                logger.warning(
                    service="streaming",
                    message="confidence_validation_failed_in_sse",
                    extra={"stream_id": session.stream_id},
                )

        return result
