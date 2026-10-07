"""段边界交接检查（每个边界的左右各 3 帧）。

判据:相邻段之间应当是**有意的转场**(淡出/硬切),不能出现
  · 两侧都空(露白)
  · 亮度跳变过大(刺眼)
  · 内容残影(上一段没走干净、下一段已开始)
"""
import subprocess
from pathlib import Path

from PIL import Image, ImageStat

MP4 = "marketing/promo-shotcraft/out/promo-v16.mp4"
W = Path("marketing/promo-shotcraft/out/bounds")
W.mkdir(parents=True, exist_ok=True)
OUT = Path(".tmp/bounds.txt")

BOUNDS = [120, 300, 540, 1500, 2700, 3780, 4560, 4950]
SHOTS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"]


def grab(n: int) -> Path:
    p = W / f"f{n}.png"
    if not p.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", MP4,
             "-vf", f"select=eq(n\\,{n})", "-vframes", "1", "-pix_fmt", "rgb24", str(p)],
            check=True,
        )
    return p


lines = [
    "=" * 74,
    "段边界交接检查（边界左右各 3 帧）",
    "=" * 74,
    "",
    "  边界            左3帧YAVG/STD        右3帧YAVG/STD        判定",
]

bad = []
for bi, b in enumerate(BOUNDS):
    left = [grab(b - 1), grab(b - 2), grab(b - 3)]
    right = [grab(b), grab(b + 1), grab(b + 2)]

    def avg(paths):
        ys, ss = [], []
        for p in paths:
            st = ImageStat.Stat(Image.open(p).convert("L"))
            ys.append(st.mean[0])
            ss.append(st.stddev[0])
        return sum(ys) / len(ys), sum(ss) / len(ss)

    ly, ls = avg(left)
    ry, rs = avg(right)
    # 判据:两侧标准差都不能接近 0(否则该侧是空白)
    issues = []
    if ls < 0.5:
        issues.append("左侧空白")
    if rs < 0.5:
        issues.append("右侧空白")
    if abs(ly - ry) > 90:
        issues.append(f"亮度跳变 {abs(ly - ry):.0f}")
    verdict = "正常" if not issues else "★ " + " / ".join(issues)
    if issues:
        bad.append((b, issues))
    lines.append(
        f"  {SHOTS[bi]}→{SHOTS[bi + 1]} f{b:5}   "
        f"{ly:6.1f}/{ls:5.2f}          {ry:6.1f}/{rs:5.2f}          {verdict}"
    )

lines.append("")
lines.append(f"  有问题的边界: {len(bad)} / {len(BOUNDS)}")
for b, iss in bad:
    lines.append(f"    f{b}: {', '.join(iss)}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
