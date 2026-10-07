"""决定性检验:声明的 cue 帧上,**渲染出的音频**是否真的有声音?

★ 为什么这才是该问的问题:
  上一版 `cue-activity.py` 问的是「cue 帧上**画面**是否在动」,得到 0.94×(与随机无异)。
  但那个问法有两个缺陷:
    ① 本片全片有连续运镜(静止率仅 9%),画面帧差基线很高,信噪比差;
    ② 有些音效本就设计为「铺垫/氛围」(riser),不必对应一个瞬时画面事件。
  真正必须先确认的是更基础的一件事:**sfx.ts 声明的 cue 与实现是否一致** ——
  即在声明的那些帧上,音频里到底有没有声音。
  如果 cue 表与实现脱钩(例如比例换算错、或段偏移没跟上),声音就会出现在别处,
  而那正是 sfx.ts 顶部注释担心的失配。

做法:比较「cue 帧的音频 RMS」与「全片随机帧的音频 RMS」。
  若 cue 表正确,应有显著提升。
"""
import re
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path("marketing/promo-shotcraft")
SFX = (ROOT / "src" / "sfx.ts").read_text(encoding="utf-8")
TL = (ROOT / "src" / "timeline.ts").read_text(encoding="utf-8")
FILM = str(ROOT / "out" / "promo-v16-nobgm.mp4")
OUT = Path(".tmp/cue-audio.txt")
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
per = len(a) // TOTAL
rms = np.array([np.sqrt((a[i * per:(i + 1) * per] ** 2).mean()) for i in range(TOTAL)])

cue_rms = np.array([rms[min(f, TOTAL - 1)] for _, _, f in cues])
all_rms = rms.copy()

lines = [
    "=" * 78,
    "cue 表与实现是否一致:声明帧上的音频能量",
    "=" * 78,
    "",
    f"  cue 条数 {len(cues)}",
    f"  全片 RMS: 中位 {np.median(all_rms):.1f}  均值 {all_rms.mean():.1f}  "
    f"非零帧占比 {100 * (all_rms > 0).mean():.1f}%",
    f"  cue 帧 RMS: 中位 {np.median(cue_rms):.1f}  均值 {cue_rms.mean():.1f}",
    "",
]
ratio = cue_rms.mean() / max(all_rms.mean(), 1e-9)
quiet_cues = int((cue_rms <= 0).sum())
lines += [
    f"  比值(cue 均值 / 全片均值): {ratio:.2f}×",
    f"  cue 帧中**完全静音**的条数: {quiet_cues}/{len(cues)}",
    "",
    "  判读:",
]
if ratio >= 3:
    lines.append(f"    ✓ cue 帧音频能量是全片均值的 {ratio:.1f} 倍 ⇒ cue 表与实现一致")
elif ratio >= 1.5:
    lines.append(f"    · cue 帧偏高({ratio:.2f}×),一致性尚可")
else:
    lines.append(f"    ★ cue 帧与全片无差别({ratio:.2f}×)⇒ cue 表可能未落在实际发声处")

if quiet_cues:
    lines += ["", f"  ★ 以下 cue 在实际音频里是静音的({quiet_cues} 条):"]
    for (sid, rr, f), v in zip(cues, cue_rms):
        if v <= 0:
            lines.append(f"    {sid} 比例 {rr:<6} f{f:<5} ({f/FPS:6.2f}s)")

# 反向检验:实际有声音的帧有多少落在 cue 附近(±3 帧)?
loud = np.where(rms > 0)[0]
near = sum(1 for f in loud if min((abs(f - c) for _, _, c in cues), default=9999) <= 3)
lines += [
    "",
    f"  反向:实际非静音帧 {len(loud)} 个,其中距最近 cue ≤3 帧的: {near} "
    f"({100 * near / max(1, len(loud)):.1f}%)",
]

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
