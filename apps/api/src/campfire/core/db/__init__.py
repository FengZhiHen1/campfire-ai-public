"""数据主库（PostgreSQL 17 + pgvector）的跨切能力。

归属（见 docs/项目结构设计.md 第 6 节）：提供连接与事务边界；
表结构与用例服务归各自的 ``modules/*``。

边界：``core/*`` 不得依赖 ``agent/*``、``surfaces/*``、``modules/*``（第 7 节）。

**表名前缀**：业务表统一用 ``campfire_`` 前缀，避免与 SuperTokens core 在自己库里
建的表、以及 SDK 自建表撞名——这是 ``docs/项目结构设计.md`` 第 10 节「表归属与
模块同名」的可执行形式。**``data_`` 前缀保留给 LlamaIndex 的 ``PGVectorStore``**
（它把 ``table_name`` 渲染为 ``data_<table_name>``，见 RAG 策略第 2 节），本项目
自己的模型不得使用该前缀。
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pgvector.sqlalchemy import Vector
from sqlalchemy import MetaData, text
from sqlalchemy import create_engine as create_engine_sync
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from campfire.core.config import Settings
from campfire.core.health import ComponentHealth, Status

#: 统一命名约定：让迁移脚本与约束名可预测，避免 ``--autogenerate`` 因默认名漂移
#: 反复生成改名迁移。
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

#: 全部业务表的元数据。Alembic 迁移与运行期共用同一份，保证两边不漂移。
metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """所有业务表模型的基类。"""

    metadata = metadata


#: 向量列类型的再导出：各模块从 ``core/db`` 取，避免各自 import 上游包。
__all__ = [
    "Base",
    "Vector",
    "check_database",
    "create_engine",
    "create_sync_engine",
    "dispose_engine",
    "get_engine",
    "get_session_factory",
    "metadata",
    "new_uuid",
    "session_scope",
    "to_sync_url",
]

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings) -> AsyncEngine:
    """按配置创建新的异步引擎（调用方负责释放）。

    Raises:
        RuntimeError: 未配置 ``DATABASE_URL`` 时——宁可显式失败，也不静默连到别处。
    """
    if not settings.database_url:
        raise RuntimeError("未配置 DATABASE_URL，无法创建数据库引擎")
    # pool_pre_ping：连接可能被网络或数据库重启中断，取用前先探活。
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def to_sync_url(async_url: str) -> str:
    """把异步连接串转成同步驱动形式（``+asyncpg`` → 驱动默认）。

    之所以存在：LlamaIndex 的 ``PGVectorStore`` 要求**同时**提供同步与异步引擎
    （实测 ``ValueError: Both engine and async_engine must be provided``），
    而本项目运行期只用 asyncpg。同步引擎仅用于该框架组件的写入路径。
    """
    return async_url.replace("postgresql+asyncpg://", "postgresql://")


def create_sync_engine(settings: Settings) -> Engine:
    """按配置创建同步引擎（供需要同步驱动的框架组件使用）。

    Raises:
        RuntimeError: 未配置 ``DATABASE_URL`` 时。
    """
    if not settings.database_url:
        raise RuntimeError("未配置 DATABASE_URL，无法创建数据库引擎")
    return create_engine_sync(to_sync_url(settings.database_url), pool_pre_ping=True)


def get_engine(settings: Settings) -> AsyncEngine:
    """返回进程内共享的引擎；首次调用时创建。"""
    global _engine
    if _engine is None:
        _engine = create_engine(settings)
    return _engine


def get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    """返回进程内共享的会话工厂。

    ``expire_on_commit=False``：提交后仍可读取对象属性，避免在事务边界外
    触发懒加载（那会在 async 上下文里报缺少 greenlet）。
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(settings), expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def session_scope(settings: Settings) -> AsyncIterator[AsyncSession]:
    """事务边界：正常退出提交，异常回滚。

    用例服务经此获得会话，不各自 ``commit``——撤下要求「同时改条目状态与删除
    该条目的节点」在同一事务内完成（RAG 策略第 2 节）。

    Raises:
        Exception: 透传块内异常（先回滚再抛出），不做吞并与转译。
    """
    factory = get_session_factory(settings)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """释放共享引擎（进程退出或测试收尾时调用）。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def new_uuid() -> uuid.UUID:
    """生成业务主键。集中在此，便于将来替换为有序 UUID 而不改各处。"""
    return uuid.uuid4()


async def check_database(settings: Settings) -> ComponentHealth:
    """探测主库可用性：建立连接并执行一次 ``SELECT 1``。

    失败时只回报异常类型，不复述连接串——连接串含凭据。

    实现说明：探针按调用创建并释放引擎，**不复用共享引擎**——健康检查不应被
    业务侧连接池状态影响，也不应为了探活把连接池拉起来。
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
