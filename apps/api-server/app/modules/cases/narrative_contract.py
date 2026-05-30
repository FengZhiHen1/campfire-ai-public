"""L1 叙事 + L2 卡片管理 — 行为契约（ABC 模板方法）。

定义叙事层 CRUD 和卡片层 CRUD 的契约骨架：
- L1 叙事: create / get / list / update / submit
- L2 卡片: get_cards_by_narrative / get_card / update_card / submit_card / approve_card

所有 @final 公共方法强制执行 前置校验 → 调用钩子 → 后置校验 的三明治结构。
实现者只能覆写 _do_ 前缀的钩子方法。

数据来源:
  - SQLAlchemy AsyncSession: MUST — 数据库操作（无独立 Repository，直接使用 ORM Session）
  - CaseNarrative / CaseCard (py_db): MUST — ORM 模型
边界:
  - 依赖: py_db, py_schemas
  - 被依赖: narrative_routes.py（路由层委托）
  - 不负责: LLM 提取（归属 extraction/ 子模块）、向量化入库（归属 CASE-04）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, final

from sqlalchemy.ext.asyncio import AsyncSession


class NarrativeManagementContract(ABC):
    """叙事管理服务契约。实现者只能覆写 _do_ 前缀的钩子方法。"""

    # ========================================================================
    # L1 叙事层 — @final 公共入口
    # ========================================================================

    @final
    async def create_narrative(
        self,
        title: str,
        narrative: str,
        source_type: str,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any:
        """创建新的 L1 叙事（status=draft）。

        前置:
          - title 非空
          - narrative 非空
        后置:
          - 叙事已写入数据库，status=draft
          - narrative_id 已通过 UUID v4 生成
        """
        self._validate_narrative_fields(title, narrative)
        result = await self._do_create_narrative(
            title, narrative, source_type, current_user, session,
        )
        self._validate_narrative_result(result)
        return result

    @final
    async def get_narrative(
        self,
        narrative_id: str,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any:
        """获取 L1 叙事详情（含所有权检查）。

        前置:
          - narrative_id 为有效 UUID 字符串
        后置:
          - 返回 CaseNarrative ORM 实例
          - 非 approved 叙事仅作者可见（其他用户返回 404）
        异常:
          - NarrativeNotFoundError: 叙事不存在或无权限
        """
        self._validate_narrative_id(narrative_id)
        result = await self._do_get_narrative(narrative_id, current_user, session)
        self._validate_narrative_result(result)
        return result

    @final
    async def list_narratives(
        self,
        scope: str,
        current_user: dict[str, Any],
        session: AsyncSession,
        page: int = 1,
        page_size: int = 15,
    ) -> tuple[list[Any], int]:
        """列出 L1 叙事（public=仅已发布 / my=当前用户）。

        前置:
          - scope 为 "public" 或 "my"
          - page >= 1, page_size 在 1-100 之间
        后置:
          - 返回 (叙事列表, 总数) 元组
        """
        self._validate_list_params(page, page_size)
        return await self._do_list_narratives(
            scope, current_user, session, page, page_size,
        )

    @final
    async def update_narrative(
        self,
        narrative_id: str,
        title: str | None,
        narrative: str | None,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any:
        """更新 L1 叙事（仅作者可编辑，status=draft 时）。

        前置:
          - narrative_id 为有效 UUID
          - 叙事存在且 status=draft
          - 当前用户是作者
        异常:
          - NarrativeNotFoundError: 叙事不存在
          - CaseStatusError: 状态不是 draft
        """
        self._validate_narrative_id(narrative_id)
        result = await self._do_update_narrative(
            narrative_id, title, narrative, current_user, session,
        )
        self._validate_narrative_result(result)
        return result

    @final
    async def submit_narrative(
        self,
        narrative_id: str,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any:
        """提交 L1 叙事审核（draft → pending_review）。

        前置:
          - 叙事存在且 status=draft
        后置:
          - 叙事状态已变更为 pending_review
        异常:
          - CaseStatusError: 状态不是 draft 或 CAS 更新失败
        """
        self._validate_narrative_id(narrative_id)
        result = await self._do_submit_narrative(
            narrative_id, current_user, session,
        )
        self._validate_narrative_result(result)
        return result

    # ========================================================================
    # L2 卡片层 — @final 公共入口
    # ========================================================================

    @final
    async def get_cards_by_narrative(
        self,
        narrative_id: str,
        session: AsyncSession,
    ) -> list[Any]:
        """获取某叙事下的所有 L2 卡片。

        后置:
          - 返回 CaseCard 列表（按 created_at 升序）
        """
        self._validate_narrative_id(narrative_id)
        return await self._do_get_cards_by_narrative(narrative_id, session)

    @final
    async def get_card(
        self,
        card_id: str,
        session: AsyncSession,
    ) -> Any:
        """获取单张 L2 卡片。

        异常:
          - CardNotFoundError: 卡片不存在
        """
        self._validate_card_id(card_id)
        result = await self._do_get_card(card_id, session)
        if result is None:
            from app.modules.cases.exceptions import CardNotFoundError
            raise CardNotFoundError(card_id)
        return result

    @final
    async def update_card(
        self,
        card_id: str,
        update_data: dict[str, Any],
        session: AsyncSession,
    ) -> Any:
        """更新 L2 卡片（专家微调，仅 draft/rejected 状态可编辑）。

        后置:
          - 卡片字段已更新，review_status 重置为 draft
        异常:
          - CardNotFoundError: 卡片不存在
          - CaseStatusError: 状态不是 draft 或 rejected
        """
        self._validate_card_id(card_id)
        result = await self._do_update_card(card_id, update_data, session)
        self._validate_card_result(result)
        return result

    @final
    async def submit_card(
        self,
        card_id: str,
        session: AsyncSession,
    ) -> Any:
        """提交单张 L2 卡片审核。

        后置:
          - 卡片 review_status 变更为 pending_review
        异常:
          - CaseStatusError: 状态不是 draft
        """
        self._validate_card_id(card_id)
        result = await self._do_submit_card(card_id, session)
        self._validate_card_result(result)
        return result

    @final
    async def approve_card(
        self,
        card_id: str,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any:
        """审核通过 L2 卡片（触发向量索引）。

        前置:
          - 审核人不是卡片创建者
        后置:
          - review_status 变更为 approved
          - index_status 变更为 pending
          - 触发 py_rag 索引入队
        异常:
          - CaseStatusError: review_status 不是 pending_review
          - SelfReviewForbiddenError: 审核人是卡片创建者
        """
        self._validate_card_id(card_id)
        result = await self._do_approve_card(card_id, current_user, session)
        self._validate_card_result(result)
        return result

    # ========================================================================
    # @abstractmethod 钩子（实现者必填）
    # ========================================================================

    @abstractmethod
    async def _do_create_narrative(
        self,
        title: str,
        narrative: str,
        source_type: str,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any: ...

    @abstractmethod
    async def _do_get_narrative(
        self,
        narrative_id: str,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any: ...

    @abstractmethod
    async def _do_list_narratives(
        self,
        scope: str,
        current_user: dict[str, Any],
        session: AsyncSession,
        page: int,
        page_size: int,
    ) -> tuple[list[Any], int]: ...

    @abstractmethod
    async def _do_update_narrative(
        self,
        narrative_id: str,
        title: str | None,
        narrative: str | None,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any: ...

    @abstractmethod
    async def _do_submit_narrative(
        self,
        narrative_id: str,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any: ...

    @abstractmethod
    async def _do_get_cards_by_narrative(
        self,
        narrative_id: str,
        session: AsyncSession,
    ) -> list[Any]: ...

    @abstractmethod
    async def _do_get_card(
        self,
        card_id: str,
        session: AsyncSession,
    ) -> Any: ...

    @abstractmethod
    async def _do_update_card(
        self,
        card_id: str,
        update_data: dict[str, Any],
        session: AsyncSession,
    ) -> Any: ...

    @abstractmethod
    async def _do_submit_card(
        self,
        card_id: str,
        session: AsyncSession,
    ) -> Any: ...

    @abstractmethod
    async def _do_approve_card(
        self,
        card_id: str,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any: ...

    # ========================================================================
    # 校验器（模板提供基线校验，子类可通过 super() 叠加）
    # ========================================================================

    def _validate_narrative_fields(self, title: str, narrative: str) -> None:
        if not title or not title.strip():
            raise ValueError("title 不能为空")
        if not narrative or not narrative.strip():
            raise ValueError("narrative 不能为空")

    def _validate_narrative_id(self, narrative_id: str) -> None:
        if not narrative_id:
            raise ValueError("narrative_id 不能为空")

    def _validate_card_id(self, card_id: str) -> None:
        if not card_id:
            raise ValueError("card_id 不能为空")

    def _validate_narrative_result(self, result: Any) -> None:
        if result is None:
            raise RuntimeError(
                f"{self.__class__.__name__} 叙事操作返回了 None"
            )

    def _validate_card_result(self, result: Any) -> None:
        if result is None:
            raise RuntimeError(
                f"{self.__class__.__name__} 卡片操作返回了 None"
            )

    def _validate_list_params(self, page: int, page_size: int) -> None:
        if page < 1:
            raise ValueError("page 必须 >= 1")
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size 必须在 1-100 之间")
