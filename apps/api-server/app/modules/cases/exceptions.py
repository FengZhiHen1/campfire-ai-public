# @contract
"""cases 模块异常层次 — 统一错误类型定义。

所有 cases 域异常继承自 CasesError 基类，上层可通过 `except CasesError`
统一捕获本模块的所有错误。每个异常携带诊断字段，供调用方做程序化处理。
"""

from __future__ import annotations

# ============================================================================
# 基类
# ============================================================================


class CasesError(Exception):
    """cases 模块异常基类。所有案例域异常统一继承自此。"""


# ============================================================================
# 案例管理异常 (CASE-01)
# ============================================================================


class CaseNotFoundError(CasesError):
    """案例不存在。

    触发条件: 通过 case_id 查询案例时数据库中无匹配记录。
    诊断字段:
      - case_id: 查询的案例标识
    """

    def __init__(self, case_id: str) -> None:
        self.case_id = case_id
        super().__init__(f"案例 {case_id} 不存在")


class CaseStatusError(CasesError):
    """案例状态不合法。

    触发条件: 操作要求的状态与案例当前状态不匹配（如对非 draft 案例执行 submit）。
    诊断字段:
      - case_id: 案例标识
      - current_status: 案例当前状态
      - expected_status: 操作要求的状态
    """

    def __init__(self, case_id: str, current_status: str, expected_status: str) -> None:
        self.case_id = case_id
        self.current_status = current_status
        self.expected_status = expected_status
        super().__init__(
            f"案例 {case_id} 当前状态为 {current_status}，需要 {expected_status}"
        )


class OptimisticLockError(CasesError):
    """乐观锁冲突。

    触发条件: 更新案例时传入的 updated_at 与数据库当前值不一致。
    诊断字段:
      - case_id: 案例标识
      - expected_ts: 客户端传入的时间戳
      - actual_ts: 数据库中的当前时间戳
    """

    def __init__(self, case_id: str, expected_ts: str, actual_ts: str) -> None:
        self.case_id = case_id
        self.expected_ts = expected_ts
        self.actual_ts = actual_ts
        super().__init__(
            f"编辑冲突：案例 {case_id} 已被其他用户修改。请刷新后重试。"
        )


class FourStageValidationError(CasesError):
    """四段式字段不完整。

    触发条件: 提交时 immediate_action、comforting_phrase、observation_metrics、
             medical_criteria 任一为空。
    诊断字段:
      - missing_fields: 缺失的字段名列表
    """

    def __init__(self, missing_fields: list[str]) -> None:
        self.missing_fields = missing_fields
        fields_str = "、".join(missing_fields)
        super().__init__(f"四段式字段不完整，缺失：{fields_str}")


# ============================================================================
# 审核工作流异常 (CASE-03)
# ============================================================================


class ReviewError(CasesError):
    """审核工作流异常基类。"""


class SelfReviewForbiddenError(ReviewError):
    """禁止自审。

    触发条件: 审核人 ID 与案例作者 ID 相同。
    诊断字段:
      - case_id: 案例标识
      - reviewer_id: 审核人 ID
      - author_id: 案例作者 ID
    """

    def __init__(self, case_id: str, reviewer_id: str, author_id: str) -> None:
        self.case_id = case_id
        self.reviewer_id = reviewer_id
        self.author_id = author_id
        super().__init__(f"不得审核自己提交的案例 {case_id}")


class PiiHardBlockError(ReviewError):
    """PII 硬门槛拦截。

    触发条件: AI 预审 PII 检测为 fail 且 is_hard_gate=True。
    诊断字段:
      - case_id: 案例标识
      - pii_details: PII 检测详情列表
    """

    def __init__(self, case_id: str, pii_details: list[str]) -> None:
        self.case_id = case_id
        self.pii_details = pii_details
        super().__init__(
            f"案例 {case_id} 未通过 PII 脱敏检查（硬门槛），"
            "请提交者完成脱敏后重新提交。"
        )


class RejectCommentTooShortError(ReviewError):
    """驳回意见长度不足。

    触发条件: 驳回决定时 review_comment 字数少于 10。
    诊断字段:
      - current_length: 当前驳回意见字数
      - min_length: 最小字数要求
    """

    def __init__(self, current_length: int, min_length: int) -> None:
        self.current_length = current_length
        self.min_length = min_length
        super().__init__(
            f"驳回意见至少需要 {min_length} 个字，当前 {current_length} 字"
        )


# ============================================================================
# 叙事管理异常
# ============================================================================


class NarrativeError(CasesError):
    """叙事管理异常基类。"""


class NarrativeNotFoundError(NarrativeError):
    """叙事不存在。

    触发条件: 通过 narrative_id 查询叙事时数据库中无匹配记录。
    诊断字段:
      - narrative_id: 查询的叙事标识
    """

    def __init__(self, narrative_id: str) -> None:
        self.narrative_id = narrative_id
        super().__init__(f"叙事 {narrative_id} 不存在")


class CardNotFoundError(NarrativeError):
    """L2 卡片不存在。

    触发条件: 通过 card_id 查询卡片时数据库中无匹配记录。
    诊断字段:
      - card_id: 查询的卡片标识
    """

    def __init__(self, card_id: str) -> None:
        self.card_id = card_id
        super().__init__(f"卡片 {card_id} 不存在")


# ============================================================================
# 提取异常
# ============================================================================


class ExtractionError(CasesError):
    """LLM 提取失败。

    触发条件: LLM 调用失败、JSON 解析失败或卡片校验不通过。
    诊断字段:
      - reason: 失败原因简述
      - raw_output: 出问题时 LLM 返回的原始文本（JSON 解析失败等场景用于排错）
    """

    def __init__(self, reason: str, raw_output: str | None = None) -> None:
        self.reason = reason
        self.raw_output = raw_output
        super().__init__(f"LLM 提取失败: {reason}")
