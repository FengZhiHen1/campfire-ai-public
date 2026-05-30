"""profiles 域常量定义。

模块: app.modules.profiles._constants
职责: 集中管理档案域所有魔法值——档案上限、追溯天数、预设标签、记录人角色等。
      避免在 routes / services 中硬编码字符串和数字。
"""

from __future__ import annotations

# PROF-01: 档案数量上限（可被 py-config 的 AppSettings 覆盖）
MAX_PROFILES_PER_USER: int = 5

# PROF-03: 事件补录追溯期（天）
EVENT_RETROSPECTIVE_DAYS: int = 30

# PROF-03: 事件记录人默认角色
DEFAULT_RECORDED_BY_ROLE: str = "parent"

# PROF-03: 预设标签池
PRESET_TAGS: list[str] = [
    "感官敏感",
    "睡眠障碍",
    "社交回避",
    "情绪调节困难",
    "语言发育迟缓",
    "注意缺陷",
    "刻板行为",
    "饮食问题",
    "攻击行为",
    "自伤行为",
]

# 标签规格
MAX_TAGS_PER_EVENT: int = 5
MAX_TAG_LENGTH: int = 10

__all__ = [
    "MAX_PROFILES_PER_USER",
    "EVENT_RETROSPECTIVE_DAYS",
    "DEFAULT_RECORDED_BY_ROLE",
    "PRESET_TAGS",
    "MAX_TAGS_PER_EVENT",
    "MAX_TAG_LENGTH",
]
