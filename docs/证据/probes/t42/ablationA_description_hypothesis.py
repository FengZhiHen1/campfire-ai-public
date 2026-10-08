"""为什么复查者复算不出 `3A220C5A…`？——**区分「我记错了」与「我的描述不足」**。

**假设 H**：报告 §2.2 的消融内容写的是
    「（把 `session.execute(delete(...))` 换成 `result = None`）」
按这句话**字面**重建（**只换那一行**，保留它上下两行注释、不加 `_ = normalized`）
⇒ 得到一个**不同的** hash，而**不是** `3A220C5A…`。

若 H 成立 ⇒ 根因是**报告的描述有损**（实际编辑是「6 行 → 5 行」的整块替换，
顺带删掉两行注释并加了 `_ = normalized`），**不是 hash 记错**。

本脚本同时给出两个 hash 供对照。
"""

from __future__ import annotations

import hashlib
import pathlib

SRC = pathlib.Path("apps/api/src/campfire/modules/accounts/onboarding_purge.py")

ABLATED_RECORDED = "3a220c5a2ea2a1cbb2fec2d2788d2d4c3e6651bf7e7ae43233157bf884677efa"

#: 实际那次消融（整块替换：6 行 → 5 行）。
ACTUAL_OLD = (
    "    normalized = validate_account_id(account_id)\n"
    "    result = await session.execute(delete(CampfireOnboarding).where("
    "CampfireOnboarding.account_id == normalized))\n"
    "    # `rowcount` 在 `CursorResult` 上；`session.execute` 的静态类型是 `Result`\n"
    "    # （mypy 实测抓到），故显式取属性并给安全默认值。\n"
    '    return int(getattr(result, "rowcount", 0) or 0)'
)
ACTUAL_NEW = (
    "    normalized = validate_account_id(account_id)\n"
    "    # ---- 消融：删掉真正的那条删除语句（临时）----\n"
    "    result = None\n"
    "    _ = normalized\n"
    '    return int(getattr(result, "rowcount", 0) or 0)'
)

#: 按报告那句话的**字面**重建：只把 `result = await session.execute(...)` 一行换成 `result = None`。
LITERAL_OLD = (
    "    result = await session.execute(delete(CampfireOnboarding).where("
    "CampfireOnboarding.account_id == normalized))"
)
LITERAL_NEW = "    result = None"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    text = SRC.read_bytes().decode("utf-8")

    actual = text.replace(ACTUAL_OLD, ACTUAL_NEW, 1).encode("utf-8")
    literal = text.replace(LITERAL_OLD, LITERAL_NEW, 1).encode("utf-8")

    print("=== A. 实际那次消融（整块 6→5 行）===")
    print(f"  sha256 = {sha256(actual)}")
    print(f"  命中报告记录的 3A220C5A… ? {sha256(actual) == ABLATED_RECORDED}")
    print(f"  字节数 = {len(actual)}")

    print("\n=== B. 按报告那句话【字面】重建（只换一行）===")
    print(f"  sha256 = {sha256(literal)}")
    print(f"  命中报告记录的 3A220C5A… ? {sha256(literal) == ABLATED_RECORDED}")
    print(f"  字节数 = {len(literal)}")

    print("\n=== 对照 ===")
    print(f"  A 与 B 相同 ? {sha256(actual) == sha256(literal)}")
    print(f"  A 命中记录 = {sha256(actual) == ABLATED_RECORDED}；B 命中记录 = {sha256(literal) == ABLATED_RECORDED}")

    hypothesis_ok = (sha256(actual) == ABLATED_RECORDED) and (sha256(literal) != ABLATED_RECORDED)
    print(f"\n[结论] 假设 H 成立（描述有损、hash 无误）? {hypothesis_ok}")
    return 0 if hypothesis_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
