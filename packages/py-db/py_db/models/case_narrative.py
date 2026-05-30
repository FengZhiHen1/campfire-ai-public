"""CASE-01 L1 原始叙事层 — CaseNarrative ORM 模型。

映射 PostgreSQL case_narratives 表，存储案例的 L1 原始叙事字段。
与 case_cards（L2 结构化卡片）构成一对多关系。
"""

# @contract — case_narratives 表 Schema 契约

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as sa_Enum, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
import uuid

from py_db.models.base import Base, TimestampMixin
from py_schemas.enums.case_enums import CaseStatus


class CaseNarrative(Base, TimestampMixin):
    """L1 原始叙事层 ORM 模型。

    存储以自然语言撰写的完整干预故事，面向人类阅读。
    审核状态控制叙事及其关联 L2 卡片的可见性。
    """

    __tablename__ = "case_narratives"

    # ---- 主键 ----
    narrative_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="L1 叙事唯一标识（UUID v4）",
    )

    # ---- L1 核心字段 ----
    title: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="叙事标题（通用化描述）",
    )
    narrative: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="完整自然语言叙事文本",
    )
    source_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="案例来源类型（专家撰写/机构脱敏/工单沉淀）",
    )
    author_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="撰写专家标识（UUID）",
    )

    # ---- 状态 ----
    status: Mapped[CaseStatus] = mapped_column(
        sa_Enum(
            CaseStatus,
            name="narrative_status",
            create_constraint=True,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=CaseStatus.DRAFT,
        index=True,
        comment="叙事状态（draft/pending_review/approved/rejected）",
    )

    # ---- 审核字段 ----
    review_comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="审核驳回意见",
    )

    # ---- 衍生卡片追踪 ----
    derived_card_ids: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
        comment="衍生的 L2 卡片 card_id 列表（JSON 数组）",
    )

    # ---- 提取状态 ----
    extraction_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        comment="LLM 提取状态（pending/extracting/extracted/failed）",
    )

    def __repr__(self) -> str:
        return (
            f"<CaseNarrative(narrative_id={self.narrative_id!r}, "
            f"title={self.title!r}, status={self.status.value!r})>"
        )


__all__ = ["CaseNarrative"]
