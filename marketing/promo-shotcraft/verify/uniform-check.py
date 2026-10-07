"""找「完全均匀帧」—— 用 PIL 直接量每帧像素标准差,不依赖 ffmpeg 的 YSTD。

为什么值得单独查:整帧只有一个颜色的画面 = 观众看到一片空白。
终检在上一版报过 6 个 std=0 帧(含 f0)。本片已修 f0 与 S2 开头,这里做全片确认。
"""
import subprocess
from pathlib import Path

from PIL import Image, ImageStat

MP4 = "marketing/promo-shotcraft/out/promo-v16.mp4"
WORK = Path("marketing/promo-shotcraft/out/uniform")
WORK.mkdir(parents=True, exist_ok=True)
OUT = Path(".tmp/uniform-check.txt")

# 逐帧抽小图(160x90)以便覆盖全片又不爆磁盘;均匀性与分辨率无关
if not (WORK / "done.flag").exists():
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", MP4,
         "-vf", "scale=160:90", "-an", str(WORK / "f%05d.png")],
        check=True,
    )
    (WORK / "done.flag").write_text("ok")

files = sorted(WORK.glob("f*.png"))
lines = [
    "=" * 74,
    "完全均匀帧检查(整帧只有一个颜色 = 空画面)",
    "=" * 74,
    f"  抽帧数: {len(files)}",
]
uniform = []
lowest = []
for p in files:
    n = int(p.stem[1:]) - 1          # ffmpeg 从 1 开始编号
    st = ImageStat.Stat(Image.open(p).convert("L"))
    sd = st.stddev[0]
    if sd < 0.5:
        uniform.append(n)
    lowest.append((sd, n))

lines.append(f"  标准差 < 0.5 的帧: {len(uniform)}")
if uniform:
    lines.append("  位置:")
    for f in uniform[:12]:
        seg = ("S1" if f < 120 else "S2" if f < 300 else "S3" if f < 540
               else "S4" if f < 1500 else "S5" if f < 2700 else "S6" if f < 3780
               else "S7" if f < 4560 else "S8" if f < 4950 else "S9")
        lines.append(f"    f{f} → {seg}")

lowest.sort()
lines.append("")
lines.append("  标准差最低的 10 帧:")
for sd, n in lowest[:10]:
    seg = ("S1" if n < 120 else "S2" if n < 300 else "S3" if n < 540
           else "S4" if n < 1500 else "S5" if n < 2700 else "S6" if n < 3780
           else "S7" if n < 4560 else "S8" if n < 4950 else "S9")
    lines.append(f"    f{n:5} (成片) {seg}  std={sd:.3f}")

lines.append("")
lines.append("  判据:std < 0.5 视为「视觉上与空白无异」。")
OUT.write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
