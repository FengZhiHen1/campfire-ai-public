"""判定：真 CLI 在【管道 stdout】下退出码 1，是不是末尾那条 emoji 打印造成的。

判据：把 `operator.py` 最后两行打印的字符串在 cp936 下编码，看是否抛 UnicodeEncodeError；
并复现「管道 + 默认 locale 编码」的组合。
"""

from __future__ import annotations

import locale
import subprocess
import sys

print("preferred encoding =", locale.getpreferredencoding(False))

# —— 一、直接编码判据 ——
# operator.py 的注销回执末尾逐字打印这条（含 U+26A0 U+FE0F）。
line = "  \u26a0\ufe0f 保留了一条不含内容的注销记录（账号标识、时间、原因）——"
for encoding in ("cp936", "utf-8"):
    try:
        line.encode(encoding)
        print(f"encode({encoding}) = OK")
    except UnicodeEncodeError as exc:
        print(f"encode({encoding}) = FAIL -> {type(exc).__name__}: {exc}")

# —— 二、复现：子进程 stdout 接管道，打印同一条 ——
script = "print('  \\u26a0\\ufe0f 保留了一条不含内容的注销记录')\nprint('done')\n"
result = subprocess.run(
    [sys.executable, "-c", script],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
print("child returncode =", result.returncode)
print("child stdout =", repr(result.stdout))
print("child stderr tail =", (result.stderr.strip().splitlines() or ["(empty)"])[-1])

# —— 三、正控：同一子进程，强制 stdout 用 utf-8 ——
result_utf8 = subprocess.run(
    [sys.executable, "-c", script],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    env={"PYTHONIOENCODING": "utf-8", "PATH": ""},
)
print("child(PYTHONIOENCODING=utf-8) returncode =", result_utf8.returncode)
print("child(PYTHONIOENCODING=utf-8) stdout =", repr(result_utf8.stdout))
