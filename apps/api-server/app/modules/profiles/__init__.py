"""app.modules.profiles — 个性化档案库模块（ADR-010 四层结构）。

四层：身份基础 / 危机预案 / 事件时间线（ABC）/ 专业评估。
访问控制：家属主控 + ProfileAccess 受邀协作（guard.py 数据级授权）。
"""

from app.modules.profiles.access_service import AccessService, NoteService
from app.modules.profiles.event_service import EventService
from app.modules.profiles.guard import ProfileAccessContext, require_profile_access
from app.modules.profiles.profile_service import ProfileService
from app.modules.profiles.routes import router as profiles_router
from app.modules.profiles.slot_source import ProfileSnapshotProviderImpl

__all__ = [
    "ProfileService",
    "EventService",
    "NoteService",
    "AccessService",
    "ProfileAccessContext",
    "require_profile_access",
    "ProfileSnapshotProviderImpl",
    "profiles_router",
]
