"""CASE-01 L2 结构化卡片层 — CaseCard ORM 模型。

映射 PostgreSQL case_cards 表，存储从 L1 叙事中提取的结构化干预协议卡片。
每张卡片对应一个独立的干预场景，是 RAG 检索的主数据源。
"""

# @contract — case_cards 表 Schema 契约

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean, DateTime, Enum as sa_Enum, ForeignKey,
    Integer, JSON, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
import uuid

from py_db.models.base import Base, TimestampMixin
from py_schemas.enums.case_enums import CaseStatus


class CaseCard(Base, TimestampMixin):
    """L2 结构化卡片层 ORM 模型。

    存储从 L1 叙事中 LLM 提取 + 专家微调的结构化干预协议。
    每张卡片是一个独立的检索单元，审核通过后切片入向量库。
    FK narrative_id 指向 case_narratives。
    """

    __tablename__ = "case_cards"

    # ---- 主键 ----
    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="L2 卡片唯一标识（UUID v4）",
    )

    # ---- FK 到 L1 ----
    narrative_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("case_narratives.narrative_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的 L1 叙事",
    )

    # ---- 基础信息 ----
    title: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="卡片标题（通用化干预方案名）",
    )
    scenario: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="适用场景描述",
    )
    behavior_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="行为类型（自伤/攻击/刻板/逃跑/情绪崩溃/其他）",
    )
    age_range_min: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="适用年龄区间起始值",
    )
    age_range_max: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="适用年龄区间结束值",
    )
    severity: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="适用严重程度（轻度/中度/重度）",
    )
    scene: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="发生场景（家庭/学校/公共场合/机构/不限）",
    )

    # ---- 循证标注 ----
    ebp_labels: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="NCAEP 28 种循证实践标签",
    )
    family_category: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="家属端展示大类（环境调整/沟通替代/行为塑造/危机安全/社交引导/自我管理）",
    )

    # ---- 四段式输出（核心） ----
    immediate_action: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="即时安全干预动作（四段式第一段）",
    )
    comforting_phrase: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="情绪安抚话术（四段式第二段）",
    )
    observation_metrics: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="后续观察指标（四段式第三段）",
    )
    medical_criteria: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="就医判断标准（四段式第四段）",
    )

    # ---- 循证与质量 ----
    evidence_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="循证等级（NCAEP循证实践/机构经验总结/个案观察记录）",
    )
    caution_notes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="禁忌、注意事项与常见误用",
    )
    contraindications: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="明确不适用的人群或场景",
    )
    is_template: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否模板",
    )

    # ---- 选填字段 ----
    excluded_population: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="不适用人群（选填）",
    )
    attachment_refs: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON,
        nullable=True,
        default=list,
        comment="附件引用列表（选填）",
    )

    # ---- 状态 ----
    review_status: Mapped[CaseStatus] = mapped_column(
        sa_Enum(
            CaseStatus,
            name="card_review_status",
            create_constraint=True,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=CaseStatus.DRAFT,
        index=True,
        comment="卡片审核状态（draft/pending_review/approved/rejected）",
    )
    review_comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="审核驳回意见",
    )

    # ---- 索引状态（由 CASE-04 Worker 更新） ----
    index_status: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        default=None,
        comment="向量化索引状态（pending/processing/indexed/indexing_failed）",
    )
    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="索引完成时间",
    )

    # ---- LLM 推断标记 ----
    _inferred: Mapped[dict[str, Any] | None] = mapped_column(
        "inferred_fields",
        JSONB,
        nullable=True,
        default=None,
        comment="LLM 提取时推断的字段及依据，供专家审核确认",
    )

    def __repr__(self) -> str:
        return (
            f"<CaseCard(card_id={self.card_id!r}, title={self.title!r}, "
            f"review_status={self.review_status.value!r})>"
        )


__all__ = ["CaseCard"]
