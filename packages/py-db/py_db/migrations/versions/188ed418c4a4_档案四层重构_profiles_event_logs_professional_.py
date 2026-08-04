"""档案四层重构-profiles-event_logs-professional_notes-profile_access

业务意图（阶段 S4 · ADR-010 档案四层与事件 ABC 标准化）：
  - profiles 重构：身份基础层（含 comorbidities/sensory_profile）+
    危机预案层字段组（走失专项/干预偏好/沟通联系——应急槽位唯一来源，
    S3 slot_filler 数据衔接点）；language_level 移入 communication_methods；
  - event_logs 重构：ABC 结构化（behavior_form BPI-01 词表/intensity 4 级/
    antecedent_category/consequence/reaction/outcome/is_quick_log/note），
    废除 intervention_tried/intervention_result/severity_level 旧字段；
  - professional_notes 新建：专业评估层（老师/专家挂载，不改家属内容）；
  - profile_access 新建：关联管理（家属主控，受邀协作，单方面解除），
    替代 teacher_links；
  - D2 授权破坏性重建：预发布期无真实数据，profiles/event_logs 直接
    drop+create（新枚举类型经 create_table 自动建型）。

Revision ID: 188ed418c4a4
Revises: 7dc982385261
Create Date: 2026-08-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '188ed418c4a4'
down_revision: Union[str, None] = '7dc982385261'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """档案四层重建（破坏性，D2 授权）。"""
    # 新枚举类型条件创建（behavior_bucket 已随 S3 迁移存在，跳过）
    _NEW_ENUMS = {
        "recorded_by_role": ["parent", "volunteer"],
        "intensity_level": ["低", "中", "高", "严重"],
        "event_setting": ["家庭", "学校", "公共场合", "机构", "工作场所", "托养机构"],
        "antecedent_category": ["给指令", "转换", "被拒绝", "感觉刺激", "社交", "常规改变", "躯体不适", "不明"],
        "outcome": ["有效", "部分有效", "无效"],
        "function_hypothesis": ["注意", "逃避", "实物", "自动强化", "躯体不适"],
        "evidence_basis": ["NCAEP EBP", "机构经验", "个案观察"],
        "access_role": ["teacher", "expert", "volunteer"],
        "access_status": ["active", "revoked"],
    }
    for type_name, values in _NEW_ENUMS.items():
        value_list = ", ".join(f"'{v}'" for v in values)
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{type_name}') "
            f"THEN CREATE TYPE {type_name} AS ENUM ({value_list}); END IF; END $$"
        )

    # consultation_sessions.profile_id 的 FK 依赖旧 profiles 表——先摘，重建后恢复
    op.drop_constraint('fk_consultation_sessions_profile_id_profiles', 'consultation_sessions', type_='foreignkey')
    # 旧表拆除（依赖序：teacher_links → event_logs → profiles）
    op.drop_index('ix_teacher_links_profile_id', table_name='teacher_links')
    op.drop_index('ix_teacher_links_teacher_id', table_name='teacher_links')
    op.drop_table('teacher_links')
    op.drop_index('ix_event_logs_profile_id', table_name='event_logs')
    op.drop_index('ix_event_logs_profile_event_time', table_name='event_logs')
    op.drop_table('event_logs')
    op.drop_index('ix_profiles_caregiver_id', table_name='profiles')
    op.drop_table('profiles')

    # 新 ENUM 类型（create_table 内联 sa.Enum 自动建型）
    op.create_table('profiles',
    sa.Column('profile_id', sa.Uuid(), nullable=False, comment='个人唯一标识（UUID v4）'),
    sa.Column('caregiver_id', sa.Uuid(), nullable=False, comment='所属家属用户'),
    sa.Column('nickname', sa.String(length=10), nullable=True, comment='家属自定义称呼（应急槽位：称呼来源）'),
    sa.Column('birth_date', sa.Date(), nullable=False, comment='出生日期（系统自动计算年龄区间）'),
    sa.Column('diagnosis_type', sa.String(length=20), nullable=False, comment='诊断类型（ASD / 疑似 ASD / 其他发育障碍）'),
    sa.Column('primary_behavior', postgresql.ENUM('情绪崩溃', '刻板行为', '自伤', '攻击', '走失', '用药相关', '社交退缩', '多动', '其他', name='behavior_bucket', create_type=False), nullable=False, comment='主要行为类型（统一行为枚举）'),
    sa.Column('comorbidities', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='精神共病多选'),
    sa.Column('sensory_profile', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='感官特征多选'),
    sa.Column('triggers', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='已知情绪触发因素'),
    sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False, comment='是否为该账号下默认档案'),
    sa.Column('physical_description', sa.Text(), nullable=True, comment='走失专项：体貌特征（报警话术填充）'),
    sa.Column('familiar_places', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='走失专项：常去地点/可能去向'),
    sa.Column('water_risk', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='走失专项：水体风险与游泳能力'),
    sa.Column('soothing_items', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='有效安抚物/感官工具（事件 outcome=有效 推导作兜底）'),
    sa.Column('avoid_list', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='禁忌/无效方式'),
    sa.Column('communication_methods', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='沟通方式（语言水平 + AAC/视觉支持多选）'),
    sa.Column('emergency_contacts', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='安全联系人 [{name, relation, phone}]'),
    sa.Column('medication_notes', sa.Text(), nullable=True, comment='用药记录（仅家属和老师可见）'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='记录创建时间'),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='记录最后更新时间'),
    sa.ForeignKeyConstraint(['caregiver_id'], ['users.id'], name=op.f('fk_profiles_caregiver_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('profile_id', name=op.f('pk_profiles'))
    )
    op.create_index(op.f('ix_profiles_caregiver_id'), 'profiles', ['caregiver_id'], unique=False)
    op.create_table('event_logs',
    sa.Column('event_id', sa.Uuid(), nullable=False, comment='事件唯一标识'),
    sa.Column('profile_id', sa.Uuid(), nullable=False, comment='关联个人（物理隔离键）'),
    sa.Column('recorded_by', sa.Uuid(), nullable=True, comment='记录人用户'),
    sa.Column('recorded_by_role', postgresql.ENUM('parent', 'volunteer', name='recorded_by_role', create_type=False), nullable=False, comment='记录人角色（parent / volunteer）'),
    sa.Column('event_time', sa.DateTime(timezone=True), nullable=False, comment='事件发生时间（可补录历史事件）'),
    sa.Column('is_quick_log', sa.Boolean(), server_default='true', nullable=False, comment='打点模式标记（补全后可转 false）'),
    sa.Column('behavior_type', postgresql.ENUM('情绪崩溃', '刻板行为', '自伤', '攻击', '走失', '用药相关', '社交退缩', '多动', '其他', name='behavior_bucket', create_type=False), nullable=False, comment='行为大类（统一行为枚举，打点必填）'),
    sa.Column('behavior_form', sa.String(length=50), nullable=True, comment='具体形态（BPI-01 词表）'),
    sa.Column('intensity', postgresql.ENUM('低', '中', '高', '严重', name='intensity_level', create_type=False), nullable=True, comment='强度 4 级（低/中/高/严重）'),
    sa.Column('duration', sa.String(length=50), nullable=True, comment='持续时间（如「约 5 分钟」）'),
    sa.Column('setting', postgresql.ENUM('家庭', '学校', '公共场合', '机构', '工作场所', '托养机构', name='event_setting', create_type=False), nullable=True, comment='发生场景（含工作场所/托养机构）'),
    sa.Column('activity', sa.String(length=100), nullable=True, comment='进行中的活动'),
    sa.Column('people_present', sa.String(length=100), nullable=True, comment='在场人员'),
    sa.Column('physical_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='身体状态多选'),
    sa.Column('antecedent_category', postgresql.ENUM('给指令', '转换', '被拒绝', '感觉刺激', '社交', '常规改变', '躯体不适', '不明', name='antecedent_category', create_type=False), nullable=True, comment='前事预置分类'),
    sa.Column('trigger_description', sa.Text(), nullable=True, comment='前事细节补充（可选）'),
    sa.Column('consequence', sa.Text(), nullable=True, comment='后果/应对（你做了什么）'),
    sa.Column('reaction', sa.Text(), nullable=True, comment='当事人对后果的反应'),
    sa.Column('outcome', postgresql.ENUM('有效', '部分有效', '无效', name='outcome', create_type=False), nullable=True, comment='干预效果结构标记（有效/部分有效/无效）'),
    sa.Column('function_hypothesis', postgresql.ENUM('注意', '逃避', '实物', '自动强化', '躯体不适', name='function_hypothesis', create_type=False), nullable=True, comment='功能假设（QABF 预留，M5 交互）'),
    sa.Column('manifestation', sa.Text(), nullable=True, comment='具体表现补充描述（可选）'),
    sa.Column('note', sa.Text(), nullable=True, comment='自由备注（唯一自由文本字段）'),
    sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='自定义标签（最多 5 个）'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='记录时间'),
    sa.ForeignKeyConstraint(['profile_id'], ['profiles.profile_id'], name=op.f('fk_event_logs_profile_id_profiles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], name=op.f('fk_event_logs_recorded_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('event_id', name=op.f('pk_event_logs'))
    )
    op.create_index(op.f('ix_event_logs_profile_id'), 'event_logs', ['profile_id'], unique=False)
    op.create_table('professional_notes',
    sa.Column('note_id', sa.Uuid(), nullable=False, comment='评估唯一标识'),
    sa.Column('event_id', sa.Uuid(), nullable=False, comment='关联事件'),
    sa.Column('author_id', sa.Uuid(), nullable=True, comment='提交老师/专家'),
    sa.Column('assessment', sa.Text(), nullable=False, comment='专业评估（FBA 简要结论）'),
    sa.Column('recommended_action', sa.Text(), nullable=False, comment='建议干预策略'),
    sa.Column('evidence_basis', postgresql.ENUM('NCAEP EBP', '机构经验', '个案观察', name='evidence_basis', create_type=False), nullable=True, comment='依据：NCAEP EBP / 机构经验 / 个案观察'),
    sa.Column('function_hypothesis', postgresql.ENUM('注意', '逃避', '实物', '自动强化', '躯体不适', name='function_hypothesis', create_type=False), nullable=True, comment='功能假设（QABF 预留）'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='提交时间'),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_professional_notes_author_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['event_id'], ['event_logs.event_id'], name=op.f('fk_professional_notes_event_id_event_logs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('note_id', name=op.f('pk_professional_notes'))
    )
    op.create_index(op.f('ix_professional_notes_event_id'), 'professional_notes', ['event_id'], unique=False)
    op.create_table('profile_access',
    sa.Column('access_id', sa.Uuid(), nullable=False, comment='关联唯一标识'),
    sa.Column('profile_id', sa.Uuid(), nullable=False, comment='关联档案'),
    sa.Column('user_id', sa.Uuid(), nullable=False, comment='被邀请用户'),
    sa.Column('role', postgresql.ENUM('teacher', 'expert', 'volunteer', name='access_role', create_type=False), nullable=False, comment='关联角色（teacher/expert/volunteer）'),
    sa.Column('status', postgresql.ENUM('active', 'revoked', name='access_status', create_type=False), server_default='active', nullable=False, comment='关联状态（active/revoked）'),
    sa.Column('created_by', sa.Uuid(), nullable=True, comment='创建关联的家属'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='建立时间'),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True, comment='解除时间'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_profile_access_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['profile_id'], ['profiles.profile_id'], name=op.f('fk_profile_access_profile_id_profiles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_profile_access_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('access_id', name=op.f('pk_profile_access')),
    sa.UniqueConstraint('profile_id', 'user_id', name='uq_profile_access_profile_user')
    )
    op.create_index(op.f('ix_profile_access_profile_id'), 'profile_access', ['profile_id'], unique=False)
    op.create_index(op.f('ix_profile_access_user_id'), 'profile_access', ['user_id'], unique=False)

    # 恢复 consultation_sessions → profiles 的 FK（升级起始摘除）
    op.create_foreign_key(
        'fk_consultation_sessions_profile_id_profiles',
        'consultation_sessions', 'profiles',
        ['profile_id'], ['profile_id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """拆除档案四层结构（旧语义不恢复——目标态不回退，D2）。"""
    op.drop_index(op.f('ix_profile_access_user_id'), table_name='profile_access')
    op.drop_index(op.f('ix_profile_access_profile_id'), table_name='profile_access')
    op.drop_table('profile_access')
    op.drop_index(op.f('ix_professional_notes_event_id'), table_name='professional_notes')
    op.drop_table('professional_notes')
    op.drop_index(op.f('ix_event_logs_profile_id'), table_name='event_logs')
    op.drop_table('event_logs')
    op.drop_index(op.f('ix_profiles_caregiver_id'), table_name='profiles')
    op.drop_table('profiles')
