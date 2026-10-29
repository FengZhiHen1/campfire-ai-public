"""运行传输层的**时序**用例：互斥键的归属与「取消不得打断收尾」。

这一层的行为不靠「读代码看出来」，而靠可复现的时序：本文件用一个受控时序的内存替身
（:class:`GatedCache`）把「这一毫秒发生了什么」写死在用例里——哪个操作停住、谁在停住
期间动了同一个键、放行之后谁的结果是什么。真实的竞态窗口只有微秒级，靠 sleep 撞不出来；
把操作本身当闸门才能确定性复现。

被判别的四个事实：

1. 会话互斥键的**释放**不得删掉别人的键（比对与删除必须是一条命令）；
2. 会话互斥键的**换手**（租约令牌 → `run_id`）不得覆盖别人的键；
3. 取消**不得**打断收尾：重复取消、或收尾期间的取消，会让元数据停在 `running`、
   会话位不释放——使用者最长 `RUN_MUTEX_TTL_SECONDS` 秒内每次发消息都吃 409；
4. 收尾的两笔写，状态必须先于位子落定（取消端点靠它判断「还在跑」）。

前三条各有一条判别性用例：把对应的旧实现放回去，那条用例立刻变红（见各用例 docstring）。

    uv run pytest apps/api/tests/test_consult_runbus_races.py
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from campfire.agent.runtime import (
    RunEvent,
    RunFinishedEvent,
    RunRequest,
    RunStartedEvent,
    RunUsage,
    TextDeltaEvent,
)
from campfire.core.cache import RedisCache
from campfire.surfaces.consult.runbus import (
    RUN_MUTEX_TTL_SECONDS,
    RUN_STATUS_FINISHED,
    RunPump,
    bind_lease_run_id,
    claim_session_run,
    drain_pumps,
    events_key,
    meta_key,
    mutex_key,
    read_run_meta,
    release_session_run,
    request_cancel,
    start_pump,
)

pytestmark = pytest.mark.asyncio

_SESSION = "s-race"
_ACCOUNT = "a-race"


# ---------------------------------------------------------------------------
# 受控时序替身
# ---------------------------------------------------------------------------

#: 「会改变键的值」的操作名。闸门挂在这一组上是有意的：两种实现都以**一次变更操作收尾**
#: （旧实现是 `delete` / `set`，新实现是 `compare_and_delete` / `compare_and_set`），
#: 因此把闸门放在变更**落地之前**，「比对已经做完、变更还没落地」这个窗口对两种实现都是
#: 同一个语义位置——用例因此不依赖具体实现，只依赖契约。
_MUTATIONS = frozenset({"delete", "set", "compare_and_delete", "compare_and_set"})


@dataclass
class _Gate:
    """一次「停在这里」：`arrived` 供用例等待，`release` 由用例放行。"""

    arrived: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)


class GatedCache(RedisCache):
    """内存版缓存替身：语义与真实实现一致，另可让**指定的那一次操作**停在原地。

    构造时的连接串只是占位：`ConnectionPool.from_url` 只装配参数，第一条命令才建连，
    而本替身一条命令都不发。每个原语都在进入时记一条 `(操作名, 键)` 到 :attr:`ops`，
    供「顺序也是契约」的断言使用。闸门是**一次性**的：命中一次之后自动摘掉。
    """

    def __init__(self) -> None:
        """建一个空的内存库（不连 Redis）。"""
        super().__init__("redis://127.0.0.1:1/0")
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.ttls: dict[str, int] = {}
        self.ops: list[tuple[str, str]] = []
        self._gates: dict[tuple[str, str], _Gate] = {}

    # --- 闸门 ---

    def pause_before_mutation(self, key: str) -> _Gate:
        """让下一次「改变该键的值」的操作停在落地之前，返回它的闸门。"""
        gate = _Gate()
        for name in _MUTATIONS:
            self._gates[(name, key)] = gate
        return gate

    async def _arrive(self, op: str, key: str) -> None:
        """登记一次操作；若该操作被要求停住，则停到用例放行为止。"""
        self.ops.append((op, key))
        gate = self._gates.pop((op, key), None)
        if gate is None:
            return
        gate.arrived.set()
        await gate.release.wait()

    # --- 原语（与 RedisCache 同签名）---

    async def get(self, key: str) -> str | None:
        """取值。"""
        await self._arrive("get", key)
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        """置值并设过期。"""
        await self._arrive("set", key)
        self.values[key] = value
        self.ttls[key] = ttl_seconds

    async def setnx(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        """只在键不存在时置值。"""
        await self._arrive("setnx", key)
        if key in self.values:
            return False
        self.values[key] = value
        self.ttls[key] = ttl_seconds
        return True

    async def compare_and_delete(self, key: str, expected: str) -> bool:
        """值仍是 `expected` 时删除（真实实现是一条 Lua 命令，这里在内存里同样不可分割）。"""
        await self._arrive("compare_and_delete", key)
        if self.values.get(key) != expected:
            return False
        del self.values[key]
        self.ttls.pop(key, None)
        return True

    async def compare_and_set(self, key: str, expected: str, value: str, *, ttl_seconds: int) -> bool:
        """值仍是 `expected` 时换值并续期（同上）。"""
        await self._arrive("compare_and_set", key)
        if self.values.get(key) != expected:
            return False
        self.values[key] = value
        self.ttls[key] = ttl_seconds
        return True

    async def rpush(self, key: str, *values: str, ttl_seconds: int) -> None:
        """追加到列表尾并续期。"""
        await self._arrive("rpush", key)
        self.lists.setdefault(key, []).extend(values)
        self.ttls[key] = ttl_seconds

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        """读列表区间（`stop=-1` 表示到末尾）。"""
        await self._arrive("lrange", key)
        items = self.lists.get(key, [])
        return items[start:] if stop == -1 else items[start : stop + 1]

    async def expire(self, key: str, ttl_seconds: int) -> bool:
        """续期；键不存在时返回 `False`。"""
        await self._arrive("expire", key)
        if key not in self.values and key not in self.lists:
            return False
        self.ttls[key] = ttl_seconds
        return True

    async def delete(self, *keys: str) -> int:
        """无条件删除（用例里模拟「键到期」时用它，不经比对）。"""
        removed = 0
        for key in keys:
            await self._arrive("delete", key)
            if key in self.values:
                del self.values[key]
                self.ttls.pop(key, None)
                removed += 1
        return removed

    async def exists(self, key: str) -> bool:
        """键是否存在（列表也算）。"""
        await self._arrive("exists", key)
        return key in self.values or key in self.lists


class GatedRunner:
    """脚本化运行器：起步事件 → 停在闸门上 → 一段正文 → 终态。

    `gate` 由用例控制：把「运行中」这个状态按住，取消才会落在推进任务的 `await` 上。
    """

    #: 本条运行的身份（基座在生成器内部生成，替身取固定值即可）。
    RUN_ID = "run-race-0123456789abcdef"

    def __init__(self, *, gate: asyncio.Event) -> None:
        """绑定「运行中」闸门。"""
        self._gate = gate

    def run(self, request: RunRequest) -> AsyncIterator[RunEvent]:
        """返回一次运行的事件生成器（与 `AgentRunner.run` 同形）。"""
        return self._generate(request)

    async def _generate(self, request: RunRequest) -> AsyncIterator[RunEvent]:
        """脚本本体。"""
        yield RunStartedEvent(
            run_id=self.RUN_ID,
            session_id=request.session_id,
            surface=request.surface,
            model="gated",
            activated_skills=(),
            injection_sources=(),
            appended_messages=1,
        )
        await self._gate.wait()
        yield TextDeltaEvent(delta="正文")
        yield RunFinishedEvent(reason="completed", citations=(), usage=RunUsage(), elapsed_seconds=0.01)


def _request() -> RunRequest:
    """一个最小的运行请求（本文件的用例只看传输层，不看注入内容）。"""
    return RunRequest(session_id=_SESSION, surface="consult", instructions="测试用静态提示", user_input="你好")


async def _start_gated_run(cache: GatedCache) -> tuple[RunPump, asyncio.Task[None], asyncio.Event]:
    """起一次停在「运行中」的运行，返回（推进器、任务、运行中闸门）。"""
    lease = await claim_session_run(cache, session_id=_SESSION)
    assert lease is not None
    gate = asyncio.Event()
    pump = RunPump(
        cache=cache,
        runner=GatedRunner(gate=gate),  # type: ignore[arg-type]  # 替身只实现 run()
        request=_request(),
        account_id=_ACCOUNT,
        lease=lease,
    )
    await pump.begin()
    task = start_pump(pump)
    # 让推进任务真的跑到「运行中」的闸门上：否则取消会落在任务的第一步行之前，
    # 那时推进器还没开始，收尾自然不会发生——测的就不是本文件要测的东西了。
    for _ in range(3):
        await asyncio.sleep(0)
    assert not task.done(), "推进任务应当停在运行中的闸门上"
    assert all("text_delta" not in frame for frame in _frames(cache, GatedRunner.RUN_ID)), "此时不该有正文"
    return pump, task, gate


def _frames(cache: GatedCache, run_id: str) -> list[str]:
    """缓冲里已有的帧原文（只用来判「正文到没到」，不解析）。"""
    return list(cache.lists.get(events_key(run_id), []))


# ---------------------------------------------------------------------------
# 1 释放会话位：不得删掉别人的键
# ---------------------------------------------------------------------------


async def test_release_never_deletes_a_lock_that_changed_hands() -> None:
    """比对期间键易手时，释放必须**不删**——删掉的会是新持有者的位子。

    时序（全部由闸门钉死）：本运行的比对已经做完 → 键在这期间到期并被另一个运行
    `setnx` 占走 → 本运行的删除才落地。

    判别性：把 `release_session_run` 换回「`GET` 比对通过后 `DEL`」，最后一条断言
    立刻变红（新持有者的键被删 ⇒ 那个会话上会出现两个并行运行）。
    """
    cache = GatedCache()
    lease = await claim_session_run(cache, session_id=_SESSION)
    assert lease is not None

    gate = cache.pause_before_mutation(mutex_key(_SESSION))
    releaser = asyncio.create_task(release_session_run(cache, lease))
    await gate.arrived.wait()

    # 键在「比对之后、删除之前」到期，另一个运行把它占走
    del cache.values[mutex_key(_SESSION)]
    other = await claim_session_run(cache, session_id=_SESSION)
    assert other is not None

    gate.release.set()
    await releaser

    assert await cache.get(mutex_key(_SESSION)) == other.token, "释放删掉了新持有者的键"


# ---------------------------------------------------------------------------
# 2 换手（令牌 → run_id）：不得覆盖别人的键
# ---------------------------------------------------------------------------


async def test_bind_never_overwrites_a_lock_that_changed_hands() -> None:
    """比对期间键易手时，换手必须**不写**，且本次租约不得声称自己拿到了 `run_id`。

    时序：比对已做完 → 键到期并被另一个运行占走 → 本运行的写入才落地。

    判别性：把 `bind_lease_run_id` 换回「`GET` 比对通过后 `SET`」，第一条断言变红
    （对方的令牌被覆盖成本次的 `run_id`，对方此后再也删不掉自己的键）。
    """
    cache = GatedCache()
    lease = await claim_session_run(cache, session_id=_SESSION)
    assert lease is not None

    gate = cache.pause_before_mutation(mutex_key(_SESSION))
    binder = asyncio.create_task(bind_lease_run_id(cache, lease, "run-A"))
    await gate.arrived.wait()

    del cache.values[mutex_key(_SESSION)]
    other = await claim_session_run(cache, session_id=_SESSION)
    assert other is not None

    gate.release.set()
    await binder

    assert await cache.get(mutex_key(_SESSION)) == other.token, "换手覆盖了新持有者的键"
    assert lease.run_id is None, "没换成手就不该声称自己握着那个位子"


async def test_bind_refreshes_the_mutex_ttl() -> None:
    """换手成功时把 TTL 重新拉满：否则一个起步慢的运行会在自己的上限之前先放锁。"""
    cache = GatedCache()
    lease = await claim_session_run(cache, session_id=_SESSION)
    assert lease is not None
    cache.ttls[mutex_key(_SESSION)] = 1  # 模拟「占位之后过了一阵才开始推进」

    await bind_lease_run_id(cache, lease, "run-A")

    assert lease.run_id == "run-A"
    assert cache.ttls[mutex_key(_SESSION)] == RUN_MUTEX_TTL_SECONDS


# ---------------------------------------------------------------------------
# 3 取消不得打断收尾
# ---------------------------------------------------------------------------


async def test_repeated_cancel_does_not_interrupt_finalize() -> None:
    """第二次取消（连点停止键 / 两个标签页同时停）不得打断收尾。

    时序：运行中 → 第一次取消（投递 `CancelledError`，收尾开始）→ 收尾的第一笔写停
    在闸门上 → **第二次取消**到达 → 放行。

    判别性：去掉 `request_cancel` 里的 `task.cancelling()` 判据，收尾的第二笔写
    （释放会话位）永远不执行——第一条断言变红，使用者最长 `RUN_MUTEX_TTL_SECONDS`
    秒内每次发消息都吃 409 `session_busy`。
    """
    cache = GatedCache()
    pump, task, gate = await _start_gated_run(cache)
    run_id = str(pump.run_id)

    finalize_gate = cache.pause_before_mutation(meta_key(run_id))
    assert request_cancel(run_id) is True
    await finalize_gate.arrived.wait()
    assert request_cancel(run_id) is True, "重复取消按「已经要求停了」如实受理"
    finalize_gate.release.set()

    gate.set()
    await drain_pumps()

    assert task.done()
    assert await cache.get(mutex_key(_SESSION)) is None, "收尾被打断：会话位没有释放"
    meta = await read_run_meta(cache, run_id=run_id)
    assert meta is not None and meta.status == RUN_STATUS_FINISHED, "收尾被打断：元数据停在运行中"


async def test_cancel_during_finalize_is_accepted_but_not_injected() -> None:
    """收尾已经开始时的取消：如实回「已要求停止」，但不注入取消。

    这是上一条的另一半：运行自己跑完了，收尾的第一笔写（元数据 → `finished`）落地途中
    收到取消（使用者恰好在模型收尾时按了停止键）。此时注入取消会让第二笔写（释放会话位）
    丢掉。

    判别性：去掉 `request_cancel` 里的 `pump.settling` 判据，最后两条断言变红。
    """
    cache = GatedCache()
    pump, task, gate = await _start_gated_run(cache)
    run_id = str(pump.run_id)

    finalize_gate = cache.pause_before_mutation(meta_key(run_id))
    gate.set()  # 让运行自己跑到终态、进入收尾
    await finalize_gate.arrived.wait()

    assert request_cancel(run_id) is True
    finalize_gate.release.set()
    await drain_pumps()

    assert task.done()
    assert await cache.get(mutex_key(_SESSION)) is None, "收尾被打断：会话位没有释放"
    meta = await read_run_meta(cache, run_id=run_id)
    assert meta is not None and meta.status == RUN_STATUS_FINISHED


async def test_cancel_still_stops_a_running_run() -> None:
    """正控：运行中（收尾未开始）的取消照旧生效，且收尾照常落定。

    没有这一条，上面两条可以被「一律拒绝取消」这种实现骗过——那会让停止键整个失效：
    运行照跑、前端却显示已中断。
    """
    cache = GatedCache()
    pump, task, _gate = await _start_gated_run(cache)
    run_id = str(pump.run_id)

    assert request_cancel(run_id) is True
    await drain_pumps()

    assert task.cancelled(), "取消必须真的停掉推进任务"
    assert await cache.get(mutex_key(_SESSION)) is None
    meta = await read_run_meta(cache, run_id=run_id)
    assert meta is not None and meta.status == RUN_STATUS_FINISHED


async def test_cancel_of_an_unknown_run_changes_nothing() -> None:
    """并发取消的兜底：本进程里没有这条运行的消费方 → `False`（端点据此回 409）。"""
    assert request_cancel("run-never-started") is False


# ---------------------------------------------------------------------------
# 4 收尾写的顺序：状态先落定，再释放位子
# ---------------------------------------------------------------------------


async def test_finalize_writes_the_status_before_releasing_the_slot() -> None:
    """取消端点靠「元数据仍是 running」判断运行还在跑，因此状态必须先落定再放位子。

    反过来（先放位子）会让「位子已易主、状态还没落定」这段窗口里，取消端点对旧运行的
    答复变成 202 而不是 409——而那个位子已经是另一个运行的了。
    """
    cache = GatedCache()
    pump, task, gate = await _start_gated_run(cache)
    run_id = str(pump.run_id)
    # 只看收尾那一段：`begin()` 也会写元数据、也会动互斥键（把令牌换成 run_id），
    # 混在一起看就分不清哪一次是收尾。
    settled_from = len(cache.ops)

    gate.set()
    await drain_pumps()
    assert task.done()

    settle_ops = cache.ops[settled_from:]
    status_index = settle_ops.index(("set", meta_key(run_id)))
    release_index = next(
        index for index, (op, key) in enumerate(settle_ops) if key == mutex_key(_SESSION) and op in _MUTATIONS
    )
    assert status_index < release_index, "释放位子早于终态落定"
