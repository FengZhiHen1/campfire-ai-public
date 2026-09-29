"""探针的失败语义：区分「未配置」「配置非法」与「不可达」。

这组用例来自一次实测：宿主机 ``NO_PROXY`` 含 IPv6 字面量（``[::1]``）时，
httpx 解析代理豁免列表抛 ``InvalidURL: Invalid port``，而当时的探针把它统一
报成「core 不可达」——把排查者引向网络问题。下面用实测确认过的触发值锁住行为：

- 坏端口 → ``httpx.InvalidURL``
- 缺协议头 / 错协议 → ``httpx.UnsupportedProtocol``
"""

import pytest

from campfire.agent.model import check_model_endpoint
from campfire.core.auth import check_auth_core, core_hello_url
from campfire.core.config import Settings
from campfire.core.health import Status


def test_core_hello_url_strips_trailing_slash() -> None:
    settings = Settings(supertokens_connection_uri="http://core:3567/")

    assert core_hello_url(settings) == "http://core:3567/hello"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configured",
    [
        pytest.param("", id="缺协议头"),
        pytest.param("not-a-url", id="完全不是 URL"),
        pytest.param("http://localhost:notaport", id="端口非法"),
    ],
)
async def test_auth_probe_reports_invalid_config_not_unreachable(configured: str) -> None:
    result = await check_auth_core(Settings(supertokens_connection_uri=configured))

    assert result.status is Status.UNAVAILABLE
    assert "SUPERTOKENS_CONNECTION_URI" in result.detail
    # 关键断言：配置问题不得被描述成可达性问题
    assert "不可达" not in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configured",
    [
        pytest.param("", id="缺协议头"),
        pytest.param("http://localhost:notaport", id="端口非法"),
    ],
)
async def test_model_probe_reports_invalid_config(configured: str) -> None:
    settings = Settings(tokenhub_base_url=configured, tokenhub_api_key="test-key-not-a-secret")

    report = await check_model_endpoint(settings)

    assert report.configured is True
    assert report.reachable is False
    assert "不是合法 URL" in report.detail


@pytest.mark.asyncio
async def test_model_probe_reports_not_configured_without_key() -> None:
    report = await check_model_endpoint(Settings(tokenhub_api_key=None))

    assert report.configured is False
    assert report.reachable is False
    assert "TOKENHUB_API_KEY" in report.detail
