"""Worker main 模块单元测试。

测试独立进程壳的核心行为：信号处理、惰性初始化、任务分发、队列配置。
Redis/DB/IndexPipeline 使用 mock，不依赖真实基础设施。
"""

from __future__ import annotations

import json
import signal
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from py_rag.indexing_contract import INDEX_QUEUE_KEY
from worker.main import (  # noqa: E402
    BRPOP_TIMEOUT,
    REDIS_RECONNECT_INITIAL,
    REDIS_RECONNECT_MAX,
    _get_pipeline,
    _get_session_factory,
    _handle_signal,
    _process_task,
    _shutdown_event,
)

_MAIN_MOD = sys.modules["worker.main"]


# ============================================================================
# 信号处理
# ============================================================================


class TestSignalHandling:
    """信号处理器测试。"""

    def test_signal_sets_shutdown_event(self):
        """SIGTERM 应设置 _shutdown_event。"""
        _shutdown_event.clear()
        _handle_signal(signal.SIGTERM, None)
        assert _shutdown_event.is_set()

    def test_sigint_sets_shutdown_event(self):
        """SIGINT 应设置 _shutdown_event。"""
        _shutdown_event.clear()
        _handle_signal(signal.SIGINT, None)
        assert _shutdown_event.is_set()


# ============================================================================
# 惰性初始化
# ============================================================================


class TestLazyInitialization:
    """惰性单例模式测试。"""

    def teardown_method(self):
        """重置模块级状态。"""
        _MAIN_MOD._session_factory = None
        _MAIN_MOD._pipeline = None
        _MAIN_MOD._engine = None

    @patch("worker.main.create_async_engine")
    @patch("worker.main.get_settings")
    def test_session_factory_lazy_singleton(self, mock_settings, mock_engine):
        """_get_session_factory 应返回惰性单例。"""
        mock_settings.return_value.DATABASE_URL = "postgresql+asyncpg://localhost/test"
        mock_engine.return_value = MagicMock()

        factory1 = _get_session_factory()
        factory2 = _get_session_factory()

        assert factory1 is factory2
        mock_engine.assert_called_once()

    @patch("py_rag.embedding._get_encoder")
    def test_pipeline_lazy_singleton(self, mock_encoder):
        """_get_pipeline 应返回惰性单例。"""
        mock_encoder.return_value = MagicMock()

        pipeline1 = _get_pipeline()
        pipeline2 = _get_pipeline()

        assert pipeline1 is pipeline2


# ============================================================================
# 任务处理
# ============================================================================


class TestProcessTask:
    """_process_task 测试。"""

    @pytest.fixture
    def mock_pipeline(self):
        """创建 mock IndexPipeline。"""
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock()
        return pipeline

    @pytest.mark.asyncio
    async def test_json_parse_error_logs_and_returns(self, mock_pipeline):
        """JSON 解析失败时应记录错误并返回，不抛异常。"""
        await _process_task(mock_pipeline, "not valid json{{{")

        mock_pipeline.process_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_case_id_skips(self, mock_pipeline):
        """缺少 case_id 时应跳过并记录警告。"""
        message = json.dumps({"trace_id": "abc123"})
        await _process_task(mock_pipeline, message)

        mock_pipeline.process_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_message_delegates_to_pipeline(self, mock_pipeline):
        """有效消息应委托给 IndexPipeline.process_task()。"""
        message = json.dumps({"case_id": "550e8400-e29b-41d4-a716-446655440000", "trace_id": "abc123"})

        with patch.object(
            _MAIN_MOD,
            "_get_session_factory",
            return_value=MagicMock(),
        ):
            await _process_task(mock_pipeline, message)

        mock_pipeline.process_task.assert_called_once()
        call_kwargs = mock_pipeline.process_task.call_args.kwargs
        assert call_kwargs["case_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert call_kwargs["trace_id"] == "abc123"


# ============================================================================
# 队列配置
# ============================================================================


class TestQueueConfiguration:
    """队列配置常量测试。"""

    def test_uses_contract_defined_queue_key(self):
        """Worker 应使用 py-rag 契约定义的队列名，非硬编码。"""
        from worker.main import INDEX_QUEUE_KEY as imported_key

        assert imported_key == "index:queue:case_chunks"
        assert imported_key == INDEX_QUEUE_KEY

    def test_brpop_timeout_positive(self):
        """BRPOP 超时应为正数。"""
        assert BRPOP_TIMEOUT > 0

    def test_reconnect_intervals_increasing(self):
        """重连间隔应递增。"""
        assert REDIS_RECONNECT_MAX > REDIS_RECONNECT_INITIAL


# ============================================================================
# 主循环
# ============================================================================


class TestMainLoop:
    """_main_loop 测试。"""

    @pytest.mark.asyncio
    async def test_shutdown_event_exits_loop(self):
        """_shutdown_event 已设置时主循环应立即退出。"""
        _shutdown_event.set()

        with patch("worker.main._get_pipeline", return_value=MagicMock()):
            await _MAIN_MOD._main_loop()

        assert _shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_brpop_timeout_returns_none_continues(self):
        """BRPOP 返回 None（超时）时应继续循环。"""
        _shutdown_event.clear()

        mock_redis = MagicMock()
        _call_count = 0

        async def _limited_brpop(_key, timeout=None):
            nonlocal _call_count
            _call_count += 1
            if _call_count >= 3:
                _shutdown_event.set()
            return None

        mock_redis.brpop = _limited_brpop

        with (
            patch("worker.main._get_pipeline", return_value=MagicMock()),
            patch("worker.main.get_redis_client", AsyncMock(return_value=mock_redis)),
        ):
            await _MAIN_MOD._main_loop()

        assert _call_count == 3


# ============================================================================
# 入口函数
# ============================================================================


class TestMainEntry:
    """main() 入口函数测试。"""

    def test_main_is_callable(self):
        """main 函数应可被调用。"""
        from worker.main import main

        assert callable(main)
