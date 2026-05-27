"""PII 检测核心模块。

提供 detect_pii() 函数，对输入文本执行 5 类 PII 正则匹配检测。
检测结果以 PiiDetectionResult 结构返回，包含是否发现 PII 和警告列表。

设计原则：
- 纯函数，无副作用，无外部依赖
- 检测为辅助提示功能，不强制阻断
- 正则模式集中维护在 pii_patterns.py 中
"""

from __future__ import annotations

import re
from typing import Any

from py_security.pii_patterns import PII_PATTERNS, PiiType


class PiiWarning:
    """PII 单条警告信息。

    Attributes:
        pii_type: PII 类型（枚举值字符串）。
        detected_text: 检测到的疑似 PII 文本片段。
        position_start: 在文本中的起始位置。
        position_end: 在文本中的结束位置。
    """

    def __init__(
        self,
        pii_type: str,
        detected_text: str,
        position_start: int,
        position_end: int,
    ) -> None:
        self.pii_type: str = pii_type
        self.detected_text: str = detected_text
        self.position_start: int = position_start
        self.position_end: int = position_end

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，用于 JSON 序列化。"""
        return {
            "pii_type": self.pii_type,
            "detected_text": self.detected_text,
            "position_start": self.position_start,
            "position_end": self.position_end,
        }


class PiiDetectionResult:
    """PII 检测完整结果。

    Attributes:
        has_pii: 是否检测到疑似 PII。
        warnings: PII 警告列表。
    """

    def __init__(self, has_pii: bool, warnings: list[PiiWarning]) -> None:
        self.has_pii: bool = has_pii
        self.warnings: list[PiiWarning] = warnings

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，用于 JSON 序列化。"""
        return {
            "has_pii": self.has_pii,
            "warnings": [w.to_dict() for w in self.warnings],
        }


def detect_pii(text: str) -> PiiDetectionResult:
    """对输入文本执行 PII 正则匹配检测。

    遍历 5 类 PII 模式（真实姓名、手机号码、身份证号、家庭住址、学校名称），
    收集所有匹配项生成警告列表。

    Args:
        text: 待检测的原始文本（通常是叙事文本 narrative）。

    Returns:
        PiiDetectionResult: 检测结果，包含 has_pii 布尔值和 warnings 列表。
            has_pii 为 True 时 warnings 列表非空。
    """
    # 输入类型守卫：非 str 输入返回空结果
    if not isinstance(text, str):
        return PiiDetectionResult(has_pii=False, warnings=[])

    if not text or not text.strip():
        return PiiDetectionResult(has_pii=False, warnings=[])

    warnings: list[PiiWarning] = []

    for pii_type, pattern_str in PII_PATTERNS.items():
        try:
            pattern: re.Pattern[str] = re.compile(pattern_str)
            for match in pattern.finditer(text):
                matched_text: str = match.group()
                # 跳过空匹配
                if not matched_text.strip():
                    continue

                warning = PiiWarning(
                    pii_type=pii_type.value,
                    detected_text=matched_text.strip(),
                    position_start=match.start(),
                    position_end=match.end(),
                )
                warnings.append(warning)
        except re.error:
            # 正则编译失败时跳过该模式（不应发生在预定义模式中）
            continue

    return PiiDetectionResult(
        has_pii=len(warnings) > 0,
        warnings=warnings,
    )


__all__ = [
    "detect_pii",
    "PiiWarning",
    "PiiDetectionResult",
]
