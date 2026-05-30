"""CSLT-01 危机分级判定 — JudgmentLayer 判定层接口（兼容性重导出）。

JudgmentLayer 的正式定义位于 crisis_contract.py。
本文件保留用于向后兼容 —— 已有代码可能 via layer import JudgmentLayer。
"""

from __future__ import annotations

from .crisis_contract import JudgmentLayer

__all__ = ["JudgmentLayer"]
