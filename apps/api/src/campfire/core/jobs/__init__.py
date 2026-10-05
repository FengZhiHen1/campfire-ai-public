"""后台执行：Taskiq broker 装配与队列积压探测。

职责：装配 broker、投递待处理记录、探测队列可达性与积压。
边界：队列只负责投递，不是真相源；本模块不判断积压是否异常。
参考：`docs/项目结构设计.md` 第 6 节；`docs/技术栈设计.md` 第 5 节。
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from taskiq_redis import ListQueueBroker

from campfire.core.config import Settings
from campfire.core.health import ComponentHealth, Status

logger = logging.getLogger(__name__)

#: 投递钩子（装配处设置一次）。必须是协程函数：Taskiq 的 `kiq()` 返回协程，
#: 不 await 就等于没有投递（mypy 的 `unused-coroutine` 抓到过这个错误）。
#:
#: 为什么是钩子而不是直接 import 任务：
#:
#: 投递需要任务对象（`consume_memory_episode_task.kiq`），而它定义在 `worker.py`——那是
#: 入口模块，不属于任何层。产品侧工具（`tools/*`）的白名单只有 `agent/tools`、
#: `modules/*` 与 `core/*`（见 docs/项目结构设计.md 第 7 节），
#: 因此 `tools/*` 不得 import `campfire.worker`（`test_layer_boundaries.py` 会判失败）。
#: 由装配处把投递函数注入本模块，工具只依赖 `core/*`，依赖方向保持单向。
#:
#: 钩子契约——按 `kind` 分派（写入路径第 4 节第 3 条）：
#:
#: 入参是 `(pending_id, kind)`，钩子据 kind 投给对应的消费者。三种结果都由钩子负责：
#:   1. 有消费者：投出去；
#:   2. 该 kind 尚无消费者：显式跳过并记日志，
#:      记录留在 `pending`——不得抛错、不得终结记录，也不得改投别的消费者；
#:      **⚠ 当前两个 kind（`memory_episode`、`profile_item`）【都有】消费者**
#:      （`worker.py` 的 `_CONSUMER_DISPATCHERS`：`_enqueue_memory_episode` / `_enqueue_profile_item`
#:      分别投给 `consume_memory_episode_task` / `consume_profile_item_task`）⇒
#:      **本分支是【为将来新增 kind 留的】，不是描述现状**。
#:      （2026-10-06 订正：此处原写「例如 `profile_item` 的消费分支未落地」——
#:      该陈述在写下时是事实，此后 `consume_profile_item_task` 已落地并接线，
#:      而这句注释没人撤销。本仓已多次因这类过期注释误判，故在此写明当前事实。）
#:   3. broker 不可用：抛错，由本模块降级为「留给兜底扫描」。
#: 这些分支在钩子那一侧（`worker.dispatch_pending_write_to_queue`），因为「谁有消费者」
#: 是装配处的事实。
#:
#: 未设置时的行为：
#:
#: 不抛异常，只记 warning：记录已在事务里落库，留在 `pending`，由兜底扫描重投
#: （见 docs/技术设计/technical-details/写入路径.md 第 4.1 节）。
#: 投递失败本来就不改变本次回执——回执承诺的是「已提交」，不是「已保存」。
_dispatch_hook: Callable[[str, str], Awaitable[object]] | None = None


def set_dispatch_hook(hook: Callable[[str, str], Awaitable[object]] | None) -> None:
    """设置（或清除）投递钩子。只在装配处调用。

    两个入口都要设：Worker 侧（兜底扫描经它重投）与 API 侧（请求事务提交后投递，
    写入路径第 4 节第 1 条）。漏设 API 侧时投递全部落进下面的 warning，所有写入
    都要等 Worker 每 5 分钟的兜底扫描——2026-09-30 修复前正是这个状态。

    传 `None` 可清除——测试据此隔离彼此，避免钩子跨用例泄漏。
    """
    global _dispatch_hook
    _dispatch_hook = hook


async def dispatch_pending_write(pending_id: str, kind: str) -> None:
    """把一条待处理记录按 `kind` 投递给队列；投递失败不让调用方失败。

    `kind` 是必填而不是可省：投给谁由它决定（第 4 节第 3 条）。省掉它就只能一律投给
    同一个消费者，那会把异构的记录送进不懂它的消费者手里。

    失败语义（见 docs/技术栈设计.md 第 5 节）：待处理记录（PostgreSQL）是真相源，
    队列只负责投递；丢的任务必须可被检测与补救，不得静默丢弃、不得假装成功。
    「该 kind 尚无消费者」不在这里判——那是装配处的事实，由钩子显式跳过并记日志，
    记录留在 `pending`，不是投递失败。
    """
    if _dispatch_hook is None:
        logger.warning("投递钩子未设置，记录留给兜底扫描：pending_id=%s kind=%s", pending_id, kind)
        return
    try:
        await _dispatch_hook(pending_id, kind)
    except Exception as exc:  # noqa: BLE001 —— 投递失败由兜底扫描补救，不改变本次回执
        # 只记标识与异常类型：异常消息可能带连接串（AGENTS.md 安全条款）。
        # 类型名是归因所需的最小信息：broker 未启动、Redis 连接被拒、队列名写错
        # 都表现为同一条「投递失败」，没有类型名就分不出是哪一类。
        # 不复述异常消息、也不带 exc_info——消息与回溯都可能含连接串。
        logger.warning(
            "投递失败，记录留给兜底扫描：pending_id=%s kind=%s 异常类型=%s",
            pending_id,
            kind,
            type(exc).__name__,
        )


#: `brpop` 的**服务端**阻塞时长（秒）：Redis 侧最多挂住这么久，然后正常返回 `nil`。
#:
#: 为什么不能沿用上游的 `brpop(self.queue_name)`（服务端 `timeout=0` = 永久阻塞）：
#: redis-py 8.1.0 的 `DEFAULT_SOCKET_TIMEOUT` 是 **5 秒**（`redis/_defaults.py:7`），而
#: `AbstractConnection.read_response(timeout=None)` 会**回落到** `self.socket_timeout`
#: （`redis/asyncio/connection.py:1277`），且其超时分支**抛** `redis.exceptions.TimeoutError`
#: （同文件 1303-1310）而不是返回 `None`——只有调用方**显式**传了 `timeout` 才返回 `None`。
#: 该异常不是内建 `ConnectionError` 的子类（MRO 实测为 `TimeoutError → RedisError → Exception`），
#: 而 `taskiq_redis/redis_broker.py:136` 捕的是内建 `ConnectionError`
#: （该文件只从 redis 导入了 `ResponseError`；实测 `"ConnectionError" in
#: redis_broker.__dict__` 为 `False`，即那个 handler 连 redis 自己的 `ConnectionError`
#: 也接不住）⇒ 异常逃出 `listen()` 生成器 ⇒ Taskiq 判 worker 子进程死亡并重启
#: ⇒ 空闲队列上每约 10 秒一轮（实测默认装配 62 秒内崩 12 次，见报告第 2 节）。
#:
#: 修法是**换一种「等」的方式**：让服务端只在有限时间内阻塞，`nil` 是**正常返回**、
#: 不产生任何异常，于是「空闲」不再是一条异常路径。这也同时消掉了任务包点名的
#: `socket_timeout=None` 的副作用——见 :data:`QUEUE_SOCKET_TIMEOUT_SECONDS`。
#:
#: 仍用 `brpop`（不换成 `blpop`）是为了**保住先进先出**：`kick()` 走 `lpush`
#: （推入表头），因此必须从表尾 `brpop` 取出才是 FIFO；换成 `blpop` 会变成后进先出，
#: 让队列顺序倒转。这是本修法唯一一处容易顺手改错的地方。
QUEUE_BLOCK_SECONDS = 2

#: 单次读取的客户端上界（秒）——「连接卡死」的检测上界。
#:
#: **必须明显大于** :data:`QUEUE_BLOCK_SECONDS`：实测（报告第 3 节 P3）当
#: `socket_timeout=1` 而服务端 block=2 时，**客户端读超时先触发**并抛 `TimeoutError`
#: ⇒ 又回到崩溃循环。反过来，只要它大于服务端 block，正常的空闲返回就永远走不到
#: 超时分支（实测 P2：`socket_timeout=10` + 服务端 block=2 → 2.05 秒正常返回 `None`，
#: 无异常）。两者的大小关系由 `test_jobs_broker_idle_resilience.py` 机械钉住。
#:
#: 它保留的意义（**这就是不选 `socket_timeout=None` 的理由**）：对端变成「黑洞」
#: （socket 还在、但永不回数据）时，这个上界会让读取失败、连接被丢弃、循环重连
#: ⇒ 故障在约 10 秒内变成可观察的重试，而不是无限等。实测对照（报告第 3 节 P5）：
#: `socket_timeout=None` 在黑洞下撑满 13 秒预算仍在阻塞、无返回无异常；
#: 有限值则在约 4 秒内抛 `TimeoutError`。
QUEUE_SOCKET_TIMEOUT_SECONDS = 10

#: 读取失败后的退避（秒），避免 Redis 不可用时把 CPU 与日志打满。
QUEUE_ERROR_BACKOFF_SECONDS = 1.0

#: 连续失败时，每多少次重新打一条 WARNING；其余降到 DEBUG。
#:
#: Redis 长时间不可用时每轮都打 WARNING 会淹掉日志（生产 worker 的 json-file 是
#: `max-size: 20m`，1 条/3 秒足以把窗口刷没）。但**完全不报**又会让「Worker 一直连不上
#: Redis」在日志里看不见——因此第一次必报、之后按周期复报。
QUEUE_ERROR_WARN_EVERY = 20


def _log_listen_failure(failures: int, exc: BaseException) -> None:
    """记一次队列读取失败；只回报异常**类型**，不复述可能含连接串的消息。

    按 :data:`QUEUE_ERROR_WARN_EVERY` 降频：第 1 次与每第 N 次打 WARNING，
    其余打到 DEBUG——既不淹没日志，也不让「一直连不上」变成静默。
    """
    level = logging.WARNING if failures == 1 or failures % QUEUE_ERROR_WARN_EVERY == 0 else logging.DEBUG
    logger.log(
        level, "队列读取失败（连续第 %d 次，%s 后重试）：%s", failures, QUEUE_ERROR_BACKOFF_SECONDS, type(exc).__name__
    )


class ResilientListQueueBroker(ListQueueBroker):
    """`ListQueueBroker`，但**空闲不是异常路径**，且 Redis 挂掉时可自愈。

    为什么要有这个子类（而不是给上游传个参数了事）：上游 `listen()` 用的是
    `brpop` + 服务端 `timeout=0`，于是「队列为空」这件事只能靠**客户端读超时**收场，
    而那条路径是抛异常；上游只捕内建 `ConnectionError`，捕不住 redis 的
    `TimeoutError`，也捕不住 redis 自己的 `ConnectionError`（见类内注释与报告第 3 节
    T1/T2 的实测）。参数层面**没有**任何一个 `socket_timeout` 取值能同时满足
    「空闲不崩」与「卡死可发现」：`None` 会让黑洞变成无限等（实测 P5），有限值则
    空闲必崩——实测 `socket_timeout=15` 只是把崩溃周期从约 10 秒拉长到约 20 秒
    （`tmp/T17/ablation_st15.err.log`：55 秒内仍崩 2 次 / 重启 2 次）。
    因此缺口只能在读取循环这一层补：把「等」改成有界的服务端阻塞，
    并把「客户端上界」只用作卡死检测。

    不改上游源码：`taskiq_redis` / `redis` 是 vendored 依赖（任务包硬约束），
    本类只覆盖 `listen()` 一个方法，其余（`kick`、结果后端、启动事件）全部继承。

    「Redis 真的挂了」时的行为（实测，报告第 3 节 P6/T2）：
    对端断开时 `brpop` 立刻抛 `redis.exceptions.ConnectionError`；对端进程没了
    （端口拒绝连接）时同样是该异常（实测 2.03 秒内抛出）。两条都被本类捕获、
    记一条日志、退避后重连：**Worker 不退出**（没有异常逃出生成器 ⇒ Taskiq 不重启
    它），只是持续重试，Redis 回来后自动恢复消费——实测 P7：断开 20 秒后重连成功。
    """

    async def listen(self) -> AsyncGenerator[bytes, None]:
        """在队列上循环取消息；空闲与连接故障都只是「再等一轮」。

        与上游 `listen()` 的三处差别（每一处都对应一条实测读数）：

        1. 服务端 block 有限（:data:`QUEUE_BLOCK_SECONDS`），空队列返回 `nil`
           ⇒ 空闲不抛异常，这是崩溃循环的直接消除点；
        2. 捕获 redis 的 `TimeoutError` 与 `ConnectionError` **两者**——上游只捕
           内建 `ConnectionError`，而实测两者都不是它的子类（`issubclass` 均为
           `False`）⇒ 上游那个 handler 一个都接不住（报告第 3 节 T1/T2）；
        3. 复用同一个 `Redis` 客户端而不是每轮进出一次上下文：上游那写法每轮
           建/放一次连接，而 `brpop` 在服务端阻塞期间该连接是被占住的，
           故障时反复建连的代价白付。

        语义与上游一致：yield **裸 bytes**（不是 `AckableMessage`）。
        列表模型没有 ack/消费组——真相源是待处理记录（见 `build_broker` 的说明），
        因此这里不做「至少一次」承诺，也不得凭空加上 ack 语义。
        """
        failures = 0
        async with Redis(connection_pool=self.connection_pool) as redis_conn:
            while True:
                try:
                    # 位置 1 是列表元素本身（位置 0 是键名），与上游一致。
                    result = await redis_conn.brpop(self.queue_name, timeout=QUEUE_BLOCK_SECONDS)
                except (RedisTimeoutError, RedisConnectionError) as exc:
                    # 必须用**显式导入**的 redis 异常类型：本模块顶部 `import redis.asyncio`
                    # 而没有把 `redis.exceptions` 的名字带进来，写裸 `ConnectionError`
                    # 会解析到内建类型——那正是上游 handler 失效的原因，不能重蹈。
                    failures += 1
                    _log_listen_failure(failures, exc)
                    await asyncio.sleep(QUEUE_ERROR_BACKOFF_SECONDS)
                    continue
                if failures:
                    logger.info("队列连接已恢复（此前连续失败 %d 次）", failures)
                    failures = 0
                if result is None:
                    # 空队列：正常返回。直接进入下一轮阻塞，不额外 sleep——`brpop`
                    # 本身已经等了 QUEUE_BLOCK_SECONDS，再加 sleep 只会拖慢新任务的接手。
                    continue
                # `type: ignore[misc]` 与上游同一处：redis-py 的 stub 把 BLPOP/BRPOP
                # 的返回标注为 `list[bytes | str]`，而 `decode_responses` 未开启时
                # 实际总是 `bytes`（`build_broker` 不传该开关，与上游装配一致）。
                # 不用 `cast` 掩盖：str 只可能在有人另开 `decode_responses` 时出现，
                # 那种改动会让这里立刻在类型检查上暴露，而不是静默错。
                yield result[1]  # type: ignore[misc]


def build_broker(settings: Settings) -> ResilientListQueueBroker:
    """构造 Taskiq broker。装配处（`main.py` / `worker.py`）各自调用一次。

    归属（见 docs/项目结构设计.md 第 6 节）：Worker 侧的投递与消费入口。

    broker 选择 `ListQueueBroker`（Redis 列表）而非 `RedisStreamBroker`：
    真相源不在队列，积压与丢失由待处理记录的记账发现，队列无需自带消费组与 ack
    语义。重访条件：出现列表模型无法表达的投递保证需求。

    返回 :class:`ResilientListQueueBroker`（`ListQueueBroker` 的子类，唯一差别是
    `listen()` 不把「空闲」当异常，并在 Redis 不可用时重试而不是让进程退出）。
    为什么需要它、以及为什么不选别的 `socket_timeout` 取值：见该类与
    :data:`QUEUE_SOCKET_TIMEOUT_SECONDS` 的说明。

    `socket_timeout` 必须显式传：redis-py 8.1.0 的默认值是 5 秒，与 2 秒的服务端
    阻塞只差一点点，一旦网络慢于预期就会退回「客户端读超时」那条异常路径。
    这里给 10 秒——对本地/容器内网都足够宽（正常 RTT 是毫秒级），同时仍是有界值，
    因此不选 `None`（那会让「Redis 静默卡死」变成无限等）。
    """
    return ResilientListQueueBroker(
        url=settings.redis_url,
        queue_name=settings.taskiq_queue_name,
        socket_timeout=QUEUE_SOCKET_TIMEOUT_SECONDS,
    )


async def check_queue(settings: Settings) -> ComponentHealth:
    """探测队列：Redis 可达性与待消费积压条数。

    「异步滞后」以积压条数如实报告。本探针不判断积压是否异常——阈值属于运行期
    告警策略，尚未确定，不在此处发明。
    """
    client = aioredis.from_url(settings.redis_url)
    try:
        pending = await client.llen(settings.taskiq_queue_name)
    except Exception as exc:  # noqa: BLE001 —— 探针吞掉一切驱动异常并如实上报
        return ComponentHealth("queue", Status.UNAVAILABLE, f"Redis 不可达（{type(exc).__name__}）")
    finally:
        await client.aclose()

    return ComponentHealth("queue", Status.OK, f"待消费 {pending} 条")
