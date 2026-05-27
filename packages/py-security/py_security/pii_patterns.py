"""PII 正则模式常量定义。

维护 5 类中文 PII 的正则匹配模式。所有模式集中管理，
供 pii_detector.py 和可能的其他模块复用。

PII 类型枚举 + 模式字典，便于扩展新类型。
"""

from __future__ import annotations

from enum import Enum


class PiiType(str, Enum):
    """PII 类型枚举。

    定义 5 类需要检测的中文 PII 类型。
    """

    REAL_NAME = "真实姓名"
    PHONE = "手机号码"
    ID_CARD = "身份证号"
    HOME_ADDRESS = "家庭住址"
    SCHOOL_NAME = "学校名称"


# ---------------------------------------------------------------------------
# PII 正则模式
# ---------------------------------------------------------------------------
# 每个模式包含：
# - pattern: 用于 re.compile 的正则字符串
# - description: 类型描述

PII_PATTERNS: dict[PiiType, str] = {
    # 中文姓名：2-4 个中文字符
    # 注意：正则方案精度有限，存在误报（普通词汇被识别为姓名）。
    # 这是已知设计取舍——宁可误报提示用户检查，不能漏报。
    # SEC-03 落地后建议替换为 NLP 实体识别方案。
    PiiType.REAL_NAME: r"[一-龥]{2,4}",
    # 中国大陆手机号码：1[3-9] 开头 + 9 位数字
    PiiType.PHONE: r"1[3-9]\d{9}",
    # 中国大陆身份证号：18 位（17 位数字 + 数字或 X）
    PiiType.ID_CARD: r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b",
    # 家庭住址：省市开头 + 详细地址
    PiiType.HOME_ADDRESS: r"(?:省|市|区|县|镇|乡|村|路|街|巷|号|栋|单元|室|号楼|层)",
    # 学校名称：……学校/中学/小学/幼儿园
    PiiType.SCHOOL_NAME: r"[一-龥]{2,20}(?:学校|中学|小学|幼儿园|学院|大学)",
}


__all__ = [
    "PiiType",
    "PII_PATTERNS",
]
