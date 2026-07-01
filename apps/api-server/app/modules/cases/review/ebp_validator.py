# @contract
"""CASE-01 EBP 标签一致性校验。

校验循证等级（evidence_level）与循证标签列表（ebp_labels）之间的一致性。
NCAEP 标准标签集定义于 py_schemas.cases.NCAEP_EBP_LABELS。

校验规则：
1. evidence_level="NCAEP循证实践" 且 ebp_labels 含非 NCAEP 标签 → 警告
2. evidence_level 不是 "NCAEP循证实践" 且 ebp_labels 含 NCAEP 标签 → 警告
"""

from __future__ import annotations

from typing import List, Optional

from py_schemas.cases import NCAEP_EBP_LABELS


def check_ebp_consistency(
    evidence_level: str,
    ebp_labels: List[str],
) -> Optional[str]:
    """检查循证等级与循证标签列表之间的一致性。

    当 evidence_level="NCAEP循证实践" 但 ebp_labels 中包含
    非 NCAEP 标准标签时，返回包含非标准标签的警告信息。

    当 evidence_level 不是 "NCAEP循证实践" 但 ebp_labels 中包含
    NCAEP 标准标签时，返回提示信息。

    Args:
        evidence_level: 循证等级（如 "NCAEP循证实践"、"机构经验总结"）。
        ebp_labels: 循证实践标签列表。

    Returns:
        一致性警告字符串（无问题时返回 None）。

    Examples:
        >>> check_ebp_consistency("NCAEP循证实践", ["视觉支持", "非标准标签"])
        '以下标签不在 NCAEP 循证实践列表中：非标准标签'

        >>> check_ebp_consistency("机构经验总结", ["视觉支持", "强化"])
        'evidence_level 为"机构经验总结"但标签列表中包含 NCAEP 循证实践标签'
    """
    # 输入类型守卫：ebp_labels 非 list 时返回 None
    if not isinstance(ebp_labels, list):
        return None

    if not evidence_level or not ebp_labels:
        return None

    ebp_set: set[str] = set(ebp_labels)

    if evidence_level == "NCAEP循证实践":
        # 检查是否有非 NCAEP 标签
        non_ncaep: set[str] = ebp_set - NCAEP_EBP_LABELS
        if non_ncaep:
            non_ncaep_list: str = "、".join(sorted(non_ncaep))
            return f"以下标签不在 NCAEP 循证实践列表中：{non_ncaep_list}"
    else:
        # evidence_level 不是 NCAEP，检查是否包含 NCAEP 标签
        ncaep_found: set[str] = ebp_set & NCAEP_EBP_LABELS
        if ncaep_found:
            ncaep_list: str = "、".join(sorted(ncaep_found))
            return f'evidence_level 为"{evidence_level}"但标签列表中包含 NCAEP 循证实践标签：{ncaep_list}'

    return None


__all__ = ["check_ebp_consistency"]
