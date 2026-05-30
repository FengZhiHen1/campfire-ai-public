"""FastAPI 依赖注入工厂 — 集中管理。

提供各业务模块所需的 Repository、适配器和基础设施依赖的工厂函数，
供 FastAPI Depends() 注入使用。

Usage:
    from app.core.dependencies.auth_dependencies import (
        get_db_session,
        get_user_repository,
        get_password_hasher,
        get_audit_logger,
    )
"""
