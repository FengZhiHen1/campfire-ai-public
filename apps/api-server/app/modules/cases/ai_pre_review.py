# @contract
"""CASE-03 案例审核工作流 — AI 预审规则引擎。

对提交审核的案例执行 4 项确定性规则检查：
1. 格式完整性检查（四段式字段非空）— 硬门槛
2. PII 脱敏检查（复用 pii_detector） — 硬门槛
3. 必填字段存在性检查（17 个必填字段） — 软检查
4. EBP 一致性检查（复用 ebp_validator） — 软检查

所有检查均为规则引擎 + 正则匹配，<5ms 响应，不使用 LLM。
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from py_schemas.cases import AiReviewSummary, CheckItem, NCAEP_EBP_LABELS
from py_security import RegexPiiDetector

_pii_detector = RegexPiiDetector()

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量：必填字段列表
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS: list[str] = [
    "title",
    "narrative",
    "source_type",
    "author_id",
    "behavior_type",
    "age_range_min",
    "age_range_max",
    "severity",
    "scene",
    "ebp_labels",
    "family_category",
    "immediate_action",
    "comforting_phrase",
    "observation_metrics",
    "medical_criteria",
    "evidence_level",
    "contraindications",
]
"""17 个必填字段（与 CASE-01 CaseCreateRequest 字段定义一致）。"""


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _check_format_completeness(case_data: dict[str, Any]) -> CheckItem:
    """格式完整性检查：四段式字段非空。

    检查 immediate_action、comforting_phrase、observation_metrics、
    medical_criteria 四个字段是否全部非空（非 None 且非空字符串）。

    此项为硬门槛检查——四段式字段不完整则 hard_block。

    Args:
        case_data: 案例数据字典（含四段式字段）。

    Returns:
        CheckItem: 检查结果（status + details + is_hard_gate=True）。
    """
    four_stage_fields: list[tuple[str, str]] = [
        ("immediate_action", "即时安全干预动作"),
        ("comforting_phrase", "情绪安抚话术"),
        ("observation_metrics", "后续观察指标"),
        ("medical_criteria", "就医判断标准"),
    ]

    missing: list[str] = []
    for field_name, display_name in four_stage_fields:
        value = case_data.get(field_name)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            missing.append(display_name)

    if missing:
        return CheckItem(
            status="fail",
            details=[f"四段式字段缺失：{'、'.join(missing)}"],
            is_hard_gate=True,
        )

    return CheckItem(
        status="pass",
        is_hard_gate=True,
    )


def _check_pii(case_data: dict[str, Any]) -> CheckItem:
    """PII 脱敏检查：检测叙事文本中的 5 类 PII。

    复用 py_security.pii_detector.detect_pii() 正则匹配检测。
    此项为硬门槛检查——检测到 PII 则 hard_block，不可被专家覆盖。

    Args:
        case_data: 案例数据字典（含 narrative 字段）。

    Returns:
        CheckItem: 检查结果（status + details + is_hard_gate=True）。
    """
    narrative: str = case_data.get("narrative", "") or ""

    if not isinstance(narrative, str) or not narrative.strip():
        return CheckItem(
            status="fail",
            details=["叙事文本为空，无法执行 PII 检测"],
            is_hard_gate=True,
        )

    result = _pii_detector.detect(narrative)

    if result.has_pii:
        pii_types: set[str] = {w.pii_type for w in result.warnings}
        details: list[str] = [
            f"检测到疑似 {', '.join(sorted(pii_types))}，请完成脱敏后重新提交",
        ]
        return CheckItem(
            status="fail",
            details=details,
            is_hard_gate=True,
        )

    return CheckItem(
        status="pass",
        is_hard_gate=True,
    )


def _check_required_fields(case_data: dict[str, Any]) -> CheckItem:
    """必填字段存在性检查：17 个必填字段非空。

    此项为软检查（is_hard_gate=False），仅标注不拦截。
    硬性必填校验已在 CASE-01 Pydantic 层面执行。

    Args:
        case_data: 案例数据字典。

    Returns:
        CheckItem: 检查结果（status + details + is_hard_gate=False）。
    """
    missing: list[str] = []
    for field_name in _REQUIRED_FIELDS:
        value = case_data.get(field_name)
        if value is None:
            missing.append(field_name)
        elif isinstance(value, str) and value.strip() == "":
            missing.append(field_name)
        elif isinstance(value, list) and len(value) == 0:
            missing.append(field_name)

    if missing:
        return CheckItem(
            status="annotated",
            details=[f"必填字段缺失：{'、'.join(missing)}"],
            is_hard_gate=False,
        )

    return CheckItem(
        status="pass",
        is_hard_gate=False,
    )


def _check_ebp_consistency(case_data: dict[str, Any]) -> CheckItem:
    """EBP 一致性检查：循证等级与标签列表一致性。

    规则：
    1. evidence_level="NCAEP循证实践" 且 ebp_labels 含非 NCAEP 标签 → annotated
    2. evidence_level 不是 NCAEP 但 ebp_labels 含 NCAEP 标签 → annotated

    此项为软检查（is_hard_gate=False），仅标注不拦截。

    Args:
        case_data: 案例数据字典（含 evidence_level 和 ebp_labels）。

    Returns:
        CheckItem: 检查结果（status + details + is_hard_gate=False）。
    """
    evidence_level: str = case_data.get("evidence_level", "") or ""
    ebp_labels: list[str] = case_data.get("ebp_labels", []) or []

    if not isinstance(ebp_labels, list):
        ebp_labels = []

    ebp_set: set[str] = set(ebp_labels)

    if evidence_level == "NCAEP循证实践":
        non_ncaep: set[str] = ebp_set - NCAEP_EBP_LABELS
        if non_ncaep:
            return CheckItem(
                status="annotated",
                details=[
                    f"以下标签不在 NCAEP 循证实践列表中：{'、'.join(sorted(non_ncaep))}"
                ],
                is_hard_gate=False,
            )
    else:
        ncaep_found: set[str] = ebp_set & NCAEP_EBP_LABELS
        if ncaep_found:
            return CheckItem(
                status="annotated",
                details=[
                    f"evidence_level 为「{evidence_level}」但标签列表中包含 "
                    f"NCAEP 循证实践标签：{'、'.join(sorted(ncaep_found))}"
                ],
                is_hard_gate=False,
            )

    return CheckItem(
        status="pass",
        is_hard_gate=False,
    )


def _compute_overall(
    format_check: CheckItem,
    pii_check: CheckItem,
    required_fields_check: CheckItem,
    ebp_consistency_check: CheckItem,
) -> str:
    """根据四项检查结果计算 overall 结论。

    推导规则：
    - 任一硬门槛（is_hard_gate=True）状态为 fail → "hard_block"
    - 无硬门槛 fail，但有任何软检查 annotated/fail → "annotated"
    - 全部 pass → "pass"

    Args:
        format_check: 格式完整性检查结果。
        pii_check: PII 脱敏检查结果。
        required_fields_check: 必填字段检查结果。
        ebp_consistency_check: EBP 一致性检查结果。

    Returns:
        "pass"、"hard_block" 或 "annotated"。
    """
    hard_gate_items: list[CheckItem] = [
        c for c in [format_check, pii_check] if c.is_hard_gate
    ]
    soft_items: list[CheckItem] = [
        c for c in [required_fields_check, ebp_consistency_check] if not c.is_hard_gate
    ]

    # 硬门槛检查：任一 fail → hard_block
    for item in hard_gate_items:
        if item.status == "fail":
            return "hard_block"

    # 软检查：任一 annotated 或 fail → annotated
    for item in soft_items:
        if item.status in ("annotated", "fail"):
            return "annotated"

    return "pass"


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


def run_ai_pre_review(case_data: dict[str, Any]) -> AiReviewSummary:
    """对案例执行 AI 预审。

    使用规则引擎执行 4 项确定性检查，所有检查 <5ms，不使用 LLM。

    检查流程：
    1. 格式完整性检查（硬门槛）
    2. PII 脱敏检查（硬门槛）
    3. 必填字段存在性检查（软检查）
    4. EBP 一致性检查（软检查）

    Args:
        case_data: 案例全量数据字典。
            必须包含四段式字段、narrative、evidence_level、ebp_labels 等字段。

    Returns:
        AiReviewSummary: AI 预审结果摘要，含 4 项检查和 overall 结论。
    """
    format_check: CheckItem = _check_format_completeness(case_data)
    pii_check: CheckItem = _check_pii(case_data)
    required_fields_check: CheckItem = _check_required_fields(case_data)
    ebp_consistency_check: CheckItem = _check_ebp_consistency(case_data)

    overall: str = _compute_overall(
        format_check, pii_check, required_fields_check, ebp_consistency_check
    )

    result = AiReviewSummary(
        format_check=format_check,
        pii_check=pii_check,
        required_fields_check=required_fields_check,
        ebp_consistency_check=ebp_consistency_check,
        overall=overall,  # type: ignore[arg-type]
    )

    _logger.info(
        "ai_pre_review_completed",
        extra={
            "overall": overall,
            "format_check": format_check.status,
            "pii_check": pii_check.status,
            "required_fields_check": required_fields_check.status,
            "ebp_consistency_check": ebp_consistency_check.status,
        },
    )

    return result


def case_data_from_orm(case: Any) -> dict[str, Any]:
    """将 Case ORM 实例转换为可用于 AI 预审的字典。

    处理 age_range 拆分字段合并、枚举值提取等 ORM→dict 转换。

    Args:
        case: Case ORM 实例。

    Returns:
        包含预审所需字段的字典。
    """
    data: dict[str, Any] = {}
    for field in _REQUIRED_FIELDS:
        data[field] = getattr(case, field, None)

    # 补充四段式字段（已在 _REQUIRED_FIELDS 中，此处确保覆盖）
    for field in ("immediate_action", "comforting_phrase", "observation_metrics", "medical_criteria"):
        data[field] = getattr(case, field, None)

    return data


__all__ = [
    "run_ai_pre_review",
    "case_data_from_orm",
]
