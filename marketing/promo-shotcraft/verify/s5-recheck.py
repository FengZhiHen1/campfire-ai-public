"""S5 静止率与边距 —— 薄封装,复用两个已验证的脚本,避免重复实现出错。

★★ 为什么重写(独立复核 P1,已逐字复现):
  旧版本有三个缺陷,叠加起来使它变成「永远不会失败的门禁」:
    ① 默认路径 `out/promo-v16-new.mp4` **不存在**(临时渲染名,早已删);
    ② `metadata=print` **漏了 `:file=-`** ⇒ 一个 YAVG 都采不到;
    ③ 采不到数据时不报错 ⇒ 输出「全片帧数 0 / **S5 静止率 0.0%**」并 **exit 0**。
  照 `ACCEPTANCE.md` 逐字跑就是这个结果 —— 而 `verify/README.md` 的陷阱第 2 条
  写的正是这个坑,等于**我自己的脚本复发了我自己记录的缺陷**。

  修法:不再重复实现,直接调用已经验证过的两个脚本:
    · 静止率 → `motion-fresh.py`(采不到数据会报错,见其注释)
    · 边距   → `bezel-scan.py`(默认路径真实、零帧会报错)
  本脚本只做汇总与「S5 那一栏」的摘录。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("marketing/promo-shotcraft")
FILM = str(ROOT / "out" / "promo-v16.mp4")
OUT = Path(".tmp/s5-recheck.txt")

if not Path(FILM).exists():
    raise SystemExit(f"★ 找不到成片: {FILM}")

lines = [
    "=" * 74,
    "S5 静止率与边距(薄封装:复用 motion-fresh.py + bezel-scan.py)",
    "=" * 74,
    f"  成片: {FILM}",
    "",
]


def run(script: str, *args: str) -> str:
    """跑 verify/ 下的脚本,返回它打印的「written …」之后的输出文件内容。"""
    r = subprocess.run(
        [sys.executable, str(ROOT / "verify" / script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    if r.returncode != 0:
        raise SystemExit(f"★ {script} 失败(exit {r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r.stdout


# ① 静止率:交给 motion-fresh.py(它会自己报错,不会静默给 0%)
run("motion-fresh.py", FILM, ".tmp/s5-motion.txt")
mo = Path(".tmp/s5-motion.txt").read_text(encoding="utf-8")
m = re.search(r"全片静止率 ([\d.]+)%", mo)
m5 = re.search(r"S5: 静止\s+([\d.]+)%", mo)
lines += [
    "  ① 静止率(口径:320×180 + tblend 帧差,YAVG < 0.35;由 motion-fresh.py 产出)",
    f"     全片: {m.group(1) + '%' if m else '?'}",
    f"     S5  : {m5.group(1) + '%' if m5 else '?'}",
    "",
]

# ② 边距:交给 bezel-scan.py
run("bezel-scan.py", FILM)
bz = Path(".tmp/bezel-scan.txt").read_text(encoding="utf-8")
lines += [
    "  ② 边距(全片逐帧扫深色 bezel;由 bezel-scan.py 产出)",
]
for ln in bz.splitlines():
    s = ln.strip()
    if s.startswith("S5") or "全片最小边距" in s or "扫描帧数" in s:
        lines.append(f"     {s}")

lines += [
    "",
    "  说明:本脚本**不自己实现**度量,只汇总。",
    "        这样「采不到数据报错」这类防护只需在 motion-fresh.py / bezel-scan.py",
    "        里各写一次,不会因为多写一份拷贝而漏掉。",
]

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
