"""应急咨询域 ORM 模型（ADR-009 时刻分层目标态）— 四表。

- ConsultationSession: 一次危机会话（桶/阶段/meltdown 分流结论）
- Consultation: 会话内的一轮咨询（首份方案四段式 / 追问轮自由文本）
- SafetyCard: 此刻安全层静态模板（bucket × stage，含槽位占位符，M3 审核状态机）
- ConsultationLog: 异步咨询日志（含红线事件，event_type 区分）

事实源：docs/技术设计/机制/智能应急咨询.md §八。
旧 ConsultationHistory 单表已随时刻分层重构废除（全新迁移链）。
"""

# @contract — consultation_sessions / consultations / safety_cards / consultation_logs 表契约

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from py_schemas.enums import BehaviorBucket, CrisisStage, MeltdownType, TurnType
from py_schemas.enums.case_enums import CaseStatus
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy import Enum as sa_Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from py_db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ConsultationSession(Base, UUIDPrimaryKeyMixin):
    """应急咨询会话（一次危机会话）。

    桶选择兼任：输入方式 / 红线分流 / 案例检索过滤维度。
    """

    __tablename__ = "consultation_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="会话所属用户",
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.profile_id", ondelete="SET NULL"),
        nullable=True,
        comment="关联档案（可无档案模式，槽位回退纯模板）",
    )
    bucket: Mapped[BehaviorBucket] = mapped_column(
        sa_Enum(BehaviorBucket, name="behavior_bucket", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        comment="行为桶（统一行为枚举子集；UI 标签映射见枚举）",
    )
    crisis_stage: Mapped[CrisisStage | None] = mapped_column(
        sa_Enum(CrisisStage, name="crisis_stage", values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,
        comment="危机阶段（触发/躁动/加速/高峰；阶段单点问题判定后写入）",
    )
    meltdown_type: Mapped[MeltdownType | None] = mapped_column(
        sa_Enum(MeltdownType, name="meltdown_type", values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,
        comment="情绪哭闹桶内分流结论（meltdown/tantrum）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="会话创建时间",
    )


class Consultation(Base, UUIDPrimaryKeyMixin):
    """会话内的一轮咨询（首份方案或追问轮）。

    confidence_score 仅离线观测（ADR-009：废除置信度路由），不驱动任何行为。
    """

    __tablename__ = "consultations"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("consultation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属会话",
    )
    turn_type: Mapped[TurnType] = mapped_column(
        sa_Enum(TurnType, name="turn_type", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        comment="轮次类型：initial_plan 首份方案 / followup 追问轮",
    )
    behavior_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="用户补充的文字描述",
    )
    retrieved_case_ids: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="检索命中的案例切片 ID 列表",
    )
    generated_plan: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="首份方案的结构化四段（immediate_action/soothing_script/observation/medical_judgment）",
    )
    reply_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="追问轮自由文本回复（不套四段式契约）",
    )
    confidence_score: Mapped[Decimal | None] = mapped_column(
        Numeric(3, 2),
        nullable=True,
        comment="置信度分数：仅离线观测，不驱动任何行为（ADR-009）",
    )
    sources: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="来源引用 [{case_id, title, source_type}]",
    )
    disclaimer_served: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="免责声明是否已随响应送达",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="轮次创建时间",
    )


class SafetyCard(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """此刻安全层静态模板卡（bucket × stage 组织）。

    卡体含槽位占位符（{称呼}/{触发物}/{安抚物}/{禁忌}/{话术适配}/{走失信息}），
    由 slot_filler 确定性填充（零 LLM）；内容生产复用 M3 案例审核链路。
    """

    __tablename__ = "safety_cards"

    bucket: Mapped[BehaviorBucket | None] = mapped_column(
        sa_Enum(BehaviorBucket, name="behavior_bucket", values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,
        comment="所属行为桶；NULL 为 0 输入通用安全卡",
    )
    crisis_stage: Mapped[CrisisStage | None] = mapped_column(
        sa_Enum(CrisisStage, name="crisis_stage", values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,
        comment="所属危机阶段；NULL 为通用桶卡",
    )
    title: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="卡片标题",
    )
    card_template: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="含槽位占位符的模板正文（祈使短句、一句一个动作、列表 ≤5 项）",
    )
    review_status: Mapped[CaseStatus] = mapped_column(
        sa_Enum(CaseStatus, name="case_status", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=CaseStatus.DRAFT,
        server_default=CaseStatus.DRAFT.value,
        comment="审核状态（复用案例审核状态机：draft/pending_review/approved/rejected）",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="内容版本号",
    )


class ConsultationLog(Base, UUIDPrimaryKeyMixin):
    """异步咨询日志（含红线事件）。

    event_type 区分：consult_completed / redline_hit / fallback_triggered 等。
    """

    __tablename__ = "consultation_logs"

    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("consultation_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联会话（可空——红线判定先于会话建立的场景）",
    )
    event_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        index=True,
        comment="事件类型：consult_completed / redline_hit / fallback_triggered",
    )
    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="事件载荷（触发规则/输入摘要/兜底信号等）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="事件时间",
    )


__all__ = [
    "ConsultationSession",
    "Consultation",
    "SafetyCard",
    "ConsultationLog",
]
