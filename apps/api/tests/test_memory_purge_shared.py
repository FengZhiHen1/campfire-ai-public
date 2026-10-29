"""单元测试：注销删图前收口**本进程共享句柄**为该账号派生的索引任务（纯替身）。

对应 2026-10-29 终审的缺口：`MemoryAccountPurger` 用一次性句柄删图，够不到进程共享
句柄里该账号缓存/临时 clone 的驱动，那些驱动的建索引任务会在 `GRAPH.DELETE` 之后继续跑。
修复后删图前借道**已存在**的同源共享句柄收口；收口失败即中止本次删图（fail-closed：
在途 `CREATE INDEX` 与删除并发会放大竞态，而注销本就可重试，不得虚报「已清理」）。

不连图库与数据库、不调模型：共享句柄与一次性句柄都是替身，账本删除单独打桩（真账本
由 `test_memory_purge_integration.py` 在真实库上覆盖）。跨进程协调与「已在途的写」不在
本文件的承诺范围内。
"""

from __future__ import annotations

import asyncio
from typing import cast

import pytest
from redis.exceptions import ResponseError

from campfire.core.config import Settings
from campfire.modules.memory import graph as graph_module
from campfire.modules.memory import purge as purge_module
from campfire.modules.memory.graph import MemoryGraph
from campfire.modules.memory.identity import AccountIdError
from campfire.modules.memory.purge import MemoryAccountPurger

#: 测试用账号（合法字符集，且不命中任何真实账号命名空间的前缀）。
_ACCOUNT = "it_mem_purge_shared_target"
#: 假连接串：只用于构造配置，不发起任何连接。
_FAKE_DATABASE_URL = "postgresql+asyncpg://tester:secret@127.0.0.1:5432/campfire_purge_unit"


def _settings(**overrides: object) -> Settings:
    """不读 `.env` 的配置：连接字段显式钉住，避免宿主机配置影响同源判定。"""
    base: dict[str, object] = {
        "database_url": _FAKE_DATABASE_URL,
        "falkordb_host": "127.0.0.1",
        "falkordb_port": 6381,
        "falkordb_database": "campfire_purge_unit",
        "falkordb_password": None,
    }
    base.update(overrides)
    # arg-type：`**base` 展开静态不收敛；call-arg：`_env_file` 不在 Settings 的合成签名里。
    return Settings(_env_file=None, **base)  # type: ignore[arg-type,call-arg]


class _FakeClient:
    """`driver.client` 替身：只实现 `select_graph(name).delete()`。"""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.selected: str | None = None
        self.error: Exception | None = None

    def select_graph(self, name: str) -> _FakeGraphHandle:
        """记下被删的图名（删错图必须可见）。"""
        self.selected = name
        return _FakeGraphHandle(self)


class _FakeGraphHandle:
    """`GRAPH.DELETE` 替身。"""

    def __init__(self, client: _FakeClient) -> None:
        self._client = client

    async def delete(self) -> None:
        """记录一次删除（不连任何实例）。"""
        if self._client.error is not None:
            raise self._client.error
        self._client.events.append(f"delete:{self._client.selected}")


class _FakeDriver:
    """驱动替身：`_drop_graph` 只读它的 `client`。"""

    def __init__(self, client: _FakeClient) -> None:
        self.client = client


class _TemporaryGraph:
    """注销自建的一次性句柄替身（`build_memory_graph` 的返回值）。"""

    def __init__(self, events: list[str], error: Exception | None = None) -> None:
        self.events = events
        self.driver = _FakeDriver(_FakeClient(events))
        self.driver.client.error = error

    async def aclose(self) -> None:
        """记录收尾（一次性句柄必须被关）。"""
        self.events.append("close-temporary")


class _TemporaryFactory:
    """一次性句柄的构造函数替身：记录「有没有被构造」（收口失败时不得构造）。"""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.graph: _TemporaryGraph | None = None
        self.error: Exception | None = None

    def __call__(self, *_args: object, **_kwargs: object) -> _TemporaryGraph:
        """构造并记录。"""
        self.events.append("build-temporary")
        self.graph = _TemporaryGraph(self.events, self.error)
        return self.graph


class _SharedHandle:
    """进程共享句柄替身：只实现 `release_account_driver` 与 `aclose`（后者不应被调用）。"""

    def __init__(
        self,
        events: list[str],
        *,
        result: bool = True,
        error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.result = result
        self.error = error

    async def release_account_driver(self, account_id: str) -> bool:
        """记录收口调用；可按用例抛错（含取消）。"""
        self.events.append(f"release:{account_id}")
        if self.error is not None:
            raise self.error
        return self.result

    async def aclose(self) -> None:
        """共享句柄的收尾不归注销管（被调用即记录，供断言用）。"""
        self.events.append("close-shared")


async def _no_ledger(self: MemoryAccountPurger, account_id: str) -> int:
    """账本删除打桩（真实账本由集成用例覆盖，这里不连关系库）。"""
    return 0


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    events: list[str],
    settings: Settings,
    shared: _SharedHandle | None,
    shared_origin: graph_module.SharedGraphOrigin | None = None,
) -> _TemporaryFactory:
    """装配替身：共享句柄（可缺）+ 一次性句柄工厂 + 账本打桩。"""
    factory = _TemporaryFactory(events)
    monkeypatch.setattr(graph_module, "_shared_graph", cast(MemoryGraph, shared) if shared is not None else None)
    monkeypatch.setattr(
        graph_module,
        "_shared_graph_origin",
        shared_origin if shared_origin is not None else graph_module._origin_of(settings),
    )
    monkeypatch.setattr(purge_module, "build_memory_graph", factory)
    monkeypatch.setattr(MemoryAccountPurger, "_delete_ledger_rows", _no_ledger)
    return factory


@pytest.mark.asyncio
async def test_purge_releases_the_shared_handle_before_deleting_the_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """顺序必须是「先收口共享句柄的派生驱动、再建句柄删图」，且不关共享句柄。"""
    settings = _settings()
    events: list[str] = []
    shared = _SharedHandle(events)
    _install(monkeypatch, events=events, settings=settings, shared=shared)

    outcome = await MemoryAccountPurger(settings).purge_account(_ACCOUNT)

    assert events == [f"release:{_ACCOUNT}", "build-temporary", f"delete:{_ACCOUNT}", "close-temporary"], (
        f"删图前没有先收口共享句柄（或收尾顺序不对）：{events}"
    )
    assert "已收口该账号的派生驱动" in outcome.detail, outcome.detail
    assert "已丢弃图" in outcome.detail, outcome.detail
    assert "close-shared" not in events, "注销把共享句柄关掉了——其它账号的连接会被一并打断"


@pytest.mark.asyncio
async def test_purge_does_not_build_a_shared_handle_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """本进程没有共享句柄时不新建（为一次注销常驻一整套连接池是反向优化）。"""
    settings = _settings()
    events: list[str] = []
    _install(monkeypatch, events=events, settings=settings, shared=None)

    def _forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("为收口新建了共享实例")

    monkeypatch.setattr(graph_module, "build_memory_graph", _forbidden)

    outcome = await MemoryAccountPurger(settings).purge_account(_ACCOUNT)

    assert events == ["build-temporary", f"delete:{_ACCOUNT}", "close-temporary"], events
    assert graph_module._shared_graph is None
    assert "本进程无同源共享句柄（未新建）" in outcome.detail, outcome.detail


@pytest.mark.asyncio
async def test_purge_skips_a_shared_handle_from_another_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """共享句柄指向另一实例（端口不同）时不碰它：否则会取消另一实例上同名账号的任务。"""
    settings = _settings()
    events: list[str] = []
    shared = _SharedHandle(events)
    other = graph_module.SharedGraphOrigin(
        host=settings.falkordb_host,
        port=settings.falkordb_port + 1,
        database=settings.falkordb_database,
        password_configured=False,
    )
    _install(monkeypatch, events=events, settings=settings, shared=shared, shared_origin=other)

    outcome = await MemoryAccountPurger(settings).purge_account(_ACCOUNT)

    assert f"release:{_ACCOUNT}" not in events, "不同源的共享句柄被动了"
    assert f"delete:{_ACCOUNT}" in events, "不同源不该影响删图本身"
    assert "本进程无同源共享句柄（未新建）" in outcome.detail, outcome.detail


@pytest.mark.asyncio
async def test_release_failure_blocks_the_delete_before_any_graph_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """收口失败即中止本次删图：不建句柄、不发 `GRAPH.DELETE`，异常原样上抛。

    fail-closed 的理由：索引任务仍在跑时删图会与在途 `CREATE INDEX` 并发（本轮 signal 11
    事故的形态），而注销可重试——报错好过虚报「已清理」。异常必须是**同一个对象**：
    重新包装或拼进 detail 都会把驱动层的端点细节带进回执。
    """
    settings = _settings()
    events: list[str] = []
    failure = RuntimeError("收口失败（合成）：127.0.0.1:6381 不可达")
    shared = _SharedHandle(events, error=failure)
    _install(monkeypatch, events=events, settings=settings, shared=shared)

    with pytest.raises(RuntimeError) as caught:
        await MemoryAccountPurger(settings).purge_account(_ACCOUNT)

    assert caught.value is failure, f"异常被重新包装了：{caught.value!r}"
    assert str(caught.value) == str(failure), "异常消息被改写过（可能夹带了底层端点细节）"
    assert events == [f"release:{_ACCOUNT}"], f"收口失败后仍继续建句柄/删图：{events}"


@pytest.mark.asyncio
async def test_release_cancellation_propagates_without_deleting(monkeypatch: pytest.MonkeyPatch) -> None:
    """取消同样必须向上传播：收口被取消时不得继续删图（也不得吞成普通异常）。"""
    settings = _settings()
    events: list[str] = []
    shared = _SharedHandle(events, error=asyncio.CancelledError())
    _install(monkeypatch, events=events, settings=settings, shared=shared)

    with pytest.raises(asyncio.CancelledError):
        await MemoryAccountPurger(settings).purge_account(_ACCOUNT)

    assert events == [f"release:{_ACCOUNT}"], f"取消之后仍继续建句柄/删图：{events}"


@pytest.mark.asyncio
async def test_purge_keeps_the_release_clause_when_the_graph_is_already_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """「无图可丢弃」是成功路径：它同样要带上收口结论，不能被提前 return 吞掉。"""
    settings = _settings()
    events: list[str] = []
    shared = _SharedHandle(events, result=False)
    factory = _install(monkeypatch, events=events, settings=settings, shared=shared)
    factory.error = ResponseError("Invalid graph operation on empty key")

    outcome = await MemoryAccountPurger(settings).purge_account(_ACCOUNT)

    assert "无图可丢弃" in outcome.detail, outcome.detail
    assert "共享句柄无该账号的派生驱动" in outcome.detail, outcome.detail
    assert f"release:{_ACCOUNT}" in events


@pytest.mark.asyncio
async def test_purge_validates_the_account_before_touching_the_shared_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """畸形账号必须在动共享句柄之前被拒（否则 `_` 之类的键会成为被收口的图名）。"""
    settings = _settings()
    events: list[str] = []
    shared = _SharedHandle(events)
    _install(monkeypatch, events=events, settings=settings, shared=shared)

    with pytest.raises(AccountIdError):
        await MemoryAccountPurger(settings).purge_account("bad\nname")

    assert events == [], f"入口校验之前就动了共享句柄：{events}"
