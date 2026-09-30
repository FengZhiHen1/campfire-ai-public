"""缓存与限流（Redis 7）：本包承载 Redis 的最小装配。

职责：连接池装配与面层需要的那几个键值原语的封装（取值、置值、占用、列表尾追加、
列表区间读、续期、删除）。不做业务语义判断，不认知任何 key 的命名含义。
边界：只有这几个原语——限流、缓存装饰器、序列化协议都不在此处；
Redis 不承载长期业务状态，丢失不恢复已撤销状态（技术栈设计第 2、4 节）。
参考：`docs/技术栈设计.md` 第 2、4、6 节；队列装配见 `core/jobs`。

为什么是「最小装配」而不是一个通用缓存客户端：
调用方（`surfaces/consult` 的事件缓冲、运行互斥与幂等键）需要的能力恰好是
「按 key 放、按 key 取、按 key 占、列表追加与区间读、给 key 续期」这六件事，
而这六件在 redis-py 上是六个一一对应的异步方法。把连接池、解码开关与关闭
集中到一处是有价值的（三处各 `from_url` 会各建一个池，且解码开关不一致时
同一个 key 在不同调用点会是 `bytes` 与 `str` 两种类型）；再往上抽象
（比如「带前缀的命名空间」或「自动 JSON 序列化」）就会把命名与编码决策
从调用方搬进来，而两者都是调用方才知道的事实。因此这里只做装配与转调。

原有的包级说明（`docs/技术栈设计.md` 第 2、4 节）保留如下：

归属：Redis 承载缓存与限流，不承载长期业务状态；丢失不恢复已撤销状态。

安全约束：授权与撤销不得依赖缓存——服务端按请求重新查证
（见 `docs/技术栈设计.md` 第 6 节）。登录限流与防爆破由我们自己实现
（SuperTokens 的攻击防护套件属付费特性）。

（原文第三段「尚未实现：本包当前无代码」已随本次实现作废，如实替换为上面
第一段的事实陈述。）
"""

from __future__ import annotations

import redis.asyncio as aioredis

from campfire.core.config import Settings

__all__ = [
    "RedisCache",
    "close_cache",
    "get_cache",
    "set_cache",
]


class RedisCache:
    """一个 Redis 连接池与六个键值原语。

    连接池在构造时建立（`ConnectionPool.from_url` 本身不发起连接，第一条命令才连），
    因此构造不会因为 Redis 不可用而失败——这与「启动不连数据库」同一种取向
    （`main.py` 的说明）：可达性由调用点按请求处理，不由启动顺序决定。

    `decode_responses=True`：事件缓冲里存的是 SSE 行与游标，调用方需要 `str`。
    不开启时同一个 key 在不同调用点会是 `bytes` 与 `str` 两种类型，而这是一个
    只能靠运行期发现的差异。
    """

    def __init__(self, redis_url: str) -> None:
        """按连接串建立连接池。

        Args:
            redis_url: Redis 连接串（唯一来源是配置）。
        """
        self._redis_url = redis_url
        self._pool: aioredis.ConnectionPool = aioredis.ConnectionPool.from_url(redis_url, decode_responses=True)

    @property
    def redis_url(self) -> str:
        """连接串（诊断用；不含凭据时为空）。"""
        return self._redis_url

    async def get(self, key: str) -> str | None:
        """取一个键的值；键不存在时返回 `None`。"""
        client = aioredis.Redis(connection_pool=self._pool)
        return await client.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        """置值并同时设定过期时间。

        `ttl_seconds` 是必填而不是可选：本包的使用者全是「有生命周期的临时键」，
        一个没有过期时间的键在 Redis 里是不可回收的垃圾（无人会来删它）。
        """
        client = aioredis.Redis(connection_pool=self._pool)
        await client.set(key, value, ex=ttl_seconds)

    async def setnx(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        """只在键不存在时置值；返回「本次是否真的写进去了」。

        `SET NX EX` 一条命令完成「占位 + 设定过期」，而不是 `SETNX` 后再 `EXPIRE`：
        两条命令之间进程死掉会留下一个永不过期的占位键，此后该位永远被占
        （互斥与幂等键都靠这个原语，卡死的后果是会话再也发不出消息）。
        """
        client = aioredis.Redis(connection_pool=self._pool)
        return bool(await client.set(key, value, nx=True, ex=ttl_seconds))

    async def rpush(self, key: str, *values: str, ttl_seconds: int) -> None:
        """把值依次追加到列表尾部，并刷新该键的过期时间。

        续期与追加放在一次调用里：事件缓冲的 TTL 语义是「最后一条事件之后的
        保留时长」，若只在建键时设一次，一个跑了 170 秒的运行会在结束前后
        就丢掉缓冲区——续传窗口随之消失。写入方每次追加都在延长它，
        不需要单独记「上次写入时间」。
        """
        if not values:
            return
        client = aioredis.Redis(connection_pool=self._pool)
        pipe = client.pipeline(transaction=False)
        pipe.rpush(key, *values)
        pipe.expire(key, ttl_seconds)
        await pipe.execute()

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        """读列表的闭区间 `[start, stop]`；`stop=-1` 表示到末尾。

        键不存在时返回空列表（redis-py 的原生行为），调用方据此判断
        「没有可续内容」——本方法不把「键不存在」与「列表为空」分开，
        因为那个区别只有调用方在决定要不要报 409 时才需要，而它可以先看键是否存在。
        """
        client = aioredis.Redis(connection_pool=self._pool)
        return list(await client.lrange(key, start, stop))

    async def expire(self, key: str, ttl_seconds: int) -> bool:
        """给已存在的键续期；返回「键是否存在（因而被续期）」。"""
        client = aioredis.Redis(connection_pool=self._pool)
        return bool(await client.expire(key, ttl_seconds))

    async def delete(self, *keys: str) -> int:
        """删除若干键，返回真的被删掉的个数。

        互斥键的释放需要它（运行终结时删键）。返回值是「删了几个」而不是布尔：
        释放方据此判断「这个键还在不在我手上」——比对值再删的释放路径要这个信息
        （见 `surfaces/consult` 的释放实现）。
        """
        if not keys:
            return 0
        client = aioredis.Redis(connection_pool=self._pool)
        return int(await client.delete(*keys))

    async def exists(self, key: str) -> bool:
        """键是否存在。续传路径据此区分「缓冲已失效」与「只是暂时没有新事件」。"""
        client = aioredis.Redis(connection_pool=self._pool)
        return bool(await client.exists(key))

    async def scan_keys(self, pattern: str, *, limit: int) -> list[str]:
        """按模式扫描键名，最多返回 `limit` 个（测试与运维复核用）。

        用 `SCAN` 而不是 `KEYS`：`KEYS` 会阻塞整个实例，而生产库与测试库常常是
        同一个实例的不同 db。`limit` 是显式上界（CORE-11）——它同时是
        「扫到这么多就够了」的短路条件，避免一个宽模式把全库键名拉回来。
        """
        client = aioredis.Redis(connection_pool=self._pool)
        found: list[str] = []
        async for key in client.scan_iter(match=pattern, count=100):
            found.append(key)
            if len(found) >= limit:
                break
        return found

    async def aclose(self) -> None:
        """关闭连接池。进程收尾时调用；调用后本对象不可再用。"""
        await self._pool.aclose()


#: 进程级缓存客户端。装配处（`main.py`）建一次，各调用点取同一个。
#:
#: 为什么用模块级单例而不是每请求构造：`ConnectionPool` 是「连接池」这一资源本身，
#: 每请求建一个等于每请求建一个池（连接不复用，且旧池要等 GC 才关）。
#: 与 `core/authz` 的 `set_authorizer`、`core/jobs` 的 `set_dispatch_hook`
#: 同一种装配处注入风格。
_cache: RedisCache | None = None


def get_cache(settings: Settings) -> RedisCache:
    """取进程级缓存客户端；尚未设置时按配置建一个。

    未显式设置也能工作：单机与测试环境不必有装配步骤，第一次取用时按
    `settings.redis_url` 建池即可。装配处预置的价值是可以在收尾时统一 `close_cache()`。
    """
    global _cache
    if _cache is None:
        _cache = RedisCache(settings.redis_url)
    return _cache


def set_cache(cache: RedisCache | None) -> None:
    """设置（或清除）进程级缓存客户端。只在装配处与测试夹具里调用。

    传 `None` 可清除——测试据此隔离彼此，避免一个用例的缓存跨用例泄漏。
    """
    global _cache
    _cache = cache


async def close_cache() -> None:
    """关闭并清除进程级客户端；未设置时无操作（幂等）。"""
    global _cache
    if _cache is not None:
        await _cache.aclose()
        _cache = None
