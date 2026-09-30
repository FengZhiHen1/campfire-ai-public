"""认证（SuperTokens）的跨切能力。

职责与归属（见 docs/项目结构设计.md 第 6 节）：会话的建立与撤销、注销墓碑；
账号的注册、邀请码、人工重置等用例服务归 `modules/accounts`。
边界：本模块只提供 core 可达性探测（`check_auth_core`）与墓碑的对外入口。
参考：docs/技术设计/decisions/会话校验逐请求查证数据库.md。
"""

import httpx

from campfire.core.auth.deletion import (
    AccountDataPurger,
    AccountDeletionError,
    DeletionReport,
    PurgeOutcome,
    delete_account,
)
from campfire.core.auth.tombstone import (
    DELETION_REASON_USER_REQUEST,
    MAX_ACCOUNT_ID_LENGTH,
    TOMBSTONE_REASONS,
    AccountDeletionTombstone,
)
from campfire.core.auth.tombstone_repository import (
    BATCH_MAX_ACCOUNTS,
    TombstoneError,
    TombstonePayloadError,
    TombstoneResult,
    deleted_account_ids,
    get_tombstone,
    is_account_deleted,
    record_deletion,
)
from campfire.core.config import Settings
from campfire.core.health import ComponentHealth, Status

# 墓碑为什么在这里：
#
# `tombstone.py` 的 `AccountDeletionTombstone` 归本模块，判据是依赖白名单：
# Worker 只允许 import `core/*` 与 `modules/{profile,memory}` 且禁止回查业务用例，
# 故墓碑不能放 `modules/accounts`；而请求路径与 Worker 都要读它。详见该文件说明。

__all__ = [
    # 探测（core 可达性）
    "check_auth_core",
    "core_hello_url",
    # 墓碑：常量与表
    "BATCH_MAX_ACCOUNTS",
    "DELETION_REASON_USER_REQUEST",
    "MAX_ACCOUNT_ID_LENGTH",
    "TOMBSTONE_REASONS",
    "AccountDeletionTombstone",
    # 墓碑：异常
    "TombstoneError",
    "TombstonePayloadError",
    # 墓碑：读写
    "TombstoneResult",
    "deleted_account_ids",
    "get_tombstone",
    "is_account_deleted",
    "record_deletion",
    # 注销编排（五步）与领域清除端口
    "AccountDataPurger",
    "AccountDeletionError",
    "DeletionReport",
    "PurgeOutcome",
    "delete_account",
]


def core_hello_url(settings: Settings) -> str:
    """返回 core 的 `/hello` 地址。

    单独抽出来是为了可测：URI 配置为空或非法时，httpx 抛的是
    `InvalidURL`（配置问题），必须与「连不上」（网络问题）区分开。
    """
    return f"{settings.supertokens_connection_uri.rstrip('/')}/hello"


async def check_auth_core(settings: Settings) -> ComponentHealth:
    """探测 SuperTokens core 是否可达（`GET /hello`）。

    core 在鉴权关键路径上（见模块说明；真源：docs/技术设计/decisions/会话校验逐请求查证数据库.md）：

    - SDK 以 `check_database=True` 发起会话校验（`supertokens-python` 源码实测：
      `recipe/session/recipe_implementation.py` 把 `check_database is True` 透传为
      `always_check_core`）；
    - 而该查证由 core 执行（`session_functions.get_session` 仅在
      `not always_check_core` 时本地返回，否则 POST `/recipe/session/verify`）；
    - 因此 core 在鉴权关键路径上：core 不可用时，注册、登录、重置、刷新以及全部
      受限操作都不可用，不存在「已登录用户不受影响」的路径。

    这是 `AC-17`（重置后旧会话立即失效）成立的必要代价——无状态校验下被撤销的
    access token 在到期前仍然可用。核心可用性因此必须被健康检查与告警覆盖。

    这个探针比它看起来重要：core 在鉴权关键路径上，因此它的
    可达性直接等于「全站受限操作是否可用」。

    刻意 `trust_env=False`：core 是内网/同机服务，它的可达性不该由宿主机的
    代理策略决定。实测踩到过：宿主机 `NO_PROXY` 含 IPv6 字面量（`[::1]`）时，
    httpx 解析代理豁免列表会抛 `InvalidURL: Invalid port`，于是探针把一个纯
    环境问题报成「core 不可达」。

    失败时只回报异常类型，不复述连接串与凭据。
    """
    url = core_hello_url(settings)
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            response = await client.get(url)
    except (httpx.InvalidURL, httpx.UnsupportedProtocol):
        # 配置问题，不是可达性问题：报错文案不能让排查者去查网络。
        # 实测两类都要覆盖：坏端口抛 InvalidURL，缺协议头/错协议抛 UnsupportedProtocol。
        return ComponentHealth(
            "auth",
            Status.UNAVAILABLE,
            "SUPERTOKENS_CONNECTION_URI 不是合法的 http(s) 地址",
        )
    except Exception as exc:  # noqa: BLE001 —— 探针吞掉一切网络异常并如实上报
        return ComponentHealth("auth", Status.UNAVAILABLE, f"core 不可达（{type(exc).__name__}）")

    if response.status_code != 200:
        return ComponentHealth("auth", Status.UNAVAILABLE, f"core 返回 {response.status_code}")
    return ComponentHealth("auth", Status.OK, "core 可达")
