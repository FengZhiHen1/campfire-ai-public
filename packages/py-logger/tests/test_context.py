"""Trace ID 上下文管理 — 单元测试。"""

from __future__ import annotations

from py_logger.context import get_trace_id, set_trace_id


class TestGetTraceId:
    def test_default_empty(self):
        assert get_trace_id() == ""

    def test_after_set(self):
        set_trace_id("abc123def456")
        assert get_trace_id() == "abc123def456"


class TestSetTraceId:
    def test_overwrite(self):
        set_trace_id("first")
        set_trace_id("second")
        assert get_trace_id() == "second"
