"""CSLT-03 应急方案生成 — Prometheus 指标定义。

指标清单：
    crisis_generation_requests_total{status}      — 请求量计数
    crisis_generation_duration_seconds            — 生成耗时 Histogram
    crisis_generation_ttft_seconds                — 首字延迟 Histogram
    crisis_generation_tokens_total{type}           — Token 消耗计数

依赖 prometheus_client，若未安装则使用 No-op 桩确保不阻塞业务。
"""

from __future__ import annotations

try:
    from prometheus_client import Counter, Histogram

    GENERATION_REQUESTS = Counter(
        "crisis_generation_requests_total",
        "Total number of generation requests",
        ["status"],
    )
    GENERATION_DURATION = Histogram(
        "crisis_generation_duration_seconds",
        "Generation duration in seconds",
        buckets=[0.5, 1, 2, 3, 5, 10, 15],
    )
    GENERATION_TTFT = Histogram(
        "crisis_generation_ttft_seconds",
        "Time to first token in seconds",
        buckets=[0.1, 0.5, 1, 2, 3, 5],
    )
    GENERATION_TOKENS = Counter(
        "crisis_generation_tokens_total",
        "Total tokens consumed",
        ["type"],
    )

except ImportError:

    class _NoopMetric:
        """No-op metric stub — absorbs all calls when prometheus_client is unavailable."""

        __slots__ = ()

        def labels(self, **kwargs: str) -> _NoopMetric:  # type: ignore[misc]
            return self

        def inc(self, amount: float = 1) -> None:
            pass

        def observe(self, amount: float) -> None:
            pass

    class _CounterNoop(_NoopMetric):
        pass

    class _HistogramNoop(_NoopMetric):
        pass

    GENERATION_REQUESTS: Counter = _CounterNoop()  # type: ignore[no-redef]
    GENERATION_DURATION: Histogram = _HistogramNoop()  # type: ignore[no-redef]
    GENERATION_TTFT: Histogram = _HistogramNoop()  # type: ignore[no-redef]
    GENERATION_TOKENS: Counter = _CounterNoop()  # type: ignore[no-redef]


__all__ = [
    "GENERATION_REQUESTS",
    "GENERATION_DURATION",
    "GENERATION_TTFT",
    "GENERATION_TOKENS",
]
