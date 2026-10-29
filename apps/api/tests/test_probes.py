"""探针的失败语义：区分「未配置」「配置非法」与「不可达」。

这组用例来自一次实测：宿主机 `NO_PROXY` 含 IPv6 字面量（`[::1]`）时，
httpx 解析代理豁免列表抛 `InvalidURL: Invalid port`，而当时的探针把它统一
报成「core 不可达」——把排查者引向网络问题。下面用实测确认过的触发值锁住行为：

- 坏端口 → `httpx.InvalidURL`
- 缺协议头 / 错协议 → `httpx.UnsupportedProtocol`
"""

import httpx
import pytest
from pydantic import SecretStr

from campfire.agent.model import check_model_endpoint
from campfire.core.auth import check_auth_core, core_hello_url
from campfire.core.config import Settings
from campfire.core.health import Status

#: 探针用例用的假凭据。`tokenhub_api_key` 声明为 `SecretStr`（避免密钥被日志/回溯
#: 原样带出），因此这里也必须包一层——与 `test_agent_model.py` 同一写法。
_TEST_API_KEY = SecretStr("test-key-not-a-secret")


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
    settings = Settings(tokenhub_base_url=configured, tokenhub_api_key=_TEST_API_KEY)

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


# --- URL 词法判断先于客户端构造（2026-10-29 实测的宿主环境遮蔽） -----------------
#
# 实测触发：宿主机 `ALL_PROXY=socks5://…` 而 `socksio` 未安装时，`httpx.AsyncClient`
# **在构造期**就抛 `ImportError`（`_init_proxy_transport`，因为 trust_env 为真）。于是
# 一个写错的 `TOKENHUB_BASE_URL` 被报成「探针自身异常（ImportError）」——同一个提交
# 在有代理与无代理的两台机器上给出两种结论，而「配置是否合法」本来与代理无关。


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configured",
    [
        pytest.param("", id="缺协议头"),
        pytest.param("not-a-url", id="完全不是 URL"),
        pytest.param("http://localhost:notaport", id="端口非法"),
        pytest.param("ftp://tokenhub.test/v1", id="协议不支持"),
    ],
)
async def test_model_probe_judges_url_legality_without_building_a_client(
    monkeypatch: pytest.MonkeyPatch,
    configured: str,
) -> None:
    """地址非法时，结论不依赖「能不能建出客户端」——构造一律不发生。

    判别性：把 URL 词法判断挪到客户端构造之后（即修复前的形状），本用例在宿主机
    带 socks 代理的机器上会拿到 ImportError 那条 detail，断言变红；把判断删掉同理。
    替身被调用即失败，因此这条用例同时钉住「顺序」而不只是「结论」。
    """

    def _client_must_not_be_built(**_kwargs: object) -> object:
        raise AssertionError("地址非法时不该构造 HTTP 客户端")

    import campfire.agent.model.probe as probe

    monkeypatch.setattr(probe.httpx, "AsyncClient", _client_must_not_be_built)

    report = await check_model_endpoint(Settings(tokenhub_base_url=configured, tokenhub_api_key=_TEST_API_KEY))

    assert report.configured is True
    assert report.reachable is False
    assert "不是合法 URL" in report.detail


@pytest.mark.asyncio
async def test_model_probe_reports_a_client_build_failure_as_its_own_class(monkeypatch: pytest.MonkeyPatch) -> None:
    """地址合法、但客户端因宿主机代理缺可选依赖建不出来时：单列一类，不说「不可达」。

    判别性：去掉 `except ImportError` 分支，本用例会落到通用分支，`"无法建立 HTTP 客户端"`
    不再出现（且会让运营者按「探针有 bug」去查，方向错误）。
    """

    def _socks_proxy_without_optional_dependency(**_kwargs: object) -> object:
        raise ImportError("Using SOCKS proxy, but the 'socksio' package is not installed.")

    import campfire.agent.model.probe as probe

    monkeypatch.setattr(probe.httpx, "AsyncClient", _socks_proxy_without_optional_dependency)

    report = await check_model_endpoint(_settings_with_key())

    assert report.configured is True
    assert report.reachable is False
    assert "无法建立 HTTP 客户端" in report.detail
    assert "ImportError" in report.detail
    assert "不可达" not in report.detail


# --- 模型探针的「200 不等于可达」（此前的成功路径零覆盖） ------------------
#
# 假客户端只替掉 HTTP 出口：被验证的仍是探针自己的判定逻辑。


class _FakeResponse:
    """假响应：状态码 + body（JSON 或原始文本）。"""

    def __init__(
        self, status_code: int, *, json_body: object = None, text: str = "", raises: BaseException | None = None
    ):
        self.status_code = status_code
        self._json_body = json_body
        self._text = text
        self._raises = raises

    def json(self) -> object:
        if self._raises is not None:
            raise self._raises
        return self._json_body


class _FakeClient:
    """假 httpx 客户端：上下文管理器 + 返回固定响应。"""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get(self, _url: str, **_kwargs: object) -> _FakeResponse:
        return self._response


def _patch_probe_client(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> None:
    """把探针用的 httpx.AsyncClient 换成假客户端。"""
    import campfire.agent.model.probe as probe

    monkeypatch.setattr(probe.httpx, "AsyncClient", lambda **_kwargs: _FakeClient(response))


def _settings_with_key() -> Settings:
    return Settings(tokenhub_api_key=_TEST_API_KEY)


@pytest.mark.asyncio
async def test_model_probe_reports_reachable_only_with_a_real_model_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """200 + 一份含该模型的清单 → 可达，且说清额度与并发未核实。"""
    _patch_probe_client(
        monkeypatch,
        _FakeResponse(200, json_body={"data": [{"id": "deepseek-v4.1-flash"}]}),
    )

    report = await check_model_endpoint(_settings_with_key())

    assert report.configured is True
    assert report.reachable is True
    assert "TECH-02" in report.detail


@pytest.mark.asyncio
async def test_model_probe_notes_a_missing_model_without_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    """清单里没有该模型时仍报可达，但把这件事写进 detail（id 写法未核实，不做硬判定）。"""
    _patch_probe_client(monkeypatch, _FakeResponse(200, json_body={"data": [{"id": "别的模型"}]}))

    report = await check_model_endpoint(_settings_with_key())

    assert report.reachable is True
    assert "未出现" in report.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_fragment"),
    [
        pytest.param(
            _FakeResponse(200, text="<html>502 Bad Gateway</html>", raises=ValueError()), "不是 JSON", id="HTML 错误页"
        ),
        pytest.param(
            _FakeResponse(200, json_body={"error": {"code": "invalid_api_key"}}), "不是模型清单", id="错误 body"
        ),
        pytest.param(_FakeResponse(200, json_body={"data": []}), "不是模型清单", id="空清单"),
        pytest.param(_FakeResponse(404, json_body={}), "返回 404", id="非 200"),
    ],
)
async def test_model_probe_does_not_call_every_200_reachable(
    monkeypatch: pytest.MonkeyPatch,
    response: _FakeResponse,
    expected_fragment: str,
) -> None:
    """200 也可能是代理/网关的错误页——第一版把这些全部报成「端点可达」。"""
    _patch_probe_client(monkeypatch, response)

    report = await check_model_endpoint(_settings_with_key())

    assert report.configured is True
    assert report.reachable is False
    assert expected_fragment in report.detail


@pytest.mark.asyncio
async def test_model_probe_does_not_blame_the_network_for_its_own_bug(monkeypatch: pytest.MonkeyPatch) -> None:
    """探针自身的编程错误不得被描述成「端点不可达」——那会把排查者引向网络问题。"""

    class _Boom:
        async def __aenter__(self) -> object:
            raise ValueError("bug in probe")

        async def __aexit__(self, *_exc: object) -> None:
            return None

    import campfire.agent.model.probe as probe

    monkeypatch.setattr(probe.httpx, "AsyncClient", lambda **_kwargs: _Boom())

    report = await check_model_endpoint(_settings_with_key())

    assert report.reachable is False
    assert "探针自身异常" in report.detail
    assert "不可达" not in report.detail


@pytest.mark.asyncio
async def test_model_probe_reports_transport_failures_as_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """真正的传输失败才说「不可达」。"""

    class _Failing:
        async def __aenter__(self) -> object:
            raise httpx.ConnectError("连接失败")

        async def __aexit__(self, *_exc: object) -> None:
            return None

    import campfire.agent.model.probe as probe

    monkeypatch.setattr(probe.httpx, "AsyncClient", lambda **_kwargs: _Failing())

    report = await check_model_endpoint(_settings_with_key())

    assert report.reachable is False
    assert "不可达" in report.detail
    assert "ConnectError" in report.detail
