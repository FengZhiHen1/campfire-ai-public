"""跨段连续性 v3:沿用**已验证可用的** bezel 检测法(与 bezel-scan.py 同法)。

★ 教训(v1/v2 都错在判据,不在代码):
    · v1「每行暗像素数 ≥5」→ 检出的是**文字**(设备缩小后左右 bezel 各仅约 2.6px,
      所以穿过设备的每一行也只有约 5 个暗像素,与文字行无法区分)。
      它报告「S1 设备高度 25px」——那是两行字,不是设备。
    · v2「连续暗像素 ≥50」→ 在 480px 缩放下,设备上/下 bezel 横条约 103px,
      按理能命中,但实测各切点前后都报「无设备框」,说明阈值/缩放仍不匹配。
    · v3 改用 bezel-scan.py 里**实测可用**的参数:1920 原分辨率、
      水平中心窄条(x 560–720)、灰 <100、每行 ≥20 个暗像素。
      那套参数此前成功量出过 6 个镜头的边距(11–29px),是可信的。

★ 并且先想清「什么才算缺陷」:
    硬切处设备换位置/换大小是**正常剪辑**(换景别)。真正的缺陷是
    **微小到像故障**的跳变(1–12px),读起来是「抖了一下」。
    本脚本按幅度分类,不一律报警。
"""
import subprocess
from pathlib import Path

import numpy as np

FILM = "marketing/promo-shotcraft/out/promo-v16.mp4"
OUT = Path(".tmp/continuity3.txt")
FW, FH = 1920, 1080
X0, X1 = 560, 720          # 水平中心窄条(与 bezel-scan.py 一致)
CW = X1 - X0
N = CW * FH
DARK = 100
MIN_ROW = 20

BOUNDS = [("S1→S2", 120), ("S2→S3", 300), ("S3→S4", 540), ("S4→S5", 1500),
          ("S5→S6", 2700), ("S6→S7", 3780), ("S7→S8", 4560), ("S8→S9", 4950)]

p = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-i", FILM,
     "-vf", f"crop={CW}:{FH}:{X0}:0,format=gray", "-f", "rawvideo", "-"],
    stdout=subprocess.PIPE,
)
assert p.stdout is not None
geo = {}
i = 0
while True:
    buf = p.stdout.read(N)
    if len(buf) < N:
        break
    a = np.frombuffer(buf, dtype=np.uint8).reshape(FH, CW)
    rows = np.where((a < DARK).sum(axis=1) >= MIN_ROW)[0]
    geo[i] = (int(rows[0]), int(rows[-1])) if rows.size else None
    i += 1
p.stdout.close()
p.wait()

have = sum(1 for v in geo.values() if v)
lines = [
    "=" * 78,
    "跨段连续性:切点处设备框是否跳变(v3,沿用已验证的检测法)",
    "=" * 78,
    "",
    f"  检测参数:crop x{X0}-{X1}、灰<{DARK}、每行≥{MIN_ROW} 暗像素",
    f"  检出设备框的帧:{have}/{len(geo)}",
    "",
]

# 段内基线:同一段内相邻帧的高度变化(避开切点)
seg_deltas = []
for f in range(1, len(geo)):
    a, b = geo.get(f - 1), geo.get(f)
    if a and b and not any(abs(f - x) <= 8 for _, x in BOUNDS):
        seg_deltas.append(abs((b[1] - b[0]) - (a[1] - a[0])))
if seg_deltas:
    lines.append(f"  段内相邻帧高度变化: 中位 {np.median(seg_deltas):.0f}px  "
                 f"99% {np.percentile(seg_deltas, 99):.0f}px  最大 {max(seg_deltas)}px")
    lines.append("")

lines.append("  切点(取前一段淡出**之前**的帧,即 f−15,因为末帧已淡到 6%):")
lines.append("    边界        前帧(f−15)          后帧(f)            高度差")
report = []
for tag, f in BOUNDS:
    a, b = geo.get(f - 15), geo.get(f)
    sa = f"({a[0]:4},{a[1]:4}) 高{a[1]-a[0]:4}" if a else "无设备框(满幅排版段)"
    sb = f"({b[0]:4},{b[1]:4}) 高{b[1]-b[0]:4}" if b else "无设备框(满幅排版段)"
    dh = None
    if a and b:
        dh = (b[1] - b[0]) - (a[1] - a[0])
    lines.append(f"    {tag:9} {sa:22} {sb:22} {('' if dh is None else f'{dh:+4}')}")
    if dh is not None:
        report.append((tag, dh))

lines += [
    "",
    "  ── 判读 ──────────────────────────────────────────",
]
if not report:
    lines.append("    无法比较(切点两侧至少一侧是满幅排版段,本就没有设备框)。")
small = [(t, d) for t, d in report if 0 < abs(d) <= 12]
large = [(t, d) for t, d in report if abs(d) > 12]
if small:
    lines.append("    ★ 「微小跳变」(1–12px,读起来像故障):")
    for t, d in small:
        lines.append(f"        {t}: {d:+}px")
else:
    lines.append("    ✓ 没有「微小到像故障」的高度跳变")
if large:
    lines.append("    · 明显变化(>12px)= 正常的换景别,不是缺陷:")
    for t, d in large:
        lines.append(f"        {t}: {d:+}px")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
