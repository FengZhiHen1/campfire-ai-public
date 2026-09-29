"""后台执行：Taskiq broker 装配与队列积压探测。

归属（见 docs/项目结构设计.md 第 6 节）：Worker 侧的投递与消费入口。

失败语义（见 docs/技术栈设计.md 第 5 节）：**待处理记录（PostgreSQL）是真相源，
队列只负责投递**；丢的任务必须可被检测与补救，不得静默丢弃、不得假装成功。

broker 选择 ``ListQueueBroker``（Redis 列表）而非 ``RedisStreamBroker``：
真相源不在队列，积压与丢失由待处理记录的记账发现，队列无需自带消费组与 ack
语义。重访条件：出现列表模型无法表达的投递保证需求。
"""

import redis.asyncio as aioredis
from taskiq_redis import ListQueueBroker

from campfire.core.config import Settings
from campfire.core.health import ComponentHealth, Status


def build_broker(settings: Settings) -> ListQueueBroker:
    """构造 Taskiq broker。装配处（``main.py`` / ``worker.py``）各自调用一次。"""
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
