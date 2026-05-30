"""profiles -- 档案管理：个人档案 CRUD、生活事件记录、专家关联管理。"""
from .profile_service import ProfileService
from .routes import router as profiles_router
from .event_routes import router as events_router
from .expert_routes import router as experts_router

__all__ = [
    "ProfileService",
    "profiles_router",
    "events_router",
    "experts_router",
]
