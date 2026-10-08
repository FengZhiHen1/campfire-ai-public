"""跨段连续性 v2:用「长水平暗条」精确定位设备框,再看切点是否跳变。

★ v1 为什么失败:v1 用「每行暗像素数 ≥5」找设备。但设备框在缩放到 480 宽后,
  左右两条竖直 bezel 各只有约 2.6px,所以**穿过设备的每一行**都只有约 5 个暗像素;
  而文字行同样有 5+ 个暗像素 ⇒ 检测到的是文字,不是设备(v1 报 S1「高度 25px」)。

  正确的签名:设备的**上/下 bezel 是两条长水平暗条**(宽约设备宽 ≈103px)。
  ⇒ 判据改为「该行存在 ≥50px 的**连续**暗像素段」,这只有 bezel 横条满足。

  这是本项目第五次同型错误:**判据与对象不匹配**(v1 找暗像素「数量」,
  而设备的特征是暗像素「连续长度」)。前四次记在 verify/README.md。

★ 另一个必须先想清的问题:**切点处的跳变本身不是缺陷**。
  硬切从全景到中景是正常剪辑语言。真正算缺陷的是**微小的、看起来像故障的**跳变
  (如 2–10px) —— 它读起来是「抖了一下」而不是「换了个景别」。
  所以本脚本报数值,并按「是否小到像故障」给出判断,而不是一律报错。
"""
import subprocess
from pathlib import Path

import numpy as np

FILM = "marketing/promo-shotcraft/out/promo-v16.mp4"
OUT = Path(".tmp/continuity2.txt")
W, H = 480, 270
N = W * H
DARK = 165
MIN_RUN = 50      # 连续暗像素长度 ≥ 这个才算 bezel 横条

BOUNDS = [("S1→S2", 120), ("S2→S3", 300), ("S3→S4", 540), ("S4→S5", 1500),
          ("S5→S6", 2700), ("S6→S7", 3780), ("S7→S8", 4560), ("S8→S9", 4950)]


def longest_run(row: np.ndarray) -> int:
    """该行最长的连续 True 段长度。"""
    best = cur = 0
    for v in row:
        if v:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return best


p = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-i", FILM, "-vf", f"scale={W}:{H},format=gray",
     "-f", "rawvideo", "-"],
    stdout=subprocess.PIPE,
)
assert p.stdout is not None
geo = {}
i = 0
while True:
    buf = p.stdout.read(N)
    if len(buf) < N:
        break
    a = np.frombuffer(buf, dtype=np.uint8).reshape(H, W)
    dark = a < DARK
    runs = np.array([longest_run(r) for r in dark])
    bars = np.where(runs >= MIN_RUN)[0]
    if bars.size >= 2:
        # 上横条 = 第一个长条;下横条 = 最后一个长条
        geo[i] = (int(bars[0]), int(bars[-1]), int(bars.max()))
    else:
        geo[i] = None
    i += 1
p.stdout.close()
p.wait()

lines = [
    "=" * 80,
    "跨段连续性:切点处设备框是否跳变(v2,长暗条判据)",
    "=" * 80,
    "",
    f"  暗阈值 {DARK},bezel 横条判据:连续暗像素 ≥ {MIN_RUN}",
    "",
]

# 段内基线(设备高度 = 下横条 y − 上横条 y)
seg_deltas = []
for f in range(1, len(geo)):
    a, b = geo.get(f - 1), geo.get(f)
    if a and b and not any(abs(f - x) <= 8 for _, x in BOUNDS):
        seg_deltas.append(abs((b[1] - b[0]) - (a[1] - a[0])))
if seg_deltas:
    lines.append(f"  段内相邻帧「设备高度」变化: 中位 {np.median(seg_deltas):.0f}px  "
                 f"99% {np.percentile(seg_deltas, 99):.0f}px  最大 {max(seg_deltas)}px")
else:
    lines.append("  (段内基线:无有效样本)")

lines += ["", "  切点:", "    边界        前帧设备(上,下,高)   后帧设备        高度差  水平中心差"]
for tag, f in BOUNDS:
    a, b = geo.get(f - 1), geo.get(f)
    if not a:
        lines.append(f"    {tag:9} 前帧无设备框(满幅排版段)")
        continue
    if not b:
        lines.append(f"    {tag:9} 后帧无设备框(满幅排版段)  前帧高 {a[1] - a[0]}")
        continue
    dh = (b[1] - b[0]) - (a[1] - a[0])
    lines.append(f"    {tag:9} ({a[0]:3},{a[1]:3},{a[1]-a[0]:3})        "
                 f"({b[0]:3},{b[1]:3},{b[1]-b[0]:3})       {dh:+4}")

lines += [
    "",
    "  判读原则(重要):",
    "    · 硬切处设备换位置/换大小**本身不是缺陷** —— 那是正常的剪辑语言(换景别)。",
    "    · 真正的缺陷是**微小到像故障**的跳变(约 1–10px),它读起来是「抖了一下」。",
    "    · 所以下面按「变化幅度」分类,而不是一律报警。",
    "",
]

small = []
for tag, f in BOUNDS:
    a, b = geo.get(f - 1), geo.get(f)
    if a and b:
        dh = abs((b[1] - b[0]) - (a[1] - a[0]))
        if 0 < dh <= 12:
            small.append((tag, dh))
if small:
    lines.append("  ★ 存在「微小跳变」(1–12px,读起来像故障):")
    for tag, dh in small:
        lines.append(f"      {tag}: 高度差 {dh}px")
else:
    lines.append("  ✓ 没有「微小到像故障」的跳变(切点处要么无设备,要么变化明显)")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
