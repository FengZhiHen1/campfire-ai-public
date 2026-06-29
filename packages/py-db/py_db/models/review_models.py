"""CASE-03 案例审核工作流 — 审核 ORM 模型。

定义两个表：
- case_reviews: 审核记录表，存储每次专家审核的完整详情（1:N 关系）
- review_audit_logs: 审核审计日志表，BIGSERIAL 自增主键，仅允许 INSERT

case_reviews 表存储 AI 预审报告、专家裁决、审核时间和审核人。
review_audit_logs 表存储不可篡改的审计记录，使用自增 BIGSERIAL 主键。
"""

# @contract — case_reviews / review_audit_logs 表 Schema 契约

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from py_db.models.base import Base, TimestampMixin


class CaseReview(Base, TimestampMixin):
    """审核记录 ORM 模型。

    映射 PostgreSQL case_reviews 表，存储每次专家审核的完整详情。
    与 cases 表为 1:N 关系（一个案例可被多次驳回-重新提交-再审核）。

    审核历史通过 review_round 字段追踪，从 1 开始递增。
    ai_review_report 以 JSONB 存储 AI 预审的完整报告。
    """

    __tablename__ = "case_reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID v4 主键",
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("case_cards.card_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的 L2 卡片标识（FK → case_cards.card_id）",
    )
    review_round: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="第几次审核（从 1 开始）",
    )
    ai_review_report: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="AI 预审完整报告（JSONB，含四项检查结果和 overall 结论）",
    )
    decision: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="专家裁决（approved / rejected）",
    )
    review_comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="审核意见（驳回时必填，>=10 字）",
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="审核人标识（UUID）",
    )
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="审核完成时间",
    )
    is_override: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否覆盖了 AI 预审结果",
    )
    override_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="覆盖理由（is_override=True 时必填）",
    )

    def __repr__(self) -> str:
        return (
            f"<CaseReview(id={self.id!r}, case_id={self.case_id!r}, "
            f"decision={self.decision!r}, round={self.review_round})>"
        )


class ReviewAuditLog(Base):
    """审核审计日志 ORM 模型。

    映射 PostgreSQL review_audit_logs 表，存储不可篡改的审计记录。
    使用 BIGSERIAL 自增主键确保记录顺序不可伪造。
    仅允许 INSERT 操作（Repository 层不提供 UPDATE/DELETE 方法）。

    Attributes:
        id: BIGSERIAL 自增主键，不可篡改。
        case_id: 关联的案例标识。
        action: 审计动作类型。
        operator_id: 操作人 UUID。
        operator_role: 操作人角色。
        details: JSONB 操作详情。
        created_at: 操作时间（TIMESTAMPTZ）。
    """

    __tablename__ = "review_audit_logs"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="BIGSERIAL 自增主键，记录顺序不可伪造",
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("case_cards.card_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的 L2 卡片标识",
    )
    action: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        comment="审计动作类型",
    )
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="操作人 UUID",
    )
    operator_role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="操作人角色",
    )
    details: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="操作详情（JSONB）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="操作时间",
    )

    def __repr__(self) -> str:
        return (
            f"<ReviewAuditLog(id={self.id!r}, case_id={self.case_id!r}, "
            f"action={self.action!r})>"
        )


__all__ = [
    "CaseReview",
    "ReviewAuditLog",
]
