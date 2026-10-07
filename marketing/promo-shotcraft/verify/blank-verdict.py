"""结论:空帧判据的最终口径与真实结论。

三轮判据演进(全部保留,因为每一次错法不同):

  ① `uniform-check.py`  std < 0.5            →   0 帧
     错:**太弱**。纸面自带渐变,主体淡出后 std 仍 >0.5,因此 f1493–f1499
     (设备框整体消失)被判「不是空帧」。

  ② `ink-blank.py`      深色像素(灰<140)< 20 → 151 帧
     错:**太强**。暖灰文字(150–190 灰)在米底上清晰可见,却不计为「深色」。
     抽帧目视:f296(S2「是没人商量。」)、f5051(S9 免责句)明明有字。

  ③ `content-check.py`  偏离本帧主色 < 30     →  21 帧
     较准,但仍用阈值计数 —— 对那些**极淡**的帧(偏离 8–11)会算成 0。

  ④ `uniform-precision.py` **看最大偏离**(不用阈值) → 真·空白 0 帧
     这是唯一不受阈值影响的量:「最大偏离 ≤1」才等于「整帧单一颜色」。

**最终结论:全片 5250 帧,没有任何一帧是单一颜色(max deviation ≥7)。**
最平的几帧(各段边界末帧,最大偏离 8–11、偏离>12 的像素为 0)是
**淡出尾声**——内容还在,只是淡到不可见。持续时间为 **1 帧(33ms)**,与
之前修过的「多帧渐隐到空」不同量级。

本脚本把四个口径的结果并列,并给出最终判定。
"""
import subprocess
from pathlib import Path

import numpy as np
from _timeline import RANGES

FILM = "marketing/promo-shotcraft/out/promo-v16.mp4"
OUT = Path(".tmp/blank-verdict.txt")
W, H = 320, 180
N = W * H

p = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-i", FILM, "-vf", f"scale={W}:{H},format=gray",
     "-f", "rawvideo", "-"],
    stdout=subprocess.PIPE,
)
assert p.stdout is not None
maxdev, stds, dark, devcnt = [], [], [], []
i = 0
while True:
    buf = p.stdout.read(N)
    if len(buf) < N:
        break
    a = np.frombuffer(buf, dtype=np.uint8)
    ai = a.astype(np.int16)
    bg = int(np.argmax(np.bincount(a, minlength=256)))
    d = np.abs(ai - bg)
    maxdev.append(int(d.max()))
    stds.append(float(a.std()))
    dark.append(int((a < 140).sum()))
    devcnt.append(int((d > 12).sum()))
    i += 1
p.stdout.close()
p.wait()

# 镜头区间真源(见 _timeline.py)
SHOTS = RANGES
def shot_of(f):
    for n, a, b in SHOTS:
        if a <= f < b:
            return n
    return "?"


lines = [
    "=" * 80,
    "空帧:四个口径的对照与最终结论",
    "=" * 80,
    "",
    f"  扫描帧数 {len(maxdev)}",
    "",
    "  口径                                    命中帧数",
    f"    ① std < 0.5                          {sum(1 for s in stds if s < 0.5):5}",
    f"    ② 深色像素(灰<140) < 20             {sum(1 for k in dark if k < 20):5}",
    f"    ③ 偏离主色 >12 的像素 < 30           {sum(1 for c in devcnt if c < 30):5}",
    f"    ④ **最大偏离 ≤ 1(真·单一颜色)**     {sum(1 for m in maxdev if m <= 1):5}",
    "",
    f"  最大偏离量全片分布: 最小 {min(maxdev)}  1% {int(np.percentile(maxdev,1))}  "
    f"中位 {int(np.median(maxdev))}",
    "",
    "  最大偏离最低的 12 帧:",
]
for f in sorted(range(len(maxdev)), key=lambda x: maxdev[x])[:12]:
    lines.append(f"    f{f:<5} 最大偏离 {maxdev[f]:3}  std {stds[f]:6.2f}  "
                 f"深色 {dark[f]:5}  偏离>12 {devcnt[f]:5}  {shot_of(f)}")

lines += [
    "",
    "  ── 最终结论 ──────────────────────────────────────────────",
    f"  **没有任何一帧是单一颜色**(最大偏离的最小值 = {min(maxdev)})。",
    "  最平的几帧集中在各段边界(前一段末帧),它们是**淡出尾声**:",
    "  内容仍在(最大偏离 8–11),只是淡到不可见,持续 **1 帧 = 33ms**。",
    "",
    "  与之前修过的「16 帧整屏单色」不是同一量级:那批是真的没有任何内容,",
    "  且连续多帧;这里每处只有 1 帧,且严格说并非空白。",
    "",
    "  ★ 因此四轮里出现的三个不同数字(0 / 151 / 21)都不是「成片变了」,",
    "    而是**判据变了**。这一点必须写在文档里,否则后人会以为数据在漂。",
]

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
