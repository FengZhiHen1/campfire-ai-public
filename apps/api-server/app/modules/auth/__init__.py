"""auth -- 身份认证：用户注册、匿名设备 ID 识别。"""
from .auth_service import register_user
from .routes import router as auth_router

__all__ = ["register_user", "auth_router"]
