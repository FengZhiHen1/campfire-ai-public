"""授权判定：唯一授权端口（一期实现「属主即允许」，由装配处注入）。

职责：导出端口协议、错误类型与两个判定入口；承载实现的注入点。
边界：不依赖任何业务模块——实现归 `modules/profile`，由 main/worker/cli 注入。
参考：docs/项目结构设计.md 第 8 节、docs/技术设计/technical-details/支持对象.md 第 5 节。
"""

# 归属（见 docs/项目结构设计.md 第 8 节）：`core/authz` 是唯一授权判定端口；
# 一期只有「属主即允许」一个实现（`RQ-MEM-05`：档案一期只创建者可用）；
# 二期新增 `spaces` 模块实现同一端口，调用点不变。一期不预建该模块与空表。
#
# 禁止（见 AGENTS.md 行为准则）：授权不得只靠角色名、前端隐藏、Agent 扩展或缓存
# 判断；认证或授权不可用时拒绝受限操作，不降级为放行
# （docs/技术栈设计.md 第 5 节）。
#
# 为什么实现不在本包（支持对象 5.1）：`core/*` 不得依赖 `modules/*`，而判定要查
# 支持对象表（属主与归档状态）。因此协议与错误类型在此、实现放 `modules/profile`、
# 由装配处注入——与注销 purger 是同一模式。
#
# 二期的接入缝：`spaces` 实现同一协议并注入即可，调用点（`require_owned` /
# `require_writable`）不变。

from campfire.core.authz.errors import (
    AUTHORIZER_UNAVAILABLE_MESSAGE,
    OBJECT_ARCHIVED_MESSAGE,
    OBJECT_NOT_ACCESSIBLE_MESSAGE,
    AuthorizationError,
    ObjectArchivedError,
)
from campfire.core.authz.port import (
    Authorizer,
    get_authorizer,
    require_owned,
    require_writable,
    set_authorizer,
)

__all__ = [
    # 端口与注入
    "Authorizer",
    "get_authorizer",
    "require_owned",
    "require_writable",
    "set_authorizer",
    # 错误类型
    "AuthorizationError",
    "ObjectArchivedError",
    # 对外文案（契约的一部分，测试逐字断言）
    "AUTHORIZER_UNAVAILABLE_MESSAGE",
    "OBJECT_ARCHIVED_MESSAGE",
    "OBJECT_NOT_ACCESSIBLE_MESSAGE",
]
