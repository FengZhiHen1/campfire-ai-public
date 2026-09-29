"""测试会话级夹具。

## 为什么要有这个夹具（这不是「顺手加的」）

实测：宿主机 ``no_proxy`` 含**带方括号的 IPv6 字面量**（本机为
``127.0.0.1,localhost,::1,[::1]``）时，httpx 0.28.1 在**构造客户端**时就抛
``InvalidURL: Invalid port: ':1]'``——它把 ``[::1]`` 当成 ``host:port`` 去解析。
这与被测代码无关，却会让任何构造 httpx/openai 客户端的测试整片失败（实测 17 个用例
同时报同一个错），并让「失败原因」看起来像被测代码的问题。

因此这里把 ``no_proxy`` 归一到合法值，让测试结果**不依赖宿主机的代理配置**。
生产代码保留 ``trust_env``（企业网络可能需代理），并把这个环境问题转成可操作的
配置错误——见 ``campfire.agent.model.gateway`` 的模块 docstring。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _normalise_proxy_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """把代理相关的环境变量归一到合法值，隔离宿主机配置对测试的影响。"""
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    yield
