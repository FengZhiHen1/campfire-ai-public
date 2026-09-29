"""测试会话级夹具。

## 为什么要有这个夹具（这不是「顺手加的」）

实测：宿主机 ``no_proxy`` 含**带方括号的 IPv6 字面量**（本机为
``127.0.0.1,localhost,::1,[::1]``）时，URL 解析在**构造客户端**时就抛
``InvalidURL: Invalid port: ':1]'``——它把 ``[::1]`` 当成 ``host:port`` 去解析。
本机实测三个都失败：``httpx.AsyncClient()``、``httpx2.AsyncClient()``、
``openai.AsyncOpenAI(...)``（注意 ``openai`` 用的是 **httpx2**，与 httpx 0.28.1 是两个独立包、
``InvalidURL`` 互不为子类）。这与被测代码无关，却会让任何构造客户端的测试整片失败
（实测 17 个用例同时报同一个错），并让「失败原因」看起来像被测代码的问题。

⚠️ 归因差异留档：另一位审查者在自己的环境里测得「裸 ``httpx.AsyncClient`` 构造成功、
只有 ``AsyncOpenAI`` 失败」。本机复测**不成立**（两者都失败），差异可能来自环境变量大小写或
版本；夹具的必要性在两种说法下都成立，故保留，措辞以本机实测为准。

因此这里把 ``no_proxy`` 归一到合法值，让测试结果**不依赖宿主机的代理配置**。
生产代码保留 ``trust_env``（企业网络可能需代理），并把这个环境问题转成可操作的
配置错误——见 ``campfire.agent.model.gateway`` 的模块 docstring。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import suppress

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

#: 「连不上 FalkorDB 容器」这一类异常。
#:
#: **实测踩坑（2026-09-29）**：`redis.exceptions.ConnectionError` **不是**内建
#: `ConnectionError`/`OSError` 的子类——它继承 `RedisError` → `Exception`。
#: 只按内建类型捕获会**匹配不到**，容器不可用时用例会变成 ERROR 而不是安静跳过。
FALKOR_UNAVAILABLE_ERRORS: tuple[type[BaseException], ...] = (
    RedisConnectionError,
    ConnectionError,
    ConnectionRefusedError,
    ConnectionResetError,
    TimeoutError,
    OSError,
)


@pytest.fixture(autouse=True)
def _normalise_proxy_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """把代理相关的环境变量归一到合法值，隔离宿主机配置对测试的影响。"""
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    yield


def connect_falkordb_or_skip():  # noqa: ANN202 —— 返回 FalkorDriver；避免在 conftest 顶部导入上游
    """连上本地 FalkorDB 并返回驱动；**容器不可用时跳过**。

    这个辅助函数存在的原因是一次实测踩坑：``FalkorDB(...)`` 的**构造函数本身就发
    网络 I/O**（指向死端口时构造期即抛 ``ConnectionError``），所以构造必须在 ``try``
    内。此前三个测试文件都把构造写在 ``try`` 之外，容器不可用时它们全部变成
    ERROR（实测某个文件 22 个用例全 ERROR、耗时约 99 秒），而 docstring 却宣称
    「容器不可用则跳过」——宣称与行为不符。

    异常类型同样踩过坑：``redis.exceptions.ConnectionError`` 不是内建
    ``ConnectionError`` 的子类，故用 :data:`FALKOR_UNAVAILABLE_ERRORS` 同时覆盖两者。

    Returns:
        ``(driver, client)``：已连上的驱动与底层客户端（调用方负责关闭客户端）。

    Raises:
        pytest.skip.Exception: 容器不可用（通过 ``pytest.skip`` 抛出）。
    """
    from falkordb.asyncio import FalkorDB
    from graphiti_core.driver.falkordb_driver import FalkorDriver

    client = None
    try:
        client = FalkorDB(host="localhost", port=6380)
        driver = FalkorDriver(falkor_db=client, database="campfire")
        return driver, client
    except FALKOR_UNAVAILABLE_ERRORS as exc:
        if client is not None:
            with suppress(Exception):
                client.aclose()
        pytest.skip(f"FalkorDB 不可用（{type(exc).__name__}）——先 docker compose up -d falkordb")
    except Exception:
        if client is not None:
            with suppress(Exception):
                client.aclose()
        raise
