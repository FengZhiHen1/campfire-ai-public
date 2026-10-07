"""决定性测量:那些「偏离<30」的帧,到底是真的**完全均匀**,还是**内容还在但极淡**?

★ 为什么必须测这个:
  上面两个口径都用了「阈值 + 计数」,而阈值会把「极淡但存在」的内容算成 0。
  例如淡出到 opacity=0.03 时,深色文字在米底上的偏离只有约 5 个灰阶
  (245 − 0.03×(245−60) ≈ 239.5),低于任何合理阈值。

  区分这两者对结论影响很大:
    · 真·完全均匀  ⇒ 那一帧什么都没有,是硬缺陷(哪怕只有 33ms)
    · 极淡但存在  ⇒ 观众同样看不见,但成因是淡出尾声,属正常过渡

  判据:直接看**最大偏离量**(不受阈值影响)。
"""
import subprocess
from pathlib import Path

import numpy as np

FILM = "marketing/promo-shotcraft/out/promo-v16.mp4"
OUT = Path(".tmp/uniform-precision.txt")
W, H = 320, 180
N = W * H

# 可疑帧 + 其两侧邻居
SUSPECT = [1499, 2699, 3779, 4559, 4949, 5249, 0, 141, 142, 143]
NEIGH = [1497, 1498, 1500, 2698, 2700, 3778, 3780, 4558, 4560, 4948, 4950,
         5248, 1, 2, 139, 140, 144, 145]
want = set(SUSPECT) | set(NEIGH)

p = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-i", FILM, "-vf", f"scale={W}:{H},format=gray",
     "-f", "rawvideo", "-"],
    stdout=subprocess.PIPE,
)
assert p.stdout is not None
res = {}
i = 0
while True:
    buf = p.stdout.read(N)
    if len(buf) < N:
        break
    if i in want:
        a = np.frombuffer(buf, dtype=np.uint8).astype(np.int16)
        bg = int(np.argmax(np.bincount(a.astype(np.uint8), minlength=256)))
        dev = np.abs(a - bg)
        res[i] = (bg, int(dev.max()), int((dev > 12).sum()),
                  int(a.min()), int(a.max()),
                  int(np.percentile(a, 1)), int(np.percentile(a, 99)))
    i += 1
p.stdout.close()
p.wait()

lines = [
    "=" * 88,
    "精测:可疑帧是「完全均匀」还是「极淡但存在」",
    "=" * 88,
    "",
    "  帧     主色  最大偏离  偏离>12像素数   最小  最大   P1   P99   判定",
]
for f in sorted(res):
    bg, mx, cnt, lo, hi, p1, p99 = res[f]
    if mx <= 1:
        verdict = "★ 完全均匀(真空白)"
    elif mx <= 8:
        verdict = "极淡内容(不可见)"
    else:
        verdict = "有可见内容"
    tag = " ←可疑" if f in SUSPECT else ""
    lines.append(f"  f{f:<5} {bg:4}  {mx:7}  {cnt:11}  {lo:4} {hi:4} {p1:4} {p99:4}   {verdict}{tag}")

lines += [
    "",
    "  判读要点:",
    "    · 「最大偏离 ≤1」= 整帧真的是单一颜色 ⇒ 该帧无任何内容",
    "    · 「最大偏离 2–8」= 内容还在,但淡到不可见(淡出尾声)",
]

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
