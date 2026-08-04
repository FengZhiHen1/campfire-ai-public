"""档案域 ORM 模型（ADR-010 四层结构与 ABC 标准化目标态）。

四表：
- profiles: 身份基础层 + 危机预案层字段组（每档案一份危机预案）
- event_logs: 事件时间线层（ABC 结构化，一键打点/事后补全双模式）
- professional_notes: 专业评估层（老师/专家挂载，只读家属内容）
- profile_access: 关联管理（家属主控，受邀协作，单方面解除）

事实源：docs/技术设计/机制/个性化档案库/数据模型.md。
已废除：TeacherLink（并入 ProfileAccess）、severity_level 3 级、
intervention_tried/intervention_result 必填自由文本。
"""

# @contract — profiles / event_logs / professional_notes / profile_access 表契约

from __future__ import annotations

import uuid
from datetime import date, datetime

from py_schemas.enums import (
    AccessRole,
    AccessStatus,
    AntecedentCategory,
    BehaviorBucket,
    EventSetting,
    EvidenceBasis,
    FunctionHypothesis,
    IntensityLevel,
    Outcome,
    RecordedByRole,
)
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import Enum as sa_Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from py_db.models.base import Base, TimestampMixin


def _enum_col(enum_cls, name: str, **kwargs):
    """统一枚举列定义（值持久化枚举的中文值）。"""
    return mapped_column(
        sa_Enum(enum_cls, name=name, values_callable=lambda obj: [e.value for e in obj]),
        **kwargs,
    )


class Profile(Base, TimestampMixin):
    """个人档案（身份基础层 + 危机预案层字段组）。

    一个家属账号可创建多个档案；危机预案层为应急槽位唯一字段来源。
    隐私：档案数据绝不入向量索引（隐私与权限 §1.2）。
    """

    __tablename__ = "profiles"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        comment="个人唯一标识（UUID v4）",
    )
    caregiver_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属家属用户",
    )

    # ---- 身份基础层 ----
    nickname: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="家属自定义称呼（应急槽位：称呼来源）",
    )
    birth_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="出生日期（系统自动计算年龄区间）",
    )
    diagnosis_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="诊断类型（ASD / 疑似 ASD / 其他发育障碍）",
    )
    primary_behavior: Mapped[BehaviorBucket] = _enum_col(
        BehaviorBucket,
        "behavior_bucket",
        nullable=False,
        comment="主要行为类型（统一行为枚举）",
    )
    comorbidities: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="精神共病多选",
    )
    sensory_profile: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="感官特征多选",
    )
    triggers: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="已知情绪触发因素",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="是否为该账号下默认档案",
    )

    # ---- 危机预案层（应急槽位唯一字段来源） ----
    physical_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="走失专项：体貌特征（报警话术填充）",
    )
    familiar_places: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="走失专项：常去地点/可能去向",
    )
    water_risk: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="走失专项：水体风险与游泳能力",
    )
    soothing_items: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="有效安抚物/感官工具（事件 outcome=有效 推导作兜底）",
    )
    avoid_list: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="禁忌/无效方式",
    )
    communication_methods: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="沟通方式（语言水平 + AAC/视觉支持多选）",
    )
    emergency_contacts: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="安全联系人 [{name, relation, phone}]",
    )
    medication_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="用药记录（仅家属和老师可见）",
    )


class EventLog(Base):
    """事件时间线层（ABC 结构化，双模式记录）。

    一键打点：仅 behavior_type + 自动时间戳（is_quick_log=true）；
    事后补全：其余字段全可选；补全后 is_quick_log 可转 false。
    """

    __tablename__ = "event_logs"

    event_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        comment="事件唯一标识",
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.profile_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联个人（物理隔离键）",
    )
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="记录人用户",
    )
    recorded_by_role: Mapped[RecordedByRole] = _enum_col(
        RecordedByRole,
        "recorded_by_role",
        nullable=False,
        comment="记录人角色（parent / volunteer）",
    )
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="事件发生时间（可补录历史事件）",
    )
    is_quick_log: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="打点模式标记（补全后可转 false）",
    )
    behavior_type: Mapped[BehaviorBucket] = _enum_col(
        BehaviorBucket,
        "behavior_bucket",
        nullable=False,
        comment="行为大类（统一行为枚举，打点必填）",
    )
    behavior_form: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="具体形态（BPI-01 词表）",
    )
    intensity: Mapped[IntensityLevel | None] = _enum_col(
        IntensityLevel,
        "intensity_level",
        nullable=True,
        comment="强度 4 级（低/中/高/严重）",
    )
    duration: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="持续时间（如「约 5 分钟」）",
    )
    setting: Mapped[EventSetting | None] = _enum_col(
        EventSetting,
        "event_setting",
        nullable=True,
        comment="发生场景（含工作场所/托养机构）",
    )
    activity: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="进行中的活动",
    )
    people_present: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="在场人员",
    )
    physical_state: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="身体状态多选",
    )
    antecedent_category: Mapped[AntecedentCategory | None] = _enum_col(
        AntecedentCategory,
        "antecedent_category",
        nullable=True,
        comment="前事预置分类",
    )
    trigger_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="前事细节补充（可选）",
    )
    consequence: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="后果/应对（你做了什么）",
    )
    reaction: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="当事人对后果的反应",
    )
    outcome: Mapped[Outcome | None] = _enum_col(
        Outcome,
        "outcome",
        nullable=True,
        comment="干预效果结构标记（有效/部分有效/无效）",
    )
    function_hypothesis: Mapped[FunctionHypothesis | None] = _enum_col(
        FunctionHypothesis,
        "function_hypothesis",
        nullable=True,
        comment="功能假设（QABF 预留，M5 交互）",
    )
    manifestation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="具体表现补充描述（可选）",
    )
    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="自由备注（唯一自由文本字段）",
    )
    tags: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="自定义标签（最多 5 个）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="记录时间",
    )


class ProfessionalNote(Base):
    """专业评估层（老师/专家挂载到事件；不直接修改家属内容）。"""

    __tablename__ = "professional_notes"

    note_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        comment="评估唯一标识",
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_logs.event_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联事件",
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="提交老师/专家",
    )
    assessment: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="专业评估（FBA 简要结论）",
    )
    recommended_action: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="建议干预策略",
    )
    evidence_basis: Mapped[EvidenceBasis | None] = _enum_col(
        EvidenceBasis,
        "evidence_basis",
        nullable=True,
        comment="依据：NCAEP EBP / 机构经验 / 个案观察",
    )
    function_hypothesis: Mapped[FunctionHypothesis | None] = _enum_col(
        FunctionHypothesis,
        "function_hypothesis",
        nullable=True,
        comment="功能假设（QABF 预留）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="提交时间",
    )


class ProfileAccess(Base):
    """档案关联（家属主控的受邀协作）。

    家属邀请老师/专家/志愿者建立关联；家属可随时单方面解除，
    解除后立即失去全部访问入口（隐私与权限 §1.1）。
    """

    __tablename__ = "profile_access"
    __table_args__ = (
        UniqueConstraint("profile_id", "user_id", name="uq_profile_access_profile_user"),
    )

    access_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        comment="关联唯一标识",
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.profile_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联档案",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="被邀请用户",
    )
    role: Mapped[AccessRole] = _enum_col(
        AccessRole,
        "access_role",
        nullable=False,
        comment="关联角色（teacher/expert/volunteer）",
    )
    status: Mapped[AccessStatus] = _enum_col(
        AccessStatus,
        "access_status",
        nullable=False,
        default=AccessStatus.ACTIVE,
        server_default=AccessStatus.ACTIVE.value,
        comment="关联状态（active/revoked）",
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建关联的家属",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="建立时间",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="解除时间",
    )


__all__ = ["Profile", "EventLog", "ProfessionalNote", "ProfileAccess"]
