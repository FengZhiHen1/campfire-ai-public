"""咨询面组合根的收尾契约：撤注入与关连接池的顺序、幂等、失败信号。

`aclose()` 只在进程收尾时被调用一次，顺序错误（工厂还在而网关已关）会让 `/readyz`
在重启尾部报「就绪」而每次发消息都打在已关闭的客户端上。不连库、不构造真网关。

    uv run pytest apps/api/tests/test_consult_composition_lifecycle.py
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from campfire.core.config import get_settings
from campfire.surfaces.consult import assembly, composition

pytestmark = pytest.mark.asyncio


class _FakeGateway:
    """网关替身：`install` 读的两个属性 + 可观察的 `aclose`（`binding` 从不被取用）。"""

    model_name = "fake-gateway"
    binding = object()

    def __init__(self, *, fail_close: bool = False) -> None:
        """`fail_close` 让关闭抛错，用来验证收尾不会因此中断。"""
        self.close_calls = 0
        self._fail_close = fail_close
        #: 关闭那一刻「注入点是否还在」——收尾顺序的唯一可观测证据。
        self.wired_at_close: bool | None = None

    async def aclose(self) -> None:
        """记录关闭次数、关闭前的注入状态，并按需失败。"""
        self.close_calls += 1
        self.wired_at_close = assembly.runner_is_wired()
        if self._fail_close:
            raise RuntimeError("网关关闭失败（替身）")


@pytest.fixture(autouse=True)
def _isolated_assembly() -> Iterator[None]:
    """注入点是模块级全局：前后各清一次，避免用例之间互相看到对方的装配。"""
    composition.reset()
    try:
        yield
    finally:
        composition.reset()


async def test_aclose_withdraws_the_runner_before_closing_the_pool() -> None:
    """撤注入必须早于关连接池——否则「已关网关 + 仍报就绪」的窗口真实存在。

    判别性：把 `aclose` 改回「只关网关、不清注入」（原实现），`wired_at_close` 会是
    `True`，第一条断言变红。
    """
    gateway = _FakeGateway()
    composition.install(get_settings(), gateway=gateway)  # type: ignore[arg-type]  # 替身只提供 install 读的两个属性与 aclose
    assert assembly.runner_is_wired() is True

    await composition.aclose()

    assert gateway.wired_at_close is False, "关连接池时运行器工厂还在注入点上"
    assert assembly.runner_is_wired() is False
    assert gateway.close_calls == 1


async def test_aclose_is_idempotent() -> None:
    """重复调用不会再关一次。"""
    gateway = _FakeGateway()
    composition.install(get_settings(), gateway=gateway)  # type: ignore[arg-type]  # 同上

    await composition.aclose()
    await composition.aclose()

    assert gateway.close_calls == 1


async def test_aclose_reports_a_close_failure_after_clearing() -> None:
    """关闭失败要把信号抛出（调用方的 AsyncExitStack 保证后续释放照跑），但不留残留状态。

    判别性：改成「吞掉异常」时第一条断言失败；不清注入 / 不置空 `_gateway` 时后两条失败
    ——半关的网关会被后续请求取到，而第二次收尾会再关一次。
    """
    gateway = _FakeGateway(fail_close=True)
    composition.install(get_settings(), gateway=gateway)  # type: ignore[arg-type]  # 同上

    with pytest.raises(RuntimeError):
        await composition.aclose()
    await composition.aclose()  # 已清空：空操作，不再抛也不再关

    assert assembly.runner_is_wired() is False
    assert gateway.close_calls == 1


async def test_aclose_without_assembly_is_a_noop() -> None:
    """未装配时是空操作（`install` 抛错的进程也能干净收尾）。"""
    await composition.aclose()

    assert assembly.runner_is_wired() is False
