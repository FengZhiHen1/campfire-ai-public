"""`core/jobs` 的队列读取：**空闲不是异常路径**，且 Redis 不可用时不退出 Worker。

背景（2026-10-05，T17）：`taskiq worker campfire.worker:broker` 在**空闲队列**上每约
10 秒崩一次、被 Taskiq 反复重启（实测 62 秒内 12 次）。链路是：

1. 上游 `ListQueueBroker.listen()` 用 `redis_conn.brpop(self.queue_name)`，
   **不传** `timeout` ⇒ 服务端 block = 0（永久阻塞）；
2. 但 `redis-py 8.1.0` 的 `DEFAULT_SOCKET_TIMEOUT = 5`，而
   `AbstractConnection.read_response(timeout=None)` 会**回落到** `self.socket_timeout`
   （`redis/asyncio/connection.py:1277`），其超时分支**抛** `redis.exceptions.TimeoutError`
   （同文件 1303-1310）而不是返回 `None`；
3. `taskiq_redis/redis_broker.py:136` 捕的是**内建** `ConnectionError`
   （该文件只从 redis 导入了 `ResponseError`，模块全局里没有 `ConnectionError`），
   而 redis 的 `TimeoutError` 继承 `RedisError`、**不是**内建 `ConnectionError` 的子类
   ⇒ 异常逃出生成器 ⇒ Taskiq 判子进程死亡 ⇒ 重启 ⇒ 循环。

因此本文件的判据全部是**行为**：
- 空队列上 `listen()` 必须**正常转着**（不抛异常）——这是崩溃循环的直接反证；
- 队列有条目时必须**取得到**——防「为了不崩把消费也修没了」；
- Redis 不可用时必须**不退出**、只重试——防「修了空闲、挂了就死」。

不写「连接的 socket_timeout 等于某个具体数字」这类断言：那钉的是实现细节，
换一种合规的等法（例如改成服务端 block + 更长的客户端上界）就会假红。
唯一保留的数值断言是**两者的大小关系**（客户端上界必须大于服务端 block），
它不是实现细节而是机理本身——实测 `socket_timeout=1` + block=2 时客户端先超时、
崩溃原样复现（原证物 `probes/probe_redis_semantics.py` 的 P3）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from campfire.core import jobs as jobs_module
from campfire.core.config import Settings
from campfire.core.jobs import build_broker

pytestmark = [pytest.mark.integration]

#: 本文件用的队列名。**不能**用生产队列名（`settings.taskiq_queue_name`）：
#: 真实环境里可能正跑着一个真 Worker 在消费它，会把本用例摆的消息抢走
#: （第一版就是这么错的：用例打的是「等不到消息」而不是它要判的东西）。
_TEST_QUEUE = "campfire_t17_broker_test"

#: 拉一条消息的等待上界（秒）。空闲时 `listen()` 每一轮只花服务端 block 的时长，
#: 因此这个上界只需比它宽裕即可，不需要跑满一个崩溃周期。
_PULL_TIMEOUT_SECONDS = 12.0

#: 空队列观察窗（秒）：必须**长于**修前的 5 秒读超时，否则「没崩」没有判别力。
_IDLE_WINDOW_SECONDS = 8.0


async def _redis_or_skip(settings: Settings) -> aioredis.Redis:
    """连上 Redis；不可用则跳过（与 `test_consult_endpoints_integration` 同一约定）。"""
    client = aioredis.from_url(settings.redis_url)
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001 —— 环境缺失与产品缺陷要分开
        await client.aclose()
        pytest.skip(f"Redis 不可用（{type(exc).__name__}）——集成测试需要 docker compose up -d redis")
    return client


async def _drain(broker: object, *, seconds: float) -> tuple[int, BaseException | None]:
    """跑 `listen()` 若干秒，返回（取到的条数, 逃出的异常）。

    异常被**返回**而不是断言在循环里，是为了让用例能把「抛了什么」写进失败信息
    ——崩溃循环的判别力就在于「有没有东西逃出来」。
    """
    count = 0
    iterator = broker.listen().__aiter__()  # type: ignore[attr-defined]
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return count, None
        try:
            await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
        except asyncio.TimeoutError:
            return count, None
        except StopAsyncIteration:
            return count, None
        except BaseException as exc:  # noqa: BLE001 —— 见 docstring
            return count, exc
        count += 1


@pytest_asyncio.fixture
async def broker_and_client() -> AsyncIterator[tuple[object, aioredis.Redis, str]]:
    """生产装配出的 broker + 一个原始 Redis 客户端（用来摆布队列内容）。

    ⚠ **必须换一个队列名**（不是 `settings.taskiq_queue_name`）：本用例要在队列里
    摆一条消息，而真实环境里可能正跑着一个真 Worker 在消费生产队列。第一版用了
    生产队列名，结果本地那条 soak Worker 把测试的消息抢走了——用例打的是
    `asyncio.TimeoutError`（等不到消息），而不是它要判的「取不到 / 崩不崩」。
    换名之后本用例只与自己交互，也不会污染生产队列。
    """
    settings = Settings().model_copy(update={"taskiq_queue_name": _TEST_QUEUE})
    client = await _redis_or_skip(settings)
    broker = build_broker(settings)
    queue = settings.taskiq_queue_name
    await client.delete(queue)
    try:
        yield broker, client, queue
    finally:
        await client.delete(queue)
        await broker.shutdown()
        await client.aclose()


@pytest.mark.asyncio
async def test_idle_queue_does_not_raise(broker_and_client: tuple[object, aioredis.Redis, str]) -> None:
    """空队列上 `listen()` 必须一直正常转着——不抛任何异常。

    这是崩溃循环的**直接反证**：修前这条在 5 秒（redis-py 的默认读超时）就会
    抛 `redis.exceptions.TimeoutError`，而 Taskiq 捕不到它 ⇒ 子进程判死重启。
    观察窗取 8 秒：必须长于 5 秒，否则「没崩」可能只是还没到超时点。
    """
    broker, _, _ = broker_and_client

    count, exc = await _drain(broker, seconds=_IDLE_WINDOW_SECONDS)

    assert exc is None, (
        f"空闲队列上 listen() 逃出异常（{type(exc).__module__}.{type(exc).__name__}: {exc}）"
        f"——Taskiq 会把 worker 子进程判死并重启，这就是崩溃循环"
    )
    assert count == 0, f"空队列上不该取到任何消息，实际取到 {count} 条"


@pytest.mark.asyncio
async def test_message_is_still_consumed(broker_and_client: tuple[object, aioredis.Redis, str]) -> None:
    """队列有条目时必须取得到，且**先进先出**。

    防「为了不崩把消费也修没了」，以及防「顺手把 `brpop` 换成 `blpop`」：
    `kick()` 走 `lpush`（推入表头），必须从表尾 `brpop` 取出才是 FIFO；
    换成 `blpop` 会让队列变成后进先出，先投的任务永远排在后面。
    """
    broker, client, queue = broker_and_client
    await client.lpush(queue, b"first")
    await client.lpush(queue, b"second")

    iterator = broker.listen().__aiter__()  # type: ignore[attr-defined]
    got = [await asyncio.wait_for(iterator.__anext__(), timeout=_PULL_TIMEOUT_SECONDS) for _ in range(2)]

    assert got == [b"first", b"second"], f"取出顺序应为先投先出（first, second），实际 {got}"


@pytest.mark.asyncio
async def test_unavailable_redis_does_not_escape_listen() -> None:
    """Redis 连不上时 `listen()` **不抛异常**：Worker 应当继续重试而不是退出。

    为什么这条必须单独钉：把空闲修好、却让「Redis 挂了」变成异常逃逸，
    等于把崩溃循环换到更糟的时机上（Redis 抖动时成批重启）。
    指向一个没人监听的端口即可——`ConnectionError` 是本类要吞掉的两类异常之一。

    这里不走 `_redis_or_skip`：本用例**故意**要一个连不上的地址。
    """
    settings = Settings()
    # 6399 在 compose / .env / CI 里都没有服务；用替换而不是拼接，保持 URL 形状合法。
    dead = settings.model_copy(update={"redis_url": settings.redis_url.replace("6379", "6399")})
    assert dead.redis_url != settings.redis_url, "本用例要求换成一个未被监听的端口，请检查 REDIS_URL 的形状"
    broker = build_broker(dead)
    try:
        count, exc = await _drain(broker, seconds=4.0)
    finally:
        await broker.shutdown()

    assert exc is None, (
        f"Redis 不可用时 listen() 逃出异常（{type(exc).__module__}.{type(exc).__name__}: {exc}）"
        f"——Taskiq 会把 worker 子进程判死并重启，Redis 抖动会变成成批重启"
    )
    assert count == 0


def test_client_read_timeout_outlives_server_side_block() -> None:
    """客户端读超时必须**大于**服务端阻塞时长，否则空闲照崩。

    这不是实现细节的复述，而是机理本身：`read_response` 的超时分支抛异常，
    而它只在「客户端上界先到」时触发。实测（原证物 `probes/probe_redis_semantics.py`）：
    `socket_timeout=1` + 服务端 block=2 ⇒ 1.00 秒抛 `TimeoutError`（=修前的崩溃）；
    `socket_timeout=10` + 服务端 block=2 ⇒ 2.05 秒正常返回 `None`。

    同时钉两个方向：
    - 客户端上界必须**有限**——`None` 会让「Redis 静默卡死」变成无限等
      （实测：黑洞下撑满 13 秒预算仍在阻塞，无返回无异常）；
    - 它必须**严格大于**服务端 block，否则空闲又会走进异常分支。
    """
    broker = build_broker(Settings())
    pool_kwargs = broker.connection_pool.connection_kwargs
    client_timeout = pool_kwargs.get("socket_timeout")

    assert client_timeout is not None, (
        "socket_timeout 不能是 None：那会让「Redis 静默卡死」不再被超时发现，"
        "连接卡住时 worker 会无限等（比崩溃更难排查）"
    )
    assert isinstance(client_timeout, (int, float)), f"socket_timeout 应为数值，实际 {client_timeout!r}"
    assert client_timeout > jobs_module.QUEUE_BLOCK_SECONDS, (
        f"客户端读超时（{client_timeout}s）必须严格大于服务端阻塞时长"
        f"（QUEUE_BLOCK_SECONDS={jobs_module.QUEUE_BLOCK_SECONDS}s），否则空队列上会先触发客户端超时"
        "并抛 TimeoutError——那正是崩溃循环的成因"
    )
    # 服务端 block 也必须是有界且为正：0 就是上游那个永久阻塞，等于把问题原样带回来。
    assert jobs_module.QUEUE_BLOCK_SECONDS > 0, "服务端 block 不能为 0（0 = 永久阻塞，回到修前状态）"
