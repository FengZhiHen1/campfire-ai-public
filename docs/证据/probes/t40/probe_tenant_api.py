"""T40 机制探针：确认 `get_tenant` 能作为「租户是否存在」的语义判据。

为什么需要它：C-3 的修法要在 `except` 分支里区分「租户不存在」与「真异常」。
SDK 抛的是**裸** `Exception("Tenant not found error.")`（`auth_utils.py:869`），
按消息字符串匹配是脆的。`get_tenant` 返回 `None` 是 SDK 自己的语义判定
（`recipe_implementation.py:183-184` 对 `TENANT_NOT_FOUND_ERROR` 返回 None），
不依赖任何字符串——本探针就是来核实这一点在**真 core**上成立的。
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("no_proxy", "localhost,127.0.0.1")
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")


async def main() -> None:
    from supertokens_python.recipe.multitenancy.asyncio import get_tenant

    from campfire.core.auth.supertokens import init_supertokens
    from campfire.core.config import get_settings
    from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields

    settings = get_settings()
    init_supertokens(settings, api_overrides=api_overrides, sign_up_form_fields=sign_up_form_fields)

    for tenant in ("public", "t40-unknown-tenant"):
        try:
            res = await get_tenant(tenant)
            print(f"get_tenant({tenant!r}) -> {type(res).__name__} / None={res is None}")
        except Exception as exc:  # noqa: BLE001 —— 探针：如实报告异常形态
            print(f"get_tenant({tenant!r}) -> RAISED {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
