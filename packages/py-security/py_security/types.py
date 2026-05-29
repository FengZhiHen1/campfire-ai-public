"""py-security 语法契约 — 语义类型与数据结构定义。

模块: py_security.types
职责: 定义 py-security 包所有公开接口使用的语义类型（NewType）、枚举与数据模型。
      每个语义概念只在此处定义一次，禁止裸用原始类型。
数据来源:
  - 无外部数据来源（纯类型定义层）
边界:
  - 依赖: Python 标准库 typing、dataclasses、enum
  - 被依赖: pii_contract.py（ABC 基类的输入输出类型）、pii_detector.py（实现类）、pii_patterns.py（模式字典）
禁止行为:
  - 禁止在类型定义文件中包含任何业务逻辑或 IO 操作
  - 禁止在公开接口中裸用 str/int/list 等原始类型替代此处的语义类型
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, NewType

# ---------------------------------------------------------------------------
# PII 类型枚举
# ---------------------------------------------------------------------------


class PiiType(str, Enum):
    """PII 类型枚举。

    定义需要检测的个人身份信息类别。使用 str 混入以支持
    直接序列化为中文标签，无需额外的 value→label 映射。
    """

    REAL_NAME = "真实姓名"
    """中文姓名：2-4 个中文字符"""
    PHONE = "手机号码"
    """中国大陆手机号码：1[3-9] + 9 位数字"""
    ID_CARD = "身份证号"
    """中国大陆 18 位身份证号码"""
    HOME_ADDRESS = "家庭住址"
    """含省市/区县/街道/门牌号等关键词的地址片段"""
    SCHOOL_NAME = "学校名称"
    """学校/中学/小学/幼儿园/学院/大学名称"""


# ---------------------------------------------------------------------------
# 语义类型（NewType）
# ---------------------------------------------------------------------------

DetectedText = NewType("DetectedText", str)
"""检测到的疑似 PII 文本片段。与普通 str 在类型层面区分，防止混用。"""

PositionIndex = NewType("PositionIndex", int)
"""文本位置索引。确保位置值在类型检查期不与普通整数混淆。"""


# ---------------------------------------------------------------------------
# 数据模型（frozen dataclass — 契约数据不可变）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PiiWarning:
    """PII 单条警告信息。

    前置: pii_type 必须是 PiiType 枚举成员
    前置: detected_text 必须是非空字符串
    前置: position_start >= 0
    前置: position_end > position_start
    后置: 所有字段不可变（frozen=True）
    """

    pii_type: PiiType
    """PII 类型"""
    detected_text: DetectedText
    """检测到的疑似 PII 文本片段"""
    position_start: PositionIndex
    """在原始文本中的起始位置"""
    position_end: PositionIndex
    """在原始文本中的结束位置"""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，用于 JSON 序列化。"""
        return {
            "pii_type": self.pii_type.value,
            "detected_text": self.detected_text,
            "position_start": self.position_start,
            "position_end": self.position_end,
        }


@dataclass(frozen=True)
class PiiDetectionResult:
    """PII 检测完整结果。

    前置: has_pii 为 True 时 warnings 必须非空
    前置: has_pii 为 False 时 warnings 必须为空列表
    后置: 结果不可变（frozen=True）
    后置: has_pii == (len(warnings) > 0)
    """

    has_pii: bool
    """是否检测到疑似 PII"""
    warnings: tuple[PiiWarning, ...] = field(default_factory=tuple)
    """PII 警告列表（不可变元组）"""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，用于 JSON 序列化。"""
        return {
            "has_pii": self.has_pii,
            "warnings": [w.to_dict() for w in self.warnings],
        }


__all__ = [
    "PiiType",
    "DetectedText",
    "PositionIndex",
    "PiiWarning",
    "PiiDetectionResult",
]
