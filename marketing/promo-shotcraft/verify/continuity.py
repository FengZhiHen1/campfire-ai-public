"""跨段连续性:换段时设备框的位置是否跳变?

★ 为什么查这个:
  我此前所有的检查都是**分段**的(各段自己的相机上限、边距、构图)。
  但段与段之间是**硬切**,如果前一段末尾设备在画面 A 处、后一段开头设备在 B 处,
  观众看到的就是一次「设备瞬移」—— 每段单独看都合规,合起来却是剪辑瑕疵。
  这与上一轮发现的「接缝空帧」是同一类:**只在跨段处出现**。

做法:逐帧量设备框(深色 bezel)在画面里的**中心 y 与宽度**,然后看
      每处切点前后各 3 帧的变化量,与「段内相邻帧的正常变化」对比。
"""
import subprocess
from pathlib import Path

import numpy as np

FILM = "marketing/promo-shotcraft/out/promo-v16.mp4"
OUT = Path(".tmp/continuity.txt")
W, H = 480, 270          # 缩放后分析(够定位 bezel)
N = W * H
# ★ 阈值是试出来的,不是猜的:实测 f1599 上灰<160 且每行≥5 像素的行有 220 行
#   (即完整的设备竖直范围);而最初用灰<120 且≥8 像素时一行都找不到
#   —— 缩放后 bezel 被抗锯齿稀释,深色像素变少。判据太严会把「有设备」判成「没设备」。
DARK = 160
MIN_ROW = 5

BOUNDS = [("S1→S2", 120), ("S2→S3", 300), ("S3→S4", 540), ("S4→S5", 1500),
          ("S5→S6", 2700), ("S6→S7", 3780), ("S7→S8", 4560), ("S8→S9", 4950)]

p = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-i", FILM,
     "-vf", f"scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
    stdout=subprocess.PIPE,
)
assert p.stdout is not None

# 每帧:设备的竖直范围(深色行的首末)与设备中心 x(深色列的均值)
geo = {}
i = 0
while True:
    buf = p.stdout.read(N)
    if len(buf) < N:
        break
    a = np.frombuffer(buf, dtype=np.uint8).reshape(H, W)
    dark = a < DARK
    rows = np.where(dark.sum(axis=1) >= MIN_ROW)[0]
    if rows.size:
        cols = np.where(dark.sum(axis=0) >= MIN_ROW)[0]
        geo[i] = (int(rows[0]), int(rows[-1]), int(cols.mean()) if cols.size else -1)
    else:
        geo[i] = None
    i += 1
p.stdout.close()
p.wait()


def span(f):
    g = geo.get(f)
    return None if g is None else (g[1] - g[0])


lines = [
    "=" * 78,
    "跨段连续性:切点处设备框是否跳变",
    "=" * 78,
    "",
    "  段内相邻帧的「设备高度」正常变化量(作为参照基线):",
]
# 基线:各段内部(避开切点)的相邻帧高度变化
deltas = []
for f in range(1, len(geo)):
    if geo.get(f) and geo.get(f - 1):
        near_cut = any(abs(f - b) <= 6 for _, b in BOUNDS)
        if not near_cut:
            deltas.append(abs(geo[f][1] - geo[f][0] - (geo[f - 1][1] - geo[f - 1][0])))
p50 = float(np.percentile(deltas, 50))
p99 = float(np.percentile(deltas, 99))
lines.append(f"    中位 {p50:.1f}px   99% 分位 {p99:.1f}px   最大 {max(deltas)}px")

lines += ["", "  切点处(前一帧 → 后一帧):"]
worst = 0
for tag, f in BOUNDS:
    a, b = geo.get(f - 1), geo.get(f)
    if a is None or b is None:
        lines.append(f"    {tag} f{f}: 有一帧找不到设备框(可能全空/全幅排版)")
        continue
    da = abs(b[1] - b[0] - (a[1] - a[0]))
    dc = abs(b[2] - a[2]) if (a[2] >= 0 and b[2] >= 0) else -1
    worst = max(worst, da)
    flag = ""
    if da > max(p99, 12):
        flag = "  ★ 高度跳变超过段内基线"
    elif da <= p99:
        flag = "  ✓ 与段内变化同量级"
    lines.append(f"    {tag} f{f-1}→f{f}: 高度 {a[1]-a[0]} → {b[1]-b[0]} "
                 f"(差 {da}px)  水平中心 {a[2]}→{b[2]}{flag}")

lines += [
    "",
    f"  最大高度跳变: {worst}px",
    "  判读:切点处的变化若与段内相邻帧同量级,说明是**平滑衔接**;",
    "        若显著更大,则是一次「设备瞬移」。",
]

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
