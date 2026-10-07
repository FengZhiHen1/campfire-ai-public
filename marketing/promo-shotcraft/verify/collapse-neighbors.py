"""看空帧「两侧」有多满 —— 决定这个 1 帧凹陷是否可见。

逻辑:如果 f1499 是纯底(偏离 0),而 f1498 与 f1500 内容很满,
那就是「满 → 空 → 满」,单帧凹陷会读成一闪(**需要修**)。
如果邻居本来就已经很空(接近淡出尾声),那这个 0 是无感的(**可以不修**)。
"""
import subprocess
from pathlib import Path

import numpy as np

FILM = "marketing/promo-shotcraft/out/promo-v16.mp4"
OUT = Path(".tmp/collapse-neighbors.txt")

# 各段边界帧(前一段的最后一帧)
BOUNDARIES = [("S3→S4", 539, 540), ("S4→S5", 1499, 1500), ("S5→S6", 2699, 2700),
              ("S6→S7", 3779, 3780), ("S7→S8", 4559, 4560), ("S8→S9", 4949, 4950)]
S2_GAP = (140, 143)

W, H = 320, 180
N = W * H


def dev_at(frames: set[int]) -> dict[int, int]:
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", FILM, "-vf", f"scale={W}:{H},format=gray",
         "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE,
    )
    assert p.stdout is not None
    out, i = {}, 0
    while True:
        buf = p.stdout.read(N)
        if len(buf) < N:
            break
        if i in frames:
            a = np.frombuffer(buf, dtype=np.uint8)
            bg = int(np.argmax(np.bincount(a, minlength=256)))
            out[i] = int((np.abs(a.astype(np.int16) - bg) > 12).sum())
        i += 1
    p.stdout.close()
    p.wait()
    return out


want = set()
for _, a, b in BOUNDARIES:
    want |= {a - 2, a - 1, a, b, b + 1, b + 2}
want |= set(range(S2_GAP[0] - 3, S2_GAP[1] + 4))
# 首帧与末帧
want |= set(range(0, 4)) | set(range(5246, 5250))

d = dev_at(want)

lines = [
    "=" * 76,
    "空帧两侧的内容量(判断单帧凹陷是否可见)",
    "=" * 76,
    "",
    "  偏离主色的像素数(越大 = 内容越多;中位约 5174)",
    "",
    "  ① 各段边界(前一段末帧 / 后一段首帧):",
]
for name, a, b in BOUNDARIES:
    vals = [f"{f}:{d.get(f, '?')}" for f in (a - 2, a - 1, a, b, b + 1, b + 2)]
    lines.append(f"    {name}:  " + "  ".join(vals))
    lines.append(f"        {'':>12}↑末帧 {a}={d.get(a)}   首帧 {b}={d.get(b)}")

lines += ["", "  ② S2 内的空档 f140–f143:"]
lines.append("    " + "  ".join(f"{f}:{d.get(f, '?')}" for f in range(137, 148)))

lines += ["", "  ③ 首尾:"]
lines.append("    " + "  ".join(f"{f}:{d.get(f, '?')}" for f in range(0, 4)))
lines.append("    " + "  ".join(f"{f}:{d.get(f, '?')}" for f in range(5246, 5250)))

# 判读
lines += ["", "  ── 判读 ──────────────────────────────────────────"]
problems = []
for name, a, b in BOUNDARIES:
    pa, nb = d.get(a - 1, 0), d.get(b, 0)
    # 若末帧为 0/极小,而前一帧或后一帧很满 ⇒ 单帧凹陷
    if d.get(a, 0) < 30 and (pa > 800 or nb > 800):
        problems.append(f"{name}: 末帧 {a}=0 但邻居 {a-1}={pa} / {b}={nb}")

only_a = d.get(0, 0)
if only_a < 30:
    lines.append(f"    f0 = {only_a}:开场首帧几乎无内容(已知,仅准星起笔)")
if problems:
    lines.append("    ★ 以下边界存在「满→空→满」的单帧凹陷:")
    for p in problems:
        lines.append(f"       {p}")
    lines.append("      ⇒ 1 帧 = 33ms。在 30fps 下这是一次**单帧闪空**,")
    lines.append("        与之前修过的「多帧渐隐到空」是同类问题,只是更短。建议修。")
else:
    lines.append("    没有边界的空帧两侧同时很满 ⇒ 这些 0 属于淡出尾声,不可见。")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
