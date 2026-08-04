# @contract
"""个性化档案库 — Pydantic 契约（ADR-010 四层结构与 ABC 标准化目标态）。

四层结构（数据模型 §2-§5）：
- 身份基础层（IdentityLayer）：相对稳定的人口学与诊断信息
- 危机预案层（CrisisPlanLayer）：应急槽位的唯一字段来源
- 事件时间线层（EventLog）：ABC 结构化事件（一键打点 + 事后补全双模式）
- 专业评估层（ProfessionalNote）：老师/专家挂载，只读家属内容

关联管理（ProfileAccess）：家属主控，受邀协作（老师/专家/志愿者），
家属可随时单方面解除（隐私与权限 §1.1）。

已废除：旧单层扁平 DTO、severity_level 3 级、intervention_tried/result、
PROF-05 隐私 DTO（AccessDecision 等——数据级授权由 ProfileAccess 落地）。
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field, field_validator

from py_schemas.base import CampfireBaseModel
from py_schemas.enums import (
    AccessRole,
    AccessStatus,
    AntecedentCategory,
    BehaviorBucket,
    Comorbidity,
    CommunicationMethod,
    EventSetting,
    EvidenceBasis,
    FunctionHypothesis,
    IntensityLevel,
    Outcome,
    PhysicalState,
    RecordedByRole,
)


# ===========================================================================
# 身份基础层
# ===========================================================================


class IdentityLayerDto(CampfireBaseModel):
    """身份基础层（冷启动必填：birth_date/diagnosis_type/primary_behavior）。"""

    nickname: str | None = Field(
        default=None,
        max_length=10,
        description="家属自定义称呼（应急槽位来源；不得以「孩子」为默认称呼）",
    )
    birth_date: date = Field(..., description="出生日期（系统自动计算年龄区间，全生命周期覆盖）")
    diagnosis_type: str = Field(
        ...,
        description="诊断类型：ASD / 疑似 ASD / 其他发育障碍",
        examples=["ASD"],
    )
    primary_behavior: BehaviorBucket = Field(..., description="主要行为类型（统一行为枚举）")
    comorbidities: list[Comorbidity] = Field(default_factory=list, description="精神共病多选")
    sensory_profile: list[str] = Field(default_factory=list, description="感官特征多选")
    triggers: list[str] = Field(default_factory=list, description="已知情绪触发因素")
    is_default: bool = Field(default=False, description="是否为该账号下默认档案")


# ===========================================================================
# 危机预案层（应急槽位唯一字段来源）
# ===========================================================================


class EmergencyContact(CampfireBaseModel):
    """安全联系人。"""

    name: str = Field(..., max_length=20)
    relation: str = Field(..., max_length=20)
    phone: str = Field(..., min_length=5, max_length=20)


class CrisisPlanLayerDto(CampfireBaseModel):
    """危机预案层（冷启动仅走失史家庭重点引导走失组，其余渐进完善）。"""

    # 走失专项组
    physical_description: str | None = Field(default=None, description="体貌特征（报警话术填充）")
    familiar_places: list[str] = Field(default_factory=list, description="常去地点/可能去向")
    water_risk: list[str] = Field(default_factory=list, description="水体风险与游泳能力")
    # 干预偏好组
    soothing_items: list[str] = Field(default_factory=list, description="有效安抚物/感官工具")
    avoid_list: list[str] = Field(default_factory=list, description="禁忌/无效方式")
    # 沟通与联系组
    communication_methods: list[CommunicationMethod] = Field(
        default_factory=list, description="语言水平 + AAC/视觉支持多选"
    )
    emergency_contacts: list[EmergencyContact] = Field(default_factory=list, description="安全联系人")
    medication_notes: str | None = Field(default=None, description="用药记录（仅家属和老师可见）")


# ===========================================================================
# 档案 CRUD DTO
# ===========================================================================


class ProfileCreateRequest(CampfireBaseModel):
    """创建档案（身份基础层必填，危机预案层可选渐进完善）。"""

    identity: IdentityLayerDto
    crisis_plan: CrisisPlanLayerDto | None = Field(default=None, description="危机预案层（可选，渐进完善）")


class ProfileUpdateRequest(CampfireBaseModel):
    """更新档案（分层分步保存——两层均可独立部分更新）。"""

    identity: IdentityLayerDto | None = None
    crisis_plan: CrisisPlanLayerDto | None = None


class ProfileResponse(CampfireBaseModel):
    """档案完整视图（身份层 + 危机预案层 + 元信息）。"""

    profile_id: str
    caregiver_id: str
    identity: IdentityLayerDto
    crisis_plan: CrisisPlanLayerDto
    age_range: str = Field(..., description="系统计算的年龄区间（由 birth_date 推导）")
    created_at: str
    updated_at: str


class ProfileListItem(CampfireBaseModel):
    """档案列表项。"""

    profile_id: str
    nickname: str | None
    age_range: str
    diagnosis_type: str
    primary_behavior: BehaviorBucket
    is_default: bool
    created_at: str


# ===========================================================================
# 事件时间线层（ABC 结构化，双模式记录）
# ===========================================================================


class EventCreateRequest(CampfireBaseModel):
    """一键打点（危机中）：必填仅 behavior_type，自动时间戳（is_quick_log=true）。"""

    behavior_type: BehaviorBucket = Field(..., description="行为大类（打点必填）")
    event_time: str | None = Field(default=None, description="事件发生时间（ISO 8601；空=服务端当前时间）")
    session_id: str | None = Field(default=None, description="挂接的应急咨询会话（可挂应急会话自动生成）")


class EventCompleteRequest(CampfireBaseModel):
    """事后补全（A.4 顺序引导，全部可选）。"""

    behavior_form: str | None = Field(default=None, description="具体形态（BPI-01 词表）")
    intensity: IntensityLevel | None = None
    duration: str | None = Field(default=None, max_length=50, description="持续时间（如「约 5 分钟」）")
    setting: EventSetting | None = None
    activity: str | None = Field(default=None, max_length=100, description="进行中的活动")
    people_present: str | None = Field(default=None, max_length=100, description="在场人员")
    physical_state: list[PhysicalState] | None = None
    antecedent_category: AntecedentCategory | None = None
    trigger_description: str | None = Field(default=None, description="前事细节补充（可选）")
    consequence: str | None = Field(default=None, description="后果/应对（你做了什么）")
    reaction: str | None = Field(default=None, description="当事人对后果的反应")
    outcome: Outcome | None = Field(default=None, description="干预效果结构标记")
    manifestation: str | None = Field(default=None, description="具体表现补充描述")
    note: str | None = Field(default=None, description="自由备注（唯一自由文本字段）")
    tags: list[str] | None = Field(default=None, description="自定义标签（最多 5 个）")

    @field_validator("tags")
    @classmethod
    def tags_max_five(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and len(v) > 5:
            raise ValueError("自定义标签最多 5 个")
        return v


class EventResponse(CampfireBaseModel):
    """事件完整视图。"""

    event_id: str
    profile_id: str
    recorded_by: str
    recorded_by_role: RecordedByRole
    event_time: str
    is_quick_log: bool
    behavior_type: BehaviorBucket
    behavior_form: str | None = None
    intensity: IntensityLevel | None = None
    duration: str | None = None
    setting: EventSetting | None = None
    activity: str | None = None
    people_present: str | None = None
    physical_state: list[PhysicalState] | None = None
    antecedent_category: AntecedentCategory | None = None
    trigger_description: str | None = None
    consequence: str | None = None
    reaction: str | None = None
    outcome: Outcome | None = None
    function_hypothesis: FunctionHypothesis | None = None
    manifestation: str | None = None
    note: str | None = None
    tags: list[str] | None = None
    created_at: str


class EventListResponse(CampfireBaseModel):
    items: list[EventResponse] = Field(default_factory=list)
    total: int = Field(..., ge=0)


# ===========================================================================
# 专业评估层（Professional Note）
# ===========================================================================


class ProfessionalNoteCreateRequest(CampfireBaseModel):
    """专业评估挂载（老师/专家，关联到事件）。"""

    event_id: str = Field(..., description="关联事件 ID")
    assessment: str = Field(..., min_length=1, description="专业评估（FBA 简要结论）")
    recommended_action: str = Field(..., min_length=1, description="建议干预策略")
    evidence_basis: EvidenceBasis | None = None
    function_hypothesis: FunctionHypothesis | None = Field(default=None, description="功能假设（QABF 预留）")


class ProfessionalNoteResponse(CampfireBaseModel):
    note_id: str
    event_id: str
    author_id: str
    author_role: str
    assessment: str
    recommended_action: str
    evidence_basis: EvidenceBasis | None = None
    function_hypothesis: FunctionHypothesis | None = None
    created_at: str


# ===========================================================================
# 关联管理（ProfileAccess）
# ===========================================================================


class ProfileAccessCreateRequest(CampfireBaseModel):
    """关联邀请（家属主控）：按手机号邀请老师/专家/志愿者。"""

    invitee_phone: str = Field(
        ...,
        min_length=11,
        max_length=11,
        pattern=r"^1[3-9]\d{9}$",
        description="被邀请人手机号（须为已注册用户）",
    )
    role: AccessRole = Field(..., description="关联角色：teacher/expert/volunteer")


class ProfileAccessItem(CampfireBaseModel):
    access_id: str
    profile_id: str
    user_id: str
    phone: str = Field(..., description="被邀请人手机号（家属可见——主控方）")
    real_name: str | None = None
    role: AccessRole
    status: AccessStatus
    created_at: str


class ProfileAccessListResponse(CampfireBaseModel):
    items: list[ProfileAccessItem] = Field(default_factory=list)
    total: int = Field(..., ge=0)


__all__ = [
    # 四层
    "IdentityLayerDto",
    "CrisisPlanLayerDto",
    "EmergencyContact",
    # 档案 CRUD
    "ProfileCreateRequest",
    "ProfileUpdateRequest",
    "ProfileResponse",
    "ProfileListItem",
    # 事件
    "EventCreateRequest",
    "EventCompleteRequest",
    "EventResponse",
    "EventListResponse",
    # 专业评估
    "ProfessionalNoteCreateRequest",
    "ProfessionalNoteResponse",
    # 关联管理
    "ProfileAccessCreateRequest",
    "ProfileAccessItem",
    "ProfileAccessListResponse",
]
