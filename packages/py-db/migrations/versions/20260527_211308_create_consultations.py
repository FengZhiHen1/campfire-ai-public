"""CSLT-06: 创建 consultations 表。

迁移内容：
1. 创建 consultations 表（20 列）
2. 创建 UNIQUE 索引：consultations.request_id（幂等键）
3. 创建 COMPOSITE 索引：(user_id, consultation_time)（列表查询）
4. 创建单列索引：consultations.user_id（用户隔离）

表说明：
    consultations 表存储每次应急咨询的完整上下文数据。
    记录一旦归档即为只读（append-only），不支持修改或删除。
    request_id UNIQUE 约束 + INSERT ... ON CONFLICT DO NOTHING 实现幂等写入。

依赖说明：
    user_id 列逻辑 FK 到 users 表，不定义数据库外键约束。
    级联删除由应用层编排。

Revision ID: 20260527_211308
Create Date: 2026-05-27 21:13:08
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision: str = "20260527_211308"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：创建 consultations 表 + 全部索引。"""

    op.create_table(
        "consultations",
        # 主键
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="UUID v4 主键",
        ),
        # 幂等键
        sa.Column(
            "request_id",
            UUID(as_uuid=True),
            nullable=False,
            comment="幂等键，由 CSLT-08 编排层在咨询开始前生成 UUID v4",
        ),
        # 用户隔离
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            nullable=False,
            comment="本次咨询的发起家属用户 UUID（逻辑 FK 到 users 表）",
        ),
        # 危机等级
        sa.Column(
            "crisis_level",
            sa.String(10),
            nullable=False,
            comment="危机分级判定结果（mild/moderate/severe）",
        ),
        # 行为描述
        sa.Column(
            "behavior_description",
            sa.String(2000),
            nullable=False,
            comment="家属输入的患者行为描述文本（1-2000 汉字，已脱敏 PII）",
        ),
        # 咨询时间（服务端 NOW() 自动填充）
        sa.Column(
            "consultation_time",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="咨询发生时间（服务端时间，由 PostgreSQL NOW() 自动填充，覆盖客户端传入值）",
        ),
        # AI 生成方案全文
        sa.Column(
            "generated_plan",
            sa.Text(),
            nullable=False,
            comment="AI 生成的四段式应急方案全文（Markdown，最大 65536 字符）",
        ),
        # 来源引用列表
        sa.Column(
            "source_list",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="被引用案例的来源信息列表（JSONB 字符串数组）",
        ),
        # 免责声明
        sa.Column(
            "disclaimer",
            sa.Text(),
            nullable=False,
            comment="合规免责声明固定文本（入库前等值校验）",
        ),
        # 生成耗时
        sa.Column(
            "generation_time_ms",
            sa.Float(),
            nullable=False,
            comment="从接收输入到完整方案生成完毕的总耗时（毫秒）",
        ),
        # 部分生成标记
        sa.Column(
            "is_partial",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="是否为部分生成结果。true 时前端应展示「部分生成」提示",
        ),
        # 引用切片 ID 列表
        sa.Column(
            "referenced_slice_ids",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="LLM 输出中实际引用的案例切片 ID 列表（JSONB 数组）",
        ),
        # 生成结束原因
        sa.Column(
            "finish_reason",
            sa.String(10),
            nullable=False,
            comment="生成结束原因（COMPLETE/PARTIAL/BLOCKED/TIMEOUT/ERROR）",
        ),
        # 首字延迟
        sa.Column(
            "ttft_ms",
            sa.Float(),
            nullable=False,
            comment="首字延迟 Time to First Token（毫秒）。阻断场景下为 0",
        ),
        # 反馈标记
        sa.Column(
            "has_feedback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="反馈标记。默认 false。由 QUAL-03 单向更新为 true",
        ),
        # Token 消耗（可选）
        sa.Column(
            "token_input",
            sa.Integer(),
            nullable=True,
            comment="LLM 输入 Token 数量。阻断场景下为 NULL",
        ),
        sa.Column(
            "token_output",
            sa.Integer(),
            nullable=True,
            comment="LLM 输出 Token 数量。阻断场景下为 NULL",
        ),
        # 设备信息（可选）
        sa.Column(
            "device_info",
            JSONB(),
            nullable=True,
            comment="设备与平台信息（全字段 nullable，用于运维排查）",
        ),
        # 时间戳
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="记录创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="记录最后更新时间",
        ),
    )

    # 索引：request_id UNIQUE（幂等键）
    op.create_unique_constraint(
        "uq_consultations_request_id",
        "consultations",
        ["request_id"],
    )

    # 索引：user_id（用户隔离）
    op.create_index(
        "ix_consultations_user_id",
        "consultations",
        ["user_id"],
    )

    # 复合索引：(user_id, consultation_time) — 列表查询
    op.create_index(
        "ix_consultations_user_time",
        "consultations",
        ["user_id", "consultation_time"],
    )

    # 单列索引：request_id（配合 UNIQUE 约束的索引，显式创建以命名可控）
    op.create_index(
        "ix_consultations_request_id",
        "consultations",
        ["request_id"],
        unique=True,
    )


def downgrade() -> None:
    """回滚：删除 consultations 表及全部索引。"""

    op.drop_index("ix_consultations_request_id", table_name="consultations")
    op.drop_index("ix_consultations_user_time", table_name="consultations")
    op.drop_index("ix_consultations_user_id", table_name="consultations")
    op.drop_constraint("uq_consultations_request_id", "consultations", type_="unique")

    op.drop_table("consultations")
