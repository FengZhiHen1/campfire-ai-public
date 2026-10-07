"""在**成片**里验证 S4 的八道题逐屏(不靠读源码)。

做法:S4 = 540-1499。在该段内密集抽帧,对「第 N / 8 题」这行做 OCR 不现实,
改用**几何特征**:题干区域的墨迹量在换题时会突变(整块文字换掉)。
通过检测突变点,数出这一段里发生了多少次「换题」。

预期:§入口1次 + 第1题 + 快掠4题 + 第6题 + 尾段2题 → 换题次数与 8 题量级相符。
"""
import re
import subprocess
from pathlib import Path

from PIL import Image

MP4 = "marketing/promo-shotcraft/out/promo-v16.mp4"
W = Path("marketing/promo-shotcraft/out/qscan")
W.mkdir(parents=True, exist_ok=True)
OUT = Path(".tmp/qscan.txt")

# S4 段
START, END = 540, 1500
STEP = 5

# 题干区(设备屏内上部):大致 x 470-830, y 300-420
BOX = (470, 300, 830, 430)


def grab(n: int) -> Path:
    p = W / f"f{n}.png"
    if not p.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", MP4,
             "-vf", f"select=eq(n\\,{n}),crop={BOX[2]-BOX[0]}:{BOX[3]-BOX[1]}:{BOX[0]}:{BOX[1]}",
             "-vframes", "1", str(p)],
            check=True,
        )
    return p


def ink(p: Path) -> int:
    with Image.open(p).convert("L") as im:
        px = im.load()
        w, h = im.size
        return sum(1 for y in range(h) for x in range(w) if px[x, y] < 128)


vals = {}
for n in range(START, END, STEP):
    vals[n] = ink(grab(n))

# 换题 = 相邻采样点墨迹量突变(>25%)
cuts = []
ks = sorted(vals)
for a, b in zip(ks, ks[1:]):
    va, vb = vals[a], vals[b]
    if va > 40 and abs(vb - va) / max(va, 1) > 0.25:
        cuts.append((b, va, vb))

lines = [
    "=" * 74,
    "S4 换题检测（成片实测，非读源码）",
    "=" * 74,
    f"  采样: f{START}–f{END} 每 {STEP} 帧一次，共 {len(vals)} 点",
    f"  题干预估墨迹量范围: {min(vals.values())} – {max(vals.values())}",
    "",
    f"  检出换题突变点 {len(cuts)} 处:",
]
for n, va, vb in cuts[:24]:
    lines.append(f"    f{n:5}  {va:5} → {vb:5}")

lines.append("")
lines.append("  预期:S4 依次演 入口 → 第1题 → 快掠4题 → 第6题 → 尾段2题，")
lines.append("        即换题约 6–8 次。检出数与之同量级即为相符。")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
