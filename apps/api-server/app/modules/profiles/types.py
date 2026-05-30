# @contract
"""profiles 域语义类型定义。

模块: app.modules.profiles.types
职责: 定义档案域（PROF-01/03/05）的 NewType 语义类型包装，
      防止 UUID/str 原始类型在方法签名间无差别传递导致的语义混淆。

使用方式:
    from app.modules.profiles.types import ProfileId, CaregiverId
    profile_id = ProfileId(uuid_str)

注意: NewType 在运行时无开销——仅静态检查时生效。
"""

from __future__ import annotations

from uuid import UUID

from typing import NewType

# PROF-01 档案标识
ProfileId = NewType("ProfileId", UUID)
r"""档案唯一标识（UUID v4）。"""

CaregiverId = NewType("CaregiverId", UUID)
r"""家属用户唯一标识（UUID v4）。"""

# PROF-03 事件标识
EventId = NewType("EventId", UUID)
r"""事件记录唯一标识（UUID v4）。"""

# PROF-05 关联标识
LinkId = NewType("LinkId", UUID)
r"""专家关联记录唯一标识（UUID v4）。"""


__all__ = [
    "ProfileId",
    "CaregiverId",
    "EventId",
    "LinkId",
]
