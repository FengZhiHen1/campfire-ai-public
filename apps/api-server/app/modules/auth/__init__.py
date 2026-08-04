"""app.modules.auth — api-server 认证模块（ADR-013 目标态）。

提供 5 大能力：
1. 用户注册: 邀请码预检 + 原子消费 + 身份-凭证分离落库 + 准入落态
2. 用户登录: 手机号 + 密码，状态机放行（disabled 拒签），新 Token 家族签发
3. Token 续期: 轮换 + 家族吊销检查 + 复用检测（命中吊销全家族）
4. 登出: access 黑名单 + 家族吊销
5. 平台管理: 邀请码生成/列表/停用（admin）+ 准入审核通过/驳回/重提

核心类：
  - AuthService(ABC): 认证服务契约骨架，@final 公共入口 + _do_ 钩子
  - AuthServiceImpl: 实现 AuthService 契约，注入 py_auth 契约实例
  - InviteCodeService: 邀请码管理服务（admin）
  - ReviewService: 准入审核服务（admin + 本人重提）

Usage:
    from app.modules.auth import AuthService, AuthServiceImpl, auth_router

    app.include_router(auth_router)
"""

from app.modules.auth.auth_contract import AuthService
from app.modules.auth.auth_service import AuthServiceImpl
from app.modules.auth.invite_codes_service import InviteCodeService
from app.modules.auth.review_service import ReviewService
from app.modules.auth.routes import router as auth_router

__all__ = [
    "AuthService",
    "AuthServiceImpl",
    "InviteCodeService",
    "ReviewService",
    "auth_router",
]
