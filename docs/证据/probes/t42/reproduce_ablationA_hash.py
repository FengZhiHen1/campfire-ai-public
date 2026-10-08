"""T42 消融 A 的 hash **可复算**证明（订正复查者 P1-1）。

**用法**（任何人可复算）：
    uv run python tmp/t42/reproduce_ablationA_hash.py
它会：
 1. 读 `apps/api/src/campfire/modules/accounts/onboarding_purge.py`（改前状态）；
 2. **按字节**做那一次消融编辑（old/new 逐字写在下面）；
 3. 断言变异真的生效（SQL 调用消失）；
 4. 打印消融后的 SHA256，并落盘 `tmp/t42/ablationA-file.bin` 供逐字节复核。

**★ 为什么它此前"复算不出"**：本节末尾给出结论（含大小写与编辑形态两点）。
"""

from __future__ import annotations

import hashlib
import pathlib

SRC = pathlib.Path("apps/api/src/campfire/modules/accounts/onboarding_purge.py")
ARTIFACT = pathlib.Path("tmp/t42/ablationA-file.bin")

#: 报告 §2.2 记的两个 hash。**按小写比对**——`hashlib.hexdigest()` 与小写 `Get-FileHash`
#: 都是小写，而报告里写的是大写。**我第一次跑本脚本时正是栽在这里**（见文件末尾结论）。
BASE = "b550f833835a1608bf003eb75cf6e24945d679595a26642a8b0b178c3d0e34e5"
ABLATED = "3a220c5a2ea2a1cbb2fec2d2788d2d4c3e6651bf7e7ae43233157bf884677efa"

#: 那次消融编辑的 old_string（逐字，含缩进、注释与换行）。
OLD = (
    "    normalized = validate_account_id(account_id)\n"
    "    result = await session.execute(delete(CampfireOnboarding).where("
    "CampfireOnboarding.account_id == normalized))\n"
    "    # `rowcount` 在 `CursorResult` 上；`session.execute` 的静态类型是 `Result`\n"
    "    # （mypy 实测抓到），故显式取属性并给安全默认值。\n"
    '    return int(getattr(result, "rowcount", 0) or 0)'
)

#: 那次消融编辑的 new_string（逐字）。
NEW = (
    "    normalized = validate_account_id(account_id)\n"
    "    # ---- 消融：删掉真正的那条删除语句（临时）----\n"
    "    result = None\n"
    "    _ = normalized\n"
    '    return int(getattr(result, "rowcount", 0) or 0)'
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    raw = SRC.read_bytes()
    text = raw.decode("utf-8")

    print("=== 1. 改前文件 ===")
    print(f"  sha256 = {sha256(raw)}")
    print(f"  与报告『改前』{BASE} 一致 ? {sha256(raw) == BASE}")
    print(f"  len = {len(raw)} bytes；LF = {raw.count(bytes([10]))}；CRLF = {raw.count(bytes([13, 10]))}")

    print("\n=== 2. 变异锚点断言（先断言生效，再读结果）===")
    occurrences = text.count(OLD)
    print(f"  OLD 命中次数 = {occurrences}（必须 1）")
    assert occurrences == 1, "锚点不唯一，读数无意义"

    ablated_text = text.replace(OLD, NEW, 1)
    ablated = ablated_text.encode("utf-8")
    gone = "session.execute(delete(CampfireOnboarding)" not in ablated_text
    present = "result = None" in ablated_text
    print(f"  替换后 `session.execute(delete(CampfireOnboarding)` 已消失 ? {gone}（必须 True）")
    print(f"  替换后含 `result = None` ? {present}（必须 True）")
    assert gone and present, "变异没生效"

    print("\n=== 3. 消融后文件（本次复算）===")
    got = sha256(ablated)
    print(f"  sha256 = {got}")
    print(f"  与报告『消融后』{ABLATED} 一致 ? {got == ABLATED}")
    print(f"  len = {len(ablated)} bytes（改前 {len(raw)}，减少 {len(raw) - len(ablated)}）")

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_bytes(ablated)
    print(f"\n  已落盘供逐字节复核：{ARTIFACT}")
    print(f"  复核命令：Get-FileHash {ARTIFACT} -Algorithm SHA256")

    ok = sha256(raw) == BASE and got == ABLATED
    print(f"\n[结论] 消融 A 的两个 hash 均按字节复算命中 ? {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
