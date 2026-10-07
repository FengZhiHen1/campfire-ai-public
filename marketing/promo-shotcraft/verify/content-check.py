"""第三次修判据:用「相对本帧主色的偏离量」衡量内容,而不是绝对灰度。

★★ 前两次判据各错一边,记录如下(这是同一类错误的第 N 次):
   ① `uniform-check.py`「整帧 std < 0.5」 —— **太弱**。
      纸面自带极轻渐变,主体全部淡出后 std 仍有 1.0–7.5,
      于是 f1493–f1499(设备框整个消失)被判为「不是空帧」。
   ② `ink-blank.py`「深色像素 < 20(灰度<140)」 —— **太强**。
      暖灰文字(约 150–190 灰)在米色底上**清晰可见**,却不算「深色」,
      于是 f296(S2 的「是没人商量。」)、f5051(S9 的免责句)被误报为空帧。
      实测:它报出 151 帧,但抽帧目视其中多数明显有内容。

   两次错的**根因相同**:拿一个与「观众能否看到内容」不对应的量——
   一次只看方差、一次只看绝对亮度。

   正确的量:**本帧主色(背景)之外,有多少像素偏离它**。
   这同时覆盖:深色文字、浅色文字、彩色元素、图形,与极性强弱无关。
"""
import subprocess
from pathlib import Path

import numpy as np
from _timeline import RANGES

FILM = "marketing/promo-shotcraft/out/promo-v16.mp4"
OUT = Path(".tmp/content-check.txt")
W, H = 320, 180
N = W * H
DELTA = 12      # 偏离本帧主色多少灰度算「可见内容」
MIN_PIX = 30    # 少于此像素数 = 画面无可见内容

p = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-i", FILM, "-vf", f"scale={W}:{H},format=gray",
     "-f", "rawvideo", "-"],
    stdout=subprocess.PIPE,
)
assert p.stdout is not None
rows = []
idx = 0
while True:
    buf = p.stdout.read(N)
    if len(buf) < N:
        break
    a = np.frombuffer(buf, dtype=np.uint8)
    # 主色 = 直方图峰值所在灰度(背景)
    hist = np.bincount(a, minlength=256)
    bg = int(np.argmax(hist))
    dev = int((np.abs(a.astype(np.int16) - bg) > DELTA).sum())
    rows.append((idx, float(a.std()), bg, dev))
    idx += 1
p.stdout.close()
p.wait()

# 镜头区间真源(见 _timeline.py)
SHOTS = RANGES
def shot_of(f):
    for n, a, b in SHOTS:
        if a <= f < b:
            return n
    return "?"


empty = [r[0] for r in rows if r[3] < MIN_PIX]
devs = [r[3] for r in rows]

lines = [
    "=" * 76,
    "内容的第三版判据:偏离本帧主色的像素数",
    "=" * 76,
    "",
    f"  偏离阈值 {DELTA} 灰阶;「无可见内容」= 偏离像素 < {MIN_PIX}",
    f"  逐帧扫描 {len(rows)} 帧",
    "",
    f"  三种口径对比:",
    f"    ① std < 0.5            : {sum(1 for r in rows if r[1] < 0.5):4} 帧   (太弱,漏报)",
    f"    ② 深色像素 < 20         : {151:4} 帧   (太强,误报;见 ink-blank.py)",
    f"    ③ 偏离主色 < {MIN_PIX}       : **{len(empty):4} 帧**  ← 本判据",
    "",
    f"  全片偏离量分布: 最小 {min(devs)}  1% {int(np.percentile(devs,1))}  "
    f"中位 {int(np.median(devs))}  99% {int(np.percentile(devs,99))}",
    "",
]

if empty:
    runs, s = [], empty[0]
    for a, b in zip(empty, empty[1:]):
        if b != a + 1:
            runs.append((s, a))
            s = b
    runs.append((s, empty[-1]))
    lines.append(f"  无可见内容的区间({len(runs)} 段,共 {len(empty)} 帧 = {len(empty)/30:.2f}s):")
    for a, b in runs:
        lines.append(f"    f{a:5}–f{b:<5} {(b-a+1)/30:5.2f}s  {shot_of(a)}"
                     f"   偏离 {min(devs[a:b+1])}–{max(devs[a:b+1])}")
else:
    lines.append("  ✓ 没有任何一帧「无可见内容」")

lines += [
    "",
    "  说明:这些区间位于段边界,是**交叉淡入淡出**的过程帧。",
    "        淡出到接近纯底是过渡的正常形态;要判断的是**持续多久**:",
    "        观众能感知到「这半秒是空的」的阈值约 0.3–0.5s。",
]

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
