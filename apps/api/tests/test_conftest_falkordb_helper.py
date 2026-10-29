"""`connect_falkordb_or_skip` 必须按 `Settings` 连接，不硬编码共享实例。

硬编码 `localhost:6380` / `campfire` 时，`FALKORDB_PORT=<独立实例>` 会被忽略，测试实际
连到共享 FalkorDB。这里用替身断言 host/port/password/database 原样传下去，不建连接。
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from campfire.core.config import Settings

from . import conftest as conftest_module


def _settings(**overrides: Any) -> Settings:  # noqa: ANN401 —— 仅转发给 Settings
    """不读 `.env` 的配置，避免宿主机配置影响断言。"""
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg, arg-type]


@pytest.fixture
def recording(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """把上游客户端与驱动换成记录参数的替身（不连网络）。"""
    calls: dict[str, Any] = {}

    class _Client:
        def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
            calls["kwargs"] = kwargs

        async def aclose(self) -> None:
            return None

    class _Driver:
        def __init__(self, *, falkor_db: Any, database: str) -> None:  # noqa: ANN401
            calls["database"] = database
            calls["db_obj"] = falkor_db

    monkeypatch.setattr("falkordb.asyncio.FalkorDB", _Client)
    monkeypatch.setattr("graphiti_core.driver.falkordb_driver.FalkorDriver", _Driver)
    return calls


def test_helper_forwards_settings_overrides(recording: dict[str, Any]) -> None:
    """host/port/password/database 全部来自传入的配置。"""
    settings = _settings(
        falkordb_host="127.0.0.1",
        falkordb_port=6381,
        falkordb_password=SecretStr("not-a-real-secret"),
        falkordb_database="campfire_isolation_probe",
    )

    _driver, client = conftest_module.connect_falkordb_or_skip(settings)

    assert recording["kwargs"]["host"] == "127.0.0.1"
    assert recording["kwargs"]["port"] == 6381
    assert recording["kwargs"]["password"] == "not-a-real-secret"
    assert recording["database"] == "campfire_isolation_probe"
    assert recording["db_obj"] is client


def test_helper_defaults_to_process_settings(recording: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """不传参数时读 `get_settings()`，而不是回落到硬编码常量。"""
    monkeypatch.setattr(
        "campfire.core.config.get_settings",
        lambda: _settings(falkordb_host="127.0.0.1", falkordb_port=6381, falkordb_database="campfire_env"),
    )

    conftest_module.connect_falkordb_or_skip()

    assert recording["kwargs"]["host"] == "127.0.0.1"
    assert recording["kwargs"]["port"] == 6381
    assert recording["database"] == "campfire_env"


def test_helper_passes_no_password_when_unset(recording: dict[str, Any]) -> None:
    """dev 的 FalkorDB 没有密码：显式传 None，不要拼空串（`AUTH ""` 会失败）。"""
    conftest_module.connect_falkordb_or_skip(_settings(falkordb_password=None))

    assert recording["kwargs"]["password"] is None


def test_unavailable_container_skips_with_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """连不上时仍然是 skip（不是 ERROR），且消息里给出实际地址。"""

    class _Refusing:
        def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
            raise ConnectionRefusedError("refused")

    monkeypatch.setattr("falkordb.asyncio.FalkorDB", _Refusing)

    with pytest.raises(pytest.skip.Exception, match=r"127\.0\.0\.1:6381"):
        conftest_module.connect_falkordb_or_skip(_settings(falkordb_host="127.0.0.1", falkordb_port=6381))
