"""从成片直接量运动量(不依赖预生成的中间文件)。

★ 为什么重写:原先 `analyze-v16.py` 读的是 `out/qa4/motion-v16.txt` ——
  那是**旧一次渲染**留下的中间文件。修完来源行后重渲,那个文件就过期了,
  而文档仍引用它的数字(9.1%)。中间产物的时效性是这类问题的根源,
  所以这里直接从 mp4 量。

口径(与文档一致,便于对照):
  ffmpeg -vf "scale=320:180,tblend=all_mode=difference,signalstats,metadata=print"
  阈值 YAVG < 0.35 视为「这一帧与上一帧无可见变化」。
  ⚠ 这是 **320×180 缩放后**的度量。全分辨率复算会得到更小的静止率(实测 7.3% vs 9.1%),
    原因是缩放把亚像素运动平均掉了。引用时必须带上这个口径。
"""
import re
import subprocess
import sys
from pathlib import Path

from _timeline import FPS, RANGES as SHOTS  # 镜头区间与 FPS 的唯一真源(不再各写一份)

_DEFAULT = "marketing/promo-shotcraft/out/promo-v17.mp4"
MP4 = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".tmp/motion-fresh.txt")

THRESH, MIN_RUN = 0.35, 30


def measure(mp4: str) -> list[float]:
    # ★ `metadata=print` 默认把结果写到日志(且级别为 info);必须显式给 `:file=-`
    #   才会打到 stdout。上一版漏了它,正则一个都没匹配到 ⇒ 静默得出「静止率 0.0%」。
    #   这类「零结果看起来像完美结果」的坑记在 verify/README.md 里。
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", mp4,
         "-vf", ("scale=320:180,tblend=all_mode=difference,signalstats,"
                 "metadata=print:key=lavfi.signalstats.YAVG:file=-"),
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    vals = [float(m) for m in re.findall(r"YAVG=([\d.eE+-]+)", r.stdout + r.stderr)]
    if not vals:
        raise SystemExit(
            "未采到任何 YAVG —— 不要把它当成「静止率 0%」。"
            "检查 metadata=print 是否带了 :file=- （见本函数注释）"
        )
    return vals


def shot_of(f: int) -> str:
    for n, a, b in SHOTS:
        if a <= f < b:
            return n
    return "?"


vals = measure(MP4)
n = len(vals) + 1  # 帧差少一帧
still = sum(1 for v in vals if v < THRESH)

out = [
    "=" * 74,
    f"运动量(直接从成片量)  {MP4}",
    "=" * 74,
    "",
    f"  帧数 {n} ({n / FPS:.1f}s)",
    f"  口径 320×180 + tblend 帧差,YAVG < {THRESH} 记为静止",
    f"  **全片静止率 {100 * still / n:.1f}%**",
    "",
    "  逐段:",
]
for sid, a, b in SHOTS:
    seg = [vals[f] for f in range(a, min(b, len(vals)))]
    if not seg:
        continue
    s = sum(1 for v in seg if v < THRESH)
    out.append(f"    {sid}: 静止 {100 * s / len(seg):5.1f}%   峰值 {max(seg):6.2f}")

# 连续静止区间
runs, start = [], None
for f, v in enumerate(vals):
    is_still = v < THRESH
    if is_still and start is None:
        start = f
    if not is_still and start is not None:
        if f - start >= MIN_RUN:
            runs.append((start, f))
        start = None
if start is not None and len(vals) - start >= MIN_RUN:
    runs.append((start, len(vals)))

runs.sort(key=lambda r: r[1] - r[0], reverse=True)
out.append("")
out.append(f"  ≥1s 的静止区间({len(runs)} 个,按长度):")
for a, b in runs[:8]:
    out.append(f"    f{a:5}-{b:5}  {(b - a) / FPS:5.2f}s  {shot_of(a)}")

# 落点目录按需创建：`.tmp/` 不入版本控制，全新检出里**不存在**
# （此前直接写会抛 FileNotFoundError，脚本以 Traceback 收场而不是给出判据）。
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(out), encoding="utf-8")
print("written", OUT)
