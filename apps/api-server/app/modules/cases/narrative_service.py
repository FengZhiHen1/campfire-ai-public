"""L1 原始叙事层 — 业务服务。

提供 L1 叙事的 CRUD 操作和 LLM 提取触发。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select, func, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.models.case_narrative import CaseNarrative
from py_db.models.case_card import CaseCard
from py_schemas.enums.case_enums import CaseStatus

from app.modules.cases.narrative_contract import NarrativeManagementContract
from app.modules.cases.exceptions import (
    NarrativeNotFoundError,
    CaseStatusError,
    SelfReviewForbiddenError,
)

_logger = logging.getLogger(__name__)


class NarrativeManagementService(NarrativeManagementContract):
    """叙事管理服务实现。实现 NarrativeManagementContract 契约的全部 _do_ 钩子。"""

    # ========================================================================
    # L1 叙事钩子
    # ========================================================================

    async def _do_create_narrative(
        self,
        title: str,
        narrative: str,
        source_type: str,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any:
        """创建新的 L1 叙事（status=draft）。"""
        entity = CaseNarrative(
            narrative_id=uuid.uuid4(),
            title=title,
            narrative=narrative,
            source_type=source_type,
            author_id=current_user.get("sub", ""),
            status=CaseStatus.DRAFT,
        )
        session.add(entity)
        await session.commit()
        await session.refresh(entity)
        return entity

    async def _do_get_narrative(
        self,
        narrative_id: str,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any:
        """获取 L1 叙事详情（含所有权检查）。"""
        nid = uuid.UUID(narrative_id)
        result = await session.execute(
            select(CaseNarrative).where(CaseNarrative.narrative_id == nid)
        )
        entity = result.scalars().first()
        if entity is None:
            raise NarrativeNotFoundError(narrative_id)

        author_id = str(entity.author_id) if entity.author_id else ""
        current_id = current_user.get("sub", "")
        is_owner = author_id == current_id

        if entity.status != CaseStatus.APPROVED and not is_owner:
            raise NarrativeNotFoundError(narrative_id)

        return entity

    async def _do_list_narratives(
        self,
        scope: str,
        current_user: dict[str, Any],
        session: AsyncSession,
        page: int,
        page_size: int,
    ) -> tuple[list[Any], int]:
        """列出 L1 叙事（public=仅已发布 / my=当前用户）。"""
        stmt = select(CaseNarrative)
        if scope == "public":
            stmt = stmt.where(CaseNarrative.status == CaseStatus.APPROVED)
        elif scope == "my":
            stmt = stmt.where(CaseNarrative.author_id == current_user.get("sub", ""))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        stmt = stmt.order_by(CaseNarrative.created_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def _do_update_narrative(
        self,
        narrative_id: str,
        title: str | None,
        narrative: str | None,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any:
        """更新 L1 叙事（仅作者可编辑，status=draft 时）。"""
        entity = await self.get_narrative(narrative_id, current_user, session)
        if entity.status != CaseStatus.DRAFT:
            raise CaseStatusError(narrative_id, str(entity.status), "draft")
        if title is not None:
            entity.title = title
        if narrative is not None:
            entity.narrative = narrative
        await session.commit()
        await session.refresh(entity)
        return entity

    async def _do_submit_narrative(
        self,
        narrative_id: str,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any:
        """提交 L1 叙事审核（draft → pending_review）。"""
        entity = await self.get_narrative(narrative_id, current_user, session)
        if entity.status != CaseStatus.DRAFT:
            raise CaseStatusError(narrative_id, str(entity.status), "draft")

        result = await session.execute(
            sa_update(CaseNarrative)
            .where(
                CaseNarrative.narrative_id == entity.narrative_id,
                CaseNarrative.status == CaseStatus.DRAFT,
            )
            .values(status=CaseStatus.PENDING_REVIEW)
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise CaseStatusError(
                narrative_id, str(entity.status), "draft",
            )

        await session.commit()
        await session.refresh(entity)
        return entity

    # ========================================================================
    # L2 卡片钩子
    # ========================================================================

    async def _do_get_cards_by_narrative(
        self,
        narrative_id: str,
        session: AsyncSession,
    ) -> list[Any]:
        """获取某叙事下的所有 L2 卡片。"""
        nid = uuid.UUID(narrative_id)
        result = await session.execute(
            select(CaseCard)
            .where(CaseCard.narrative_id == nid)
            .order_by(CaseCard.created_at.asc())
        )
        return list(result.scalars().all())

    async def _do_get_card(
        self,
        card_id: str,
        session: AsyncSession,
    ) -> Any:
        """获取单张 L2 卡片。未找到返回 None，由契约层抛出 CardNotFoundError。"""
        cid = uuid.UUID(card_id)
        result = await session.execute(
            select(CaseCard).where(CaseCard.card_id == cid)
        )
        return result.scalars().first()

    async def _do_update_card(
        self,
        card_id: str,
        update_data: dict[str, Any],
        session: AsyncSession,
    ) -> Any:
        """更新 L2 卡片（专家微调）。"""
        entity = await self.get_card(card_id, session)
        if entity.review_status not in (CaseStatus.DRAFT, CaseStatus.REJECTED):
            raise CaseStatusError(
                card_id, str(entity.review_status), "draft 或 rejected",
            )

        for key, value in update_data.items():
            if value is not None and hasattr(entity, key):
                setattr(entity, key, value)

        entity.review_status = CaseStatus.DRAFT
        await session.commit()
        await session.refresh(entity)
        return entity

    async def _do_submit_card(
        self,
        card_id: str,
        session: AsyncSession,
    ) -> Any:
        """提交单张 L2 卡片审核。"""
        entity = await self.get_card(card_id, session)
        if entity.review_status != CaseStatus.DRAFT:
            raise CaseStatusError(card_id, str(entity.review_status), "draft")

        result = await session.execute(
            sa_update(CaseCard)
            .where(
                CaseCard.card_id == entity.card_id,
                CaseCard.review_status == CaseStatus.DRAFT,
            )
            .values(review_status=CaseStatus.PENDING_REVIEW)
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise CaseStatusError(card_id, str(entity.review_status), "draft")

        await session.commit()
        await session.refresh(entity)
        return entity

    async def _do_approve_card(
        self,
        card_id: str,
        current_user: dict[str, Any],
        session: AsyncSession,
    ) -> Any:
        """审核通过 L2 卡片（触发向量索引）。"""
        entity = await self.get_card(card_id, session)
        if entity.review_status != CaseStatus.PENDING_REVIEW:
            raise CaseStatusError(
                card_id, str(entity.review_status), "pending_review",
            )
        if str(entity.narrative_id) == current_user.get("sub", ""):
            raise SelfReviewForbiddenError(
                card_id, current_user.get("sub", ""),
                str(entity.narrative_id),
            )

        result = await session.execute(
            sa_update(CaseCard)
            .where(
                CaseCard.card_id == entity.card_id,
                CaseCard.review_status == CaseStatus.PENDING_REVIEW,
            )
            .values(review_status=CaseStatus.APPROVED, index_status="pending")
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise CaseStatusError(
                card_id, str(entity.review_status), "pending_review",
            )

        # 触发索引
        from py_rag.indexing.service import enqueue_index_task
        await enqueue_index_task(str(entity.card_id))

        await session.commit()
        await session.refresh(entity)
        return entity

    # ========================================================================
    # 校验器覆盖（增强 UUID 格式校验）
    # ========================================================================

    def _validate_narrative_id(self, narrative_id: str) -> None:
        """增强校验：非空 + 有效 UUID 格式。"""
        super()._validate_narrative_id(narrative_id)
        try:
            uuid.UUID(narrative_id)
        except ValueError:
            raise ValueError(f"narrative_id 格式无效: {narrative_id}")

    def _validate_card_id(self, card_id: str) -> None:
        """增强校验：非空 + 有效 UUID 格式。"""
        super()._validate_card_id(card_id)
        try:
            uuid.UUID(card_id)
        except ValueError:
            raise ValueError(f"card_id 格式无效: {card_id}")


# ============================================================================
# 辅助：ORM → dict 转换（模块级函数）
# ============================================================================


def narrative_to_response(n: CaseNarrative, card_count: int = 0) -> dict:
    """将 CaseNarrative ORM 对象转换为 API 响应字典。"""
    return {
        "narrative_id": str(n.narrative_id),
        "title": n.title,
        "narrative": n.narrative,
        "source_type": n.source_type,
        "author_id": n.author_id,
        "status": n.status,
        "review_comment": n.review_comment,
        "derived_card_ids": n.derived_card_ids,
        "card_count": card_count,
        "created_at": n.created_at,
        "updated_at": n.updated_at,
    }


def card_to_response(
    c: CaseCard,
    is_owner: bool = False,
    narrative_author_id: str = "",
    current_user_id: str = "",
) -> dict:
    """将 CaseCard ORM 对象转换为 API 响应字典。"""
    return {
        "card_id": str(c.card_id),
        "narrative_id": str(c.narrative_id),
        "title": c.title,
        "scenario": c.scenario,
        "behavior_type": c.behavior_type,
        "age_range": [c.age_range_min, c.age_range_max],
        "severity": c.severity,
        "scene": c.scene,
        "ebp_labels": c.ebp_labels,
        "family_category": c.family_category,
        "immediate_action": c.immediate_action,
        "comforting_phrase": c.comforting_phrase,
        "observation_metrics": c.observation_metrics,
        "medical_criteria": c.medical_criteria,
        "evidence_level": c.evidence_level,
        "caution_notes": c.caution_notes or "",
        "contraindications": c.contraindications,
        "is_template": c.is_template,
        "excluded_population": c.excluded_population,
        "attachment_refs": c.attachment_refs,
        "review_status": c.review_status,
        "review_comment": c.review_comment,
        "inferred_fields": c._inferred,
        "is_owner": is_owner,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }

__all__ = [
    "NarrativeManagementService",
    "narrative_to_response",
    "card_to_response",
]
