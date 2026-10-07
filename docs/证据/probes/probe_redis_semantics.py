"""T17 机制探针：`brpop` 的读超时/服务端超时/连接断开各自产生什么。

要回答的问题（任务包要求「Redis 真的挂了时 worker 会怎样」要有实测或源码依据）：
  P1 默认装配（socket_timeout=5, brpop 服务端 timeout=0）空闲 → 抛什么、多久
  P2 brpop(服务端 timeout=2) + socket_timeout=10 → 是抛异常还是正常返回 None
  P3 brpop(服务端 timeout=2) + socket_timeout=1 → 是否会先被客户端读超时打断（两者的大小关系）
  P4 socket_timeout=None + 空闲 → 是否无限阻塞
  P5 对端【静默】（socket 不断、只是不再回数据）→ 三种 socket_timeout 下各自的行为
  P6 对端【断开】（RST/FIN）→ 抛的是 redis 的哪个异常

P5/P6 用一个进程内的 TCP 代理模拟（**不动本机 Memurai**，那是共享数据服务）：
    客户端 → 代理 127.0.0.1:6390 → 真实 Redis 127.0.0.1:6379

用法：
    uv run python tmp/T17/probe_redis_semantics.py
"""

from __future__ import annotations

import asyncio
import os
import time

os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
os.environ["no_proxy"] = "127.0.0.1,localhost,::1"

import redis.asyncio as aioredis  # noqa: E402

QUEUE = "campfire_t17_probe"
REAL = ("127.0.0.1", 6379)
PROXY_PORT = 6390


def describe(exc: BaseException) -> str:
    return f"{type(exc).__module__}.{type(exc).__name__}: {exc}"


async def pop(url: str, *, server_timeout: int | None, budget: float, socket_timeout: object = "url") -> str:
    """跑一次 brpop，返回可读结论。server_timeout=None 表示沿用上游的默认 timeout=0。

    `socket_timeout`：`"url"` 表示由 URL 查询串决定；否则作为构造参数传入
    （`None` 不能写进 URL——redis-py 的 parse_url 会 `float('None')` 失败，这是实测到的）。
    """
    kwargs = {} if socket_timeout == "url" else {"socket_timeout": socket_timeout}
    client = aioredis.from_url(url, **kwargs)
    started = time.monotonic()
    try:
        if server_timeout is None:
            call = client.brpop(QUEUE)
        else:
            call = client.brpop(QUEUE, timeout=server_timeout)
        result = await asyncio.wait_for(call, timeout=budget)
        verdict = f"正常返回 {result!r}"
    except asyncio.TimeoutError:
        verdict = f"撑满预算 {budget:.0f}s 仍在阻塞（无返回、无异常）"
    except Exception as exc:  # noqa: BLE001 —— 探针只报类型
        verdict = describe(exc)
    cost = time.monotonic() - started
    await client.aclose()
    return f"{verdict}  ({cost:.2f}s)"


class Silencer:
    """TCP 代理：可以先正常转发，然后切成「静默」或「断开」来模拟 Redis 真挂。"""

    def __init__(self, *, mode: str = "pass") -> None:
        self.mode = mode  # pass | blackhole | reset
        self._server: asyncio.Server | None = None
        self._pairs: list[tuple[asyncio.StreamWriter, asyncio.StreamWriter]] = []

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", PROXY_PORT)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
        for client_writer, upstream_writer in list(self._pairs):
            for writer in (client_writer, upstream_writer):
                writer.close()

    async def _pump(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            if self.mode == "blackhole":
                # 静默：数据既不转发也不报错，socket 保持打开（模拟黑洞/Redis 卡死不回应）
                await asyncio.sleep(3600)
            writer.write(chunk)
            await writer.drain()

    async def _handle(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        upstream_reader, upstream_writer = await asyncio.open_connection(*REAL)
        self._pairs.append((client_writer, upstream_writer))
        if self.mode == "reset":
            client_writer.close()
            upstream_writer.close()
            return
        try:
            await asyncio.gather(
                self._pump(client_reader, upstream_writer),
                self._pump(upstream_reader, client_writer),
            )
        except Exception:  # noqa: BLE001 —— 代理的收尾异常与被测对象无关
            pass


async def main() -> int:
    import redis as sync_redis  # noqa: E402

    print("=== 环境 ===")
    print("redis-py", sync_redis.__version__, "| brpop 默认服务端 timeout=0")
    print(f"真实 Redis = {REAL[0]}:{REAL[1]}；代理 = 127.0.0.1:{PROXY_PORT}")

    direct = f"redis://127.0.0.1:{REAL[1]}/0"
    print("\n=== 直连真实 Redis（空闲队列）===")
    print("P1 默认 socket_timeout(=5) + 服务端 timeout=0 :", await pop(direct, server_timeout=None, budget=12))
    print("P2 socket_timeout=10 + 服务端 timeout=2    :", await pop(f"{direct}?socket_timeout=10", server_timeout=2, budget=8))
    print("P3 socket_timeout=1  + 服务端 timeout=2    :", await pop(f"{direct}?socket_timeout=1", server_timeout=2, budget=8))
    print(
        "P4 socket_timeout=None + 服务端 timeout=0  :",
        await pop(direct, server_timeout=None, budget=10, socket_timeout=None),
    )

    proxied = f"redis://127.0.0.1:{PROXY_PORT}/0"

    print("\n=== P5 对端【静默】（BRPOP 已发出后，代理不再回任何数据；socket 保持打开）===")
    for label, kwargs, budget in (
        ("socket_timeout=None", {"socket_timeout": None}, 13),
        ("socket_timeout=5（默认）", {}, 13),
        ("socket_timeout=3", {"socket_timeout": 3}, 13),
    ):
        proxy = Silencer()
        await proxy.start()
        client = aioredis.from_url(proxied, **kwargs)
        # 先让 BRPOP 真正发到真实 Redis 并进入阻塞，再把代理切成静默
        task = asyncio.create_task(client.brpop(QUEUE))
        await asyncio.sleep(1.0)
        proxy.mode = "blackhole"
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(task, timeout=budget)
            verdict = f"正常返回 {result!r}"
        except asyncio.TimeoutError:
            verdict = f"撑满预算 {budget}s 仍在阻塞（无返回、无异常）"
        except Exception as exc:  # noqa: BLE001
            verdict = describe(exc)
        print(f"  {label:28s} -> {verdict}  ({time.monotonic() - started:.2f}s 自静默起算)")
        await client.aclose()
        await proxy.stop()

    print("\n=== P6 对端【断开】（代理直接 close socket）===")
    for label, kwargs in (("socket_timeout=None", {"socket_timeout": None}), ("socket_timeout=5（默认）", {})):
        proxy = Silencer()
        await proxy.start()
        client = aioredis.from_url(proxied, **kwargs)
        task = asyncio.create_task(client.brpop(QUEUE))
        await asyncio.sleep(1.0)
        for _, upstream_writer in list(proxy._pairs):
            upstream_writer.close()
        for client_writer, _ in list(proxy._pairs):
            client_writer.close()
        await asyncio.sleep(0)
        try:
            result = await asyncio.wait_for(task, timeout=15)
            verdict = f"正常返回 {result!r}"
        except asyncio.TimeoutError:
            verdict = "撑满预算 15s 仍在阻塞"
        except Exception as exc:  # noqa: BLE001
            verdict = describe(exc)
        print(f"  {label:28s} -> {verdict}")
        await client.aclose()
        await proxy.stop()

    print("\n=== P7 对端【静默后自己放弃】（代理在 20s 时把 socket 断掉；客户端 socket_timeout=None）===")
    proxy = Silencer()
    await proxy.start()
    client = aioredis.from_url(proxied, socket_timeout=None)
    task = asyncio.create_task(client.brpop(QUEUE))
    await asyncio.sleep(1.0)
    proxy.mode = "blackhole"
    started = time.monotonic()

    async def drop_later() -> None:
        await asyncio.sleep(20)
        for _, upstream_writer in list(proxy._pairs):
            upstream_writer.close()
        for client_writer, _ in list(proxy._pairs):
            client_writer.close()

    dropper = asyncio.create_task(drop_later())
    try:
        result = await asyncio.wait_for(task, timeout=40)
        verdict = f"正常返回 {result!r}"
    except asyncio.TimeoutError:
        verdict = "撑满预算 40s 仍在阻塞"
    except Exception as exc:  # noqa: BLE001
        verdict = describe(exc)
    print(f"  socket_timeout=None, 对端在 20s 断开 -> {verdict}  ({time.monotonic() - started:.2f}s 自静默起算)")
    dropper.cancel()
    await client.aclose()
    await proxy.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
