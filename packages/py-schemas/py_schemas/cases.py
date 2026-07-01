# @contract
"""CASE-01 案例录入管理 — Pydantic Schema 定义。

对外接口的类型定义必须与 docs/contracts/CASE-01/ 下的 JSON 契约一致。
所有模型继承 CampfireBaseModel（统一 extra='forbid'）。

契约引用：
- CaseCreateRequest: docs/contracts/CASE-01/CaseCreateRequest.json
- CaseUpdate: docs/contracts/CASE-01/CaseUpdate.json
- CaseResponse: docs/contracts/CASE-01/CaseResponse.json
- CaseListItem: docs/contracts/CASE-01/CaseListItem.json
- PiiWarning: docs/contracts/CASE-01/PiiWarning.json
- PiiDetectionResult: docs/contracts/CASE-01/PiiDetectionResult.json
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import Field, StrictBool, field_validator

from py_schemas.base import CampfireBaseModel
from py_schemas.enums.case_enums import (
    BehaviorType,
    CaseStatus,
    EvidenceLevel,
    FamilyDisplayCategory,
    SceneType,
    SeverityLevel,
    SourceType,
)

# ---------------------------------------------------------------------------
# 泛型类型变量
# ---------------------------------------------------------------------------

T = TypeVar("T")

# ---------------------------------------------------------------------------
# NCAEP 循证实践标签集（用于 EBP 一致性校验）
# ---------------------------------------------------------------------------

NCAEP_EBP_LABELS: set[str] = {
    "辅助技术",
    "行为动量",
    "代币系统",
    "反应中断/重定向",
    "功能性行为评估",
    "功能性沟通训练",
    "家长实施干预",
    "同伴介入训练",
    "强化",
    "回合式教学",
    "认知行为干预",
    "社会故事",
    "社会技能训练",
    "视频示范",
    "塑造",
    "提示",
    "消退",
    "延迟满足训练",
    "任务分析",
    "视觉支持",
    "自我管理",
    "自然情境教学",
    "关键反应训练",
    "语言训练(表达)",
    "语言训练(接受)",
    "结构化游戏小组",
    "练习与复习",
}


# ---------------------------------------------------------------------------
# 基础模型
# ---------------------------------------------------------------------------


class AttachmentRef(CampfireBaseModel):
    """附件引用结构。

    临时由 CASE-01 定义，待 CASE-02 落地后迁移为正式引用。
    仅存储文件名与引用路径，不存储文件内容。
    """

    file_name: str = Field(..., description="附件文件名")
    minio_path: str = Field(..., description="MinIO 存储路径")
    file_type: str = Field(..., description="附件文件类型（MIME）")
    file_size: int = Field(..., ge=0, description="附件文件大小（字节）")
    uploaded_at: datetime = Field(..., description="上传时间")
    sort_order: int = Field(..., ge=0, description="排序顺序")


# ---------------------------------------------------------------------------
# PII 检测模型
# ---------------------------------------------------------------------------


class PiiWarning(CampfireBaseModel):
    """PII 单条警告。

    对叙事文本执行正则匹配检测，检测到疑似 PII 时生成此警告。
    在前端提交按钮附近逐条展示，用户确认已脱敏后可继续提交。
    """

    pii_type: str = Field(
        ...,
        description="PII 类型（真实姓名/手机号码/身份证号/家庭住址/学校名称）",
    )
    detected_text: str = Field(..., description="检测到的疑似 PII 文本片段")
    position_start: int = Field(..., ge=0, description="在叙事文本中的起始字符位置")
    position_end: int = Field(..., ge=0, description="在叙事文本中的结束字符位置")


class PiiDetectionResult(CampfireBaseModel):
    """PII 检测完整结果。

    对叙事文本执行 5 类 PII 正则匹配检测后返回的完整结果。
    检测为提示性辅助检测，不强制阻断提交。
    """

    has_pii: bool = Field(..., description="是否检测到疑似 PII")
    warnings: list[PiiWarning] = Field(..., description="PII 警告列表，has_pii 为 False 时为空列表")


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class CaseCreateRequest(CampfireBaseModel):
    """案例创建请求体。

    包含 L1 原始叙事层 4 个字段和 L2 结构化卡片层 13 个必填字段 + 2 个选填字段。
    L2 四段式字段（immediate_action/comforting_phrase/observation_metrics/medical_criteria）
    在创建时仅校验非空，提交时执行完整性校验。
    """

    # MVP 核心必填字段
    title: str = Field(..., max_length=100, description="案例标题（L1），去个性化后的简短名称")
    behavior_type: BehaviorType = Field(..., description="行为类型（L2）")
    severity: SeverityLevel = Field(..., description="适用严重程度（L2）")
    scene: SceneType = Field(..., description="发生场景（L2）")
    immediate_action: str = Field(..., min_length=1, description="即时安全干预动作（L2），四段式第一段")
    comforting_phrase: str = Field(..., min_length=1, description="情绪安抚话术（L2），四段式第二段")
    observation_metrics: str = Field(..., min_length=1, description="后续观察指标（L2），四段式第三段")
    medical_criteria: str = Field(..., min_length=1, description="就医判断标准（L2），四段式第四段")
    evidence_level: EvidenceLevel = Field(..., description="循证等级（L2）")

    # MVP 简化：非核心字段改为 Optional，由 Service 层填充默认值
    narrative: str | None = Field(
        default="",
        description="原始叙事文本（L1），以自然语言撰写的完整干预故事，必须完成 PII 脱敏",
    )
    source_type: SourceType | None = Field(default=None, description="案例来源类型（L1）")
    author_id: str | None = Field(default=None, description="撰写专家标识（L1），后端从 current_user 填充")
    age_range: list[int] | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        description="适用年龄区间（L2），[起始岁, 结束岁]",
    )
    ebp_labels: list[str] | None = Field(
        default=None,
        description="循证实践标签（L2），从 NCAEP EBP 标签中选取至少一项",
    )
    family_category: FamilyDisplayCategory | None = Field(default=None, description="家属端展示大类（L2）")
    contraindications: str | None = Field(default=None, description="禁忌与注意事项（L2），必须具体明确")
    is_template: bool = Field(default=False, description="是否模板（L2），普通录入默认为 false")

    # 选填字段
    excluded_population: str | None = Field(
        default=None, description="不适用人群（L2，选填），明确标注不适宜的患者群体"
    )
    attachment_refs: list[AttachmentRef] | None = Field(default=None, description="附件引用列表（L2，选填）")

    @field_validator("age_range")
    @classmethod
    def age_range_must_be_valid(cls, v: list[int]) -> list[int]:
        """校验 age_range 值在 0-100 范围内且 start <= end。"""
        if len(v) != 2:
            raise ValueError("age_range 必须是包含两个整数的数组 [start, end]")
        start, end = v[0], v[1]
        if start < 0 or start > 100 or end < 0 or end > 100:
            raise ValueError("age_range 的值必须在 0 到 100 之间")
        if start > end:
            raise ValueError("age_range 的起始值不能大于结束值")
        return v

    @field_validator("ebp_labels")
    @classmethod
    def ebp_labels_not_empty(cls, v: list[str]) -> list[str]:
        """校验 ebp_labels 非空。"""
        if not v or len(v) == 0:
            raise ValueError("ebp_labels 至少需要包含一个标签")
        return v


class CaseUpdate(CampfireBaseModel):
    """案例更新请求体（部分更新 + 乐观锁）。

    所有业务字段均为可选（partial update），仅 updated_at 为必填。
    updated_at 用于乐观锁并发控制。

    编辑 pending_review 或 rejected 状态的案例时自动重置状态为 draft。
    """

    title: str | None = Field(default=None, max_length=100, description="案例标题（L1）")
    narrative: str | None = Field(default=None, min_length=100, description="原始叙事文本（L1）")
    source_type: SourceType | None = Field(default=None, description="案例来源类型（L1）")
    behavior_type: BehaviorType | None = Field(default=None, description="行为类型（L2）")
    age_range: list[int] | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        description="适用年龄区间（L2），[起始岁, 结束岁]",
    )
    severity: SeverityLevel | None = Field(default=None, description="适用严重程度（L2）")
    scene: SceneType | None = Field(default=None, description="发生场景（L2）")
    ebp_labels: list[str] | None = Field(default=None, min_length=1, description="循证实践标签（L2）")
    family_category: FamilyDisplayCategory | None = Field(default=None, description="家属端展示大类（L2）")
    immediate_action: str | None = Field(default=None, min_length=1, description="即时安全干预动作（L2）")
    comforting_phrase: str | None = Field(default=None, min_length=1, description="情绪安抚话术（L2）")
    observation_metrics: str | None = Field(default=None, min_length=1, description="后续观察指标（L2）")
    medical_criteria: str | None = Field(default=None, min_length=1, description="就医判断标准（L2）")
    evidence_level: EvidenceLevel | None = Field(default=None, description="循证等级（L2）")
    contraindications: str | None = Field(default=None, min_length=1, description="禁忌与注意事项（L2）")
    is_template: bool | None = Field(default=None, description="是否模板（L2）")
    excluded_population: str | None = Field(default=None, description="不适用人群（L2，选填）")
    attachment_refs: list[AttachmentRef] | None = Field(default=None, description="附件引用列表（L2，选填）")
    updated_at: datetime = Field(..., description="上次读取时的时间戳，用于乐观锁冲突检测")

    @field_validator("age_range")
    @classmethod
    def age_range_must_be_valid(cls, v: list[int] | None) -> list[int] | None:
        """校验 age_range 值在 0-100 范围内且 start <= end。"""
        if v is None:
            return v
        if len(v) != 2:
            raise ValueError("age_range 必须是包含两个整数的数组 [start, end]")
        start, end = v[0], v[1]
        if start < 0 or start > 100 or end < 0 or end > 100:
            raise ValueError("age_range 的值必须在 0 到 100 之间")
        if start > end:
            raise ValueError("age_range 的起始值不能大于结束值")
        return v


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------


class CaseResponse(CampfireBaseModel):
    """案例详情响应体。

    包含全部 L1+L2 字段以及系统字段。
    下游模块通过此接口获取案例全量数据。
    """

    case_id: str = Field(..., description="案例唯一标识，格式 CASE-YYYY-NNNN")
    status: CaseStatus = Field(..., description="案例当前状态")
    title: str = Field(..., description="案例标题")
    narrative: str = Field(..., description="原始叙事文本")
    source_type: str = Field(..., description="案例来源类型")
    author_id: str = Field(..., description="撰写专家标识")
    behavior_type: str = Field(..., description="行为类型")
    age_range: list[int] = Field(..., description="适用年龄区间[起始, 结束]")
    severity: str = Field(..., description="适用严重程度")
    scene: str = Field(..., description="发生场景")
    ebp_labels: list[str] = Field(..., description="循证实践标签列表")
    family_category: str = Field(..., description="家属端展示大类")
    immediate_action: str = Field(..., description="即时安全干预动作")
    comforting_phrase: str = Field(..., description="情绪安抚话术")
    observation_metrics: str = Field(..., description="后续观察指标")
    medical_criteria: str = Field(..., description="就医判断标准")
    evidence_level: str = Field(..., description="循证等级")
    contraindications: str = Field(..., description="禁忌与注意事项")
    is_template: bool = Field(..., description="是否模板")
    excluded_population: str | None = Field(default=None, description="不适用人群")
    attachment_refs: list[AttachmentRef] | None = Field(default=None, description="附件引用列表")
    review_comment: str | None = Field(default=None, description="审核驳回意见，由 CASE-03 填写")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后编辑时间")
    pii_warnings: list[PiiWarning] | None = Field(default=None, description="PII 检测警告列表（仅创建和提交时返回）")
    ebp_inconsistency_warning: str | None = Field(default=None, description="EBP 标签一致性警告（仅提交时返回）")
    is_owner: bool | None = Field(default=None, description="当前用户是否为案例作者")


class CaseListItem(CampfireBaseModel):
    """案例列表条目。

    用于案例管理列表展示，仅包含摘要字段以支持高效列表查询。
    """

    case_id: str = Field(..., description="案例唯一标识")
    title: str = Field(..., description="案例标题")
    status: str = Field(..., description="案例状态")
    source_type: str = Field(..., description="案例来源类型")
    behavior_type: str = Field(..., description="行为类型")
    severity: str = Field(..., description="严重程度")
    scene: str = Field(..., description="发生场景")
    author_id: str = Field(..., description="撰写专家标识")
    is_template: bool = Field(..., description="是否模板")
    evidence_level: str = Field(..., description="循证等级（A/B/C/D）")
    age_range: list[int] = Field(..., description="适用年龄区间 [起始, 结束]")
    citation_count: int = Field(default=0, description="被引用次数")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后编辑时间")


class PaginatedResponse(CampfireBaseModel, Generic[T]):
    """泛型分页响应模型。

    所有列表查询端点统一使用此模型包装分页结果。
    """

    items: list[T] = Field(..., description="当前页数据项列表")
    total: int = Field(..., ge=0, description="总记录数")
    page: int = Field(..., ge=1, description="当前页码（从 1 开始）")
    page_size: int = Field(..., ge=1, description="每页条数")
    total_pages: int = Field(..., ge=0, description="总页数")


# ---------------------------------------------------------------------------
# CASE-03 案例审核工作流 — 审核相关模型
# ---------------------------------------------------------------------------


class ReviewAuditAction(StrEnum):
    """审核审计动作类型枚举。

    记录审核流程中所有可审计的操作类型。
    持久化到 review_audit_logs 表的 action 列。
    """

    SUBMITTED = "submitted"
    AI_REVIEW_COMPLETED = "ai_review_completed"
    AI_REVIEW_HARD_BLOCKED = "ai_review_hard_blocked"
    EXPERT_REVIEW_STARTED = "expert_review_started"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT_REMINDED = "timeout_reminded"
    TIMEOUT_REASSIGNED = "timeout_reassigned"
    EXPERT_OVERRIDE = "expert_override"
    EXPERT_OVERRIDE_PII_BLOCKED = "expert_override_pii_blocked"


class ReviewRequest(CampfireBaseModel):
    """专家终审裁决请求体。

    约束：
    - decision=rejected 时 review_comment 不可为空，>=10 字
    - decision=approved 时 AI 预审硬门槛不通过 => pii_override_confirmed=false 则拒绝
    - PII 零容忍：pii_override_confirmed=true 也会被拒绝（PII 硬门槛不可覆盖）
    """

    decision: Literal["approved", "rejected"] = Field(..., description="专家裁决（approved/rejected）")
    review_comment: str | None = Field(
        default=None,
        description="审核意见（驳回时必填，>=10 字，逐项列出修改建议）",
    )
    override_reason: str | None = Field(
        default=None,
        description="覆盖 AI 预审理由（覆盖时必填）",
    )
    pii_override_confirmed: StrictBool = Field(
        default=False,
        description="是否确认覆盖 PII 硬门槛（默认 false，设为 true 也会被拒绝——PII 零容忍）",
    )


class CheckItem(CampfireBaseModel):
    """单条 AI 预审检查结果。

    每条检查包含状态（通过/不通过/标注）、详情说明和是否硬门槛。
    硬门槛检查不通过时将整体标记为 hard_block，不可进入专家终审。
    """

    status: Literal["pass", "fail", "annotated"] = Field(
        ..., description="检查状态：pass=通过 / fail=不通过 / annotated=标注"
    )
    details: list[str] | None = Field(default=None, description="具体不合格项或标注说明")
    is_hard_gate: bool = Field(..., description="true=硬门槛（拦截），false=软检查（仅标注）")


class AiReviewSummary(CampfireBaseModel):
    """AI 预审结果摘要。

    包含 4 项规则引擎检查结果和 overall 总体结论。
    overall 由各单项的 is_hard_gate 状态推导：
    - 任一硬门槛 fail → hard_block
    - 无硬门槛 fail 但有软检查 fail/annotated → annotated
    - 全部 pass → pass
    """

    format_check: CheckItem = Field(..., description="格式完整性检查（硬门槛）")
    pii_check: CheckItem = Field(..., description="PII 脱敏检查（硬门槛）")
    required_fields_check: CheckItem = Field(..., description="必填字段存在性检查（软检查）")
    ebp_consistency_check: CheckItem = Field(..., description="EBP 一致性检查（软检查）")
    overall: Literal["pass", "hard_block", "annotated"] = Field(..., description="总体结论")


class CaseReviewResponse(CampfireBaseModel):
    """审核裁决响应。

    包含案例最终状态、AI 预审摘要、专家裁决和审核人信息。
    """

    case_id: str = Field(..., description="案例唯一标识")
    new_status: Literal["approved", "rejected"] = Field(..., description="审核后的案例状态")
    ai_review_summary: AiReviewSummary = Field(..., description="AI 预审结果摘要")
    expert_decision: str = Field(..., description="专家裁决描述")
    review_comment: str | None = Field(default=None, description="审核意见")
    reviewer_id: str = Field(..., description="审核人标识")
    reviewed_at: datetime = Field(..., description="审核完成时间")


class ReviewQueueItem(CampfireBaseModel):
    """待审核队列条目。

    用于前端审核列表展示，包含案例摘要信息和审核队列特有字段。
    """

    narrative_id: str = Field(..., description="叙事唯一标识（UUID）")
    title: str = Field(..., description="案例标题")
    author_id: str | None = Field(default=None, description="提交者标识（用于前端判断自审）")
    author_name: str = Field(..., description="提交者名称")
    behavior_type: str = Field(default="", description="行为类型（L2 提取后填充）")
    submitted_at: datetime = Field(..., description="提交审核时间")
    ai_review_overall: str = Field(..., description="AI 预审总体结论")
    deadline: datetime = Field(..., description="审核截止时间（AI 预审完成 + 2 工作日）")
    timeout_status: Literal["normal", "warning", "overdue"] = Field(..., description="超时状态")


__all__ = [
    "AttachmentRef",
    "CaseCreateRequest",
    "CaseUpdate",
    "CaseResponse",
    "CaseListItem",
    "PiiWarning",
    "PiiDetectionResult",
    "PaginatedResponse",
    "NCAEP_EBP_LABELS",
    "ReviewAuditAction",
    "ReviewRequest",
    "CheckItem",
    "AiReviewSummary",
    "CaseReviewResponse",
    "ReviewQueueItem",
]
