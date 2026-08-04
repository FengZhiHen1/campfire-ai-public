# @contract
"""应急咨询 — Pydantic 契约（ADR-009 时刻分层目标态）。

时刻分层链路契约（智能应急咨询 §二/§五/§六）：
- 桶选择/阶段回答/文字描述统一创建端点请求
- SafetyCardDto（安全卡，含槽位填充结果）
- EmergencyPlan（四段式输出契约，仅约束首份方案）
- 追问/历史/兜底信号 DTO
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from py_schemas.base import CampfireBaseModel
from py_schemas.enums import (
    BehaviorBucket,
    CrisisStage,
    FallbackSignal,
    MeltdownType,
    TurnType,
)

# 统一免责声明（红线安全门 §九）
DISCLAIMER_TEXT: str = (
    "AI 建议仅供参考，不构成医疗诊断或治疗建议。"
    "涉及身体伤害、走失风险或用药决策时，请立即联系专业医疗机构。"
)


# ===========================================================================
# 创建/推进端点（POST /api/v1/consult/stream）
# ===========================================================================


class ConsultStreamCreateRequest(CampfireBaseModel):
    """应急咨询创建/推进请求（POST /api/v1/consult/stream）。

    三种输入形态（智能应急咨询 §六）：
    - 桶选择：session_id 空 + bucket 必填（新建会话）
    - 阶段回答：session_id 非空 + stage_answer（quick-reply 值）
    - 文字描述：text（新建时可选附带；会话内为补充细节触发精化）
    """

    session_id: UUID | None = Field(
        default=None,
        description="已有会话 ID（阶段回答/补充描述时携带；为空则新建会话）",
    )
    profile_id: UUID | None = Field(
        default=None,
        description="关联患者档案 ID（可选；无档案模式回退纯模板）",
    )
    bucket: BehaviorBucket | None = Field(
        default=None,
        description="行为桶选择（新建会话必填；红线桶直接命中红线）",
    )
    stage_answer: str | None = Field(
        default=None,
        max_length=100,
        description="阶段单点问题的回答（quick-reply 值，会话内推进）",
    )
    text: str | None = Field(
        default=None,
        max_length=2000,
        description="可选文字描述（新建附带 / 会话内补充细节）",
    )

    @model_validator(mode="after")
    def _validate_shape(self) -> "ConsultStreamCreateRequest":
        if self.session_id is None and self.bucket is None:
            raise ValueError("新建会话必须选择行为桶（bucket）")
        if self.session_id is not None and self.stage_answer is None and self.text is None:
            raise ValueError("会话内推进必须携带 stage_answer 或 text")
        return self


class ConsultStreamCreateResponse(CampfireBaseModel):
    """创建/推进响应——session_id 供事件流端点连接。"""

    session_id: str = Field(..., description="会话 ID（GET /api/v1/consult/stream/{session_id} 连接事件流）")


# ===========================================================================
# 追问端点
# ===========================================================================


class FollowupRequest(CampfireBaseModel):
    """追问轮请求（POST /api/v1/consult/stream/{session_id}/followup）。

    通用 Agent 会话：自由文本回复，不套四段式契约（智能应急咨询 §5.3）。
    """

    text: str = Field(..., min_length=1, max_length=2000, description="追问内容")


class UnresolvedMarkRequest(CampfireBaseModel):
    """用户标记未解决（确定性兜底信号之一，智能应急咨询 §七）。"""

    mark: bool = Field(default=True, description="标记未解决")


# ===========================================================================
# 安全卡 DTO（此刻安全层）
# ===========================================================================


class SafetyCardDto(CampfireBaseModel):
    """安全卡消息（槽位填充后的展示形态）。

    卡体为专家审核静态模板（bucket × stage 组织），
    槽位经档案确定性填充（无档案回退纯模板——冷启动兼容）。
    """

    card_id: str = Field(..., description="安全卡模板 ID")
    bucket: BehaviorBucket | None = Field(default=None, description="所属行为桶（None 为通用卡）")
    stage: CrisisStage | None = Field(default=None, description="所属危机阶段（None 为通用桶卡）")
    title: str = Field(..., description="卡片标题")
    content: str = Field(..., description="槽位填充后的卡体正文（祈使短句、一句一个动作）")
    personalized: bool = Field(default=False, description="是否经过档案槽位填充（False = 纯模板回退）")
    variant: str = Field(
        default="normal",
        description="展示变体：normal 常规 / redline 高危标红置顶 / elopement 走失一键流程",
    )


class StageQuestionDto(CampfireBaseModel):
    """阶段单点问题（每次一问，quick-reply 大字按钮）。"""

    question_id: str = Field(..., description="问题标识（阶段推进状态机键）")
    question: str = Field(..., description="问题文案")
    options: list[str] = Field(..., min_length=2, description="quick-reply 选项值")
    stage: CrisisStage | None = Field(default=None, description="回答后进入的阶段（由状态机判定）")


class RedlineGuideDto(CampfireBaseModel):
    """红线指引消息（标红置顶：高危桶卡 + 就医/紧急求助指引）。"""

    card: SafetyCardDto = Field(..., description="高危桶卡（槽位填充后）")
    guidance: str = Field(..., description="就医与紧急求助指引（紧急电话、就近就医建议）")
    gate_trigger: str = Field(..., description="触发规则 ID（审计关联）")


class FallbackNoticeDto(CampfireBaseModel):
    """兜底提示消息（确定性兜底信号触发：强提示 + 求助指引）。"""

    signal: FallbackSignal = Field(..., description="触发的兜底信号")
    message: str = Field(..., description="强提示文案")
    guidance: str = Field(..., description="求助指引")


# ===========================================================================
# 四段式输出契约（仅约束首份方案）
# ===========================================================================


class SourceRef(CampfireBaseModel):
    """来源引用（每条建议必须标注来源案例/专家文章——溯源要求）。"""

    case_id: str | None = Field(default=None, description="案例切片 ID")
    title: str = Field(..., description="来源标题（案例/专家文章）")
    source_type: str = Field(default="案例", description="来源类型")


class EmergencyPlan(CampfireBaseModel):
    """四段式完整方案契约（智能应急咨询 §5.2，仅约束首份方案）。

    Skill metadata output-schema 指向本契约（Pydantic 校验失败 →
    阻断输出 + 降级检索结果直出，§九 失败语义）。
    """

    immediate_action: str = Field(..., min_length=1, description="即时安全干预动作（与此刻层卡片一致并展开）")
    soothing_script: str = Field(..., min_length=1, description="情绪安抚话术（适配语言水平与 meltdown/tantrum 分流）")
    observation: str = Field(..., min_length=1, description="后续观察指标（需持续观察的行为/情绪指标）")
    medical_judgment: str = Field(..., min_length=1, description="就医判断标准（强制段落——何种情况必须就医）")
    sources: list[SourceRef] = Field(default_factory=list, description="来源引用列表")
    disclaimer: str = Field(default=DISCLAIMER_TEXT, description="免责声明（固定文案）")


# ===========================================================================
# 安全卡管理 DTO（admin/expert 内容运营，M3 审核链路复用）
# ===========================================================================


class SafetyCardUpsertRequest(CampfireBaseModel):
    """安全卡创建/更新请求（更新生成新版本）"""

    bucket: BehaviorBucket | None = Field(default=None, description="所属行为桶；null 为通用卡")
    stage: CrisisStage | None = Field(default=None, description="所属危机阶段；null 为通用桶卡")
    title: str = Field(..., min_length=1, max_length=100)
    card_template: str = Field(..., min_length=1, description="含槽位占位符的模板正文")


class SafetyCardManageItem(CampfireBaseModel):
    """安全卡管理列表项。"""

    card_id: str
    bucket: BehaviorBucket | None
    stage: CrisisStage | None
    title: str
    card_template: str
    review_status: str
    version: int
    updated_at: str


class SafetyCardReviewRequest(CampfireBaseModel):
    """安全卡审核操作（approve/reject/unlist）。"""

    action: str = Field(..., pattern=r"^(approve|reject|unlist)$")
    comment: str | None = Field(default=None, max_length=200)


# ===========================================================================
# 历史与详情 DTO
# ===========================================================================


class ConsultationTurnDto(CampfireBaseModel):
    """会话内的一轮咨询（首份方案或追问轮）。"""

    id: str
    turn_type: TurnType
    behavior_description: str | None = None
    generated_plan: EmergencyPlan | None = None
    reply_text: str | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    disclaimer_served: bool = False
    created_at: str


class ConsultationSessionDetailDto(CampfireBaseModel):
    """咨询详情（完整方案 + 引用来源 + 会话记录）。"""

    id: str
    profile_id: str | None = None
    bucket: BehaviorBucket
    crisis_stage: CrisisStage | None = None
    meltdown_type: MeltdownType | None = None
    turns: list[ConsultationTurnDto] = Field(default_factory=list)
    created_at: str


class ConsultationSessionListItem(CampfireBaseModel):
    """咨询历史列表项。"""

    id: str
    bucket: BehaviorBucket
    crisis_stage: CrisisStage | None = None
    turn_count: int = Field(..., ge=0)
    created_at: str


__all__ = [
    "DISCLAIMER_TEXT",
    "ConsultStreamCreateRequest",
    "ConsultStreamCreateResponse",
    "FollowupRequest",
    "UnresolvedMarkRequest",
    "SafetyCardDto",
    "SafetyCardUpsertRequest",
    "SafetyCardManageItem",
    "SafetyCardReviewRequest",
    "StageQuestionDto",
    "RedlineGuideDto",
    "FallbackNoticeDto",
    "SourceRef",
    "EmergencyPlan",
    "ConsultationTurnDto",
    "ConsultationSessionDetailDto",
    "ConsultationSessionListItem",
]
