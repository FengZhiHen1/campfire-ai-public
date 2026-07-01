"""profiles — 档案管理域（PROF-01/03/05）。

模块: app.modules.profiles
职责: 档案管理相关的全部业务能力——个人档案 CRUD、生活事件记录、专家关联管理。
      采用契约驱动架构：ABC 契约基类定义业务编排模板，实现类填充 _do_ 钩子。

子域:
  - PROF-01: 个人档案管理（ProfileServiceImpl → BaseProfileService）
  - PROF-03: 事件记录管理（EventServiceImpl → BaseEventService）
  - PROF-05: 专家关联管理（ExpertServiceImpl → BaseExpertService）

契约文件:
  - profiles_contract.py: BaseProfileService ABC
  - events_contract.py: BaseEventService ABC
  - experts_contract.py: BaseExpertService ABC

类型与异常:
  - types.py: 语义类型（ProfileId, CaregiverId, EventId, LinkId）
  - exceptions.py: 统一异常层次（ProfileDomainError 及其子类）
"""

from app.modules.profiles.event_routes import router as events_router
from app.modules.profiles.event_service import EventServiceImpl
from app.modules.profiles.events_contract import BaseEventService
from app.modules.profiles.expert_routes import router as experts_router
from app.modules.profiles.expert_service import ExpertServiceImpl
from app.modules.profiles.experts_contract import BaseExpertService
from app.modules.profiles.profile_service import ProfileServiceImpl
from app.modules.profiles.profiles_contract import BaseProfileService
from app.modules.profiles.routes import router as profiles_router

__all__ = [
    # 实现类（向后兼容）
    "ProfileServiceImpl",
    "EventServiceImpl",
    "ExpertServiceImpl",
    # 契约基类（供外部审查和类型检查）
    "BaseProfileService",
    "BaseEventService",
    "BaseExpertService",
    # 路由
    "profiles_router",
    "events_router",
    "experts_router",
]
