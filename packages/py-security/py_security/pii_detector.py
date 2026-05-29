"""PII 检测 — RegexPiiDetector 实现（正则匹配策略）。

模块: py_security.pii_detector
职责: 基于正则表达式实现 BasePiiDetector 契约。
      遍历 PII_PATTERNS 中的 5 类中文 PII 模式，
      对输入文本执行正则匹配并生成 PiiWarning 列表。
数据来源:
  - PII_PATTERNS (py_security.pii_patterns): MUST — PII 正则模式字典
边界:
  - 依赖: py_security.types、py_security.pii_contract、py_security.pii_patterns
  - 被依赖: 通过 BasePiiDetector 契约调用（api-server 中间件等）
禁止行为:
  - 禁止覆盖 @final detect() 方法
  - 禁止跳过 _validate_* 校验器
设计取舍:
  - 正则方案精度有限，存在误报。这是已知设计取舍——宁可误报提示用户检查，不能漏报。
  - 这是临时实现。SEC-03 落地后应替换为 NLP 实体识别方案（继承同一 BasePiiDetector 契约）。
"""

from __future__ import annotations

import re

from py_security.exceptions import PiiPatternCompileError
from py_security.pii_contract import BasePiiDetector
from py_security.pii_patterns import PII_PATTERNS
from py_security.types import (
    DetectedText,
    PiiDetectionResult,
    PiiType,
    PiiWarning,
    PositionIndex,
)


class RegexPiiDetector(BasePiiDetector):
    """基于正则表达式的 PII 检测器实现。

    实现 BasePiiDetector 契约，使用 PII_PATTERNS 中预定义的
    5 类中文 PII 正则模式进行匹配。
    """

    def _do_detect(self, text: str) -> PiiDetectionResult:
        """遍历 PII_PATTERNS 执行正则匹配，收集所有匹配项。

        前置: text 是经过 _validate_input 校验的非空 str
        后置: 返回的 PiiDetectionResult.has_pii 与 warnings 非空一致
        异常: PiiPatternCompileError — 正则模式编译失败时向上传播
        """
        warnings: list[PiiWarning] = []

        for pii_type, pattern_str in PII_PATTERNS.items():
            try:
                pattern: re.Pattern[str] = re.compile(pattern_str)
            except re.error as exc:
                raise PiiPatternCompileError(pattern_str, str(exc)) from exc

            for match in pattern.finditer(text):
                matched_text = match.group()
                if not matched_text.strip():
                    continue

                warning = PiiWarning(
                    pii_type=pii_type,
                    detected_text=DetectedText(matched_text.strip()),
                    position_start=PositionIndex(match.start()),
                    position_end=PositionIndex(match.end()),
                )
                warnings.append(warning)

        return PiiDetectionResult(
            has_pii=len(warnings) > 0,
            warnings=tuple(warnings),
        )


__all__ = [
    "RegexPiiDetector",
]
