"""决定性问题:每段末尾「实际看不见」持续多久?

★ 为什么要这个量:
  前面几个判据都在数「空帧个数」,但**1 帧空(33ms)与 1 秒空**是完全不同的事。
  观众感知的阈值在 0.3–0.5s 量级。所以正确的量是**持续时间**,
  而且判据不该用绝对阈值,应当用「相对该段正常帧的内容量」。

  判据:内容量 < 该段中位数的 10% ⇒ 该帧「实际看不见」。
"""
import subprocess
from pathlib import Path

import numpy as np

FILM = "marketing/promo-shotcraft/out/promo-v16.mp4"
OUT = Path(".tmp/invisible-tail.txt")
W, H = 320, 180
N = W * H
FPS = 30

SHOTS = [("S1", 0, 120), ("S2", 120, 300), ("S3", 300, 540), ("S4", 540, 1500),
         ("S5", 1500, 2700), ("S6", 2700, 3780), ("S7", 3780, 4560),
         ("S8", 4560, 4950), ("S9", 4950, 5250)]

p = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-i", FILM, "-vf", f"scale={W}:{H},format=gray",
     "-f", "rawvideo", "-"],
    stdout=subprocess.PIPE,
)
assert p.stdout is not None
content = []
while True:
    buf = p.stdout.read(N)
    if len(buf) < N:
        break
    a = np.frombuffer(buf, dtype=np.uint8)
    bg = int(np.argmax(np.bincount(a, minlength=256)))
    content.append(int((np.abs(a.astype(np.int16) - bg) > 12).sum()))
p.stdout.close()
p.wait()

lines = [
    "=" * 80,
    "每段末尾「实际看不见」的持续时间",
    "=" * 80,
    "",
    "  判据:该帧内容量 < 本段中位内容量的 10%",
    "",
    "  段    中位内容量   末尾连续不可见帧数   时长      开始帧",
]
worst = 0.0
for sid, a, b in SHOTS:
    seg = content[a:b]
    med = float(np.median(seg))
    thr = med * 0.10
    # 从末尾往回数连续不可见帧
    n = 0
    for v in reversed(seg):
        if v < thr:
            n += 1
        else:
            break
    dur = n / FPS
    worst = max(worst, dur)
    lines.append(f"  {sid}   {int(med):8}   {n:18}   {dur:5.2f}s   f{b - n}")

lines += [
    "",
    f"  最长的一段: {worst:.2f}s",
    "",
    "  判读:",
]
if worst >= 0.5:
    lines.append(f"    ★ 有段落末尾不可见 ≥0.5s ⇒ 观众能感知到「空了一下」,建议修")
elif worst >= 0.3:
    lines.append(f"    · 最长 {worst:.2f}s,处于 0.3–0.5s 边界 ⇒ 临界,可修可不修")
else:
    lines.append(f"    ✓ 最长 {worst:.2f}s < 0.3s ⇒ 低于感知阈值,属淡出尾声")

lines += [
    "",
    "  参照:本片全片中位内容量 = " + str(int(np.median(content))),
]

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
