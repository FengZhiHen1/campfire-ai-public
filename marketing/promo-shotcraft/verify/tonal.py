"""全片明暗分布 —— 检查是否有段落过暗(观众看不清)或过亮(刺眼)。

判据:1080p 视频里,平均亮度 <40 的画面基本看不清细节;<230 以上则接近纯白。
输出逐段亮度分布,便于判断。
"""
import subprocess
from pathlib import Path
from _timeline import RANGES

MP4 = "marketing/promo-shotcraft/out/promo-v16.mp4"
OUT = Path(".tmp/tonal.txt")
W = Path("marketing/promo-shotcraft/out/tonal")
W.mkdir(parents=True, exist_ok=True)

# 镜头区间真源(见 _timeline.py)
SHOTS = RANGES
lines = [
    "=" * 74,
    "全片明暗分布（逐段，10 帧采样）",
    "=" * 74,
    "",
    "  段    最低亮度  最高亮度  均值    判定",
]

for sid, a, b in SHOTS:
    ys = []
    for k in range(10):
        f = a + (b - a) * k // 10
        p = W / f"{sid}_{f}.png"
        if not p.exists():
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", MP4,
                 "-vf", f"select=eq(n\\,{f}),scale=160:90", "-vframes", "1", str(p)],
                check=True,
            )
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", str(p), "-vf", "signalstats,metadata=print",
             "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="ignore",
        )
        import re
        m = re.search(r"YAVG=([\d.]+)", r.stderr + r.stdout)
        if m:
            ys.append(float(m.group(1)))
    if not ys:
        lines.append(f"  {sid}   (无数据)")
        continue
    lo, hi, avg = min(ys), max(ys), sum(ys) / len(ys)
    if lo < 40:
        v = "★ 有帧过暗(<40)"
    elif hi > 250:
        v = "★ 有帧近纯白"
    else:
        v = "正常"
    lines.append(f"  {sid}   {lo:6.1f}   {hi:6.1f}   {avg:5.1f}   {v}")

lines.append("")
lines.append("  说明:S2 是刻意的暗场(情绪段),其最低值低是设计意图;")
lines.append("        S1/S3-S9 的底色是暖米纸(约 245),偏高也正常。")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
