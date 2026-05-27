"""PROF-05 档案隐私控制 + PROF-01 个人档案管理 — Pydantic Schema 定义。

PROF-05 部分：提供档案操作类型枚举、可见范围枚举、访问请求和裁决模型。
PROF-01 部分：提供个人档案管理的 DTO 和枚举类型。

对外接口类型定义与 docs/contracts/ 下的 JSON Schema 契约一致。

契约引用（PROF-05）：
- AccessOperation: docs/contracts/PROF-05/AccessOperation.json
- VisibleScope: docs/contracts/PROF-05/VisibleScope.json
- AccessRequest: docs/contracts/PROF-05/AccessRequest.json
- AccessDecision: docs/contracts/PROF-05/AccessDecision.json

契约引用（PROF-01）：
- DiagnosisType: docs/contracts/PROF-01/DiagnosisType.json
- ProfileBehaviorType: docs/contracts/PROF-01/ProfileBehaviorType.json
- LanguageLevel: docs/contracts/PROF-01/LanguageLevel.json
- SensoryFeature: docs/contracts/PROF-01/SensoryFeature.json
- Trigger: docs/contracts/PROF-01/Trigger.json
- AgeRange: docs/contracts/PROF-01/AgeRange.json
- ProfileCreate: docs/contracts/PROF-01/ProfileCreate.json
- ProfileUpdate: docs/contracts/PROF-01/ProfileUpdate.json
- ProfileResponse: docs/contracts/PROF-01/ProfileResponse.json
- ProfileListItem: docs/contracts/PROF-01/ProfileListItem.json
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ===========================================================================
# PROF-05 类型（保持不变）
# ===========================================================================


class AccessOperation(StrEnum):
    """个人档案操作类型枚举。

    定义可对个人档案执行的全部操作种类，六值枚举：
    - VIEW: 查看档案内容
    - CREATE: 新增档案数据
    - UPDATE: 修改档案数据
    - DELETE: 删除档案数据
    - SUPPLEMENT_ASSESSMENT: 补充专业评估
    - UNLINK: 解除老师关联

    与 docs/contracts/PROF-05/AccessOperation.json 契约一致。
    """

    VIEW = "view"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SUPPLEMENT_ASSESSMENT = "supplement_assessment"
    UNLINK = "unlink"


class VisibleScope(StrEnum):
    """档案数据可见范围枚举。

    定义访问被允许时请求人可查看的数据范围，三值枚举：
    - ALL_FIELDS: 全部字段可见（家属、关联老师/专家）
    - METADATA_ONLY: 仅元数据可见（管理员）
    - NOTHING: 无可见内容（非关联用户/拒绝时）

    与 docs/contracts/PROF-05/VisibleScope.json 契约一致。
    """

    ALL_FIELDS = "all_fields"
    METADATA_ONLY = "metadata_only"
    NOTHING = "none"


class AccessRequest(BaseModel):
    """档案访问请求输入模型。

    封装一次档案访问请求的全部上下文信息，由下游模块（PROF-01/03/04）
    在执行档案操作前构造并传递给 PrivacyGuard.check_access() 进行权限校验。

    与 docs/contracts/PROF-05/AccessRequest.json 契约一致。

    Attributes:
        operation: 请求执行的操作类型，必须在 AccessOperation 枚举值范围内。
        target_profile_id: 目标个人档案的唯一标识。
        requester_id: 请求发起人的用户唯一标识。
        requester_role: 请求发起人的角色枚举值（family/teacher/expert/admin/maintainer）。
        relation_type: 请求人与目标档案的关联关系类型（可选）。
    """

    operation: AccessOperation = Field(
        ...,
        description="请求执行的操作类型，必须在 AccessOperation 枚举值范围内",
    )
    target_profile_id: UUID = Field(
        ...,
        description="目标个人档案的唯一标识，必须对应 profiles 表中的有效记录",
    )
    requester_id: UUID = Field(
        ...,
        description="请求发起人的用户唯一标识，必须是已通过 AUTH-04 鉴权的有效用户",
    )
    requester_role: str = Field(
        ...,
        pattern="^(family|teacher|expert|admin|maintainer)$",
        description="请求发起人的角色枚举值，必须是五级角色之一",
    )
    relation_type: str | None = Field(
        default=None,
        description=(
            "请求人与目标档案的关联关系类型。"
            "linked_teacher/linked_expert 表示已关联，"
            "family_member 表示同家庭家属，none 表示无关联"
        ),
    )

    model_config = {"extra": "forbid"}


class AccessDecision(BaseModel):
    """档案访问裁决输出模型。

    封装 PrivacyGuard.check_access() 对一次档案访问请求的裁决结论。
    被下游模块（PROF-01/03/04）消费以决定是否继续执行数据库操作。

    与 docs/contracts/PROF-05/AccessDecision.json 契约一致。

    Attributes:
        allowed: 访问许可结果。true 表示允许，false 表示拒绝。
        visible_scope: 可见数据范围。allowed=true 时值取决于角色；allowed=false 时固定为 nothing。
        denial_reason: 拒绝原因。allowed=false 时必填，值为泛化消息"数据不存在"。
    """

    allowed: bool = Field(
        ...,
        description="访问许可结果。true 表示允许执行所请求的操作，false 表示拒绝",
    )
    visible_scope: VisibleScope = Field(
        ...,
        description=(
            "可见数据范围。allowed=true 时值取决于角色和访问矩阵"
            "（all_fields/metadata_only）；allowed=false 时固定为 none"
        ),
    )
    denial_reason: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "拒绝原因。allowed=false 时必填，值必须为泛化消息'数据不存在'。"
            "allowed=true 时为 null"
        ),
    )

    model_config = {"extra": "forbid"}


# ===========================================================================
# PROF-01 — 枚举类型
# ===========================================================================


class DiagnosisType(StrEnum):
    """患者诊断类型枚举。

    定义孤独症谱系障碍的专业诊断分类。
    用于个人档案的必填字段 diagnosis_type。

    与 docs/contracts/PROF-01/DiagnosisType.json 契约一致。
    """

    ASD = "ASD"
    SUSPECTED_ASD = "疑似ASD"
    OTHER_DEVELOPMENTAL_DISORDER = "其他发育障碍"


class ProfileBehaviorType(StrEnum):
    """个人档案主要行为类型枚举。

    定义孤独症患者最常出现的行为特征类别（单值必填）。
    用于个人档案的必填字段 primary_behavior。
    与 CASE-01 的 BehaviorType 业务域不同，使用 ProfileBehaviorType 命名以避碰。

    与 docs/contracts/PROF-01/ProfileBehaviorType.json 契约一致。
    """

    STEREOTYPED = "刻板行为"
    MELTDOWN = "情绪崩溃"
    SELF_INJURY = "自伤行为"
    AGGRESSION = "攻击行为"
    SOCIAL_WITHDRAWAL = "社交退缩"
    HYPERACTIVITY = "多动"


class LanguageLevel(StrEnum):
    """患者语言沟通能力评估等级枚举。

    用于个人档案的可选字段 language_level。

    与 docs/contracts/PROF-01/LanguageLevel.json 契约一致。
    """

    NO_LANGUAGE = "无语言"
    SINGLE_WORD = "单字词"
    SHORT_PHRASE = "短句"
    CONVERSATIONAL = "可对话"


class SensoryFeature(StrEnum):
    """患者感官特征枚举。

    定义孤独症人士常见的感官反应类别（可多选）。
    用于个人档案的可选字段 sensory_features。

    与 docs/contracts/PROF-01/SensoryFeature.json 契约一致。
    """

    AUDITORY_SENSITIVE = "听觉敏感"
    TACTILE_SENSITIVE = "触觉敏感"
    GUSTATORY_SENSITIVE = "味觉敏感"
    VISUAL_SENSITIVE = "视觉敏感"
    VESTIBULAR_SEEKING = "前庭寻求"
    PROPRIOCEPTIVE_SEEKING = "本体觉寻求"


class Trigger(StrEnum):
    """已知触发因素枚举。

    定义可能引发患者情绪波动或行为问题的环境/情境因素（可多选）。
    用于个人档案的可选字段 triggers。

    与 docs/contracts/PROF-01/Trigger.json 契约一致。
    """

    NOISE = "噪音"
    ENVIRONMENTAL_CHANGE = "环境变化"
    STRANGER = "陌生人"
    TASK_INTERRUPTION = "任务中断"
    SOCIAL_PRESSURE = "社交压力"
    SENSORY_OVERLOAD = "感官过载"
    PHYSICAL_DISCOMFORT = "身体不适"


class AgeRange(StrEnum):
    """患者年龄区间枚举。

    由出生日期实时计算得出（不持久化存储）。
    用于个人档案输出字段 age_range 和下游 PROF-02 的检索过滤。

    与 docs/contracts/PROF-01/AgeRange.json 契约一致。
    """

    AGE_0_3 = "0-3岁"
    AGE_4_6 = "4-6岁"
    AGE_7_12 = "7-12岁"
    AGE_13_18 = "13-18岁"
    AGE_18_PLUS = "18岁以上"


# ===========================================================================
# PROF-01 — DTO
# ===========================================================================


class ProfileCreate(BaseModel):
    """个人档案创建请求体。

    家属通过 POST /api/v1/profiles 创建新患者档案时提交的输入模型。
    必填字段为 birth_date、diagnosis_type、primary_behavior 共 3 项。

    与 docs/contracts/PROF-01/ProfileCreate.json 契约一致。
    """

    nickname: str | None = Field(
        default=None,
        max_length=10,
        description="档案昵称，家属对患者的日常称呼，仅家庭内部可见。不使用真实姓名",
        examples=["小明"],
    )
    birth_date: date = Field(
        ...,
        description="患者的出生日期，格式 YYYY-MM-DD，不能晚于当前日期",
        examples=["2019-03-15"],
    )
    diagnosis_type: DiagnosisType = Field(
        ...,
        description="患者获得的专业诊断结果分类",
        examples=["ASD"],
    )
    primary_behavior: ProfileBehaviorType = Field(
        ...,
        description="患者最常出现的行为特征类别",
        examples=["刻板行为"],
    )
    language_level: LanguageLevel | None = Field(
        default=None,
        description="患者的语言沟通能力评估等级",
        examples=["短句"],
    )
    sensory_features: list[SensoryFeature] = Field(
        default_factory=list,
        max_length=6,
        description="患者感官反应的特殊性（可多选，最多 6 项）",
    )
    triggers: list[Trigger] = Field(
        default_factory=list,
        max_length=7,
        description="已知会引发患者情绪波动或行为问题的环境或情境因素（可多选，最多 7 项）",
    )
    medication_notes: str | None = Field(
        default=None,
        max_length=200,
        description="患者当前服用的药物信息，建议注明药名和剂量。仅家属本人和关联老师可见",
        examples=["利培酮每日 0.5mg，睡前服用"],
    )

    @field_validator("birth_date")
    @classmethod
    def birth_date_not_future(cls, v: date) -> date:
        """校验出生日期不能晚于当前日期。"""
        if v > date.today():
            raise ValueError("出生日期不能晚于当前日期")
        return v

    model_config = {"extra": "forbid"}


class ProfileUpdate(BaseModel):
    """个人档案更新请求体。

    家属通过 PUT /api/v1/profiles/{profile_id} 修改已有档案时提交的输入模型。
    所有字段均为可选——仅提交需要更新的字段，未提交的字段保持原值不变。

    与 docs/contracts/PROF-01/ProfileUpdate.json 契约一致。
    """

    nickname: str | None = Field(
        default=None,
        max_length=10,
        description="档案昵称",
    )
    birth_date: date | None = Field(
        default=None,
        description="患者的出生日期，不能晚于当前日期",
    )
    diagnosis_type: DiagnosisType | None = Field(
        default=None,
        description="诊断类型",
    )
    primary_behavior: ProfileBehaviorType | None = Field(
        default=None,
        description="主要行为类型",
    )
    language_level: LanguageLevel | None = Field(
        default=None,
        description="语言水平",
    )
    sensory_features: list[SensoryFeature] | None = Field(
        default=None,
        max_length=6,
        description="感官特征（多选）",
    )
    triggers: list[Trigger] | None = Field(
        default=None,
        max_length=7,
        description="已知触发因素（多选）",
    )
    medication_notes: str | None = Field(
        default=None,
        max_length=200,
        description="用药备注",
    )

    @field_validator("birth_date")
    @classmethod
    def birth_date_not_future(cls, v: date | None) -> date | None:
        """校验出生日期不能晚于当前日期。"""
        if v is not None and v > date.today():
            raise ValueError("出生日期不能晚于当前日期")
        return v

    model_config = {"extra": "forbid"}


class ProfileResponse(BaseModel):
    """个人档案详情响应体。

    GET /api/v1/profiles/{profile_id} 和 POST/PUT 操作成功后返回的完整档案数据。
    age_range 字段由出生日期实时计算（不持久化）。

    与 docs/contracts/PROF-01/ProfileResponse.json 契约一致。
    """

    profile_id: UUID = Field(
        ...,
        description="系统为档案分配的唯一标识，UUID v4 格式，全局不可重复",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    nickname: str | None = Field(
        default=None,
        max_length=10,
        description="档案昵称",
    )
    birth_date: date = Field(
        ...,
        description="患者的出生日期，YYYY-MM-DD 格式",
    )
    age_range: AgeRange = Field(
        ...,
        description="由出生日期实时计算得出的年龄区间，不持久化存储",
    )
    diagnosis_type: DiagnosisType = Field(
        ...,
        description="诊断类型",
    )
    primary_behavior: ProfileBehaviorType = Field(
        ...,
        description="主要行为类型",
    )
    language_level: LanguageLevel | None = Field(
        default=None,
        description="语言水平",
    )
    sensory_features: list[SensoryFeature] = Field(
        ...,
        description="感官特征列表",
    )
    triggers: list[Trigger] = Field(
        ...,
        description="已知触发因素列表",
    )
    medication_notes: str | None = Field(
        default=None,
        max_length=200,
        description="用药备注",
    )
    is_default: bool = Field(
        ...,
        description="是否为当前家属账号的默认档案，同一账号下有且仅有一个默认为 true",
    )
    caregiver_id: UUID = Field(
        ...,
        description="所属家属用户标识，由服务端从 JWT payload 注入，不来自客户端请求",
    )
    created_at: datetime = Field(
        ...,
        description="档案首次创建的日期与时刻，服务端自动记录，不可修改",
    )
    updated_at: datetime = Field(
        ...,
        description="档案最近一次被修改的日期与时刻，每次修改后自动刷新",
    )

    model_config = {"extra": "forbid"}


class ProfileListItem(BaseModel):
    """个人档案列表条目响应体。

    GET /api/v1/profiles 返回的档案列表中的每个条目，
    为 ProfileResponse 的精简版。

    与 docs/contracts/PROF-01/ProfileListItem.json 契约一致。
    """

    profile_id: UUID = Field(
        ...,
        description="档案唯一标识",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    nickname: str | None = Field(
        default=None,
        max_length=10,
        description="档案昵称",
    )
    age_range: AgeRange = Field(
        ...,
        description="年龄区间（实时计算）",
    )
    diagnosis_type: DiagnosisType = Field(
        ...,
        description="诊断类型",
    )
    primary_behavior: ProfileBehaviorType = Field(
        ...,
        description="主要行为类型",
    )
    is_default: bool = Field(
        ...,
        description="是否为当前家属账号的默认档案",
    )

    model_config = {"extra": "forbid"}


# ===========================================================================
# 年龄区间计算工具函数
# ===========================================================================


def calculate_age_range(birth_date: date) -> AgeRange:
    """根据出生日期实时计算年龄区间。

    使用 dateutil.relativedelta 计算精确年龄（考虑闰年），
    然后映射到 AgeRange 枚举值。

    Args:
        birth_date: 患者的出生日期。

    Returns:
        AgeRange: 对应的年龄区间枚举值。
    """
    from dateutil.relativedelta import relativedelta

    age_years = relativedelta(date.today(), birth_date).years

    if age_years <= 3:
        return AgeRange.AGE_0_3
    elif age_years <= 6:
        return AgeRange.AGE_4_6
    elif age_years <= 12:
        return AgeRange.AGE_7_12
    elif age_years <= 18:
        return AgeRange.AGE_13_18
    else:
        return AgeRange.AGE_18_PLUS


# ===========================================================================
# 模块导出
# ===========================================================================


__all__ = [
    # PROF-05
    "AccessOperation",
    "VisibleScope",
    "AccessRequest",
    "AccessDecision",
    # PROF-01 枚举
    "DiagnosisType",
    "ProfileBehaviorType",
    "LanguageLevel",
    "SensoryFeature",
    "Trigger",
    "AgeRange",
    # PROF-01 DTO
    "ProfileCreate",
    "ProfileUpdate",
    "ProfileResponse",
    "ProfileListItem",
    # 工具函数
    "calculate_age_range",
]
