"""健康检查的形状与端点行为。

对应 docs/项目结构设计.md 第 10 节的要求：**分别报告各项能力，不用一个全绿接口
表示所有能力安全**。因此这里既断言 All-OK 时 200，也断言局部不可用时 503 且
其余能力仍被如实报告。
"""

from collections.abc import Awaitable, Callable

import pytest
from fastapi.testclient import TestClient

from campfire import main as main_module
from campfire.core.config import Settings
from campfire.core.health import ComponentHealth, HealthReport, Status

# 端点报告的四个能力名，与 main.health 的装配顺序无关（断言用集合）
EXPECTED_COMPONENTS = {"auth", "database", "model", "queue"}


def test_report_is_ready_only_when_every_component_is_ok() -> None:
    report = HealthReport((ComponentHealth("database", Status.OK, "连接正常"),))

    assert report.is_ready is True
    assert report.degraded == ()


def test_report_exposes_degraded_components_individually() -> None:
    report = HealthReport(
        (
            ComponentHealth("database", Status.OK, "连接正常"),
            ComponentHealth("model", Status.NOT_CONFIGURED, "未配置 TOKENHUB_API_KEY"),
        )
    )

    assert report.is_ready is False
    assert [item.name for item in report.degraded] == ["model"]
    assert report.as_dict()["components"]["model"]["status"] == "not_configured"


def _install_probes(monkeypatch: pytest.MonkeyPatch, *, failing: str | None) -> None:
    """替换四个探针为测试替身，避免测试依赖网络与基础设施。"""
    attributes = {
        "auth": "check_auth_core",
        "database": "check_database",
        "model": "check_model",
        "queue": "check_queue",
    }

    def make(name: str) -> Callable[[Settings], Awaitable[ComponentHealth]]:
        status = Status.UNAVAILABLE if name == failing else Status.OK

        async def probe(_settings: Settings) -> ComponentHealth:
            return ComponentHealth(name, status, "测试替身")

        return probe

    for component, attribute in attributes.items():
        monkeypatch.setattr(main_module, attribute, make(component))


def test_health_returns_200_when_all_capabilities_are_up(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_probes(monkeypatch, failing=None)

    with TestClient(main_module.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert set(body["components"]) == EXPECTED_COMPONENTS
    assert all(item["status"] == "ok" for item in body["components"].values())


def test_health_returns_503_and_still_reports_the_healthy_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_probes(monkeypatch, failing="model")

    with TestClient(main_module.app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["components"]["model"]["status"] == "unavailable"
    # 局部不可用不得掩盖其余能力的真实状态
    assert body["components"]["database"]["status"] == "ok"
    assert body["components"]["queue"]["status"] == "ok"
    assert body["components"]["auth"]["status"] == "ok"
