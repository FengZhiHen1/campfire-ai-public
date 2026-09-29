"""数据主库（PostgreSQL 17 + pgvector）的跨切能力。

归属（见 docs/项目结构设计.md 第 6 节）：提供连接与事务边界；
表结构与用例服务归各自的 ``modules/*``。

边界：``core/*`` 不得依赖 ``agent/*``、``surfaces/*``、``modules/*``（第 7 节）。
连接生命周期与数据访问层的端口形状尚未确定，故此处只有健康检查探针。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from campfire.core.config import Settings
from campfire.core.health import ComponentHealth, Status


async def check_database(settings: Settings) -> ComponentHealth:
    """探测主库可用性：建立连接并执行一次 ``SELECT 1``。

    失败时只回报异常类型，不复述连接串——连接串含凭据。

    实现说明：此处按调用创建并释放引擎。共享引擎的生命周期管理随真正的
    数据访问层一起落地，届时本函数改为复用该引擎。
    """
    if not settings.database_url:
        return ComponentHealth("database", Status.NOT_CONFIGURED, "未配置 DATABASE_URL")

    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 —— 探针吞掉一切驱动异常并如实上报
        return ComponentHealth("database", Status.UNAVAILABLE, f"连接失败（{type(exc).__name__}）")
    finally:
        await engine.dispose()

    return ComponentHealth("database", Status.OK, "连接正常")
