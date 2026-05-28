"""OBS-04 健康检查 — 模型与状态管理单元测试。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from py_health.models import (
    ComponentHealth,
    ComponentStatus,
    Components,
    HealthCheckResponse,
    HealthStatus,
    ReadinessResponse,
)
from py_health.checker import _truncate_error, _is_status_degraded
from py_health.state import (
    get_consecutive_failures,
    get_last_status,
    increment_failures,
    reset_failures,
    set_last_status,
)


# ---- Enums ----


class TestHealthStatus:
    def test_values(self):
        assert HealthStatus.healthy == "healthy"
        assert HealthStatus.degraded == "degraded"
        assert HealthStatus.unhealthy == "unhealthy"


class TestComponentStatus:
    def test_values(self):
        assert ComponentStatus.connected == "connected"
        assert ComponentStatus.disconnected == "disconnected"


# ---- Models ----


class TestComponentHealth:
    def test_connected(self):
        h = ComponentHealth(status=ComponentStatus.connected)
        assert h.error is None

    def test_disconnected_with_error(self):
        h = ComponentHealth(status=ComponentStatus.disconnected, error="连接超时")
        assert h.error == "连接超时"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ComponentHealth(status=ComponentStatus.connected, extra="bad")


class TestComponents:
    def test_valid(self):
        c = Components(
            postgresql=ComponentHealth(status=ComponentStatus.connected),
            redis=ComponentHealth(status=ComponentStatus.connected),
            minio=ComponentHealth(status=ComponentStatus.connected),
        )
        assert c.postgresql.status == ComponentStatus.connected


class TestHealthCheckResponse:
    def test_healthy(self):
        c = Components(
            postgresql=ComponentHealth(status=ComponentStatus.connected),
            redis=ComponentHealth(status=ComponentStatus.connected),
            minio=ComponentHealth(status=ComponentStatus.connected),
        )
        resp = HealthCheckResponse(
            status=HealthStatus.healthy,
            version="0.1.0",
            uptime_seconds=3600,
            components=c,
            timestamp="2026-05-28T10:00:00+00:00",
        )
        assert resp.status == HealthStatus.healthy

    def test_uptime_non_negative(self):
        c = Components(
            postgresql=ComponentHealth(status=ComponentStatus.connected),
            redis=ComponentHealth(status=ComponentStatus.connected),
            minio=ComponentHealth(status=ComponentStatus.connected),
        )
        with pytest.raises(ValidationError):
            HealthCheckResponse(
                status=HealthStatus.healthy,
                version="0.1.0",
                uptime_seconds=-1,
                components=c,
                timestamp="2026-05-28T10:00:00+00:00",
            )


class TestReadinessResponse:
    def test_ready(self):
        resp = ReadinessResponse(
            ready=True,
            database=ComponentHealth(status=ComponentStatus.connected),
            timestamp="2026-05-28T10:00:00+00:00",
        )
        assert resp.ready is True

    def test_not_ready(self):
        resp = ReadinessResponse(
            ready=False,
            database=ComponentHealth(status=ComponentStatus.disconnected, error="超时"),
            timestamp="2026-05-28T10:00:00+00:00",
        )
        assert resp.ready is False


# ---- State management ----


class TestState:
    def test_initial_none(self):
        assert get_last_status() is None

    def test_set_and_get(self):
        set_last_status(HealthStatus.healthy)
        assert get_last_status() == HealthStatus.healthy

    def test_consecutive_failures(self):
        reset_failures()
        assert get_consecutive_failures() == 0
        assert increment_failures() == 1
        assert increment_failures() == 2
        reset_failures()
        assert get_consecutive_failures() == 0


# ---- Utility functions ----


class TestTruncateError:
    def test_short_error(self):
        assert _truncate_error("短错误") == "短错误"

    def test_long_error_truncated(self):
        long_msg = "x" * 300
        result = _truncate_error(long_msg)
        assert len(result) <= 256
        assert result.endswith("...")


class TestIsStatusDegraded:
    def test_first_check(self):
        assert _is_status_degraded(None, HealthStatus.healthy) is False

    def test_healthy_to_degraded(self):
        assert _is_status_degraded(HealthStatus.healthy, HealthStatus.degraded) is True

    def test_degraded_to_healthy(self):
        assert _is_status_degraded(HealthStatus.degraded, HealthStatus.healthy) is False

    def test_healthy_to_unhealthy(self):
        assert _is_status_degraded(HealthStatus.healthy, HealthStatus.unhealthy) is True

    def test_same_status(self):
        assert _is_status_degraded(HealthStatus.healthy, HealthStatus.healthy) is False
