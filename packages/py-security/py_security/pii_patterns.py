"""PII 正则模式常量定义。

模块: py_security.pii_patterns
职责: 维护 PII 正则匹配模式字典。所有模式集中管理，
      供 BasePiiDetector 的实现类复用。
数据来源:
  - 无外部数据来源（静态正则模式）
边界:
  - 依赖: py_security.types.PiiType（枚举定义）
  - 被依赖: pii_detector.py（RegexPiiDetector 实现）、未来的 NLP 检测器实现
禁止行为:
  - 禁止在模式字典中包含业务逻辑或检测流程
  - 禁止在公开接口中裸用 dict 替代 PII_PATTERNS 的类型声明
设计取舍:
  - 正则方案精度有限，存在误报（普通词汇被识别为姓名）。
    这是已知设计取舍——宁可误报提示用户检查，不能漏报。
    SEC-03 落地后建议替换为 NLP 实体识别方案。
"""

from __future__ import annotations

from py_security.types import PiiType

# ---------------------------------------------------------------------------
# PII 正则模式
# ---------------------------------------------------------------------------
# 每个模式包含：
# - key: PiiType 枚举成员
# - value: 用于 re.compile 的正则字符串
#
# 模式说明：
# - REAL_NAME: 2-4 个中文字符，精度有限，是已知设计取舍
# - PHONE: 1[3-9] + 9 位数字，标准中国大陆手机号格式
# - ID_CARD: 18 位公民身份证号码，含出生日期校验位
# - HOME_ADDRESS: 省市/区县/街道/门牌号等关键词匹配
# - SCHOOL_NAME: 以"学校/中学/小学/幼儿园/学院/大学"结尾的机构名称

PII_PATTERNS: dict[PiiType, str] = {
    PiiType.REAL_NAME: r"[一-龥]{2,4}",
    PiiType.PHONE: r"1[3-9]\d{9}",
    PiiType.ID_CARD: r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b",
    PiiType.HOME_ADDRESS: r"(?:省|市|区|县|镇|乡|村|路|街|巷|号|栋|单元|室|号楼|层)",
    PiiType.SCHOOL_NAME: r"[一-龥]{2,20}(?:学校|中学|小学|幼儿园|学院|大学)",
}


__all__ = [
    "PII_PATTERNS",
]
