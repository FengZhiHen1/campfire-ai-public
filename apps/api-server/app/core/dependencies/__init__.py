"""FastAPI 依赖注入工厂 — 集中管理。

提供各业务模块所需的 Repository、适配器和基础设施依赖的工厂函数，
供 FastAPI Depends() 注入使用。

Usage:
    from app.core.dependencies import (
        get_db_session,
        get_current_user,
        require_roles,
    )
"""

from app.core.dependencies.auth_dependencies import (
    AuditLogger,
    CurrentUser,
    PasswordHasher,
    get_audit_logger,
    get_auth_service,
    get_credential_repository,
    get_current_user,
    get_db_session,
    get_event_repository,
    get_invite_code_repository,
    get_invite_code_service,
    get_narrative_repository,
    get_password_hasher,
    get_profile_access_repository,
    get_profile_repository,
    get_professional_note_repository,
    get_review_audit_log_repository,
    get_review_repository,
    get_review_service,
    get_token_blacklist,
    get_token_manager,
    get_user_repository,
    require_roles,
)

__all__ = [
    "get_db_session",
    "get_user_repository",
    "get_credential_repository",
    "get_invite_code_repository",
    "get_narrative_repository",
    "get_review_repository",
    "get_review_audit_log_repository",
    "get_event_repository",
    "get_profile_repository",
    "get_profile_access_repository",
    "get_professional_note_repository",
    "get_password_hasher",
    "get_audit_logger",
    "get_token_manager",
    "get_token_blacklist",
    "get_auth_service",
    "get_invite_code_service",
    "get_review_service",
    "get_current_user",
    "require_roles",
    "CurrentUser",
    "PasswordHasher",
    "AuditLogger",
]
