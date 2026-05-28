"""CSLT-02 RAG 检索 — 异常类单元测试。
"""

from __future__ import annotations

from py_infra.exceptions import EmbeddingUnavailableError, RetrievalTimeoutError


class TestRetrievalTimeoutError:
    def test_defaults(self):
        e = RetrievalTimeoutError()
        assert e.status_code == 504
        assert e.elapsed_ms == 500.0
        assert e.partial_count == 0

    def test_custom(self):
        e = RetrievalTimeoutError("自定义超时", elapsed_ms=1200.0, partial_count=3)
        assert e.elapsed_ms == 1200.0
        assert e.partial_count == 3


class TestEmbeddingUnavailableError:
    def test_defaults(self):
        e = EmbeddingUnavailableError()
        assert e.status_code == 503
        assert e.retry_count == 3

    def test_with_last_error(self):
        e = EmbeddingUnavailableError(last_error="Connection refused")
        assert e.last_error == "Connection refused"
