"""app.modules.auth — api-server 认证模块。

提供 4 大能力：
1. 用户注册 (AUTH-01): 7 步校验流程（复杂度→唯一性→哈希→持久化→审计）
2. 用户登录 (AUTH-02): 凭证校验 + JWT Token 对签发
3. Token 续期 (AUTH-03): Refresh Token 校验 + 轮换 + 重放防护
4. 登出: Token 黑名单写入 + Refresh Token 标记已使用

核心类：
  - AuthService(ABC): 认证服务契约骨架，@final 公共入口 + _do_ 钩子
  - AuthServiceImpl: 实现 AuthService 契约，注入 py_auth 契约实例

外部接口（路由层消费）：
  - AuthService: ABC 契约类（路由层通过 Depends 注入实现）
  - AuthServiceImpl: 具体实现类（由 auth_dependencies 组装）
  - auth_router: FastAPI APIRouter 实例（注册到 app）

异常（业务层，由 @final 方法自动映射为 HTTPException）：
  - AuthServiceError: 统一基类
  - PasswordComplexityError: 密码复杂度不足 → 422
  - RealNameRequiredError: 专家缺少 real_name → 422
  - DuplicateUserError: 用户名/手机号重复 → 409
  - InvalidCredentialsError: 凭证无效 → 401
  - TokenInvalidError: Token 无效/过期/重放 → 401
  - AuthInternalError: 内部错误 → 500

依赖注入链：
  AuthService → PasswordHasher(py_auth) + TokenManager(py_auth)
                + TokenBlacklist(py_auth) + UserRepository(py_db)
                + AuditLogger

Usage:
    from app.modules.auth import AuthService, AuthServiceImpl, auth_router

    app.include_router(auth_router)
"""

from app.modules.auth.auth_contract import AuthService
from app.modules.auth.auth_service import AuthServiceImpl
from app.modules.auth.routes import router as auth_router

__all__ = ["AuthService", "AuthServiceImpl", "auth_router"]
