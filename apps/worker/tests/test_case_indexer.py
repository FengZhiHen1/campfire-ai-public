"""Worker case_indexer 模块单元测试。

测试向后兼容的 index_case() 函数：正确委托 IndexPipeline、使用正确的队列键。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.tasks.case_indexer import INDEX_QUEUE_KEY, index_case


class TestIndexCase:
    """index_case 函数测试。"""

    @pytest.mark.asyncio
    async def test_delegates_to_pipeline_process_task(self):
        """index_case 应委托 IndexPipeline.process_task() 处理索引。"""
        mock_pipeline = MagicMock()
        mock_pipeline.process_task = AsyncMock()

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        with (
            patch(
                "worker.tasks.case_indexer.IndexPipeline",
                return_value=mock_pipeline,
            ),
            patch(
                "py_rag.embedding._get_encoder",
                return_value=MagicMock(),
            ),
            patch(
                "sqlalchemy.ext.asyncio.create_async_engine",
                return_value=mock_engine,
            ),
            patch(
                "sqlalchemy.ext.asyncio.async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("py_config.get_settings"),
        ):
            await index_case("550e8400-e29b-41d4-a716-446655440000", trace_id="abc123")

        mock_pipeline.process_task.assert_called_once()
        call_kwargs = mock_pipeline.process_task.call_args.kwargs
        assert call_kwargs["case_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert call_kwargs["trace_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_engine_disposed_after_use(self):
        """index_case 完成后应 dispose 数据库引擎。"""
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_pipeline = MagicMock()
        mock_pipeline.process_task = AsyncMock()

        with (
            patch(
                "worker.tasks.case_indexer.IndexPipeline",
                return_value=mock_pipeline,
            ),
            patch(
                "py_rag.embedding._get_encoder",
                return_value=MagicMock(),
            ),
            patch(
                "sqlalchemy.ext.asyncio.create_async_engine",
                return_value=mock_engine,
            ),
            patch(
                "sqlalchemy.ext.asyncio.async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("py_config.get_settings"),
        ):
            await index_case("test-id")

        mock_engine.dispose.assert_called_once()


class TestQueueKeyExport:
    """队列键导出测试。"""

    def test_exports_contract_queue_key(self):
        """case_indexer 应导出契约定义的队列键。"""
        assert INDEX_QUEUE_KEY == "index:queue:case_chunks"


class TestModuleAll:
    """__all__ 导出测试。"""

    def test_index_case_in_all(self):
        """index_case 应在 __all__ 中。"""
        from worker.tasks.case_indexer import __all__

        assert "index_case" in __all__
        assert "INDEX_QUEUE_KEY" in __all__
