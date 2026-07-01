"""结构化日志核心 — 单元测试。"""

from __future__ import annotations

import json

from py_logger.core import JSONFormatter, _default_handler, _make_timestamp


class TestMakeTimestamp:
    def test_returns_string(self):
        ts = _make_timestamp()
        assert isinstance(ts, str)

    def test_ends_with_z(self):
        ts = _make_timestamp()
        assert ts.endswith("Z")

    def test_contains_t(self):
        ts = _make_timestamp()
        assert "T" in ts


class TestDefaultHandler:
    def test_unserializable_object(self):
        result = _default_handler(set([1, 2, 3]))
        assert result.startswith("<set:")
        assert "1" in result

    def test_complex_object(self):
        result = _default_handler(lambda x: x)
        assert "lambda" in result or "function" in result


class TestJSONFormatter:
    def test_format_output_is_json(self):
        import logging

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=1,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        record.service = "test-service"
        record.trace_id = "trace-abc"
        record.op_type = None
        record.extra = None
        output = formatter.format(record)
        data = json.loads(output)
        assert data["severity"] == "INFO"
        assert data["service"] == "test-service"
        assert data["message"] == "hello world"
        assert data["trace_id"] == "trace-abc"
