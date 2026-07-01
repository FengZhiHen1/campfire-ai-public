"""FastAPI 依赖注入工厂 — 集中管理。

提供各业务模块所需的 Repository、适配器和基础设施依赖的工厂函数，
供 FastAPI Depends() 注入使用。

Usage:
    from app.core.dependencies import (
        get_db_session,
        get_user_repository,
        get_password_hasher,
        get_audit_logger,
    )
"""

from app.core.dependencies.anonymous_user import get_anonymous_user
from app.core.dependencies.auth_dependencies import (
    AuditLogger,
    PasswordHasher,
    get_audit_logger,
    get_auth_service,
    get_db_session,
    get_event_repository,
    get_narrative_repository,
    get_password_hasher,
    get_profile_repository,
    get_review_audit_log_repository,
    get_review_repository,
    get_teacher_link_repository,
    get_token_blacklist,
    get_token_manager,
    get_user_repository,
)

__all__ = [
    "get_db_session",
    "get_user_repository",
    "get_narrative_repository",
    "get_review_repository",
    "get_review_audit_log_repository",
    "get_event_repository",
    "get_profile_repository",
    "get_teacher_link_repository",
    "get_password_hasher",
    "get_audit_logger",
    "get_token_manager",
    "get_token_blacklist",
    "get_auth_service",
    "get_anonymous_user",
    "PasswordHasher",
    "AuditLogger",
]
