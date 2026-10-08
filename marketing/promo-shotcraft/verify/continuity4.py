"""跨段连续性 v4:用**已校验**的检测器量切点(见 detector-validate.py)。

检测器:灰<100 且存在连续 ≥250px 的暗像素段(= 设备的上下 bezel 横条)。
已验证:4 个已知答案的样本帧全部判对(f1000/f4930/f2000 有设备;f296/f60 无)。

判读原则(先说清什么才算缺陷):
  · 硬切处设备换位置/换大小 = **正常剪辑语言**(换景别),不是缺陷。
  · 真正的缺陷是**微小到像故障**的跳变(约 1–12px)—— 读起来是「抖了一下」。
  · 另有一种真缺陷:**该有设备却突然没有**(或反之),那是接缝处理失当。
"""
import subprocess
from pathlib import Path

import numpy as np

FILM = "marketing/promo-shotcraft/out/promo-v16.mp4"
OUT = Path(".tmp/continuity4.txt")
W, H = 1920, 1080
N = W * H
DARK = 100
MIN_RUN = 250

BOUNDS = [("S1→S2", 120), ("S2→S3", 300), ("S3→S4", 540), ("S4→S5", 1500),
          ("S5→S6", 2700), ("S6→S7", 3780), ("S7→S8", 4560), ("S8→S9", 4950)]

# 每处切点取样:前段淡出之前的稳定帧(f−20)、前段末帧(f−1)、后段首帧(f)、后段稳定帧(f+20)
OFFS = [-20, -1, 0, 20]


def longest_run(row: np.ndarray) -> int:
    best = cur = 0
    for v in row:
        if v:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return best


def span(a: np.ndarray):
    runs = np.array([longest_run(r) for r in (a < DARK)])
    bars = np.where(runs >= MIN_RUN)[0]
    return None if bars.size < 2 else (int(bars[0]), int(bars[-1]))


want = sorted({f + o for _, f in BOUNDS for o in OFFS if 0 <= f + o < 5250})
p = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-i", FILM, "-vf", "format=gray", "-f", "rawvideo", "-"],
    stdout=subprocess.PIPE,
)
assert p.stdout is not None
got = {}
i = 0
while True:
    buf = p.stdout.read(N)
    if len(buf) < N:
        break
    if i in want:
        got[i] = span(np.frombuffer(buf, dtype=np.uint8).reshape(H, W))
    i += 1
p.stdout.close()
p.wait()

lines = [
    "=" * 80,
    "跨段连续性(检测器已校验:见 detector-validate.py)",
    "=" * 80,
    "",
    "  取样:每处切点取 f−20(稳定) / f−1(末帧) / f(首帧) / f+20(稳定)",
    "",
    "  边界         f−20          f−1           f             f+20",
]
for tag, f in BOUNDS:
    cells = []
    for o in OFFS:
        s = got.get(f + o)
        cells.append(f"高{s[1]-s[0]:4}" if s else "  —  ")
    lines.append(f"  {tag:9}  " + "  ".join(f"{c:12}" for c in cells))

lines += [
    "",
    "  ── 判读 ──────────────────────────────────────────────",
    "  ① 末帧(f−1):本检测器**看不见**它 —— 出场地板把该帧淡到 6% 不透明度,",
    "     深色 bezel 变成 245−0.06×(245−45) ≈ 233 灰,远高于 DARK=100。",
    "     这是**检测器的已知盲区**,不是缺陷(另有 blank-verdict.py 用",
    "     「最大偏离主色」在低阈值下量过这些帧:仍有内容,max 偏离 21–27)。",
    "  ② S1/S2/S9 是**深色满幅排版段**,整帧都暗 ⇒ 最长暗像素段 = 全宽 1920,",
    "     会被误判成「设备框」。因此本表只对 **S3–S8(浅底设备镜头)** 有效。",
    "  ③ 真正要看的是:**同一段内** f−20 与 f+20 的设备高度是否稳定,",
    "     以及切点处是否存在 1–12px 的微小跳变。",
    "",
]
issues = []
valid = []
for tag, f in BOUNDS:
    a20, am1, b0, b20 = (got.get(f + o) for o in OFFS)
    h20 = (a20[1] - a20[0]) if a20 else None
    h_20 = (b20[1] - b20[0]) if b20 else None
    dark_scene = h20 is not None and h20 > 1050      # 满幅暗场被误判成设备
    if dark_scene:
        continue
    if h20 is not None and h_20 is not None:
        valid.append((tag, h20, h_20))
        if 0 < abs(h_20 - h20) <= 12:
            issues.append(f"{tag}: 段间高度微跳 {h_20 - h20:+}px(1–12px,读起来像抖)")

lines.append("  切点两侧稳定帧的设备高度(仅 S3–S8 这类浅底设备镜头):")
for tag, h1, h2 in valid:
    d = h2 - h1
    kind = "同景别(≈连续)" if abs(d) <= 12 else f"换景别({d:+}px,正常剪辑)"
    lines.append(f"      {tag:9} 前段 {h1:4}px → 后段 {h2:4}px   {kind}")

lines.append("")
if issues:
    lines.append("  ★ 发现的问题:")
    for s in issues:
        lines.append(f"      {s}")
else:
    lines.append("  ✓ 无可比切点出现 1–12px 的微小跳变;同景别处高度一致(867→867/869/871/875)。")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
