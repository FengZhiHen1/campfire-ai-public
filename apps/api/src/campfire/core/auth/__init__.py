"""认证（SuperTokens）的跨切能力。

归属（见 docs/项目结构设计.md 第 6 节）：会话的建立与撤销；
账号的注册、邀请码、人工重置等用例服务归 ``modules/accounts``。

已核实的形状（见 docs/技术栈设计.md 第 2 节）：core 是独立 Java HTTP 服务，
**会话校验在 Python SDK 内完成、不经过 core**；core 只在注册、登录、重置、
刷新时被调用；用户数据 100% 在自己的 PostgreSQL。

因此本模块当前只有 core 可达性探测；正式的 SDK 装配随 accounts 用例落地，
不在此处预先发明会话端口形状。
"""

import httpx

from campfire.core.config import Settings
from campfire.core.health import ComponentHealth, Status


def core_hello_url(settings: Settings) -> str:
    """返回 core 的 ``/hello`` 地址。

    单独抽出来是为了可测：URI 配置为空或非法时，httpx 抛的是
    ``InvalidURL``（配置问题），必须与「连不上」（网络问题）区分开。
    """
    return f"{settings.supertokens_connection_uri.rstrip('/')}/hello"


async def check_auth_core(settings: Settings) -> ComponentHealth:
    """探测 SuperTokens core 是否可达（``GET /hello``）。

    **刻意 ``trust_env=False``**：core 是内网/同机服务，它的可达性不该由宿主机的
    代理策略决定。实测踩到过：宿主机 ``NO_PROXY`` 含 IPv6 字面量（``[::1]``）时，
    httpx 解析代理豁免列表会抛 ``InvalidURL: Invalid port``，于是探针把一个纯
    环境问题报成「core 不可达」。

    失败时只回报异常类型，不复述连接串与凭据。
    """
    url = core_hello_url(settings)
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            response = await client.get(url)
    except (httpx.InvalidURL, httpx.UnsupportedProtocol):
        # 配置问题，不是可达性问题：报错文案不能让排查者去查网络。
        # 实测两类都要覆盖：坏端口抛 InvalidURL，缺协议头/错协议抛 UnsupportedProtocol。
        return ComponentHealth(
            "auth",
            Status.UNAVAILABLE,
            "SUPERTOKENS_CONNECTION_URI 不是合法的 http(s) 地址",
        )
    except Exception as exc:  # noqa: BLE001 —— 探针吞掉一切网络异常并如实上报
        return ComponentHealth("auth", Status.UNAVAILABLE, f"core 不可达（{type(exc).__name__}）")

    if response.status_code != 200:
        return ComponentHealth("auth", Status.UNAVAILABLE, f"core 返回 {response.status_code}")
    return ComponentHealth("auth", Status.OK, "core 可达")
