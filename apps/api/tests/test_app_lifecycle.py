"""入口生命周期回归：在途运行退出后才关闭资源，异常退出仍完整收尾。"""

from __future__ import annotations

import asyncio

import pytest
from taskiq import TaskiqState

from campfire import main, worker


@pytest.fixture
def lifecycle_events(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    events: list[str] = []
    for name in ("init_supertokens", "set_authorizer", "set_dispatch_hook", "get_cache"):
        monkeypatch.setattr(main, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(main.consult_composition, "install", lambda *args: None)

    def cancel() -> None:
        events.append("cancel")

    async def drain() -> None:
        events.append("drain")

    async def gateway() -> None:
        events.append("gateway")

    async def memory() -> None:
        events.append("memory")

    async def cache() -> None:
        events.append("cache")

    async def database() -> None:
        events.append("database")

    monkeypatch.setattr(main, "cancel_pumps", cancel)
    monkeypatch.setattr(main, "drain_pumps", drain, raising=False)
    monkeypatch.setattr(main.consult_composition, "aclose", gateway)
    monkeypatch.setattr(main, "aclose_shared_memory_graph", memory, raising=False)
    monkeypatch.setattr(main, "close_cache", cache)
    monkeypatch.setattr(main, "dispose_engine", database)
    return events


@pytest.mark.asyncio
@pytest.mark.parametrize("body_fails", [False, True])
async def test_api_releases_resources_even_when_lifespan_body_fails(
    lifecycle_events: list[str], body_fails: bool
) -> None:
    if body_fails:
        with pytest.raises(RuntimeError, match="body failed"):
            async with main.lifespan(main.app):
                raise RuntimeError("body failed")
    else:
        async with main.lifespan(main.app):
            pass
    assert lifecycle_events == ["cancel", "drain", "gateway", "memory", "cache", "database"]


@pytest.mark.asyncio
async def test_api_waits_for_cancelled_run_before_closing_its_dependencies(
    monkeypatch: pytest.MonkeyPatch, lifecycle_events: list[str]
) -> None:
    started = asyncio.Event()
    settled = asyncio.Event()

    async def running() -> None:
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            lifecycle_events.append("run-settled")
            settled.set()

    task = asyncio.create_task(running())
    await started.wait()

    def cancel() -> None:
        task.cancel()

    async def drain() -> None:
        await asyncio.gather(task, return_exceptions=True)

    async def gateway() -> None:
        assert settled.is_set(), "后台运行仍在收尾时关闭了模型网关"
        lifecycle_events.append("gateway")

    monkeypatch.setattr(main, "cancel_pumps", cancel)
    monkeypatch.setattr(main, "drain_pumps", drain, raising=False)
    monkeypatch.setattr(main.consult_composition, "aclose", gateway)
    try:
        async with main.lifespan(main.app):
            pass
        assert lifecycle_events == ["run-settled", "gateway", "memory", "cache", "database"]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failing", ["drain_pumps", "gateway", "aclose_shared_memory_graph", "close_cache"])
async def test_api_cleanup_failure_does_not_leave_later_connections_open(
    monkeypatch: pytest.MonkeyPatch, lifecycle_events: list[str], failing: str
) -> None:
    async def fail() -> None:
        raise RuntimeError("close failed")

    if failing == "gateway":
        monkeypatch.setattr(main.consult_composition, "aclose", fail)
    else:
        monkeypatch.setattr(main, failing, fail)
    with pytest.raises(RuntimeError, match="close failed"):
        async with main.lifespan(main.app):
            pass
    assert lifecycle_events[-1] == "database"


@pytest.mark.asyncio
@pytest.mark.parametrize("sweep_fails", [False, True])
async def test_worker_stops_sweep_before_closing_resources(monkeypatch: pytest.MonkeyPatch, sweep_fails: bool) -> None:
    events: list[str] = []
    started = asyncio.Event()

    async def sweep() -> None:
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            events.append("sweep-settled")
            if sweep_fails:
                raise RuntimeError("sweep failed")

    async def memory() -> None:
        assert events == ["sweep-settled"]
        events.append("memory")

    async def cache() -> None:
        events.append("cache")

    async def database() -> None:
        events.append("database")

    task = asyncio.create_task(sweep())
    await started.wait()
    monkeypatch.setattr(worker, "_sweep_task", task)
    monkeypatch.setattr(worker, "aclose_shared_memory_graph", memory, raising=False)
    monkeypatch.setattr(worker, "close_cache", cache, raising=False)
    monkeypatch.setattr(worker, "dispose_engine", database, raising=False)
    stopping = worker._stop_sweep(TaskiqState())
    assert stopping is not None
    if sweep_fails:
        with pytest.raises(RuntimeError, match="sweep failed"):
            await stopping
    else:
        await stopping
    assert events == ["sweep-settled", "memory", "cache", "database"]
    assert worker._sweep_task is None
