"""运行的传输层状态：事件缓冲、会话互斥与客户端幂等。

职责：把一次运行的事件写成可续传的 Redis 列表，并管住「一个会话一个运行」与
「同一个 `client_message_id` 只落一次使用者消息」两条不变量。
边界：不构造运行、不解析事件载荷、不做鉴权与归属判定（那些归 `routes` 与 `modules/accounts`）。
参考：docs/技术设计/面/consult/HTTP与SSE契约.md 第 1、4.1、4.2 节；
编排器 T07 裁决 1、2、3、5。

三件事都落在 Redis，理由各自写在常量旁边；共同的理由是：它们的生命周期都比
一次请求短、比一次运行长，都是传输层的临时事实而不是业务事实。业务事实（会话
归属、消息、引用）有自己的表，本模块一个都不碰。

缓冲存帧原文而不是「seq + 事件对象」。续传路径要把已发过的部分原样跳过，而它
需要的是「这一条的序号是多少」——把序号单独存一份等于同一件事有两个表示，
追加方改了其中一处就会得到「跳过的条数与实际不符」这种只在断线后才出现的缺陷。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Literal

from campfire.agent.runtime import AgentRunner, RunEvent, RunRequest
from campfire.core.cache import RedisCache
from campfire.surfaces.consult.sse import (
    TERMINAL_EVENT_TYPES,
    decode_frame,
    encode_frame,
    event_name,
)

logger = logging.getLogger(__name__)

#: 事件缓冲的保留时长（秒）。编排器裁决 1：运行上限 180 秒，终结后再留 420 秒
#: 供断线续传与回看，共 600 秒。
#:
#: 这个数是编排器裁决，不是设计文档里的数字——契约第 10 节把「缓冲结构、TTL 与
#: 终结后保留多久」列为待确认，裁决在 T07 任务包里给定。420 秒这个余量的意义：
#: 它必须覆盖前端的指数退避重连窗口（第 8 节），否则一次短暂的网络抖动就会让
#: 使用者落到「改走历史水合」的降级路径上，而他本可以无缝续上。
RUN_BUFFER_TTL_SECONDS = 600

#: 会话互斥键的 TTL（秒）。编排器裁决 2：运行上限 180 秒 + 5 秒余量。
#:
#: 为什么必须比运行上限大一点点：TTL 短于运行上限时，一个跑到 179 秒的运行会在
#: 自己还没结束时把锁放掉，第二个请求就能在同一会话上并行起第二次运行——正是这条
#: 互斥要防的事。5 秒余量给的是「终结路径删键」失败时的兜底窗口。
RUN_MUTEX_TTL_SECONDS = 185

#: 客户端幂等键的 TTL（秒）：24 小时。编排器裁决 3。
#:
#: 这条键记录的是「这个 `client_message_id` 已经换到过哪个 run_id」，它的生命周期
#: 是传输层的：覆盖前端重试窗口（含使用者关掉页面第二天再打开重试的极端情形）。
#: 主库不建表——幂等键不是业务事实，把它写进业务表会让「会话里到底有哪几条消息」
#: 这个问题多出一个可写的旁证。
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60

#: 幂等键的占位值前缀。第一个请求在拿到 `run_id` 之前必须先占住这个键，
#: 否则并发重发会各起一次运行；占位期间的读取方看到它就知道「已有同键请求在跑」。
_PENDING_PREFIX = "pending:"

#: 会话忙的错误码（契约第 2 节的 409 行）：同一会话同时只允许一个运行。
SESSION_BUSY = "session_busy"

#: 无法续传的错误码（契约 4.2）：缓冲已失效且没有可续内容，前端改走历史水合。
RUN_NOT_RESUMABLE = "run_not_resumable"

#: 运行状态取值（CORE-01：状态显式化，只有两种终局）。
RunStatus = Literal["running", "finished"]

RUN_STATUS_RUNNING: RunStatus = "running"
RUN_STATUS_FINISHED: RunStatus = "finished"

#: 事件缓冲里单条帧的长度上界（CORE-11）。一条事件本身就是模型增量或工具摘要，
#: 基座侧已有摘要长度上界（`SUMMARY_LIMIT`）；这里兜的是「万一某个载荷失控」，
#: 超界的帧会被截断并记警告，而不是让一次 RPUSH 写入兆字节。
MAX_FRAME_CHARS = 256 * 1024


def events_key(run_id: str) -> str:
    """事件缓冲的键（编排器裁决 1）。"""
    return f"run:{run_id}:events"


def meta_key(run_id: str) -> str:
    """运行元数据的键：归属账号、会话、状态。

    与事件缓冲分开两个键而不是塞进同一个：续传路径要判的是「这条运行是不是我的、
    结束了没有」，而它不必读事件正文；把归属塞进事件列表的元素里，会让一次鉴权
    判定变成一次列表扫描。
    """
    return f"run:{run_id}:meta"


def mutex_key(session_id: str) -> str:
    """会话互斥键（编排器裁决 2）。"""
    return f"session:{session_id}:run"


def idempotency_key(session_id: str, client_message_id: str) -> str:
    """客户端幂等键（编排器裁决 3）。"""
    return f"idem:{session_id}:{client_message_id}"


# ---------------------------------------------------------------------------
# 运行元数据
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunMeta:
    """一次运行的传输层身份：谁发的、发在哪个会话、跑完了没有。

    只记传输层需要的事实。不记「发的是什么消息」——那是会话真源的职责
    （基座第 2 节：对话的唯一真源是 SDK 的会话存储）。
    """

    run_id: str
    session_id: str
    account_id: str
    status: RunStatus

    def as_json(self) -> str:
        """序列化成缓冲里存的 JSON 文本。"""
        return json.dumps(
            {
                "run_id": self.run_id,
                "session_id": self.session_id,
                "account_id": self.account_id,
                "status": self.status,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def parse(raw: str | None) -> RunMeta | None:
        """从缓冲里读回元数据；缺失或形状不符时返回 `None`。

        形状不符一律按「不存在」处理而不是抛错：这条键由本模块写，读到别的东西
        只可能是别的东西占用了同名键，而调用方（订阅端点）对它的正确反应就是
        「按运行不存在处理」——fail-closed，不猜。
        """
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        run_id = payload.get("run_id")
        session_id = payload.get("session_id")
        account_id = payload.get("account_id")
        status = payload.get("status")
        if not all(isinstance(value, str) and value for value in (run_id, session_id, account_id)):
            return None
        if status not in (RUN_STATUS_RUNNING, RUN_STATUS_FINISHED):
            return None
        return RunMeta(
            run_id=run_id,
            session_id=session_id,
            account_id=account_id,
            status=status,
        )


async def write_run_meta(cache: RedisCache, meta: RunMeta, *, ttl_seconds: int = RUN_BUFFER_TTL_SECONDS) -> None:
    """写入（或刷新）运行元数据。"""
    await cache.set(meta_key(meta.run_id), meta.as_json(), ttl_seconds=ttl_seconds)


async def read_run_meta(cache: RedisCache, run_id: str) -> RunMeta | None:
    """读取运行元数据；不存在或形状不符时返回 `None`。"""
    return RunMeta.parse(await cache.get(meta_key(run_id)))


# ---------------------------------------------------------------------------
# 会话互斥（一个会话同时只允许一个运行）
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SessionRunLease:
    """一次运行占住的会话位。

    值分两段（`token` → `run_id`）而不是一开始就用 `run_id`：`run_id` 由基座在
    `run_started` 事件里给出，面层在启动运行之前拿不到它，而互斥必须在启动之前
    就成立——先启动再占位，两个并发请求各起一次运行，占位就白占了。
    因此先用一个本请求私有的租约令牌占位，拿到 `run_id` 后把值升级成它
    （裁决 2 要的「值 = run_id」在稳态下成立）。
    """

    session_id: str
    token: str
    run_id: str | None = None

    @property
    def expected_value(self) -> str:
        """当前应存在于互斥键里的值（升级前后不同）。"""
        return self.run_id or self.token


async def claim_session_run(cache: RedisCache, *, session_id: str) -> SessionRunLease | None:
    """尝试占住会话的运行位；已被占则返回 `None`。

    返回 `None` 而不是抛异常：调用方（发消息端点）要把它翻译成一个明确的对外
    拒绝（409 `session_busy`），而不是一次内部错误。
    """
    lease = SessionRunLease(session_id=session_id, token=uuid.uuid4().hex)
    claimed = await cache.setnx(mutex_key(session_id), lease.token, ttl_seconds=RUN_MUTEX_TTL_SECONDS)
    return lease if claimed else None


async def bind_lease_run_id(cache: RedisCache, lease: SessionRunLease, run_id: str) -> None:
    """把互斥键的值从租约令牌升级成 `run_id`。

    只在值仍是自己的令牌时升级：键可能已经过期并被另一个运行占走，此时改写它
    会破坏那个运行的互斥。升级后 `expected_value` 随之变化，释放路径据此比对。
    """
    key = mutex_key(lease.session_id)
    if await cache.get(key) != lease.token:
        logger.warning("会话互斥键易主，跳过 run_id 升级：会话=%s", lease.session_id)
        return
    lease.run_id = run_id
    await cache.set(key, run_id, ttl_seconds=RUN_MUTEX_TTL_SECONDS)


async def release_session_run(cache: RedisCache, lease: SessionRunLease) -> None:
    """释放会话位（compare-and-delete）。

    比对再删：键可能因 TTL 到期已被另一个运行占住，无条件 `DEL` 会把别人的位子
    放掉，于是那个会话上会出现两个并行运行——互斥失效的方式恰好是它要防的事。
    """
    key = mutex_key(lease.session_id)
    if await cache.get(key) != lease.expected_value:
        return
    await cache.delete(key)


# ---------------------------------------------------------------------------
# 客户端幂等
# ---------------------------------------------------------------------------


async def read_idempotent_run_id(cache: RedisCache, *, session_id: str, client_message_id: str) -> str | None:
    """取该幂等键已换到的 `run_id`；没有或仍在占位时返回 `None`。

    占位值按「还没有结论」处理：调用方据此继续往下走，而它随后会在互斥那一步
    拿到 409（同键的并发请求里，先到的那个正占着会话位）。这比让第二个请求等一个
    还不知道何时有结果的 `run_id` 更诚实——等待会把它变成一个无上界的阻塞点。
    """
    value = await cache.get(idempotency_key(session_id, client_message_id))
    if value is None or value.startswith(_PENDING_PREFIX):
        return None
    return value


async def reserve_idempotency(cache: RedisCache, *, session_id: str, client_message_id: str) -> bool:
    """占住该幂等键（值 = 占位）；已被占（无论占位或已有结论）则返回 `False`。"""
    return await cache.setnx(
        idempotency_key(session_id, client_message_id),
        f"{_PENDING_PREFIX}{uuid.uuid4().hex}",
        ttl_seconds=IDEMPOTENCY_TTL_SECONDS,
    )


async def commit_idempotency(cache: RedisCache, *, session_id: str, client_message_id: str, run_id: str) -> None:
    """把幂等键的值落成 `run_id`（此后重发返回它，不重复追加消息）。"""
    await cache.set(
        idempotency_key(session_id, client_message_id),
        run_id,
        ttl_seconds=IDEMPOTENCY_TTL_SECONDS,
    )


async def drop_idempotency(cache: RedisCache, *, session_id: str, client_message_id: str) -> None:
    """撤销占位（运行没能启动时）。

    为什么要撤销：占位值在读取方看来是「已有同键请求在跑」，而这次请求已经失败、
    没有任何运行在跑。留着它会让使用者的重试永远拿不到结论（既不返回 run_id，
    也进不去新运行）。只删占位、不删已落定的结论——后者是幂等语义本身。
    """
    key = idempotency_key(session_id, client_message_id)
    value = await cache.get(key)
    if value is not None and value.startswith(_PENDING_PREFIX):
        await cache.delete(key)


# ---------------------------------------------------------------------------
# 事件缓冲
# ---------------------------------------------------------------------------


async def append_event(cache: RedisCache, *, run_id: str, seq: int, event: RunEvent) -> None:
    """把一条事件按序号追加进缓冲，并刷新缓冲与元数据的过期时间。

    刷新元数据的 TTL 与刷新缓冲的 TTL 必须同时做：只续事件列表时，元数据会比它
    先到期，于是「缓冲里还有事件」与「运行不存在」会同时成立，续传方拿到 404 而
    不是续上的帧（两个键的寿命必须一起走）。
    """
    frame = encode_frame(seq, event)
    if len(frame) > MAX_FRAME_CHARS:
        logger.warning("事件帧超长，已截断：运行=%s 序号=%s 长度=%s", run_id, seq, len(frame))
        frame = frame[:MAX_FRAME_CHARS]
    await cache.rpush(events_key(run_id), frame, ttl_seconds=RUN_BUFFER_TTL_SECONDS)
    await cache.expire(meta_key(run_id), RUN_BUFFER_TTL_SECONDS)


async def read_events_after(cache: RedisCache, *, run_id: str, after_seq: int) -> list[tuple[int, str]]:
    """读序号大于 `after_seq` 的帧（含序号与原文），按序号升序。

    列表下标与序号的换算：序号从 1 开始，列表下标从 0 开始（第 n 条的下标是 n-1），
    因此「序号大于 after_seq」的下标起点就是 `after_seq`。这条换算只写在这里一处。
    """
    if after_seq < 0:
        after_seq = 0
    raw_frames = await cache.lrange(events_key(run_id), after_seq, -1)
    frames: list[tuple[int, str]] = []
    for raw in raw_frames:
        try:
            seq, _name = decode_frame(raw)
        except ValueError:
            logger.warning("事件缓冲里有一条解析不出的帧，已跳过：运行=%s", run_id)
            continue
        # 截断过的帧会解析失败（json 行不完整由调用方按需处理）：它仍带正确的 id 行，
        # 因此按原样交给调用方，由它决定怎么送给客户端。
        frames.append((seq, raw))
    return frames


async def last_event_seq(cache: RedisCache, *, run_id: str) -> int:
    """缓冲里最后一条事件的序号；缓冲为空或不存在时返回 0。"""
    frames = await cache.lrange(events_key(run_id), -1, -1)
    if not frames:
        return 0
    try:
        seq, _name = decode_frame(frames[-1])
    except ValueError:
        return 0
    return seq


# ---------------------------------------------------------------------------
# 推进器：把一次运行的事件写进缓冲
# ---------------------------------------------------------------------------


class RunStartupFailure(Exception):
    """运行在产出任何事件之前就失败了，因此没有 `run_id` 可返回。

    这是两段式形状的一个必然后果：订阅要一个 `run_id`，而 `run_id` 由基座在
    `run_started` 事件里给出（`agent/runtime/runner.py` 的 `run_id = uuid4().hex`
    在生成器内部生成，`RunRequest` 没有承载它的字段，面层无法预知）。因此
    「还没开始就失败」的运行没有可订阅的身份，只能作为本次 POST 的失败回复，
    而不是一条可以订阅的终态事件——契约第 8 节的 `run_failed` 变体在这里
    表达不出来，如实上报给编排器。

    不携带会话内容，只带错误码与类型级说明（与基座 `RunFailedEvent.detail`
    同一条纪律：面向排障，不含使用者内容）。
    """

    def __init__(self, code: str, detail: str) -> None:
        """记录失败码与说明。"""
        self.code = code
        self.detail = detail
        super().__init__(f"运行未能启动：{code}")


class RunPump:
    """一次运行的推进器：先推到首个事件，再在后台把余下事件写进缓冲。

    两段的方法而不是一个 `async def`：发消息端点必须在返回 202 之前拿到 `run_id`
    （否则没有可供订阅的路径段），因此首个事件由调用方在场时推进；余下的推进
    交给后台任务，让 POST 立刻返回。
    """

    def __init__(
        self,
        *,
        cache: RedisCache,
        runner: AgentRunner,
        request: RunRequest,
        account_id: str,
        lease: SessionRunLease,
    ) -> None:
        """绑定协作者与本次请求的会话位。"""
        self._cache = cache
        self._runner = runner
        self._request = request
        self._account_id = account_id
        self._lease = lease
        self._stream = runner.run(request)
        self._seq = 0

    @property
    def run_id(self) -> str | None:
        """已拿到的运行标识；尚未推进到 `run_started` 时为 `None`。"""
        return self._lease.run_id

    async def begin(self) -> str:
        """推进到首个事件并写入缓冲，返回 `run_id`。

        首个事件必然是 `run_started`（基座的形状约定：事件流以它为首项）。它若是
        `run_failed`，说明运行在起步阶段就失败了（例如会话真源不可读）——此时
        没有 `run_id`，抛 :class:`RunStartupFailure` 让端点回 503，而不是回一个
        订阅不了的 202。

        Raises:
            RunStartupFailure: 首个事件是 `run_failed`，或生成器在产出事件前
                抛异常/结束。
        """
        try:
            first = await self._stream.__anext__()
        except StopAsyncIteration as exc:
            raise RunStartupFailure("internal", "运行在产出任何事件之前就结束了") from exc
        except Exception as exc:  # noqa: BLE001 —— 起步阶段的任何异常都没有可订阅的身份
            raise RunStartupFailure("internal", f"运行起步失败（{type(exc).__name__}）") from exc

        run_id = getattr(first, "run_id", None)
        if event_name(first) != "run_started" or not isinstance(run_id, str) or not run_id:
            code = getattr(first, "code", "internal")
            detail = getattr(first, "detail", "运行未产出 run_started")
            raise RunStartupFailure(str(code), str(detail))

        self._seq = 1
        await append_event(self._cache, run_id=run_id, seq=self._seq, event=first)
        await bind_lease_run_id(self._cache, self._lease, run_id)
        await write_run_meta(
            self._cache,
            RunMeta(
                run_id=run_id,
                session_id=self._lease.session_id,
                account_id=self._account_id,
                status=RUN_STATUS_RUNNING,
            ),
        )
        return run_id

    async def drive(self) -> None:
        """后台推进：把余下事件写进缓冲，终结时落状态并释放会话位。

        无论正常结束、异常还是被取消，收尾都要做（`finally`）：一次没释放的会话位
        会让这个会话在 TTL 到期之前再也发不出消息，而 TTL 是 185 秒——使用者会
        看到「刚中断的对话再也发不出去」，这正是「终结时删键」要避免的。
        """
        run_id = self._lease.run_id
        if run_id is None:  # pragma: no cover —— drive 只在 begin 成功后调用
            return
        try:
            async for event in self._stream:
                self._seq += 1
                await append_event(self._cache, run_id=run_id, seq=self._seq, event=event)
                if event_name(event) in TERMINAL_EVENT_TYPES:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 —— 推进失败必须留下痕迹，不能让订阅方永远等
            logger.warning("运行推进中断：运行=%s 异常=%s", run_id, type(exc).__name__)
        finally:
            await self._finalize(run_id)

    async def _finalize(self, run_id: str) -> None:
        """落「已终结」状态并释放会话位；失败只记日志（TTL 是兜底）。"""
        try:
            await write_run_meta(
                self._cache,
                RunMeta(
                    run_id=run_id,
                    session_id=self._lease.session_id,
                    account_id=self._account_id,
                    status=RUN_STATUS_FINISHED,
                ),
            )
            await release_session_run(self._cache, self._lease)
        except Exception as exc:  # noqa: BLE001 —— 收尾失败不能让终态事件丢失；TTL 兜底
            logger.warning("运行收尾失败：运行=%s 异常=%s", run_id, type(exc).__name__)


#: 在跑的后台推进任务。持引用是为了不被 GC 回收（弱引用会让任务在无人看时消失），
#: 并在收尾时能等到它们结束——测试夹具靠它避免「上一个用例的推进写在下一个用例的库上」。
_pump_tasks: set[asyncio.Task[None]] = set()


def start_pump(pump: RunPump) -> asyncio.Task[None]:
    """把推进器交给后台任务并登记它。"""
    task = asyncio.create_task(pump.drive())
    _pump_tasks.add(task)
    task.add_done_callback(_pump_tasks.discard)
    return task


async def drain_pumps() -> None:
    """等待所有在跑的推进任务结束（测试夹具与进程收尾用）。

    先等到「集合为空」再返回：`add_done_callback` 在任务结束后才把它摘掉，
    因此只 `gather` 当前快照可能漏掉调用期间新起的任务。
    """
    while _pump_tasks:
        await asyncio.gather(*list(_pump_tasks), return_exceptions=True)


def cancel_pumps() -> None:
    """请求取消所有在跑的推进任务（进程收尾用）。不等待。"""
    for task in list(_pump_tasks):
        task.cancel()
