"""用「内容密度」而非「灰度标准差」找空帧 —— 修正判据本身。

★ 为什么原判据漏了:
  `uniform-check.py` 用「整帧灰度标准差 < 0.5」。但纸面背景自带极轻微的渐变/暗角,
  即使**画面主体完全消失**,标准差仍有 1.0–7.5。于是 f1493–f1499(设备框整体淡出、
  屏内无任何深色像素)被判为「不是空帧」——**判据的分辨率不够**。

  这与本项目反复出现的错误同型:拿一个分辨率不够的度量去下强结论。
  更贴合「观众看到空画面」的判据是**深色内容的绝对量**:
  正常帧有手机 bezel、文字等大量深色像素;空帧应当是接近 0。
"""
import subprocess
from pathlib import Path

import numpy as np

FILM = "marketing/promo-shotcraft/out/promo-v16.mp4"
OUT = Path(".tmp/ink-blank.txt")
W, H = 320, 180
N = W * H
DARK = 140          # 深色阈值(bezel ≈45,正文 ≈60-90,纸 ≈245)
MIN_INK = 20        # 少于此像素数 = 「画面无主体」

p = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-i", FILM, "-vf", f"scale={W}:{H},format=gray",
     "-f", "rawvideo", "-"],
    stdout=subprocess.PIPE,
)
assert p.stdout is not None
stds, inks = [], []
while True:
    buf = p.stdout.read(N)
    if len(buf) < N:
        break
    a = np.frombuffer(buf, dtype=np.uint8).reshape(H, W)
    stds.append(float(a.std()))
    inks.append(int((a < DARK).sum()))
p.stdout.close()
p.wait()

SHOTS = [("S1", 0, 120), ("S2", 120, 300), ("S3", 300, 540), ("S4", 540, 1500),
         ("S5", 1500, 2700), ("S6", 2700, 3780), ("S7", 3780, 4560),
         ("S8", 4560, 4950), ("S9", 4950, 5250)]


def shot_of(f):
    for n, a, b in SHOTS:
        if a <= f < b:
            return n
    return "?"


empty_by_ink = [f for f, k in enumerate(inks) if k < MIN_INK]
empty_by_std = [f for f, s in enumerate(stds) if s < 0.5]

lines = [
    "=" * 74,
    "空帧复检:内容密度口径 vs 灰度标准差口径",
    "=" * 74,
    "",
    f"  深色阈值 {DARK},「无主体」判据:深色像素 < {MIN_INK}",
    "",
    f"  ① 灰度标准差口径(std<0.5):     {len(empty_by_std)} 帧",
    f"  ② 内容密度口径(深色<{MIN_INK}):  **{len(empty_by_ink)} 帧**",
    "",
]

if empty_by_ink:
    # 归并连续区间
    runs, s = [], empty_by_ink[0]
    for a, b in zip(empty_by_ink, empty_by_ink[1:]):
        if b != a + 1:
            runs.append((s, a))
            s = b
    runs.append((s, empty_by_ink[-1]))
    lines.append(f"  空帧区间({len(runs)} 段):")
    for a, b in runs:
        lines.append(f"    f{a:5}–f{b:<5} {(b - a + 1) / 30:5.2f}s  {shot_of(a)}"
                     f"   std {min(stds[a:b+1]):.2f}–{max(stds[a:b+1]):.2f}")
    lines += [
        "",
        "  ★ 这些帧在**灰度标准差口径下全部通过**(std 都 > 0.5),",
        "    但画面上**没有任何深色主体** —— 观众看到的是一片近乎纯色的纸面。",
        "    ⇒ 原判据「0/5250 空帧」是**低估**:它只找到了「整屏单色」,",
        "      漏掉了「单色 + 极轻渐变、但主体已全部淡出」。",
    ]

# 顺便看全片 ink 的分布,确认 20 这个阈值没有把正常帧误判
lines += [
    "",
    "  全片内容密度分布:",
    f"    最小 {min(inks)}   1% 分位 {int(np.percentile(inks, 1))}   "
    f"中位 {int(np.median(inks))}   99% 分位 {int(np.percentile(inks, 99))}",
]

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
