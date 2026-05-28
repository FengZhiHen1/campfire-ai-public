"""L1 原始叙事层 — 业务服务。

提供 L1 叙事的 CRUD 操作和 LLM 提取触发。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.models.case_narrative import CaseNarrative
from py_db.models.case_card import CaseCard
from py_schemas.enums.case_enums import CaseStatus

_logger = logging.getLogger(__name__)


# ============================================================================
# L1 叙事 CRUD
# ============================================================================


async def create_narrative(
    title: str,
    narrative: str,
    source_type: str,
    current_user: Dict[str, Any],
    session: AsyncSession,
) -> CaseNarrative:
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


async def get_narrative(
    narrative_id: str,
    current_user: Dict[str, Any],
    session: AsyncSession,
) -> CaseNarrative:
    """获取 L1 叙事详情（含所有权检查）。"""
    from sqlalchemy import select
    nid = uuid.UUID(narrative_id)
    result = await session.execute(
        select(CaseNarrative).where(CaseNarrative.narrative_id == nid)
    )
    entity = result.scalars().first()
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="叙事不存在")

    author_id = str(entity.author_id) if entity.author_id else ""
    current_id = current_user.get("sub", "")
    is_owner = author_id == current_id

    if entity.status != CaseStatus.APPROVED and not is_owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="叙事不存在")

    return entity


async def list_narratives(
    scope: str,
    current_user: Dict[str, Any],
    session: AsyncSession,
    page: int = 1,
    page_size: int = 15,
) -> tuple[list[CaseNarrative], int]:
    """列出 L1 叙事（public=仅已发布 / my=当前用户）。"""
    from sqlalchemy import select, func

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


async def update_narrative(
    narrative_id: str,
    title: str | None,
    narrative: str | None,
    current_user: Dict[str, Any],
    session: AsyncSession,
) -> CaseNarrative:
    """更新 L1 叙事（仅作者可编辑，status=draft 时）。"""
    entity = await get_narrative(narrative_id, current_user, session)
    if entity.status != CaseStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="仅草稿状态的叙事可编辑",
        )
    if title is not None:
        entity.title = title
    if narrative is not None:
        entity.narrative = narrative
    await session.commit()
    await session.refresh(entity)
    return entity


async def submit_narrative(
    narrative_id: str,
    current_user: Dict[str, Any],
    session: AsyncSession,
) -> CaseNarrative:
    """提交 L1 叙事审核（draft → pending_review）。"""
    entity = await get_narrative(narrative_id, current_user, session)
    if entity.status != CaseStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="仅草稿状态的叙事可提交审核",
        )
    entity.status = CaseStatus.PENDING_REVIEW
    await session.commit()
    await session.refresh(entity)
    return entity


# ============================================================================
# L2 卡片 CRUD
# ============================================================================


async def get_cards_by_narrative(
    narrative_id: str,
    session: AsyncSession,
) -> list[CaseCard]:
    """获取某叙事下的所有 L2 卡片。"""
    from sqlalchemy import select

    nid = uuid.UUID(narrative_id)
    result = await session.execute(
        select(CaseCard)
        .where(CaseCard.narrative_id == nid)
        .order_by(CaseCard.created_at.asc())
    )
    return list(result.scalars().all())


async def get_card(
    card_id: str,
    session: AsyncSession,
) -> CaseCard:
    """获取单张 L2 卡片。"""
    from sqlalchemy import select

    cid = uuid.UUID(card_id)
    result = await session.execute(
        select(CaseCard).where(CaseCard.card_id == cid)
    )
    entity = result.scalars().first()
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="卡片不存在")
    return entity


async def update_card(
    card_id: str,
    update_data: Dict[str, Any],
    session: AsyncSession,
) -> CaseCard:
    """更新 L2 卡片（专家微调）。"""
    entity = await get_card(card_id, session)
    if entity.review_status not in (CaseStatus.DRAFT, CaseStatus.REJECTED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="仅草稿/已驳回状态的卡片可编辑",
        )

    for key, value in update_data.items():
        if value is not None and hasattr(entity, key):
            setattr(entity, key, value)

    entity.review_status = CaseStatus.DRAFT
    await session.commit()
    await session.refresh(entity)
    return entity


async def submit_card(
    card_id: str,
    session: AsyncSession,
) -> CaseCard:
    """提交单张 L2 卡片审核。"""
    entity = await get_card(card_id, session)
    if entity.review_status != CaseStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="仅草稿状态的卡片可提交审核",
        )
    entity.review_status = CaseStatus.PENDING_REVIEW
    await session.commit()
    await session.refresh(entity)
    return entity


async def approve_card(
    card_id: str,
    current_user: Dict[str, Any],
    session: AsyncSession,
) -> CaseCard:
    """审核通过 L2 卡片（触发向量索引）。"""
    entity = await get_card(card_id, session)
    if entity.review_status != CaseStatus.PENDING_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="仅待审核状态的卡片可通过",
        )
    if str(entity.narrative_id) == current_user.get("sub", ""):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="不能审核自己创建的卡片",
        )

    entity.review_status = CaseStatus.APPROVED
    entity.index_status = "pending"

    # 触发索引
    from py_rag.indexing.service import enqueue_index_task
    await enqueue_index_task(str(entity.card_id))

    await session.commit()
    await session.refresh(entity)
    return entity


# ============================================================================
# 辅助：ORM → Pydantic 转换
# ============================================================================


def narrative_to_response(n: CaseNarrative, card_count: int = 0) -> dict:
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
