"""PROF-05 档案隐私控制 + PROF-01 个人档案管理 + PROF-03 事件记录管理 — ORM 模型定义。

PROF-05 部分：teacher_links 表（家属-老师关联关系表）。
PROF-01 部分：profiles 表（个人档案主表）。
PROF-03 部分：event_logs 表（事件记录表，16 列）。

teacher_links 表用于存储家属（profile owner）与老师/专家之间的
关联关系。每次档案访问请求到达时，PrivacyGuard 通过实时查询此表
（WHERE unlinked_at IS NULL）判定请求人是否与目标档案存在有效关联。

profiles 表是 PROF-01 的核心数据表，存储每个患者的个人档案信息。
使用 JSONB 存储多选标签字段（sensory_features、triggers），
利用 GIN 索引支持下游 PROF-02 的标签过滤查询。

级联删除由 PROF-01 应用层编排。
"""

# @contract — profiles / teacher_links / event_logs 表 Schema 契约

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from py_db.models.base import Base, TimestampMixin


# ===========================================================================
# PROF-01 — Profile ORM 模型
# ===========================================================================


class Profile(Base):
    """个人档案 ORM 模型。

    映射 profiles 表，存储患者的个人档案信息。
    每个档案属于一个家属用户（caregiver_id），
    患者数据严格按 caregiver_id 物理隔离。

    Attributes:
        profile_id: UUID v4 主键，由服务端 uuid.uuid4() 生成。
        caregiver_id: 所属家属用户 UUID，建立索引支持按用户查询。
        nickname: 档案昵称，可选，最长 10 字符。
        birth_date: 患者出生日期，用于实时计算年龄区间。
        diagnosis_type: 诊断类型枚举值（ASD/疑似ASD/其他发育障碍）。
        primary_behavior: 主要行为类型枚举值。
        language_level: 语言水平枚举值，可选。
        sensory_features: 感官特征列表，JSONB 数组存储。
        triggers: 已知触发因素列表，JSONB 数组存储。
        medication_notes: 用药备注，可选，最长 200 字符。
        is_default: 是否为当前家属账号的默认档案。
        created_at: 记录创建时间（由 TimestampMixin 语义提供）。
        updated_at: 记录最后更新时间，用作乐观锁版本。
    """

    __tablename__ = "profiles"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID v4 主键",
    )
    caregiver_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属家属用户 UUID",
    )
    nickname: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        default=None,
        comment="档案昵称，最长 10 字符",
    )
    birth_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="患者出生日期",
    )
    diagnosis_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="诊断类型（ASD/疑似ASD/其他发育障碍）",
    )
    primary_behavior: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="主要行为类型",
    )
    language_level: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        default=None,
        comment="语言水平",
    )
    sensory_features: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="感官特征列表（JSONB 数组）",
    )
    triggers: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="已知触发因素列表（JSONB 数组）",
    )
    medication_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="用药备注",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否为当前家属账号的默认档案",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="记录创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="记录最后更新时间（乐观锁版本）",
    )

    def __repr__(self) -> str:
        return (
            f"<Profile(profile_id={self.profile_id!r}, "
            f"caregiver_id={self.caregiver_id!r}, "
            f"nickname={self.nickname!r}, "
            f"is_default={self.is_default!r})>"
        )


# ===========================================================================
# PROF-05 — TeacherLink ORM 模型（保持不变）
# ===========================================================================


class TeacherLink(Base, TimestampMixin):
    """家属-老师关联关系 ORM 模型。

    映射 teacher_links 表，记录家属（档案拥有者）与老师/专家之间的
    关联关系。有效关联（unlinked_at IS NULL）是该老师/专家访问对应
    档案的权限基础。

    Attributes:
        link_id: UUID v4 主键。
        profile_id: 目标个人档案 UUID（FK 到 profiles 表）。
        teacher_id: 关联老师/专家的用户 UUID（FK 到 users 表）。
        role: 关联角色（teacher / expert），表示被关联用户在档案中的身份。
        unlinked_at: 解除关联的时间戳。NULL 表示关联有效，非 NULL 表示已解除。
        version: 乐观锁版本号，用于并发控制。
        created_at: 记录创建时间（由 TimestampMixin 提供）。
        updated_at: 记录最后更新时间（由 TimestampMixin 提供）。
    """

    __tablename__ = "teacher_links"

    link_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID v4 主键",
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.profile_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="目标个人档案 UUID",
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联老师/专家的用户 UUID",
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="关联角色（teacher / expert）",
    )
    unlinked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="解除关联时间戳，NULL 表示关联有效",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="乐观锁版本号",
    )

    def __repr__(self) -> str:
        return (
            f"<TeacherLink(link_id={self.link_id!r}, "
            f"profile_id={self.profile_id!r}, "
            f"teacher_id={self.teacher_id!r}, "
            f"role={self.role!r}, "
            f"unlinked_at={self.unlinked_at!r}, "
            f"version={self.version!r})>"
        )


# ===========================================================================
# PROF-03 — EventLog ORM 模型
# ===========================================================================


class EventLog(Base):
    """事件记录 ORM 模型。

    映射 event_logs 表，存储家属为关联患者记录的行为/情绪事件。
    每条事件属于一个档案（profile_id），按 profile_id 物理隔离。
    所有查询必须含 WHERE profile_id = :pid 条件。

    不设 ON DELETE CASCADE 外键——级联删除由 PROF-01
    应用层通过 EventRepository.delete_by_profile() 编排。

    Attributes:
        event_id: UUID v4 主键，由服务端 uuid.uuid4() 生成。
        profile_id: 所属档案 UUID，建立单列索引和复合索引。
        recorded_by: 记录人用户 UUID（创建时从 JWT 获取，不可修改）。
        recorded_by_role: 记录人角色，固定值 'parent'。
        event_time: 事件实际发生时间（UTC），支持 30 天内的补录。
        behavior_type: 行为类型（ProfileBehaviorType 枚举字符串值）。
        severity_level: 家属自评严重程度（SeverityLevel 枚举字符串值）。
        setting: 事件发生场景（EventSetting 枚举字符串值），可选。
        trigger_description: 触发因素描述，自由文本。
        manifestation: 具体表现描述，自由文本。
        intervention_tried: 尝试干预措施，自由文本。
        intervention_result: 干预结果，自由文本。
        is_professional: 是否有专业评估补充，默认为 false。
        tags: 自定义标签列表，JSONB 数组，可选。
        created_at: 记录创建时间。
        updated_at: 记录最后更新时间。
    """

    __tablename__ = "event_logs"

    # 复合索引: (profile_id, event_time DESC) — 列表查询
    __table_args__ = (
        Index("ix_event_logs_profile_event_time", "profile_id", "event_time"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID v4 主键",
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.profile_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属档案 UUID",
    )
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="记录人用户 UUID",
    )
    recorded_by_role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="parent",
        comment="记录人角色，固定为 'parent'",
    )
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="事件实际发生时间（UTC）",
    )
    behavior_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="行为类型",
    )
    severity_level: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="家属自评严重程度",
    )
    setting: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        default=None,
        comment="事件发生场景",
    )
    trigger_description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="触发因素描述",
    )
    manifestation: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="具体表现描述",
    )
    intervention_tried: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="尝试干预措施",
    )
    intervention_result: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="干预结果",
    )
    is_professional: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否有专业评估补充",
    )
    tags: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="自定义标签列表（JSONB 数组）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="记录创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="记录最后更新时间",
    )

    def __repr__(self) -> str:
        return (
            f"<EventLog(event_id={self.event_id!r}, "
            f"profile_id={self.profile_id!r}, "
            f"behavior_type={self.behavior_type!r}, "
            f"event_time={self.event_time!r})>"
        )


__all__ = [
    "Profile",
    "TeacherLink",
    "EventLog",
]
