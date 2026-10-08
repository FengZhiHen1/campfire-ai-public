"""T25 资产自证：三份配置的派生关系必须逐字节可核对。

判据（全部为真才算资产可信）：

1. `before`（改动前从工作区拷出的那份）与 `git show HEAD:...` **逐字节相同**（LF 归一化后）
   —— 证明「修前」不是我事后凭记忆写的；
2. `after` 去掉那条 location 的 5 行后**逐字节等于** `ablated` —— 证明**消融输入与交付内容
   之间唯一的差异就是这一条 location**。这正是消融实验要问的问题（「把这一条删掉会怎样」）
   所要求的前提；
3. **功能等价**：`ablated` 与 `before`/HEAD 去掉**全部注释行**之后逐字节相同 ——
   证明消融输入在 nginx 眼里与「未修」等价（`ablated` 与 `before` 的文本差异只有注释，
   而 nginx 解析器不读注释行）。它把「注释差异不影响实验结论」从口头声明变成机器判据；
4. 那条 location 在 `after` 里出现且仅出现一次，在 `ablated` / `before` / HEAD 里零次。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
ASSETS = Path(__file__).resolve().parent
REL = "infrastructure/docker/app-locations.conf"

LOCATION_BLOCK = (
    "location = /readyz/deep {\n"
    "    proxy_pass         http://$campfire_api;\n"
    "    proxy_set_header   Host $host;\n"
    '    add_header         Cache-Control "no-store" always;\n'
    "}\n"
)


def _without_comments(text: str) -> str:
    """去掉整行注释与空行——近似「nginx 解析器看到的指令序列」。

    只丢**整行**注释（行首可选空白后是 `#`）：本文件没有行尾注释，也没有 `#`
    出现在指令参数里的写法（实测 `grep -n '#' ` 的命中全部在行首）。这个简化在
    本文件的形态下是安全的，且它只用来自证「注释差异不动语义」——不承担路由判据。
    """
    return "".join(line for line in text.splitlines(keepends=True) if line.strip() and not line.lstrip().startswith("#"))


def main() -> int:
    head = (
        subprocess.run(["git", "show", f"HEAD:{REL}"], cwd=REPO, check=True, capture_output=True)
        .stdout.decode("utf-8")
        .replace("\r\n", "\n")
    )
    after = (ASSETS / "app-locations.after.conf").read_text(encoding="utf-8")
    ablated = (ASSETS / "app-locations.ablated.conf").read_text(encoding="utf-8")
    before = (ASSETS / "app-locations.before.conf").read_text(encoding="utf-8")

    checks = [
        ("before（改动前工作区副本）与 git HEAD 逐字节相同", before == head),
        ("after 去掉 location 块后 == ablated（唯一差异）", after.replace(LOCATION_BLOCK, "") == ablated),
        ("去注释后：ablated == before（消融输入与未修等价）", _without_comments(ablated) == _without_comments(before)),
        ("去注释后：ablated == HEAD 且 after 多出恰好一行 location", (
            _without_comments(ablated) == _without_comments(head)
            and _without_comments(after).count("location = /readyz/deep {") == 1
            and _without_comments(ablated).count("location = /readyz/deep {") == 0
        )),
        ("location 块在 after 中出现恰好 1 次", after.count(LOCATION_BLOCK) == 1),
        ("location 块在 ablated / before / HEAD 中出现 0 次", (
            ablated.count(LOCATION_BLOCK) == 0
            and before.count(LOCATION_BLOCK) == 0
            and head.count(LOCATION_BLOCK) == 0
        )),
    ]
    ok = True
    for label, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    print()
    print(f"assets dir: {ASSETS}")
    print(f"head bytes={len(head.encode())}  before bytes={len(before.encode())}")
    print(f"ablated bytes={len(ablated.encode())}  after bytes={len(after.encode())}")
    print(f"去注释后指令字节数：head={len(_without_comments(head).encode())} "
          f"ablated={len(_without_comments(ablated).encode())} after={len(_without_comments(after).encode())}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
