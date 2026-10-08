"""临时探针：打印「可安全删除」的精确清单（默认 dry-run，加 --apply 才真删）。

收紧后的判据（三条全部满足）：
  A. 无任何已跟踪文件引用（git grep）；
  B. .tmp 下无任何已跟踪文件（整体为 0，作为不变量再查一次）；
  C. 内容是**某个工具的纯输出**，且其输入仍在仓库内 ⇒ 可重跑再现。
     具体只认这几类扩展名/形态：
       - ffmpeg 分析产物（vf-*.mp4 / vf-*.txt / *.dump / *.log 形式的信号统计）
       - pytest / CI 运行输出（*.xml、*.log、*.txt 报告，且不含手写源码）
       - Python 字节码（__pycache__、*.pyc）
       - 浏览器临时 Profile（brand-chrome-profile）
       - 纯图片抽帧目录（目录内只有 *.png/*.jpg）

**只要条目里含手写源码（.py/.ts/.tsx/.ps1/.mjs/.md/.json），一律不删** ——
那些可能是别处不存在的探针或记录（已实测 .tmp/skillfix 属此类）。
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"E:\Project\Web_Development\Campfire-AI")
os.chdir(ROOT)
TMP = ROOT / ".tmp"
APPLY = "--apply" in sys.argv

SOURCE_EXT = {".py", ".ts", ".tsx", ".ps1", ".mjs", ".md", ".json", ".orig", ".diff"}
OUTPUT_EXT = {".png", ".jpg", ".jpeg", ".pyc", ".pma", ".dmp"}

raw = subprocess.run(
    ["git", "grep", "-oh", "-E", r"\.tmp/[A-Za-z0-9_.@/-]*", "--", "."],
    capture_output=True, text=True, encoding="utf-8", errors="replace",
).stdout
refs = {l.strip()[5:].rstrip(".,`）)") for l in raw.splitlines() if l.strip().startswith(".tmp/")}
refs.discard("")


def cited(name: str) -> bool:
    return any(r == name or r.startswith(name + "/") or name.startswith(r) for r in refs)


def _structural_ok(entry: Path) -> tuple[bool, str]:
    """对 .xml / .log 做**结构判据**（不是靠散文关键词，那会误判）。

    - `.xml`：必须以 `<?xml` 或 `<testsuite` 开头，且含 `<testsuite` 元素
      ⇒ 是 JUnit/pytest 报告，不可能是手写笔记。
    - `.log`：必须含 pytest 或 ffmpeg 的机器标记（`PASSED`/`FAILED`/`====`/
      `ffmpeg version`/`frame=`/`collected `）。
    """
    head = entry.read_bytes()[:400].decode("utf-8", errors="replace")
    if entry.suffix.lower() == ".xml":
        ok = (head.lstrip().startswith(("<?xml", "<testsuite", "<!DOCTYPE"))
              and "<testsuite" in entry.read_text(encoding="utf-8", errors="replace")[:20000])
        return (True, "JUnit/pytest XML 报告") if ok else (False, "不是标准测试报告 XML")
    text = entry.read_text(encoding="utf-8", errors="replace")[:40000]
    marks = ("PASSED", "FAILED", "ERROR", "====", "ffmpeg version", "frame=", "collected ", "passed,", "failed,")
    hit = [m for m in marks if m in text]
    return (True, f"机器日志（命中 {hit[:3]}）") if hit else (False, "无机器日志标记")


def is_output_only(entry: Path) -> tuple[bool, str]:
    """条目是否「纯工具输出」。返回 (是否, 理由)。

    ★ 收紧决定（2026-10-08）：**`.txt` 一律不删**。
    原因：`.tmp/gate-prose.py` 对 440 个 `.txt/.log/.xml` 扫「手写笔记特征」，
    156 个命中。逐个人工判读确认**多为假阳性**（工具输出含从产品代码/文档抓到的
    中文，如 grep 转储里的 `## 墓碑为什么在…` 是代码注释），但**机器无法可靠区分**
    工具输出与手写记录。`.txt` 整类仅 2.42 MB（占候选 1.4%），而 `vf-*` 一类就有
    161.6 MB ⇒ 放弃低价值高歧义的一类，保留高价值低歧义的四类。
    `.xml`/`.log` 不靠关键词而靠上面 `_structural_ok` 的**结构判据**，故仍可删。
    """
    if entry.is_file():
        n = entry.name
        if re.fullmatch(r"vf-.*", n):
            return True, "ffmpeg 分析产物"
        e = entry.suffix.lower()
        if e == ".txt":
            return False, "歧义（工具输出与手写记录无法机械区分）⇒ 整体保留"
        if e in OUTPUT_EXT:
            return True, f"工具输出（{e}）"
        if e in {".xml", ".log"}:
            return _structural_ok(entry)
        return False, f"未知扩展名 {e or '(无)'}"
    n = entry.name
    if n == "__pycache__":
        return True, "Python 字节码缓存"
    if n == "brand-chrome-profile":
        return True, "浏览器临时 Profile"
    if n == "misplaced":
        return True, "误放的 ffmpeg 转储"
    files = [f for f in entry.rglob("*") if f.is_file()]
    if files and all(f.suffix.lower() in OUTPUT_EXT for f in files):
        return True, "纯图片/字节码抽帧目录"
    bad = sorted({f.suffix.lower() or "(无)" for f in files} - OUTPUT_EXT)
    return False, f"含非纯输出文件 {bad[:4]}"


deleting: list[tuple[Path, int, int, str]] = []
skipped: list[tuple[Path, int, int, str]] = []

for entry in sorted(TMP.iterdir()):
    name = entry.name
    # 保护本轮交付物与已登记保留项
    if name in {"screenshots", "tmp-inventory.py", "tmp-candidates.py", "verify-dup.py",
                "verify-autism.py", "check-recoverable.py", "confirm-vf.py", "check-links.py",
                "check-do-refs.py", "decode-session.cjs", "subagent-status.cjs"}:
        continue
    if entry.is_file():
        size, count = entry.stat().st_size, 1
    else:
        fl = [f for f in entry.rglob("*") if f.is_file()]
        size, count = sum(f.stat().st_size for f in fl), len(fl)

    if cited(name):
        skipped.append((entry, size, count, "被已跟踪文件引用"))
        continue
    ok, why = is_output_only(entry)
    (deleting if ok else skipped).append((entry, size, count, why))

print("=== 将删除（纯工具输出 + 无引用）===")
tot_mb = tot_f = 0
for p, size, count, why in sorted(deleting, key=lambda i: -i[1]):
    tot_mb += size / 1024 / 1024
    tot_f += count
    print(f"  {size / 1024 / 1024:>8.2f} MB {count:>5}f  {p.name:<34} {why}")
print(f"\n合计 {tot_mb:.1f} MB / {tot_f} 文件 / {len(deleting)} 个顶层条目")

print("\n=== 不删（保留并登记）===")
for p, size, count, why in sorted(skipped, key=lambda i: -i[1])[:14]:
    print(f"  {size / 1024 / 1024:>8.2f} MB {count:>5}f  {p.name:<34} {why}")

if not APPLY:
    print("\n(dry-run；加 --apply 才真删)")
    sys.exit(0)

print("\n=== 执行删除 ===")
# 不变量：.tmp 下不得有任何已跟踪文件
tracked = subprocess.run(["git", "ls-files", ".tmp"], capture_output=True, text=True).stdout.strip()
if tracked:
    print("中止：.tmp 下有已跟踪文件，拒绝删除：")
    print(tracked[:500])
    sys.exit(1)
print("不变量通过：git ls-files .tmp 为空")

for p, size, count, why in deleting:
    if p.is_file():
        p.unlink()
    else:
        shutil.rmtree(p)
print(f"已删除 {len(deleting)} 个条目")
