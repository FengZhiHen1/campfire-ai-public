"""CSLT-04 流式应答推送 — StreamSessionManager 会话管理器。

单例模式，内部维护 ``dict[str, StreamSession]`` 字典管理所有活跃会话。
提供创建、查询、更新、删除和过期清理功能。

所有读写操作限定在单个协程内（asyncio 单线程协作式调度，无多线程竞态条件）。
"""

from __future__ import annotations

import re
import time

from py_logger import logger
from py_schemas.streaming import StreamSession


class StreamSessionManager:
    """StreamSession 生命周期管理器（单例）。

    内部维护 ``_sessions: dict[str, StreamSession]`` 字典。
    使用 ``__new__`` 实现模块级单例，确保所有调用者共享同一实例。
    """

    _instance: StreamSessionManager | None = None
    _sessions: dict[str, StreamSession]

    def __new__(cls) -> StreamSessionManager:
        """确保全局只有一个 StreamSessionManager 实例。"""
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._sessions = {}
            cls._instance = instance
        return cls._instance

    def create_session(self, session_id: str) -> StreamSession:
        """创建新的 StreamSession，使用传入的 session_id 作为 key。

        新会话的 status 为 "CREATED"，sequence 初始化为 0。

        Args:
            session_id: 流标识符，格式 stream-{uuid4}。

        Returns:
            StreamSession: 新创建的会话对象。

        Raises:
            ValueError: session_id 格式不匹配 stream-{uuid4}。
        """
        _SESSION_ID_PATTERN = (
            r"^stream-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}"
            r"-[0-9a-f]{4}-[0-9a-f]{12}\Z"
        )
        if not re.match(_SESSION_ID_PATTERN, session_id):
            raise ValueError(
                f"Invalid session_id format: {session_id!r}. "
                f"Expected stream-{{uuid4}}",
            )

        session = StreamSession(
            stream_id=session_id,
            created_at=time.monotonic(),
        )
        self._sessions[session_id] = session
        logger.info(
            service="streaming",
            message="session_created",
            op_type="session_create",
            extra={
                "stream_id": session_id,
                "status": "CREATED",
            },
        )
        return session

    def get_session(self, session_id: str) -> StreamSession | None:
        """根据 session_id 查询会话。

        Args:
            session_id: 流标识符，格式 stream-{uuid4}。

        Returns:
            StreamSession | None: 找到的会话对象。不存在时返回 None。
        """
        return self._sessions.get(session_id)

    def update_session(self, session: StreamSession) -> None:
        """更新会话在字典中的引用。

        调用方修改 StreamSession 字段后应调用此方法同步到管理器。

        Args:
            session: 更新后的会话对象（必须包含有效的 stream_id）。
        """
        self._sessions[session.stream_id] = session

    def remove_session(self, session_id: str) -> None:
        """从字典中移除指定会话。

        Args:
            session_id: 要移除的会话的 stream_id。
        """
        self._sessions.pop(session_id, None)
        logger.info(
            service="streaming",
            message="session_removed",
            op_type="session_remove",
            extra={
                "stream_id": session_id,
                "reason": "explicit_removal",
            },
        )

    def cleanup_expired(self, ttl_seconds: float) -> int:
        """清理所有超过 TTL 的过期会话。

        遍历 ``_sessions``，将 status 非 EXPIRED 且已超过 TTL 的会话
        标记为 EXPIRED 并从字典中移除。

        Args:
            ttl_seconds: 会话过期时间（秒）。建议使用 ``SSE_SESSION_TTL_SECONDS``。

        Returns:
            int: 本次清理的过期会话数量。
        """
        now = time.monotonic()
        expired_ids: list[str] = []
        for sid, session in self._sessions.items():
            if session.status != "EXPIRED" and (now - session.created_at) >= ttl_seconds:
                session.status = "EXPIRED"
                expired_ids.append(sid)

        for sid in expired_ids:
            self._sessions.pop(sid, None)
            logger.info(
                service="streaming",
                message="session_expired",
                op_type="session_expire",
                extra={
                    "stream_id": sid,
                    "reason": "ttl_expired",
                },
            )

        return len(expired_ids)

    @property
    def active_count(self) -> int:
        """当前活跃会话数量（status 不为 EXPIRED 的会话数）。"""
        return sum(1 for s in self._sessions.values() if s.status != "EXPIRED")
