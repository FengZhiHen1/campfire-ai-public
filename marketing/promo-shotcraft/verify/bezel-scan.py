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
# ★★ P1 修复(2026-10-07):默认要求 S3–S8 六段**全部**测到;只分析片段时
#    必须显式写 --partial,且**落在片段范围内的段仍必须全部测到**。
#    旧版没有这道闸:传 S1 段(120 帧、画面里没有设备框)时六段全部保留哨兵,
#    输出「全片最小边距 9999px」并 exit 0。
PARTIAL = "--partial" in sys.argv[1:]
_ARGS = [a for a in sys.argv[1:] if a != "--partial"]
MP4 = _ARGS[0] if _ARGS else _DEFAULT
if not Path(MP4).exists():
    raise SystemExit(
        f"★ 找不到成片: {MP4}\n"
        f"  用法: uv run python {sys.argv[0]} [--partial] <成片路径>"
    )
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

# ★★ P1 修复(2026-10-07):**哨兵检查**。
#    `mins` 的初值是 (9999, None) 哨兵,而旧版**没有任何一行读它** ——
#    于是「一帧都没测到」与「边距很大」在输出上不可区分。
#    独立复核实测:`bezel-scan.py out/s1seg.mp4`(S1 段 120 帧,画面里没有设备框)
#    → 「扫描帧数 120 / 全片最小边距 9999px / exit 0」。
#    一段都没测到却判通过,正是 AGENTS.md 禁止的「永远不会失败的检查」。
missing = [sid for sid, _, _ in SHOTS if mins[sid][1] is None]
in_scope = [sid for sid, s0, _ in SHOTS if s0 < fidx]

if PARTIAL:
    # 显式声明「只分析片段」时才允许有段落在范围外,
    # 但**落在范围内的段必须全部测到**,否则仍是静默失明。
    if not in_scope:
        raise SystemExit(
            f"★ 该片段({fidx} 帧)不覆盖任何设备框段"
            f"(最早的设备段 {SHOTS[0][0]} 起于 f{SHOTS[0][1]})——\n"
            f"  没有可度量的对象。这不是「通过」,是「没测」。"
        )
    bad = [s for s in in_scope if mins[s][1] is None]
    if bad:
        raise SystemExit(
            f"★ 片段覆盖了 {'/'.join(bad)},但这些段一帧深色 bezel 都没检出 ——\n"
            f"  不要把它当成『无贴边』。检查 crop 参数与 DARK 阈值是否匹配当前素材。"
        )
elif missing:
    raise SystemExit(
        f"★ 以下段一帧深色 bezel 都没检出: {'/'.join(missing)}\n"
        f"  它们不在被扫描的素材里(本次共扫到 {fidx} 帧)。\n"
        f"  全片扫描请传完整成片;只分析片段请显式加 --partial。\n"
        f"  ★ 绝不把「没测到」当成「边距达标」。"
    )

# ★★ 独立复核的证伪(2026-10-07,已复验):
#    一段**纯黑**的 5250 帧成片里没有任何设备框,但深色像素铺满全屏 ⇒ 每段的
#    「边距」都被算成 **0px**,脚本仍然 **exit 0**。哨兵只能区分「没有深色行」与
#    「有深色行」,区分不了「有设备框」与「整屏都是深色」。
#    判据:**边距 0 说明深色区域贴到了画布边缘** —— 居中的设备框不可能这样。
#    0px 要读作「没检出设备框」,不能读作「贴边」。
zero_margin = [sid for sid, _, _ in SHOTS
               if mins[sid][1] is not None and mins[sid][0] <= 0]
if zero_margin:
    raise SystemExit(
        f"★ 以下段的边距测得 0px: {'/'.join(zero_margin)}\n"
        f"  深色像素贴到了画布边缘,即没有检出居中的设备框(整屏深色也会得到 0px)。\n"
        f"  ★ 不要把它读成「边距为 0 / 贴边」。"
    )

lines = [
    "=" * 76,
    "设备框边距:" + ("片段逐帧扫描(--partial)" if PARTIAL else "全片逐帧扫描"),
    "=" * 76,
    f"  成片: {MP4}",
    f"  扫描帧数: {fidx}",
    "",
    "  段    最小边距   出现在      我上一版的结论",
]
PREV = {"S3": "33/23", "S4": "23/25", "S5": "39/33", "S6": "17/21", "S7": "42/30", "S8": "29/26"}
for sid, _, _ in SHOTS:
    m, f = mins[sid]
    if f is None:
        lines.append(f"  {sid}        —     (范围外)    {PREV[sid]}(那 6 帧的实测值)")
    else:
        lines.append(f"  {sid}     {m:4}px    f{f}      {PREV[sid]}(那 6 帧的实测值)")

allmin = min(m for m, f in mins.values() if f is not None)
lines.append("")
lines.append(f"  全片最小边距: {allmin}px")
lines.append("")
lines.append("  判据回顾:")
lines.append("    · 硬约束「背景页面永不超过 1.3 倍」—— 与边距无关,另行验证")
lines.append("    · 「不贴边」我采用 ≥12px。若最小边距 < 12px,则该表述需要修正")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
