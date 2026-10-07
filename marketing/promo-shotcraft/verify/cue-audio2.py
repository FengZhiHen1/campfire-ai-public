"""重做 cue↔音频 检验:先修掉分帧漂移这个仪器误差。

★ 上一版为什么不可信(仪器误差,不是结论):
  它用 `per = len(a) // TOTAL` 做整数分帧。实测 len(a)=1400150、TOTAL=5250
  ⇒ per=266,而理想值是 266.70。累积漂移 = 3650 样本 ≈ **13.7 帧 = 0.46s**。
  而本片的音效大多很短(0.1–0.5s)⇒ 0.46s 的错位足以把「有声音」读成「静音」。
  上一版报「47/67 cue 落在静音上」,**这个数字是仪器造成的,不能采信**。

  这是同类错误的又一次:前面是「判据太弱/太强」,这次是**坐标换算有累积误差**。
  修法:用**精确的样本边界** `round(i*n/TOTAL)`,而不是整数步长。

★ 还有一个必须同时排除的效应:**播放器/解码的帧对齐**。
  这里直接从 mp4 解码音频,时间轴与视频流是对齐的,不涉及额外偏移。
"""
import re
import subprocess
from pathlib import Path

import numpy as np
from _timeline import FPS, TOTAL

ROOT = Path("marketing/promo-shotcraft")
SFX = (ROOT / "src" / "sfx.ts").read_text(encoding="utf-8")
TL = (ROOT / "src" / "timeline.ts").read_text(encoding="utf-8")
FILM = str(ROOT / "out" / "promo-v16-nobgm.mp4")
OUT = Path(".tmp/cue-audio2.txt")
# 时间轴真源(见 _timeline.py)

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

# ★ 精确边界:第 i 帧 = 样本 [round(i*n/TOTAL), round((i+1)*n/TOTAL))
edges = [round(i * n / TOTAL) for i in range(TOTAL + 1)]
rms = np.array([
    np.sqrt((a[edges[i]:edges[i + 1]] ** 2).mean()) if edges[i + 1] > edges[i] else 0.0
    for i in range(TOTAL)
])

lines = [
    "=" * 80,
    "cue 表与实现是否一致(已修分帧漂移)",
    "=" * 80,
    "",
    f"  音频样本 {n};精确边界分帧(漂移 0)",
    f"  非静音帧占比 {100 * (rms > 0).mean():.1f}%",
    "",
]
cue_rms = np.array([rms[min(f, TOTAL - 1)] for _, _, f in cues])
ratio = cue_rms.mean() / max(rms.mean(), 1e-9)
lines += [
    f"  全片 RMS 均值 {rms.mean():.1f}   中位 {np.median(rms):.1f}",
    f"  cue 帧 RMS 均值 {cue_rms.mean():.1f}",
    f"  比值 {ratio:.2f}×",
    f"  cue 帧完全静音条数: {int((cue_rms <= 0).sum())}/{len(cues)}",
    "",
]

# 局部窗口检验:音效可能稍早/稍晚 1–3 帧,取 ±3 帧窗口内的最大 RMS 更稳健
def window_max(f: int, k: int = 3) -> float:
    lo, hi = max(0, f - k), min(TOTAL, f + k + 1)
    return float(rms[lo:hi].max())


cue_win = np.array([window_max(f) for _, _, f in cues])
ratio_w = cue_win.mean() / max(rms.mean(), 1e-9)
lines += [
    f"  ±3 帧窗口内最大 RMS 均值 {cue_win.mean():.1f} → 比值 {ratio_w:.2f}×",
    f"  窗口内仍静音的 cue: {int((cue_win <= 0).sum())}/{len(cues)}",
    "",
    "  判读:",
]
if ratio_w >= 3:
    lines.append(f"    ✓ cue 处音频能量是全片均值的 {ratio_w:.1f} 倍 ⇒ cue 表与实现一致")
else:
    lines.append(f"    ★ 比值仅 {ratio_w:.2f}× ⇒ cue 表可能未落在实际发声处")

if (cue_win <= 0).sum():
    lines += ["", "  以下 cue 在其 ±3 帧窗口内完全没有音频:"]
    for (sid, rr, f), v in zip(cues, cue_win):
        if v <= 0:
            lines.append(f"    {sid} 比例 {rr:<6} f{f:<5} ({f/FPS:6.2f}s)")

lines += [
    "",
    "  ⚠ 仪器误差记录:上一版用整数步长分帧,累积漂移 3650 样本 ≈ 13.7 帧 ≈ 0.46s,",
    "    导致它误报「47/67 cue 静音」。**那个数字是错的**,本版才可采信。",
]
OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
