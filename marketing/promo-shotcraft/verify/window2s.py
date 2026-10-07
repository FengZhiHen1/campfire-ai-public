"""独立复算:是否存在「2 秒窗口内没有任何可见变化」的区间。

判据与交付文档一致:tblend 差分逐帧 YAVG,<0.35 视为该帧无可见变化。
窗口 = 60 帧(2s)。若一个 60 帧窗口内**全部**低于阈值,即违规。

与「最长连续静止区间」的区别:后者找的是连续静止段;这里找的是**任意**滑动窗口,
更能反映观众的体感(哪怕静止段被打断成 59+1+59,两个窗口仍然是近乎全静止)。
"""
import io
import re
from pathlib import Path
from _timeline import RANGES

ROOT = Path("marketing/promo-shotcraft")
MOTION = ROOT / "out" / "qa4" / "motion-v16.txt"
OUT = Path(".tmp/window2s.txt")

THRESH = 0.35
WIN = 60  # 2s @30fps

vals: dict[int, float] = {}
for i, line in enumerate(io.open(MOTION, encoding="utf-8", errors="ignore")):
    m = re.search(r"YAVG=([\d.eE+-]+)", line)
    if m:
        vals[i] = float(m.group(1))

frames = sorted(vals)
# 镜头区间真源(见 _timeline.py)
SHOTS = RANGES
def shot_of(f: int) -> str:
    for n, a, b in SHOTS:
        if a <= f < b:
            return n
    return "?"


lines = [
    "=" * 74,
    "2 秒窗口检查（窗口内全部帧无可见变化 = 违规）",
    "=" * 74,
    f"  阈值 YAVG < {THRESH}；窗口 {WIN} 帧（2s）；统计帧数 {len(frames)}",
    "",
]

bad: list[tuple[int, int, float]] = []
for start in frames:
    end = start + WIN
    if end > frames[-1]:
        break
    seg = [vals[f] for f in range(start, end + 1) if f in vals]
    if len(seg) < WIN * 0.9:
        continue
    if max(seg) < THRESH:
        bad.append((start, end, max(seg)))

if not bad:
    lines.append("  ✓ 不存在这样的窗口 —— 任意 2 秒内都有可见变化")
else:
    # 归并相邻窗口
    runs = []
    s = prev = bad[0][0]
    for a, _b, _m in bad[1:]:
        if a > prev + 1:
            runs.append((s, prev))
            s = a
        prev = a
    runs.append((s, prev))
    lines.append(f"  ✗ 存在 {len(bad)} 个违规窗口，归并为 {len(runs)} 个区间：")
    for a, b in runs:
        # 该区间的实际最低值
        seg = [vals[f] for f in range(a, b + WIN + 1) if f in vals]
        lines.append(
            f"    f{a}-{b + WIN}  起帧 {a} ({shot_of(a)})  "
            f"窗口长度 {(b + WIN - a) / 30:.2f}s  峰值 {max(seg):.3f}"
        )

lines.append("")
lines.append("  说明:S1/S9 的品牌 hold 是 final-review B3 **要求**的静止（≥1s），")
lines.append("        品牌字标落定后画面本就不动；若违规区间完全落在 hold 内，属合规。")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
