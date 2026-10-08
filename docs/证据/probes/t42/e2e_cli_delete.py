"""T42 真栈端到端：走完整运营 CLI 注销，读 `campfire_onboarding` 的前后行数。

**为什么是一个探针脚本而不是提交进测试套件的用例**：
本探针会**真的删除数据**（身份用户 + 真实库行），且需要真实 core 与图库同时可用。
把它提交进 `apps/api/tests` 的后果有两条，都不可接受：
① CI 刻意不起 SuperTokens core（见 `ci.yml` 的说明），它会 skip 或 fail；
② 本地每次跑都真的删一轮数据。
这正是 `docs/TODO.md` 第 129 行「运营 CLI 未做端到端集成测试」写明的落地方式
（「另起一次性的隔离库 + 隔离 core 配置，或做成显式的手动验收清单」）。

用法：
    uv run python tmp/t42/e2e_cli_delete.py

它做的事（**只碰自建账号**）：
 1. 记基线：引导表总行数 + 全部 `account_id` 的集合；
 2. 真建两个身份用户（`t42-e2e-<stamp>-target` / `-bystander`）；
 3. 各落一行引导状态；
 4. **子进程调用真 CLI**：`python -m campfire.cli account delete <target> --confirm <target>`；
 5. 记注销后读数，断言目标账号行为 0、旁证账号行仍在、其余账号集合逐字不变；
 6. 清理本探针自建的一切（两个身份用户、两行引导状态、目标账号的墓碑）。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

# 宿主机的 no_proxy 可能含 `[::1]`，而 SDK 的 querier 自建 httpx 客户端
# （生产侧已由 `apply_no_proxy_normalization` 覆盖；这里再显式处理一次本进程的写入侧）。
for _name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_name, None)
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from sqlalchemy import delete, func, select  # noqa: E402

from campfire.core.auth.tombstone import AccountDeletionTombstone  # noqa: E402
from campfire.core.auth.supertokens import init_supertokens  # noqa: E402
from campfire.core.config import get_settings  # noqa: E402
from campfire.core.db import dispose_engine, session_scope  # noqa: E402
from campfire.modules.accounts.models import (  # noqa: E402
    ONBOARDING_IN_PROGRESS,
    CampfireOnboarding,
)

PASSWORD = "probePass123"
DOMAIN = "t42-e2e.example.test"


def _stamp() -> str:
    return time.strftime("%H%M%S")


async def _all_account_ids() -> set[str]:
    """引导表里全部 `account_id`（用于「别人的行不变」的集合级判据）。"""
    async with session_scope(get_settings()) as session:
        return set(
            (await session.execute(select(CampfireOnboarding.account_id))).scalars()
        )


async def _count(account_id: str) -> int:
    async with session_scope(get_settings()) as session:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(CampfireOnboarding)
                    .where(CampfireOnboarding.account_id == account_id)
                )
            ).scalar_one()
        )


async def _seed(account_id: str, state: str) -> None:
    async with session_scope(get_settings()) as session:
        session.add(CampfireOnboarding(account_id=account_id, state=state))


async def _make_user(email: str) -> str:
    """真建一个身份用户，返回它的 user id（即 CLI 收的 account 标识）。"""
    from supertokens_python.recipe.emailpassword.asyncio import sign_up

    created = await sign_up("public", email, PASSWORD)
    assert type(created).__name__.startswith("SignUpOk"), f"建号失败：{created}"
    return created.user.id


async def _delete_user(user_id: str) -> None:
    from supertokens_python.asyncio import delete_user

    await delete_user(user_id)


async def main() -> int:
    settings = get_settings()
    assert settings.database_url, "未配置 DATABASE_URL"
    assert settings.supertokens_api_key is not None, "未配置 SUPERTOKENS_API_KEY"

    stamp = _stamp()
    target_email = f"t42-e2e-{stamp}-target@{DOMAIN}"
    bystander_email = f"t42-e2e-{stamp}-bystander@{DOMAIN}"

    init_supertokens(settings)

    before_ids = await _all_account_ids()
    before_total = len(before_ids)
    print(f"[基线] campfire_onboarding 总行数 = {before_total}")

    target = await _make_user(target_email)
    bystander = await _make_user(bystander_email)
    print(f"[建号] target={target}")
    print(f"[建号] bystander={bystander}")

    await _seed(target, ONBOARDING_IN_PROGRESS)
    await _seed(bystander, ONBOARDING_IN_PROGRESS)

    before_total = len(await _all_account_ids())
    before_target = await _count(target)
    before_bystander = await _count(bystander)
    before_others = (await _all_account_ids()) - {target, bystander}
    print(f"[注销前] 总行数={before_total} 该账号行数={before_target} 旁证账号行数={before_bystander}")
    print(f"[注销前] 其它账号行数={len(before_others)}")

    # —— 真栈：子进程调用真 CLI（运营入口），不是直接调 delete_account ——
    cmd = [
        sys.executable,
        "-m",
        "campfire.cli",
        "account",
        "delete",
        target,
        "--confirm",
        target,
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "apps" / "api" / "src")
    # **必须给子进程 UTF-8**：`operator.py` 的注销回执末尾打印一条含 `⚠️`（U+26A0 U+FE0F）
    # 的提示，而 Windows 上子进程 stdout 接管道时落 cp936 ⇒ `UnicodeEncodeError` ⇒
    # **注销其实已经成功，CLI 却在打印回执时崩掉并退出 1**（本次实测踩到，见
    # `diagnose_cli_exit.py`）。这是**既有**行为，不属本包改动；本探针不改产品代码，
    # 只给子进程一个能编码该字符的 stdout，以便读到真实退出码与回执。
    # ⚠ 如实说明：这条设置把「cp936 控制台下 CLI 会崩」这一事实掩盖掉了——
    # 该事实另有独立证据（`diagnose_cli_exit.py`），已登记在报告的证据边界里。
    env["PYTHONIOENCODING"] = "utf-8"
    print(f"[CLI] {' '.join(cmd[:6])} <account> --confirm <account>")
    completed = subprocess.run(  # noqa: S603 —— 固定参数、无 shell
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(f"[CLI] 退出码 = {completed.returncode}")
    print("---- CLI stdout ----")
    print(completed.stdout.strip())
    print("---- CLI stderr ----")
    print(completed.stderr.strip())

    after_ids = await _all_account_ids()
    after_target = await _count(target)
    after_bystander = await _count(bystander)
    after_others = after_ids - {target, bystander}
    after_total = len(after_ids)
    print(f"[注销后] 总行数={after_total} 该账号行数={after_target} 旁证账号行数={after_bystander}")
    print(f"[注销后] 其它账号行数={len(after_others)}")

    verdict = {
        "cli_exit_code": completed.returncode,
        "target_rows_before": before_target,
        "target_rows_after": after_target,
        "bystander_rows_before": before_bystander,
        "bystander_rows_after": after_bystander,
        "others_unchanged": before_others == after_others,
        "others_count_before": len(before_others),
        "others_count_after": len(after_others),
    }
    print("[判定] " + json.dumps(verdict, ensure_ascii=False))

    # —— 清理本探针自建的一切（白名单：只有上面两个账号）——
    async with session_scope(settings) as session:
        await session.execute(delete(CampfireOnboarding).where(CampfireOnboarding.account_id.in_((target, bystander))))
        await session.execute(
            delete(AccountDeletionTombstone).where(AccountDeletionTombstone.account_id == target)
        )
    for user_id in (target, bystander):
        try:
            await _delete_user(user_id)
        except Exception as exc:  # noqa: BLE001 —— 清理失败如实报告，不掩盖判定
            print(f"[清理] 删除身份用户失败（{user_id}）：{type(exc).__name__}: {exc}")

    final_ids = await _all_account_ids()
    print(f"[清理后] 总行数={len(final_ids)}；与基线一致={final_ids == before_ids}")

    await dispose_engine()

    ok = (
        completed.returncode == 0
        and before_target == 1
        and after_target == 0
        and after_bystander == 1
        and before_others == after_others
        and final_ids == before_ids
    )
    print(f"[结论] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
