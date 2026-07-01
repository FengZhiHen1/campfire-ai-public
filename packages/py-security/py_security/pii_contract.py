"""py-security PII 检测行为契约 — ABC 模板方法。

模块: py_security.pii_contract
职责: 定义 PII 检测器的契约骨架。调用者走 @final 公共入口，
      实现者只能覆写 _do_ 前缀的钩子。
数据来源:
  - PII_PATTERNS (py_security.pii_patterns): MUST — PII 正则模式字典
边界:
  - 依赖: py_security.types（语义类型）、py_security.exceptions（异常层次）
  - 被依赖: api-server 的 PII 检测中间件、CASE-03 案例审核的脱敏检测
禁止行为:
  - 禁止在契约文件中包含具体检测逻辑实现
  - 禁止在 @final 方法之外提供公共入口
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from py_logger import StructuredLogger

from py_security.exceptions import PiiDetectionError, PiiInputValidationError
from py_security.types import PiiDetectionResult


def _get_logger() -> StructuredLogger:
    from py_logger import logger

    return logger


class BasePiiDetector(ABC):
    """PII 检测器行为契约。

    模板方法: detect(text) → @final 公共入口
              ├── _validate_input(text)        前置校验
              ├── _do_detect(text)             实现者钩子（唯一覆写点）
              └── _validate_result(text, result)  后置校验

    实现者只能覆写 _do_ 前缀的钩子方法。
    调用者只能使用 @final 标注的公共入口。
    """

    # === @final 公共入口：外部唯一调用点 ===

    @final
    def detect(self, text: str) -> PiiDetectionResult:
        """
        前置校验 → 调用钩子 → 后置校验。

        前置: text 必须是 str 类型（非 None）
        后置: 返回的 PiiDetectionResult.has_pii 与 warnings 长度一致
        后置: 每个 warning 的 position_start/position_end 在 text 范围内
        异常: PiiInputValidationError — 输入校验失败
        异常: PiiPatternCompileError — 正则模式编译失败（取决于实现）
        """
        self._validate_input(text)
        result = self._do_detect(text)
        self._validate_result(text, result)

        if result.has_pii:
            types_found = list({w.pii_type.value for w in result.warnings})
            _get_logger().warning(
                "py-security",
                f"检测到 {len(result.warnings)} 处疑似 PII",
                op_type="pii_detect",
                extra={
                    "pii_count": len(result.warnings),
                    "pii_types": types_found,
                    "text_length": len(text),
                },
            )

        return result

    # === @abstractmethod 钩子：实现者必填 ===

    @abstractmethod
    def _do_detect(self, text: str) -> PiiDetectionResult:
        """
        执行实际的 PII 检测逻辑。

        前置: _validate_input 已通过（由 detect 保证）
        前置: text 是经过输入校验的非空字符串
        后置: 返回的 PiiDetectionResult 满足契约约束
        实现者在此方法中编写具体检测策略（正则匹配 / NLP 实体识别 / 混合方案）。
        """
        ...

    # === 校验器：模板提供基线校验 ===

    def _validate_input(self, text: str) -> None:
        """
        基线输入校验。子类可通过 super() 叠加业务级校验。

        前置: 无
        后置: text 通过类型和非空校验
        异常: PiiInputValidationError — text 为 None 或非字符串类型
        """
        if not isinstance(text, str):
            raise PiiInputValidationError(f"text 必须是 str 类型，实际类型: {type(text).__name__}")
        if not text or not text.strip():
            raise PiiInputValidationError("text 不能为空或仅含空白字符")

    def _validate_result(self, text: str, result: PiiDetectionResult) -> None:
        """
        基线后置校验。子类可通过 super() 叠加业务级校验。

        前置: text 是原始输入文本，result 是检测结果
        后置: has_pii 与 warnings 长度逻辑一致
        后置: 每个 warning 的 position 在 text 有效范围内
        异常: PiiDetectionError — 后置校验失败
        """
        text_len = len(text)
        has_warnings = len(result.warnings) > 0
        if result.has_pii != has_warnings:
            raise PiiDetectionError(f"has_pii={result.has_pii} 与 warnings 数量({len(result.warnings)})不一致")
        for i, w in enumerate(result.warnings):
            if w.position_start < 0:
                raise PiiDetectionError(f"warning[{i}] position_start={w.position_start} < 0")
            if w.position_end > text_len:
                raise PiiDetectionError(f"warning[{i}] position_end={w.position_end} 超出文本长度 {text_len}")
            if w.position_start >= w.position_end:
                raise PiiDetectionError(
                    f"warning[{i}] position_start({w.position_start}) >= position_end({w.position_end})"
                )


__all__ = [
    "BasePiiDetector",
]
