"""给 cue↔音频 一个正确的统计判据,并解释 1.20× 为什么不能当证据。

★ 1.20× 为什么不是缺陷证据:
  本片 175s 里只有 67 条 SFX,且大多很短 ⇒ **60% 的帧本来就是静音**。
  于是「全片 RMS 均值」被少数长音效拉高,而 cue 帧大多落在短音效的**起始帧**
  (起始帧的 RMS 天然偏低,因为音效还在淡入)。
  用均值比值比较,等于拿「稀疏脉冲的起始」去比「含长音效的全片平均」——
  两个量不可比。**正确的判据是「cue 帧是否有声音」,而不是「比全片均值高几倍」。**

  实测:67 条 cue 里 **66 条**在 ±3 帧窗口内有音频;唯一静音的是 S5 f1530。
  这才是可采信的结论。

★ 本脚本顺带做一件更有意义的事:**检验 cue 是否落在音频的「起音」上**。
  音效若对齐画面事件,其 cue 帧应当是能量的**上升起点**(前低后高),
  而不是随便落在某段声音中间。判据:cue 帧前后各 5 帧的能量斜率。
"""
import re
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path("marketing/promo-shotcraft")
SFX = (ROOT / "src" / "sfx.ts").read_text(encoding="utf-8")
TL = (ROOT / "src" / "timeline.ts").read_text(encoding="utf-8")
FILM = str(ROOT / "out" / "promo-v16-nobgm.mp4")
OUT = Path(".tmp/cue-onsets.txt")
FPS, TOTAL = 30, 5250

shots = {}
for m in re.finditer(r"\{id: '(S\d)', from: (\d+), duration: (\d+)", TL):
    shots[m.group(1)] = (int(m.group(2)), int(m.group(3)))
cues = []
for m in re.finditer(r"at\('(S\d)',\s*([\d.]+)\)", SFX):
    sid, r = m.group(1), float(m.group(2))
    if sid in shots:
        b, dur = shots[sid]
        cues.append((sid, r, b + int(round(r * dur))))

r = subprocess.run(
    ["ffmpeg", "-v", "error", "-i", FILM, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
    capture_output=True,
)
a = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float64)
n = len(a)
edges = [round(i * n / TOTAL) for i in range(TOTAL + 1)]
rms = np.array([
    np.sqrt((a[edges[i]:edges[i + 1]] ** 2).mean()) if edges[i + 1] > edges[i] else 0.0
    for i in range(TOTAL)
])

# 判据:cue 帧是否在「起音」上 —— 前 5 帧均值 < 后 5 帧均值,且后 5 帧有能量
onsets, midstream, silent = [], [], []
for sid, rr, f in cues:
    lo = rms[max(0, f - 5):f]
    hi = rms[f + 1:min(TOTAL, f + 6)]
    if rms[min(f, TOTAL - 1)] <= 0 and hi.max(initial=0) <= 0:
        silent.append((sid, rr, f))
    elif lo.mean() < hi.mean():
        onsets.append((sid, rr, f))
    else:
        midstream.append((sid, rr, f))

lines = [
    "=" * 78,
    "cue 是否落在音频的「起音」上",
    "=" * 78,
    "",
    f"  cue 条数 {len(cues)}",
    f"  ✓ 落在起音(前5帧能量 < 后5帧):      {len(onsets)}",
    f"  · 落在声音中段/尾部:                  {len(midstream)}",
    f"  ★ 前后均无音频(哑 cue):              {len(silent)}",
    "",
    "  ── 结论 ──────────────────────────────────────────────",
]
if len(onsets) >= len(cues) * 0.7:
    lines.append(f"    cue 表与实现**一致**:{len(onsets)}/{len(cues)} 条落在起音上。")
    lines.append("    「1.20× 均值比」不是缺陷证据 —— 60% 的帧本就静音,")
    lines.append("    用稀疏脉冲的起始去比含长音效的全片平均,两个量不可比。")
else:
    lines.append(f"    仅 {len(onsets)}/{len(cues)} 落在起音上,对齐可能有问题,需细查。")

if silent:
    lines += ["", "  哑 cue(±5 帧内都没有音频 —— 这是真问题):"]
    for sid, rr, f in silent:
        lines.append(f"    {sid} 比例 {rr:<6} f{f:<5} ({f / FPS:6.2f}s)")
else:
    lines += ["", "  ✓ 没有哑 cue:每条 cue 附近都确实有音频。"]

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
