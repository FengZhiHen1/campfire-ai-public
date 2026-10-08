"""清理 T42 首次（崩溃）运行留下的残留，并改由 SDK 删除身份用户。

残留清单（psql 只读确认）：
  - 身份用户 `27a94117-2cf9-478e-be03-4513e861cfd0`（bystander，仍在 core）
  - `campfire_onboarding` 里它那一行
  - 目标账号 `39e89d2f-...` 的墓碑行（注销真的成功了，其身份用户已删）

**不碰任何非本探针自建的账号**（白名单 = 上面两个固定 id）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

for _name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_name, None)
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from sqlalchemy import delete, select  # noqa: E402

from campfire.core.auth.tombstone import AccountDeletionTombstone  # noqa: E402
from campfire.core.auth.supertokens import init_supertokens  # noqa: E402
from campfire.core.config import get_settings  # noqa: E402
from campfire.core.db import dispose_engine, session_scope  # noqa: E402
from campfire.modules.accounts.models import CampfireOnboarding  # noqa: E402

TARGET = "39e89d2f-3a48-46ba-ad1f-2d7a416018ef"
BYSTANDER = "27a94117-2cf9-478e-be03-4513e861cfd0"


async def _rows() -> list[str]:
    async with session_scope(get_settings()) as session:
        return sorted(
            (await session.execute(select(CampfireOnboarding.account_id))).scalars()
        )


async def main() -> int:
    settings = get_settings()
    init_supertokens(settings)

    print("[前] 引导表全部 account_id：")
    before = await _rows()
    print(f"  共 {len(before)} 行；含 target={TARGET in before} 含 bystander={BYSTANDER in before}")

    # 1) 引导状态行（只删这两个 id）
    async with session_scope(settings) as session:
        await session.execute(delete(CampfireOnboarding).where(CampfireOnboarding.account_id.in_((TARGET, BYSTANDER))))
        await session.execute(delete(AccountDeletionTombstone).where(AccountDeletionTombstone.account_id == TARGET))
    print("[1] 已删除两个 id 的引导状态行 + target 的墓碑行")

    # 2) 身份用户走 SDK 删（不手工改 core 的表）
    from supertokens_python.asyncio import delete_user

    for user_id in (TARGET, BYSTANDER):
        try:
            await delete_user(user_id)
            print(f"[2] 已删除身份用户 {user_id}")
        except Exception as exc:  # noqa: BLE001 —— 如实报告，不掩盖
            print(f"[2] 删除身份用户 {user_id} 未成功：{type(exc).__name__}: {exc}")

    after = await _rows()
    print(f"[后] 引导表共 {len(after)} 行；含 target={TARGET in after} 含 bystander={BYSTANDER in after}")

    await dispose_engine()
    ok = not ( {TARGET, BYSTANDER} & set(after) ) and len(after) == len(before) - 1
    print(f"[结论] {'CLEAN' if ok else '还有残留'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
