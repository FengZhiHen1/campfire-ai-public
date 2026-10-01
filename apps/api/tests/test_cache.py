"""`core/cache` 的装配前提：池必须开 `decode_responses`。

`RedisCache.get` 与 `RedisCache.lrange` 各有一处 `cast`，把 redis-py stub 的
`bytes | str | None` 收窄成 `str`。收窄可靠的唯一依据是构造参数——开了
`decode_responses`，`GET`/`LRANGE` 才返回 `str`，关掉就是 `bytes`。
redis-py 8.1.0 的 `Redis` 不是泛型类，也没有区分该开关的重载，静态检查据此
发现不了任何东西；因此这个前提需要一条自己的机械通道（CORE-05：不变量落
最强通道，禁注释承诺）。
"""

from __future__ import annotations

from campfire.core.cache import RedisCache


def test_pool_decodes_responses() -> None:
    """池的生效连接参数里 `decode_responses` 必须为 True。

    断言看的是池的生效参数（`connection_kwargs`）而不是构造时传了什么，
    这样「传了又被覆盖」的改动也拦得住。

    不需要 Redis 容器：`ConnectionPool.from_url` 只装配参数，第一条命令才建连。
    """
    cache = RedisCache("redis://127.0.0.1:6379/0")

    assert cache._pool.connection_kwargs.get("decode_responses") is True
