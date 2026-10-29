"""`core/cache` 的装配前提与两条原子原语。

**装配前提**：池必须开 `decode_responses`。`RedisCache.get` 与 `RedisCache.lrange`
各有一处 `cast`，把 redis-py stub 的 `bytes | str | None` 收窄成 `str`。收窄可靠的
唯一依据是构造参数——开了 `decode_responses`，`GET`/`LRANGE` 才返回 `str`，关掉就是
`bytes`。redis-py 8.1.0 的 `Redis` 不是泛型类，也没有区分该开关的重载，静态检查据此
发现不了任何东西；因此这个前提需要一条自己的机械通道（CORE-05：不变量落最强通道，
禁注释承诺）。

**两条原子原语**（`compare_and_delete` / `compare_and_set`）：它们是会话互斥的两条
释放/换手路径所依赖的全部语义——值还是自己的才动，不是自己的就一个字节都不写。
这一层测的是「语义与 TTL」，**原子性本身由实现形状保证**（单条 Lua 脚本，比较与变更
之间不存在可插入的窗口），因此它不需要、也无法用单线程用例证明；对应的时序回归在
`tests/test_consult_runbus_races.py`（那里把「比对之后、变更之前」这个位置变成闸门）。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from campfire.core.cache import RedisCache
from campfire.core.config import get_settings

#: 本文件写的键前缀。用例结束逐个删掉，不 FLUSH（同一实例上还有别的库与别人的键）。
_KEY_PREFIX = "it-cache-unit:"

# 标记逐条加：`integration` 只给真的需要 Redis 的用例（上面那条装配前提不连 Redis，
# 标成 integration 会让它在「只跑单测」时消失），`asyncio` 只给 async 用例。


def test_pool_decodes_responses() -> None:
    """池的生效连接参数里 `decode_responses` 必须为 True。

    断言看的是池的生效参数（`connection_kwargs`）而不是构造时传了什么，
    这样「传了又被覆盖」的改动也拦得住。

    不需要 Redis 容器：`ConnectionPool.from_url` 只装配参数，第一条命令才建连。
    """
    cache = RedisCache("redis://127.0.0.1:6379/0")

    assert cache._pool.connection_kwargs.get("decode_responses") is True


@pytest_asyncio.fixture
async def cache() -> AsyncIterator[RedisCache]:
    """连真实 Redis；不可用时**跳过**（不假装通过）。"""
    client = RedisCache(get_settings().redis_url)
    try:
        await client.exists(f"{_KEY_PREFIX}probe")
    except Exception as exc:  # noqa: BLE001 —— 探针只回答「能不能连上」
        await client.aclose()
        pytest.skip(f"Redis 不可用（{type(exc).__name__}）——本用例需要 docker compose up -d redis")
    try:
        yield client
    finally:
        leftover = await client.scan_keys(f"{_KEY_PREFIX}*", limit=100)
        if leftover:
            await client.delete(*leftover)
        await client.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compare_and_delete_only_deletes_the_value_it_was_given(cache: RedisCache) -> None:
    """值仍是 `expected` 才删；不是就一个字节都不动，并如实回 `False`。"""
    key = f"{_KEY_PREFIX}{uuid.uuid4().hex}"
    await cache.set(key, "mine", ttl_seconds=60)

    assert await cache.compare_and_delete(key, "theirs") is False
    assert await cache.get(key) == "mine", "值不匹配时删掉了别人的键"

    assert await cache.compare_and_delete(key, "mine") is True
    assert await cache.get(key) is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compare_and_delete_returns_false_for_a_missing_key(cache: RedisCache) -> None:
    """键不存在同样是 `False`：调用方据此知道「这个位子已经不在我手上」。"""
    assert await cache.compare_and_delete(f"{_KEY_PREFIX}{uuid.uuid4().hex}", "mine") is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compare_and_set_writes_only_when_the_value_matches(cache: RedisCache) -> None:
    """值仍是 `expected` 才换值；不是就保持原样，并如实回 `False`。"""
    key = f"{_KEY_PREFIX}{uuid.uuid4().hex}"
    await cache.set(key, "theirs", ttl_seconds=60)

    assert await cache.compare_and_set(key, "mine", "run-A", ttl_seconds=60) is False
    assert await cache.get(key) == "theirs", "值不匹配时覆盖了别人的键"

    assert await cache.compare_and_set(key, "theirs", "run-A", ttl_seconds=60) is True
    assert await cache.get(key) == "run-A"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compare_and_set_leaves_a_ttl_behind(cache: RedisCache) -> None:
    """换手后的键**必须**带过期时间：没有 TTL 的互斥键是永久占位（会话再也发不出消息）。

    判据读的是真实 TTL（`TTL` 命令，单位秒），而不是「本方法传了参数」——传了却被
    丢掉（例如误写成不带 `EX` 的 `SET`）只有这个断言拦得住。
    """
    key = f"{_KEY_PREFIX}{uuid.uuid4().hex}"
    await cache.set(key, "mine", ttl_seconds=600)

    assert await cache.compare_and_set(key, "mine", "run-A", ttl_seconds=42) is True

    raw = aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        ttl = await raw.ttl(key)
    finally:
        await raw.aclose()
    assert 0 < ttl <= 42, f"换手后的键没有按 ttl_seconds 过期：ttl={ttl}"
