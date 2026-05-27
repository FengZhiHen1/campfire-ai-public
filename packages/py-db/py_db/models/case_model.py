"""CASE-01 案例录入管理 — Case ORM 模型。

映射 PostgreSQL cases 表，存储案例 L1+L2 的全部字段。
主键为 case_id（VARCHAR，格式 CASE-YYYY-NNNN），不使用 UUID 主键。
age_range 在表中拆分为 age_range_min 和 age_range_max 两个 INT 列。
ebp_labels 和 attachment_refs 以 JSON 列存储。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as sa_Enum, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from py_db.models.base import Base, TimestampMixin
from py_schemas.enums.case_enums import CaseStatus


class Case(Base, TimestampMixin):
    """案例 ORM 模型。

    映射 PostgreSQL cases 表，存储案例的完整 L1+L2 字段。
    主键 case_id 格式为 CASE-YYYY-NNNN，由数据库序列自动生成。
    age_range 以 age_range_min 和 age_range_max 两个 INT 列存储。
    """

    __tablename__ = "cases"

    # ---- 主键 ----
    case_id: Mapped[str] = mapped_column(
        String(20),
        primary_key=True,
        comment="案例唯一标识，格式 CASE-YYYY-NNNN，由序列自动生成",
    )

    # ---- L1 字段 ----
    title: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="案例标题，去个性化后的简短名称",
    )
    narrative: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="原始叙事文本，以自然语言撰写的完整干预故事",
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

    # ---- L2 字段 ----
    behavior_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="行为类型",
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
        comment="发生场景",
    )
    ebp_labels: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="循证实践标签列表，JSON 数组",
    )
    family_category: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="家属端展示大类",
    )
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
    evidence_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="循证等级",
    )
    contraindications: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="禁忌与注意事项",
    )
    is_template: Mapped[bool] = mapped_column(
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
        comment="附件引用列表（选填），JSON 数组",
    )

    # ---- 状态 ----
    status: Mapped[CaseStatus] = mapped_column(
        sa_Enum(CaseStatus, name="case_status", create_constraint=True),
        nullable=False,
        default=CaseStatus.DRAFT,
        index=True,
        comment="案例状态（draft/pending_review/rejected）",
    )

    # ---- 审核字段（由 CASE-03 填写） ----
    review_comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="审核驳回意见，由 CASE-03 填写",
    )

    def __repr__(self) -> str:
        return (
            f"<Case(case_id={self.case_id!r}, title={self.title!r}, "
            f"status={self.status.value!r})>"
        )


__all__ = ["Case"]
