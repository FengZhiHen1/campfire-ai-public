"""后台执行：Taskiq broker 装配与队列积压探测。

职责：装配 broker、投递待处理记录、探测队列可达性与积压。
边界：队列只负责投递，不是真相源；本模块不判断积压是否异常。
参考：`docs/项目结构设计.md` 第 6 节；`docs/技术栈设计.md` 第 5 节。
"""

import logging
from collections.abc import Awaitable, Callable

import redis.asyncio as aioredis
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
#:   2. 该 kind 尚无消费者（例如 `profile_item` 的消费分支未落地）：显式跳过并记日志，
#:      记录留在 `pending`——不得抛错、不得终结记录，也不得改投别的消费者；
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
    except Exception:  # noqa: BLE001 —— 投递失败由兜底扫描补救，不改变本次回执
        # 只记标识与异常类型：异常消息可能带连接串（AGENTS.md 安全条款）。
        logger.warning("投递失败，记录留给兜底扫描：pending_id=%s kind=%s", pending_id, kind)


def build_broker(settings: Settings) -> ListQueueBroker:
    """构造 Taskiq broker。装配处（`main.py` / `worker.py`）各自调用一次。

    归属（见 docs/项目结构设计.md 第 6 节）：Worker 侧的投递与消费入口。

    broker 选择 `ListQueueBroker`（Redis 列表）而非 `RedisStreamBroker`：
    真相源不在队列，积压与丢失由待处理记录的记账发现，队列无需自带消费组与 ack
    语义。重访条件：出现列表模型无法表达的投递保证需求。
    """
    return ListQueueBroker(url=settings.redis_url, queue_name=settings.taskiq_queue_name)


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
