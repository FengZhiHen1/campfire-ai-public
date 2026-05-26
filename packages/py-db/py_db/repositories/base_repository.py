"""SEC-05 输入校验防护 — Repository 基类。

SQLAlchemy 2.0 AsyncSession 通用 Repository 基类。
提供参数化查询 CRUD 方法骨架和数据库连接失败重试逻辑。

所有数据库操作必须通过 Repository 类执行，禁止在 Service 层直接
调用 session.execute() 或字符串拼接 SQL。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------


class DependencyCommunicationError(Exception):
    """基础设施依赖不可达异常。

    在重试耗尽后抛出，表示数据库、缓存或其他基础设施服务不可达。
    向上层传递到 FastAPI 后返回 HTTP 503。
    """

    def __init__(self, message: str) -> None:
        self.message: str = message
        super().__init__(self.message)


# ---------------------------------------------------------------------------
# 重试配置常量
# ---------------------------------------------------------------------------

_MAX_RETRY_COUNT: int = 3
_RETRY_INTERVAL_SECONDS: float = 2.0

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 泛型类型变量
# ---------------------------------------------------------------------------

ModelT = TypeVar("ModelT")

# ---------------------------------------------------------------------------
# Repository 基类
# ---------------------------------------------------------------------------


class BaseRepository(Generic[ModelT]):
    """SQLAlchemy 2.0 异步 Repository 基类。

    提供通用的 CRUD 方法骨架，所有数据库操作通过 AsyncSession 参数化查询执行。
    包含连接失败重试逻辑（最大 3 次，固定间隔 2s），每次重试前关闭失效连接
    并从连接池获取新连接。

    子类必须设置 ``model`` 属性指向 SQLAlchemy ORM 模型类。

    Usage:
        class UserRepository(BaseRepository[UserModel]):
            model = UserModel
    """

    model: type[ModelT]

    def __init__(self, session_factory: Any) -> None:
        """初始化 Repository 实例。

        Args:
            session_factory: 异步会话工厂（callable），每次调用返回新的 AsyncSession。
        """
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # 内部辅助：带重试的操作执行器
    # ------------------------------------------------------------------

    async def _execute_with_retry(
        self,
        session: AsyncSession,
        operation_name: str,
        operation: Any,
    ) -> Any:
        """带重试逻辑的数据库操作执行器。

        对 OperationalError 和 SQLAlchemyTimeoutError 执行自动重试：
          - 最大重试 3 次，固定间隔 2s
          - 每次重试前关闭失效连接
          - 第 3 次仍失败 → 抛出 DependencyCommunicationError

        Args:
            session: 当前数据库会话。
            operation_name: 操作名称（用于日志）。
            operation: 无参异步可调用对象，返回操作执行结果。

        Returns:
            操作执行结果。

        Raises:
            DependencyCommunicationError: 重试耗尽后仍然失败。
        """
        last_exception: Exception | None = None

        for attempt in range(1, _MAX_RETRY_COUNT + 1):
            try:
                return await operation()
            except (OperationalError, SQLAlchemyTimeoutError) as exc:
                last_exception = exc
                _logger.warning(
                    "database_operation_failure",
                    extra={
                        "operation": operation_name,
                        "attempt": attempt,
                        "max_retries": _MAX_RETRY_COUNT,
                        "error": str(exc),
                    },
                )

                # 关闭失效连接
                try:
                    await session.close()
                except Exception:
                    pass

                if attempt < _MAX_RETRY_COUNT:
                    # 等待固定间隔后重新获取连接
                    await asyncio.sleep(_RETRY_INTERVAL_SECONDS)
                    # 从连接池获取新连接
                    try:
                        await session.connection()
                    except Exception:
                        pass

        # 所有重试均已耗尽
        raise DependencyCommunicationError(
            f"数据库操作 '{operation_name}' 在 {_MAX_RETRY_COUNT} 次重试后仍然失败: "
            f"{last_exception}"
        )

    # ------------------------------------------------------------------
    # 通用 CRUD 方法骨架
    # ------------------------------------------------------------------

    async def create(self, session: AsyncSession, entity: ModelT) -> ModelT:
        """创建单条记录。

        使用参数化 INSERT 操作，自动通过 SQLAlchemy ORM 的 bindparam() 绑定参数。

        Args:
            session: 活动数据库会话。
            entity: 待创建的 ORM 模型实例。

        Returns:
            创建成功后的实体（含数据库生成的字段如 ID、时间戳）。

        Raises:
            DependencyCommunicationError: 数据库连接失败且重试耗尽。
        """
        async def _create() -> ModelT:
            session.add(entity)
            await session.flush()
            await session.refresh(entity)
            return entity

        return await self._execute_with_retry(session, "create", _create)

    async def find_by_id(
        self, session: AsyncSession, entity_id: Any
    ) -> ModelT | None:
        """通过主键 ID 查询单条记录。

        使用参数化 SELECT ... WHERE id = :id 查询。

        Args:
            session: 活动数据库会话。
            entity_id: 实体主键值。

        Returns:
            匹配的实体，不存在时返回 None。

        Raises:
            DependencyCommunicationError: 数据库连接失败且重试耗尽。
        """
        async def _find() -> ModelT | None:
            stmt: Select = select(self.model).where(self.model.id == entity_id)
            result = await session.execute(stmt)
            return result.scalars().first()

        return await self._execute_with_retry(session, "find_by_id", _find)

    async def find_all(
        self,
        session: AsyncSession,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ModelT]:
        """分页查询全部记录。

        使用参数化 SELECT ... LIMIT :limit OFFSET :offset 查询。

        Args:
            session: 活动数据库会话。
            offset: 分页偏移量（默认 0）。
            limit: 每页记录数（默认 100）。

        Returns:
            实体列表，无记录时返回空列表。

        Raises:
            DependencyCommunicationError: 数据库连接失败且重试耗尽。
        """
        async def _find_all() -> list[ModelT]:
            stmt: Select = select(self.model).offset(offset).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(session, "find_all", _find_all)

    async def update(
        self,
        session: AsyncSession,
        entity: ModelT,
    ) -> ModelT:
        """更新单条记录。

        使用参数化 UPDATE 操作（session.merge），
        自动通过 SQLAlchemy ORM 的 bindparam() 绑定参数。

        Args:
            session: 活动数据库会话。
            entity: 包含更新值的 ORM 模型实例（必须已设置主键）。

        Returns:
            更新后的实体（合并后的持久化实例）。

        Raises:
            DependencyCommunicationError: 数据库连接失败且重试耗尽。
        """
        async def _update() -> ModelT:
            merged = await session.merge(entity)
            await session.flush()
            await session.refresh(merged)
            return merged

        return await self._execute_with_retry(session, "update", _update)

    async def delete(
        self,
        session: AsyncSession,
        entity: ModelT,
    ) -> None:
        """删除单条记录。

        使用参数化 DELETE 操作。

        Args:
            session: 活动数据库会话。
            entity: 待删除的 ORM 模型实例。

        Returns:
            None

        Raises:
            DependencyCommunicationError: 数据库连接失败且重试耗尽。
        """
        async def _delete() -> None:
            await session.delete(entity)
            await session.flush()

        await self._execute_with_retry(session, "delete", _delete)
