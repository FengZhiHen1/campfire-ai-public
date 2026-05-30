"""history 行为契约 — ABC 模板方法骨架。

模块: app.modules.consultation.history.history_contract
职责: 定义咨询历史管理的契约骨架。覆盖 CSLT-06（历史归档、列表查询、详情查询）三个核心流程。
      每个 @final 公共入口强制执行 前置校验 → _do_ 钩子 → 后置校验 三步流程。
      实现者只能覆写 _do_ 前缀的钩子方法。
数据来源:
  - py_db.repositories.ConsultHistoryRepository: MUST — 咨询历史持久化
  - py_schemas.consultation_history.ConsultationHistoryCreate: MUST — 归档输入契约
边界:
  - 依赖: py_db, py_logger, py_schemas
  - 被依赖: history_routes.py（REST 端点）、service.py（实现类）
禁止行为:
  - 禁止在 _do_ 钩子中直接返回 ORM 实体（必须转换为 DTO）
  - 禁止 user_id 信任前端传入的值（强制从认证上下文注入）
  - 禁止在 consultation_time 使用客户端传入的时间（以服务端 NOW() 为准）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


class BaseHistoryManager(ABC):
    """咨询历史管理契约 — 实现者只能覆写 _do_ 前缀的钩子。"""

    # ==========================================================================
    # @final 公共入口：POST /api/v1/consultations — 归档写入
    # ==========================================================================

    @final
    async def archive_consultation(
        self,
        data: Any,
        current_user: dict[str, Any],
        db: AsyncSession,
    ) -> Any:
        """将一次应急咨询的完整上下文数据归档存储为一条历史记录。

        幂等语义：重复的 request_id 提交返回已有记录（HTTP 200），不产生重复行。
        此方法不可覆写（@final）。

        前置:
          - data 为 ConsultationHistoryCreate 实例
          - current_user 含 "sub" 字段
          - db 为有效的 AsyncSession
        后置:
          - 返回 ConsultationHistoryDetail 实例
          - 已持久化到 PostgreSQL
        输入约束:
          - data.disclaimer: 必须与 CSLT-03 固定声明文本一致
          - data.request_id: 非空 UUID
        输出约束:
          - 返回的 consultation_time 以服务端 NOW() 为准
        异常:
          - ConsultationArchiveError: disclaimer 等值校验失败或必填字段缺失
        Side Effects:
          - INSERT 到 consultations 表（ON CONFLICT DO NOTHING 幂等）
          - 记录结构化审计日志（含 request_id + user_id）
        """
        self._validate_archive_preconditions(data=data, current_user=current_user, db=db)

        record = await self._do_archive(data=data, current_user=current_user, db=db)

        self._validate_archive_postconditions(record=record)
        return record

    @abstractmethod
    async def _do_archive(
        self,
        data: Any,
        current_user: dict[str, Any],
        db: AsyncSession,
    ) -> Any:
        """执行归档写入（disclaimer 等值校验 + 幂等插入）。

        实现者在此填写 ORM 写入逻辑。
        不需要关心 data 的顶层校验——_validate_archive_preconditions 已处理。
        不需要关心 consultation_time——实现者以服务端 NOW() 为准。
        """
        ...

    # ==========================================================================
    # @final 公共入口：GET /api/v1/consultations — 历史列表
    # ==========================================================================

    @final
    async def list_history(
        self,
        page: int,
        page_size: int,
        current_user: dict[str, Any],
        db: AsyncSession,
    ) -> Any:
        """查询当前用户的所有咨询历史记录摘要列表。

        按 consultation_time 降序排列。
        此方法不可覆写（@final）。

        前置:
          - page >= 1, page_size 在 [1, 100]
          - current_user 含 "sub" 字段
        后置:
          - 返回 PaginatedResponse[ConsultationHistoryListItem]
          - page 超出总页数时返回空列表 + 正确的 total
        输入约束:
          - user_id 从 current_user 注入，不信任前端传入
        异常:
          - 无（user_id 缺失时返回空列表而非抛异常）
        Side Effects:
          - 记录结构化日志（含 user_id + page + total）
        """
        self._validate_list_preconditions(page=page, page_size=page_size, current_user=current_user)

        result = await self._do_list_history(
            page=page,
            page_size=page_size,
            current_user=current_user,
            db=db,
        )

        self._validate_list_postconditions(result=result)
        return result

    @abstractmethod
    async def _do_list_history(
        self,
        page: int,
        page_size: int,
        current_user: dict[str, Any],
        db: AsyncSession,
    ) -> Any:
        """执行分页查询。

        实现者在此填写 Repository 分页查询和 ORM→DTO 转换逻辑。
        不需要关心参数边界校验——_validate_list_preconditions 已处理。
        """
        ...

    # ==========================================================================
    # @final 公共入口：GET /api/v1/consultations/{id} — 详情查询
    # ==========================================================================

    @final
    async def get_detail(
        self,
        consultation_id: UUID,
        current_user: dict[str, Any],
        db: AsyncSession,
    ) -> Any:
        """查询单次咨询的完整详情。

        仅返回当前用户本人的记录。不存在或无权访问统一返回 404。
        此方法不可覆写（@final）。

        前置:
          - consultation_id 为有效 UUID
          - current_user 含 "sub" 字段
        后置:
          - 返回 ConsultationHistoryDetail 实例
        输入约束:
          - 按 id + user_id 联合过滤
        异常:
          - ConsultationNotFoundError: 不存在或无权访问（对外统一 404）
        Side Effects:
          - 内部日志记录真实拒绝原因（供运维排查，不返回客户端）
        """
        self._validate_detail_preconditions(
            consultation_id=consultation_id,
            current_user=current_user,
        )

        record = await self._do_get_detail(
            consultation_id=consultation_id,
            current_user=current_user,
            db=db,
        )

        self._validate_detail_postconditions(record=record)
        return record

    @abstractmethod
    async def _do_get_detail(
        self,
        consultation_id: UUID,
        current_user: dict[str, Any],
        db: AsyncSession,
    ) -> Any:
        """执行详情查询（id + user_id 联合过滤）。

        实现者在此填写 Repository 查询 + 权限校验 + ORM→DTO 转换。
        不需要关心 consultation_id 格式——Python UUID 类型已保证。

        输出约束:
          - 返回 ConsultationHistoryDetail 实例
        异常:
          - ConsultationNotFoundError: 不存在或无权访问
        """
        ...

    # ==========================================================================
    # 校验器
    # ==========================================================================

    def _validate_archive_preconditions(
        self,
        data: Any,
        current_user: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """基线前置校验——归档写入。"""
        if data is None:
            from app.modules.consultation.exceptions import ConsultationArchiveError
            raise ConsultationArchiveError(
                message="归档数据不能为空",
                field="data",
            )
        if not current_user or not current_user.get("sub"):
            from app.modules.consultation.exceptions import ConsultationArchiveError
            raise ConsultationArchiveError(
                message="用户身份不能为空",
                field="user_id",
            )
        if db is None:
            from app.modules.consultation.exceptions import ConsultationArchiveError
            raise ConsultationArchiveError(
                message="数据库会话不能为空",
                field="db",
            )

    def _validate_archive_postconditions(self, record: Any) -> None:
        """基线后置校验——归档写入。"""
        if record is None:
            raise RuntimeError("archive_consultation 返回了 None")

    def _validate_list_preconditions(
        self,
        page: int,
        page_size: int,
        current_user: dict[str, Any],
    ) -> None:
        """基线前置校验——历史列表。"""
        from app.modules.consultation.exceptions import ConsultationInputError
        if page < 1:
            raise ConsultationInputError(message="page 必须 >= 1", field="page")
        if page_size < 1 or page_size > 100:
            raise ConsultationInputError(message="page_size 必须在 [1, 100]", field="page_size")

    def _validate_list_postconditions(self, result: Any) -> None:
        """基线后置校验——历史列表。"""
        if result is None:
            raise RuntimeError("list_history 返回了 None")

    def _validate_detail_preconditions(
        self,
        consultation_id: UUID,
        current_user: dict[str, Any],
    ) -> None:
        """基线前置校验——详情查询。"""
        if consultation_id is None:
            from app.modules.consultation.exceptions import ConsultationNotFoundError
            raise ConsultationNotFoundError(
                consultation_id="None",
                actual_reason="consultation_id 为空",
            )
        if not current_user or not current_user.get("sub"):
            from app.modules.consultation.exceptions import ConsultationNotFoundError
            raise ConsultationNotFoundError(
                consultation_id=str(consultation_id),
                actual_reason="user_id 缺失",
            )

    def _validate_detail_postconditions(self, record: Any) -> None:
        """基线后置校验——详情查询。"""
        if record is None:
            raise RuntimeError("get_detail 返回了 None")


__all__ = ["BaseHistoryManager"]
