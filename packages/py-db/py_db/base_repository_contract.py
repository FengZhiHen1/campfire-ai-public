"""py-db 仓储基类契约 — ABC 模板方法定义。

模块: py_db.base_repository_contract
职责: 定义通用异步 Repository 的 ABC 契约骨架。@final CRUD 方法强制执行
      参数化查询 + 连接失败重试的模板流程，实现者通过继承获得安全的数据库操作能力。
数据来源:
  - SQLAlchemy 2.0 AsyncSession: MUST — 异步数据库会话，所有操作通过其执行
  - py_logger.logger: MUST — 结构化日志全局单例，记录重试和操作事件
边界:
  - 依赖: py_db.exceptions, py_logger, sqlalchemy
  - 被依赖: 所有具体 Repository 子类（CaseRepository, UserRepository 等）
禁止行为:
  - 禁止在 @final 方法之外暴露 CRUD 入口
  - 禁止在 Service 层直接调用 session.execute() 或拼接 SQL
  - 禁止在子类中覆写 @final CRUD 方法
  - 禁止在循环体内执行数据库查询——使用批量操作
"""

from __future__ import annotations

import asyncio
from abc import ABC
from typing import Any, Generic, TypeVar, final

from py_logger import logger
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.exceptions import RepositoryCommunicationError

# ---------------------------------------------------------------------------
# 重试配置常量
# ---------------------------------------------------------------------------

_MAX_RETRY_COUNT: int = 3  # 共 3 次尝试（1 主 + 2 重试）
_RETRY_INTERVAL_SECONDS: float = 2.0

# ---------------------------------------------------------------------------
# 泛型类型变量
# ---------------------------------------------------------------------------

ModelT = TypeVar("ModelT")


# ============================================================================
# BaseRepository — 异步仓储契约 ABC
# ============================================================================


class BaseRepository(ABC, Generic[ModelT]):
    """SQLAlchemy 2.0 异步 Repository 契约基类。

    提供 @final CRUD 方法骨架，所有数据库操作通过 AsyncSession 参数化查询执行。
    包含连接失败重试逻辑（最大 3 次，固定间隔 2s），重试耗尽抛出
    RepositoryCommunicationError。

    子类必须设置 model 属性指向 SQLAlchemy ORM 模型类。

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

    # ==================================================================
    # 内部机制：带重试的操作执行器
    # ==================================================================

    async def _execute_with_retry(
        self,
        session: AsyncSession,
        operation_name: str,
        operation: Any,
    ) -> Any:
        """带重试逻辑的数据库操作执行器。

        对 OperationalError 和 TimeoutError 执行自动重试：
          - 最大重试 3 次，固定间隔 2s
          - 每次重试前关闭失效连接
          - 重试耗尽 → 抛出 RepositoryCommunicationError
          通过 py_logger 记录每次重试事件。

        子类可通过覆写此方法自定义重试策略。

        输入约束:
          - session: 当前活动数据库会话
          - operation_name: 操作名称（用于日志标识）
          - operation: 无参异步可调用对象
        输出约束:
          - 返回操作执行结果
        异常:
          - RepositoryCommunicationError: 重试耗尽后仍然失败
        Side Effects:
          - 通过 py_logger 记录结构化日志（重试事件）
          - 关闭失效连接并从连接池获取新连接
        """
        last_exception: Exception | None = None

        for attempt in range(1, _MAX_RETRY_COUNT + 1):
            try:
                return await operation()
            except (OperationalError, SQLAlchemyTimeoutError) as exc:
                last_exception = exc
                logger.warning(
                    service="py-db",
                    message="database_operation_failure",
                    extra={
                        "operation": operation_name,
                        "attempt": attempt,
                        "max_retries": _MAX_RETRY_COUNT,
                        "error": str(exc),
                    },
                    op_type="repository_retry",
                )

                try:
                    await session.close()
                except Exception:
                    pass

                if attempt < _MAX_RETRY_COUNT:
                    await asyncio.sleep(_RETRY_INTERVAL_SECONDS)
                    try:
                        await session.connection()
                    except Exception:
                        pass

        raise RepositoryCommunicationError(
            f"数据库操作 '{operation_name}' 在 {_MAX_RETRY_COUNT} 次重试后仍然失败: "
            f"{last_exception}",
            operation_name=operation_name,
            retries_attempted=_MAX_RETRY_COUNT,
        )

    # ==================================================================
    # @final CRUD 方法 — 子类不可覆写
    # ==================================================================

    @final
    async def create(self, session: AsyncSession, entity: ModelT) -> ModelT:
        """创建单条记录。

        使用参数化 INSERT 操作，自动通过 SQLAlchemy ORM bindparam() 绑定参数。

        前置: session 为活动 AsyncSession，entity 为有效的 ORM 模型实例
        后置: entity 已持久化到数据库（含生成的 ID、时间戳等字段）
        输入约束:
          - session: 活动 AsyncSession
          - entity: 符合 model 类型的 ORM 实例
        输出约束:
          - 返回刷新后的持久化实体
        异常:
          - RepositoryCommunicationError: 数据库连接失败且重试耗尽
        Side Effects:
          - 数据库 INSERT 操作
          - 通过 py_logger 记录结构化日志（失败重试时）
        """
        self._validate_entity_not_none(entity)
        result = await self._execute_with_retry(
            session, "create", lambda: self._do_create(session, entity)
        )
        self._validate_result_not_none(result, "create")
        return result

    @final
    async def find_by_id(
        self,
        session: AsyncSession,
        entity_id: Any,
    ) -> ModelT | None:
        """通过主键 ID 查询单条记录。

        使用参数化 SELECT ... WHERE id = :id 查询。

        前置: session 为活动 AsyncSession
        后置: 返回匹配实体或 None
        输入约束:
          - session: 活动 AsyncSession
          - entity_id: 实体的主键值（类型由模型定义）
        输出约束:
          - 存在时返回实体，不存在时返回 None
        异常:
          - RepositoryCommunicationError: 数据库连接失败且重试耗尽
        Side Effects:
          - 数据库 SELECT 操作（只读）
          - 通过 py_logger 记录结构化日志（失败重试时）
        """
        self._validate_entity_id_not_none(entity_id)
        result = await self._execute_with_retry(
            session, "find_by_id", lambda: self._do_find_by_id(session, entity_id)
        )
        self._validate_find_result(result, entity_id)
        return result

    @final
    async def find_all(
        self,
        session: AsyncSession,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ModelT]:
        """分页查询全部记录。

        使用参数化 SELECT ... LIMIT :limit OFFSET :offset 查询。

        前置: session 为活动 AsyncSession
        后置: 返回实体列表（无记录时为空列表）
        输入约束:
          - session: 活动 AsyncSession
          - offset: >= 0 的整数
          - limit: > 0 的整数
        输出约束:
          - 返回 list[ModelT]，无记录时返回空列表
        异常:
          - RepositoryCommunicationError: 数据库连接失败且重试耗尽
        Side Effects:
          - 数据库 SELECT 操作（只读）
          - 通过 py_logger 记录结构化日志（失败重试时）
        """
        self._validate_pagination_params(offset, limit)
        result = await self._execute_with_retry(
            session, "find_all", lambda: self._do_find_all(session, offset, limit)
        )
        self._validate_result_is_list(result, "find_all")
        return result

    @final
    async def update(
        self,
        session: AsyncSession,
        entity: ModelT,
    ) -> ModelT:
        """更新单条记录。

        使用参数化 UPDATE 操作（session.merge），自动通过 bindparam() 绑定参数。

        前置: session 为活动 AsyncSession，entity 已设置主键
        后置: entity 的变更已持久化到数据库
        输入约束:
          - session: 活动 AsyncSession
          - entity: 包含更新值的 ORM 实例（主键必须已设置）
        输出约束:
          - 返回合并后的持久化实体
        异常:
          - RepositoryCommunicationError: 数据库连接失败且重试耗尽
        Side Effects:
          - 数据库 UPDATE 操作
          - 通过 py_logger 记录结构化日志（失败重试时）
        """
        self._validate_entity_not_none(entity)
        result = await self._execute_with_retry(
            session, "update", lambda: self._do_update(session, entity)
        )
        self._validate_result_not_none(result, "update")
        return result

    @final
    async def delete(
        self,
        session: AsyncSession,
        entity: ModelT,
    ) -> None:
        """删除单条记录。

        使用参数化 DELETE 操作。

        前置: session 为活动 AsyncSession，entity 为已存在的持久化实体
        后置: entity 已从数据库删除
        输入约束:
          - session: 活动 AsyncSession
          - entity: 待删除的 ORM 实例
        异常:
          - RepositoryCommunicationError: 数据库连接失败且重试耗尽
        Side Effects:
          - 数据库 DELETE 操作
          - 通过 py_logger 记录结构化日志（失败重试时）
        """
        self._validate_entity_not_none(entity)
        await self._execute_with_retry(
            session, "delete", lambda: self._do_delete(session, entity)
        )
        self._validate_delete_completed()

    # ==================================================================
    # _do_ 钩子 — 标准 SQLAlchemy 操作（子类可按需覆写）
    # ==================================================================

    async def _do_create(self, session: AsyncSession, entity: ModelT) -> ModelT:
        """执行 INSERT 操作。

        实现者可按需覆写以添加自定义创建逻辑。
        不需要关心重试和连接管理——@final create 已通过 _execute_with_retry 处理。
        """
        session.add(entity)
        await session.flush()
        await session.refresh(entity)
        return entity

    async def _do_find_by_id(
        self, session: AsyncSession, entity_id: Any
    ) -> ModelT | None:
        """执行 SELECT ... WHERE id = :id 查询。

        实现者可按需覆写以添加自定义查询逻辑。
        不需要关心重试和连接管理——@final find_by_id 已通过 _execute_with_retry 处理。
        """
        stmt = select(self.model).where(self.model.id == entity_id)
        result = await session.execute(stmt)
        return result.scalars().first()

    async def _do_find_all(
        self, session: AsyncSession, offset: int, limit: int
    ) -> list[ModelT]:
        """执行 SELECT ... LIMIT OFFSET 分页查询。

        实现者可按需覆写以添加自定义查询逻辑。
        不需要关心重试和连接管理——@final find_all 已通过 _execute_with_retry 处理。
        """
        stmt = select(self.model).offset(offset).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def _do_update(self, session: AsyncSession, entity: ModelT) -> ModelT:
        """执行 UPDATE 操作（session.merge）。

        实现者可按需覆写以添加自定义更新逻辑。
        不需要关心重试和连接管理——@final update 已通过 _execute_with_retry 处理。
        """
        merged = await session.merge(entity)
        await session.flush()
        await session.refresh(merged)
        return merged

    async def _do_delete(self, session: AsyncSession, entity: ModelT) -> None:
        """执行 DELETE 操作。

        实现者可按需覆写以添加自定义删除逻辑。
        不需要关心重试和连接管理——@final delete 已通过 _execute_with_retry 处理。
        """
        await session.delete(entity)
        await session.flush()

    # ==================================================================
    # 校验器 — 模板提供基线校验
    # ==================================================================

    @staticmethod
    def _validate_entity_not_none(entity: ModelT) -> None:
        """基线校验：实体不能为 None。

        异常:
          - ValueError: entity 为 None。
        """
        if entity is None:
            raise ValueError("entity must not be None")

    @staticmethod
    def _validate_entity_id_not_none(entity_id: Any) -> None:
        """基线校验：实体 ID 不能为 None。

        异常:
          - ValueError: entity_id 为 None。
        """
        if entity_id is None:
            raise ValueError("entity_id must not be None")

    @staticmethod
    def _validate_pagination_params(offset: int, limit: int) -> None:
        """基线校验：分页参数合法性。

        异常:
          - ValueError: offset < 0 或 limit <= 0。
        """
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        if limit <= 0:
            raise ValueError(f"limit must be > 0, got {limit}")

    @staticmethod
    def _validate_result_not_none(result: ModelT, operation: str) -> None:
        """后置校验：操作结果不能为 None。

        异常:
          - RuntimeError: result 为 None。
        """
        if result is None:
            raise RuntimeError(
                f"{operation} returned None after successful execution"
            )

    @staticmethod
    def _validate_result_is_list(result: list[ModelT], operation: str) -> None:
        """后置校验：查询结果必须为 list。

        异常:
          - RuntimeError: result 不是 list。
        """
        if not isinstance(result, list):
            raise RuntimeError(
                f"{operation} returned non-list result: {type(result).__name__}"
            )

    def _validate_find_result(
        self, result: ModelT | None, entity_id: Any
    ) -> None:
        """后置校验：查询结果可为 None（表示未找到），不阻断。

        子类可覆写以添加"必须找到"语义。
        """
        if result is not None and not isinstance(result, self.model):
            raise RuntimeError(
                f"find_by_id returned unexpected type: {type(result).__name__}, "
                f"expected {self.model.__name__}"
            )

    @staticmethod
    def _validate_delete_completed() -> None:
        """后置校验：delete 操作无异常即成功，无需额外检查。

        占位校验器，子类可通过 super() 叠加业务级删除后置条件。
        """
        pass
