"""全片扫设备框边距 —— 复核终检的「最小 10px」vs 我的「≥17px」。

★ 为什么我上一版错了(终检指出):
  我只抽了 6 帧,且**按「推近最大处」选帧**。但边距的最小值并不出现在推近最大处 ——
  它出现在 `pushCamera` 的 **ty 摆动极值**上(camera.ts 里 ty 叠加了正弦位移)。
  于是「口径对、取样错」,结论偏乐观。这与上一轮「只读 PSNR 最后一行」是同一类错误。

本脚本改为**每帧都扫**(不是抽样):把设备屏水平中心地带裁成窄条,逐帧找
最上/最下的深色(bezel)像素,得到真实的上下边距及其最小值。
"""
import subprocess
import sys
from pathlib import Path

import numpy as np

# ★★ 默认路径必须是**真实存在**的文件。独立复核 P1 指出:
#    此前默认 `out/promo-v16-new.mp4`(某个临时渲染名,早已不存在),
#    而 ACCEPTANCE.md 把它列为「可复跑门禁」且不带参数 ⇒ 逐字照跑会得到
#    「扫描帧数 0 / 全片最小边距 **9999px**」并 **exit 0**。
#    那是**永远不会失败的门禁**(AGENTS.md 明令禁止),比没有门禁更危险。
_DEFAULT = "marketing/promo-shotcraft/out/promo-v16.mp4"
MP4 = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT
if not Path(MP4).exists():
    raise SystemExit(f"★ 找不到成片: {MP4}\n  用法: uv run python {sys.argv[0]} <成片路径>")
OUT = Path(".tmp/bezel-scan.txt")

W, H = 1920, 1080
# 只取水平中心地带(设备居中于 x=640;tx 摆动幅度远小于此宽度)
X0, X1 = 560, 720
CW = X1 - X0

SHOTS = [("S3", 300, 540), ("S4", 540, 1500), ("S5", 1500, 2700),
         ("S6", 2700, 3780), ("S7", 3780, 4560), ("S8", 4560, 4950)]

# 逐帧输出灰度窄条
proc = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-i", MP4,
     "-vf", f"crop={CW}:{H}:{X0}:0,format=gray",
     "-f", "rawvideo", "-"],
    stdout=subprocess.PIPE,
)
assert proc.stdout is not None

DARK = 100  # bezel 灰度约 45;纸色约 245
frame_bytes = CW * H
mins = {s: (9999, None) for s, _, _ in SHOTS}
per_frame = []
fidx = 0

while True:
    buf = proc.stdout.read(frame_bytes)
    if len(buf) < frame_bytes:
        break
    a = np.frombuffer(buf, dtype=np.uint8).reshape(H, CW)
    dark_rows = np.where((a < DARK).sum(axis=1) >= 10)[0]
    if dark_rows.size:
        top = int(dark_rows[0])
        bot = int(dark_rows[-1])
        gap_t = top
        gap_b = H - 1 - bot
        per_frame.append((fidx, gap_t, gap_b))
        for sid, s0, s1 in SHOTS:
            if s0 <= fidx < s1:
                m = min(gap_t, gap_b)
                if m < mins[sid][0]:
                    mins[sid] = (m, fidx)
                break
    fidx += 1

proc.stdout.close()
proc.wait()

# ★ 采不到帧 = 失败,不是「0 帧也通过」。
#   独立复核用这个脚本得到过「扫描帧数 0 / 最小边距 9999px / exit 0」——
#   一个永远不会失败的检查。零结果必须报错。
if fidx == 0:
    raise SystemExit(
        f"★ 扫不到任何帧({MP4})—— 不要把它当成通过。\n"
        f"  检查 ffmpeg 是否可用、路径是否正确。"
    )
if not per_frame:
    raise SystemExit(
        "★ 一帧都没检出深色 bezel —— 不要把它当成『无贴边』。\n"
        "  检查 crop 参数与 DARK 阈值是否匹配当前成片。"
    )

lines = [
    "=" * 76,
    "设备框边距:全片逐帧扫描",
    "=" * 76,
    f"  成片: {MP4}",
    f"  扫描帧数: {fidx}",
    "",
    "  段    最小边距   出现在      我上一版的结论",
]
PREV = {"S3": "33/23", "S4": "23/25", "S5": "39/33", "S6": "17/21", "S7": "42/30", "S8": "29/26"}
for sid, _, _ in SHOTS:
    m, f = mins[sid]
    lines.append(f"  {sid}     {m:4}px    f{f}      {PREV[sid]}(那 6 帧的实测值)")

allmin = min(m for m, _ in mins.values())
lines.append("")
lines.append(f"  全片最小边距: {allmin}px")
lines.append("")
lines.append("  判据回顾:")
lines.append("    · 硬约束「背景页面永不超过 1.3 倍」—— 与边距无关,另行验证")
lines.append("    · 「不贴边」我采用 ≥12px。若最小边距 < 12px,则该表述需要修正")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
