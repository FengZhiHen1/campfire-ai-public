"""CSLT-06 咨询历史管理 — ConsultationHistory ORM 模型。

定义 consultations 表的 SQLAlchemy 2.0 声明式映射模型。
ConsultationHistory 模型作为应急咨询流程末端的记录存档节点，
按 user_id 物理隔离，append-only 写入，不支持修改或删除。

UUID 主键由 UUIDPrimaryKeyMixin 提供（Python uuid.uuid4 作为应用层后备）。
幂等键 request_id 由 CSLT-08 编排层生成并传入，本模块仅做存储和冲突检测。
"""

# @contract — consultations 表 Schema 契约

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from py_db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ConsultationHistory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """咨询历史记录 ORM 模型。

    映射 PostgreSQL consultations 表，存储每次应急咨询的完整上下文数据。
    记录一旦归档即为只读，不支持用户自行修改或删除。

    索引策略：
    - PK: id（UUIDPrimaryKeyMixin 提供）
    - UNIQUE: request_id（幂等键，由 CSLT-08 生成）
    - COMPOSITE: (user_id, consultation_time DESC)（驱动列表查询）
    - INDEX: user_id（用户隔离）

    Attributes:
        id: UUID v4 主键（由 UUIDPrimaryKeyMixin 提供）。
        request_id: 幂等键，由 CSLT-08 编排层在咨询开始前生成 UUID v4。
        user_id: 本次咨询的发起家属用户 UUID（FK 到 users 表，不定义外键约束）。
        crisis_level: 危机分级判定结果（mild/moderate/severe）。
        behavior_description: 家属输入的患者行为描述文本（1-2000 汉字，已脱敏 PII）。
        consultation_time: 咨询发生时间（服务端 NOW() 自动填充）。
        generated_plan: AI 生成的四段式应急方案全文（Markdown，最大 65536 字）。
        plan_sections: AI 生成的四段式应急方案结构化数据（段落标题 → 内容列表）。
        source_list: 被引用案例的来源信息列表（JSONB 数组）。
        disclaimer: 合规免责声明固定文本。
        generation_time_ms: 方案生成总耗时（毫秒）。
        is_partial: 是否为部分生成结果。
        referenced_slice_ids: LLM 输出中实际引用的案例切片 ID 列表（JSONB 数组）。
        finish_reason: 生成结束原因（COMPLETE/PARTIAL/BLOCKED/TIMEOUT/ERROR）。
        ttft_ms: 首字延迟 Time to First Token（毫秒）。
        has_feedback: 是否已提交反馈标记（默认 false，由 QUAL-03 单向更新为 true）。
        token_input: LLM 输入 Token 数量（阻断场景下为 NULL）。
        token_output: LLM 输出 Token 数量（阻断场景下为 NULL）。
        device_info: 设备与平台信息（JSONB，全字段 nullable）。
        created_at: 记录创建时间（由 TimestampMixin 提供）。
        updated_at: 记录最后更新时间（由 TimestampMixin 提供）。
    """

    __tablename__ = "consultations"

    # 复合索引: (user_id, consultation_time DESC) — 列表查询
    __table_args__ = (Index("ix_consultations_user_time", "user_id", "consultation_time"),)

    request_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
        unique=True,
        comment="幂等键，由 CSLT-08 编排层在咨询开始前生成 UUID v4",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="本次咨询的发起家属用户 UUID（FK 到 users 表）",
    )
    crisis_level: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="危机分级判定结果（mild/moderate/severe）",
    )
    behavior_description: Mapped[str] = mapped_column(
        String(2000),
        nullable=False,
        comment="家属输入的患者行为描述文本（1-2000 汉字，已脱敏 PII）",
    )
    consultation_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="咨询发生时间（服务端时间，由 PostgreSQL NOW() 自动填充）",
    )
    generated_plan: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="AI 生成的四段式应急方案全文（Markdown，最大 65536 字符）",
    )
    plan_sections: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=dict,
        comment="AI 生成的四段式应急方案结构化数据（段落标题 → 内容列表）",
    )
    source_list: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="被引用案例的来源信息列表（JSONB 数组）",
    )
    disclaimer: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="合规免责声明固定文本",
    )
    generation_time_ms: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="从接收输入到完整方案生成完毕的总耗时（毫秒）",
    )
    is_partial: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否为部分生成结果。true 时前端应展示「部分生成」提示",
    )
    referenced_slice_ids: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="LLM 输出中实际引用的案例切片 ID 列表（JSONB 数组）",
    )
    finish_reason: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="生成结束原因（COMPLETE/PARTIAL/BLOCKED/TIMEOUT/ERROR）",
    )
    ttft_ms: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="首字延迟 Time to First Token（毫秒）。阻断场景下为 0",
    )
    has_feedback: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="反馈标记。默认 false。由 QUAL-03 单向更新为 true",
    )
    token_input: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="LLM 输入 Token 数量。阻断场景下为 NULL",
    )
    token_output: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="LLM 输出 Token 数量。阻断场景下为 NULL",
    )
    device_info: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="设备与平台信息（全字段 nullable，用于运维排查）",
    )
    confidence_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="CSLT-05 置信度后校验综合得分（0.0-1.0）。null 表示尚未完成校验或校验失败",
    )
    validation_verdict: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="CSLT-05 置信度判定结论（PASS/APPEND_WARNING/FORCE_BLOCK）。null 表示尚未完成校验",
    )

    def __repr__(self) -> str:
        return (
            f"<ConsultationHistory(id={self.id!r}, "
            f"request_id={self.request_id!r}, "
            f"user_id={self.user_id!r}, "
            f"crisis_level={self.crisis_level!r}, "
            f"consultation_time={self.consultation_time!r})>"
        )


__all__ = ["ConsultationHistory"]
